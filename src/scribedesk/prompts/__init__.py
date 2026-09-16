# SPDX-License-Identifier: MIT
"""Bibliothèque d'actions : celles fournies, puis celles de l'utilisateur."""

from __future__ import annotations

import contextlib
from pathlib import Path

from .library import (
    Action,
    ActionLibrary,
    Parameter,
    PromptError,
    dump_action,
    parse_action,
)

__all__ = [
    "Action",
    "ActionLibrary",
    "Parameter",
    "PromptError",
    "builtin_directory",
    "delete_user_action",
    "dump_action",
    "load_library",
    "parse_action",
    "restore_default_actions",
    "save_user_action",
]


def builtin_directory() -> Path:
    """Répertoire des actions livrées avec le paquet."""
    return Path(__file__).parent / "builtin"


def _disabled_path(user_directory: Path) -> Path:
    """Fichier listant les actions masquées, une clé par ligne."""
    return user_directory / ".disabled"


def _read_disabled(user_directory: Path) -> set[str]:
    """Clés des actions masquées, ou un ensemble vide.

    Un fichier illisible est traité comme un fichier absent : masquer une
    action est une préférence d'affichage, et perdre cette préférence doit
    rendre l'action visible plutôt qu'empêcher le chargement de toutes.
    """
    chemin = _disabled_path(user_directory)
    if not chemin.exists():
        return set()
    try:
        contenu = chemin.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {ligne.strip().casefold() for ligne in contenu.splitlines() if ligne.strip()}


def _write_disabled(user_directory: Path, cles: set[str]) -> None:
    """Réécrit la liste des actions masquées, sans jamais interrompre l'appelant."""
    with contextlib.suppress(OSError):
        _disabled_path(user_directory).write_text("\n".join(sorted(cles)) + "\n", encoding="utf-8")


def load_library(user_directory: Path | None = None) -> ActionLibrary:
    """Charge les actions fournies, complétées par celles de l'utilisateur.

    Args:
        user_directory: dossier des actions personnelles. Une action y portant
            le même nom qu'une action fournie la remplace intégralement, ce qui
            permet d'adapter une invite sans perdre la mise à jour des autres.
    """
    directories = [builtin_directory()]
    if user_directory is not None:
        directories.append(user_directory)
    library = ActionLibrary.load(*directories)

    if user_directory is not None:
        disabled = _read_disabled(user_directory)
        if disabled:
            return ActionLibrary(tuple(a for a in library if a.key not in disabled))
    return library


def save_user_action(action: Action, user_directory: Path) -> Path:
    """Enregistre ou met à jour une action dans le dossier de l'utilisateur."""
    user_directory.mkdir(parents=True, exist_ok=True)

    # Réenregistrer une action vaut réactivation : la retirer de .disabled.
    disabled = _read_disabled(user_directory)
    if action.key in disabled:
        _write_disabled(user_directory, disabled - {action.key})

    if action.source and action.source.parent.resolve() == user_directory.resolve():
        target = action.source
    else:
        slug = (
            "".join(c if c.isalnum() else "-" for c in action.name.lower()).strip("-") or "action"
        )
        target = user_directory / f"{action.order:02d}-{slug}.md"

    target.write_text(dump_action(action), encoding="utf-8")
    return target


def delete_user_action(action: Action, user_directory: Path) -> None:
    """Supprime une action de l'utilisateur ou masque une action fournie."""
    user_directory.mkdir(parents=True, exist_ok=True)
    if action.source and action.source.parent.resolve() == user_directory.resolve():
        with contextlib.suppress(OSError):
            action.source.unlink(missing_ok=True)
    else:
        slug = "".join(c if c.isalnum() else "-" for c in action.name.lower()).strip("-")
        for f in user_directory.glob("*.md"):
            if slug in f.stem:
                with contextlib.suppress(OSError):
                    f.unlink(missing_ok=True)

    # Inscrire dans .disabled pour bloquer le chargement (notamment des builtins)
    _write_disabled(user_directory, _read_disabled(user_directory) | {action.key})


def restore_default_actions(user_directory: Path) -> None:
    """Restaure les actions intégrées masquées."""
    with contextlib.suppress(OSError):
        _disabled_path(user_directory).unlink(missing_ok=True)
