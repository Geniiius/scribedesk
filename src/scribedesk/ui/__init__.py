# SPDX-License-Identifier: MIT
"""Interface graphique Qt.

Importer ce paquet charge PySide6. Le coeur de ScribeDesk n'en dépend jamais :
c'est ce qui permet d'utiliser la bibliothèque et la ligne de commande sur une
machine sans serveur graphique.
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    """Lance l'interface graphique. Importée paresseusement."""
    from .app import main as _main

    return _main()
