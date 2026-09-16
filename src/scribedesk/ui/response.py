# SPDX-License-Identifier: MIT
"""Fenêtre de résultat : le texte produit, et ce qu'il a coûté en données."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..privacy import Redaction

__all__ = ["ResponseWindow"]


class ResponseWindow(QWidget):
    """Affiche la réponse au fil de son arrivée et propose la suite.

    La mention de confidentialité en bas de fenêtre n'est pas décorative : elle
    indique, pour *cette* requête, ce qui a été masqué avant l'envoi. Une
    garantie que l'utilisateur ne peut pas constater n'en est pas une.
    """

    replace_requested = Signal(str)
    """L'utilisateur veut remplacer sa sélection par ce texte."""

    regenerate_requested = Signal()
    """L'utilisateur veut relancer la même demande."""

    cancel_requested = Signal()
    """L'utilisateur interrompt la génération en cours."""

    adjustment_requested = Signal(str, str)
    """Retouche demandée : ``(consigne, texte affiché)``.

    La consigne porte sur le résultat courant et non sur la sélection
    d'origine : les passes s'enchaînent, chacune affinant la précédente.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ScribeDesk")
        self.resize(660, 480)
        self._streaming = False
        self._comparing = False
        self._drag_pos: QPoint | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self._title = QLabel("", self)
        self._title.setObjectName("title")
        layout.addWidget(self._title)

        # Volet source à gauche, résultat à droite. Le premier reste replié
        # tant qu'aucune comparaison n'est demandée : la plupart des usages —
        # corriger une phrase — n'ont rien à comparer, et un écran coupé en
        # deux pour rien coûte de la place à la lecture.
        self._split = QSplitter(Qt.Orientation.Horizontal, self)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(8)

        self._source = QTextEdit(self._split)
        self._source.setObjectName("sourcePane")
        self._source.setAcceptRichText(False)
        self._source.setReadOnly(True)
        self._source.setPlaceholderText("Texte d'origine…")
        self._source.hide()

        self._output = QTextEdit(self._split)
        self._output.setObjectName("responseOutput")
        self._output.setAcceptRichText(False)
        self._output.setPlaceholderText("La réponse s'affichera ici…")
        self._output.installEventFilter(self)

        self._split.addWidget(self._source)
        self._split.addWidget(self._output)
        layout.addWidget(self._split, stretch=1)

        # Bandeau des deux volets, masqué avec eux.
        self._pane_labels = self._build_pane_labels()
        layout.addLayout(self._pane_labels)

        self._privacy = QLabel("", self)
        self._privacy.setObjectName("privacy")
        self._privacy.setWordWrap(True)
        self._privacy.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._privacy)

        # Barre d'ajustement, juste sous le texte : c'est là que le regard se
        # trouve après lecture du résultat, et le geste suivant le plus probable
        # est de demander une retouche — pas de fermer la fenêtre.
        layout.addLayout(self._build_adjustment_row())
        layout.addLayout(self._build_buttons())

    def _build_pane_labels(self) -> QHBoxLayout:
        """Étiquettes des deux volets, affichées seulement en mode comparaison."""
        row = QHBoxLayout()
        self._source_label = QLabel("Original", self)
        self._source_label.setObjectName("muted")
        self._source_label.hide()

        self._output_label = QLabel("Résultat", self)
        self._output_label.setObjectName("muted")
        self._output_label.hide()

        row.addWidget(self._source_label, stretch=1)
        row.addWidget(self._output_label, stretch=1)
        return row

    def _build_adjustment_row(self) -> QHBoxLayout:
        """Champ de retouche : affiner sans repartir de la sélection d'origine."""
        row = QHBoxLayout()
        row.setSpacing(8)

        self._adjustment = QLineEdit(self)
        self._adjustment.setObjectName("customPrompt")
        self._adjustment.setPlaceholderText(
            "Demander un ajustement (ton, longueur, détail technique…)"
        )
        self._adjustment.setClearButtonEnabled(True)
        self._adjustment.returnPressed.connect(self._emit_adjustment)
        row.addWidget(self._adjustment, stretch=1)

        self._adjust_button = QPushButton("➤", self)
        self._adjust_button.setObjectName("sendBtn")
        self._adjust_button.setFixedWidth(46)
        self._adjust_button.setToolTip("Appliquer l'ajustement au texte affiché (Entrée)")
        self._adjust_button.clicked.connect(self._emit_adjustment)
        row.addWidget(self._adjust_button)
        return row

    def _emit_adjustment(self) -> None:
        """Transmet la consigne de retouche, si elle n'est pas vide."""
        consigne = self._adjustment.text().strip()
        if not consigne or self._streaming:
            return
        self._adjustment.clear()
        # La retouche porte sur le texte *affiché*, pas sur la sélection
        # d'origine : elle s'enchaîne donc naturellement, chaque passe
        # raffinant la précédente.
        self.adjustment_requested.emit(consigne, self._output.toPlainText())

    # -- Comparaison ------------------------------------------------------

    def set_comparison(self, source: str | None) -> None:
        """Affiche ou replie le volet du texte d'origine.

        Args:
            source: texte à comparer, ou ``None`` pour revenir en plein écran.
        """
        actif = bool(source)
        if actif:
            self._source.setPlainText(source or "")
        self._source.setVisible(actif)
        self._source_label.setVisible(actif)
        self._output_label.setVisible(actif)

        # L'état est suivi explicitement : `isVisible()` reste faux tant que la
        # fenêtre parente n'est pas à l'écran, ce qui rendrait la propriété
        # fausse au moment précis où on la consulte pour préparer l'affichage.
        self._comparing = actif

        if actif:
            moitie = max(self.width() // 2, 260)
            self._split.setSizes([moitie, moitie])
            if self.width() < 900:
                self.resize(920, max(self.height(), 520))

    @property
    def comparing(self) -> bool:
        """Vrai si le volet d'origine est affiché."""
        return self._comparing

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._cancel = QPushButton("Interrompre", self)
        self._cancel.clicked.connect(self.cancel_requested)
        self._cancel.hide()

        self._regenerate = QPushButton("Régénérer", self)
        self._regenerate.clicked.connect(self.regenerate_requested)

        self._copy = QPushButton("Copier", self)
        self._copy.clicked.connect(self._copy_to_clipboard)

        self._replace = QPushButton("Remplacer la sélection", self)
        self._replace.setObjectName("primary")
        self._replace.clicked.connect(
            lambda: self.replace_requested.emit(self._output.toPlainText())
        )

        row.addWidget(self._cancel)
        row.addWidget(self._regenerate)
        row.addStretch(1)
        row.addWidget(self._copy)
        row.addWidget(self._replace)
        return row

    # -- Cycle d'une génération -------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API Qt
        if watched is self._output and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            if (
                key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and key_event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and not self._streaming
            ):
                self.regenerate_requested.emit()
                return True
        return super().eventFilter(watched, event)

    def prompt_for_input(self, action_name: str, placeholder: str = "") -> None:
        """Prépare la fenêtre en mode saisie manuelle lorsque aucune sélection n'a été détectée."""
        self._streaming = False
        self._title.setText(action_name)
        self._output.clear()
        self._output.setPlaceholderText(
            placeholder
            or "Collez ou saisissez votre texte ici, puis cliquez sur « Lancer » (ou Ctrl+Entrée)…"
        )
        self._privacy.setText(
            "Aucun texte capturé automatiquement. "
            "Collez ou saisissez votre texte ci-dessus puis cliquez sur « Lancer »."
        )
        self._set_busy(False)
        self._regenerate.setText("Lancer")
        self._replace.setEnabled(False)
        self._copy.setEnabled(False)

        self.show()
        self.raise_()
        self.activateWindow()
        self._output.setFocus()

    def begin(self, action_name: str) -> None:
        """Prépare la fenêtre pour une nouvelle génération."""
        self._streaming = True
        self._title.setText(action_name)
        self._output.clear()
        self._output.setPlaceholderText("La réponse s'affichera ici…")
        self._privacy.setText("Envoi en cours…")
        self._set_busy(True)
        self._regenerate.setText("Régénérer")

        self.show()
        self.raise_()
        self.activateWindow()

    def append(self, chunk: str) -> None:
        """Ajoute un fragment reçu, en gardant la vue collée au bas du texte."""
        scrollbar = self._output.verticalScrollBar()
        at_bottom = scrollbar is None or scrollbar.value() >= scrollbar.maximum() - 4

        cursor = self._output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)

        # Ne suivre le texte que si l'utilisateur n'a pas remonté lui-même :
        # forcer le défilement pendant qu'il relit le début serait pénible.
        if at_bottom and scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def finish(self, note: str, *, elapsed: float | None = None) -> None:
        """Clôt la génération et affiche la mention de confidentialité."""
        self._streaming = False
        self._set_busy(False)
        self._regenerate.setText("Régénérer")
        suffix = f" · {elapsed:.1f} s" if elapsed is not None else ""
        self._privacy.setText(f"{note}{suffix}")

    def fail(self, message: str) -> None:
        """Signale un échec sans effacer ce qui a déjà été reçu."""
        self._streaming = False
        self._set_busy(False)
        self._privacy.setText(f"Échec : {message}")

    def set_text(self, text: str) -> None:
        """Remplace intégralement le contenu affiché."""
        self._output.setPlainText(text)

    def text(self) -> str:
        """Le texte actuellement affiché, modifications de l'utilisateur comprises."""
        return self._output.toPlainText()

    def describe_redaction(self, redaction: Redaction | None) -> None:
        """Affiche le détail de ce qui a été masqué avant l'envoi."""
        if redaction is None:
            self._privacy.setText("Traitement local : aucune donnée n'a quitté ce poste.")
            return
        if redaction.is_empty:
            self._privacy.setText("Aucune donnée personnelle détectée avant l'envoi.")
            return
        detail = ", ".join(f"{n} × {rule}" for rule, n in sorted(redaction.summary().items()))
        self._privacy.setText(f"Masqué avant envoi : {detail}.")

    # -- Interne ----------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._adjustment.setEnabled(not busy)
        self._adjust_button.setEnabled(not busy)
        self._cancel.setVisible(busy)
        self._regenerate.setEnabled(not busy)
        self._replace.setEnabled(not busy)
        self._copy.setEnabled(not busy)

    def _copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._output.toPlainText())
            self._copy.setText("Copié")
            self._copy.setEnabled(False)
            # Rétablir l'étiquette après un instant, pour que le retour visuel
            # soit perceptible sans bloquer l'interface.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(1200, self._reset_copy_button)

    def _reset_copy_button(self) -> None:
        self._copy.setText("Copier")
        self._copy.setEnabled(not self._streaming)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API Qt
        # Fermer la fenêtre pendant une génération doit couper la requête :
        # sinon elle continuerait de consommer du quota dans le vide.
        if self._streaming:
            self.cancel_requested.emit()
        super().closeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API Qt
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
