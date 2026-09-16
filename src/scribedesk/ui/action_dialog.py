# SPDX-License-Identifier: MIT
"""Dialogue de création et modification d'une action personnalisée."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..prompts import Action
from .glyphs import action_icon
from .theme import Palette


class ActionEditDialog(QDialog):
    """Formulaire modal d'ajout ou d'édition d'une action."""

    AVAILABLE_ICONS = (
        ("pencil", "Crayon / Plume (Rédaction)"),
        ("relecture", "Loupe & Coche (Correction)"),
        ("mail", "Enveloppe (Tickets / Mails)"),
        ("resume", "Document Résumé (Synthèse)"),
        ("shield-check", "Bouclier Contrôle Qualité"),
        ("badge-check", "Badge Résolution"),
        ("diagnostic", "Mallette Diagnostic"),
        ("description", "Détail / Tableau"),
        ("flash", "Éclair Génération Rapide"),
        ("resolution", "Drapeau Note de Résolution"),
    )

    AVAILABLE_COLORS = (
        ("blue", "Bleu"),
        ("green", "Vert"),
        ("orange", "Orange"),
        ("yellow", "Jaune"),
        ("purple", "Violet"),
        ("red", "Rouge"),
        ("grey", "Gris"),
    )

    def __init__(
        self,
        palette: Palette,
        action: Action | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._action = action
        self._is_new = action is None

        self.setWindowTitle("Ajouter une action" if self._is_new else "Modifier l'action")
        self.resize(520, 560)
        self._build()
        if action:
            self._load(action)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        # 1. Nom de l'action
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Ex : Traduction en anglais, Reformulation...")
        form.addRow("Nom de l'action", self._name)

        # 2. Groupe
        self._group = QLineEdit(self)
        self._group.setPlaceholderText("Ex : Rédaction, Service Desk, Traduction...")
        form.addRow("Groupe", self._group)

        # 3. Icône
        self._icon = QComboBox(self)
        for icon_id, label in self.AVAILABLE_ICONS:
            self._icon.addItem(action_icon(icon_id, self._palette.accent, size=18), label, icon_id)
        form.addRow("Icône", self._icon)

        # 4. Couleur / Teinte
        self._color = QComboBox(self)
        for color_id, label in self.AVAILABLE_COLORS:
            tint = self._palette.tint(color_id)
            self._color.addItem(action_icon("dot", tint, size=14), label, color_id)
        form.addRow("Teinte visuelle", self._color)

        # 5. Ordre d'affichage
        self._order = QSpinBox(self)
        self._order.setRange(1, 999)
        self._order.setValue(100)
        form.addRow("Ordre de tri", self._order)

        # 6. Préfixe optionnel
        self._prefix = QLineEdit(self)
        self._prefix.setPlaceholderText("Ex : Consigne préalable avant le texte...")
        form.addRow("Préfixe utilisateur", self._prefix)

        # 7. Ouvrir dans une fenêtre
        self._open_in_window = QCheckBox("Afficher le résultat dans une fenêtre dédiée", self)
        self._open_in_window.setChecked(True)
        form.addRow("", self._open_in_window)

        layout.addLayout(form)

        # 8. Consigne / Prompt système
        prompt_label = QLabel("Consigne système (Prompt envoyé au modèle) :", self)
        prompt_label.setObjectName("title")
        layout.addWidget(prompt_label)

        self._instruction = QPlainTextEdit(self)
        self._instruction.setPlaceholderText(
            "Tu es un assistant expert...\n"
            "Prends en compte les consignes suivantes pour traiter le texte de l'utilisateur."
        )
        layout.addWidget(self._instruction, stretch=1)

        # Boutons
        btn_box = QHBoxLayout()
        cancel_btn = QPushButton("Annuler", self)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Enregistrer l'action", self)
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._validate_and_save)

        btn_box.addStretch(1)
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(save_btn)
        layout.addLayout(btn_box)

    def _load(self, action: Action) -> None:
        self._name.setText(action.name)
        self._group.setText(action.group)
        self._instruction.setPlainText(action.instruction)
        self._prefix.setText(action.prefix)
        self._order.setValue(action.order)
        self._open_in_window.setChecked(action.open_in_window)

        # Trouver icône
        idx = self._icon.findData(action.icon)
        if idx >= 0:
            self._icon.setCurrentIndex(idx)

        # Trouver couleur
        idx_c = self._color.findData(action.color)
        if idx_c >= 0:
            self._color.setCurrentIndex(idx_c)

    def _validate_and_save(self) -> None:
        name = self._name.text().strip()
        instruction = self._instruction.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "Champ requis", "Veuillez indiquer un nom pour l'action.")
            self._name.setFocus()
            return
        if not instruction:
            QMessageBox.warning(self, "Champ requis", "La consigne système ne peut pas être vide.")
            self._instruction.setFocus()
            return

        self.accept()

    def build_action(self) -> Action:
        """Construit l'objet Action correspondant aux saisies."""
        return Action(
            name=self._name.text().strip(),
            instruction=self._instruction.toPlainText().strip(),
            prefix=self._prefix.text().strip(),
            group=self._group.text().strip(),
            icon=self._icon.currentData() or "pencil",
            color=self._color.currentData() or "blue",
            open_in_window=self._open_in_window.isChecked(),
            order=self._order.value(),
            parameters=self._action.parameters if self._action else (),
            source=self._action.source if self._action else None,
        )
