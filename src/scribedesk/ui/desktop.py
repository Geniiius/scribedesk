# SPDX-License-Identifier: MIT
"""Intégration au bureau : sélection courante et raccourci clavier global.

Deux opérations reposent nécessairement sur des mécanismes propres au système :
lire le texte sélectionné dans une *autre* application, et capter une
combinaison de touches alors que l'application n'a pas le focus. Elles sont
regroupées ici pour que le reste de l'interface reste ignorante de la
plateforme.

La lecture de sélection passe par une simulation de Ctrl+C. C'est la seule
méthode qui fonctionne uniformément d'un traitement de texte à un navigateur ou
à un outil de ticketing : il n'existe pas d'API portable pour interroger la
sélection d'un processus tiers. Le presse-papiers antérieur est sauvegardé puis
restauré, afin de ne pas déposséder l'utilisateur de ce qu'il y avait rangé.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import time
from collections.abc import Callable
from typing import Any, Final

from PySide6.QtGui import QGuiApplication

__all__ = ["HotkeyListener", "capture_selection", "normalise_hotkey", "replace_selection"]

logger = logging.getLogger(__name__)

#: Délai unitaire laissé à l'application source pour honorer le Ctrl+C simulé.
_CLIPBOARD_SETTLE: Final = 0.04

#: Nombre de relectures du presse-papiers avant d'abandonner (12 * 0.04s = ~0.48s max).
_CLIPBOARD_POLLS: Final = 12


def _release_modifiers(keyboard: Any) -> None:
    """Relâche les touches que le raccourci global a pu laisser enfoncées.

    Simuler Ctrl+C pendant que Ctrl+Espace maintient encore Ctrl produit une
    combinaison que l'application visée n'attend pas, et la copie échoue sans
    rien signaler. On repart d'un clavier au repos plutôt que de parier sur le
    moment où l'utilisateur relâche.

    Chaque relâchement est protégé : `pynput` lève sur une touche qu'il ne
    connaît pas pour la disposition courante, et l'échec d'une touche ne doit
    pas empêcher les suivantes.
    """
    from pynput.keyboard import Key

    for touche in (
        Key.space,
        Key.ctrl,
        Key.ctrl_l,
        Key.ctrl_r,
        Key.alt,
        Key.alt_l,
        Key.alt_r,
        Key.shift,
        Key.shift_l,
        Key.shift_r,
    ):
        with contextlib.suppress(Exception):
            keyboard.release(touche)


def _controller() -> Any:
    """Renvoie un contrôleur clavier `pynput`.

    Le type de retour est `Any` : `pynput` ne fournit pas de stubs, et
    l'importer au niveau du module rendrait le paquet inimportable là où il
    n'est pas installé.
    """
    from pynput.keyboard import Controller

    return Controller()


def _copy_combo() -> tuple[object, str]:
    """Renvoie ``(modificateur, touche)`` pour la copie sur cette plateforme."""
    from pynput.keyboard import Key

    modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
    return modifier, "c"


def capture_selection(
    *,
    restore_clipboard: bool = True,
    fallback_to_clipboard: bool = True,
) -> str:
    """Renvoie le texte actuellement sélectionné dans l'application au premier plan.

    Args:
        restore_clipboard: remettre l'ancien contenu du presse-papiers après
            lecture. Laisser à `True` en usage courant ; le passer à `False`
            quand on s'apprête justement à écrire dans le presse-papiers.
        fallback_to_clipboard: en cas d'échec de la copie simulée (ex: application
            avec privilèges élevés ou contrôle personnalisé), utiliser le texte
            déjà présent dans le presse-papiers.

    Returns:
        Le texte sélectionné, ou une chaîne vide si la sélection est vide ou
        si la copie n'a pas abouti.
    """
    clipboard = QGuiApplication.clipboard()
    # Les stubs Qt déclarent un retour non optionnel, mais sans QGuiApplication
    # vivante l'appel renvoie bien None à l'exécution.
    if clipboard is None:  # pragma: no cover - sans serveur graphique
        return ""  # type: ignore[unreachable]

    from PySide6.QtCore import QCoreApplication

    QCoreApplication.processEvents()
    previous = clipboard.text()
    # Un marqueur distinct permet de distinguer « la copie n'a rien produit »
    # de « la sélection était identique au presse-papiers précédent ».
    sentinel = f"\x00scribedesk\x00{time.monotonic_ns()}"
    clipboard.setText(sentinel)
    QCoreApplication.processEvents()

    try:
        # `_controller` importe `pynput` : c'est lui qui lève l'ImportError
        # rattrapée plus bas quand le paquet est absent.
        keyboard = _controller()
        _release_modifiers(keyboard)

        time.sleep(0.02)
        modifier, key = _copy_combo()
        with keyboard.pressed(modifier):
            keyboard.press(key)
            keyboard.release(key)
    except ImportError:
        logger.warning("pynput est absent : la capture de sélection est indisponible.")
        clipboard.setText(previous)
        return ""
    except Exception as exc:
        logger.warning("Copie simulée impossible : %s", exc)
        clipboard.setText(previous)
        return ""

    captured = ""
    for _ in range(_CLIPBOARD_POLLS):
        QCoreApplication.processEvents()
        time.sleep(_CLIPBOARD_SETTLE)
        QCoreApplication.processEvents()
        current = clipboard.text()
        if current and current != sentinel:
            captured = current
            break

    # Si la copie simulée n'a rien donné mais que le presse-papiers contenait déjà du texte
    if (
        not captured
        and fallback_to_clipboard
        and previous
        and not previous.startswith("\x00scribedesk\x00")
    ):
        logger.info("Copie simulée sans résultat : repli sur le presse-papiers existant.")
        captured = previous

    if restore_clipboard and captured != previous:
        clipboard.setText(previous)
        QCoreApplication.processEvents()
    elif captured:
        clipboard.setText(captured)
        QCoreApplication.processEvents()

    return captured.strip()


def replace_selection(text: str) -> bool:
    """Remplace la sélection courante par `text`, via le presse-papiers.

    Returns:
        `True` si le collage a été déclenché. Le succès réel dépend de
        l'application cible, qui peut refuser le collage.
    """
    clipboard = QGuiApplication.clipboard()
    # Les stubs Qt déclarent un retour non optionnel, mais sans QGuiApplication
    # vivante l'appel renvoie bien None à l'exécution.
    if clipboard is None:  # pragma: no cover - sans serveur graphique
        return False  # type: ignore[unreachable]

    from PySide6.QtCore import QCoreApplication

    clipboard.setText(text)
    QCoreApplication.processEvents()

    try:
        from pynput.keyboard import Key

        keyboard = _controller()
        _release_modifiers(keyboard)

        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        time.sleep(0.04)
        with keyboard.pressed(modifier):
            keyboard.press("v")
            keyboard.release("v")
    except ImportError:
        logger.warning("pynput est absent : le texte reste dans le presse-papiers.")
        return False
    except Exception as exc:
        logger.warning("Collage simulé impossible : %s", exc)
        return False
    return True


def normalise_hotkey(shortcut: str) -> str:
    """Traduit « ctrl+space » vers la syntaxe attendue par pynput.

    `pynput` réclame des chevrons autour des modificateurs et des touches
    nommées — ``<ctrl>+<space>`` — alors que la forme lisible, celle qu'un
    utilisateur écrit dans ses préférences, ne les a pas.
    """
    named = {
        "ctrl",
        "control",
        "alt",
        "alt_gr",
        "shift",
        "cmd",
        "super",
        "win",
        "space",
        "tab",
        "enter",
        "return",
        "esc",
        "escape",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "up",
        "down",
        "left",
        "right",
        *(f"f{n}" for n in range(1, 25)),
    }
    aliases = {"control": "ctrl", "win": "cmd", "super": "cmd", "return": "enter", "escape": "esc"}

    parts: list[str] = []
    for raw in shortcut.replace(" ", "").split("+"):
        token = aliases.get(raw.lower(), raw.lower())
        if not token:
            continue
        parts.append(f"<{token}>" if token in named else token)
    return "+".join(parts)


class HotkeyListener:
    """Écoute une combinaison de touches globale.

    L'écouteur `pynput` tourne dans son propre fil. Le callback est donc appelé
    *hors* du fil Qt : il doit se contenter de programmer un traitement sur la
    boucle Qt (typiquement via un signal), et jamais toucher directement à un
    widget.
    """

    __slots__ = ("_callback", "_listener", "_shortcut")

    def __init__(self, shortcut: str, callback: Callable[[], None]) -> None:
        self._shortcut = shortcut
        self._callback = callback
        self._listener: object | None = None

    @property
    def shortcut(self) -> str:
        return self._shortcut

    @property
    def running(self) -> bool:
        return self._listener is not None

    def start(self) -> bool:
        """Démarre l'écoute.

        Returns:
            `True` si le raccourci a pu être enregistré. Un échec est fréquent
            et bénin : la combinaison peut être déjà prise par le système ou par
            une autre application.
        """
        self.stop()
        try:
            from pynput.keyboard import GlobalHotKeys

            listener = GlobalHotKeys({normalise_hotkey(self._shortcut): self._callback})
            listener.daemon = True
            listener.start()
        except ImportError:
            logger.warning("pynput est absent : aucun raccourci global.")
            return False
        except Exception as exc:
            logger.warning("Raccourci « %s » non enregistré : %s", self._shortcut, exc)
            return False

        self._listener = listener
        return True

    def stop(self) -> None:
        """Arrête l'écoute. Sans effet si elle n'a pas démarré."""
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Arrêt de l'écouteur de raccourci sans effet.")

    def rebind(self, shortcut: str) -> bool:
        """Change la combinaison écoutée."""
        self._shortcut = shortcut
        return self.start()
