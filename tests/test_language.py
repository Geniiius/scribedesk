# SPDX-License-Identifier: MIT
"""Reconnaissance de la langue et consigne transmise au modèle.

Les cas de test sont volontairement des phrases courtes de tickets réels, pas
des paragraphes : c'est la longueur que l'outil rencontre en pratique, et celle
où la reconnaissance est difficile.
"""

from __future__ import annotations

import pytest

from scribedesk.config import ProviderConfig, Settings
from scribedesk.engine import Engine
from scribedesk.language import detect_language
from scribedesk.prompts import Action, ActionLibrary, load_library

# --------------------------------------------------------------------------
# Reconnaissance
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("L'agent ne sait plus se connecter sur SAP", "fr"),
        ("Problème de connexion sur SAP", "fr"),
        ("Tout est fonctionnel", "fr"),
        ("Prise a distance avec l agent nous avons change le mot de passe", "fr"),
        ("The user cannot connect to SAP after changing his password", "en"),
        ("Please check with the team if the issue is still there", "en"),
        ("Everything is working now, thanks", "en"),
        ("El usuario no puede conectarse a SAP tras cambiar su contraseña", "es"),
        ("Por favor revisa con el equipo si el problema sigue", "es"),
        ("Todo funciona ahora, gracias", "es"),
    ],
)
def test_reconnaissance_sur_phrases_courtes(texte: str, attendu: str) -> None:
    assert detect_language(texte).code == attendu


@pytest.mark.parametrize(
    "texte", ["SAP", "INC0042", "OK", "7841", "Comptoir REZ1", "", "   ", "Groq"]
)
def test_s_abstenir_plutot_que_deviner(texte: str) -> None:
    """Se tromper de langue coûte plus cher que de ne pas conclure."""
    detection = detect_language(texte)
    assert detection.code is None
    assert not detection


def test_les_accents_ne_sont_pas_indispensables() -> None:
    """Les agents omettent souvent les accents : cela ne doit pas tout casser."""
    assert detect_language("Le probleme de connexion est resolu").code == "fr"


def test_un_caractere_signature_pese_lourd() -> None:
    assert detect_language("¿Dónde está el usuario?").code == "es"


def test_la_detection_expose_son_raisonnement() -> None:
    detection = detect_language("The user cannot connect")
    assert detection.name == "anglais"
    assert set(detection.scores) == {"fr", "en", "es"}
    assert 0.0 <= detection.confidence <= 1.0


# --------------------------------------------------------------------------
# Consigne transmise au modèle
# --------------------------------------------------------------------------

ACTION = Action(name="Relecture", instruction="Réponds toujours en français.")


def _engine(**reglages: object) -> Engine:
    settings = Settings(provider=ProviderConfig(key="ollama"), **reglages)  # type: ignore[arg-type]
    return Engine(settings, ActionLibrary([ACTION]))


def test_la_consigne_de_langue_prime_sur_l_invite() -> None:
    """L'invite impose le français ; la consigne doit venir après pour primer."""
    messages, _ = _engine().prepare(ACTION, "The password does not work anymore")
    systeme = messages[0].content

    assert systeme.index("Réponds toujours en français.") < systeme.index("anglais")
    assert "Rédige impérativement ta réponse en anglais" in systeme


def test_langue_indeterminee_delegue_au_modele() -> None:
    """Le modèle voit le texte, nous non : mieux vaut lui laisser le choix."""
    messages, _ = _engine().prepare(ACTION, "SAP")
    assert "dans la même langue que le texte fourni" in messages[0].content


def test_le_reglage_peut_etre_desactive() -> None:
    messages, _ = _engine(respect_source_language=False).prepare(ACTION, "The password is wrong")
    assert "anglais" not in messages[0].content


def test_une_action_de_traduction_ne_recoit_pas_de_consigne_de_langue() -> None:
    """Lui dire « réponds en anglais » contredirait son objet même."""
    traduction = Action(name="Traduction", instruction="Traduis.", preserve_language=False)
    engine = Engine(Settings(provider=ProviderConfig(key="ollama")), ActionLibrary([traduction]))

    messages, _ = engine.prepare(traduction, "The password does not work")
    assert "Rédige" not in messages[0].content


def test_la_detection_porte_sur_le_texte_non_anonymise() -> None:
    """Les jetons appauvriraient un échantillon déjà court."""
    settings = Settings(provider=ProviderConfig(key="groq", model="m"))
    engine = Engine(settings, ActionLibrary([ACTION]))

    messages, redaction = engine.prepare(ACTION, "DUPONT cannot connect to SAP with his password")
    assert redaction is not None and not redaction.is_empty
    assert "anglais" in messages[0].content


# --------------------------------------------------------------------------
# Action optionnelle
# --------------------------------------------------------------------------


def test_la_traduction_est_masquee_par_defaut() -> None:
    complete = load_library()
    visible = complete.for_features(Settings().enabled_features())

    assert complete.get("Traduction") is not None, "l'action existe sur le disque"
    assert visible.get("Traduction") is None, "mais reste masquée tant qu'on ne l'active pas"


def test_activer_la_traduction_la_fait_apparaitre() -> None:
    settings = Settings(translation_enabled=True)
    visible = load_library().for_features(settings.enabled_features())

    traduction = visible.get("Traduction")
    assert traduction is not None
    assert traduction.preserve_language is False
    assert [p.name for p in traduction.parameters] == ["langue_cible", "registre"]


def test_une_action_sans_prerequis_est_toujours_visible() -> None:
    library = ActionLibrary([Action(name="Libre", instruction="i")])
    assert len(library.for_features(())) == 1


def test_les_reglages_de_traduction_survivent_a_un_aller_retour(tmp_path) -> None:  # type: ignore[no-untyped-def]
    origine = Settings(
        translation_enabled=True,
        translation_targets=("Anglais", "Allemand"),
        respect_source_language=False,
    )
    relu = Settings.load(origine.save(tmp_path / "settings.toml"))

    assert relu.translation_enabled is True
    assert relu.translation_targets == ("Anglais", "Allemand")
    assert relu.respect_source_language is False


# --------------------------------------------------------------------------
# Langue imposée depuis la palette
# --------------------------------------------------------------------------


def test_une_langue_imposee_prime_sur_la_langue_detectee() -> None:
    """Le sélecteur de la palette modifie *toutes* les actions, pas une seule.

    Diagnostiquer en français puis livrer la note en néerlandais est un geste
    unique — là où passer par l'action « Traduction » en demanderait deux.
    """
    messages, _ = _engine().prepare(
        ACTION, "Le serveur ne répond plus", target_language="Néerlandais"
    )
    systeme = messages[0].content

    assert "en Néerlandais" in systeme
    assert "français" not in systeme.split("Réponds toujours en français.")[-1]


def test_sans_langue_imposee_la_detection_reprend_la_main() -> None:
    messages, _ = _engine().prepare(ACTION, "The password does not work", target_language="")
    assert "anglais" in messages[0].content


def test_une_langue_imposee_ignore_le_reglage_de_respect() -> None:
    """Un choix explicite de l'utilisateur prime sur une préférence générale."""
    moteur = _engine(respect_source_language=False)
    messages, _ = moteur.prepare(ACTION, "Le serveur est tombé", target_language="Espagnol")
    assert "en Espagnol" in messages[0].content


def test_une_action_de_traduction_ignore_la_langue_imposee() -> None:
    """Elle gère sa propre langue cible : une seconde consigne la contredirait."""
    traduction = Action(name="Traduction", instruction="Traduis.", preserve_language=False)
    moteur = Engine(Settings(provider=ProviderConfig(key="ollama")), ActionLibrary([traduction]))

    messages, _ = moteur.prepare(traduction, "Bonjour", target_language="Anglais")
    assert "Rédige impérativement" not in messages[0].content


def test_le_selecteur_de_la_palette_est_discret_au_repos(qapp_langue) -> None:  # type: ignore[no-untyped-def]
    """Discret quand inactif, franchement visible dès qu'une langue est imposée.

    C'est sa seule protection : le réglage persiste d'une action à l'autre, et
    l'oublier enverrait tout un ticket dans la mauvaise langue.
    """
    from scribedesk.prompts import load_library
    from scribedesk.ui.popup import PopupWindow
    from scribedesk.ui.theme import DARK

    popup = PopupWindow(load_library())
    popup.set_palette(DARK)
    popup.set_language_choices(["Anglais", "Néerlandais"])

    assert popup.target_language() == ""
    assert "langue du texte" in popup._language_button.text().casefold()

    popup._set_target_language("Néerlandais")
    assert popup.target_language() == "Néerlandais"
    assert "Néerlandais" in popup._language_button.text()
    assert (
        DARK.accent.lower() in popup._language_button.styleSheet().lower()
        or str(int(DARK.accent[1:3], 16)) in popup._language_button.styleSheet()
    )


@pytest.fixture
def qapp_langue():  # type: ignore[no-untyped-def]
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])
