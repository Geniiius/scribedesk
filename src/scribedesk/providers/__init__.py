# SPDX-License-Identifier: MIT
"""Catalogue des fournisseurs de modèles et fabrique associée."""

from __future__ import annotations

from typing import Final

from .base import (
    AuthenticationError,
    Message,
    ModelInfo,
    Provider,
    ProviderError,
    ProviderUnavailable,
    RateLimitError,
    RetryPolicy,
    join_instructions,
    system_and_user,
)
from .ollama import OllamaProvider
from .openai_compat import (
    GroqProvider,
    MistralProvider,
    NvidiaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
)

__all__ = [
    "PROVIDERS",
    "AuthenticationError",
    "GroqProvider",
    "Message",
    "MistralProvider",
    "ModelInfo",
    "NvidiaProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "RateLimitError",
    "RetryPolicy",
    "build_provider",
    "describe",
    "join_instructions",
    "system_and_user",
]

#: Identifiant stable (celui écrit dans le fichier de configuration) vers classe.
#: L'ordre pilote l'affichage dans les préférences : le local d'abord, parce
#: que c'est l'option à privilégier pour des données de service public.
PROVIDERS: Final[dict[str, type[Provider]]] = {
    "ollama": OllamaProvider,
    "nvidia": NvidiaProvider,
    "groq": GroqProvider,
    "mistral": MistralProvider,
    "openai": OpenAIProvider,
    "custom": OpenAICompatibleProvider,
}


def build_provider(
    key: str,
    *,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.3,
    timeout: float = 60.0,
    max_tokens: int | None = None,
) -> Provider:
    """Instancie un fournisseur à partir de son identifiant de configuration.

    Raises:
        KeyError: si `key` ne correspond à aucun fournisseur connu.
    """
    try:
        cls = PROVIDERS[key]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise KeyError(f"Fournisseur inconnu : {key!r}. Valeurs possibles : {known}.") from None

    return cls(
        model=model or default_model(key),
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
        max_tokens=max_tokens,
    )


def describe(key: str) -> tuple[str, tuple[ModelInfo, ...], bool]:
    """Renvoie ``(libellé, modèles suggérés, clé requise)`` sans instancier."""
    cls = PROVIDERS[key]
    label = getattr(cls, "display_name", key)
    models = getattr(cls, "suggested_models", ())
    needs_key = key != "ollama"
    return label, models, needs_key


def default_model(key: str) -> str:
    """Premier modèle suggéré du fournisseur, ou chaîne vide."""
    models = getattr(PROVIDERS.get(key), "suggested_models", ())
    return models[0].id if models else ""
