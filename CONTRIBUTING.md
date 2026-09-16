# Contribuer à ScribeDesk

Merci de l'intérêt porté au projet. Voici de quoi s'y retrouver.

## Mise en route

```bash
pip install -e ".[gui,dev]"
pytest
```

Les tests d'interface tournent sans écran. Sous Linux, exportez
`QT_QPA_PLATFORM=offscreen` si Qt réclame un affichage.

## Contributions particulièrement bienvenues

### Nouvelles règles de détection

C'est là que le projet a le plus à gagner, et le plus à perdre en cas d'erreur.
Une règle utile respecte deux exigences :

1. **Un validateur plutôt qu'une regex plus longue.** Si la donnée porte une clé
   de contrôle (mod 97, Luhn, checksum), vérifiez-la. C'est ce qui distingue une
   détection fiable d'un générateur de faux positifs.
2. **Un test pour chaque sens.** Un cas qui doit être détecté, et un cas voisin
   qui ne doit pas l'être. Les faux positifs coûtent cher : masquer `SAP` ou
   `BONJOUR` dégrade la réponse du modèle et fait perdre confiance dans l'outil.

Ajoutez la règle dans `src/scribedesk/privacy/patterns.py`, avec sa `priority` :
les règles spécifiques passent avant les génériques et réservent leurs positions
dans le texte.

Si vous découvrez qu'une règle **laisse passer** une donnée qu'elle devrait
masquer, ne l'écrivez pas dans une issue publique : c'est un contournement tant
qu'aucun correctif n'existe. Voir [`SECURITY.md`](SECURITY.md). Les faux
positifs — un sigle masqué à tort — relèvent en revanche de l'issue normale.

### Adaptation à un autre pays

Les règles actuelles couvrent la Belgique, la France et le Luxembourg. Les
formats d'identifiants nationaux, de téléphones et de numéros fiscaux varient ;
une contribution pour un autre pays francophone (Suisse, Québec) serait très
utile.

### Nouvelles actions

Un fichier dans `src/scribedesk/prompts/builtin/`. Restez générique : une action
livrée doit servir à d'autres services que le vôtre. Les invites très spécifiques
ont leur place dans le dossier d'actions personnelles.

## Conventions

- Le code, les commentaires et la documentation sont en **français**.
- Les commentaires expliquent *pourquoi*, pas *quoi*. Si un choix est
  contre-intuitif — un délai, un ordre d'opérations, un repli — dites pourquoi.
- Type hints partout ; `mypy src` doit passer en mode strict.
- `ruff check src tests` et `ruff format` avant de proposer.

## Ce qui sera refusé

- Une dépendance supplémentaire dans le **cœur**. `httpx` et `platformdirs`
  suffisent ; tout le reste est optionnel. La légèreté du noyau est une
  fonctionnalité, pas un accident.
- Un import de Qt hors de `src/scribedesk/ui/`.
- Une règle de détection sans test de faux positif.
- Un stockage de secret sur disque, sous quelque forme que ce soit — y compris
  « chiffré » avec une clé embarquée dans le programme.

## Licence

En contribuant, vous acceptez que votre travail soit distribué sous licence
**MIT**, comme le reste du projet.
