# SPDX-License-Identifier: MIT
"""Chargement de la bibliothèque d'actions.

Une action est un fichier Markdown précédé d'un en-tête TOML délimité par
``+++`` : les métadonnées en haut, l'invite système en dessous, écrite en texte
courant. Ce format a été préféré à un unique fichier JSON pour trois raisons
concrètes : une invite de 12 000 caractères reste lisible et se relit en revue
de code ; un `git diff` porte sur l'action modifiée et non sur tout le
catalogue ; et un contributeur peut proposer une action sans toucher au reste.

    +++
    name = "Relecture et correction"
    group = "Lecture"
    icon = "pencil"
    +++

    Tu es un assistant expert de relecture…

Les actions fournies avec le paquet sont chargées en premier ; celles du
répertoire de configuration de l'utilisateur les complètent et, à nom égal,
les remplacent.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = ["Action", "ActionLibrary", "Parameter", "PromptError"]

_DELIMITER: Final = "+++"
_ENCODING: Final = "utf-8"


class PromptError(ValueError):
    """En-tête absent, TOML invalide ou champ obligatoire manquant."""


@dataclass(frozen=True, slots=True)
class Parameter:
    """Un choix proposé à l'utilisateur avant l'exécution de l'action.

    Rendu sous forme de liste déroulante dans la fenêtre surgissante, puis
    injecté dans l'invite. C'est ce qui permet à une même action de couvrir
    « répondre formellement à un usager » et « relancer un collègue » sans
    dupliquer l'invite.
    """

    name: str
    label: str
    choices: tuple[str, ...]
    default: str = ""

    @property
    def initial(self) -> str:
        """Valeur présélectionnée."""
        if self.default and self.default in self.choices:
            return self.default
        return self.choices[0] if self.choices else ""

    @classmethod
    def parse(cls, raw: Mapping[str, Any], *, origin: str) -> Parameter:
        name = str(raw.get("name", "")).strip()
        choices = tuple(str(c) for c in raw.get("choices", ()) if str(c).strip())
        if not name:
            raise PromptError(f"{origin} : un paramètre n'a pas de champ « name ».")
        if not choices:
            raise PromptError(f"{origin} : le paramètre « {name} » n'offre aucun choix.")
        return cls(
            name=name,
            label=str(raw.get("label", name)),
            choices=choices,
            default=str(raw.get("default", "")),
        )


@dataclass(frozen=True, slots=True)
class Action:
    """Une transformation proposée à l'utilisateur."""

    name: str
    instruction: str
    prefix: str = ""
    group: str = ""
    icon: str = "pencil"
    color: str = ""
    open_in_window: bool = True
    order: int = 100

    requires: str = ""
    """Fonction optionnelle dont dépend l'action, ou chaîne vide.

    Une action déclarant ``requires = "translation"`` n'apparaît que si
    l'utilisateur a activé la traduction. C'est le mécanisme qui permet de
    livrer des actions spécialisées sans encombrer la grille de ceux qui n'en
    ont pas l'usage.
    """

    preserve_language: bool = True
    """Répondre dans la langue du texte source.

    Mise à ``false`` par les actions qui changent délibérément de langue : leur
    ajouter une consigne « réponds en français » contredirait leur objet même.
    """
    parameters: tuple[Parameter, ...] = ()
    source: Path | None = field(default=None, compare=False)

    @property
    def key(self) -> str:
        """Identifiant stable, insensible à la casse et aux accents de surface."""
        return self.name.strip().casefold()

    def render_instruction(self, choices: Mapping[str, str] | None = None) -> str:
        """Complète l'invite système avec les paramètres retenus.

        Les valeurs sont ajoutées en fin d'invite sous forme de consignes
        explicites plutôt que substituées dans le texte : l'invite reste
        lisible seule, et un paramètre non renseigné ne laisse pas de trou.
        """
        if not self.parameters:
            return self.instruction

        picked = dict(choices or {})
        lines = [
            f"- {param.label} : {picked.get(param.name) or param.initial}"
            for param in self.parameters
        ]
        return f"{self.instruction}\n\nContraintes retenues pour cette demande :\n" + "\n".join(
            lines
        )

    def render_user_message(self, text: str) -> str:
        """Assemble le message utilisateur envoyé au modèle."""
        return f"{self.prefix}{text}" if self.prefix else text


class ActionLibrary(Sequence[Action]):
    """Collection ordonnée d'actions, indexable par nom."""

    __slots__ = ("_actions", "_by_key")

    def __init__(self, actions: Sequence[Action] = ()) -> None:
        ordered = sorted(actions, key=lambda a: (a.order, a.name))
        self._actions: tuple[Action, ...] = tuple(ordered)
        self._by_key: dict[str, Action] = {a.key: a for a in ordered}

    # -- Protocole Sequence ----------------------------------------------

    def __len__(self) -> int:
        return len(self._actions)

    def __getitem__(self, index: int) -> Action:  # type: ignore[override]
        return self._actions[index]

    def __iter__(self) -> Iterator[Action]:
        return iter(self._actions)

    # -- Accès ------------------------------------------------------------

    def get(self, name: str) -> Action | None:
        """Retrouve une action par son nom, sans tenir compte de la casse."""
        return self._by_key.get(name.strip().casefold())

    @property
    def groups(self) -> dict[str, tuple[Action, ...]]:
        """Actions regroupées, dans l'ordre d'apparition des groupes."""
        grouped: dict[str, list[Action]] = {}
        for action in self._actions:
            grouped.setdefault(action.group or "Général", []).append(action)
        return {name: tuple(items) for name, items in grouped.items()}

    # -- Construction -----------------------------------------------------

    @classmethod
    def load(cls, *directories: Path) -> ActionLibrary:
        """Charge toutes les actions des répertoires donnés, dans l'ordre.

        Un fichier d'un répertoire ultérieur portant le même nom d'action
        écrase le précédent : c'est le mécanisme de personnalisation locale.
        Les fichiers illisibles sont ignorés silencieusement au profit des
        autres — une action mal formée ne doit pas empêcher l'outil de démarrer.
        """
        merged: dict[str, Action] = {}
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    action = parse_action(path.read_text(encoding=_ENCODING), source=path)
                except (PromptError, OSError, UnicodeDecodeError):
                    continue
                merged[action.key] = action
        return cls(tuple(merged.values()))

    def with_action(self, action: Action) -> ActionLibrary:
        """Renvoie une nouvelle bibliothèque incluant (ou remplaçant) `action`."""
        kept = [a for a in self._actions if a.key != action.key]
        return ActionLibrary((*kept, action))

    def for_features(self, features: Iterable[str]) -> ActionLibrary:
        """Ne retient que les actions dont la fonction requise est active.

        Une action sans `requires` passe toujours. Le filtrage est appliqué à
        l'affichage plutôt qu'au chargement : l'action reste sur le disque et
        réapparaît dès que l'utilisateur active la fonction, sans réinstaller
        quoi que ce soit.
        """
        actives = set(features)
        return ActionLibrary(
            tuple(a for a in self._actions if not a.requires or a.requires in actives)
        )

    def without(self, name: str) -> ActionLibrary:
        """Renvoie une nouvelle bibliothèque privée de l'action nommée."""
        key = name.strip().casefold()
        return ActionLibrary(tuple(a for a in self._actions if a.key != key))


def split_front_matter(raw: str) -> tuple[str, str]:
    """Sépare l'en-tête TOML du corps Markdown.

    Returns:
        Le couple ``(en-tête, corps)``.

    Raises:
        PromptError: si le délimiteur d'ouverture ou de fermeture manque.
    """
    text = raw.lstrip("﻿").lstrip()
    if not text.startswith(_DELIMITER):
        raise PromptError("En-tête « +++ » absent en début de fichier.")

    remainder = text[len(_DELIMITER) :].lstrip("\r\n")
    closing = remainder.find(f"\n{_DELIMITER}")
    if closing == -1:
        raise PromptError("En-tête « +++ » non refermé.")

    header = remainder[:closing]
    body = remainder[closing + len(_DELIMITER) + 1 :]
    return header, body.strip()


def parse_action(raw: str, *, source: Path | None = None) -> Action:
    """Construit une :class:`Action` à partir du contenu d'un fichier."""
    origin = str(source) if source else "<mémoire>"
    header, body = split_front_matter(raw)

    try:
        meta: dict[str, Any] = tomllib.loads(header)
    except tomllib.TOMLDecodeError as exc:
        raise PromptError(f"{origin} : en-tête TOML invalide — {exc}") from exc

    name = str(meta.get("name", "")).strip()
    if not name:
        raise PromptError(f"{origin} : le champ « name » est obligatoire.")
    if not body:
        raise PromptError(f"{origin} : l'invite système (corps du fichier) est vide.")

    raw_params = meta.get("parameters") or []
    if not isinstance(raw_params, list):
        raise PromptError(f"{origin} : « parameters » doit être une liste de tables.")

    return Action(
        name=name,
        instruction=body,
        prefix=str(meta.get("prefix", "")),
        group=str(meta.get("group", "")),
        icon=str(meta.get("icon", "pencil")),
        color=str(meta.get("color", "")),
        open_in_window=bool(meta.get("open_in_window", True)),
        order=int(meta.get("order", 100)),
        requires=str(meta.get("requires", "")),
        preserve_language=bool(meta.get("preserve_language", True)),
        parameters=tuple(
            Parameter.parse(p, origin=origin) for p in raw_params if isinstance(p, Mapping)
        ),
        source=source,
    )


def dump_action(action: Action) -> str:
    """Sérialise une action au format fichier, pour l'éditeur d'actions."""
    lines = [_DELIMITER, f'name = "{_escape(action.name)}"']
    if action.group:
        lines.append(f'group = "{_escape(action.group)}"')
    lines.append(f'icon = "{_escape(action.icon)}"')
    if action.color:
        lines.append(f'color = "{_escape(action.color)}"')
    if action.prefix:
        lines.append(f'prefix = "{_escape(action.prefix)}"')
    if action.requires:
        lines.append(f'requires = "{_escape(action.requires)}"')
    if not action.preserve_language:
        lines.append("preserve_language = false")
    lines.append(f"open_in_window = {str(action.open_in_window).lower()}")
    lines.append(f"order = {action.order}")

    for param in action.parameters:
        choices = ", ".join(f'"{_escape(c)}"' for c in param.choices)
        lines += [
            "",
            "[[parameters]]",
            f'name = "{_escape(param.name)}"',
            f'label = "{_escape(param.label)}"',
            f"choices = [{choices}]",
        ]
        if param.default:
            lines.append(f'default = "{_escape(param.default)}"')

    lines += [_DELIMITER, "", action.instruction, ""]
    return "\n".join(lines)


def _escape(value: str) -> str:
    """Échappe une chaîne pour une valeur TOML entre guillemets simples."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
