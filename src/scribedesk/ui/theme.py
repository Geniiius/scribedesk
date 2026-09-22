# SPDX-License-Identifier: MIT
"""Palette et feuille de style.

Les couleurs sont définies une seule fois ici, puis injectées dans une feuille
de style Qt. Aucune couleur n'est écrite en dur dans les fenêtres : changer de
thème ne demande donc de toucher qu'à ce fichier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

__all__ = [
    "DARK",
    "LIGHT",
    "GradientBackground",
    "Palette",
    "apply_theme",
    "resolve_theme",
    "rgba",
    "stylesheet",
]


#: Pile de polices de l'interface. Declaree une fois : la repeter dans
#: chaque regle de style rendait les lignes illisibles et le remplacement
#: d'une police impossible sans oubli.
_FONTS: Final = (
    '"Segoe UI Variable Text", "Segoe UI", "Inter", -apple-system, '
    'BlinkMacSystemFont, "Roboto", "Helvetica Neue", Arial, sans-serif'
)


@dataclass(frozen=True, slots=True)
class Palette:
    """Jeu de couleurs complet d'un thème."""

    name: str
    background: str
    surface: str
    surface_hover: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    success: str
    warning: str
    danger: str
    gradient: tuple[str, str, str]
    """Trois arrêts du dégradé de fond, du coin haut-gauche au bas-droit."""

    tints: dict[str, str]
    """Couleurs nommées déclarées par les actions (« green », « orange »…).

    Elles sont définies par thème plutôt que fixées une fois pour toutes : un
    vert lisible sur fond clair devient criard sur fond sombre.
    """

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def tint(self, name: str) -> str:
        """Couleur d'une action, avec repli sur l'accent si le nom est inconnu."""
        return self.tints.get(name.strip().lower(), self.accent)


LIGHT: Final = Palette(
    name="light",
    background="#f6f7f9",
    surface="#ffffff",
    surface_hover="#eef1f5",
    border="#d6dae1",
    text="#1b1f24",
    text_muted="#5c6773",
    accent="#2c6bed",
    accent_text="#ffffff",
    success="#1a7f4b",
    warning="#9a6700",
    danger="#c1392b",
    gradient=("#edf2fe", "#f5f1fc", "#eaf3fc"),
    tints={
        "green": "#1a7f4b",
        "orange": "#b45309",
        "blue": "#1d4ed8",
        "yellow": "#a16207",
        "red": "#b91c1c",
        "purple": "#6d28d9",
        "grey": "#4b5563",
        "gray": "#4b5563",
    },
)

DARK: Final = Palette(
    name="dark",
    background="#111222",
    surface="#171932",
    surface_hover="#212548",
    border="#293060",
    text="#e3e6f5",
    text_muted="#6f789d",
    accent="#254ef8",
    accent_text="#ffffff",
    success="#2ebb77",
    warning="#e59834",
    danger="#e55353",
    gradient=("#0f1327", "#161b3a", "#0f1225"),
    tints={
        "green": "#34d399",
        "orange": "#fb923c",
        "blue": "#60a5fa",
        "yellow": "#fbbf24",
        "red": "#f87171",
        "purple": "#a78bfa",
        "grey": "#94a3b8",
        "gray": "#94a3b8",
    },
)


class GradientBackground(QWidget):
    """Fond dégradé aux coins arrondis, peint à la volée.

    Le projet dont ScribeDesk s'inspire obtient cet effet en affichant quatre
    images PNG — claire, sombre, et leurs variantes popup. Les peindre plutôt
    que les embarquer présente trois avantages concrets : aucune ressource
    binaire à versionner ni à licencier, un rendu net à toutes les densités
    d'écran, et un dégradé qui suit la palette au lieu d'être figé dans un
    fichier.

    Le widget se place sous les autres et ne capte pas les clics : il ne sert
    qu'à peindre.
    """

    def __init__(
        self,
        palette: Palette,
        parent: QWidget | None = None,
        *,
        radius: int = 14,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_palette(self, palette: Palette) -> None:
        """Change la palette et redessine."""
        self._palette = palette
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - API Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)

        # Coins arrondis et découpe propre
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(clip_path)

        is_dark = self._palette.is_dark

        # 1. Dégradé de fond principal fluide et profond
        bg_gradient = QLinearGradient(0.0, 0.0, w * 0.9, h)
        start, middle, end = self._palette.gradient
        bg_gradient.setColorAt(0.0, QColor(start))
        bg_gradient.setColorAt(0.50, QColor(middle))
        bg_gradient.setColorAt(1.0, QColor(end))
        painter.fillPath(clip_path, bg_gradient)

        # 2. Halo d'ambiance supérieur doux (lumière zénithale discrète)
        top_glow = QRadialGradient(w * 0.40, 0.0, max(w * 0.75, 380.0))
        if is_dark:
            top_glow.setColorAt(0.0, QColor(99, 102, 241, 35))  # Indigo lumineux
            top_glow.setColorAt(0.55, QColor(79, 70, 229, 10))
            top_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:
            top_glow.setColorAt(0.0, QColor(59, 130, 246, 22))  # Bleu ciel doux
            top_glow.setColorAt(0.60, QColor(99, 102, 241, 8))
            top_glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), top_glow)

        # 3. Vagues géométriques épurées (courbes générées harmoniques non animées)
        # Nappe 1 : vague d'arrière-plan ample et douce
        wave1_path = QPainterPath()
        wave1_path.moveTo(0.0, h * 0.62)
        wave1_path.cubicTo(
            w * 0.22,
            h * 0.48,
            w * 0.46,
            h * 0.74,
            w * 0.72,
            h * 0.58,
        )
        wave1_path.cubicTo(
            w * 0.85,
            h * 0.50,
            w * 0.94,
            h * 0.56,
            w,
            h * 0.54,
        )
        wave1_fill = QPainterPath(wave1_path)
        wave1_fill.lineTo(w, h)
        wave1_fill.lineTo(0.0, h)
        wave1_fill.closeSubpath()

        grad_wave1 = QLinearGradient(0.0, h * 0.50, w * 0.8, h)
        if is_dark:
            grad_wave1.setColorAt(0.0, QColor(79, 70, 229, 26))  # Indigo profond
            grad_wave1.setColorAt(0.65, QColor(56, 189, 248, 12))  # Cyan subtil
            grad_wave1.setColorAt(1.0, QColor(15, 23, 42, 6))
        else:
            grad_wave1.setColorAt(0.0, QColor(99, 102, 241, 20))
            grad_wave1.setColorAt(0.65, QColor(59, 130, 246, 10))
            grad_wave1.setColorAt(1.0, QColor(241, 245, 249, 4))
        painter.fillPath(wave1_fill, grad_wave1)

        # Crête lumineuse de la vague 1
        pen1_grad = QLinearGradient(0.0, 0.0, w, 0.0)
        if is_dark:
            pen1_grad.setColorAt(0.0, QColor(99, 102, 241, 0))
            pen1_grad.setColorAt(0.30, QColor(129, 140, 248, 55))
            pen1_grad.setColorAt(0.70, QColor(56, 189, 248, 45))
            pen1_grad.setColorAt(1.0, QColor(99, 102, 241, 10))
        else:
            pen1_grad.setColorAt(0.0, QColor(99, 102, 241, 0))
            pen1_grad.setColorAt(0.30, QColor(99, 102, 241, 45))
            pen1_grad.setColorAt(0.70, QColor(59, 130, 246, 40))
            pen1_grad.setColorAt(1.0, QColor(99, 102, 241, 10))
        painter.strokePath(wave1_path, QPen(QBrush(pen1_grad), 1.0))

        # Nappe 2 : vague de premier plan, fluide et rythmée
        wave2_path = QPainterPath()
        wave2_path.moveTo(0.0, h * 0.76)
        wave2_path.cubicTo(
            w * 0.28,
            h * 0.88,
            w * 0.52,
            h * 0.64,
            w * 0.78,
            h * 0.78,
        )
        wave2_path.cubicTo(
            w * 0.88,
            h * 0.84,
            w * 0.95,
            h * 0.79,
            w,
            h * 0.74,
        )
        wave2_fill = QPainterPath(wave2_path)
        wave2_fill.lineTo(w, h)
        wave2_fill.lineTo(0.0, h)
        wave2_fill.closeSubpath()

        grad_wave2 = QLinearGradient(0.0, h * 0.65, w, h)
        if is_dark:
            grad_wave2.setColorAt(0.0, QColor(56, 189, 248, 20))  # Cyan lumineux
            grad_wave2.setColorAt(0.50, QColor(99, 102, 241, 15))  # Indigo
            grad_wave2.setColorAt(1.0, QColor(14, 165, 233, 4))
        else:
            grad_wave2.setColorAt(0.0, QColor(59, 130, 246, 16))
            grad_wave2.setColorAt(0.50, QColor(147, 51, 234, 12))
            grad_wave2.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(wave2_fill, grad_wave2)

        # Crête lumineuse de la vague 2
        pen2_grad = QLinearGradient(0.0, 0.0, w, 0.0)
        if is_dark:
            pen2_grad.setColorAt(0.0, QColor(56, 189, 248, 5))
            pen2_grad.setColorAt(0.45, QColor(56, 189, 248, 70))
            pen2_grad.setColorAt(0.80, QColor(129, 140, 248, 60))
            pen2_grad.setColorAt(1.0, QColor(56, 189, 248, 15))
        else:
            pen2_grad.setColorAt(0.0, QColor(59, 130, 246, 5))
            pen2_grad.setColorAt(0.45, QColor(59, 130, 246, 60))
            pen2_grad.setColorAt(0.80, QColor(99, 102, 241, 50))
            pen2_grad.setColorAt(1.0, QColor(59, 130, 246, 15))
        painter.strokePath(wave2_path, QPen(QBrush(pen2_grad), 1.2))

        # 4. Trait filigrane aérien (écho d'onde épuré)
        echo_path = QPainterPath()
        echo_path.moveTo(0.0, h * 0.44)
        echo_path.cubicTo(
            w * 0.35,
            h * 0.32,
            w * 0.65,
            h * 0.54,
            w,
            h * 0.38,
        )
        echo_pen_grad = QLinearGradient(0.0, 0.0, w, 0.0)
        if is_dark:
            echo_pen_grad.setColorAt(0.0, QColor(147, 197, 253, 0))
            echo_pen_grad.setColorAt(0.50, QColor(165, 180, 252, 28))
            echo_pen_grad.setColorAt(1.0, QColor(147, 197, 253, 0))
        else:
            echo_pen_grad.setColorAt(0.0, QColor(59, 130, 246, 0))
            echo_pen_grad.setColorAt(0.50, QColor(99, 102, 241, 24))
            echo_pen_grad.setColorAt(1.0, QColor(59, 130, 246, 0))
        painter.strokePath(echo_path, QPen(QBrush(echo_pen_grad), 0.9))

        # 5. Filet de bordure net
        border_pen = QPen(QColor(self._palette.border))
        border_pen.setWidthF(1.0)
        painter.setPen(border_pen)
        painter.drawPath(clip_path)

        painter.end()


def resolve_theme(preference: str) -> Palette:
    """Traduit la préférence (« auto », « light », « dark », « sombre ») en palette.

    Par défaut ou en cas de valeur non reconnue, le thème sombre est retenu.
    En mode automatique, on interroge la palette de Qt plutôt que le registre
    ou une API système : Qt sait déjà lire le réglage clair/sombre de Windows
    comme de la plupart des bureaux Linux.
    """
    match preference.strip().lower():
        case "light" | "clair":
            return LIGHT
        case "dark" | "sombre":
            return DARK
        case "auto":
            return DARK if _system_prefers_dark() else LIGHT
        case _:
            return DARK


def _system_prefers_dark() -> bool:
    """Devine le réglage du système à partir de la luminosité de fond.

    `QGuiApplication.palette()` est une méthode statique : elle évite de passer
    par `QApplication.instance()`, dont le type déclaré est `QCoreApplication`
    et qui n'expose donc pas de palette.
    """
    if QApplication.instance() is None:
        return False
    window = QGuiApplication.palette().color(QPalette.ColorRole.Window)
    return bool(window.lightness() < 128)


def rgba(hex_color: str, alpha: float) -> str:
    """Convertit « #rrggbb » en « rgba(r, g, b, a) » pour une feuille de style."""
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"


def apply_theme(app: QApplication, palette: Palette) -> None:
    """Applique la palette et une typographie moderne à toute l'application."""
    font = QFont()
    # Typographie moderne et nette : Segoe UI, Inter, Roboto, sans-serif
    font.setFamilies(
        [
            "Segoe UI",
            "Inter",
            "Roboto",
            "Helvetica Neue",
            "Arial",
            "sans-serif",
        ]
    )
    font.setPointSize(10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)

    app.setPalette(_qt_palette(palette))
    app.setStyleSheet(stylesheet(palette))


def _qt_palette(palette: Palette) -> QPalette:
    """Aligne la palette native de Qt sur la nôtre.

    Nécessaire pour les éléments que la feuille de style ne couvre pas : curseur
    de saisie, sélection de texte, infobulles.
    """
    qt_palette = QPalette()
    qt_palette.setColor(QPalette.ColorRole.Window, QColor(palette.background))
    qt_palette.setColor(QPalette.ColorRole.WindowText, QColor(palette.text))
    qt_palette.setColor(QPalette.ColorRole.Base, QColor(palette.surface))
    qt_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(palette.surface_hover))
    qt_palette.setColor(QPalette.ColorRole.Text, QColor(palette.text))
    qt_palette.setColor(QPalette.ColorRole.Button, QColor(palette.surface))
    qt_palette.setColor(QPalette.ColorRole.ButtonText, QColor(palette.text))
    qt_palette.setColor(QPalette.ColorRole.Highlight, QColor(palette.accent))
    qt_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(palette.accent_text))
    qt_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette.surface))
    qt_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(palette.text))
    return qt_palette


def stylesheet(p: Palette) -> str:
    """Feuille de style Qt dérivée de la palette avec typographie soignée."""
    return f"""
    QWidget {{
        color: {p.text};
        font-family: {_FONTS};
        font-size: 13px;
    }}
    /* Le cadre ne fait plus que porter la marge : le dégradé est peint
       dessous par GradientBackground, qui dessine aussi le filet. */
    QFrame#card, QFrame#headerBar {{
        background: transparent;
        border: none;
    }}
    QLabel#title {{
        font-size: 15.5px;
        font-weight: 700;
        letter-spacing: -0.15px;
        color: {p.text};
    }}
    QLabel#contextBadge {{
        background: {rgba(p.accent, 0.16)};
        color: {p.accent};
        border: 1px solid {rgba(p.accent, 0.36)};
        border-radius: 6px;
        font-size: 11px;
        font-weight: 650;
        padding: 2px 7px;
        letter-spacing: 0.3px;
    }}
    QLabel#muted, QLabel#privacy {{
        color: {p.text_muted};
        font-size: 12px;
        font-weight: 400;
        line-height: 1.45;
    }}
    QLabel#groupHeader {{
        color: {p.text_muted};
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        padding: 6px 2px 2px 2px;
    }}
    /* Les boutons flottent sur le dégradé : un fond légèrement translucide
       les détache sans masquer la couleur qui passe derrière. */
    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px 12px;
        text-align: left;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.1px;
    }}
    QPushButton:hover {{
        background: {p.surface_hover};
        border-color: {p.accent};
    }}
    QPushButton:pressed {{
        background: {p.accent};
        color: {p.accent_text};
    }}
    QPushButton#primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: none;
        font-size: 13.5px;
        font-weight: 650;
        letter-spacing: 0.2px;
        text-align: center;
    }}
    QPushButton#primary:hover {{
        background: {p.accent};
    }}
    QPushButton#sendBtn {{
        background: {p.accent};
        color: #ffffff;
        border: none;
        border-radius: 10px;
        font-size: 15px;
        font-weight: 700;
        text-align: center;
    }}
    QPushButton#sendBtn:hover {{
        background: #3b63fa;
    }}
    QPushButton#iconTool {{
        background: transparent;
        border: none;
        padding: 4px 6px;
        border-radius: 6px;
        color: {p.text_muted};
        font-size: 14px;
        text-align: center;
    }}
    QPushButton#iconTool:hover {{
        background: {p.surface_hover};
        color: {p.text};
    }}
    QPushButton#iconTool:checked {{
        background: {p.accent};
        color: #ffffff;
        border-radius: 8px;
    }}
    QFrame#helperBanner {{
        background: {rgba(p.surface, 0.55)};
        border: 1px solid {p.border};
        border-radius: 8px;
    }}
    QFrame#actionRow, QFrame#historyRow {{
        background: {rgba(p.surface, 0.70)};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame#actionRow:hover, QFrame#historyRow:hover {{
        background: {p.surface_hover};
        border-color: {p.accent};
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QPushButton#pillOption {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 9px;
        padding: 6px 16px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.15px;
        color: {p.text_muted};
        text-align: center;
    }}
    QPushButton#pillOption:hover {{
        background: {p.surface_hover};
        border-color: {p.accent};
        color: {p.text};
    }}
    QPushButton#pillOption:checked {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {p.accent},
            stop:1 #1d40db);
        border: 1px solid {p.accent};
        padding: 6px 16px;
        color: #ffffff;
        font-weight: 600;
    }}
    QLineEdit#customPrompt {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
        padding: 8px 14px;
        font-size: 13.5px;
        font-weight: 450;
        letter-spacing: 0.1px;
        color: {p.text};
    }}
    QLineEdit#customPrompt:focus {{
        border-color: {p.accent};
    }}
    QMenu {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
        padding: 6px;
    }}
    QMenu::item {{
        background: transparent;
        padding: 8px 24px;
        border-radius: 8px;
        color: {p.text};
        font-size: 13px;
        font-weight: 450;
    }}
    QMenu::item:selected {{
        background-color: {p.accent};
        color: #ffffff;
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.border};
        margin: 4px 8px;
    }}
    QPushButton#danger {{
        color: {p.danger};
        font-weight: 600;
    }}
    QTextEdit, QPlainTextEdit, QLineEdit {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px;
        font-size: 13px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QTextEdit#responseOutput {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 12px 14px;
        font-family: {_FONTS};
        font-size: 13.5px;
        line-height: 1.6;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 5px 8px;
        font-size: 13px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        border: 1px solid {p.border};
        font-size: 13px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QListWidget, QListView, QTreeView, QTableView {{
        background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        color: {p.text};
        padding: 4px;
        outline: none;
    }}
    QListWidget::item, QListView::item {{
        padding: 5px 8px;
        border-radius: 6px;
        color: {p.text};
    }}
    QListWidget::item:hover, QListView::item:hover {{
        background-color: {p.surface_hover};
    }}
    QListWidget::item:selected, QListView::item:selected {{
        background-color: {rgba(p.accent, 0.18)};
        color: {p.text};
    }}
    QListWidget:focus, QListView:focus, QTreeView:focus, QTableView:focus {{
        border-color: {p.accent};
    }}
    QCheckBox {{
        spacing: 8px;
        font-size: 13px;
    }}
    QGroupBox {{
        border: 1px solid {p.border};
        border-radius: 10px;
        margin-top: 14px;
        padding-top: 10px;
        font-size: 12.5px;
        font-weight: 650;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {p.text_muted};
        font-size: 11.5px;
        font-weight: 700;
        letter-spacing: 0.3px;
    }}
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 10px;
        top: -1px;
    }}
    QTabBar::tab {{
        padding: 8px 14px;
        border: 1px solid transparent;
        border-radius: 8px;
        margin-right: 4px;
        color: {p.text_muted};
        font-size: 12.5px;
        font-weight: 550;
        letter-spacing: 0.1px;
    }}
    QTabBar::tab:selected {{
        background: {p.surface};
        border-color: {p.border};
        color: {p.text};
        font-weight: 650;
    }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QStatusBar {{
        color: {p.text_muted};
        font-size: 12px;
    }}
    """
