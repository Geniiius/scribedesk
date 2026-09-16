# SPDX-License-Identifier: MIT
"""Contrat commun à tous les fournisseurs de modèles.

Un fournisseur expose une seule opération utile — produire du texte à partir
d'une conversation — sous deux formes : :meth:`Provider.stream`, qui rend la
main à chaque fragment, et :meth:`Provider.complete`, qui attend la réponse
entière. La seconde est construite sur la première, de sorte qu'une
implémentation n'a qu'un point d'entrée à écrire.

Toutes les erreurs réseau ou protocolaires sont converties en
:class:`ProviderError`. L'interface graphique n'a donc jamais à connaître
`httpx`, ni les codes HTTP propres à chaque service.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import json
import random
import ssl
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import httpx

__all__ = [
    "AuthenticationError",
    "Message",
    "ModelInfo",
    "Provider",
    "ProviderError",
    "ProviderUnavailable",
    "RateLimitError",
]

Role = Literal["system", "user", "assistant"]

#: Codes HTTP pour lesquels une nouvelle tentative a des chances d'aboutir.
#:
#: La seconde famille (515, 520-527) ne vient pas du fournisseur mais de ce qui
#: se trouve entre lui et nous : passerelle d'entreprise, pare-feu inspectant le
#: TLS, réseau de diffusion. Observé en conditions réelles sur un poste
#: d'administration — un « 515 Upstream Certificate Untrusted » au milieu d'une
#: série d'appels réussis, avec le suivant qui passe sans rien changer.
#:
#: Ces codes étaient auparavant traités comme définitifs : l'action échouait
#: sous les yeux de l'utilisateur alors qu'un simple réessai l'aurait sauvée.
_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset(
    {
        # Côté fournisseur : surcharge, indisponibilité passagère, quota.
        408,
        409,
        425,
        429,
        500,
        502,
        503,
        504,
        # Côté intermédiaire : certificat, poignée de main, origine injoignable.
        515,
        520,
        521,
        522,
        523,
        524,
        525,
        526,
        527,
    }
)


# --------------------------------------------------------------------------
# Erreurs
# --------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """Erreur générique remontée par un fournisseur.

    Attributes:
        provider: nom du fournisseur concerné.
        retryable: indique si relancer la même requête a du sens.
    """

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class AuthenticationError(ProviderError):
    """Clé d'API absente, invalide ou révoquée."""


class RateLimitError(ProviderError):
    """Quota atteint. `retry_after` porte le délai conseillé, en secondes."""

    def __init__(self, message: str, *, provider: str = "", retry_after: float | None = None):
        super().__init__(message, provider=provider, retryable=True)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Service injoignable : panne réseau, serveur local éteint, DNS…"""

    def __init__(self, message: str, *, provider: str = "") -> None:
        super().__init__(message, provider=provider, retryable=True)


# --------------------------------------------------------------------------
# Types de données
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    """Un tour de conversation."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Un modèle proposé par le fournisseur."""

    id: str
    label: str = ""

    def __str__(self) -> str:
        return self.label or self.id


@dataclass(slots=True)
class RetryPolicy:
    """Paramètres du réessai avec repli exponentiel et gigue."""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int, *, suggested: float | None = None) -> float:
        """Calcule l'attente avant la tentative `attempt` (indexée à partir de 0).

        La gigue aléatoire évite que plusieurs clients repartis en même temps ne
        retombent en choeur sur le serveur au même instant.
        """
        if suggested is not None:
            return min(suggested, self.max_delay)
        window = min(self.base_delay * 2**attempt, self.max_delay)
        return random.uniform(window / 2, window)


#: Hôtes désignant la machine elle-même.
_LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _points_to_localhost(base_url: str) -> bool:
    """Détermine si une URL désigne un service hébergé sur ce poste.

    Permet à un point d'accès personnalisé — LM Studio, llama.cpp, vLLM lancé
    en local — d'être correctement rapporté comme local dans l'audit, au lieu
    d'être compté comme une sortie réseau qu'il n'est pas.
    """
    if not base_url:
        return False
    from urllib.parse import urlparse

    hote = urlparse(base_url).hostname
    return hote is not None and hote.lower() in _LOCAL_HOSTS


def _default_ssl_context() -> ssl.SSLContext:
    """Crée un contexte SSL utilisant les certificats du magasin système."""
    ctx = ssl.create_default_context()
    with contextlib.suppress(Exception):
        ctx.load_default_certs()
    return ctx


# --------------------------------------------------------------------------
# Classe de base
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Provider(abc.ABC):
    """Base commune des fournisseurs.

    Le client HTTP est créé paresseusement, à la première requête, et réutilisé
    ensuite : ouvrir une connexion TLS coûte plus cher que l'appel lui-même sur
    des textes courts, et l'assistant est justement sollicité par rafales.
    """

    model: str
    base_url: str = ""
    api_key: str = ""
    timeout: float = 60.0
    temperature: float = 0.3
    max_tokens: int | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    # -- À implémenter par les sous-classes -------------------------------

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Nom lisible du fournisseur."""

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool:
        """Indique si une clé d'API est nécessaire pour émettre une requête."""

    @property
    def is_local(self) -> bool:
        """Indique si l'inférence a lieu sur ce poste, sans sortie réseau.

        Distinct de `requires_api_key` : un service distant peut être gratuit et
        sans clé, un service local peut en exiger une. C'est bien la *sortie de
        la machine* qui compte pour le journal d'audit, et c'est la seule chose
        qu'un délégué à la protection des données veut savoir.

        La base suppose un service distant : c'est l'hypothèse prudente. Une
        implémentation locale doit le déclarer explicitement.
        """
        return _points_to_localhost(self.base_url)

    @abc.abstractmethod
    def _endpoint(self) -> str:
        """URL absolue de l'API de complétion."""

    @abc.abstractmethod
    def _payload(self, messages: Sequence[Message], *, stream: bool) -> dict[str, Any]:
        """Corps JSON de la requête."""

    @abc.abstractmethod
    def _decode(self, chunk: Mapping[str, Any]) -> str:
        """Extrait le fragment de texte d'un événement de flux."""

    def _headers(self) -> dict[str, str]:
        """En-têtes HTTP. Surchargée pour les schémas d'authentification exotiques."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # -- Cycle de vie -----------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        """Le client HTTP partagé, créé à la demande."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
                verify=_default_ssl_context(),
            )
        return self._client

    async def aclose(self) -> None:
        """Ferme le client HTTP. Idempotent."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> Provider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- API publique -----------------------------------------------------

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Produit la réponse fragment par fragment.

        Yields:
            Les morceaux de texte, dans l'ordre. Aucun n'est vide.

        Raises:
            ProviderError: ou l'une de ses sous-classes, en cas d'échec.
        """
        self._check_ready()
        last_error: ProviderError | None = None

        for attempt in range(self.retry.attempts):
            # Un réessai ne peut avoir lieu qu'avant le premier fragment. Une
            # fois du texte transmis à l'appelant, relancer la requête
            # concaténerait deux réponses partielles : l'erreur est propagée.
            produced = False
            try:
                async for piece in self._stream_once(messages):
                    produced = True
                    yield piece
                if produced:
                    return
                last_error = ProviderError(
                    "Le modèle n'a renvoyé aucun texte.", provider=self.name, retryable=True
                )
            except ProviderError as exc:
                if produced or not exc.retryable:
                    raise
                last_error = exc
            except (httpx.TransportError, httpx.StreamError) as exc:
                if produced:
                    raise ProviderError(
                        f"Flux interrompu par {self.name} : {exc}", provider=self.name
                    ) from exc
                last_error = ProviderUnavailable(str(exc), provider=self.name)

            if attempt + 1 < self.retry.attempts:
                suggested = getattr(last_error, "retry_after", None)
                await asyncio.sleep(self.retry.delay_for(attempt, suggested=suggested))

        raise last_error or ProviderError("Échec inconnu.", provider=self.name)

    async def complete(self, messages: Sequence[Message]) -> str:
        """Renvoie la réponse complète, une fois le flux épuisé."""
        parts: list[str] = []
        async for piece in self.stream(messages):
            parts.append(piece)
        return "".join(parts).strip()

    async def check(self) -> str:
        """Vérifie la configuration par un appel minimal.

        Returns:
            Le texte renvoyé par le modèle, utile pour l'afficher tel quel dans
            les préférences.
        """
        reply = await self.complete([Message("user", "Réponds exactement : OK")])
        return reply or "(réponse vide)"

    # -- Interne ----------------------------------------------------------

    def _check_ready(self) -> None:
        if self.requires_api_key and not self.api_key:
            raise AuthenticationError(
                f"Aucune clé d'API n'est configurée pour {self.name}.", provider=self.name
            )
        if not self.model:
            raise ProviderError(f"Aucun modèle sélectionné pour {self.name}.", provider=self.name)

    async def _stream_once(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Une tentative unique, sans réessai."""
        request = self.client.build_request(
            "POST",
            self._endpoint(),
            json=self._payload(messages, stream=True),
            headers=self._headers(),
        )
        response = await self.client.send(request, stream=True)
        try:
            if response.status_code >= 400:
                await response.aread()
                raise self._error_for(response)
            async for event in self._iter_events(response):
                text = self._decode(event)
                if text:
                    yield text
        finally:
            await response.aclose()

    async def _iter_events(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        """Décode un flux ``text/event-stream`` ou JSON-lines.

        Les deux formats coexistent dans l'écosystème — SSE côté OpenAI, JSON
        par ligne côté Ollama — et se distinguent au préfixe ``data:``.
        """
        async for raw in response.aiter_lines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
                if line == "[DONE]":
                    return
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload

    def _error_for(self, response: httpx.Response) -> ProviderError:
        """Traduit une réponse HTTP en erreur métier."""
        detail = _extract_message(response) or response.reason_phrase
        status = response.status_code

        if status in (401, 403):
            return AuthenticationError(
                f"Authentification refusée par {self.name} : {detail}", provider=self.name
            )
        if status == 429:
            return RateLimitError(
                f"Quota atteint sur {self.name} : {detail}",
                provider=self.name,
                retry_after=_retry_after(response),
            )
        if status == 404:
            return ProviderError(
                f"Modèle ou URL introuvable sur {self.name} : {detail}", provider=self.name
            )
        return ProviderError(
            f"{self.name} a répondu {status} : {detail}",
            provider=self.name,
            retryable=status in _RETRYABLE_STATUS,
        )


def _extract_message(response: httpx.Response) -> str:
    """Récupère le message d'erreur, quel que soit l'emballage JSON du service."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip()

    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("detail")
            if isinstance(message, str):
                return message
        if isinstance(error, str):
            return error
    return str(body)[:300]


def _retry_after(response: httpx.Response) -> float | None:
    """Lit l'en-tête ``Retry-After`` s'il est exprimé en secondes."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def system_and_user(system: str, user: str) -> list[Message]:
    """Raccourci pour la conversation à deux tours utilisée par les actions."""
    messages: list[Message] = []
    if system:
        messages.append(Message("system", system))
    messages.append(Message("user", user))
    return messages


def join_instructions(parts: Iterable[str]) -> str:
    """Concatène des consignes non vides en un seul bloc système."""
    return "\n\n".join(part.strip() for part in parts if part and part.strip())
