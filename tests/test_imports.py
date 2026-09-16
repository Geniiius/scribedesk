# SPDX-License-Identifier: MIT
"""Garde-fous sur le graphe d'imports.

Le découpage en couches — coeur / réseau / interface — n'est tenu par rien
d'autre que la discipline. Un `import httpx` ou `from PySide6 import ...` ajouté
en tête d'un module du coeur passerait inaperçu : le code fonctionnerait,
simplement plus lentement, et la bibliothèque cesserait d'être utilisable sans
serveur graphique.

Ces tests s'exécutent dans un interpréteur neuf, car le module peut déjà avoir
été chargé par un autre test de la suite.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Modules qui ne doivent apparaître dans `sys.modules` qu'à la demande.
COUTEUX = ("PySide6", "httpx", "asyncio")


def modules_apres_import(cible: str) -> set[str]:
    """Renvoie les modules de premier niveau chargés après `import cible`."""
    programme = textwrap.dedent(f"""
        import sys, json
        import {cible}
        print(json.dumps(sorted({{m.split(".")[0] for m in sys.modules}})))
    """)
    resultat = subprocess.run(
        [sys.executable, "-c", programme],
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    return set(json.loads(resultat.stdout))


@pytest.mark.parametrize(
    "cible",
    ["scribedesk", "scribedesk.config", "scribedesk.privacy", "scribedesk.prompts"],
)
def test_le_coeur_ne_charge_ni_qt_ni_reseau(cible: str) -> None:
    charges = modules_apres_import(cible)
    for module in COUTEUX:
        assert module not in charges, (
            f"« import {cible} » charge {module}. Le coeur doit rester utilisable "
            f"sans interface graphique ni pile réseau — déplacez cet import dans "
            f"la fonction qui s'en sert."
        )


def test_la_ligne_de_commande_ne_charge_pas_le_reseau() -> None:
    """`scribedesk redact` n'émet aucune requête : il ne doit rien payer pour ça."""
    charges = modules_apres_import("scribedesk.cli")
    assert "httpx" not in charges
    assert "asyncio" not in charges
    assert "PySide6" not in charges


def test_le_moteur_charge_bien_la_pile_reseau() -> None:
    """Contrepartie : le module qui en a besoin doit effectivement l'obtenir."""
    assert "httpx" in modules_apres_import("scribedesk.engine")


def test_l_historique_se_lit_sans_pile_reseau() -> None:
    """Consulter le journal ne doit pas entraîner `engine`, donc `httpx`."""
    assert "httpx" not in modules_apres_import("scribedesk.history")
