# SPDX-License-Identifier: MIT
"""``python -m scribedesk`` lance l'interface graphique.

L'import de Qt est différé jusqu'à l'appel effectif, pour que
``python -m scribedesk --help`` reste instantané et fonctionne même là où
PySide6 n'est pas installé.
"""

from __future__ import annotations

import sys

__all__ = ["main"]


def main() -> int:
    """Point d'entrée du module."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "Usage : python -m scribedesk\n\n"
            "Lance l'interface graphique (plateau système + raccourci global).\n"
            "Pour la ligne de commande, utilisez : python -m scribedesk.cli --help"
        )
        return 0

    try:
        from .ui import main as gui_main
    except ImportError as exc:
        print(
            f"Interface graphique indisponible : {exc}\n"
            "Installez les dépendances avec : pip install 'scribedesk[gui]'",
            file=sys.stderr,
        )
        return 1
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
