# SPDX-License-Identifier: MIT
"""Fournisseurs parlant le dialecte ``/v1/chat/completions`` d'OpenAI.

Groq, Together, Mistral, OpenRouter, DeepSeek, LM Studio, vLLM et OpenAI
lui-même exposent la même API. Une seule implémentation les couvre donc tous :
seules changent l'URL de base et la liste de modèles suggérés.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from .base import Message, ModelInfo, Provider

__all__ = [
    "GroqProvider",
    "MistralProvider",
    "NvidiaProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
]


@dataclass(slots=True)
class OpenAICompatibleProvider(Provider):
    """Client générique pour toute API compatible OpenAI."""

    #: Valeurs par défaut, surchargées par les sous-classes.
    display_name: ClassVar[str] = "API compatible OpenAI"
    default_base_url: ClassVar[str] = "https://api.openai.com/v1"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = ()
    needs_key: ClassVar[bool] = True

    @property
    def name(self) -> str:
        return self.display_name

    @property
    def requires_api_key(self) -> bool:
        return self.needs_key

    def _endpoint(self) -> str:
        root = (self.base_url or self.default_base_url).rstrip("/")
        # Tolère aussi bien « …/v1 » que « …/v1/chat/completions » dans les
        # préférences : les deux formes circulent dans les documentations.
        if root.endswith("/chat/completions"):
            return root
        return f"{root}/chat/completions"

    def _payload(self, messages: Sequence[Message], *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.as_dict() for m in messages],
            "temperature": self.temperature,
            "stream": stream,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        return payload

    def _decode(self, chunk: Mapping[str, Any]) -> str:
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, Mapping):
            return ""
        # `delta` en mode flux, `message` si le serveur ignore stream=true.
        holder = first.get("delta") or first.get("message") or {}
        if not isinstance(holder, Mapping):
            return ""
        content = holder.get("content")
        return content if isinstance(content, str) else ""


@dataclass(slots=True)
class OpenAIProvider(OpenAICompatibleProvider):
    display_name: ClassVar[str] = "OpenAI"
    default_base_url: ClassVar[str] = "https://api.openai.com/v1"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = (
        ModelInfo("gpt-4o-mini", "GPT-4o mini — rapide et économique"),
        ModelInfo("gpt-4o", "GPT-4o — le plus capable"),
    )


@dataclass(slots=True)
class GroqProvider(OpenAICompatibleProvider):
    """Groq — inférence très rapide, palier gratuit généreux."""

    display_name: ClassVar[str] = "Groq"
    default_base_url: ClassVar[str] = "https://api.groq.com/openai/v1"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = (
        ModelInfo("openai/gpt-oss-120b", "GPT-OSS 120B — qualité de rédaction"),
        ModelInfo("llama-3.3-70b-versatile", "Llama 3.3 70B — polyvalent"),
        ModelInfo("llama-3.1-8b-instant", "Llama 3.1 8B — latence minimale"),
    )


@dataclass(slots=True)
class MistralProvider(OpenAICompatibleProvider):
    """Mistral — hébergement européen, argument de poids en secteur public."""

    display_name: ClassVar[str] = "Mistral"
    default_base_url: ClassVar[str] = "https://api.mistral.ai/v1"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = (
        ModelInfo("mistral-large-latest", "Mistral Large — qualité maximale"),
        ModelInfo("mistral-small-latest", "Mistral Small — bon compromis"),
    )


@dataclass(slots=True)
class NvidiaProvider(OpenAICompatibleProvider):
    """NVIDIA NIM (build.nvidia.com) — modèles open-source avec clés API gratuites."""

    display_name: ClassVar[str] = "NVIDIA NIM (build.nvidia.com)"
    default_base_url: ClassVar[str] = "https://integrate.api.nvidia.com/v1"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = (
        ModelInfo("meta/llama-3.3-70b-instruct", "Llama 3.3 70B — performant et précis"),
        ModelInfo("meta/llama-3.1-70b-instruct", "Llama 3.1 70B — polyvalent"),
        ModelInfo("meta/llama-3.1-8b-instruct", "Llama 3.1 8B — ultra-rapide"),
        ModelInfo("mistralai/mistral-large-2411", "Mistral Large (2411) — haute qualité"),
        ModelInfo("deepseek-ai/deepseek-r1", "DeepSeek R1 — raisonnement poussé"),
        ModelInfo("qwen/qwen2.5-72b-instruct", "Qwen 2.5 72B — excellent en français"),
    )
