# SPDX-License-Identifier: MIT
"""Journal local des transformations.

Le format est du JSON Lines : une entrée par ligne, ajoutée en fin de fichier.
Écrire ne demande donc pas de relire l'historique complet, contrairement à un
tableau JSON qu'il faudrait désérialiser puis réécrire en entier à chaque appel.

Par défaut, **seules les métadonnées sont conservées** — horodatage, action,
fournisseur, nombre de valeurs masquées. Le texte de l'usager n'est enregistré
que si l'utilisateur l'a explicitement demandé. Un poste de Service Desk traite
des données de tiers : les accumuler en clair, indéfiniment, dans le profil
utilisateur, demanderait une base légale que l'outil n'a pas à présumer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from .config import HistoryConfig

if TYPE_CHECKING:
    # Importé pour le typage seulement : `engine` entraîne `providers`, donc
    # `httpx`. Consulter l'historique ne doit pas coûter le chargement de la
    # pile réseau.
    from .engine import TransformResult

__all__ = ["History", "HistoryEntry"]

logger = logging.getLogger(__name__)

_ENCODING: Final = "utf-8"

#: Longueur de l'aperçu conservé quand le stockage du texte est activé.
PREVIEW_LENGTH: Final = 240


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Une transformation passée."""

    timestamp: str
    action: str
    provider: str
    model: str = ""
    elapsed: float = 0.0
    redacted: int = 0

    rules: dict[str, int] = field(default_factory=dict)
    """Nombre de valeurs masquées par type de règle — jamais les valeurs.

    C'est ce qui rend le journal opposable : « 2 patronymes, 1 téléphone »
    documente ce qui a été protégé sans recréer la fuite qu'on prétend
    éviter.
    """

    local: bool = False
    """Le traitement a eu lieu sur ce poste, sans aucune sortie réseau."""

    redaction_active: bool = False
    """L'anonymisation était en service. Distinct de `redacted == 0`, qui
    peut signifier « rien à masquer » comme « protection désactivée »."""

    input_preview: str = ""
    output_preview: str = ""

    @property
    def moment(self) -> datetime:
        """L'horodatage sous forme d'objet, pour l'affichage trié."""
        try:
            return datetime.fromisoformat(self.timestamp)
        except ValueError:
            return datetime.fromtimestamp(0, tz=UTC)

    @classmethod
    def from_result(cls, result: TransformResult, source: str, *, store_text: bool) -> HistoryEntry:
        """Construit une entrée à partir d'un résultat d'exécution."""
        return cls(
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            action=result.action,
            provider=result.provider,
            model=result.model,
            elapsed=round(result.elapsed, 3),
            redacted=result.redacted_count,
            rules=dict(result.redaction.summary()) if result.redaction else {},
            local=result.local,
            redaction_active=result.redaction is not None,
            input_preview=_clip(source) if store_text else "",
            output_preview=_clip(result.text) if store_text else "",
        )


@dataclass(slots=True)
class History:
    """Accès au journal, borné en taille."""

    path: Path
    config: HistoryConfig = field(default_factory=HistoryConfig)

    def append(self, entry: HistoryEntry) -> None:
        """Ajoute une entrée, puis élague si le plafond est dépassé.

        Une écriture d'historique ne doit jamais faire échouer une
        transformation réussie : les erreurs d'entrée-sortie sont journalisées
        et absorbées.
        """
        if not self.config.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding=_ENCODING) as handle:
                json.dump(asdict(entry), handle, ensure_ascii=False)
                handle.write("\n")
        except OSError as exc:
            logger.warning("Historique non écrit : %s", exc)
            return
        self._trim()

    def read(self, limit: int | None = None) -> list[HistoryEntry]:
        """Renvoie les entrées, de la plus récente à la plus ancienne."""
        entries = list(self._iter_entries())
        entries.reverse()
        return entries[:limit] if limit else entries

    def clear(self) -> None:
        """Efface tout l'historique."""
        self.path.unlink(missing_ok=True)

    def delete_entry(self, index: int) -> None:
        """Supprime une entrée spécifique par son index récent (0 = plus récente)."""
        entries = self.read()
        if 0 <= index < len(entries):
            del entries[index]
            entries.reverse()  # Remettre en ordre chronologique
            self._rewrite(entries)

    def _rewrite(self, entries: Sequence[HistoryEntry]) -> None:
        try:
            with self.path.open("w", encoding=_ENCODING) as handle:
                for entry in entries:
                    json.dump(asdict(entry), handle, ensure_ascii=False)
                    handle.write("\n")
        except OSError as exc:
            logger.warning("Historique non réécrit : %s", exc)

    def __len__(self) -> int:
        return sum(1 for _ in self._iter_entries())

    # -- Interne ----------------------------------------------------------

    def _iter_entries(self) -> Iterator[HistoryEntry]:
        """Parcourt le fichier en ignorant les lignes illisibles."""
        try:
            content = self.path.read_text(encoding=_ENCODING)
        except (OSError, UnicodeDecodeError):
            return

        known = set(HistoryEntry.__dataclass_fields__)
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload: Any = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            try:
                yield HistoryEntry(**{k: v for k, v in payload.items() if k in known})
            except TypeError:
                continue

    def _trim(self) -> None:
        """Ramène le fichier au plafond configuré, en gardant les plus récentes."""
        limit = max(0, self.config.max_entries)
        if limit == 0:
            self.clear()
            return

        lines = self._raw_lines()
        if len(lines) <= limit:
            return
        try:
            self.path.write_text("\n".join(lines[-limit:]) + "\n", encoding=_ENCODING)
        except OSError as exc:
            logger.warning("Élagage de l'historique impossible : %s", exc)

    def _raw_lines(self) -> Sequence[str]:
        try:
            return [ln for ln in self.path.read_text(encoding=_ENCODING).splitlines() if ln.strip()]
        except (OSError, UnicodeDecodeError):
            return []


def _clip(text: str) -> str:
    """Tronque un texte à la longueur d'aperçu, sur une frontière de mot."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= PREVIEW_LENGTH:
        return collapsed
    cut = collapsed[:PREVIEW_LENGTH].rsplit(" ", 1)[0]
    return f"{cut}…"
