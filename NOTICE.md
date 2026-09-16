# Origine et attributions

## Filiation

ScribeDesk doit son idée de départ à **[Writing Tools](https://github.com/theJayTea/WritingTools)**,
créé par **Jesai Tarun** (`theJayTea`) et ses contributeurs — un assistant
d'écriture à l'échelle du système, déclenché par un raccourci clavier sur le
texte sélectionné, branché sur un modèle au choix de l'utilisateur.
Qu'il en soit remercié.

## Ce qui a été écrit pour ce projet

L'intégralité du code de ScribeDesk : architecture, moteur d'anonymisation,
couche fournisseurs, bibliothèque d'actions, interface, pictogrammes, tests.
**Aucun fichier source de Writing Tools n'a été repris.**

C'est ce qui rend la licence MIT légitime : le droit d'auteur protège
l'expression, pas les idées. Une implémentation indépendante du même concept
n'est pas une œuvre dérivée.

## Ce qui a été délibérément écarté

Writing Tools est distribué sous **GPL-3.0**, sans exception déclarée pour ses
ressources. Deux éléments en ont donc été exclus :

- **Le jeu d'icônes.** Sa provenance n'a pas pu être établie — aucun fichier de
  crédits dans le dépôt amont, aucune métadonnée dans les PNG, rien de
  retrouvable. Tel que distribué, il arrive sous GPL-3.0. ScribeDesk dessine
  donc ses propres pictogrammes en vectoriel (`src/scribedesk/ui/glyphs.py`).
- **Les images de fond dégradé.** Même raisonnement : le dégradé est peint dans
  le code (`GradientBackground`), ce qui supprime la question et donne au
  passage un rendu net à toute densité d'écran.

L'apparence générale — fenêtre sans cadre, coins arrondis, fond dégradé — a en
revanche été reprise assumée : une esthétique ne se protège pas ainsi. Ce sont
les **fichiers** qui portent une licence.

## Les invites métier

Les actions livrées dans `src/scribedesk/prompts/builtin/` ont été rédigées par
l'auteur de ScribeDesk pour un Service Desk francophone. Elles proviennent d'un
outil interne antérieur, et non de Writing Tools.

## Dépendances

| Composant | Licence |
|---|---|
| [PySide6](https://doc.qt.io/qtforpython/) | LGPL-3.0 |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause |
| [pynput](https://github.com/moses-palmer/pynput) | LGPL-3.0 |
| [keyring](https://github.com/jaraco/keyring) | MIT |
| [platformdirs](https://github.com/tox-dev/platformdirs) | MIT |

PySide6 et pynput sont sous LGPL : ScribeDesk les utilise comme bibliothèques
liées dynamiquement, sans les modifier, ce que la LGPL autorise dans un projet
sous une autre licence.

## Licence

**MIT** — voir [`LICENSE`](LICENSE).
