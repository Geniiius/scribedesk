# SPDX-License-Identifier: MIT
"""Rapport d'anonymisation.

L'exigence centrale n'est pas que le rapport soit joli, mais qu'il soit
**capable d'accuser**. Un état qui ne saurait montrer que des succès serait un
argument commercial ; c'est le cas fautif qui lui donne sa valeur.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from scribedesk.audit import build_report, since_days
from scribedesk.engine import TransformResult
from scribedesk.history import HistoryEntry
from scribedesk.privacy import Redactor


def entree(
    *,
    quand: str = "2026-09-14T09:00:00+00:00",
    action: str = "Relecture et correction",
    provider: str = "Groq",
    masque: int = 0,
    regles: dict[str, int] | None = None,
    local: bool = False,
    anonymisation: bool = True,
) -> HistoryEntry:
    return HistoryEntry(
        timestamp=quand,
        action=action,
        provider=provider,
        redacted=masque,
        rules=regles or {},
        local=local,
        redaction_active=anonymisation,
    )


# --------------------------------------------------------------------------
# Classement des sorties réseau
# --------------------------------------------------------------------------


def test_les_trois_natures_de_traitement_sont_distinguees() -> None:
    rapport = build_report(
        [
            entree(local=True, anonymisation=False),
            entree(local=False, anonymisation=True, masque=2, regles={"NOM": 2}),
            entree(local=False, anonymisation=False),
        ]
    )
    assert rapport.locales == 1
    assert rapport.distantes_protegees == 1
    assert rapport.distantes_non_protegees == 1
    assert rapport.distantes == 2
    assert rapport.total == 3


def test_un_envoi_non_anonymise_rend_le_rapport_non_conforme() -> None:
    """C'est la seule chose que le rapport doit absolument savoir dire."""
    rapport = build_report([entree(local=False, anonymisation=False)])
    assert rapport.conforme is False
    assert "sans anonymisation" in rapport.to_markdown()
    assert "⚠️" in rapport.to_markdown()


def test_un_traitement_local_ne_compte_pas_comme_un_manquement() -> None:
    """Sans anonymisation mais sans sortie : il n'y a rien à protéger."""
    rapport = build_report([entree(local=True, anonymisation=False)])
    assert rapport.conforme is True
    assert rapport.distantes_non_protegees == 0
    assert "✅" in rapport.to_markdown()


def test_local_prime_sur_l_etat_de_l_anonymisation() -> None:
    """Un traitement local reste local, quel que soit le réglage."""
    rapport = build_report([entree(local=True, anonymisation=True)])
    assert rapport.locales == 1
    assert rapport.distantes == 0


# --------------------------------------------------------------------------
# Contenu
# --------------------------------------------------------------------------


def test_le_detail_par_regle_est_agrege() -> None:
    rapport = build_report(
        [
            entree(masque=3, regles={"NOM": 2, "TEL": 1}),
            entree(masque=2, regles={"NOM": 1, "EMAIL": 1}),
        ]
    )
    assert rapport.valeurs_masquees == 5
    assert rapport.par_regle["NOM"] == 3
    assert rapport.par_regle["TEL"] == 1
    assert rapport.par_regle["EMAIL"] == 1


def test_le_rapport_ne_contient_aucune_valeur_masquee() -> None:
    """Documenter la protection ne doit pas recréer la fuite qu'on évite."""
    rapport = build_report(
        [
            HistoryEntry(
                timestamp="2026-09-14T09:00:00+00:00",
                action="Relecture",
                provider="Groq",
                redacted=1,
                rules={"NOM": 1},
                input_preview="DUPONT ne peut plus se connecter",
                output_preview="DUPONT ne parvient plus à se connecter",
            )
        ]
    )
    rendu = rapport.to_markdown()
    assert "DUPONT" not in rendu
    assert "connecter" not in rendu
    assert "NOM" in rendu, "le type doit apparaître, pas la valeur"


def test_repartition_par_moteur_et_par_action() -> None:
    rapport = build_report(
        [
            entree(provider="Groq", action="Relecture et correction"),
            entree(provider="Groq", action="Résumé"),
            entree(provider="Ollama (local)", action="Relecture et correction", local=True),
        ]
    )
    assert rapport.par_fournisseur["Groq"] == 2
    assert rapport.par_action["Relecture et correction"] == 2


# --------------------------------------------------------------------------
# Période
# --------------------------------------------------------------------------


def test_le_filtrage_par_date_exclut_les_entrees_anciennes() -> None:
    maintenant = datetime.now(UTC)
    rapport = build_report(
        [
            entree(quand=(maintenant - timedelta(days=10)).isoformat()),
            entree(quand=(maintenant - timedelta(hours=2)).isoformat()),
        ],
        since=since_days(1),
    )
    assert rapport.total == 1


def test_un_journal_vide_donne_un_rapport_conforme_et_lisible() -> None:
    rapport = build_report([])
    assert rapport.total == 0
    assert rapport.conforme is True
    assert "Rapport d'anonymisation" in rapport.to_markdown()


def test_un_horodatage_illisible_ne_fait_pas_echouer_le_rapport() -> None:
    """Une ligne abîmée ne doit pas empêcher de produire l'état."""
    rapport = build_report([entree(quand="pas une date")])
    assert rapport.total == 1


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------


def test_le_csv_reprend_les_memes_chiffres() -> None:
    rapport = build_report(
        [
            entree(local=True, anonymisation=False),
            entree(masque=2, regles={"NOM": 2}),
            entree(anonymisation=False),
        ]
    )
    csv = rapport.to_csv()
    assert "traitees_localement,1" in csv
    assert "envoyees_anonymisees,1" in csv
    assert "envoyees_non_anonymisees,1" in csv
    assert "regle_NOM,2" in csv


def test_le_rapport_annonce_sa_propre_portee() -> None:
    """Un audit crédible dit ce qu'il ne prouve pas."""
    rendu = build_report([entree()]).to_markdown()
    assert "Il n'atteste rien des autres logiciels" in rendu
    assert "heuristiques" in rendu


# --------------------------------------------------------------------------
# Localité du fournisseur
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cle", "url", "attendu"),
    [
        ("ollama", "", True),
        ("ollama", "http://localhost:11434", True),
        # Un Ollama hébergé ailleurs fait bel et bien sortir les données.
        ("ollama", "http://srv-ia.interne.be:11434", False),
        ("groq", "", False),
        ("custom", "http://127.0.0.1:1234/v1", True),
        ("custom", "https://api.exemple.com/v1", False),
    ],
)
def test_la_localite_suit_l_url_et_non_le_nom_du_fournisseur(
    cle: str, url: str, attendu: bool
) -> None:
    from scribedesk.providers import build_provider

    provider = build_provider(cle, base_url=url, model="m", api_key="k")
    assert provider.is_local is attendu


# --------------------------------------------------------------------------
# La fabrique est le seul chemin de construction
# --------------------------------------------------------------------------


def test_la_fabrique_renseigne_ce_que_l_audit_lit() -> None:
    """Régression : l'interface recopiait les champs à la main, et en oubliait trois.

    `local`, `rules` et `redaction_active` restaient à leur valeur par défaut,
    si bien que *toute* transformation passée par la fenêtre était comptée
    comme un envoi sans anonymisation. Le rapport accusait l'outil de la fuite
    qu'il venait précisément d'empêcher.
    """
    redaction = Redactor().redact("Appeler DUPONT au 02 000 00 00")
    resultat = TransformResult(
        text="Appeler [[NOM_1]] au [[TEL_1]]",
        action="Relecture",
        provider="Groq",
        model="m",
        elapsed=1.2,
        redaction=redaction,
        local=False,
    )

    entree = HistoryEntry.from_result(resultat, "Appeler DUPONT au 02 000 00 00", store_text=False)

    assert entree.redaction_active is True
    assert entree.rules, "la répartition par règle alimente le rapport"
    assert entree.redacted == 2

    rapport = build_report([entree])
    assert rapport.distantes_protegees == 1
    assert rapport.distantes_non_protegees == 0
    assert rapport.conforme


def test_un_moteur_local_est_compte_comme_tel() -> None:
    resultat = TransformResult(
        text="ok", action="Relecture", provider="Ollama", model="m", elapsed=0.4, local=True
    )
    rapport = build_report([HistoryEntry.from_result(resultat, "ok", store_text=False)])

    assert rapport.locales == 1
    assert rapport.distantes == 0


def test_aucun_module_ne_construit_une_entree_a_la_main() -> None:
    """Verrouille l'invariant plutôt que la discipline.

    Le défaut corrigé plus haut n'était pas visible : ajouter un champ à
    `HistoryEntry` laissait les appelants manuels compiler, passer `mypy`, et
    journaliser des entrées incomplètes. Seule `history.py` a le droit de
    construire une entrée champ par champ — la fabrique et le relecteur JSONL.
    """
    racine = pathlib.Path(__file__).resolve().parents[1] / "src" / "scribedesk"
    fautifs: list[str] = []

    for fichier in racine.rglob("*.py"):
        if fichier.name == "history.py":
            continue
        for noeud in ast.walk(ast.parse(fichier.read_text(encoding="utf-8"))):
            if isinstance(noeud, ast.Call) and getattr(noeud.func, "id", None) == "HistoryEntry":
                relatif = fichier.relative_to(racine.parent.parent).as_posix()
                fautifs.append(f"{relatif}:{noeud.lineno}")

    assert not fautifs, (
        "construire HistoryEntry(...) directement contourne from_result, "
        f"qui seule renseigne local/rules/redaction_active : {fautifs}"
    )
