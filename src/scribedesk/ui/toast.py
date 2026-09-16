# SPDX-License-Identifier: MIT
"""Indicateur transitoire affiché près du curseur.

Le mode « geste unique » ne montre ni palette ni fenêtre de résultat : la
sélection est simplement remplacée quelques instants plus tard. Sans le moindre
retour visuel, l'utilisateur croit que rien ne s'est passé et appuie une
deuxième fois — déclenchant une seconde requête pendant que la première est
encore en vol.

Cette pastille comble ce silence. Elle est volontairement minuscule et sans
interaction : elle informe, elle ne demande rien.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .theme import Palette

__all__ = ["Toast"]

#: Décalage sous le curseur, assez bas pour ne pas masquer le texte sélectionné.
_OFFSET = QPoint(14, 22)

#: Durée d'affichage d'un message final, en millisecondes.
_LINGER = 2200


class Toast(QWidget):
    """Pastille flottante, sans cadre et non cliquable.

    Elle laisse passer les clics (`WA_TransparentForMouseEvents`) : apparaître
    sous le curseur ne doit jamais intercepter une action de l'utilisateur dans
    l'application qu'il est en train d'utiliser.
    """

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.ToolTip
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self._label = QLabel("", self)
        layout.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self._accent = palette.accent
        self._restyle()

    # -- Apparence --------------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._accent = palette.accent
        self._restyle()

    def _restyle(self) -> None:
        self._label.setStyleSheet(f"color: {self._palette.text}; font-size: 12px;")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - API Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 9, 9)

        fond = QColor(self._palette.surface)
        fond.setAlpha(242)
        painter.fillPath(path, fond)

        painter.setPen(QColor(self._accent))
        painter.drawPath(path)
        painter.end()

    # -- Affichage --------------------------------------------------------

    def show_busy(self, message: str) -> None:
        """Affiche un message persistant, jusqu'à `dismiss` ou `show_done`."""
        self._timer.stop()
        self._present(message, self._palette.accent)

    def show_done(self, message: str) -> None:
        """Affiche un message de réussite, puis s'efface tout seul."""
        self._present(message, self._palette.success)
        self._timer.start(_LINGER)

    def show_error(self, message: str) -> None:
        """Affiche un échec, plus longtemps : il y a quelque chose à lire."""
        self._present(message, self._palette.danger)
        self._timer.start(_LINGER * 2)

    def dismiss(self) -> None:
        """Masque immédiatement."""
        self._timer.stop()
        self.hide()

    def _present(self, message: str, accent: str) -> None:
        self._accent = accent
        self._label.setText(message)
        self.adjustSize()
        self._move_near_cursor()
        self.show()
        self.raise_()

    def _move_near_cursor(self) -> None:
        """Place la pastille sous le curseur, sans déborder de l'écran."""
        position = QCursor.pos() + _OFFSET
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover - sans écran attaché
            self.move(position)  # type: ignore[unreachable]
            return

        zone = screen.availableGeometry()
        x = min(position.x(), zone.right() - self.width() - 8)
        y = min(position.y(), zone.bottom() - self.height() - 8)
        self.move(max(zone.left() + 8, x), max(zone.top() + 8, y))
