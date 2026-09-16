# SPDX-License-Identifier: MIT
"""Rangement des clés d'API dans le trousseau du système d'exploitation.

`keyring` est une dépendance optionnelle : le coeur doit rester installable
sans elle. Quand elle manque — ou quand aucun coffre n'est disponible, cas
courant sur un serveur Linux sans session graphique — on se rabat sur la
variable d'environnement ``SCRIBEDESK_API_KEY``, en lecture seule.

Aucune écriture de clé sur disque n'est prévue. C'est une décision de
conception, pas un oubli : si le trousseau est indisponible, mieux vaut le dire
franchement à l'utilisateur que déposer un secret en clair dans son profil.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

from .config import KEYRING_SERVICE

__all__ = [
    "KeyringUnavailable",
    "delete_api_key",
    "get_api_key",
    "keyring_available",
    "set_api_key",
]

logger = logging.getLogger(__name__)

#: Repli en lecture seule, utile en conteneur ou en intégration continue.
ENV_VAR: Final = "SCRIBEDESK_API_KEY"


class KeyringUnavailable(RuntimeError):
    """Aucun coffre-fort système n'est accessible sur cette machine."""


def _backend() -> Any:
    """Renvoie le module `keyring`, ou lève si le coffre est inutilisable.

    Typé `Any` : `keyring` est une dépendance optionnelle, absente de
    l'installation minimale, et ne fournit pas de stubs.
    """
    try:
        import keyring
        from keyring.errors import NoKeyringError
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise KeyringUnavailable(
            "Le module « keyring » n'est pas installé. "
            "Installez ScribeDesk avec l'extra « gui », ou définissez "
            f"la variable d'environnement {ENV_VAR}."
        ) from exc

    try:
        if keyring.get_keyring() is None:
            raise NoKeyringError
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        raise KeyringUnavailable(f"Aucun trousseau disponible : {exc}") from exc
    return keyring


def keyring_available() -> bool:
    """Indique si un coffre système est utilisable, sans lever d'exception."""
    try:
        _backend()
    except KeyringUnavailable:
        return False
    return True


def get_api_key(provider_key: str) -> str:
    """Lit la clé du fournisseur.

    L'environnement a la priorité : cela permet de surcharger ponctuellement la
    configuration sans toucher au trousseau, par exemple lors d'un test.

    Returns:
        La clé, ou une chaîne vide si aucune n'est enregistrée.
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env

    try:
        stored = _backend().get_password(KEYRING_SERVICE, provider_key)
    except KeyringUnavailable:
        return ""
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        logger.warning("Lecture du trousseau impossible : %s", exc)
        return ""
    return (stored or "").strip()


def set_api_key(provider_key: str, api_key: str) -> None:
    """Enregistre (ou efface, si `api_key` est vide) la clé du fournisseur.

    Raises:
        KeyringUnavailable: si aucun coffre système n'est accessible.
    """
    if not api_key.strip():
        delete_api_key(provider_key)
        return
    _backend().set_password(KEYRING_SERVICE, provider_key, api_key.strip())


def delete_api_key(provider_key: str) -> None:
    """Supprime la clé du fournisseur. Sans effet si elle n'existe pas."""
    try:
        backend = _backend()
    except KeyringUnavailable:
        return
    try:
        backend.delete_password(KEYRING_SERVICE, provider_key)
    except Exception:
        logger.debug("Aucune clé à supprimer pour %s", provider_key)
