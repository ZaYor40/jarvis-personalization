# Copyright (C) 2026 Barthélemy Houot
# This file is part of Jarvis OS, licensed under the GNU AGPL-3.0-or-later.
# See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from loguru import logger

from jarvis.engine.agent import Agent
from jarvis.engine.background.notifications import NotificationQueue
from jarvis.engine.background.worker import BackgroundWorker
from jarvis.engine.llm_errors import friendly_llm_error
from jarvis.engine.router import RouteEnum, SpeedRouter
from jarvis.engine.session import Session, SessionManager
from jarvis.kernel.contracts import CrossSessionRecall
from jarvis.kernel.error_collector import collector  # jrv: autofix


def _fallback(exc: BaseException | None = None) -> str:
    if exc is not None:
        return friendly_llm_error(exc)
    return friendly_llm_error(RuntimeError("unknown"))


# Filet de sécurité : certains modèles (mistral-small avec beaucoup d'outils
# disponibles) écrivent parfois un appel d'outil EN TEXTE au lieu de faire un
# vrai appel de fonction — ex. `player_control(action="play_local")` recopié
# tel quel dans la réponse. Si ça arrive et qu'aucun vrai tool_use n'a eu
# lieu, on repère le motif et on exécute l'outil pour de vrai à la place.
_TOOL_ECHO_RE = re.compile(r'^`?([a-zA-Z_][a-zA-Z0-9_]*)\(([^()]*)\)`?\.?$')
_TOOL_ARG_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# Rattrapage ciblé "volume" : le modèle décrit parfois l'action en langage
# naturel ("Je baisse le volume à 20%.") sans jamais appeler l'outil — aucune
# syntaxe reconnaissable à repérer dans SA réponse. On se base donc sur LA
# PHRASE DE L'UTILISATEUR (plus fiable, vocabulaire contraint) plutôt que sur
# ce que le modèle prétend avoir fait. Portée volontairement étroite : ne
# se déclenche que si "volume" est explicitement mentionné.
_VOLUME_MENTION_RE = re.compile(r"\bvolume\b", re.IGNORECASE)
_VOLUME_PCT_RE = re.compile(r"volume.{0,20}?(\d{1,3})\s*%", re.IGNORECASE)
_VOLUME_UP_RE = re.compile(r"\b(monte|augmente|hausse)\w*\b", re.IGNORECASE)
_VOLUME_DOWN_RE = re.compile(r"\b(baisse|diminue|r[ée]dui)\w*\b", re.IGNORECASE)

# Rattrapage ciblé "vue météo" : même situation que le volume — le modèle
# décrit l'affichage plutôt que d'appeler show_view. Portée volontairement
# étroite (une seule vue) — étendre au cas par cas si d'autres vues souffrent
# du même souci, plutôt que de généraliser à l'aveugle.
_VIEW_WEATHER_MENTION_RE = re.compile(r"\b(m[ée]t[ée]o|weather)\b", re.IGNORECASE)
_VIEW_SHOW_VERB_RE = re.compile(r"\b(montre|affiche|ouvre|active)\w*\b", re.IGNORECASE)


class Gateway:
    """Point d'entrée unique. Gère session, notifications, routing et agent.

    Phase C : le constructeur Gateway était DÉJÀ bien injecté en pré-C
    (5 dépendances reçues par paramètres typés). Le singleton historique
    `_tool_registry_instance` a été supprimé à l'étape 2 (b) — les call-sites
    (preset, http_skills) reçoivent maintenant le ToolRegistry via constructeur
    ou `request.app.state.container.tool_registry`.

    Flux double-passe pour les outils (CF) :
    1. Premier appel LLM streamé : détection du tag + ack text + capture tool_use.
    2. Exécution parallèle des outils (overlap avec TTS de l'ack).
    3. Second appel LLM (synthesize) : résultats injectés dans le contexte,
       LLM produit une réponse naturelle — pas de dump brut.
    L'utilisateur reçoit : ack streamé → synthèse streamée dans la même bulle.
    [BG] : le worker est soumis par le WebSocket après "done".
    """

    def __init__(
        self,
        session_manager: SessionManager,
        agent: Agent,
        notifications: NotificationQueue,
        worker: BackgroundWorker,
        recall: CrossSessionRecall | None = None,
    ) -> None:
        self._sessions = session_manager
        self._agent = agent
        self._notifications = notifications
        self._worker = worker
        self._recall = recall

    async def handle(
        self,
        message: str,
        session_id: str | None = None,
        stream: bool = True,
    ) -> tuple[Session, RouteEnum, str | AsyncIterator[str]]:
        session = self._sessions.get_or_create(session_id)
        logger.info("Gateway handle", session_id=str(session.id))

        pending = self._notifications.drain()
        notif_texts = [n.content for n in pending] if pending else None
        if notif_texts:
            logger.info("Injecting notifications", count=len(notif_texts))

        # Rappel cross-session uniquement au premier message de la session
        recall_summary: str | None = None
        if self._recall is not None and not session.messages:
            try:
                recall_summary = await self._recall.recall(message)
                if recall_summary:
                    logger.debug("CrossSessionRecall injected", chars=len(recall_summary))
            except Exception as e:
                collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
                logger.warning("CrossSessionRecall failed", error=str(e))

        try:
            raw_stream, tool_capture = self._agent.start_routing_stream(
                session=session,
                user_message=message,
                notifications=notif_texts,
                recall_summary=recall_summary,
            )

            route, text_stream = await SpeedRouter.extract_route(raw_stream)
            logger.debug("Route detected", route=route.value)

            agent = self._agent
            notifications = self._notifications

            async def _pipe() -> AsyncIterator[str]:
                tool_task: asyncio.Task | None = None
                ack_text = ""  # Accumule le texte streamé avant les outils

                async for chunk in text_stream:
                    ack_text += chunk
                    # Dès que _stream_capturing peuple capture (content_block_stop tool_use),
                    # on démarre la task outil — elle tourne pendant que la voice WS fait du TTS.
                    if tool_task is None and tool_capture is not None and tool_capture.calls:
                        tool_task = asyncio.create_task(
                            agent.execute_captured_tools(tool_capture),
                            name="cf-tools",
                        )

                # Fallback : LLM sans préambule texte
                if tool_task is None and tool_capture is not None and tool_capture.calls:
                    tool_task = asyncio.create_task(
                        agent.execute_captured_tools(tool_capture),
                        name="cf-tools",
                    )

                # Second appel LLM pour synthétiser les résultats — avant "done"
                if tool_task is not None:
                    try:
                        results = await tool_task
                        logger.debug("CF tools done", names=[n for _, n, _ in tool_capture.calls])
                        synth_stream = agent.synthesize(session, ack_text, tool_capture, results)
                        _, clean_synth = await SpeedRouter.extract_route(synth_stream)
                        synth_text = "".join([chunk async for chunk in clean_synth])
                        final_text = (
                            (ack_text.strip() + " " + synth_text) if ack_text.strip() else synth_text
                        )
                    except Exception as e:
                        collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
                        logger.opt(exception=True).error(
                            "CF tool or synthesize error",
                            error=type(e).__name__,
                            detail=str(e),
                        )
                        notifications.add(f"Outil échoué : {e}")
                        final_text = friendly_llm_error(e)
                else:
                    # Aucun vrai tool_use n'a eu lieu : le texte final peut être un
                    # appel d'outil recopié en clair plutôt qu'exécuté (mistral-small
                    # avec beaucoup d'outils dispo). On tente de le rattraper AVANT
                    # de rien envoyer — un yield progressif enverrait déjà les mots
                    # au client avant qu'on ait pu détecter le motif.
                    rescued = await self._rescue_echoed_tool_call(ack_text)
                    if rescued is None:
                        # Pas de syntaxe reconnaissable dans la réponse — la
                        # demande était peut-être décrite en langage naturel sans
                        # être vraiment exécutée. Rattrapages ciblés un par un.
                        rescued = await self._rescue_volume_intent(message)
                    if rescued is None:
                        rescued = await self._rescue_view_intent(message)
                    final_text = rescued if rescued is not None else ack_text

                yield final_text

            return await self._finalize(session, route, _pipe(), stream, tool_capture)

        except Exception as e:
            collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
            logger.opt(exception=True).error(
                "Gateway error", error=type(e).__name__, detail=str(e), session_id=str(session.id)
            )
            return session, RouteEnum.INSTANT, _fallback(e)

    async def _finalize(
        self,
        session: Session,
        route: RouteEnum,
        response: str | AsyncIterator[str],
        stream: bool,
        tool_capture: object | None = None,  # noqa: ARG002 — conservé pour compat signature
    ) -> tuple[Session, RouteEnum, str | AsyncIterator[str]]:
        """Si stream=False : draine la réponse, ajoute l'assistant en session.

        Le rattrapage d'un outil recopié en texte (cf. _rescue_echoed_tool_call)
        est appliqué en amont dans _pipe(), avant le premier yield — nécessaire
        pour les appelants stream=True (voice_generate) qui, sinon, auraient déjà
        envoyé les mots au client avant qu'on puisse détecter et corriger le motif.
        """
        if stream:
            return session, route, response
        if isinstance(response, str):
            text = response
        else:
            text = "".join([chunk async for chunk in response])
        session.add_message("assistant", text)
        return session, route, text

    async def _rescue_echoed_tool_call(self, text: str) -> str | None:
        match = _TOOL_ECHO_RE.match(text.strip())
        if not match:
            return None
        name, raw_args = match.group(1), match.group(2)
        tool_registry = getattr(self._agent, "_tool_registry", None)
        if tool_registry is None or not tool_registry.has_tool(name):
            return None
        args = dict(_TOOL_ARG_RE.findall(raw_args))
        logger.warning("Rescued tool call echoed as text — executing for real", name=name, args=args)
        try:
            return await tool_registry.call_str(name, args)
        except Exception as e:
            collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
            logger.opt(exception=True).error("Tool echo rescue failed", name=name, error=str(e))
            return None

    async def _rescue_volume_intent(self, user_message: str) -> str | None:
        """Repli étroit : la demande de volume vient de l'UTILISATEUR (vocabulaire
        contraint, fiable), pas d'une tentative de deviner ce que le modèle a
        prétendu faire dans sa réponse (imprévisible en langage naturel)."""
        if not _VOLUME_MENTION_RE.search(user_message):
            return None
        tool_registry = getattr(self._agent, "_tool_registry", None)
        if tool_registry is None or not tool_registry.has_tool("player_control"):
            return None

        pct_match = _VOLUME_PCT_RE.search(user_message)
        if pct_match:
            args: dict[str, str] = {"action": "set_volume", "percent": pct_match.group(1)}
        elif _VOLUME_DOWN_RE.search(user_message):
            args = {"action": "volume_delta", "delta": "-10"}
        elif _VOLUME_UP_RE.search(user_message):
            args = {"action": "volume_delta", "delta": "10"}
        else:
            return None

        logger.warning("Rescued volume intent from user message", args=args)
        try:
            return await tool_registry.call_str("player_control", args)
        except Exception as e:
            collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
            logger.opt(exception=True).error("Volume intent rescue failed", error=str(e))
            return None

    async def _rescue_view_intent(self, user_message: str) -> str | None:
        """Repli étroit, une seule vue (weather) — même logique que le volume :
        se base sur la phrase de l'utilisateur, pas sur ce que le modèle
        prétend avoir affiché."""
        if not (
            _VIEW_WEATHER_MENTION_RE.search(user_message)
            and _VIEW_SHOW_VERB_RE.search(user_message)
        ):
            return None
        tool_registry = getattr(self._agent, "_tool_registry", None)
        if tool_registry is None or not tool_registry.has_tool("show_view"):
            return None

        logger.warning("Rescued view intent from user message", view_id="weather")
        try:
            return await tool_registry.call_str("show_view", {"action": "show", "view_id": "weather"})
        except Exception as e:
            collector.error("JRV-GWY-001", "JRV-GWY-001", cause=e)
            logger.opt(exception=True).error("View intent rescue failed", error=str(e))
            return None
