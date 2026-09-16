# SPDX-License-Identifier: MIT
"""Assemblage de l'application : raccourci, fenêtres, moteur, plateau système."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from typing import Final

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from ..config import Settings, paths
from ..engine import Engine, TransformResult
from ..history import History, HistoryEntry
from ..language import detect_language
from ..privacy import Redaction
from ..prompts import Action, ActionLibrary, load_library
from ..providers import ProviderError, RetryPolicy, build_provider, describe
from ..secrets import get_api_key
from .bridge import AsyncRunner, StreamHandle
from .desktop import HotkeyListener, capture_selection, replace_selection
from .instance import SingleInstance
from .popup import PopupWindow
from .response import ResponseWindow
from .settings import SettingsWindow
from .theme import apply_theme, resolve_theme
from .toast import Toast

__all__ = ["ScribeDeskApp", "main"]

logger = logging.getLogger(__name__)

#: Action synthétique utilisée quand l'utilisateur tape une consigne libre.
_CUSTOM_INSTRUCTION = (
    "Tu es un assistant d'écriture pour un Service Desk francophone. "
    "Applique exactement la consigne de l'utilisateur au texte fourni. "
    "Réponds uniquement par le texte transformé, sans commentaire ni préambule."
)


#: Invite des retouches demandées depuis la fenêtre de résultat.
_ADJUSTMENT_INSTRUCTION = (
    "Tu es un assistant d'écriture pour un Service Desk francophone. "
    "On te fournit un texte déjà produit et une consigne d'ajustement. "
    "Applique la consigne en conservant le sens, les faits, les noms "
    "d'applications et les références techniques. "
    "Réponds uniquement par le texte ajusté, sans commentaire ni préambule."
)


#: Délai de la sonde de démarrage. Court : il ne s'agit que de savoir si le
#: service répond, pas d'attendre une génération.
_PROBE_TIMEOUT: Final = 6.0


class _HotkeySignal(QObject):
    """Relais du fil `pynput` vers la boucle Qt.

    Le callback du raccourci s'exécute dans le fil de l'écouteur clavier.
    Toucher un widget depuis ce fil provoquerait des plantages aléatoires : le
    signal reporte donc le traitement sur la boucle d'événements de Qt.
    """

    triggered = Signal()


class ScribeDeskApp:
    """Cycle de vie complet de l'application graphique."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._locations = paths().ensure()
        self._settings = Settings.load()
        self._engine = Engine(self._settings, self._visible_library())
        self._history = History(self._locations.history_file, self._settings.history)

        self._runner = AsyncRunner()
        self._runner.start()

        self._selection = ""
        self._last_request: tuple[Action, str, dict[str, str]] | None = None
        self._active: StreamHandle | None = None
        self._started_at = 0.0
        self._redaction: Redaction | None = None

        self._popup = PopupWindow(self._engine.library, self._history)
        self._response = ResponseWindow()
        self._settings_window: SettingsWindow | None = None

        self._toast = Toast(resolve_theme(self._settings.theme))
        self._quick_busy = False

        self._hotkey_signal = _HotkeySignal()
        self._hotkey = HotkeyListener(self._settings.hotkey, self._hotkey_signal.triggered.emit)

        self._quick_signal = _HotkeySignal()
        self._quick_hotkey = HotkeyListener(
            self._settings.quick_hotkey, self._quick_signal.triggered.emit
        )

        self._wire()
        self._apply_theme()
        self._app.setWindowIcon(_app_icon())
        self._tray = self._build_tray()

    # -- Câblage ----------------------------------------------------------

    def _wire(self) -> None:
        self._hotkey_signal.triggered.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._quick_signal.triggered.connect(
            self._on_quick_hotkey, Qt.ConnectionType.QueuedConnection
        )
        self._popup.submitted.connect(self._run_action)
        self._popup.custom_submitted.connect(self._run_custom)
        self._popup.library_changed.connect(self._on_library_changed)
        self._response.replace_requested.connect(self._replace_selection)
        self._response.regenerate_requested.connect(self._regenerate)
        self._response.cancel_requested.connect(self._cancel)
        self._response.adjustment_requested.connect(self._run_adjustment)

    def _visible_library(self) -> ActionLibrary:
        """Bibliothèque restreinte aux actions dont la fonction est activée."""
        return load_library(self._locations.actions_dir).for_features(
            self._settings.enabled_features()
        )

    def _on_library_changed(self, library: ActionLibrary) -> None:
        self._engine.library = library.for_features(self._settings.enabled_features())

    def _apply_theme(self) -> None:
        palette = resolve_theme(self._settings.theme)
        apply_theme(self._app, palette)
        # La feuille de style ne couvre ni le fond dégradé ni les teintes des
        # actions, tous deux peints : il faut transmettre la palette.
        self._popup.set_palette(palette)
        self._popup.set_engine(self._engine.provider.name, self._settings.provider.model)
        self._popup.set_language_choices(self._settings.translation_targets)
        self._toast.set_palette(palette)

    def start(self) -> int:
        """Lance l'application et rend son code de sortie."""
        if self._hotkey.start():
            logger.info("Raccourci global « %s » enregistré.", self._settings.hotkey)
        else:
            logger.warning("Raccourci « %s » refusé par le système.", self._settings.hotkey)
            self._notify(
                "Raccourci indisponible",
                f"« {self._settings.hotkey} » n'a pas pu être enregistré. "
                "Ouvrez ScribeDesk depuis le plateau système, ou changez la combinaison.",
            )

        # Le raccourci rapide est un confort, pas une fonction vitale : son
        # refus se journalise mais n'alerte pas l'utilisateur, qui garde la
        # palette. Deux bulles au démarrage seraient une pour trop.
        rapide = self.default_action()
        if self._quick_hotkey.start():
            logger.info(
                "Raccourci rapide « %s » enregistré sur l'action « %s ».",
                self._settings.quick_hotkey,
                rapide.name if rapide else "(aucune)",
            )
        else:
            logger.warning(
                "Raccourci rapide « %s » refusé par le système.", self._settings.quick_hotkey
            )

        logger.info(
            "ScribeDesk prêt — %d actions, fournisseur %s, anonymisation %s.",
            len(self._engine.library),
            self._settings.provider.key,
            "active" if self._settings.redaction_applies() else "inactive",
        )
        # Différé d'un tour de boucle : le plateau système doit exister pour
        # pouvoir afficher une bulle, et l'application doit être visible avant
        # qu'on ne lui ouvre les préférences.
        QTimer.singleShot(0, self._check_configuration)

        self._app.aboutToQuit.connect(self._shutdown)
        return self._app.exec()

    # -- Mise en route ----------------------------------------------------

    def _check_configuration(self) -> None:
        """Vérifie que le moteur est utilisable, et guide l'utilisateur sinon.

        Sans ce contrôle, une installation neuve démarre en silence puis échoue
        à la première action, avec une erreur réseau que rien n'explique. Le
        premier contact avec l'outil serait un échec sans mode d'emploi.

        La vérification de configuration est synchrone et sûre ; l'accessibilité
        réelle du service est sondée en arrière-plan, pour ne pas retarder le
        démarrage d'un aller-retour réseau.
        """
        config = self._settings.provider
        _, _, cle_requise = describe(config.key)

        if cle_requise and not get_api_key(config.key):
            logger.warning("Aucune clé d'API pour %s : ouverture des préférences.", config.key)
            self._notify(
                "Configuration à compléter",
                f"Renseignez votre clé d'API {config.key} pour commencer.",
            )
            self._open_settings()
            return

        self._probe_provider()

    def _probe_provider(self) -> None:
        """Sonde le moteur en arrière-plan et signale son indisponibilité.

        La sonde utilise sa propre instance, sans réessai et avec un délai
        court. La politique de réessai du moteur courant sert à absorber une
        coupure passagère pendant un vrai appel ; ici elle ne ferait que
        retarder de plusieurs secondes un diagnostic déjà certain — un service
        arrêté ne démarre pas tout seul entre deux tentatives.
        """
        config = self._settings.provider
        sonde = build_provider(
            config.key,
            model=config.model,
            api_key=get_api_key(config.key),
            base_url=config.base_url,
            timeout=_PROBE_TIMEOUT,
        )
        sonde.retry = RetryPolicy(attempts=1)

        async def interroger() -> str:
            try:
                return await sonde.check()
            finally:
                await sonde.aclose()

        future = self._runner.run_coroutine(interroger)

        def rapporter() -> None:
            try:
                reponse = future.result(timeout=0)
            except TimeoutError:
                QTimer.singleShot(400, rapporter)
                return
            except ProviderError as exc:
                logger.warning("Moteur injoignable : %s", exc)
                self._notify("Moteur indisponible", self._conseil(exc))
            except Exception as exc:
                logger.warning("Sonde du moteur en échec : %s", exc)
            else:
                logger.info("Moteur opérationnel — réponse : %s", reponse[:60])

        QTimer.singleShot(400, rapporter)

    def _conseil(self, exc: ProviderError) -> str:
        """Traduit un échec de sonde en consigne actionnable."""
        if self._settings.provider.key == "ollama":
            return (
                "Ollama ne répond pas sur ce poste. Démarrez-le, ou choisissez "
                "un fournisseur en ligne dans les préférences."
            )
        return f"{exc} — vérifiez la clé et le modèle dans les préférences."

    def _shutdown(self) -> None:
        # Tracer l'arrêt demandé est ce qui permet, en relisant le journal, de
        # distinguer une fermeture volontaire d'une disparition inexpliquée.
        logger.info("Arrêt demandé — fermeture des raccourcis et de la boucle réseau.")
        self._hotkey.stop()
        self._quick_hotkey.stop()
        self._runner.stop()
        logger.info("ScribeDesk arrêté proprement.")

    # -- Plateau système --------------------------------------------------

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(_app_icon(), self._app)
        tray.setToolTip(f"ScribeDesk — {self._settings.hotkey}")

        menu = QMenu()

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        self._paused = False
        pause_action = QAction("Pause", menu)
        pause_action.triggered.connect(self._toggle_pause)
        self._pause_action = pause_action
        menu.addAction(pause_action)

        about_action = QAction("About", menu)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)

        menu.addSeparator()
        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self._app.quit)
        menu.addAction(exit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        return tray

    def _toggle_pause(self) -> None:
        """Suspend ou rétablit **les deux** raccourcis globaux.

        Mettre en pause n'a de sens que si plus rien ne se déclenche : oublier
        le raccourci rapide laisserait l'outil réécrire la sélection alors que
        l'utilisateur le croit désactivé — précisément le cas où il vient de le
        suspendre pour taper autre chose.
        """
        self._paused = not getattr(self, "_paused", False)
        if self._paused:
            self._hotkey.stop()
            self._quick_hotkey.stop()
            self._pause_action.setText("Reprendre")
            logger.info("ScribeDesk mis en pause — raccourcis désactivés.")
        else:
            self._hotkey.start()
            self._quick_hotkey.start()
            self._pause_action.setText("Pause")
            logger.info("ScribeDesk réactivé — raccourcis rétablis.")

    def _show_about(self) -> None:
        modele = self._settings.provider.model or "défaut"
        anonymisation = "active" if self._settings.redaction_applies() else "inactive"
        QMessageBox.about(
            self._response,
            "À propos de ScribeDesk",
            "<h3>ScribeDesk</h3>"
            "<p>Assistant d'écriture pour Service Desk.</p>"
            f"<p><b>Raccourci :</b> {self._settings.hotkey}<br/>"
            f"<b>Moteur actif :</b> {self._engine.provider.name} ({modele})<br/>"
            f"<b>Anonymisation :</b> {anonymisation}.</p>",
        )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_hotkey()

    def _notify(self, title: str, message: str) -> None:
        tray = getattr(self, "_tray", None)
        if tray is not None and QSystemTrayIcon.supportsMessages():
            tray.showMessage(title, message, _app_icon())
        else:
            logger.warning("%s — %s", title, message)

    # -- Déclenchement ----------------------------------------------------

    def _on_hotkey(self) -> None:
        """Capture la sélection puis ouvre le sélecteur d'action."""
        # Laisser retomber les touches du raccourci avant de simuler Ctrl+C :
        # sans ce délai, le modificateur encore enfoncé fausse la combinaison.
        QTimer.singleShot(180, self._present_popup)

    # -- Geste unique -----------------------------------------------------

    def default_action(self) -> Action | None:
        """Action déclenchée par le raccourci rapide.

        Un repli sur la première action de la bibliothèque évite que l'outil
        devienne muet si le nom configuré a été renommé ou traduit.
        """
        found = self._engine.library.get(self._settings.default_action)
        if found is not None:
            return found
        return self._engine.library[0] if len(self._engine.library) else None

    def _on_quick_hotkey(self) -> None:
        """Applique l'action par défaut et remplace la sélection, sans fenêtre."""
        # Même délai que pour la palette : les touches du raccourci doivent
        # être relâchées avant de simuler Ctrl+C.
        QTimer.singleShot(180, self._run_quick)

    def _run_quick(self) -> None:
        if self._quick_busy:
            # Sans ce verrou, un second appui pendant l'attente lancerait une
            # requête concurrente et les deux collages se marcheraient dessus.
            logger.info("Geste rapide ignoré : une correction est déjà en cours.")
            return

        action = self.default_action()
        if action is None:
            self._toast.show_error("Aucune action disponible.")
            return

        text = capture_selection()
        if not text:
            clipboard = QGuiApplication.clipboard()
            clip_text = clipboard.text().strip() if clipboard else ""
            if clip_text and not clip_text.startswith("\x00scribedesk\x00"):
                text = clip_text

        if not text:
            self._toast.show_error("Sélectionnez d'abord du texte.")
            return

        self._quick_busy = True
        self._selection = text
        self._last_request = (action, text, {})
        self._engine.settings = self._settings
        started = time.perf_counter()

        try:
            _, redaction = self._engine.prepare(action, text, {})
        except Exception as exc:
            self._quick_busy = False
            self._toast.show_error(str(exc))
            return

        self._toast.show_busy(f"{action.name}…")

        handle = self._runner.run_stream(lambda: self._engine.stream(action, text, {}), self._toast)
        fragments: list[str] = []
        handle.chunk.connect(fragments.append)
        handle.finished.connect(
            lambda complet: self._quick_finished(action, text, complet, redaction, started)
        )
        handle.failed.connect(self._quick_failed)

    def _quick_finished(
        self,
        action: Action,
        source: str,
        produced: str,
        redaction: Redaction | None,
        started: float,
    ) -> None:
        """Colle le résultat à la place de la sélection et journalise."""
        self._quick_busy = False
        elapsed = time.perf_counter() - started

        if not produced.strip():
            self._toast.show_error("Le modèle n'a rien renvoyé.")
            return

        self._toast.dismiss()
        if replace_selection(produced):
            masque = len(redaction.mapping) if redaction else 0
            detail = f" · {masque} masqué(s)" if masque else ""
            self._toast.show_done(f"{action.name} appliqué ({elapsed:.1f} s){detail}")
        else:
            self._toast.show_done("Copié dans le presse-papiers — collez avec Ctrl+V.")

        self._journalise(action, source, produced, redaction, elapsed)

    def _quick_failed(self, message: str) -> None:
        self._quick_busy = False
        self._toast.show_error(message)

    def _present_popup(self) -> None:
        self._selection = capture_selection()
        self._popup.present(self._selection)

    def present_popup(self) -> None:
        """Ouvre la palette — point d'entrée public.

        Appelé par la garde d'instance unique quand un second lancement réveille
        celui-ci. Le délai reproduit celui du raccourci : il laisse le temps à la
        fenêtre précédente de reprendre le focus avant la copie simulée.
        """
        QTimer.singleShot(180, self._present_popup)

    # -- Exécution --------------------------------------------------------

    def _run_action(self, action: Action, choices: Mapping[str, str]) -> None:
        text = self._selection
        if not text:
            # 1. Vérifier si un texte a été saisi dans le champ libre du sélecteur
            custom_input = self._popup._custom.text().strip()
            if custom_input:
                text = custom_input
            else:
                # 2. Vérifier si le presse-papiers contient du texte
                clipboard = QGuiApplication.clipboard()
                clip_text = clipboard.text().strip() if clipboard else ""
                if clip_text and not clip_text.startswith("\x00scribedesk\x00"):
                    text = clip_text

        if not text:
            # 3. Ouvrir la fenêtre de réponse en mode saisie plutôt que d'émettre
            # une notification bloquante.
            self._last_request = (action, "", dict(choices))
            self._response.prompt_for_input(action.name)
            return

        self._last_request = (action, text, dict(choices))
        self._launch(action, text, dict(choices), self._popup.target_language())

    def _run_custom(self, instruction: str) -> None:
        """Exécute une consigne libre, avec ou sans texte sélectionné."""
        action = Action(name=instruction[:60], instruction=_CUSTOM_INSTRUCTION)
        body = (
            f"Consigne : {instruction}\n\nTexte :\n{self._selection}"
            if self._selection
            else f"Consigne : {instruction}"
        )
        self._last_request = (action, body, {})
        self._launch(action, body, {})

    def _comparison_source(
        self,
        action: Action,
        text: str,
        target_language: str,
        choices: Mapping[str, str] | None = None,
    ) -> str | None:
        """Texte à afficher en vis-à-vis, ou ``None`` pour un volet unique.

        La comparaison n'a d'intérêt que si la sortie **change de langue**.
        Demander du français sur un texte déjà français affichait deux volets
        quasi identiques — la correction à gauche, l'original à droite — ce qui
        occupe l'écran sans rien apprendre.

        La cible peut venir de deux endroits : le sélecteur de la palette, ou le
        paramètre propre à l'action de traduction. Les deux sont considérés.
        """
        cible = target_language.strip()
        if not cible and choices:
            cible = str(choices.get("langue_cible", "")).strip()
        if not cible:
            return None

        detectee = detect_language(text)
        # Langue indéterminée : on ne peut pas exclure une traduction, et un
        # volet de trop coûte moins cher qu'une comparaison manquante.
        if detectee and detectee.name.casefold() == cible.casefold():
            return None
        return text

    def _run_adjustment(self, consigne: str, texte: str) -> None:
        """Applique une retouche au résultat affiché.

        La consigne porte sur le texte courant et non sur la sélection
        d'origine : les passes s'enchaînent — « plus court », puis « plus
        formel » — sans repartir de zéro ni rouvrir la palette.

        Le texte affiché contient les valeurs réelles, restaurées après le
        premier appel. Il repasse donc par le moteur, donc par une nouvelle
        anonymisation : la retouche ne crée aucune fuite.
        """
        if not texte.strip():
            return
        action = Action(
            name=f"Ajustement : {consigne[:48]}",
            instruction=_ADJUSTMENT_INSTRUCTION,
        )
        corps = f"Consigne : {consigne}\n\nTexte :\n{texte}"
        self._last_request = (action, corps, {})
        self._launch(action, corps, {}, self._popup.target_language())

    def _regenerate(self) -> None:
        if self._last_request is not None:
            action, old_text, choices = self._last_request
            content = self._response.text().strip()
            text_to_use = content if content else old_text
            if not text_to_use:
                self._response.fail("Veuillez saisir ou coller votre texte avant de lancer.")
                return
            self._last_request = (action, text_to_use, choices)
            self._launch(action, text_to_use, choices)

    def _launch(
        self,
        action: Action,
        text: str,
        choices: dict[str, str],
        target_language: str = "",
    ) -> None:
        """Démarre la génération et branche la fenêtre de résultat dessus."""
        self._cancel()
        self._engine.settings = self._settings
        self._started_at = time.perf_counter()

        try:
            _, self._redaction = self._engine.prepare(action, text, choices, target_language)
        except Exception as exc:
            self._response.begin(action.name)
            self._response.fail(str(exc))
            return

        if self._settings.privacy.confirm_before_send and not self._confirm(action):
            return

        self._response.begin(action.name)
        self._response.set_comparison(
            self._comparison_source(action, text, target_language, choices)
        )
        self._response.describe_redaction(self._redaction)

        handle = self._runner.run_stream(
            lambda: self._engine.stream(action, text, choices, target_language),
            self._response,
        )
        handle.chunk.connect(self._response.append)
        handle.finished.connect(lambda full: self._on_finished(action, text, full))
        handle.failed.connect(self._on_failed)
        self._active = handle

    def _confirm(self, action: Action) -> bool:
        """Montre ce qui va partir et attend l'accord de l'utilisateur."""
        if self._redaction is None:
            body = "Le traitement est local : aucune donnée ne quitte ce poste."
        elif self._redaction.is_empty:
            body = "Aucune donnée personnelle n'a été détectée. Le texte part tel quel."
        else:
            detail = "\n".join(
                f"  {token} ← {original}" for token, original in self._redaction.mapping.items()
            )
            body = f"{len(self._redaction.mapping)} valeur(s) seront masquées :\n\n{detail}"

        answer = QMessageBox.question(
            self._response,
            f"Envoyer — {action.name}",
            body,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        return answer == QMessageBox.StandardButton.Ok

    def _cancel(self) -> None:
        if self._active is not None:
            self._active.cancel()
            self._active = None

    # -- Fin de génération ------------------------------------------------

    def _on_finished(self, action: Action, source: str, full_text: str) -> None:
        elapsed = time.perf_counter() - self._started_at
        self._active = None

        note = _privacy_note(self._redaction)
        self._response.finish(note, elapsed=elapsed)

        self._journalise(action, source, full_text, self._redaction, elapsed)

    def _journalise(
        self,
        action: Action,
        source: str,
        produced: str,
        redaction: Redaction | None,
        elapsed: float,
    ) -> None:
        """Journalise une transformation, par la fabrique commune à la CLI.

        Recopier les champs à la main — ce que faisaient les deux appelants —
        laissait `local`, `rules` et `redaction_active` à leur valeur par
        défaut. Ce sont précisément les trois que lit ``scribedesk audit`` :
        chaque passage par l'interface était donc compté comme un envoi sans
        anonymisation. Un seul chemin de construction supprime la question.
        """
        self._history.config = self._settings.history
        self._history.append(
            HistoryEntry.from_result(
                TransformResult(
                    text=produced,
                    action=action.name,
                    provider=self._engine.provider.name,
                    model=self._settings.provider.model,
                    elapsed=elapsed,
                    redaction=redaction,
                    local=self._engine.provider.is_local,
                ),
                source,
                store_text=self._settings.history.store_text,
            )
        )

    def _on_failed(self, message: str) -> None:
        self._active = None
        self._response.fail(message)

    def _replace_selection(self, text: str) -> None:
        """Remet le texte produit à la place de la sélection d'origine."""
        self._response.hide()
        # Laisser le temps à la fenêtre précédente de reprendre le focus, sinon
        # le collage atterrit dans le vide.
        QTimer.singleShot(180, lambda: self._do_replace(text))

    def _do_replace(self, text: str) -> None:
        if not replace_selection(text):
            self._notify(
                "Collage impossible",
                "Le texte a été placé dans le presse-papiers ; collez-le manuellement.",
            )

    # -- Préférences ------------------------------------------------------

    def _open_settings(self) -> None:
        if self._settings_window is None:
            window = SettingsWindow(self._settings)
            window.applied.connect(self._on_settings_applied)
            window.test_requested.connect(self._test_connection)
            self._settings_window = window
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_settings_applied(self, settings: Settings) -> None:
        previous_hotkey = self._settings.hotkey
        previous_quick = self._settings.quick_hotkey
        self._settings = settings
        self._engine.settings = settings
        self._engine.invalidate()

        # La palette construit sa grille une fois pour toutes : sans cet appel,
        # activer une fonction optionnelle — la traduction, par exemple —
        # ajouterait l'action au moteur mais pas à l'écran. L'utilisateur
        # conclurait que le réglage ne fonctionne pas.
        bibliotheque = self._visible_library()
        self._engine.library = bibliotheque
        self._popup.set_library(bibliotheque)

        self._history.config = settings.history
        self._apply_theme()

        if settings.hotkey != previous_hotkey and not self._hotkey.rebind(settings.hotkey):
            self._notify(
                "Raccourci indisponible",
                f"« {settings.hotkey} » est refusé par le système ; l'ancien reste actif.",
            )
        if settings.quick_hotkey != previous_quick and not self._quick_hotkey.rebind(
            settings.quick_hotkey
        ):
            self._notify(
                "Raccourci rapide indisponible",
                f"« {settings.quick_hotkey} » est refusé par le système ; l'ancien reste actif.",
            )
        self._tray.setToolTip(f"ScribeDesk — {settings.hotkey}")

    def _test_connection(self, settings: Settings, candidate_key: str = "") -> None:
        """Vérifie la configuration en cours d'édition, sans l'enregistrer."""
        window = self._settings_window
        if window is None:
            return
        window.show_status("Test en cours…")

        api_key = candidate_key or get_api_key(settings.provider.key)
        probe = build_provider(
            settings.provider.key,
            model=settings.provider.model,
            api_key=api_key,
            base_url=settings.provider.base_url,
            timeout=_PROBE_TIMEOUT,
        )
        probe.retry = RetryPolicy(attempts=1)

        async def interroger() -> str:
            try:
                return await probe.check()
            finally:
                await probe.aclose()

        future = self._runner.run_coroutine(interroger)

        def report() -> None:
            try:
                reply = future.result(timeout=0)
            except TimeoutError:
                QTimer.singleShot(200, report)
                return
            except ProviderError as exc:
                window.show_status(f"Échec : {exc}")
            except Exception as exc:
                window.show_status(f"Échec : {exc}")
            else:
                window.show_status(f"Connexion établie avec succès. Réponse du modèle : {reply}")

        QTimer.singleShot(200, report)


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------


def _privacy_note(redaction: Redaction | None) -> str:
    if redaction is None:
        return "Traitement local : aucune donnée n'a quitté ce poste."
    if redaction.is_empty:
        return "Aucune donnée personnelle détectée avant l'envoi."
    detail = ", ".join(f"{n} × {rule}" for rule, n in sorted(redaction.summary().items()))
    return f"Masqué avant envoi : {detail}."


def _app_icon() -> QIcon:
    """Icône de l'application, peinte à l'exécution.

    Aucun fichier n'est lu : charger une image depuis le dépôt donnerait une
    icône à qui travaille sur les sources, et une autre à qui installe la roue,
    puisque celle-ci n'embarque que ``src/scribedesk``. Un seul chemin de code,
    donc un seul résultat.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.darkCyan)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(Qt.GlobalColor.white)
    font = painter.font()
    font.setPointSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    painter.end()
    return QIcon(pixmap)


def _configure_logging() -> None:
    """Journalise à la fois sur la sortie d'erreur et dans un fichier.

    Lancée depuis un raccourci ou l'icône du plateau, l'application n'a pas de
    terminal : tout ce qui part sur stderr est perdu. Sans trace sur disque, un
    arrêt inattendu est indistinguable d'un arrêt demandé — on ne peut ni
    diagnostiquer, ni même savoir qu'il y a eu un incident.

    Le fichier est cyclique et borné : un journal qui grossit sans fin dans le
    profil de l'utilisateur finirait par poser son propre problème.
    """
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        destination = paths().ensure().log_file
        file_handler = RotatingFileHandler(
            destination, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - profil en lecture seule
        root.warning("Journal fichier indisponible : %s", exc)
        return

    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def main() -> int:
    """Point d'entrée de la commande ``scribedesk-gui``."""
    _configure_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("ScribeDesk")
    app.setApplicationDisplayName("ScribeDesk")
    # L'outil vit dans le plateau système : fermer une fenêtre ne doit pas
    # terminer le processus, sinon le raccourci global cesserait de répondre.
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.warning("Aucun plateau système : l'icône ne sera pas affichée.")

    # Deux instances enregistreraient les mêmes raccourcis globaux, avec un
    # comportement indéterminé. Le second lancement réveille donc la première
    # au lieu d'en démarrer une autre.
    garde = SingleInstance()
    if not garde.try_acquire():
        logger.info("ScribeDesk tourne déjà : la palette a été demandée, ce lancement s'arrête.")
        return 0

    scribedesk = ScribeDeskApp(app)
    garde.activated.connect(scribedesk.present_popup, Qt.ConnectionType.QueuedConnection)
    app.aboutToQuit.connect(garde.release)
    return scribedesk.start()
