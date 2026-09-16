# SPDX-License-Identifier: MIT
"""Ollama — inférence locale, aucune donnée ne quitte le poste.

C'est le fournisseur recommandé en administration : il rend l'anonymisation
facultative plutôt qu'indispensable, et supprime toute question de transfert
hors Union européenne.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from .base import Message, ModelInfo, Provider, ProviderUnavailable, _points_to_localhost

__all__ = ["OllamaProvider"]


@dataclass(slots=True)
class OllamaProvider(Provider):
    """Client de l'API native d'Ollama (``/api/chat``)."""

    display_name: ClassVar[str] = "Ollama (local)"
    default_base_url: ClassVar[str] = "http://localhost:11434"
    suggested_models: ClassVar[tuple[ModelInfo, ...]] = (
        ModelInfo("llama3.1:8b", "Llama 3.1 8B — 5 Go de RAM"),
        ModelInfo("mistral:7b", "Mistral 7B — francophone solide"),
        ModelInfo("qwen2.5:14b", "Qwen 2.5 14B — 10 Go de RAM"),
    )

    @property
    def name(self) -> str:
        return self.display_name

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def is_local(self) -> bool:
        """Ollama s'exécute sur le poste — sauf si l'URL a été détournée ailleurs.

        Le réglage accepte une URL arbitraire : pointer vers un Ollama hébergé
        sur un serveur distant est légitime, mais alors les données sortent bel
        et bien de la machine. L'audit doit le refléter.
        """
        root = self.base_url or self.default_base_url
        return _points_to_localhost(root)

    def _root(self) -> str:
        return (self.base_url or self.default_base_url).rstrip("/")

    def _endpoint(self) -> str:
        return f"{self._root()}/api/chat"

    def _payload(self, messages: Sequence[Message], *, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": self.temperature}
        if self.max_tokens:
            options["num_predict"] = self.max_tokens
        return {
            "model": self.model,
            "messages": [m.as_dict() for m in messages],
            "stream": stream,
            "options": options,
        }

    def _decode(self, chunk: Mapping[str, Any]) -> str:
        message = chunk.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                return content
        # Ollama expose aussi /api/generate, dont le champ diffère.
        fallback = chunk.get("response")
        return fallback if isinstance(fallback, str) else ""

    async def available_models(self) -> tuple[ModelInfo, ...]:
        """Interroge le démon local pour lister les modèles réellement installés.

        Contrairement aux services distants, Ollama sait exactement ce qui est
        présent sur la machine : autant proposer la vraie liste plutôt qu'un
        catalogue théorique dont la moitié n'est pas téléchargée.
        """
        try:
            response = await self.client.get(f"{self._root()}/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"Ollama est injoignable sur {self._root()}. Le service est-il démarré ?",
                provider=self.name,
            ) from exc

        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, Mapping) else []
        found = tuple(
            ModelInfo(entry["name"], entry["name"])
            for entry in models
            if isinstance(entry, Mapping) and isinstance(entry.get("name"), str)
        )
        return found or self.suggested_models
