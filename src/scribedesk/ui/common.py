# SPDX-License-Identifier: MIT
"""Pièces partagées entre la palette et ses panneaux.

Ce module n'existe que pour rompre un cycle : `popup` construit `panels`, et
les deux ont besoin des mêmes trois outils. Les loger ici plutôt que dans
`popup` évite que `panels` doive importer son propre parent.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QLayout, QWidget

#: Pictogramme propre à chaque action livrée. Une action personnelle retombe
#: sur l'icône déclarée dans son en-tête.
ACTION_ICONS: Final[dict[str, str]] = {
    "Relecture et correction": "relecture",
    "Améliore mon écrit": "plume",
    "Analyseur de tickets mail": "mail",
    "Résumé": "resume",
    "Vérification qualité description": "qualite-description",
    "Vérification qualité résolution": "qualite-resolution",
    "Aide au diagnostic": "diagnostic",
    "Description": "description",
    "Brève Génération": "flash",
    "Note de résolution": "resolution",
}


def clear_layout(layout: QLayout) -> None:
    """Retire et détruit tous les widgets et sous-layouts récursivement."""
    while (item := layout.takeAt(0)) is not None:
        widget: QWidget | None = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif (sub_layout := item.layout()) is not None:
            clear_layout(sub_layout)


class ClickableFrame(QFrame):
    """Cadre qui émet un signal au clic.

    Préférée au remplacement de `mousePressEvent` par une lambda : réassigner
    une méthode virtuelle Qt depuis Python contourne la table virtuelle C++,
    échappe au vérificateur de types, et casse silencieusement dès qu'une
    sous-classe ou un style redéfinit la gestion des événements.
    """

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
