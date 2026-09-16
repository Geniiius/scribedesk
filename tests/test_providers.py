# SPDX-License-Identifier: MIT
"""Fournisseurs : décodage du flux, traduction des erreurs, réessai."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from scribedesk.providers import (
    AuthenticationError,
    GroqProvider,
    Message,
    NvidiaProvider,
    OllamaProvider,
    ProviderError,
    RateLimitError,
    RetryPolicy,
    build_provider,
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MESSAGES = [Message("user", "bonjour")]


def sse(*morceaux: str) -> str:
    """Fabrique un flux SSE au format OpenAI."""
    lignes = [f"data: {json.dumps({'choices': [{'delta': {'content': m}}]})}" for m in morceaux]
    return "\n\n".join(lignes) + "\n\ndata: [DONE]\n\n"


def _provider(**kwargs: object) -> GroqProvider:
    defaults = {"model": "m", "api_key": "k", "retry": RetryPolicy(attempts=2, base_delay=0)}
    return GroqProvider(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Fabrique
# --------------------------------------------------------------------------


def test_fabrique_connait_les_fournisseurs() -> None:
    assert build_provider("groq").name == "Groq"
    assert build_provider("nvidia").name == "NVIDIA NIM (build.nvidia.com)"
    assert build_provider("nvidia").requires_api_key is True
    assert build_provider("ollama").requires_api_key is False
    assert build_provider("groq").requires_api_key is True


def test_nvidia_fournisseur_endpoint_et_modeles() -> None:
    provider = build_provider("nvidia", api_key="nvapi-test")
    assert isinstance(provider, NvidiaProvider)
    assert provider._endpoint() == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert "meta/llama-3.3-70b-instruct" in [m.id for m in provider.suggested_models]


def test_fournisseur_inconnu() -> None:
    with pytest.raises(KeyError, match="Fournisseur inconnu"):
        build_provider("inexistant")


@pytest.mark.parametrize(
    ("base_url", "attendu"),
    [
        ("", GROQ_URL),
        ("http://local:1234/v1", "http://local:1234/v1/chat/completions"),
        ("http://local:1234/v1/", "http://local:1234/v1/chat/completions"),
        # Les documentations donnent tantôt la racine, tantôt l'URL complète.
        ("http://local:1234/v1/chat/completions", "http://local:1234/v1/chat/completions"),
    ],
)
def test_construction_de_l_url(base_url: str, attendu: str) -> None:
    assert _provider(base_url=base_url)._endpoint() == attendu


# --------------------------------------------------------------------------
# Flux
# --------------------------------------------------------------------------


@respx.mock
async def test_flux_assemble_les_fragments() -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(200, text=sse("Bon", "jour", " !")))
    async with _provider() as provider:
        assert await provider.complete(MESSAGES) == "Bonjour !"


@respx.mock
async def test_flux_rend_les_fragments_un_a_un() -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(200, text=sse("a", "b", "c")))
    async with _provider() as provider:
        assert [m async for m in provider.stream(MESSAGES)] == ["a", "b", "c"]


@respx.mock
async def test_reponse_non_streamee_est_acceptee() -> None:
    """Certains serveurs ignorent stream=true et répondent d'un bloc."""
    corps = json.dumps({"choices": [{"message": {"content": "Bonjour"}}]})
    respx.post(GROQ_URL).mock(return_value=httpx.Response(200, text=corps))
    async with _provider() as provider:
        assert await provider.complete(MESSAGES) == "Bonjour"


@respx.mock
async def test_ollama_decode_son_format_json_lines() -> None:
    corps = "\n".join(json.dumps({"message": {"content": m}}) for m in ("Bon", "jour"))
    respx.post("http://localhost:11434/api/chat").mock(return_value=httpx.Response(200, text=corps))
    async with OllamaProvider(model="llama3.1:8b") as provider:
        assert await provider.complete(MESSAGES) == "Bonjour"


# --------------------------------------------------------------------------
# Erreurs
# --------------------------------------------------------------------------


@respx.mock
async def test_401_devient_erreur_d_authentification() -> None:
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    )
    async with _provider() as provider:
        with pytest.raises(AuthenticationError, match="Invalid API key"):
            await provider.complete(MESSAGES)


@respx.mock
async def test_429_est_signale_avec_le_delai_conseille() -> None:
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "2"}, json={"error": "quota"})
    )
    async with _provider() as provider:
        with pytest.raises(RateLimitError) as info:
            await provider.complete(MESSAGES)
    assert info.value.retry_after == 2.0


async def test_cle_absente_detectee_sans_appel_reseau() -> None:
    """Aucune requête ne doit partir si la configuration est incomplète."""
    async with GroqProvider(model="m", api_key="") as provider:
        with pytest.raises(AuthenticationError, match="Aucune clé"):
            await provider.complete(MESSAGES)


async def test_modele_absent_detecte() -> None:
    async with GroqProvider(model="", api_key="k") as provider:
        with pytest.raises(ProviderError, match="Aucun modèle"):
            await provider.complete(MESSAGES)


# --------------------------------------------------------------------------
# Réessai
# --------------------------------------------------------------------------


@respx.mock
async def test_reessai_apres_erreur_transitoire() -> None:
    route = respx.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": "indisponible"}),
            httpx.Response(200, text=sse("ok")),
        ]
    )
    async with _provider() as provider:
        assert await provider.complete(MESSAGES) == "ok"
    assert route.call_count == 2


@respx.mock
async def test_pas_de_reessai_sur_erreur_definitive() -> None:
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(401, json={"error": "non"}))
    async with _provider() as provider:
        with pytest.raises(AuthenticationError):
            await provider.complete(MESSAGES)
    assert route.call_count == 1, "une clé invalide ne devient pas valide en réessayant"


class _FluxRompu(httpx.AsyncByteStream):
    """Émet un fragment valide puis coupe la connexion."""

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield b'data: {"choices":[{"delta":{"content":"debut"}}]}\n\n'
        raise httpx.ReadError("connexion perdue")


@respx.mock
async def test_pas_de_reessai_apres_emission_partielle() -> None:
    """Relancer après un fragment déjà transmis concaténerait deux réponses."""
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(200, stream=_FluxRompu()))
    async with _provider() as provider:
        recus: list[str] = []
        with pytest.raises(ProviderError, match="interrompu"):
            async for morceau in provider.stream(MESSAGES):
                recus.append(morceau)

    assert recus == ["debut"], "le fragment déjà reçu est conservé"
    assert route.call_count == 1, "aucun réessai après émission partielle"


# --------------------------------------------------------------------------
# Politique de repli
# --------------------------------------------------------------------------


def test_le_delai_croit_et_reste_borne() -> None:
    policy = RetryPolicy(attempts=5, base_delay=1.0, max_delay=4.0)
    assert all(0 < policy.delay_for(i) <= 4.0 for i in range(5))
    assert policy.delay_for(0) <= policy.max_delay
    assert policy.delay_for(3, suggested=100.0) == 4.0, "le délai conseillé reste plafonné"


# --------------------------------------------------------------------------
# Erreurs d'intermédiaire réseau
# --------------------------------------------------------------------------


@respx.mock
async def test_515_du_proxy_est_reessaye() -> None:
    """Régression : rejoue un échec observé en conditions réelles.

    Sur un poste d'administration, un appel sur cinq revenait en
    « 515 Upstream Certificate Untrusted » — une passerelle inspectant le TLS,
    pas un refus de Groq. Le code suivant passait sans rien changer. Ce statut
    était pourtant traité comme définitif, et l'action échouait.
    """
    route = respx.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(515, text="Upstream Certificate Untrusted"),
            httpx.Response(200, text=sse("corrigé")),
        ]
    )
    async with _provider() as provider:
        assert await provider.complete(MESSAGES) == "corrigé"
    assert route.call_count == 2, "le 515 doit déclencher un réessai"


@pytest.mark.parametrize("statut", [515, 520, 521, 522, 523, 524, 525, 526, 527])
@respx.mock
async def test_toute_la_famille_des_erreurs_de_passerelle_est_reessayee(statut: int) -> None:
    route = respx.post(GROQ_URL).mock(
        side_effect=[httpx.Response(statut, text="edge"), httpx.Response(200, text=sse("ok"))]
    )
    async with _provider() as provider:
        assert await provider.complete(MESSAGES) == "ok"
    assert route.call_count == 2, f"{statut} devrait être réessayé"


@pytest.mark.parametrize("statut", [400, 401, 403, 404, 422, 501])
@respx.mock
async def test_les_refus_definitifs_ne_sont_pas_reessayes(statut: int) -> None:
    """Contrepartie : élargir le réessai ne doit pas le rendre aveugle.

    Une requête malformée ou une clé invalide ne deviendra pas valide au
    deuxième essai — insister ne ferait que tripler le délai avant l'erreur.
    """
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(statut, json={"error": "non"}))
    async with _provider() as provider:
        with pytest.raises(ProviderError):
            await provider.complete(MESSAGES)
    assert route.call_count == 1, f"{statut} ne doit pas être réessayé"
