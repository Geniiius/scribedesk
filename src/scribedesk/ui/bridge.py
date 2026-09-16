# SPDX-License-Identifier: MIT
"""Passerelle entre la boucle asyncio des fournisseurs et celle de Qt.

Qt et asyncio ont chacun leur boucle d'événements, et aucune des deux ne peut
tourner dans l'autre. Plutôt que d'ajouter une dépendance comme *qasync*, on
héberge une boucle asyncio dans un fil dédié et l'on communique par signaux Qt,
qui sont justement conçus pour franchir les frontières de fils.

Conséquence pratique : l'interface ne se fige jamais pendant un appel réseau,
et le texte s'affiche au fur et à mesure de son arrivée.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

__all__ = ["AsyncRunner", "StreamHandle"]

logger = logging.getLogger(__name__)


class StreamHandle(QObject):
    """Suit une génération en cours et en rapporte l'avancement.

    Les trois signaux s'excluent : `finished` ou `failed` est émis une seule
    fois, jamais les deux, et toujours après le dernier `chunk`.
    """

    chunk = Signal(str)
    """Un fragment de texte vient d'arriver."""

    finished = Signal(str)
    """La génération est terminée ; porte le texte complet."""

    failed = Signal(str)
    """La génération a échoué ; porte un message destiné à l'utilisateur."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancelled = threading.Event()
        self._future: Future[Any] | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Demande l'arrêt. Les fragments déjà émis restent affichés."""
        self._cancelled.set()
        if self._future is not None:
            self._future.cancel()

    def _attach(self, future: Future[Any]) -> None:
        self._future = future


class AsyncRunner(QObject):
    """Héberge une boucle asyncio dans un fil de discussion dédié.

    Une seule instance suffit pour toute l'application : les appels y sont
    sérialisés par la boucle elle-même, et le fil reste vivant entre deux
    requêtes pour préserver les connexions HTTP ouvertes.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # Les générations en cours sont retenues ici. Sans cela, un appelant
        # qui écrit `runner.run_stream(f).finished.connect(...)` sans garder le
        # handle verrait l'objet ramassé par le GC, et ses signaux disparaître
        # sans le moindre message d'erreur.
        self._inflight: set[StreamHandle] = set()

    # -- Cycle de vie -----------------------------------------------------

    def start(self) -> None:
        """Démarre le fil et sa boucle. Sans effet s'il tourne déjà."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="scribedesk-async", daemon=True)
        self._thread.start()
        # Attendre que la boucle existe évite une course au tout premier appel.
        self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        """Arrête proprement la boucle et attend la fin du fil."""
        for handle in list(self._inflight):
            handle.cancel()
        self._inflight.clear()

        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5.0)
        self._loop = None
        self._thread = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                _cancel_pending(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    # -- Soumission -------------------------------------------------------

    def run_stream(
        self, factory: Callable[[], AsyncIterator[str]], parent: QObject | None = None
    ) -> StreamHandle:
        """Consomme un générateur asynchrone et en relaie les fragments.

        Args:
            factory: fonction sans argument renvoyant le générateur. C'est une
                fabrique et non le générateur lui-même, car celui-ci doit être
                créé *dans* la boucle qui le consommera.
            parent: parent Qt du handle, pour la durée de vie de l'objet.

        Returns:
            Un :class:`StreamHandle` sur lequel se connecter.

        La soumission est volontairement différée d'un tour de boucle Qt. Si la
        coroutine démarrait immédiatement, une génération très courte — modèle
        local, réponse en cache, erreur immédiate — pourrait émettre ses signaux
        *avant* que l'appelant, qui branche ses `connect` à la ligne suivante,
        ne soit prêt à les recevoir. Les fragments seraient alors perdus sans
        aucune trace. Le report garantit que les connexions sont en place.
        """
        handle = StreamHandle(parent)
        self._inflight.add(handle)
        handle.finished.connect(lambda _: self._release(handle))
        handle.failed.connect(lambda _: self._release(handle))

        self.start()
        QTimer.singleShot(0, lambda: self._submit(factory, handle))
        return handle

    def _release(self, handle: StreamHandle) -> None:
        """Cesse de retenir une génération terminée."""
        self._inflight.discard(handle)

    def _submit(self, factory: Callable[[], AsyncIterator[str]], handle: StreamHandle) -> None:
        """Confie réellement le générateur à la boucle asyncio."""
        if handle.cancelled:
            return
        loop = self._loop
        if loop is None:  # pragma: no cover - défensif
            handle.failed.emit("La boucle asynchrone n'a pas pu démarrer.")
            return
        future = asyncio.run_coroutine_threadsafe(self._pump(factory, handle), loop)
        handle._attach(future)

    @staticmethod
    async def _pump(factory: Callable[[], AsyncIterator[str]], handle: StreamHandle) -> None:
        """Parcourt le générateur et émet les signaux correspondants."""
        parts: list[str] = []
        try:
            async for piece in factory():
                if handle.cancelled:
                    break
                parts.append(piece)
                handle.chunk.emit(piece)
        except asyncio.CancelledError:
            handle.failed.emit("Génération annulée.")
            raise
        except Exception as exc:
            logger.exception("Échec de la génération")
            handle.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            handle.finished.emit("".join(parts).strip())

    def run_coroutine(self, factory: Callable[[], Any]) -> Future[Any]:
        """Soumet une coroutine et renvoie son `Future`, pour les tâches ponctuelles.

        Utilisé par le test de connexion des préférences, qui attend un résultat
        unique plutôt qu'un flux.
        """
        self.start()
        loop = self._loop
        if loop is None:  # pragma: no cover - défensif
            failed: Future[Any] = Future()
            failed.set_exception(RuntimeError("Boucle asynchrone indisponible."))
            return failed
        return asyncio.run_coroutine_threadsafe(factory(), loop)


def _cancel_pending(loop: asyncio.AbstractEventLoop) -> None:
    """Annule les tâches restantes avant de fermer la boucle."""
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
