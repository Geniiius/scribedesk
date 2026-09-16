# SPDX-License-Identifier: MIT
"""Garde d'instance unique, adossée à une socket locale nommée.

Deux ScribeDesk lancés en même temps enregistrent les *mêmes* raccourcis
globaux auprès du système. Le comportement devient alors indéterminé : les deux
peuvent répondre, un seul, ou aucun. Constaté en conditions réelles — une
session de test entière pendant laquelle aucune correction n'est partie, parce
qu'une instance oubliée tournait encore.

Le piège est facile : l'icône de la zone de notification est discrète, on croit
l'application fermée, on la relance. Et dans le pire des cas les deux instances
répondent, écrivent tour à tour dans le presse-papiers et collent par-dessus le
texte de l'utilisateur.

La garde transforme ce défaut en commodité : le second lancement n'ouvre pas une
seconde application, il demande à la première de se montrer, puis se termine.

Le choix de `QLocalServer` plutôt qu'un fichier de verrou est délibéré. Un
fichier survit à un plantage et bloque tous les démarrages suivants ; une socket
disparaît avec le processus qui la détenait.
"""

from __future__ import annotations

import getpass
import hashlib
import logging
from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

__all__ = ["SingleInstance"]

logger = logging.getLogger(__name__)

#: Message envoyé par le second lancement pour réveiller le premier.
_WAKE: Final = b"show"

#: Délai de connexion à l'instance existante, en millisecondes. Court : soit
#: elle répond tout de suite, soit la socket est un résidu.
_CONNECT_TIMEOUT: Final = 400


def _socket_name(base: str) -> str:
    """Compose un nom de socket propre à l'utilisateur de la session.

    Sur un poste partagé ou un serveur de sessions, deux comptes doivent pouvoir
    faire tourner leur propre instance. Le nom d'utilisateur est haché plutôt
    qu'inséré tel quel : il apparaîtrait autrement dans la liste des canaux
    nommés, visible par les autres sessions.
    """
    try:
        utilisateur = getpass.getuser()
    except Exception:
        utilisateur = "default"
    empreinte = hashlib.sha256(utilisateur.encode("utf-8")).hexdigest()[:12]
    return f"{base}-{empreinte}"


class SingleInstance(QObject):
    """Détermine si ce processus est la première instance, et relaie les réveils."""

    activated = Signal()
    """Un autre lancement a demandé à ce que l'application se montre."""

    def __init__(self, base_name: str = "scribedesk", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = _socket_name(base_name)
        self._server: QLocalServer | None = None
        self._client: QLocalSocket | None = None

    @property
    def name(self) -> str:
        """Nom effectif de la socket."""
        return self._name

    @property
    def is_primary(self) -> bool:
        """Vrai si ce processus détient la socket."""
        return self._server is not None

    # -- Acquisition ------------------------------------------------------

    def try_acquire(self) -> bool:
        """Tente de devenir l'instance principale.

        Returns:
            `True` si aucune autre instance ne tournait et que la socket a pu
            être ouverte. `False` si une instance répond déjà.

        Un échec d'ouverture *sans* instance répondante n'est pas bloquant : on
        se déclare principal malgré tout. Mieux vaut un doublon improbable qu'un
        outil qui refuse de démarrer parce qu'une socket est en mauvais état.
        """
        if self._ping():
            return False

        # La socket ne répond pas mais peut subsister après un arrêt brutal.
        # La retirer avant d'écouter évite de buter dessus indéfiniment.
        QLocalServer.removeServer(self._name)

        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            logger.warning(
                "Socket d'instance « %s » indisponible : %s. Démarrage sans garde.",
                self._name,
                server.errorString(),
            )
            return True

        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _ping(self) -> bool:
        """Vérifie qu'une instance écoute, en lui demandant de se montrer.

        Le socket est retenu sur l'objet, et non laissé en variable locale : au
        retour de la fonction il serait détruit, refermant le tube avant que le
        destinataire ait eu l'occasion de lire. Le message partait alors dans le
        vide — la connexion réussissait, le réveil n'arrivait jamais.
        """
        socket = QLocalSocket(self)
        socket.connectToServer(self._name)
        if not socket.waitForConnected(_CONNECT_TIMEOUT):
            socket.deleteLater()
            return False

        self._client = socket
        socket.write(_WAKE)
        socket.flush()
        socket.waitForBytesWritten(_CONNECT_TIMEOUT)
        # Attendre que le destinataire referme : c'est l'accusé de réception
        # implicite. Sans cela, rien ne garantit qu'il ait lu avant que ce
        # processus ne se termine.
        socket.waitForDisconnected(_CONNECT_TIMEOUT)

        logger.info("Une instance de ScribeDesk répond déjà : réveil puis sortie.")
        return True

    def signal_existing(self) -> bool:
        """Demande à l'instance en place de se montrer. Alias explicite de `_ping`."""
        return self._ping()

    # -- Réception --------------------------------------------------------

    def _on_connection(self) -> None:
        """Un second lancement nous contacte : relayer la demande d'affichage."""
        if self._server is None:  # pragma: no cover - défensif
            return
        connexion = self._server.nextPendingConnection()
        if connexion is None:  # pragma: no cover - défensif
            return  # type: ignore[unreachable]

        # Le message est minuscule et l'émetteur se déconnecte aussitôt après
        # l'avoir écrit : il est fréquemment déjà dans le tampon à cet instant.
        # Se contenter de brancher `readyRead` laisserait alors passer le seul
        # signal que l'on attend — il a été émis avant la connexion du slot.
        connexion.readyRead.connect(lambda: self._read(connexion))
        connexion.disconnected.connect(connexion.deleteLater)

        if connexion.bytesAvailable() or connexion.waitForReadyRead(_CONNECT_TIMEOUT):
            self._read(connexion)

    def _read(self, connexion: QLocalSocket) -> None:
        """Lit le message et déclenche le réveil, une seule fois par connexion."""
        charge = bytes(connexion.readAll().data())
        if charge.startswith(_WAKE):
            logger.info("Réveil demandé par un second lancement.")
            self.activated.emit()
        # Refermer signale à l'émetteur que le message est bien arrivé.
        connexion.disconnectFromServer()

    # -- Libération -------------------------------------------------------

    def release(self) -> None:
        """Ferme la socket et le canal émetteur. Idempotent."""
        if self._client is not None:
            self._client.abort()
            self._client.deleteLater()
            self._client = None
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._name)
            self._server = None
