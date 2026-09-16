# Politique de sécurité

ScribeDesk existe pour empêcher des données personnelles d'atteindre un service
tiers. Un défaut qui casse cette promesse est une vulnérabilité, même s'il ne
ressemble pas à une faille classique — pas d'exécution de code, pas d'élévation
de privilèges, juste un nom qui sort du poste.

C'est ce qui rend cette page nécessaire, et c'est pourquoi elle décrit le
modèle de menace plutôt que de se contenter d'une adresse.

## Versions suivies

| Version | Corrections de sécurité |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ — aucune version antérieure n'a été publiée |

## Signaler

**N'ouvrez pas d'issue publique.** Un rapport décrivant comment contourner
l'anonymisation est un mode d'emploi tant qu'aucun correctif n'existe.

Utilisez le **signalement privé de GitHub** : onglet *Security* du dépôt →
*Report a vulnerability*. Le fil reste privé entre vous et le mainteneur
jusqu'à publication.

Un rapport exploitable contient :

- le **texte d'entrée** qui déclenche le problème — anonymisé de votre côté si
  ce sont de vraies données, un cas reconstruit suffit presque toujours ;
- ce qui était **attendu** et ce qui s'est **produit** ;
- la version, le système, et le fournisseur configuré ;
- si le défaut concerne une règle de détection : la règle en cause.

## Ce qui constitue une vulnérabilité ici

Par ordre de gravité décroissante :

1. **Une donnée personnelle franchit la frontière réseau alors qu'une règle
   aurait dû la masquer.** En particulier pour les quatre règles à clé de
   contrôle — `IBAN`, `NRN`, `NIR`, `CB` — dont la fiabilité est annoncée comme
   élevée. Un IBAN valide non masqué est un défaut, pas une approximation.
2. **Une clé d'API atteint le disque**, sous quelque forme que ce soit : fichier
   de préférences, journal, historique, trace d'erreur, variable d'environnement
   écrite.
3. **Un envoi distant est rapporté comme local.** La localité se déduit de
   l'URL, pas du nom du fournisseur : un Ollama hébergé sur un serveur distant
   doit être compté comme une sortie réseau. Un `is_local` complaisant ferait
   croire à une confidentialité qui n'existe pas — et fausserait le rapport
   `scribedesk audit`.
4. **L'historique contient du texte d'usager alors que `store_text` est à
   `false`**, sa valeur par défaut.
5. **La restauration réinjecte la mauvaise valeur** — `[[NOM_1]]` rendu avec le
   nom d'une autre personne. Le risque est réel en flux, où un jeton peut être
   coupé entre deux fragments réseau.
6. **Le rapport d'audit sous-compte les envois non protégés.** Un audit qui
   rassure à tort est pire que pas d'audit.

## Ce qui n'en est pas une

**La détection des patronymes est heuristique, et le README le dit.** Un nom
écrit en minuscules au fil d'une phrase lui échappe par construction. Ce n'est
pas une faille, c'est une limite documentée — la parade est la confirmation
avant envoi, ou un modèle local.

La frontière est celle-ci :

| Situation | Statut |
|---|---|
| `dupont` en minuscules, non détecté | Limite connue |
| `DUPONT` en capitales, non détecté | **Vulnérabilité** |
| Un sigle métier masqué à tort comme un nom | Faux positif → issue publique bienvenue |
| Un IBAN à clé valide, non masqué | **Vulnérabilité** |
| Une règle à clé de contrôle qui échoue systématiquement | **Vulnérabilité** |

Les faux positifs — `SAP` pris pour un patronyme — dégradent la réponse du
modèle mais ne font fuir aucune donnée. Ouvrez une issue publique normale, avec
le cas qui échoue et le cas voisin qui doit continuer de fonctionner.

## Hors périmètre

- Les **fournisseurs de modèles** (Groq, NVIDIA, Mistral, OpenAI, Ollama). Ce
  qu'ils font des données reçues relève de leurs conditions, pas de ce dépôt.
  ScribeDesk ne promet que ceci : ce qui part est anonymisé.
- Les **dépendances** — Qt, httpx, pynput, keyring. Remontez en amont ; signalez
  ici si ScribeDesk en fait un usage qui aggrave le problème.
- Un poste **déjà compromis**. Un enregistreur de frappe voit le texte avant
  ScribeDesk ; aucune anonymisation ne protège de cela.
- Les **actions personnelles** que vous écrivez. Une invite qui demande au
  modèle de deviner des données masquées contourne la protection par conception.

## Ce que ce projet ne promet pas

ScribeDesk est maintenu par une personne, sur son temps. Il n'y a ni prime aux
bogues, ni astreinte, ni engagement contractuel. L'intention est de répondre
sous une semaine et de corriger selon la gravité — c'est une intention, pas un
engagement de service.

Aucun audit de sécurité indépendant n'a été conduit. Si vous déployez cet outil
dans un contexte où une fuite aurait des conséquences réglementaires, traitez
l'anonymisation comme une réduction de risque, pas comme une garantie — et
envisagez un modèle local, où la question ne se pose plus.

## Divulgation

Correctif publié, puis crédit dans le journal des modifications si vous le
souhaitez. Vous pouvez rendre le rapport public quand vous voulez ; un délai
laissant le temps de livrer une version corrigée est apprécié, il n'est pas
exigé.
