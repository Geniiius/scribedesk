# SPDX-License-Identifier: MIT
"""Interface en ligne de commande.

Elle sert trois usages : automatiser des traitements par lot, diagnostiquer une
configuration sans lancer l'interface graphique, et — surtout — montrer
l'anonymisation à l'oeuvre. ``scribedesk redact`` n'appelle aucun service
distant et ne réclame aucune clé : c'est la commande à taper pour comprendre en
dix secondes ce que l'outil protège.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import Settings, paths
from .history import History, HistoryEntry
from .privacy import RULE_DESCRIPTIONS, Redactor
from .prompts import load_library

# `engine` et `providers` sont importés dans les seules commandes qui émettent
# une requête. Les commandes purement locales — `redact`, `list`, `rules`,
# `config`, `history` — évitent ainsi de charger httpx et asyncio, soit environ
# la moitié du temps de démarrage.

__all__ = ["main"]

_OK = 0
_ERROR = 1


# --------------------------------------------------------------------------
# Analyse des arguments
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scribedesk",
        description="Assistant d'écriture Service Desk, avec anonymisation avant envoi.",
    )
    parser.add_argument("--version", action="version", version=f"ScribeDesk {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Lister les actions disponibles.")

    run = subparsers.add_parser("run", help="Exécuter une action sur un texte.")
    run.add_argument("action", help="Nom de l'action, tel qu'affiché par « list ».")
    _add_text_arguments(run)
    run.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NOM=VALEUR",
        help="Renseigne un paramètre de l'action. Répétable.",
    )
    run.add_argument(
        "--show-payload",
        action="store_true",
        help="Afficher sur la sortie d'erreur le texte réellement transmis.",
    )

    redact = subparsers.add_parser(
        "redact", help="Montrer le texte anonymisé, sans aucun appel réseau."
    )
    _add_text_arguments(redact)
    redact.add_argument(
        "--mapping", action="store_true", help="Afficher aussi la table de correspondance."
    )

    subparsers.add_parser("check", help="Tester la connexion au fournisseur configuré.")
    subparsers.add_parser("config", help="Afficher la configuration et les chemins utilisés.")
    subparsers.add_parser("rules", help="Lister les règles de détection.")

    audit = subparsers.add_parser(
        "audit", help="Produire un rapport d'anonymisation, pour un DPO ou une DSI."
    )
    audit.add_argument("--jours", type=int, default=0, help="Ne couvrir que les N derniers jours.")
    audit.add_argument("--format", choices=("md", "csv"), default="md", help="Format de sortie.")
    audit.add_argument("-o", "--output", type=Path, help="Écrire dans un fichier.")

    history = subparsers.add_parser("history", help="Consulter le journal local.")
    history.add_argument("-n", "--limit", type=int, default=20, help="Nombre d'entrées.")
    history.add_argument("--clear", action="store_true", help="Effacer tout l'historique.")

    return parser


def _add_text_arguments(parser: argparse.ArgumentParser) -> None:
    """Ajoute les trois façons de fournir le texte d'entrée."""
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-t", "--text", help="Texte à traiter.")
    source.add_argument("-f", "--file", type=Path, help="Fichier à traiter.")
    parser.epilog = "Sans -t ni -f, le texte est lu sur l'entrée standard."


def read_input(args: argparse.Namespace) -> str:
    """Récupère le texte depuis l'option, le fichier ou l'entrée standard."""
    # `Namespace` est typé `Any` : les conversions explicites redonnent au
    # reste du module des chaînes réellement typées.
    if args.text:
        return str(args.text)
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise SystemExit("Aucun texte fourni. Utilisez --text, --file, ou un tube.")
    return sys.stdin.read()


def parse_assignments(pairs: Sequence[str]) -> dict[str, str]:
    """Convertit une liste ``nom=valeur`` en dictionnaire."""
    result: dict[str, str] = {}
    for pair in pairs:
        name, separator, value = pair.partition("=")
        if not separator:
            raise SystemExit(f"Paramètre mal formé : {pair!r}. Attendu « nom=valeur ».")
        result[name.strip()] = value.strip()
    return result


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------


def cmd_list() -> int:
    library = load_library(paths().actions_dir)
    if not library:
        print("Aucune action chargée.")
        return _ERROR
    for group, actions in library.groups.items():
        print(f"\n{group}")
        for action in actions:
            params = " ".join(f"[{p.name}]" for p in action.parameters)
            print(f"  {action.name}{'  ' + params if params else ''}")
    print()
    return _OK


def cmd_redact(args: argparse.Namespace) -> int:
    settings = Settings.load()
    text = read_input(args)
    redactor = Redactor(
        enabled=settings.privacy.rules,
        extra_stopwords=settings.privacy.extra_stopwords,
    )
    result = redactor.redact(text)

    print(result.text)
    if result.is_empty:
        print("\n— Aucune donnée personnelle détectée.", file=sys.stderr)
        return _OK

    summary = ", ".join(f"{count} × {rule}" for rule, count in sorted(result.summary().items()))
    print(f"\n— {len(result.mapping)} valeur(s) masquée(s) : {summary}", file=sys.stderr)
    if args.mapping:
        for token, original in result.mapping.items():
            print(f"    [[{token}]] = {original}", file=sys.stderr)
    return _OK


def cmd_audit(args: argparse.Namespace) -> int:
    """Produit le rapport d'anonymisation à partir du journal local."""
    from .audit import build_report, since_days

    settings = Settings.load()
    history = History(paths().history_file, settings.history)
    rapport = build_report(history.read(), since=since_days(args.jours) if args.jours else None)

    rendu = rapport.to_csv() if args.format == "csv" else rapport.to_markdown()
    if args.output:
        args.output.write_text(rendu, encoding="utf-8")
        print(f"Rapport écrit dans {args.output}", file=sys.stderr)
    else:
        print(rendu)

    # Un envoi non anonymisé rend le code de sortie non nul : le rapport
    # devient utilisable dans un contrôle automatisé.
    return _OK if rapport.conforme else _ERROR


def cmd_rules() -> int:
    for name, description in RULE_DESCRIPTIONS.items():
        print(f"  {name:8} {description}")
    return _OK


def cmd_config() -> int:
    locations = paths()
    settings = Settings.load()
    print(f"Configuration : {locations.settings_file}")
    print(f"Actions perso : {locations.actions_dir}")
    print(f"Historique    : {locations.history_file}")
    print()
    print(settings.to_toml())
    return _OK


def cmd_history(args: argparse.Namespace) -> int:
    settings = Settings.load()
    history = History(paths().history_file, settings.history)

    if args.clear:
        history.clear()
        print("Historique effacé.")
        return _OK

    entries: list[HistoryEntry] = history.read(limit=args.limit)
    if not entries:
        print("Historique vide.")
        return _OK
    for entry in entries:
        masked = f" · {entry.redacted} masqué(s)" if entry.redacted else ""
        print(f"{entry.timestamp}  {entry.action}  ({entry.provider}{masked})")
        if entry.input_preview:
            print(f"    < {entry.input_preview}")
            print(f"    > {entry.output_preview}")
    return _OK


async def cmd_run(args: argparse.Namespace) -> int:
    from .engine import Engine
    from .providers import ProviderError

    settings = Settings.load()
    engine = Engine(settings, load_library(paths().actions_dir))

    try:
        action = engine.action(args.action)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return _ERROR

    text = read_input(args)
    choices = parse_assignments(args.set)

    if args.show_payload:
        messages, _ = engine.prepare(action, text, choices)
        print("--- envoyé au modèle ---", file=sys.stderr)
        for message in messages:
            print(f"[{message.role}] {message.content}", file=sys.stderr)
        print("------------------------", file=sys.stderr)

    try:
        result = await engine.run(action, text, choices)
    except ProviderError as exc:
        print(f"Échec : {exc}", file=sys.stderr)
        return _ERROR
    finally:
        await engine.aclose()

    print(result.text)
    print(f"\n— {result.privacy_note()} ({result.elapsed:.1f} s)", file=sys.stderr)

    History(paths().history_file, settings.history).append(
        HistoryEntry.from_result(result, text, store_text=settings.history.store_text)
    )
    return _OK


async def cmd_check() -> int:
    from .engine import Engine
    from .providers import ProviderError

    settings = Settings.load()
    engine = Engine(settings)
    provider = engine.provider
    print(f"Fournisseur : {provider.name}")
    print(f"Modèle      : {provider.model}")
    try:
        reply = await provider.check()
    except ProviderError as exc:
        print(f"Échec : {exc}", file=sys.stderr)
        return _ERROR
    finally:
        await engine.aclose()
    print(f"Réponse     : {reply}")
    return _OK


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def _force_utf8() -> None:
    """Rend la sortie capable d'écrire les caractères des rapports.

    La console Windows est en cp1252 par défaut. Le rapport d'audit contient
    « ⚠️ » et « ✅ », absents de cette table : sans cela, ``scribedesk audit``
    se terminait par une ``UnicodeEncodeError`` au lieu d'afficher son
    résultat. Les accents du texte anonymisé, eux, sortaient mutilés.
    """
    for flux in (sys.stdout, sys.stderr):
        reconfigure = getattr(flux, "reconfigure", None)
        if reconfigure is None:  # flux capturé par un test, déjà en mémoire
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée de la commande ``scribedesk``."""
    _force_utf8()
    args = build_parser().parse_args(argv)

    match args.command:
        case "list":
            return cmd_list()
        case "redact":
            return cmd_redact(args)
        case "rules":
            return cmd_rules()
        case "audit":
            return cmd_audit(args)
        case "config":
            return cmd_config()
        case "history":
            return cmd_history(args)
        case "run":
            import asyncio

            return asyncio.run(cmd_run(args))
        case "check":
            import asyncio

            return asyncio.run(cmd_check())
        case _:  # pragma: no cover - argparse garantit l'exhaustivité
            return _ERROR


if __name__ == "__main__":
    raise SystemExit(main())
