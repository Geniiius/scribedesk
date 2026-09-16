# SPDX-License-Identifier: MIT
"""Moteur : ce qui part vraiment sur le réseau, et ce qui revient à l'agent."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from scribedesk.config import HistoryConfig, PrivacyConfig, ProviderConfig, Settings
from scribedesk.engine import Engine
from scribedesk.history import History, HistoryEntry
from scribedesk.privacy import PRESERVE_INSTRUCTION
from scribedesk.prompts import Action, ActionLibrary

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SENSIBLE = "Appeler DUPONT au 02 000 00 00 puis écrire à jean@exemple.test"

ACTION = Action(name="Relecture", instruction="Corrige le texte.", prefix="Corrige :\n")


def _engine(**privacy: object) -> Engine:
    settings = Settings(
        provider=ProviderConfig(key="groq", model="m"),
        privacy=PrivacyConfig(**privacy),  # type: ignore[arg-type]
        history=HistoryConfig(enabled=False),
    )
    return Engine(settings, ActionLibrary([ACTION]))


@pytest.fixture(autouse=True)
def _cle_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRIBEDESK_API_KEY", "cle-de-test")


def sse(texte: str) -> str:
    return f"data: {json.dumps({'choices': [{'delta': {'content': texte}}]})}\n\ndata: [DONE]\n\n"


# --------------------------------------------------------------------------
# Ce qui part
# --------------------------------------------------------------------------


def test_le_texte_envoye_ne_contient_aucune_donnee_personnelle() -> None:
    messages, redaction = _engine().prepare(ACTION, SENSIBLE)
    envoye = "\n".join(m.content for m in messages)

    assert redaction is not None
    for valeur in ("DUPONT", "02 000 00 00", "jean@exemple.test"):
        assert valeur not in envoye, f"{valeur} ne doit jamais quitter le poste"
    assert "[[NOM_1]]" in envoye


def test_la_consigne_de_preservation_est_ajoutee() -> None:
    messages, _ = _engine().prepare(ACTION, SENSIBLE)
    assert PRESERVE_INSTRUCTION in messages[0].content


def test_pas_de_consigne_inutile_si_rien_n_est_masque() -> None:
    """Alourdir l'invite sans raison dégrade la qualité de la réponse."""
    messages, redaction = _engine().prepare(ACTION, "Tout est fonctionnel.")
    assert redaction is not None and redaction.is_empty
    assert PRESERVE_INSTRUCTION not in messages[0].content


def test_le_prefixe_de_l_action_est_applique() -> None:
    messages, _ = _engine(enabled=False).prepare(ACTION, "mon texte")
    assert messages[1].content == "Corrige :\nmon texte"


def test_anonymisation_desactivee_laisse_le_texte_intact() -> None:
    messages, redaction = _engine(enabled=False).prepare(ACTION, SENSIBLE)
    assert redaction is None
    assert "DUPONT" in messages[1].content


def test_fournisseur_local_exempte_par_defaut() -> None:
    """Anonymiser pour un modèle qui tourne sur le poste n'a pas d'objet."""
    engine = Engine(Settings(provider=ProviderConfig(key="ollama", model="m")))
    _, redaction = engine.prepare(ACTION, SENSIBLE)
    assert redaction is None


# --------------------------------------------------------------------------
# Ce qui revient
# --------------------------------------------------------------------------


@respx.mock
async def test_les_valeurs_reelles_reviennent_dans_le_resultat() -> None:
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(200, text=sse("Appeler [[NOM_1]] au [[TEL_1]]."))
    )
    engine = _engine()
    try:
        resultat = await engine.run(ACTION, SENSIBLE)
    finally:
        await engine.aclose()

    assert resultat.text == "Appeler DUPONT au 02 000 00 00."
    assert resultat.redacted_count == 3
    assert "3 valeur(s) masquée(s)" in resultat.privacy_note()


@respx.mock
async def test_restauration_correcte_meme_si_le_jeton_est_coupe_en_deux() -> None:
    """Le découpage réseau ne doit pas laisser de jeton dans la sortie."""
    corps = (
        'data: {"choices":[{"delta":{"content":"Appeler [[NO"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"M_1]] demain"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(GROQ_URL).mock(return_value=httpx.Response(200, text=corps))

    engine = _engine()
    try:
        morceaux = [m async for m in engine.stream(ACTION, SENSIBLE)]
    finally:
        await engine.aclose()

    assert "".join(morceaux) == "Appeler DUPONT demain"
    assert "[[" not in "".join(morceaux)


@respx.mock
async def test_note_de_confidentialite_pour_un_traitement_local() -> None:
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, text=json.dumps({"message": {"content": "ok"}}))
    )
    engine = Engine(
        Settings(provider=ProviderConfig(key="ollama", model="m")), ActionLibrary([ACTION])
    )
    try:
        resultat = await engine.run(ACTION, SENSIBLE)
    finally:
        await engine.aclose()
    assert "aucune donnée n'a quitté ce poste" in resultat.privacy_note()


# --------------------------------------------------------------------------
# Cycle de vie
# --------------------------------------------------------------------------


def test_le_fournisseur_est_reutilise_entre_deux_appels() -> None:
    engine = _engine()
    assert engine.provider is engine.provider, "le pool de connexions doit être conservé"


def test_changer_de_reglage_reconstruit_le_fournisseur() -> None:
    engine = _engine()
    premier = engine.provider
    engine.settings = engine.settings.with_provider(model="autre-modele")
    assert engine.provider is not premier


def test_action_inconnue_liste_les_possibilites() -> None:
    with pytest.raises(KeyError, match="Relecture"):
        _engine().action("inexistante")


# --------------------------------------------------------------------------
# Historique
# --------------------------------------------------------------------------


def test_historique_ne_conserve_pas_le_texte_par_defaut(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scribedesk.engine import TransformResult

    resultat = TransformResult(text="sortie", action="A", provider="Groq", model="m", elapsed=0.1)
    entree = HistoryEntry.from_result(resultat, SENSIBLE, store_text=False)
    assert entree.input_preview == ""
    assert entree.output_preview == ""
    assert entree.action == "A"


def test_historique_borne_sa_taille(tmp_path) -> None:  # type: ignore[no-untyped-def]
    history = History(tmp_path / "h.jsonl", HistoryConfig(max_entries=3))
    for index in range(10):
        history.append(HistoryEntry(timestamp=f"t{index}", action=f"A{index}", provider="P"))

    entrees = history.read()
    assert len(entrees) == 3
    assert [e.action for e in entrees] == ["A9", "A8", "A7"]


def test_historique_desactive_n_ecrit_rien(tmp_path) -> None:  # type: ignore[no-untyped-def]
    chemin = tmp_path / "h.jsonl"
    History(chemin, HistoryConfig(enabled=False)).append(
        HistoryEntry(timestamp="t", action="A", provider="P")
    )
    assert not chemin.exists()


def test_ligne_corrompue_ignoree_sans_perdre_les_autres(tmp_path) -> None:  # type: ignore[no-untyped-def]
    chemin = tmp_path / "h.jsonl"
    chemin.write_text(
        '{"timestamp":"t1","action":"A","provider":"P"}\n'
        "ceci n'est pas du json\n"
        '{"timestamp":"t2","action":"B","provider":"P"}\n',
        encoding="utf-8",
    )
    entrees = History(chemin, HistoryConfig()).read()
    assert [e.action for e in entrees] == ["B", "A"]
