# SPDX-License-Identifier: MIT
"""Les deux panneaux secondaires de la palette : éditer, et relire.

Ils vivaient dans `PopupWindow`, qui atteignait mille lignes et quarante-neuf
méthodes pour trois responsabilités sans rapport : choisir une action, gérer
des fichiers d'action, consulter un journal. Les séparer n'est pas qu'une
question de taille — c'est ce qui permet de les éprouver isolément.

Le contrat est volontairement à sens unique : un panneau **ne connaît pas** la
palette qui l'héberge. Il signale ce qu'il a fait, et l'hôte décide. Sans quoi
l'extraction n'aurait déplacé le couplage qu'à un appel de distance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import paths
from ..history import History
from ..prompts import (
    Action,
    ActionLibrary,
    delete_user_action,
    dump_action,
    load_library,
    parse_action,
    restore_default_actions,
    save_user_action,
)
from .action_dialog import ActionEditDialog
from .common import ACTION_ICONS, ClickableFrame, clear_layout
from .glyphs import action_icon
from .theme import Palette


def _scroll_area(parent: QWidget) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    """Zone défilante et son conteneur, réglés à l'identique pour les deux panneaux.

    Les bornes de hauteur sont ce qui empêche la palette de s'étirer jusqu'au
    bas de l'écran quand la liste s'allonge.
    """
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("background: transparent;")
    scroll.setMinimumHeight(240)
    scroll.setMaximumHeight(360)

    container = QWidget()
    container.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 4, 4, 4)
    layout.setSpacing(6)
    scroll.setWidget(container)
    return scroll, container, layout


def _tool_button(
    parent: QWidget, glyph: str, couleur: str, infobulle: str, taille: int
) -> QPushButton:
    """Bouton d'outil carré, tel qu'utilisé dans les deux barres."""
    bouton = QPushButton(parent)
    bouton.setObjectName("iconTool")
    bouton.setIcon(action_icon(glyph, couleur, size=taille))
    bouton.setToolTip(infobulle)
    bouton.setFixedSize(28, 28)
    return bouton


def _actions_dir() -> Path:
    """Dossier des actions personnelles, créé au besoin."""
    return paths().ensure().actions_dir


# --------------------------------------------------------------------------
# Éditeur d'actions
# --------------------------------------------------------------------------


class ActionEditorPanel(QWidget):
    """Création, modification, réordonnancement et import/export des actions.

    Toute opération qui touche le disque se termine par `library_changed` :
    c'est l'hôte qui relit la bibliothèque et reconstruit sa grille. Le
    panneau n'a donc jamais besoin d'une référence vers lui.
    """

    library_changed = Signal(ActionLibrary)
    done = Signal()

    def __init__(self, library: ActionLibrary, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self._library = library
        self._palette = palette
        self._build()

    # -- Construction -----------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        barre = QHBoxLayout()
        barre.setSpacing(8)

        self._back_btn = _tool_button(
            self, "check-circle", self._palette.accent, "Terminer la modification", 18
        )
        self._back_btn.clicked.connect(self.done)
        barre.addWidget(self._back_btn)

        self._title = QLabel("Modifier les actions", self)
        self._title.setObjectName("title")
        barre.addWidget(self._title)
        barre.addStretch(1)

        self._add_btn = _tool_button(self, "plus", self._palette.text, "Ajouter une action", 18)
        self._add_btn.clicked.connect(self._add)
        barre.addWidget(self._add_btn)

        self._import_btn = _tool_button(
            self, "download", self._palette.text_muted, "Importer un fichier .md", 16
        )
        self._import_btn.clicked.connect(self._import)
        barre.addWidget(self._import_btn)

        self._export_btn = _tool_button(
            self, "upload", self._palette.text_muted, "Exporter les actions", 16
        )
        self._export_btn.clicked.connect(self._export)
        barre.addWidget(self._export_btn)

        self._restore_btn = _tool_button(
            self, "restore", self._palette.text_muted, "Restaurer les actions par défaut", 16
        )
        self._restore_btn.clicked.connect(self._restore)
        barre.addWidget(self._restore_btn)

        layout.addLayout(barre)

        banniere = QFrame(self)
        banniere.setObjectName("helperBanner")
        b_layout = QHBoxLayout(banniere)
        b_layout.setContentsMargins(12, 8, 12, 8)
        etiquette = QLabel("Glissez pour réorganiser, ou ajoutez de nouvelles actions.", banniere)
        etiquette.setObjectName("muted")
        b_layout.addWidget(etiquette)
        layout.addWidget(banniere)

        scroll, self._container, self._list_layout = _scroll_area(self)
        layout.addWidget(scroll, stretch=1)

    # -- API de l'hôte ----------------------------------------------------

    def set_library(self, library: ActionLibrary) -> None:
        self._library = library
        self.refresh()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._back_btn.setIcon(action_icon("check-circle", palette.accent, size=18))
        self._add_btn.setIcon(action_icon("plus", palette.text, size=18))
        for bouton, glyphe in (
            (self._import_btn, "download"),
            (self._export_btn, "upload"),
            (self._restore_btn, "restore"),
        ):
            bouton.setIcon(action_icon(glyphe, palette.text_muted, size=16))
        self.refresh()

    def refresh(self) -> None:
        """Reconstruit la liste éditable."""
        clear_layout(self._list_layout)

        dernier = len(self._library) - 1
        for rang, action in enumerate(self._library):
            self._list_layout.addWidget(self._row(action, rang, dernier))

        self._list_layout.addStretch(1)

    def _row(self, action: Action, rang: int, dernier: int) -> QFrame:
        teinte = self._palette.tint(action.color)
        glyphe = ACTION_ICONS.get(action.name, action.icon)

        ligne = QFrame(self._container)
        ligne.setObjectName("actionRow")
        disposition = QHBoxLayout(ligne)
        disposition.setContentsMargins(10, 6, 10, 6)
        disposition.setSpacing(8)

        for nom, couleur, taille in (
            ("drag", self._palette.text_muted, 16),
            (glyphe, teinte, 18),
            ("dot", teinte, 10),
        ):
            vignette = QLabel(ligne)
            vignette.setPixmap(action_icon(nom, couleur, size=taille).pixmap(taille, taille))
            disposition.addWidget(vignette)

        libelle = QLabel(action.name, ligne)
        libelle.setStyleSheet("font-size: 13px; font-weight: 500;")
        disposition.addWidget(libelle, stretch=1)

        if rang > 0:
            haut = QPushButton("▲", ligne)
            haut.setObjectName("iconTool")
            haut.setFixedSize(24, 24)
            haut.setToolTip("Monter")
            haut.clicked.connect(lambda _, a=action: self._move(a, -1))
            disposition.addWidget(haut)

        if rang < dernier:
            bas = QPushButton("▼", ligne)
            bas.setObjectName("iconTool")
            bas.setFixedSize(24, 24)
            bas.setToolTip("Descendre")
            bas.clicked.connect(lambda _, a=action: self._move(a, 1))
            disposition.addWidget(bas)

        modifier = QPushButton(ligne)
        modifier.setObjectName("iconTool")
        modifier.setIcon(action_icon("edit-tool", self._palette.text, size=16))
        modifier.setFixedSize(26, 26)
        modifier.setToolTip("Modifier cette action")
        modifier.clicked.connect(lambda _, a=action: self._edit(a))
        disposition.addWidget(modifier)

        supprimer = QPushButton(ligne)
        supprimer.setObjectName("iconTool")
        supprimer.setIcon(action_icon("trash", self._palette.danger, size=16))
        supprimer.setFixedSize(26, 26)
        supprimer.setToolTip("Supprimer cette action")
        supprimer.clicked.connect(lambda _, a=action: self._delete(a))
        disposition.addWidget(supprimer)

        return ligne

    # -- Opérations -------------------------------------------------------

    def _recharger(self) -> None:
        """Relit depuis le disque et prévient l'hôte.

        Point de passage unique : chaque opération se termine ici, ce qui
        garantit que la grille de la palette et la liste éditable ne peuvent
        pas diverger.
        """
        self._library = load_library(_actions_dir())
        self.refresh()
        self.library_changed.emit(self._library)

    def _move(self, action: Action, direction: int) -> None:
        """Déplace une action vers le haut (-1) ou vers le bas (+1)."""
        actions = list(self._library)
        index = next((i for i, a in enumerate(actions) if a.key == action.key), -1)
        cible = index + direction
        if index < 0 or not 0 <= cible < len(actions):
            return

        actions[index], actions[cible] = actions[cible], actions[index]
        dossier = _actions_dir()
        for rang, act in enumerate(actions, start=1):
            save_user_action(
                Action(
                    name=act.name,
                    instruction=act.instruction,
                    prefix=act.prefix,
                    group=act.group,
                    icon=act.icon,
                    color=act.color,
                    open_in_window=act.open_in_window,
                    order=rang * 10,
                    parameters=act.parameters,
                    source=act.source,
                ),
                dossier,
            )
        self._recharger()

    def _add(self) -> None:
        dialogue = ActionEditDialog(self._palette, parent=self)
        if dialogue.exec():
            save_user_action(dialogue.build_action(), _actions_dir())
            self._recharger()

    def _edit(self, action: Action) -> None:
        dialogue = ActionEditDialog(self._palette, action=action, parent=self)
        if dialogue.exec():
            save_user_action(dialogue.build_action(), _actions_dir())
            self._recharger()

    def _delete(self, action: Action) -> None:
        reponse = QMessageBox.question(
            self,
            "Supprimer l'action",
            f"Supprimer définitivement l'action « {action.name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reponse == QMessageBox.StandardButton.Yes:
            delete_user_action(action, _actions_dir())
            self._recharger()

    def _import(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Importer une action", "", "Fichiers Markdown (*.md);;Tous les fichiers (*.*)"
        )
        if not chemin:
            return
        fichier = Path(chemin)
        try:
            action = parse_action(fichier.read_text(encoding="utf-8"), source=fichier)
            save_user_action(action, _actions_dir())
        except Exception as exc:
            QMessageBox.warning(self, "Erreur d'import", f"Impossible d'importer l'action :\n{exc}")
            return
        self._recharger()

    def _export(self) -> None:
        dossier = QFileDialog.getExistingDirectory(self, "Dossier d'exportation des actions")
        if not dossier:
            return
        cible = Path(dossier)
        for action in self._library:
            limace = (
                "".join(c if c.isalnum() else "-" for c in action.name.lower()).strip("-")
                or "action"
            )
            (cible / f"{action.order:02d}-{limace}.md").write_text(
                dump_action(action), encoding="utf-8"
            )
        QMessageBox.information(
            self,
            "Export réussi",
            f"{len(self._library)} actions ont été exportées avec succès dans :\n{cible}",
        )

    def _restore(self) -> None:
        reponse = QMessageBox.question(
            self,
            "Restaurer les actions",
            "Voulez-vous restaurer les actions d'origine livrées avec ScribeDesk ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reponse == QMessageBox.StandardButton.Yes:
            restore_default_actions(_actions_dir())
            self._recharger()


# --------------------------------------------------------------------------
# Historique
# --------------------------------------------------------------------------


def format_relative_time(timestamp: str) -> str:
    """Traduit un horodatage ISO en texte relatif lisible."""
    try:
        moment = datetime.fromisoformat(timestamp)
        secondes = int((datetime.now(UTC) - moment).total_seconds())
        if secondes < 60:
            return "à l'instant"
        minutes = secondes // 60
        if minutes < 60:
            return f"il y a {minutes} min"
        heures = minutes // 60
        if heures < 24:
            return f"il y a {heures}h"
        jours = heures // 24
        if jours < 7:
            return f"il y a {jours}j"
        return moment.strftime("%d/%m")
    except Exception:
        return ""


class HistoryPanel(QWidget):
    """Consultation du journal local : relire, recopier, effacer.

    `status` porte ce que l'hôte doit afficher dans sa barre d'état — nombre
    d'entrées, ou accusé de copie. Le panneau ne touche pas à cette barre.
    """

    status = Signal(str)
    entry_copied = Signal(str)

    def __init__(self, history: History, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self._history = history
        self._palette = palette
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        scroll, self._container, self._list_layout = _scroll_area(self)
        layout.addWidget(scroll, stretch=1)

    # -- API de l'hôte ----------------------------------------------------

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.refresh()

    def entry_count(self) -> int:
        return len(self._history)

    def count_label(self) -> str:
        """Libellé d'état, accordé au nombre d'entrées."""
        nombre = len(self._history)
        return f"{nombre} entrée{'s' if nombre > 1 else ''}"

    def refresh(self) -> None:
        clear_layout(self._list_layout)

        entrees = self._history.read(limit=50)
        if not entrees:
            vide = QLabel(
                "Aucun historique pour le moment.\nLes requêtes traitées apparaîtront ici.",
                self._container,
            )
            vide.setObjectName("muted")
            vide.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vide.setStyleSheet("padding: 40px 10px; font-size: 13px;")
            self._list_layout.addWidget(vide)
            return

        for rang, entree in enumerate(entrees):
            self._list_layout.addWidget(self._row(entree, rang))

        self._list_layout.addStretch(1)

    def _row(self, entree: object, rang: int) -> ClickableFrame:
        action = getattr(entree, "action", "")
        glyphe = ACTION_ICONS.get(action, "relecture")

        ligne = ClickableFrame(self._container)
        ligne.setObjectName("historyRow")
        ligne.setCursor(Qt.CursorShape.PointingHandCursor)
        disposition = QHBoxLayout(ligne)
        disposition.setContentsMargins(10, 8, 10, 8)
        disposition.setSpacing(10)

        vignette = QLabel(ligne)
        vignette.setPixmap(action_icon(glyphe, self._palette.accent, size=20).pixmap(20, 20))
        disposition.addWidget(vignette)

        milieu = QVBoxLayout()
        milieu.setSpacing(2)

        entete = QHBoxLayout()
        titre = QLabel(action, ligne)
        titre.setStyleSheet("font-size: 13px; font-weight: 600;")
        entete.addWidget(titre)
        entete.addStretch(1)

        relatif = format_relative_time(getattr(entree, "timestamp", ""))
        if relatif:
            horodatage = QLabel(relatif, ligne)
            horodatage.setObjectName("muted")
            entete.addWidget(horodatage)

        milieu.addLayout(entete)

        brut = (
            getattr(entree, "output_preview", "")
            or getattr(entree, "input_preview", "")
            or "Transformation terminée"
        )
        apercu = " ".join(brut.splitlines()).strip()
        resume = QLabel(apercu, ligne)
        resume.setObjectName("muted")
        resume.setWordWrap(False)
        milieu.addWidget(resume)

        disposition.addLayout(milieu, stretch=1)

        supprimer = QPushButton(ligne)
        supprimer.setObjectName("iconTool")
        supprimer.setIcon(action_icon("trash", self._palette.text_muted, size=16))
        supprimer.setFixedSize(26, 26)
        supprimer.setToolTip("Supprimer de l'historique")
        supprimer.clicked.connect(lambda _, i=rang: self.delete_entry(i))
        disposition.addWidget(supprimer)

        ligne.clicked.connect(lambda texte=apercu: self.copy_entry(texte))
        return ligne

    # -- Opérations -------------------------------------------------------

    def delete_entry(self, index: int) -> None:
        self._history.delete_entry(index)
        self.refresh()
        self.status.emit(self.count_label())

    def copy_entry(self, texte: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(texte)
        self.entry_copied.emit(texte)
        self.status.emit("Copié dans le presse-papier !")

    def clear_all(self) -> bool:
        """Efface tout le journal, après confirmation. Renvoie `True` si fait."""
        if not len(self._history):
            return False
        reponse = QMessageBox.question(
            self,
            "Vider l'historique",
            "Êtes-vous sûr de vouloir effacer tout l'historique local ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reponse != QMessageBox.StandardButton.Yes:
            return False
        self._history.clear()
        self.refresh()
        self.status.emit("0 entrée")
        return True
