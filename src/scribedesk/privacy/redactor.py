# SPDX-License-Identifier: MIT
"""Pseudonymisation réversible du texte avant envoi à un modèle distant.

Principe : les données personnelles sont remplacées par des jetons stables
(``[[TEL_1]]``) *avant* l'appel réseau, puis les valeurs d'origine sont
réinjectées dans la réponse du modèle. Le fournisseur cloud ne voit jamais le
nom ni le numéro de téléphone de l'usager, mais l'agent récupère un texte
complet et directement exploitable.

    >>> r = Redactor()
    >>> red = r.redact("Appeler DUPONT au 02 000 00 00")
    >>> red.text
    'Appeler [[NOM_1]] au [[TEL_1]]'
    >>> r.restore("J'ai appelé [[NOM_1]] au [[TEL_1]].", red.mapping)
    "J'ai appelé DUPONT au 02 000 00 00."

Le remplacement est *idempotent par valeur* : une même chaîne reçoit toujours le
même jeton dans un document donné, ce qui préserve la cohérence des références
(« DUPONT … il ») pour le modèle.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from .patterns import Rule, build_rules

__all__ = [
    "PRESERVE_INSTRUCTION",
    "TOKEN_RE",
    "Entity",
    "Redaction",
    "Redactor",
    "StreamRestorer",
]


#: Jeton de substitution. Le double crochet est volontaire : il est rare dans un
#: texte naturel, les LLM le recopient fidèlement, et il survit au passage en
#: Markdown — contrairement aux crochets simples parfois interprétés comme des
#: liens.
TOKEN_RE: Final = re.compile(r"\[\[\s*(?P<label>[A-Z_]+_\d+)\s*\]\]")

_TOKEN_TEMPLATE: Final = "[[{label}]]"

#: Préfixe incomplet de jeton en fin de chaîne, pendant un flux : « [ », « [[ »,
#: « [[NOM », « [[NOM_1] »… Sert à savoir jusqu'où le texte est définitif.
_PARTIAL_TOKEN_RE: Final = re.compile(r"\[(?:\[[A-Z_0-9]*\]?)?$")

#: Consigne ajoutée à l'invite système lorsque l'anonymisation est active.
PRESERVE_INSTRUCTION: Final = (
    "Le texte contient des jetons de la forme [[TYPE_N]] (par exemple [[NOM_1]] "
    "ou [[TEL_2]]). Ce sont des espaces réservés qui remplacent des données "
    "confidentielles. Recopie-les EXACTEMENT tels quels dans ta réponse, sans "
    "les traduire, les renuméroter, les reformuler ni les commenter. Traite "
    "chacun comme un nom propre opaque."
)


@dataclass(frozen=True, slots=True)
class Entity:
    """Une donnée détectée et masquée."""

    rule: str
    original: str
    token: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Redaction:
    """Résultat d'une passe d'anonymisation."""

    text: str
    """Le texte prêt à être envoyé au modèle."""

    mapping: Mapping[str, str] = field(default_factory=dict)
    """Table ``libellé de jeton -> valeur d'origine``."""

    entities: tuple[Entity, ...] = ()
    """Détail des occurrences, dans l'ordre du texte source."""

    @property
    def is_empty(self) -> bool:
        """Vrai si rien n'a été masqué."""
        return not self.entities

    def summary(self) -> dict[str, int]:
        """Compte les valeurs *distinctes* masquées, par type de règle."""
        counts: dict[str, int] = {}
        for token in self.mapping:
            rule = token.rsplit("_", 1)[0]
            counts[rule] = counts.get(rule, 0) + 1
        return counts


class Redactor:
    """Applique un jeu de règles à un texte, et sait revenir en arrière.

    L'instance est sans état entre deux appels à :meth:`redact` : la table de
    correspondance est portée par l'objet :class:`Redaction` renvoyé. Deux
    documents traités en parallèle ne peuvent donc pas mélanger leurs jetons.
    """

    __slots__ = ("_rules",)

    def __init__(
        self,
        rules: Iterable[Rule] | None = None,
        *,
        enabled: Iterable[str] | None = None,
        extra_stopwords: Iterable[str] = (),
    ) -> None:
        """Construit un anonymiseur.

        Args:
            rules: catalogue de règles à considérer. Par défaut, le catalogue
                standard éventuellement enrichi par `extra_stopwords`.
            enabled: noms de règles à conserver. ``None`` les active toutes.
            extra_stopwords: sigles propres à l'organisation, à ne jamais
                confondre avec des patronymes. Ignoré si `rules` est fourni.
        """
        catalogue = build_rules(extra_stopwords) if rules is None else list(rules)
        selected = (
            list(catalogue) if enabled is None else [r for r in catalogue if r.name in enabled]
        )
        # Tri décroissant : les règles spécifiques réservent leurs positions
        # avant que les règles génériques ne soient évaluées.
        self._rules: tuple[Rule, ...] = tuple(
            sorted(selected, key=lambda r: r.priority, reverse=True)
        )

    @property
    def rules(self) -> tuple[Rule, ...]:
        """Les règles actives, de la plus prioritaire à la moins prioritaire."""
        return self._rules

    # -- Anonymisation ----------------------------------------------------

    def redact(self, text: str) -> Redaction:
        """Remplace toute donnée personnelle détectée par un jeton stable."""
        if not text:
            return Redaction(text="")

        spans = self._collect_spans(text)
        if not spans:
            return Redaction(text=text)

        mapping: dict[str, str] = {}
        tokens: dict[str, str] = {}  # valeur d'origine -> libellé de jeton
        counters: dict[str, int] = {}
        entities: list[Entity] = []
        chunks: list[str] = []
        cursor = 0

        for start, end, rule_name in spans:
            original = text[start:end]
            label = tokens.get(original)
            if label is None:
                counters[rule_name] = counters.get(rule_name, 0) + 1
                label = f"{rule_name}_{counters[rule_name]}"
                tokens[original] = label
                mapping[label] = original

            token = _TOKEN_TEMPLATE.format(label=label)
            chunks.append(text[cursor:start])
            chunks.append(token)
            cursor = end
            entities.append(Entity(rule_name, original, token, start, end))

        chunks.append(text[cursor:])
        return Redaction(text="".join(chunks), mapping=mapping, entities=tuple(entities))

    def _collect_spans(self, text: str) -> list[tuple[int, int, str]]:
        """Sélectionne des positions non chevauchantes, priorité décroissante.

        Un tableau de booléens marque les caractères déjà réservés par une règle
        plus prioritaire. C'est ce qui garantit qu'un IBAN n'est pas redécoupé
        en numéro de téléphone, et qu'un identifiant ne mord pas sur un e-mail.
        """
        claimed = bytearray(len(text))
        spans: list[tuple[int, int, str]] = []

        for rule in self._rules:
            for match in rule.matches(text):
                start, end = rule.span(match)
                if start >= end or any(claimed[start:end]):
                    continue
                claimed[start:end] = b"\x01" * (end - start)
                spans.append((start, end, rule.name))

        spans.sort(key=lambda s: s[0])
        return spans

    # -- Restauration -----------------------------------------------------

    @staticmethod
    def restore(text: str, mapping: Mapping[str, str]) -> str:
        """Réinjecte les valeurs d'origine à la place des jetons.

        Tolère les déformations courantes des LLM (espaces parasites à
        l'intérieur des crochets). Un jeton inconnu — inventé par le modèle — est
        laissé intact plutôt que supprimé : mieux vaut une anomalie visible
        qu'une perte d'information silencieuse.
        """
        if not mapping or not text:
            return text
        return TOKEN_RE.sub(
            lambda m: mapping.get(m.group("label"), m.group(0)),
            text,
        )

    @staticmethod
    def unknown_tokens(text: str, mapping: Mapping[str, str]) -> tuple[str, ...]:
        """Liste les jetons présents dans `text` mais absents de `mapping`."""
        found = {m.group("label") for m in TOKEN_RE.finditer(text)}
        return tuple(sorted(found - set(mapping)))


class StreamRestorer:
    """Restaure les valeurs d'origine au fil d'un flux, sans couper les jetons.

    En mode flux, rien ne garantit qu'un jeton arrive d'un seul tenant : le
    serveur peut très bien émettre ``"…rappeler [[TE"`` puis ``"L_1]] demain"``.
    Substituer fragment par fragment laisserait alors le jeton intact dans la
    sortie finale.

    Cette classe retient donc la fin du tampon tant qu'elle pourrait être le
    début d'un jeton, et ne la libère qu'une fois la question tranchée. La
    retenue est plafonnée par :data:`MAX_HOLD` : si un crochet ouvrant n'est
    jamais refermé — le modèle a simplement écrit ``[`` — le texte repart au
    lieu de rester bloqué.

        >>> sr = StreamRestorer({"TEL_1": "02 000 00 00"})
        >>> sr.feed("Rappeler [[TE") + sr.feed("L_1]] demain") + sr.flush()
        'Rappeler 02 000 00 00 demain'
    """

    #: Longueur maximale retenue en attente d'un jeton complet. Un libellé fait
    #: au plus quelques dizaines de caractères ; au-delà, ce n'en est pas un.
    MAX_HOLD: Final[int] = 48

    __slots__ = ("_buffer", "_mapping")

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = mapping
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        """Absorbe un fragment et renvoie la portion sûre à afficher."""
        if not self._mapping:
            return chunk

        self._buffer += chunk
        resolved = Redactor.restore(self._buffer, self._mapping)

        boundary = self._safe_boundary(resolved)
        emitted, self._buffer = resolved[:boundary], resolved[boundary:]
        return emitted

    def flush(self) -> str:
        """Vide le tampon en fin de flux et renvoie ce qu'il restait."""
        remaining = Redactor.restore(self._buffer, self._mapping)
        self._buffer = ""
        return remaining

    def _safe_boundary(self, text: str) -> int:
        """Position jusqu'à laquelle le texte ne peut plus changer.

        On cherche en fin de chaîne un *préfixe strict* de jeton — ``[``,
        ``[[``, ``[[NO``, ``[[NOM_1]`` — et l'on retient à partir de là. Se
        contenter de chercher le dernier ``[`` serait faux : dans ``[[TE``, il
        désigne le second crochet, et l'on émettrait le premier tout seul.
        """
        match = _PARTIAL_TOKEN_RE.search(text)
        if match is None:
            return len(text)
        start = match.start()
        # Garde-fou : un crochet ouvert que le modèle ne refermera jamais ne
        # doit pas geler le flux indéfiniment.
        if len(text) - start > self.MAX_HOLD:
            return len(text)
        return start
