# SPDX-License-Identifier: MIT
"""Point d'entrée de l'exécutable Windows, utilisé par PyInstaller.

``python -m scribedesk`` ne convient pas comme script de départ une fois le
programme figé : le module ``__main__`` d'un paquet perd alors son contexte de
paquet, et ses imports relatifs échouent. Ce fichier appelle la même fonction
par un import absolu, valable dans les deux mondes.

À l'usage normal — depuis les sources — rien ne change : ``python -m scribedesk``
reste le chemin documenté.
"""

from __future__ import annotations

import multiprocessing
import sys

from scribedesk.__main__ import main

if __name__ == "__main__":
    # Sans cet appel, un exécutable figé qui crée un processus fils relance
    # l'application entière au lieu du fils. Qt n'en crée pas aujourd'hui, mais
    # l'oubli ne se remarque que le jour où une dépendance en crée un, sous la
    # forme d'une fenêtre qui se duplique à l'infini.
    multiprocessing.freeze_support()
    sys.exit(main())
