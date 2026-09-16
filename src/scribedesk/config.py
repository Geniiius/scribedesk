# SPDX-License-Identifier: MIT
"""Préférences persistées et emplacements de fichiers.

La configuration est un TOML lisible et modifiable à la main. Elle ne contient
**jamais** de secret : les clés d'API vont dans le trousseau du système
(`keyring`), c'est-à-dire le Gestionnaire d'identifiants sous Windows et
Secret Service / KWallet sous Linux.

Cette séparation est délibérée. Chiffrer une clé dans un fichier avec une clé
de déchiffrement embarquée dans le programme n'est pas de la confidentialité,
seulement de l'obscurcissement : quiconque possède le binaire possède la clé.
Le trousseau, lui, adosse la protection à la session ouverte de l'utilisateur.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Final, TypeVar

from platformdirs import PlatformDirs

#: Une section de configuration, c'est-à-dire une dataclasse sans argument requis.
_SectionT = TypeVar("_SectionT", "ProviderConfig", "PrivacyConfig", "HistoryConfig")

__all__ = [
    "APP_NAME",
    "HistoryConfig",
    "Paths",
    "PrivacyConfig",
    "ProviderConfig",
    "Settings",
    "paths",
]

logger = logging.getLogger(__name__)

APP_NAME: Final = "ScribeDesk"
_ENCODING: Final = "utf-8"

#: Nom du service sous lequel les clés sont rangées dans le trousseau.
KEYRING_SERVICE: Final = "scribedesk"


# --------------------------------------------------------------------------
# Emplacements
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Paths:
    """Où l'application range ses fichiers."""

    config_dir: Path
    data_dir: Path

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.toml"

    @property
    def actions_dir(self) -> Path:
        """Actions personnelles de l'utilisateur."""
        return self.config_dir / "actions"

    @property
    def history_file(self) -> Path:
        return self.data_dir / "history.jsonl"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "scribedesk.log"

    def ensure(self) -> Paths:
        """Crée les répertoires manquants. Idempotent."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.actions_dir.mkdir(parents=True, exist_ok=True)
        return self


def paths() -> Paths:
    """Emplacements standards de la plateforme.

    ``SCRIBEDESK_HOME`` force un répertoire unique : indispensable pour les
    tests, et pratique pour une installation portable sur clé USB.
    """
    override = os.environ.get("SCRIBEDESK_HOME")
    if override:
        root = Path(override).expanduser()
        return Paths(config_dir=root, data_dir=root)

    dirs = PlatformDirs(appname=APP_NAME, appauthor=False, roaming=True)
    return Paths(config_dir=Path(dirs.user_config_dir), data_dir=Path(dirs.user_data_dir))


# --------------------------------------------------------------------------
# Sections de configuration
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ProviderConfig:
    """Choix du moteur d'inférence."""

    key: str = "ollama"
    model: str = ""
    base_url: str = ""
    temperature: float = 0.3
    timeout: float = 60.0
    max_tokens: int | None = None


@dataclass(slots=True)
class PrivacyConfig:
    """Politique d'anonymisation appliquée avant tout envoi distant."""

    enabled: bool = True
    """Anonymiser le texte avant l'appel réseau."""

    local_providers_exempt: bool = True
    """Ne pas anonymiser quand l'inférence est locale : c'est inutile, et cela
    évite de dégrader la qualité de sortie sans contrepartie."""

    confirm_before_send: bool = False
    """Afficher ce qui va partir et attendre validation. Lourd au quotidien,
    mais précieux en phase de mise en confiance ou pour une démonstration."""

    rules: tuple[str, ...] | None = None
    """Règles actives. ``None`` signifie « toutes »."""

    extra_stopwords: tuple[str, ...] = ()
    """Sigles maison à ne jamais prendre pour des patronymes."""


@dataclass(slots=True)
class HistoryConfig:
    """Journal local des transformations."""

    enabled: bool = True
    max_entries: int = 200
    store_text: bool = False
    """Conserver le texte source et le résultat. Désactivé par défaut : un
    historique de Service Desk accumule vite des données d'usagers dont la
    conservation devrait être justifiée."""


@dataclass(slots=True)
class Settings:
    """L'ensemble des préférences."""

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)

    hotkey: str = "ctrl+space"
    """Ouvre la palette de choix."""

    quick_hotkey: str = "ctrl+alt+space"
    """Applique l'action par défaut et remplace la sélection, sans rien afficher.

    Le relevé d'usage montre qu'une seule action représente l'écrasante
    majorité des appels, sur des textes de quelques dizaines de caractères.
    Passer par la palette puis par une fenêtre de résultat pour corriger un
    accent coûte six gestes ; celui-ci en coûte un.
    """

    default_action: str = "Relecture et correction"
    """Action déclenchée par `quick_hotkey`. Repli sur la première si absente."""

    respect_source_language: bool = True
    """Répondre dans la langue du texte sélectionné, pas dans celle des invites.

    Les actions livrées sont rédigées en français et imposent le français.
    Appliquées telles quelles à un ticket anglais ou espagnol, elles
    produiraient une traduction que personne n'a demandée.
    """

    translation_enabled: bool = False
    """Afficher l'action de traduction dans la palette.

    Désactivée par défaut : traduire n'est pas corriger, et une onzième action
    encombrerait la grille de ceux qui n'en ont pas l'usage.
    """

    translation_targets: tuple[str, ...] = ("Français", "Anglais", "Espagnol", "Néerlandais")
    """Langues cibles proposées par l'action de traduction."""

    theme: str = "auto"
    locale: str = "fr"
    streaming: bool = True

    def enabled_features(self) -> frozenset[str]:
        """Fonctions optionnelles actives, comparées au champ `requires` des actions."""
        actives = set()
        if self.translation_enabled:
            actives.add("translation")
        return frozenset(actives)

    # -- Persistance ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Lit le fichier de préférences, ou renvoie les valeurs par défaut.

        Un fichier corrompu n'empêche jamais le démarrage : l'incident est
        journalisé et les valeurs par défaut prennent le relais. Perdre ses
        préférences est ennuyeux ; ne plus pouvoir lancer l'outil l'est plus.
        """
        target = path or paths().settings_file
        try:
            raw = tomllib.loads(target.read_text(encoding=_ENCODING))
        except FileNotFoundError:
            return cls()
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Préférences illisibles (%s) : valeurs par défaut. %s", target, exc)
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Settings:
        """Construit des préférences en ignorant les champs inconnus.

        Cette tolérance permet d'ouvrir sans dégât un fichier écrit par une
        version plus récente : les clés non reconnues sont simplement ignorées.
        """
        return cls(
            provider=_section(ProviderConfig, raw.get("provider")),
            privacy=_section(PrivacyConfig, raw.get("privacy")),
            history=_section(HistoryConfig, raw.get("history")),
            hotkey=str(raw.get("hotkey", "ctrl+space")),
            quick_hotkey=str(raw.get("quick_hotkey", "ctrl+alt+space")),
            default_action=str(raw.get("default_action", "Relecture et correction")),
            respect_source_language=bool(raw.get("respect_source_language", True)),
            translation_enabled=bool(raw.get("translation_enabled", False)),
            translation_targets=tuple(str(v) for v in raw.get("translation_targets", ()))
            or ("Français", "Anglais", "Espagnol", "Néerlandais"),
            theme=str(raw.get("theme", "auto")),
            locale=str(raw.get("locale", "fr")),
            streaming=bool(raw.get("streaming", True)),
        )

    def save(self, path: Path | None = None) -> Path:
        """Écrit les préférences de façon atomique.

        Le passage par un fichier temporaire puis un renommage évite qu'une
        coupure au mauvais moment ne laisse un TOML tronqué — auquel cas
        l'utilisateur perdrait sa configuration au redémarrage suivant.
        """
        target = path or paths().ensure().settings_file
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".toml.tmp")
        temporary.write_text(self.to_toml(), encoding=_ENCODING)
        temporary.replace(target)
        return target

    def to_toml(self) -> str:
        """Sérialise en TOML, avec les commentaires d'aide."""
        lines = [
            "# Préférences ScribeDesk.",
            "# Les clés d'API ne sont pas ici : elles sont dans le trousseau du système.",
            "",
            f"hotkey = {_toml(self.hotkey)}",
            f"quick_hotkey = {_toml(self.quick_hotkey)}",
            f"default_action = {_toml(self.default_action)}",
            f"respect_source_language = {_toml(self.respect_source_language)}",
            f"translation_enabled = {_toml(self.translation_enabled)}",
            f"translation_targets = {_toml(self.translation_targets)}",
            f"theme = {_toml(self.theme)}",
            f"locale = {_toml(self.locale)}",
            f"streaming = {_toml(self.streaming)}",
            "",
            "[provider]",
            *_dump_section(asdict(self.provider)),
            "",
            "[privacy]",
            *_dump_section(asdict(self.privacy)),
            "",
            "[history]",
            *_dump_section(asdict(self.history)),
            "",
        ]
        return "\n".join(lines)

    # -- Confort ----------------------------------------------------------

    def with_provider(self, **changes: Any) -> Settings:
        """Copie des préférences avec une section « provider » modifiée."""
        return replace(self, provider=replace(self.provider, **changes))

    def redaction_applies(self) -> bool:
        """Indique si le texte doit être anonymisé avant l'appel courant."""
        if not self.privacy.enabled:
            return False
        # Un modèle local ne fait sortir aucune donnée : masquer n'apporterait
        # rien et dégraderait la qualité de la réponse.
        return not (self.privacy.local_providers_exempt and self.provider.key == "ollama")


# --------------------------------------------------------------------------
# Sérialisation TOML minimale
# --------------------------------------------------------------------------


def _section(cls: type[_SectionT], raw: Any) -> _SectionT:
    """Instancie une section en ne retenant que les champs qu'elle déclare."""
    if not isinstance(raw, Mapping):
        return cls()
    known = {f.name for f in cls.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in raw.items() if k in known}
    # Les séquences TOML arrivent en listes ; les champs les attendent en tuples.
    for key, value in list(kwargs.items()):
        if isinstance(value, list):
            kwargs[key] = tuple(value)
    try:
        return cls(**kwargs)
    except TypeError as exc:
        logger.warning("Section %s ignorée : %s", cls.__name__, exc)
        return cls()


def _toml(value: Any) -> str:
    """Rend une valeur scalaire ou une liste au format TOML."""
    match value:
        case bool():
            return "true" if value else "false"
        case None:
            # TOML n'a pas de valeur nulle : l'absence de clé fait office.
            return ""
        case int() | float():
            return str(value)
        case str():
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        case Iterable():
            return "[" + ", ".join(_toml(v) for v in value) + "]"
        case _:
            return f'"{value}"'


def _dump_section(data: Mapping[str, Any]) -> list[str]:
    """Rend les paires clé/valeur d'une section, en omettant les nulles."""
    return [f"{key} = {_toml(value)}" for key, value in data.items() if value is not None]
