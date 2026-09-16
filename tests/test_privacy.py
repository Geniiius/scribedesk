# SPDX-License-Identifier: MIT
"""Anonymisation : détection, non-chevauchement, restauration, flux."""

from __future__ import annotations

import pytest

from scribedesk.privacy import Redactor, StreamRestorer
from scribedesk.privacy.patterns import luhn_ok, mod97_ok, nir_ok, nrn_ok

# --------------------------------------------------------------------------
# Validateurs
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("iban", "expected"),
    [
        ("BE68 5390 0754 7034", True),
        ("FR1420041010050500013M02606", True),
        ("BE68 5390 0754 7035", False),  # clé fausse
        ("XX00 0000", False),  # trop court
    ],
)
def test_mod97(iban: str, expected: bool) -> None:
    assert mod97_ok(iban) is expected


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("85.07.30-033.28", True),
        ("85.07.30-033.29", False),
        ("1234", False),
    ],
)
def test_registre_national(number: str, expected: bool) -> None:
    assert nrn_ok(number) is expected


def test_luhn() -> None:
    assert luhn_ok("4111 1111 1111 1111")
    assert not luhn_ok("4111 1111 1111 1112")


def test_nir() -> None:
    # Clés calculées par 97 - (corps % 97), et non recopiées d'un exemple.
    assert nir_ok("180077505600102")
    assert nir_ok("285067511403650")
    assert not nir_ok("180077505600103")


# --------------------------------------------------------------------------
# Détection
# --------------------------------------------------------------------------


def test_masque_les_types_courants() -> None:
    redactor = Redactor()
    result = redactor.redact("DUPONT (dupontj01) au 02 000 00 00, jean@exemple.test, IP 10.42.0.17")
    assert set(result.summary()) == {"NOM", "UID", "TEL", "EMAIL", "IP"}
    assert "DUPONT" not in result.text
    assert "jean@exemple.test" not in result.text


def test_ignore_les_sigles_metier() -> None:
    """Un ticket parle de SAP et de RGPD : ce ne sont pas des patronymes."""
    result = Redactor().redact("Incident SAP bloquant, RGPD applicable, RAS côté VPN.")
    assert result.is_empty, result.mapping


def test_ignore_les_salutations_en_capitales() -> None:
    """Chaque mot est vérifié : « BONJOUR MERCI » ne forme pas un nom composé."""
    result = Redactor().redact("BONJOUR MERCI CORDIALEMENT")
    assert result.is_empty, result.mapping


def test_sigles_supplementaires_configurables() -> None:
    texte = "Connexion GEODE impossible pour MARTIN."
    assert len(Redactor().redact(texte).mapping) == 2
    restreint = Redactor(extra_stopwords=["geode"]).redact(texte)
    assert list(restreint.mapping.values()) == ["MARTIN"]


def test_pas_de_chevauchement_entre_regles() -> None:
    """L'IBAN est prioritaire : ses chiffres ne repartent pas en téléphone."""
    result = Redactor().redact("Virement sur BE68 5390 0754 7034 avant vendredi.")
    assert list(result.summary()) == ["IBAN"]
    assert result.text.count("[[") == 1


def test_meme_valeur_meme_jeton() -> None:
    """La cohérence des références compte pour la qualité de la réponse."""
    result = Redactor().redact("DUPONT a appelé. DUPONT rappellera demain.")
    assert result.text.count("[[NOM_1]]") == 2
    assert len(result.mapping) == 1


def test_selection_de_regles() -> None:
    result = Redactor(enabled=["EMAIL"]).redact("DUPONT — jean@exemple.test")
    assert list(result.summary()) == ["EMAIL"]
    assert "DUPONT" in result.text


def test_texte_vide() -> None:
    result = Redactor().redact("")
    assert result.text == ""
    assert result.is_empty


# --------------------------------------------------------------------------
# Restauration
# --------------------------------------------------------------------------


def test_aller_retour_complet() -> None:
    source = "Rappeler DUPONT au 02 000 00 00 ou jean@exemple.test"
    redactor = Redactor()
    result = redactor.redact(source)
    assert redactor.restore(result.text, result.mapping) == source


def test_restauration_tolere_les_espaces_parasites() -> None:
    """Les modèles insèrent parfois des espaces à l'intérieur des crochets."""
    assert Redactor.restore("Voir [[ NOM_1 ]].", {"NOM_1": "DUPONT"}) == "Voir DUPONT."


def test_jeton_invente_reste_visible() -> None:
    """Mieux vaut une anomalie repérable qu'une suppression silencieuse."""
    sortie = Redactor.restore("Voir [[NOM_9]].", {"NOM_1": "DUPONT"})
    assert sortie == "Voir [[NOM_9]]."
    assert Redactor.unknown_tokens("Voir [[NOM_9]].", {"NOM_1": "X"}) == ("NOM_9",)


# --------------------------------------------------------------------------
# Restauration en flux
# --------------------------------------------------------------------------


def _stream(chunks: list[str], mapping: dict[str, str]) -> str:
    restorer = StreamRestorer(mapping)
    return "".join(restorer.feed(c) for c in chunks) + restorer.flush()


@pytest.mark.parametrize(
    ("chunks", "attendu"),
    [
        (["Rappeler [[TE", "L_1]] demain"], "Rappeler 0241 demain"),
        (list("Voir [[NOM_1]] svp"), "Voir DUPONT svp"),
        (["[[NOM_1]] au [[TEL", "_1]]."], "DUPONT au 0241."),
        (["un tableau [x] et ", "la suite"], "un tableau [x] et la suite"),
        (["texte ["], "texte ["),
        (["- point [1]", " suite"], "- point [1] suite"),
    ],
)
def test_flux_ne_coupe_pas_les_jetons(chunks: list[str], attendu: str) -> None:
    assert _stream(chunks, {"TEL_1": "0241", "NOM_1": "DUPONT"}) == attendu


def test_flux_sans_correspondance_est_transparent() -> None:
    assert _stream(["abc", "def"], {}) == "abcdef"


def test_flux_ne_bloque_pas_sur_crochet_orphelin() -> None:
    """Au-delà du plafond de retenue, le texte repart même sans fermeture."""
    long_texte = "[" + "z" * (StreamRestorer.MAX_HOLD + 10)
    assert _stream([long_texte], {"NOM_1": "X"}) == long_texte


# --------------------------------------------------------------------------
# Identifiants d'infrastructure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "machine",
    [
        "srvapp01",  # préfixe serveur
        "sapprod02",  # produit + environnement
        "citrixweb01",  # produit composé
        "exchmail03",  # préfixe Exchange
        "exch2019",  # millésime de version
        "office2021",
        "vm0042",
        "dbsql01",
        "prod01",
        "fwedge03",
        "glpi01",
    ],
)
def test_les_noms_de_machines_ne_sont_pas_masques(machine: str) -> None:
    """Masquer un nom de serveur empêche le modèle de diagnostiquer.

    `srvapp01` et `dupontj01` ont la même forme — des lettres puis des
    chiffres. Sans arbitrage, la règle UID masquait les deux, et le modèle
    recevait `[[UID_1]]` à la place de l'infrastructure dont il devait parler.
    """
    assert Redactor().redact(machine).is_empty, f"{machine} a été masqué à tort"


@pytest.mark.parametrize(
    "login", ["dupontj01", "janssens01", "martinl02", "lefevre12", "dubois03", "vandammep01"]
)
def test_les_identifiants_de_personne_restent_masques(login: str) -> None:
    """Contrepartie : élargir la préservation ne doit pas désarmer la règle."""
    resultat = Redactor().redact(login)
    assert not resultat.is_empty, f"{login} aurait dû être masqué"
    assert list(resultat.summary()) == ["UID"]


@pytest.mark.parametrize("sigle", ["BSOD", "JIRA", "GLPI", "SNOW", "ZENDESK", "OTRS", "FAQ"])
def test_les_outils_itsm_ne_sont_pas_pris_pour_des_noms(sigle: str) -> None:
    assert Redactor().redact(sigle).is_empty, f"{sigle} a été masqué à tort"


def test_un_sigle_maison_protege_aussi_ses_instances() -> None:
    """Déclarer « GEODE » doit couvrir « GEODE » comme « geode02 »."""
    redactor = Redactor(extra_stopwords=["GEODE"])
    assert redactor.redact("GEODE").is_empty
    assert redactor.redact("geode02").is_empty
    # Sans la déclaration, l'instance reste masquée : c'est bien le réglage
    # qui agit, pas un effet de bord de la liste par défaut.
    assert not Redactor().redact("geode02").is_empty


def test_un_ticket_reel_garde_son_contexte_technique() -> None:
    """Cas d'ensemble : la personne est masquée, l'infrastructure préservée."""
    resultat = Redactor().redact(
        "dupontj01 signale que srvapp01 ne répond plus depuis la MEP, "
        "erreur 0x80070005 sur exch2019, ticket INC0042"
    )
    assert "[[UID_1]]" in resultat.text
    for technique in ("srvapp01", "exch2019", "INC0042", "0x80070005"):
        assert technique in resultat.text, f"{technique} doit rester lisible"
