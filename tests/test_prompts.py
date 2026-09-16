# SPDX-License-Identifier: MIT
"""Bibliothèque d'actions : analyse de l'en-tête, aller-retour, surcharge."""

from __future__ import annotations

from pathlib import Path

import pytest

from scribedesk.prompts import (
    Action,
    ActionLibrary,
    Parameter,
    PromptError,
    builtin_directory,
    delete_user_action,
    dump_action,
    load_library,
    parse_action,
    restore_default_actions,
    save_user_action,
)

FICHIER = """+++
name = "Relecture"
group = "Lecture"
icon = "pencil"
prefix = "Corrige :\\n\\n"
order = 10

[[parameters]]
name = "ton"
label = "Ton"
choices = ["Formel", "Neutre"]
+++

Tu es un correcteur.
Deuxième ligne.
"""


def test_analyse_complete() -> None:
    action = parse_action(FICHIER)
    assert action.name == "Relecture"
    assert action.group == "Lecture"
    assert action.prefix == "Corrige :\n\n"
    assert action.instruction == "Tu es un correcteur.\nDeuxième ligne."
    assert action.parameters[0].choices == ("Formel", "Neutre")


@pytest.mark.parametrize(
    ("contenu", "motif"),
    [
        ("pas d'en-tête", "absent"),
        ("+++\nname = 'X'\n\ncorps sans fermeture", "refermé"),
        ('+++\nname = "X"\n+++\n\n', "vide"),
        ('+++\ngroup = "X"\n+++\n\ncorps', "name"),
        ("+++\nceci n'est pas du toml =\n+++\n\ncorps", "TOML"),
    ],
)
def test_fichiers_invalides(contenu: str, motif: str) -> None:
    with pytest.raises(PromptError, match=motif):
        parse_action(contenu)


def test_aller_retour_serialisation() -> None:
    original = parse_action(FICHIER)
    assert parse_action(dump_action(original)) == original


def test_parametre_sans_choix_est_refuse() -> None:
    with pytest.raises(PromptError, match="aucun choix"):
        parse_action('+++\nname = "X"\n[[parameters]]\nname = "t"\n+++\n\ncorps')


def test_instruction_integre_les_choix() -> None:
    action = parse_action(FICHIER)
    rendu = action.render_instruction({"ton": "Formel"})
    assert rendu.startswith("Tu es un correcteur.")
    assert "- Ton : Formel" in rendu


def test_instruction_retombe_sur_la_valeur_par_defaut() -> None:
    """Un paramètre non renseigné ne doit pas laisser de trou dans l'invite."""
    assert "- Ton : Formel" in parse_action(FICHIER).render_instruction({})


def test_action_sans_parametre_garde_son_instruction() -> None:
    action = Action(name="X", instruction="Fais ceci.")
    assert action.render_instruction({"a": "b"}) == "Fais ceci."


def test_prefixe_applique_au_message_utilisateur() -> None:
    action = parse_action(FICHIER)
    assert action.render_user_message("mon texte") == "Corrige :\n\nmon texte"


# --------------------------------------------------------------------------
# Bibliothèque
# --------------------------------------------------------------------------


def _ecrire(directory: Path, nom_fichier: str, name: str, corps: str, order: int = 50) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / nom_fichier).write_text(
        f'+++\nname = "{name}"\norder = {order}\n+++\n\n{corps}\n', encoding="utf-8"
    )


def test_les_actions_utilisateur_surchargent_les_fournies(tmp_path: Path) -> None:
    fournies, perso = tmp_path / "builtin", tmp_path / "user"
    _ecrire(fournies, "a.md", "Relecture", "Version fournie.")
    _ecrire(perso, "a.md", "relecture", "Version personnalisée.")

    library = ActionLibrary.load(fournies, perso)
    assert len(library) == 1
    assert library.get("Relecture").instruction == "Version personnalisée."


def test_fichier_invalide_ignore_sans_bloquer(tmp_path: Path) -> None:
    """Une action mal formée ne doit pas empêcher l'outil de démarrer."""
    _ecrire(tmp_path, "bon.md", "Bon", "Corps.")
    (tmp_path / "casse.md").write_text("pas d'en-tête du tout", encoding="utf-8")

    library = ActionLibrary.load(tmp_path)
    assert [a.name for a in library] == ["Bon"]


def test_tri_par_ordre_puis_nom(tmp_path: Path) -> None:
    _ecrire(tmp_path, "z.md", "Zebre", "c", order=1)
    _ecrire(tmp_path, "a.md", "Abeille", "c", order=2)
    assert [a.name for a in ActionLibrary.load(tmp_path)] == ["Zebre", "Abeille"]


def test_recherche_insensible_a_la_casse(tmp_path: Path) -> None:
    _ecrire(tmp_path, "a.md", "Note de résolution", "Corps.")
    library = ActionLibrary.load(tmp_path)
    assert library.get("NOTE DE RÉSOLUTION") is not None
    assert library.get("inconnue") is None


def test_ajout_et_retrait() -> None:
    base = ActionLibrary([Action(name="A", instruction="a")])
    enrichie = base.with_action(Action(name="B", instruction="b"))
    assert len(enrichie) == 2
    assert len(enrichie.without("B")) == 1
    assert len(base) == 1, "la bibliothèque d'origine doit rester intacte"


# --------------------------------------------------------------------------
# Actions livrées avec le paquet
# --------------------------------------------------------------------------


def test_les_actions_fournies_sont_toutes_valides() -> None:
    library = load_library()
    assert len(library) >= 10
    for action in library:
        assert action.instruction.strip()
        assert action.name.strip()
        for parameter in action.parameters:
            assert parameter.choices
            assert parameter.initial in parameter.choices


def test_chaque_fichier_fourni_se_relit() -> None:
    for path in builtin_directory().glob("*.md"):
        action = parse_action(path.read_text(encoding="utf-8"), source=path)
        assert parse_action(dump_action(action)).instruction == action.instruction


def test_parametre_valeur_par_defaut_hors_choix() -> None:
    """Une valeur par défaut absente de la liste retombe sur le premier choix."""
    parameter = Parameter(name="t", label="T", choices=("A", "B"), default="Z")
    assert parameter.initial == "A"


def test_sauvegarde_et_suppression_action_utilisateur(tmp_path: Path) -> None:
    action = Action(name="Nouvelle action", instruction="Mon prompt personnalisé", order=50)
    saved_path = save_user_action(action, tmp_path)
    assert saved_path.exists()

    lib = load_library(tmp_path)
    assert lib.get("Nouvelle action") is not None

    delete_user_action(action, tmp_path)
    assert not saved_path.exists()

    lib_after = load_library(tmp_path)
    assert lib_after.get("Nouvelle action") is None


def test_restauration_actions_par_defaut(tmp_path: Path) -> None:
    builtin = load_library()[0]
    delete_user_action(builtin, tmp_path)

    lib = load_library(tmp_path)
    assert lib.get(builtin.name) is None

    restore_default_actions(tmp_path)
    lib_restored = load_library(tmp_path)
    assert lib_restored.get(builtin.name) is not None
