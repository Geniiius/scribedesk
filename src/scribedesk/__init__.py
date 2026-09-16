# SPDX-License-Identifier: MIT
"""ScribeDesk — assistant d'écriture système orienté Service Desk.

Le paquet est volontairement scindé en deux moitiés :

* le **coeur** (`config`, `prompts`, `privacy`, `history`) ne dépend que de la
  bibliothèque standard et de `platformdirs`. Il se teste sans serveur
  graphique et sans réseau ;
* la **couche réseau** (`providers`, `engine`) ajoute `httpx`, de loin l'import
  le plus coûteux du projet. Les commandes purement locales — anonymiser,
  lister les actions — ne la chargent pas ;
* la **couche UI** (`scribedesk.ui`) importe Qt et n'est chargée qu'au moment où
  une fenêtre doit réellement s'afficher.

Ce découpage est mesurable : `scribedesk redact` démarre environ deux fois plus
vite que `scribedesk run`, parce qu'il ne paie ni `httpx` ni `asyncio`.

Rien dans ce module de tête n'importe Qt : `import scribedesk` reste bon marché.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
