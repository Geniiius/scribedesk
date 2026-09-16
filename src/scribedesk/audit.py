# SPDX-License-Identifier: MIT
"""Rapport d'anonymisation, destiné à un délégué à la protection des données.

Une promesse de confidentialité qu'on ne peut pas vérifier ne vaut rien. Ce
module transforme le journal local en un état récapitulatif : combien de
transformations, lesquelles sont restées sur le poste, combien de valeurs ont
été masquées et de quelle nature.

Deux principes en gouvernent la conception.

**Le rapport doit pouvoir accuser.** Un état qui ne saurait montrer que des
succès serait un argument commercial, pas un audit. Les envois effectués avec
l'anonymisation désactivée y figurent donc en premier, et sont comptés à part.

**Le rapport ne recrée pas la fuite qu'il documente.** Il n'y figure aucune
valeur masquée, aucun extrait de texte : uniquement des dénombrements par type
de règle. « 2 patronymes, 1 téléphone » décrit ce qui a été protégé sans le
divulguer.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .history import HistoryEntry

__all__ = ["AuditReport", "build_report"]


@dataclass(slots=True)
class AuditReport:
    """Synthèse d'une période d'utilisation."""

    depuis: datetime | None
    jusqu_a: datetime | None
    total: int = 0
    locales: int = 0
    """Transformations traitées sur le poste : aucune sortie réseau."""

    distantes_protegees: int = 0
    """Envois distants effectués avec l'anonymisation en service."""

    distantes_non_protegees: int = 0
    """Envois distants **sans** anonymisation. C'est le chiffre à surveiller."""

    valeurs_masquees: int = 0
    par_regle: Counter[str] = field(default_factory=Counter)
    par_fournisseur: Counter[str] = field(default_factory=Counter)
    par_action: Counter[str] = field(default_factory=Counter)

    @property
    def distantes(self) -> int:
        return self.distantes_protegees + self.distantes_non_protegees

    @property
    def conforme(self) -> bool:
        """Vrai si aucun envoi distant n'a eu lieu sans anonymisation."""
        return self.distantes_non_protegees == 0

    # -- Rendus -----------------------------------------------------------

    def to_markdown(self) -> str:
        """Rapport lisible, destiné à être joint à un dossier."""
        lignes = [
            "# Rapport d'anonymisation — ScribeDesk",
            "",
            f"**Période** : {_periode(self.depuis, self.jusqu_a)}",
            f"**Transformations** : {self.total}",
            "",
            "## Sorties réseau",
            "",
            "| Nature | Nombre |",
            "|---|---|",
            f"| Traitées localement, aucune sortie | {self.locales} |",
            f"| Envoyées avec anonymisation | {self.distantes_protegees} |",
            f"| **Envoyées sans anonymisation** | **{self.distantes_non_protegees}** |",
            "",
        ]

        if self.conforme:
            lignes.append(
                "✅ Aucun envoi vers un service distant n'a eu lieu sans anonymisation "
                "préalable sur la période."
            )
        else:
            lignes.append(
                f"⚠️ **{self.distantes_non_protegees} envoi(s) vers un service distant "
                "ont eu lieu sans anonymisation.** Vérifiez le réglage "
                "« Anonymiser avant envoi » dans les préférences."
            )
        lignes.append("")

        if self.par_regle:
            lignes += [
                "## Données masquées avant envoi",
                "",
                f"{self.valeurs_masquees} valeur(s) au total.",
                "",
                "| Type | Nombre |",
                "|---|---|",
                *(f"| {regle} | {n} |" for regle, n in self.par_regle.most_common()),
                "",
            ]

        lignes += [
            "## Répartition",
            "",
            "| Moteur | Transformations |",
            "|---|---|",
            *(f"| {nom} | {n} |" for nom, n in self.par_fournisseur.most_common()),
            "",
            "| Action | Transformations |",
            "|---|---|",
            *(f"| {nom} | {n} |" for nom, n in self.par_action.most_common()),
            "",
            "## Portée de ce rapport",
            "",
            "Ce document rend compte des traitements effectués **par ScribeDesk**,",
            "d'après son journal local. Il n'atteste rien des autres logiciels du",
            "poste, ni d'un éventuel contournement de l'outil.",
            "",
            "La détection des patronymes repose sur des heuristiques : elle ne",
            "remplace pas une relecture humaine. Aucune valeur masquée ne figure",
            "ici, seulement des dénombrements.",
        ]
        return "\n".join(lignes)

    def to_csv(self) -> str:
        """Même contenu, pour une reprise en tableur."""
        lignes = [
            "indicateur,valeur",
            f"periode_debut,{self.depuis.isoformat() if self.depuis else ''}",
            f"periode_fin,{self.jusqu_a.isoformat() if self.jusqu_a else ''}",
            f"transformations,{self.total}",
            f"traitees_localement,{self.locales}",
            f"envoyees_anonymisees,{self.distantes_protegees}",
            f"envoyees_non_anonymisees,{self.distantes_non_protegees}",
            f"valeurs_masquees,{self.valeurs_masquees}",
        ]
        lignes += [f"regle_{regle},{n}" for regle, n in sorted(self.par_regle.items())]
        lignes += [f"moteur_{nom},{n}" for nom, n in sorted(self.par_fournisseur.items())]
        return "\n".join(lignes)


def build_report(
    entries: Iterable[HistoryEntry],
    *,
    since: datetime | None = None,
) -> AuditReport:
    """Agrège les entrées du journal en un état récapitulatif.

    Args:
        entries: entrées à considérer, dans n'importe quel ordre.
        since: ne retenir que les entrées postérieures à cette date.
    """
    retenues: Sequence[HistoryEntry] = [
        entree for entree in entries if since is None or entree.moment >= since
    ]

    rapport = AuditReport(depuis=since, jusqu_a=datetime.now(UTC))
    if not retenues:
        return rapport

    moments = [entree.moment for entree in retenues]
    rapport.depuis = since or min(moments)
    rapport.jusqu_a = max(moments)
    rapport.total = len(retenues)

    for entree in retenues:
        if entree.local:
            rapport.locales += 1
        elif entree.redaction_active:
            rapport.distantes_protegees += 1
        else:
            rapport.distantes_non_protegees += 1

        rapport.valeurs_masquees += entree.redacted
        rapport.par_regle.update(entree.rules)
        rapport.par_fournisseur[entree.provider] += 1
        rapport.par_action[entree.action] += 1

    return rapport


def since_days(days: int) -> datetime:
    """Date de début correspondant à `days` jours en arrière."""
    return datetime.now(UTC) - timedelta(days=days)


def _periode(depuis: datetime | None, jusqu_a: datetime | None) -> str:
    """Rend une période lisible, même partiellement définie."""
    if depuis is None and jusqu_a is None:
        return "aucune donnée"
    debut = depuis.strftime("%d/%m/%Y %H:%M") if depuis else "origine"
    fin = jusqu_a.strftime("%d/%m/%Y %H:%M") if jusqu_a else "maintenant"
    return f"du {debut} au {fin}"
