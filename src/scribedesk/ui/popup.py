# SPDX-License-Identifier: MIT
"""Fenêtre surgissante : le choix de l'action, au plus près du curseur.

La disposition est une **grille à deux colonnes** de boutons teintés, et non
une liste verticale. Ce n'est pas qu'une préférence esthétique : avec dix
actions, la liste impose de défiler et de lire chaque libellé, alors que la
grille tient d'un seul écran. La couleur et le pictogramme deviennent alors le
repère principal — on vise « le bouton vert en haut à gauche », sans relire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import paths
from ..history import History
from ..prompts import Action, ActionLibrary
from .common import ACTION_ICONS, clear_layout
from .glyphs import action_icon
from .panels import ActionEditorPanel, HistoryPanel
from .theme import GradientBackground, Palette, resolve_theme

__all__ = ["PopupWindow"]

#: Marge entre le curseur et le bord de la fenêtre.
_CURSOR_OFFSET = 12

#: Au-delà, la grille défile au lieu d'agrandir la fenêtre.
_MAX_HEIGHT = 640

#: Bornes de largeur. Deux colonnes lisibles réclament plus qu'une liste.
_MIN_WIDTH = 520
_MAX_WIDTH = 620

#: Nombre de colonnes de la grille.
_COLUMNS = 2

#: Marque suffixant les actions qui réclament des précisions.
_PARAM_MARK = " ▸"


class PillSelector(QWidget):
    """Sélecteur d'option par boutons « pilule », à la place d'un menu déroulant.

    Les choix d'une action sont peu nombreux et connus d'avance : les exposer
    tous d'un coup supprime le déroulé du menu, soit un clic et une attente en
    moins sur le trajet le plus fréquent.
    """

    def __init__(
        self,
        choices: tuple[str, ...] | list[str],
        initial: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        for choice in choices:
            btn = QPushButton(choice, self)
            btn.setObjectName("pillOption")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if choice == initial or (not initial and not self._group.buttons()):
                btn.setChecked(True)
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

    # Les deux méthodes suivantes imitent volontairement l'API de QComboBox :
    # le code appelant peut alterner entre pilules et menu déroulant sans
    # changer d'appel. D'où la casse Qt plutôt que la convention Python.

    def currentText(self) -> str:  # noqa: N802 - imite l'API QComboBox
        """Texte de l'option actuellement sélectionnée."""
        checked = self._group.checkedButton()
        return checked.text() if checked is not None else ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802 - imite l'API QComboBox
        """Définit l'option sélectionnée."""
        for btn in self._group.buttons():
            if btn.text() == text:
                btn.setChecked(True)
                break


def _rgba(hex_color: str, alpha: float) -> str:
    """Convertit « #rrggbb » en « rgba(r, g, b, a) » pour une feuille de style."""
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"


class PopupWindow(QWidget):
    """Sélecteur d'action affiché sous le curseur.

    La fenêtre est sans cadre et se ferme dès qu'elle perd le focus : elle doit
    se comporter comme un menu contextuel, pas comme une application qu'il faut
    ranger. Toute la navigation est possible au clavier, puisque l'utilisateur
    vient précisément d'y arriver par un raccourci.
    """

    submitted = Signal(object, dict)
    """Action choisie et paramètres retenus : ``(Action, dict[str, str])``."""

    custom_submitted = Signal(str)
    """Consigne libre saisie par l'utilisateur."""

    library_changed = Signal(object)
    """Émis quand la bibliothèque d'actions est modifiée."""

    history_selected = Signal(object)
    """Émis quand une entrée d'historique doit être affichée dans la fenêtre de résultat."""

    def __init__(
        self,
        library: ActionLibrary,
        history: History | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._history = history or History(paths().ensure().history_file)
        self._selection = ""
        self._pending: Action | None = None
        self._palette = resolve_theme("dark")
        self._buttons: list[tuple[QPushButton, Action]] = []
        self._current_view = "main"
        self._target_language = ""
        self._language_choices: list[str] = []
        self._drag_pos: QPoint | None = None
        self._user_moved = False

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(_MIN_WIDTH)
        self.setMaximumWidth(_MAX_WIDTH)
        self._build()

    # -- Construction -----------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Le dégradé et le dessin vectoriel statique de fond
        self._backdrop = GradientBackground(self._palette, self)
        self._backdrop.lower()

        card = QFrame(self)
        card.setObjectName("card")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 10)
        layout.setSpacing(10)

        layout.addWidget(self._build_header(card))

        self._prompt_widget = self._build_prompt_row(card)
        layout.addWidget(self._prompt_widget)

        self._actions_area = self._build_grid(card)
        layout.addWidget(self._actions_area, stretch=1)

        self._params_panel = self._build_params_panel(card)
        layout.addWidget(self._params_panel)
        self._params_panel.hide()

        self._editor_panel = ActionEditorPanel(self._library, self._palette, card)
        self._editor_panel.library_changed.connect(self.set_library)
        self._editor_panel.done.connect(lambda: self._switch_view("main"))
        layout.addWidget(self._editor_panel)
        self._editor_panel.hide()

        self._history_panel = HistoryPanel(self._history, self._palette, card)
        self._history_panel.entry_selected.connect(self.history_selected)
        layout.addWidget(self._history_panel)
        self._history_panel.hide()

        layout.addLayout(self._build_footer(card))
        # Après le pied de page seulement : c'est lui qui crée `_count`.
        self._history_panel.status.connect(self._count.setText)
        self._restyle()

    def _build_header(self, parent: QWidget) -> QWidget:
        """Bandeau de titre : identité à gauche, contexte et outils à droite."""
        bar = QFrame(parent)
        bar.setObjectName("headerBar")
        bar.setCursor(Qt.CursorShape.SizeAllCursor)
        bar.setToolTip("Cliquer et glisser pour déplacer la fenêtre")

        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        # Poignée visuelle de déplacement
        self._drag_grip = QLabel(bar)
        self._drag_grip.setObjectName("dragGrip")
        self._drag_grip.setPixmap(
            action_icon("drag", self._palette.text_muted, size=16).pixmap(16, 16)
        )
        self._drag_grip.setToolTip("Cliquer et glisser pour déplacer la fenêtre")
        self._drag_grip.setCursor(Qt.CursorShape.SizeAllCursor)
        row.addWidget(self._drag_grip)

        icon_label = QLabel(bar)
        icon_label.setPixmap(action_icon("sparkle", self._palette.accent).pixmap(18, 18))
        row.addWidget(icon_label)

        title = QLabel("Assistant", bar)
        title.setObjectName("title")
        row.addWidget(title)

        self._context = QLabel("Service Desk", bar)
        self._context.setObjectName("contextBadge")
        row.addWidget(self._context)

        row.addStretch(1)

        self._header = QLabel("", bar)
        self._header.setObjectName("muted")
        row.addWidget(self._header)

        # Outils rapides : Historique, Éditer les actions, Effacer
        self._refresh_btn = QPushButton(bar)
        self._refresh_btn.setObjectName("iconTool")
        self._refresh_btn.setCheckable(True)
        self._refresh_btn.setIcon(action_icon("history", self._palette.text_muted, size=16))
        self._refresh_btn.setToolTip("Historique")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.clicked.connect(self._toggle_history)
        row.addWidget(self._refresh_btn)

        self._edit_btn = QPushButton(bar)
        self._edit_btn.setObjectName("iconTool")
        self._edit_btn.setCheckable(True)
        self._edit_btn.setIcon(action_icon("edit-tool", self._palette.text_muted, size=16))
        self._edit_btn.setToolTip("Modifier les actions")
        self._edit_btn.setFixedSize(28, 28)
        self._edit_btn.clicked.connect(self._toggle_editor)
        row.addWidget(self._edit_btn)

        self._trash_btn = QPushButton(bar)
        self._trash_btn.setObjectName("iconTool")
        self._trash_btn.setIcon(action_icon("trash", self._palette.text_muted, size=16))
        self._trash_btn.setToolTip("Effacer")
        self._trash_btn.setFixedSize(28, 28)
        self._trash_btn.clicked.connect(self._on_trash_clicked)
        row.addWidget(self._trash_btn)

        return bar

    def _toggle_history(self) -> None:
        """Bascule entre la vue principale et la vue historique."""
        if self._current_view == "history":
            self._switch_view("main")
        else:
            self._switch_view("history")

    def _toggle_editor(self) -> None:
        """Bascule entre la vue principale et l'éditeur d'actions."""
        if self._current_view == "editor":
            self._switch_view("main")
        else:
            self._switch_view("editor")

    def _on_trash_clicked(self) -> None:
        """Efface le champ de saisie en mode normal ou vide l'historique en mode historique."""
        if self._current_view == "history":
            self._history_panel.clear_all()
        else:
            self._custom.clear()

    def _switch_view(self, view: str) -> None:
        """Change la vue active (main, params, editor, history)."""
        self._current_view = view
        self._prompt_widget.setVisible(view in ("main", "params"))
        self._actions_area.setVisible(view == "main")
        self._params_panel.setVisible(view == "params")
        self._editor_panel.setVisible(view == "editor")
        self._history_panel.setVisible(view == "history")

        self._refresh_btn.setChecked(view == "history")
        self._edit_btn.setChecked(view == "editor")
        self._restyle_tool_buttons()

        if view == "editor":
            self._editor_panel.refresh()
            self._count.setText(f"{len(self._library)} actions")
        elif view == "history":
            self._history_panel.refresh()
            self._count.setText(self._history_panel.count_label())
        else:
            self._count.setText(f"{len(self._library)} actions")

        self.adjustSize()

    def _restyle_tool_buttons(self) -> None:
        """Met à jour l'icône des outils selon leur état actif/inactif."""
        if hasattr(self, "_drag_grip"):
            self._drag_grip.setPixmap(
                action_icon("drag", self._palette.text_muted, size=16).pixmap(16, 16)
            )

        if hasattr(self, "_refresh_btn"):
            c_hist = "#ffffff" if self._refresh_btn.isChecked() else self._palette.text_muted
            self._refresh_btn.setIcon(action_icon("history", c_hist, size=16))

            c_edit = "#ffffff" if self._edit_btn.isChecked() else self._palette.text_muted
            self._edit_btn.setIcon(action_icon("edit-tool", c_edit, size=16))

            self._trash_btn.setIcon(action_icon("trash", self._palette.text_muted, size=16))

    def _build_prompt_row(self, parent: QWidget) -> QWidget:
        """Champ de consigne libre, avec son bouton d'envoi."""
        container = QWidget(parent)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._custom = QLineEdit(container)
        self._custom.setObjectName("customPrompt")
        self._custom.setPlaceholderText("Écrivez une consigne personnalisée…")
        self._custom.setFixedHeight(40)
        self._custom.returnPressed.connect(self._emit_custom)
        row.addWidget(self._custom, stretch=1)

        self._send = QPushButton("➤", container)
        self._send.setObjectName("sendBtn")
        self._send.setFixedSize(46, 40)
        self._send.clicked.connect(self._emit_custom)
        row.addWidget(self._send)
        return container

    def _build_grid(self, parent: QWidget) -> QScrollArea:
        """Grille des actions, dans une zone défilante si elle déborde."""
        area = QScrollArea(parent)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)
        area.setStyleSheet("background: transparent;")

        self._actions_host = QWidget()
        self._actions_host.setAutoFillBackground(False)
        self._grid = QGridLayout(self._actions_host)
        self._grid.setContentsMargins(0, 0, 4, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)

        self._rebuild_grid()
        area.setWidget(self._actions_host)
        return area

    def _rebuild_grid(self) -> None:
        """Reconstruit les boutons de la grille."""
        self._buttons.clear()
        clear_layout(self._grid)

        for index, action in enumerate(self._library):
            button = self._make_button(action, self._actions_host)
            self._grid.addWidget(button, index // _COLUMNS, index % _COLUMNS)
            self._buttons.append((button, action))

        for column in range(_COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _make_button(self, action: Action, parent: QWidget) -> QPushButton:
        """Bouton d'une action : pictogramme teinté, libellé, marque de paramètres."""
        label = action.name + (_PARAM_MARK if action.parameters else "")
        button = QPushButton(label, parent)
        button.setMinimumWidth(0)
        button.setMinimumHeight(44)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if action.parameters:
            button.setToolTip("Cette action demande des précisions avant de s'exécuter.")
        elif action.group:
            button.setToolTip(action.group)
        button.clicked.connect(lambda _=False, a=action: self._choose(a))
        return button

    def _build_footer(self, parent: QWidget) -> QHBoxLayout:
        """Barre d'état : actions à gauche, langue au centre, moteur à droite."""
        row = QHBoxLayout()
        self._count = QLabel(f"{len(self._library)} actions", parent)
        self._count.setObjectName("muted")
        row.addWidget(self._count)

        row.addStretch(1)

        # Sélecteur de langue de sortie. Il ne remplace aucune action : il les
        # modifie toutes. Diagnostiquer un incident en français puis livrer la
        # note en néerlandais est un geste unique, là où passer par l'action
        # « Traduction » en demanderait deux.
        self._language_button = QPushButton(parent)
        self._language_button.setObjectName("langTool")
        self._language_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._language_button.setFlat(True)
        self._language_button.clicked.connect(self._choose_language)
        row.addWidget(self._language_button)

        row.addStretch(1)

        self._engine_label = QLabel("", parent)
        self._engine_label.setObjectName("muted")
        row.addWidget(self._engine_label)

        self._refresh_language_button()
        return row

    # -- Langue de sortie -------------------------------------------------

    def target_language(self) -> str:
        """Langue imposée pour la prochaine action, ou chaîne vide."""
        return self._target_language

    def set_language_choices(self, langues: Sequence[str]) -> None:
        """Renseigne les langues proposées, depuis les préférences."""
        self._language_choices = list(langues)

    def _choose_language(self) -> None:
        """Menu discret : langue du texte, ou l'une des langues configurées."""
        menu = QMenu(self)
        defaut = menu.addAction("Langue du texte")
        defaut.setCheckable(True)
        defaut.setChecked(not self._target_language)
        defaut.triggered.connect(lambda: self._set_target_language(""))

        menu.addSeparator()
        for langue in self._language_choices:
            item = menu.addAction(langue)
            item.setCheckable(True)
            item.setChecked(langue == self._target_language)
            item.triggered.connect(lambda _=False, valeur=langue: self._set_target_language(valeur))

        menu.exec(self._language_button.mapToGlobal(self._language_button.rect().topLeft()))

    def _set_target_language(self, langue: str) -> None:
        self._target_language = langue
        self._refresh_language_button()

    def _refresh_language_button(self) -> None:
        """Discret au repos, franchement visible dès qu'une langue est imposée.

        C'est le garde-fou de ce réglage : il est persistant d'une action à
        l'autre, et l'oublier enverrait tout un ticket dans la mauvaise langue.
        Sa seule protection est d'être impossible à manquer quand il est actif.
        """
        actif = bool(self._target_language)
        teinte = self._palette.accent if actif else self._palette.text_muted

        # Un globe rend la commande identifiable sans lire l'étiquette, et
        # distingue ce bouton des boutons d'action de la grille.
        self._language_button.setIcon(action_icon("globe", teinte, 14))
        self._language_button.setIconSize(QSize(14, 14))
        self._language_button.setText(
            f" {self._target_language} " if actif else " Langue du texte "
        )
        self._language_button.setToolTip(
            f"La réponse sera rédigée en {self._target_language}."
            if actif
            else "La réponse suivra la langue du texte sélectionné. Cliquez pour en imposer une."
        )
        self._language_button.setStyleSheet(
            f"""
            QPushButton#langTool {{
                color: {teinte};
                background: {_rgba(teinte, 0.16 if actif else 0.06)};
                border: 1px solid {_rgba(teinte, 0.45 if actif else 0.22)};
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: {"600" if actif else "400"};
            }}
            QPushButton#langTool:hover {{
                background: {_rgba(teinte, 0.24)};
                border-color: {_rgba(teinte, 0.55)};
            }}
            """
        )

    def _build_params_panel(self, parent: QWidget) -> QFrame:
        """Panneau des paramètres rapides en pilules interactives."""
        panel = QFrame(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        self._params_title = QLabel("", panel)
        self._params_title.setObjectName("title")
        layout.addWidget(self._params_title)

        self._params_box = QVBoxLayout()
        self._params_box.setSpacing(10)
        layout.addLayout(self._params_box)

        buttons = QHBoxLayout()
        back = QPushButton("Retour", panel)
        back.clicked.connect(self._cancel_params)
        launch = QPushButton("Lancer", panel)
        launch.setObjectName("primary")
        launch.setDefault(True)
        launch.clicked.connect(self._emit_pending)
        buttons.addWidget(back)
        buttons.addStretch(1)
        buttons.addWidget(launch)
        layout.addLayout(buttons)

        self._param_widgets: dict[str, PillSelector] = {}
        return panel

    # -- Habillage --------------------------------------------------------

    def _restyle(self) -> None:
        """Applique la teinte de chaque action à son bouton."""
        for button, action in self._buttons:
            tint = self._palette.tint(action.color)
            icon_name = ACTION_ICONS.get(action.name, action.icon)
            button.setIcon(action_icon(icon_name, tint, size=20))
            button.setIconSize(QSize(20, 20))
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {_rgba(tint, 0.22)},
                        stop:1 {_rgba(tint, 0.10)});
                    border: 1px solid {_rgba(tint, 0.44)};
                    border-top: 1px solid {_rgba(tint, 0.68)};
                    border-radius: 12px;
                    padding: 9px 14px;
                    text-align: left;
                    font-size: 13px;
                    font-weight: 600;
                    letter-spacing: 0.15px;
                    color: {self._palette.text};
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {_rgba(tint, 0.35)},
                        stop:1 {_rgba(tint, 0.20)});
                    border: 1px solid {tint};
                    color: #ffffff;
                }}
                QPushButton:pressed {{
                    background: {_rgba(tint, 0.42)};
                    border-color: {tint};
                }}
                """
            )

        self._restyle_tool_buttons()

    def set_palette(self, palette: Palette) -> None:
        """Applique une nouvelle palette au fond et aux boutons."""
        self._palette = palette
        self._backdrop.set_palette(palette)
        self._restyle()
        self._refresh_language_button()
        # Les panneaux détiennent leur propre copie depuis qu'ils sont
        # autonomes : sans ce relais, un changement de thème les laisserait
        # aux couleurs précédentes jusqu'au prochain redémarrage.
        self._editor_panel.set_palette(palette)
        self._history_panel.set_palette(palette)

    def set_engine(self, provider: str, model: str) -> None:
        """Renseigne la barre d'état avec le moteur courant."""
        self._engine_label.setText(f"{provider} · {model}" if model else provider)

    def set_library(self, library: ActionLibrary) -> None:
        """Met à jour la bibliothèque d'actions et reconstruit la grille."""
        self._library = library
        self._rebuild_grid()
        self._restyle()
        # Sans condition sur la vue courante : l'éditeur doit être à jour même
        # fermé, sinon l'ouvrir après un changement venu des préférences —
        # activer la traduction, par exemple — afficherait l'ancienne liste.
        self._editor_panel.set_library(library)
        self._count.setText(f"{len(self._library)} actions")
        self.library_changed.emit(self._library)

    # -- Affichage --------------------------------------------------------

    def present(self, selection: str) -> None:
        """Affiche la fenêtre près du curseur, pour le texte donné."""
        self._user_moved = False
        self._selection = selection
        self._cancel_params()
        self._switch_view("main")

        if selection:
            count = len(selection)
            self._header.setText(f"{count} caractère{'s' if count > 1 else ''} sélectionné(s)")
            self._custom.setPlaceholderText("Ecrivez un prompt personnalisé")
        else:
            self._header.setText("aucune sélection")
            self._custom.setPlaceholderText("Ecrivez un prompt personnalisé")

        self._custom.clear()
        self.adjustSize()
        self._move_near_cursor()

        self.show()
        self.raise_()
        self.activateWindow()
        self._custom.setFocus()

    def present_history(self) -> None:
        """Affiche directement la palette sur le panneau d'historique."""
        self._user_moved = False
        self._selection = ""
        self._cancel_params()
        self._switch_view("history")
        self.adjustSize()
        self._move_near_cursor()

        self.show()
        self.raise_()
        self.activateWindow()

    def _move_near_cursor(self) -> None:
        """Positionne la fenêtre sans la laisser déborder de l'écran."""
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        # Les stubs déclarent primaryScreen() non optionnel ; il renvoie
        # pourtant None quand aucun écran n'est attaché.
        if screen is None:  # pragma: no cover - sans écran attaché
            self.move(cursor)  # type: ignore[unreachable]
            return

        available = screen.availableGeometry()
        height = min(self.sizeHint().height(), _MAX_HEIGHT, available.height() - 40)
        self.setFixedHeight(height)
        width = max(self.sizeHint().width(), _MIN_WIDTH)

        x = min(cursor.x() + _CURSOR_OFFSET, available.right() - width - 8)
        y = min(cursor.y() + _CURSOR_OFFSET, available.bottom() - height - 8)
        self.move(max(available.left() + 8, x), max(available.top() + 8, y))

    def _ensure_within_screen(self) -> None:
        """Garantit que la fenêtre reste entièrement dans l'écran visible."""
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover - sans écran attaché
            return  # type: ignore[unreachable]

        available = screen.availableGeometry()
        height = min(self.sizeHint().height(), _MAX_HEIGHT, available.height() - 40)
        self.setFixedHeight(height)
        width = max(self.sizeHint().width(), _MIN_WIDTH)

        x = max(available.left() + 8, min(self.x(), available.right() - width - 8))
        y = max(available.top() + 8, min(self.y(), available.bottom() - height - 8))
        self.move(x, y)

    # -- Interactions -----------------------------------------------------

    def _choose(self, action: Action) -> None:
        """Lance l'action, ou demande d'abord ses paramètres."""
        if not action.parameters:
            self.submitted.emit(action, {})
            self.hide()
            return

        self._pending = action
        self._params_title.setText(action.name)
        clear_layout(self._params_box)
        self._param_widgets.clear()

        for parameter in action.parameters:
            param_row = QVBoxLayout()
            param_row.setSpacing(3)
            label = QLabel(parameter.label, self._params_panel)
            label.setObjectName("muted")
            param_row.addWidget(label)

            selector = PillSelector(
                parameter.choices, initial=parameter.initial, parent=self._params_panel
            )
            param_row.addWidget(selector)
            self._params_box.addLayout(param_row)
            self._param_widgets[parameter.name] = selector

        self._switch_view("params")
        if not self._user_moved:
            self._move_near_cursor()
        else:
            self._ensure_within_screen()

    def _cancel_params(self) -> None:
        """Revient à la grille des actions."""
        self._pending = None
        self._switch_view("main")

    def _emit_pending(self) -> None:
        if self._pending is None:
            return
        choices: Mapping[str, str] = {
            name: selector.currentText() for name, selector in self._param_widgets.items()
        }
        action, self._pending = self._pending, None
        self.submitted.emit(action, dict(choices))
        self.hide()

    def _emit_custom(self) -> None:
        instruction = self._custom.text().strip()
        if instruction:
            self.custom_submitted.emit(instruction)
            self.hide()

    # -- Comportement de menu ---------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - API Qt
        self._backdrop.setGeometry(self.rect())
        super().resizeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - API Qt
        if event.key() == Qt.Key.Key_Escape:
            if self._current_view in ("params", "editor", "history"):
                self._switch_view("main")
            else:
                self.hide()
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        # Se refermer à la perte de focus est ce qui distingue une palette d'une
        # fenêtre — sauf si l'utilisateur vient d'ouvrir l'éditeur d'action :
        # la palette perd alors le focus au profit de sa propre boîte de
        # dialogue, et disparaître emporterait l'éditeur avec elle.
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            dialogue_ouvert = any(d.isVisible() for d in self.findChildren(QDialog))
            if not dialogue_ouvert:
                self.hide()
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            self._user_moved = True
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
