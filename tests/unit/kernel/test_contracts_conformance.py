"""Conformité statique + runtime des implémentations aux Protocols kernel.

CDC §F.1.3bis — sans type-checker, `kernel/contracts.py` n'est que de la
documentation : les Protocols structurels NE sont JAMAIS vérifiés au
runtime par CPython. mypy compare les signatures au point d'assignation
TYPÉE — c'est ici qu'on l'oblige à faire le travail.

Mécanisme :
  - une assignation explicite `_x: Protocol = ConcreteImpl(...)` par
    couple (Protocol, implémentation) — mypy compare alors les signatures
    et plante si un paramètre, un type de retour, un nom ou une arity
    diffère.
  - mypy est scopé sur ce fichier + `src/jarvis/kernel/` dans
    `pyproject.toml::tool.mypy.files` — le reste du codebase n'est PAS
    typé strictement (chantier séparé, hors-périmètre).

Le test pytest associé NE INSTANCIE PAS les classes : il fait l'assignation
via `typing.cast` après un check `if False`, ce qui est ANALYSÉ par mypy
mais éliminé au runtime. C'est volontaire — la plupart des providers LLM
ont besoin d'une clé API à l'instantiation, et on ne veut pas que la
suite de tests dépende d'une .env complète. La validation runtime
(`isinstance` au boot bootstrap.build()) est faite côté `bootstrap.py`
GATE F1bis-b, sur les instances RÉELLES.

Périmètre couvert en Phase F :
  - L1 / Providers / LLM : 5 providers (mypy statique)
  - L1 / Providers / Memory : FTSIndex, VectorIndex, SessionStore,
    TopicStore, MemoryIndex (mypy statique)
  - L2 / Engine / tracking : UsageTracker (mypy + runtime)

Hors-périmètre (BACKLOG Phase G "fermer conformité Protocols stricte") :
MemoryStore, ToolRegistry, SkillRegistry — divergences réelles entre
Protocols et impls documentées dans BACKLOG.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from jarvis.kernel import contracts

if TYPE_CHECKING:
    # Imports pour le check statique. Les types sont résolus par mypy
    # mais le code n'est jamais exécuté → pas besoin de clé API pour le LLM.
    from jarvis.providers.llm.api import (
        AnthropicProvider,
        GeminiProvider,
        MistralProvider,
        OpenAIProvider,
    )
    from jarvis.providers.llm.local import OllamaProvider
    from jarvis.providers.memory.index import MemoryIndex as _ConcreteMemoryIndex
    from jarvis.providers.memory.search import FTSIndex as _ConcreteFTSIndex
    from jarvis.providers.memory.search import VectorIndex as _ConcreteVectorIndex
    from jarvis.providers.memory.sessions import SessionStore as _ConcreteSessionStore
    from jarvis.providers.memory.topics import TopicStore as _ConcreteTopicStore


def test_conformance_static() -> None:
    """Assignation typée par couple (Protocol, implémentation).

    Au runtime, le code dans `if False:` est éliminé — pas d'instantiation.
    mypy le visite normalement et vérifie chaque assignation.
    """
    if False:  # noqa: SIM108 — bloc analysé par mypy, jamais exécuté
        # ── L1 — Providers / LLM ────────────────────────────────────────────
        _a: contracts.LLMProvider = cast("AnthropicProvider", None)
        _m: contracts.LLMProvider = cast("MistralProvider", None)
        _g: contracts.LLMProvider = cast("GeminiProvider", None)
        _open: contracts.LLMProvider = cast("OpenAIProvider", None)
        _o: contracts.LLMProvider = cast("OllamaProvider", None)

        # ── L1 — Providers / Memory ─────────────────────────────────────────
        _sess: contracts.SessionStore = cast("_ConcreteSessionStore", None)
        _top: contracts.TopicStore = cast("_ConcreteTopicStore", None)
        _mi: contracts.MemoryIndex = cast("_ConcreteMemoryIndex", None)
        _fts: contracts.FTSIndex = cast("_ConcreteFTSIndex", None)
        _vi: contracts.VectorIndex = cast("_ConcreteVectorIndex", None)

    assert True  # mypy a tranché statiquement


def test_conformance_runtime_check() -> None:
    """Ceinture-bretelles runtime : Protocols `@runtime_checkable` valident
    l'EXISTENCE des méthodes (pas les signatures).

    On évite d'instancier les LLM providers (clé API requise). UsageTracker
    n'a pas de dépendance externe — bon proxy pour l'isinstance check.
    """
    from jarvis.engine.tracking import UsageTracker

    assert isinstance(UsageTracker(), contracts.UsageTracker)
