# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Ce projet suit le [versionnage sémantique](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- **Icône d'application redessinée** : monogramme « SD » sur dégradé indigo,
  peint en huit résolutions natives (16 à 256 px) pour rester net dans la barre
  des tâches comme dans le plateau système. Toujours vectoriel : le dépôt reste
  sans actif binaire.
- **Exécutable Windows autonome** : `ScribeDesk.exe`, sans Python ni
  installation, construit par l'intégration continue à chaque tag `v*` et
  publié avec son empreinte SHA-256. La recette est versionnée
  (`ScribeDesk.spec`), et la construction refuse de partir si le tag annonce
  une version que le code ne porte pas.
- README : section d'installation pour l'utilisateur final, et tableau des
  variables d'environnement reconnues.

### Modifié

- **Thème sombre par défaut** au lieu du suivi du thème système.
- Le numéro de version n'est plus déclaré qu'à un seul endroit
  (`src/scribedesk/__init__.py`) ; `pyproject.toml` le lit.

### Retiré

- `uv.lock` : ni la documentation ni l'intégration continue ne s'en servaient.
  Un verrou que personne ne lit se périme en silence, et laissait croire que
  `uv sync` était un chemin d'installation pris en charge.

## [1.0.0] — 2026-09-15

Première version publique.

### Confidentialité

- **Anonymisation réversible** avant tout appel à un service distant : les
  données personnelles sont remplacées par des jetons `[[NOM_1]]`, et les
  valeurs d'origine réinjectées dans la réponse — y compris en flux, où un
  jeton peut être coupé entre deux fragments réseau.
- **Douze règles de détection**, dont quatre à clé de contrôle vérifiée : IBAN
  (mod 97), registre national belge, NIR français, carte bancaire (Luhn).
- **Les identifiants d'infrastructure sont préservés** : `srvapp01`, `exch2019`
  ou `citrixweb01` ont la même forme qu'un identifiant de personne, mais les
  masquer empêcherait le modèle de diagnostiquer quoi que ce soit.
- **Rapport d'anonymisation exportable** (`scribedesk audit`), en Markdown ou
  CSV. Il compte les envois effectués *sans* protection et rend un code de
  sortie non nul le cas échéant : un audit doit pouvoir accuser.
- **Clés d'API dans le trousseau du système**, jamais sur disque.
- **Historique sans texte d'usager par défaut** : seules les métadonnées sont
  conservées, sauf activation explicite.

### Usage

- **Deux raccourcis** : `Ctrl+Espace` ouvre la palette, `Ctrl+Alt+Espace`
  applique l'action par défaut et remplace la sélection sans rien afficher.
- **Palette en grille** à deux colonnes, teintée et pictogrammée d'après les
  fichiers d'action.
- **Sélecteur de langue de sortie** : n'importe quelle action peut livrer son
  résultat dans une autre langue, sans passer par une action de traduction.
- **Barre d'ajustement** sous le résultat : affiner par passes successives
  — « plus formel », « plus court » — sans rouvrir la palette.
- **Vue comparée** original / résultat, ouverte uniquement lorsque la sortie
  change réellement de langue.
- **Reconnaissance de la langue source** (français, anglais, espagnol) pour que
  les invites françaises livrées ne traduisent pas un ticket anglais.
- **Éditeur d'actions intégré** : créer, modifier, importer, exporter.
- **Action de traduction** optionnelle, désactivée par défaut.

### Moteurs

Ollama (local), NVIDIA NIM, Groq, Mistral, OpenAI, et tout point d'accès
compatible OpenAI. La localité est déduite de l'URL : un Ollama hébergé sur un
serveur distant est correctement rapporté comme une sortie réseau.

### Robustesse

- **Instance unique** : un second lancement ouvre la palette de l'instance en
  place au lieu d'enregistrer les mêmes raccourcis globaux une seconde fois.
- **Réessai sur erreur de passerelle** (`515`, `520`–`527`) : ces codes viennent
  d'un intermédiaire — pare-feu inspectant le TLS, réseau de diffusion — et non
  du fournisseur. Observé en conditions réelles à raison d'un appel sur cinq.
- **Contrôle de configuration au démarrage** : le moteur est sondé, et les
  préférences s'ouvrent si une clé manque.
- **Journal sur disque** avec rotation, dans le répertoire de données.

### Qualité

271 tests, `mypy` en mode strict, `ruff` sans exception non documentée.
Un test vérifie dans un interpréteur neuf que le cœur n'importe ni Qt ni
`httpx` — ce qui garde `scribedesk redact` à 214 ms de démarrage.
