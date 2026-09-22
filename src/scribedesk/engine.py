# SPDX-License-Identifier: MIT
"""Orchestration : action + anonymisation + fournisseur.

C'est le seul module que l'interface graphique et la ligne de commande ont
besoin de connaître. Il enchaîne toujours la même séquence :

1. l'action fournit l'invite système et le préfixe utilisateur ;
2. si la politique l'exige, le texte est anonymisé et une consigne de
   préservation des jetons est ajoutée à l'invite ;
3. le fournisseur produit la réponse ;
4. les valeurs d'origine sont réinjectées — y compris en flux, grâce à
   :class:`~scribedesk.privacy.StreamRestorer`.

L'étape 4 est la contrepartie indispensable de l'étape 2 : sans elle, l'agent
recevrait un texte truffé de ``[[NOM_1]]``, et l'outil ne servirait à rien.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

from .config import Settings
from .language import LANGUAGE_NAMES, detect_language
from .privacy import PRESERVE_INSTRUCTION, Redaction, Redactor, StreamRestorer
from .prompts import Action, ActionLibrary, load_library
from .providers import Message, Provider, build_provider, join_instructions
from .secrets import get_api_key

__all__ = ["Engine", "TransformResult"]

logger = logging.getLogger(__name__)


def _impose_language(nom: str) -> str:
    """Consigne imposant une langue de sortie, quelle que soit celle du texte.

    Le rappel « quelle que soit la langue de ces consignes » n'est pas une
    précaution de style : les invites livrées sont rédigées en français et
    demandent explicitement du français. Sans cette phrase, le modèle suit
    l'invite plutôt que le choix de l'utilisateur.
    """
    return (
        f"Rédige impérativement ta réponse en {nom}, "
        "quelle que soit la langue du texte fourni ou de ces consignes. "
        "Applique d'abord la consigne principale, puis livre le résultat "
        "dans cette langue."
    )


@dataclass(frozen=True, slots=True)
class TransformResult:
    """Ce qu'une exécution produit, au-delà du texte lui-même."""

    text: str
    action: str
    provider: str
    model: str
    elapsed: float
    redaction: Redaction | None = None

    local: bool = False
    """L'inférence a eu lieu sur ce poste : aucune donnée n'est sortie.

    Enregistré explicitement plutôt que déduit de `redaction is None` : cette
    dernière vaut aussi `None` quand l'anonymisation a simplement été coupée,
    ce qui est l'inverse exact au regard d'un audit.
    """

    @property
    def redacted_count(self) -> int:
        """Nombre de valeurs distinctes masquées avant l'envoi."""
        return len(self.redaction.mapping) if self.redaction else 0

    def privacy_note(self) -> str:
        """Phrase récapitulative affichable sous le résultat."""
        if self.redaction is None:
            return "Traitement local : aucune donnée n'a quitté ce poste."
        if self.redaction.is_empty:
            return "Aucune donnée personnelle détectée dans le texte envoyé."
        details = ", ".join(
            f"{count} {label.lower()}" for label, count in sorted(self.redaction.summary().items())
        )
        return f"{self.redacted_count} valeur(s) masquée(s) avant envoi : {details}."


@dataclass(slots=True)
class Engine:
    """Point d'entrée unique pour exécuter une action sur un texte."""

    settings: Settings
    library: ActionLibrary = field(default_factory=load_library)
    _provider: Provider | None = field(default=None, init=False, repr=False)
    _provider_signature: tuple[str, ...] = field(default=(), init=False, repr=False)

    # -- Fournisseur ------------------------------------------------------

    @property
    def provider(self) -> Provider:
        """Le fournisseur courant, reconstruit seulement si les réglages ont changé.

        Conserver l'instance conserve aussi son pool de connexions HTTP ; c'est
        ce qui rend la deuxième invocation nettement plus rapide que la première.
        """
        config = self.settings.provider
        api_key = get_api_key(config.key)
        signature = (config.key, config.model, config.base_url, api_key, str(config.temperature))

        if self._provider is None or signature != self._provider_signature:
            self._provider = build_provider(
                config.key,
                model=config.model,
                api_key=api_key,
                base_url=config.base_url,
                temperature=config.temperature,
                timeout=config.timeout,
                max_tokens=config.max_tokens,
            )
            self._provider_signature = signature
        return self._provider

    async def aclose(self) -> None:
        """Libère les connexions réseau."""
        if self._provider is not None:
            await self._provider.aclose()
            self._provider = None
            self._provider_signature = ()

    def invalidate(self) -> None:
        """Force la reconstruction du fournisseur au prochain appel.

        À utiliser après une modification des préférences : la connexion en
        cours ne doit pas survivre à un changement de clé ou d'URL.
        """
        self._provider_signature = ()

    # -- Préparation ------------------------------------------------------

    def _redactor(self) -> Redactor:
        policy = self.settings.privacy
        return Redactor(enabled=policy.rules, extra_stopwords=policy.extra_stopwords)

    def prepare(
        self,
        action: Action,
        text: str,
        choices: Mapping[str, str] | None = None,
        target_language: str = "",
    ) -> tuple[list[Message], Redaction | None]:
        """Construit la conversation à envoyer, et l'éventuelle anonymisation.

        Exposée publiquement pour que l'interface puisse montrer à l'utilisateur
        *exactement* ce qui partira, avant de partir. Une promesse de
        confidentialité qu'on ne peut pas inspecter ne vaut pas grand-chose.
        """
        redaction: Redaction | None = None
        payload = text

        if self.settings.redaction_applies():
            redaction = self._redactor().redact(text)
            payload = redaction.text

        consignes = [action.render_instruction(choices)]

        # La consigne de langue vient après l'invite de l'action, et c'est
        # délibéré : les invites livrées imposent le français (« réponds
        # toujours en français »). Placée avant, elle serait contredite ; placée
        # après, elle prime, comme la dernière instruction reçue.
        langue = self._language_directive(text, action, target_language)
        if langue:
            consignes.append(langue)

        if redaction is not None and not redaction.is_empty:
            consignes.append(PRESERVE_INSTRUCTION)

        messages = [
            Message("system", join_instructions(consignes)),
            Message("user", action.render_user_message(payload)),
        ]
        return messages, redaction

    def _language_directive(self, text: str, action: Action, target: str = "") -> str:
        """Consigne de langue à ajouter, ou chaîne vide s'il n'y a rien à dire.

        Quatre cas, du plus explicite au plus implicite :

        1. une langue choisie **pour cet envoi**, depuis la palette ;
        2. sinon, la langue de travail fixée dans les **préférences** ;
        3. sinon, la langue **détectée** dans le texte source ;
        4. sinon, le choix est délégué au modèle, qui voit le texte.

        Cet ordre place le ponctuel avant le permanent : un réglage qui ne
        pourrait pas être outrepassé pour un ticket obligerait à ouvrir les
        préférences pour répondre une fois en anglais.

        La détection est faite sur le texte **d'origine**, avant anonymisation :
        remplacer les noms par des jetons appauvrit l'échantillon, déjà court.
        """
        # Une action qui gère elle-même la langue — la traduction — ne doit
        # recevoir aucune consigne : elle la contredirait.
        if not action.preserve_language:
            return ""

        if target.strip():
            return _impose_language(target.strip())

        choisie = LANGUAGE_NAMES.get(self.settings.assistant_language, "")
        if choisie:
            return _impose_language(choisie)

        if not self.settings.respect_source_language:
            return ""

        detection = detect_language(text)
        if detection:
            return (
                f"Le texte fourni est en {detection.name}. "
                f"Rédige impérativement ta réponse en {detection.name}, "
                "quelle que soit la langue de ces consignes."
            )
        # Indéterminé : le modèle voit le texte, nous non. Lui déléguer le choix
        # vaut mieux que d'imposer une langue sur une supposition.
        return (
            "Rédige ta réponse dans la même langue que le texte fourni, "
            "quelle que soit la langue de ces consignes."
        )

    # -- Exécution --------------------------------------------------------

    async def stream(
        self,
        action: Action,
        text: str,
        choices: Mapping[str, str] | None = None,
        target_language: str = "",
    ) -> AsyncIterator[str]:
        """Exécute l'action et rend le texte restauré, fragment par fragment."""
        messages, redaction = self.prepare(action, text, choices, target_language)
        mapping = redaction.mapping if redaction else {}
        restorer = StreamRestorer(mapping)

        async for chunk in self.provider.stream(messages):
            visible = restorer.feed(chunk)
            if visible:
                yield visible

        tail = restorer.flush()
        if tail:
            yield tail

    async def run(
        self,
        action: Action,
        text: str,
        choices: Mapping[str, str] | None = None,
        target_language: str = "",
    ) -> TransformResult:
        """Exécute l'action et renvoie le résultat complet."""
        started = time.perf_counter()
        messages, redaction = self.prepare(action, text, choices, target_language)

        raw = await self.provider.complete(messages)
        restored = Redactor.restore(raw, redaction.mapping) if redaction else raw

        if redaction is not None:
            missing = Redactor.unknown_tokens(raw, redaction.mapping)
            if missing:
                # Le modèle a inventé un jeton. Le signaler vaut mieux que de
                # laisser passer un texte qui semble anonymisé sans l'être.
                logger.warning("Jetons inconnus dans la réponse : %s", ", ".join(missing))

        return TransformResult(
            text=restored.strip(),
            action=action.name,
            provider=self.provider.name,
            model=self.settings.provider.model,
            elapsed=time.perf_counter() - started,
            redaction=redaction,
            local=self.provider.is_local,
        )

    # -- Confort ----------------------------------------------------------

    def action(self, name: str) -> Action:
        """Retrouve une action par son nom.

        Raises:
            KeyError: si aucune action ne porte ce nom.
        """
        found = self.library.get(name)
        if found is None:
            available = ", ".join(a.name for a in self.library)
            raise KeyError(f"Action inconnue : {name!r}. Disponibles : {available}.")
        return found

    def action_names(self) -> Sequence[str]:
        """Noms de toutes les actions chargées, dans l'ordre d'affichage."""
        return [a.name for a in self.library]
