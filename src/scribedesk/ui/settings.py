# SPDX-License-Identifier: MIT
"""Fenêtre de préférences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, paths
from ..privacy import RULE_DESCRIPTIONS
from ..prompts import load_library
from ..providers import PROVIDERS, describe
from ..secrets import (
    KeyringUnavailable,
    delete_api_key,
    get_api_key,
    keyring_available,
    set_api_key,
)

__all__ = ["SettingsWindow"]

#: Habillage des liens d'aide, répété dans chaque description de fournisseur.
_LIEN = "color:#6366f1;font-weight:bold"


class SettingsWindow(QWidget):
    """Édition des préférences, appliquées à la validation."""

    applied = Signal(object)
    """Nouvelles préférences validées : ``Settings``."""

    test_requested = Signal(object, str)
    """Demande de test de connexion sur les préférences en cours d'édition : ``(Settings, str)``."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Préférences — ScribeDesk")
        self.resize(560, 620)
        self._settings = settings
        self._build()
        self._load(settings)

    # -- Construction -----------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        tabs = QTabWidget(self)
        tabs.addTab(self._provider_tab(), "Modèle")
        tabs.addTab(self._privacy_tab(), "Confidentialité")
        tabs.addTab(self._general_tab(), "Général")
        layout.addWidget(tabs, stretch=1)

        self._status = QLabel("", self)
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        test = QPushButton("Tester la connexion", self)
        test.clicked.connect(
            lambda: self.test_requested.emit(self.collect(), self._api_key.text().strip())
        )
        self._save_btn = QPushButton("Enregistrer", self)
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._apply)
        close_btn = QPushButton("Fermer", self)
        close_btn.clicked.connect(self.close)

        buttons.addWidget(test)
        buttons.addStretch(1)
        buttons.addWidget(self._save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _provider_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(10)

        self._provider = QComboBox(page)
        for key in PROVIDERS:
            label, _, _ = describe(key)
            self._provider.addItem(label, key)
        self._provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Fournisseur", self._provider)

        self._model = QComboBox(page)
        self._model.setEditable(True)
        form.addRow("Modèle", self._model)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit(page)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("Enregistrée dans le trousseau du système")
        self._toggle_key_btn = QPushButton("👁", page)
        self._toggle_key_btn.setFixedSize(34, 30)
        self._toggle_key_btn.setToolTip("Afficher ou masquer la clé d'API")
        self._toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self._api_key, stretch=1)
        key_row.addWidget(self._toggle_key_btn)
        form.addRow("Clé d'API", key_row)

        self._base_url = QLineEdit(page)
        self._base_url.setPlaceholderText("Laisser vide pour l'URL par défaut")
        form.addRow("URL de l'API", self._base_url)

        self._temperature = QDoubleSpinBox(page)
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setToolTip(
            "Plus la valeur est basse, plus la sortie est prévisible. "
            "0,3 convient à la correction ; 0,7 à la rédaction."
        )
        form.addRow("Température", self._temperature)

        self._provider_help = QLabel("", page)
        self._provider_help.setObjectName("muted")
        self._provider_help.setWordWrap(True)
        self._provider_help.setOpenExternalLinks(True)
        form.addRow("", self._provider_help)

        self._keyring_note = QLabel("", page)
        self._keyring_note.setObjectName("muted")
        self._keyring_note.setWordWrap(True)
        if not keyring_available():
            self._keyring_note.setText(
                "Aucun trousseau système détecté. La clé ne pourra pas être enregistrée ; "
                "utilisez la variable d'environnement SCRIBEDESK_API_KEY."
            )
        form.addRow("", self._keyring_note)
        return page

    def _privacy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        intro = QLabel(
            "Avant tout envoi à un service distant, les données personnelles "
            "détectées sont remplacées par des jetons. Les valeurs réelles sont "
            "réinsérées dans la réponse : le fournisseur ne les voit jamais, "
            "vous les retrouvez intactes.",
            page,
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._privacy_enabled = QCheckBox("Anonymiser avant envoi", page)
        self._local_exempt = QCheckBox("Ne pas anonymiser quand le modèle est local (Ollama)", page)
        self._local_exempt.setToolTip(
            "Le texte ne quitte pas le poste : l'anonymisation n'apporterait rien "
            "et peut dégrader la qualité de la réponse."
        )
        self._confirm_before_send = QCheckBox(
            "Afficher le texte anonymisé et demander confirmation", page
        )
        layout.addWidget(self._privacy_enabled)
        layout.addWidget(self._local_exempt)
        layout.addWidget(self._confirm_before_send)

        rules_box = QGroupBox("Règles de détection", page)
        rules_layout = QVBoxLayout(rules_box)
        self._rules = QListWidget(rules_box)
        for name, description in RULE_DESCRIPTIONS.items():
            item = QListWidgetItem(f"{name} — {description}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self._rules.addItem(item)
        rules_layout.addWidget(self._rules)
        layout.addWidget(rules_box, stretch=1)

        stopwords_box = QGroupBox("Sigles à ne jamais masquer", page)
        stopwords_layout = QVBoxLayout(stopwords_box)
        hint = QLabel(
            "Noms d'applications ou codes internes, séparés par des virgules. "
            "Utile si un outil maison est pris pour un nom de personne.",
            stopwords_box,
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self._stopwords = QLineEdit(stopwords_box)
        self._stopwords.setPlaceholderText("GEODE, ATLAS, SIGMA")
        stopwords_layout.addWidget(hint)
        stopwords_layout.addWidget(self._stopwords)
        layout.addWidget(stopwords_box)
        return page

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(10)

        self._hotkey = QLineEdit(page)
        self._hotkey.setPlaceholderText("ctrl+space")
        self._hotkey.setToolTip("Ouvre la palette des actions.")
        form.addRow("Raccourci global", self._hotkey)

        self._quick_hotkey = QLineEdit(page)
        self._quick_hotkey.setPlaceholderText("ctrl+alt+space")
        self._quick_hotkey.setToolTip(
            "Applique l'action par défaut et remplace la sélection, "
            "sans passer par la palette ni par une fenêtre de résultat."
        )
        form.addRow("Raccourci rapide", self._quick_hotkey)

        self._default_action = QComboBox(page)
        self._default_action.setEditable(True)
        self._default_action.setToolTip("Action déclenchée par le raccourci rapide.")
        for action in load_library(paths().actions_dir):
            self._default_action.addItem(action.name)
        form.addRow("Action par défaut", self._default_action)

        self._respect_language = QCheckBox("Répondre dans la langue du texte sélectionné", page)
        self._respect_language.setToolTip(
            "Les actions livrées sont rédigées en français et imposent le français. "
            "Sans cette option, un ticket anglais ou espagnol reviendrait traduit "
            "en français sans que vous l'ayez demandé."
        )
        form.addRow("Langue", self._respect_language)

        self._translation_enabled = QCheckBox("Afficher l'action de traduction", page)
        self._translation_enabled.setToolTip(
            "Ajoute une action « Traduction » à la palette, avec choix de la "
            "langue cible et du registre."
        )
        form.addRow("", self._translation_enabled)

        self._translation_targets = QLineEdit(page)
        self._translation_targets.setPlaceholderText("Français, Anglais, Espagnol, Néerlandais")
        self._translation_targets.setToolTip(
            "Langues proposées par l'action de traduction, séparées par des virgules."
        )
        form.addRow("Langues cibles", self._translation_targets)
        self._translation_enabled.toggled.connect(self._translation_targets.setEnabled)

        self._theme = QComboBox(page)
        for label, value in (("Automatique", "auto"), ("Clair", "light"), ("Sombre", "dark")):
            self._theme.addItem(label, value)
        form.addRow("Thème", self._theme)

        self._streaming = QCheckBox("Afficher la réponse au fil de sa génération", page)
        form.addRow("", self._streaming)

        self._history_enabled = QCheckBox("Tenir un journal local", page)
        form.addRow("", self._history_enabled)

        self._history_text = QCheckBox("Y conserver aussi les textes traités", page)
        self._history_text.setToolTip(
            "Désactivé par défaut : un poste de Service Desk traite des données "
            "de tiers, dont la conservation devrait être justifiée."
        )
        form.addRow("", self._history_text)

        self._history_max = QSpinBox(page)
        self._history_max.setRange(0, 5000)
        form.addRow("Entrées conservées", self._history_max)
        return page

    # -- Chargement et collecte -------------------------------------------

    def _load(self, settings: Settings) -> None:
        index = self._provider.findData(settings.provider.key)
        self._provider.setCurrentIndex(max(0, index))
        self._refresh_models(settings.provider.key)
        if settings.provider.model:
            self._model.setCurrentText(settings.provider.model)
        self._base_url.setText(settings.provider.base_url)
        self._temperature.setValue(settings.provider.temperature)
        self._api_key.setText(get_api_key(settings.provider.key))

        self._privacy_enabled.setChecked(settings.privacy.enabled)
        self._local_exempt.setChecked(settings.privacy.local_providers_exempt)
        self._confirm_before_send.setChecked(settings.privacy.confirm_before_send)
        self._stopwords.setText(", ".join(settings.privacy.extra_stopwords))

        active = settings.privacy.rules
        for row in range(self._rules.count()):
            item = self._rules.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            checked = active is None or name in active
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

        self._hotkey.setText(settings.hotkey)
        self._quick_hotkey.setText(settings.quick_hotkey)
        self._default_action.setCurrentText(settings.default_action)
        self._respect_language.setChecked(settings.respect_source_language)
        self._translation_enabled.setChecked(settings.translation_enabled)
        self._translation_targets.setText(", ".join(settings.translation_targets))
        self._translation_targets.setEnabled(settings.translation_enabled)
        self._theme.setCurrentIndex(max(0, self._theme.findData(settings.theme)))
        self._streaming.setChecked(settings.streaming)
        self._history_enabled.setChecked(settings.history.enabled)
        self._history_text.setChecked(settings.history.store_text)
        self._history_max.setValue(settings.history.max_entries)

    def collect(self) -> Settings:
        """Construit un objet `Settings` depuis l'état des champs."""
        settings = Settings.load()

        settings.provider.key = self._provider.currentData()
        settings.provider.model = self._model.currentText().strip()
        settings.provider.base_url = self._base_url.text().strip()
        settings.provider.temperature = self._temperature.value()

        settings.privacy.enabled = self._privacy_enabled.isChecked()
        settings.privacy.local_providers_exempt = self._local_exempt.isChecked()
        settings.privacy.confirm_before_send = self._confirm_before_send.isChecked()
        settings.privacy.extra_stopwords = tuple(
            word.strip() for word in self._stopwords.text().split(",") if word.strip()
        )
        settings.privacy.rules = self._checked_rules()

        settings.hotkey = self._hotkey.text().strip() or "ctrl+space"
        settings.quick_hotkey = self._quick_hotkey.text().strip() or "ctrl+alt+space"
        settings.default_action = self._default_action.currentText().strip()
        settings.respect_source_language = self._respect_language.isChecked()
        settings.translation_enabled = self._translation_enabled.isChecked()
        cibles = tuple(
            mot.strip() for mot in self._translation_targets.text().split(",") if mot.strip()
        )
        settings.translation_targets = cibles or Settings().translation_targets
        settings.theme = self._theme.currentData()
        settings.streaming = self._streaming.isChecked()
        settings.history.enabled = self._history_enabled.isChecked()
        settings.history.store_text = self._history_text.isChecked()
        settings.history.max_entries = self._history_max.value()
        return settings

    def _checked_rules(self) -> tuple[str, ...] | None:
        """Renvoie les règles cochées, ou `None` si elles le sont toutes.

        Le `None` n'est pas un détail : il signifie « toutes », y compris celles
        qu'une version future ajoutera. Enregistrer la liste explicite figerait
        la configuration sur le catalogue d'aujourd'hui.
        """
        selected = [
            self._rules.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._rules.count())
            if self._rules.item(row).checkState() == Qt.CheckState.Checked
        ]
        return None if len(selected) == self._rules.count() else tuple(selected)

    # -- Réactions --------------------------------------------------------

    def _provider_changed(self) -> None:
        key = self._provider.currentData()
        if not key:
            return
        self._refresh_models(key)
        self._api_key.setText(get_api_key(key))
        _, _, needs_key = describe(key)
        self._api_key.setEnabled(needs_key)

        if key == "nvidia":
            self._api_key.setPlaceholderText("Clé gratuite nvapi-... (sur build.nvidia.com)")
            self._provider_help.setText(
                "💡 <b>NVIDIA NIM</b> offre des clés gratuites avec des crédits pour tester "
                "Llama 3.3, Mistral, DeepSeek R1, Qwen...<br>"
                f"Obtenez votre clé sur <a href='https://build.nvidia.com/models' style='{_LIEN}'>"
                "build.nvidia.com/models</a>."
            )
            self._provider_help.setVisible(True)
        elif key == "groq":
            self._api_key.setPlaceholderText("gsk_...")
            self._provider_help.setText(
                "💡 <b>Groq</b> offre un accès gratuit ultra-rapide. Clé disponible sur "
                f"<a href='https://console.groq.com/keys' style='{_LIEN}'>"
                "console.groq.com</a>."
            )
            self._provider_help.setVisible(True)
        elif key == "mistral":
            self._api_key.setPlaceholderText("Clé API Mistral")
            self._provider_help.setText(
                "💡 <b>Mistral AI</b> : hébergement européen souverain. Clé disponible sur "
                f"<a href='https://console.mistral.ai' style='{_LIEN}'>"
                "console.mistral.ai</a>."
            )
            self._provider_help.setVisible(True)
        elif key == "ollama":
            self._api_key.setPlaceholderText(
                "Aucune clé nécessaire : le modèle tourne sur ce poste"
            )
            self._provider_help.setText(
                "💡 <b>Ollama</b> s'exécute sur ce poste : aucune donnée ne sort."
            )
            self._provider_help.setVisible(True)
        else:
            self._api_key.setPlaceholderText(
                "Enregistrée dans le trousseau du système"
                if needs_key
                else "Aucune clé nécessaire : le modèle tourne sur ce poste"
            )
            self._provider_help.setVisible(False)

    def _refresh_models(self, key: str) -> None:
        _, models, _ = describe(key)
        current = self._model.currentText()
        self._model.clear()
        for model in models:
            self._model.addItem(model.id)
        if current and any(m.id == current for m in models):
            self._model.setEditText(current)
        elif models:
            self._model.setCurrentIndex(0)
            self._model.setEditText(models[0].id)

    def _toggle_key_visibility(self) -> None:
        """Bascule entre affichage masqué (••••) et clair du texte de la clé."""
        if self._api_key.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_key_btn.setText("🔒")
            self._toggle_key_btn.setToolTip("Masquer la clé d'API")
        else:
            self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_key_btn.setText("👁")
            self._toggle_key_btn.setToolTip("Afficher la clé d'API")

    def _apply(self) -> None:
        settings = self.collect()

        key = self._api_key.text().strip()
        if self._api_key.isEnabled():
            if key:
                try:
                    set_api_key(settings.provider.key, key)
                except KeyringUnavailable as exc:
                    self._status.setStyleSheet("color: #e53e3e; font-weight: 600;")
                    self._status.setText(f"Clé non enregistrée : {exc}")
                    return
                except Exception as exc:
                    self._status.setStyleSheet("color: #e53e3e; font-weight: 600;")
                    self._status.setText(f"Erreur trousseau : {exc}")
                    return
            else:
                delete_api_key(settings.provider.key)

        settings.save()
        self._settings = settings
        self._status.setStyleSheet("color: #38a169; font-weight: 600;")
        self._status.setText("✓ Préférences et clé d'API enregistrées avec succès.")
        self._save_btn.setText("✓ Enregistré !")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2000, lambda: self._save_btn.setText("Enregistrer"))
        self.applied.emit(settings)

    def show_status(self, message: str) -> None:
        """Affiche un message, typiquement le résultat d'un test de connexion."""
        msg_lower = message.lower()
        if "succès" in msg_lower or "réussi" in msg_lower or "ok" in msg_lower:
            self._status.setStyleSheet("color: #38a169; font-weight: 600;")
        elif "échec" in msg_lower or "erreur" in msg_lower or "injoignable" in msg_lower:
            self._status.setStyleSheet("color: #e53e3e; font-weight: 600;")
        else:
            self._status.setStyleSheet("")
        self._status.setText(message)
