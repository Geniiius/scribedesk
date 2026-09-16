# SPDX-License-Identifier: MIT
"""Reconnaissance de la langue source, sans dépendance.

Les invites livrées imposent le français (« réponds toujours en français »).
Appliquées telles quelles à un texte anglais ou espagnol, elles produiraient une
traduction non demandée. Ce module détermine la langue du texte sélectionné pour
que le moteur puisse ajuster la consigne.

La difficulté tient à la longueur : un agent de Service Desk sélectionne une
phrase, pas un article — 80 caractères en médiane. Les bibliothèques statistiques
usuelles sont peu fiables à cette échelle, et pèsent bien plus que le besoin.

L'approche retenue combine deux signaux, du plus décisif au plus faible :

1. **les caractères propres à une langue** — `ñ`, `¿`, `¡` ne s'écrivent qu'en
   espagnol ; `ç`, `œ`, `è`, `ê` qu'en français ;
2. **les mots-outils fréquents**, pondérés selon qu'ils sont exclusifs à une
   langue ou partagés.

Surtout, la fonction sait dire « je ne sais pas ». En dessous du seuil de
confiance, le moteur délègue le choix au modèle plutôt que d'imposer une langue
sur une supposition — se tromper coûte plus cher que s'abstenir.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Final

__all__ = ["LANGUAGE_NAMES", "Detection", "detect_language"]

#: Nom lisible de chaque langue reconnue, tel qu'il sera écrit dans l'invite.
LANGUAGE_NAMES: Final[dict[str, str]] = {
    "fr": "français",
    "en": "anglais",
    "es": "espagnol",
}

#: Caractères qui, à eux seuls, désignent presque sûrement une langue.
_SIGNATURE_CHARS: Final[dict[str, str]] = {
    "es": "ñ¿¡",
    "fr": "çœàèêëùûÿâîï",
}

#: Mots-outils exclusifs à une langue : chacun vaut un point plein.
_EXCLUSIVE: Final[dict[str, frozenset[str]]] = {
    "fr": frozenset(
        """le les des du est etes sommes etre avec dans cette ces pour sur nous vous
        qui ne pas aux mais donc alors toujours jamais faire fait peut doit tres
        plus moins aussi bien alors alors quand comme alors ainsi cela celui elle
        ils elles leur leurs notre votre je tu il on son sa ses au et ou car alors
        merci bonjour cordialement veuillez suite compte mot passe""".split()
    ),
    "en": frozenset(
        """the is are was were this that with from have has been will would should
        and but not you your they their there what when which about into than then
        please thanks hello dear regards password account user cannot could its
        our my his her been being does did done such only some any""".split()
    ),
    "es": frozenset(
        """el los las una es esta estan para con por pero como cuando donde muy mas
        tambien siempre nunca hacer puede debe gracias hola senor ano nino usuario
        contrasena cuenta su sus nosotros ustedes ellos ellas este esa eso porque
        desde hasta segun sobre entre""".split()
    ),
}

#: Mots partagés par plusieurs langues : demi-point, pour départager sans trancher.
_SHARED: Final[dict[str, frozenset[str]]] = {
    "fr": frozenset("la de un une en que ne a y".split()),
    "es": frozenset("la de un una en que no a y".split()),
    "en": frozenset("a in on to of it as at be or no so".split()),
}

_WORD_RE: Final = re.compile(r"[^\W\d_]+", re.UNICODE)

#: En dessous de cet écart relatif entre la meilleure et la deuxième langue, on
#: préfère s'abstenir. Réglé empiriquement sur des phrases courtes de tickets.
_MIN_MARGIN: Final = 0.22

#: Sous ce nombre de mots reconnus, l'échantillon est trop maigre pour conclure.
#: Réglé à 1,0 après mesure : à 1,5, des phrases courtes mais sans ambiguïté
#: (« Tout est fonctionnel », « Gracias ») restaient indéterminées, sans qu'un
#: seuil plus bas n'introduise le moindre faux positif sur les sigles et les
#: références de tickets.
_MIN_HITS: Final = 1.0


@dataclass(frozen=True, slots=True)
class Detection:
    """Résultat d'une reconnaissance de langue."""

    code: str | None
    """Code ISO 639-1, ou ``None`` si le texte n'a pas permis de conclure."""

    confidence: float
    """Écart relatif avec la deuxième hypothèse, entre 0 et 1."""

    scores: dict[str, float]
    """Score brut de chaque langue, utile au diagnostic."""

    @property
    def name(self) -> str:
        """Nom lisible de la langue, ou chaîne vide si indéterminée."""
        return LANGUAGE_NAMES.get(self.code or "", "")

    def __bool__(self) -> bool:
        return self.code is not None


def _strip_accents(word: str) -> str:
    """Retire les diacritiques, pour comparer aux listes écrites sans accents."""
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def detect_language(text: str) -> Detection:
    """Reconnaît la langue d'un texte court.

    Args:
        text: le texte sélectionné par l'utilisateur.

    Returns:
        Une :class:`Detection` dont ``code`` vaut ``None`` quand aucune langue
        ne se dégage assez nettement.

    >>> detect_language("Le mot de passe ne fonctionne plus").code
    'fr'
    >>> detect_language("The password does not work anymore").code
    'en'
    >>> detect_language("La contraseña ya no funciona").code
    'es'
    >>> detect_language("SAP").code is None
    True
    """
    scores: dict[str, float] = dict.fromkeys(LANGUAGE_NAMES, 0.0)
    if not text or not text.strip():
        return Detection(None, 0.0, scores)

    lowered = text.lower()

    # 1. Caractères signatures. Deux points par occurrence distincte : c'est le
    #    signal le plus sûr, mais il reste additif pour qu'un « ñ » isolé dans
    #    un texte par ailleurs français ne renverse pas le verdict.
    for code, signature in _SIGNATURE_CHARS.items():
        distincts = {c for c in signature if c in lowered}
        scores[code] += 2.0 * len(distincts)

    # 2. Mots-outils. Le texte est comparé sans accents, car les agents en
    #    omettent souvent dans la précipitation.
    mots = Counter(_strip_accents(m.group(0).lower()) for m in _WORD_RE.finditer(text))
    reconnus = 0.0
    for mot, occurrences in mots.items():
        for code in LANGUAGE_NAMES:
            if mot in _EXCLUSIVE[code]:
                scores[code] += occurrences
                reconnus += occurrences
            elif mot in _SHARED[code]:
                scores[code] += 0.5 * occurrences
                reconnus += 0.25 * occurrences

    if reconnus < _MIN_HITS:
        return Detection(None, 0.0, scores)

    classement = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    (meilleur, haut), (_, second) = classement[0], classement[1]
    if haut <= 0:
        return Detection(None, 0.0, scores)

    marge = (haut - second) / haut
    if marge < _MIN_MARGIN:
        return Detection(None, marge, scores)
    return Detection(meilleur, marge, scores)
