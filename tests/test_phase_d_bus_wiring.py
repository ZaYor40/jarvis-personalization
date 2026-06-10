"""Phase D — Tests d'intégration du bus d'événements.

Vérifie que chaque émetteur PUBLIE l'événement sur le bus injecté :
  - BudgetGuard.reserve(over-limit) → BudgetThresholdReached
  - BudgetGuard.reserve(near-warn)  → BudgetThresholdReached
  - MemoryIngest.ingest(content)    → MemoryIngested

(MissionCompleted est testé via test_mission_engine.py qui patche déjà
le pipeline complet.)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.kernel.events import (
    BudgetThresholdReached,
    EventBus,
    MemoryIngested,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(monthly: float, per_project: float, warn_pct: float) -> MagicMock:
    s = MagicMock()
    s.budget_enabled = True
    s.budget_monthly_usd = monthly
    s.budget_per_project_usd = per_project
    s.budget_warn_pct = warn_pct
    return s


def _fake_tracker() -> MagicMock:
    t = MagicMock()
    t._read_day = MagicMock(return_value=[])
    t.get_monthly_totals = MagicMock(return_value={"cost_usd": 0.0})
    return t


# ── BudgetGuard ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_hard_stop_publie_BudgetThresholdReached() -> None:
    """Reserve au-delà du plafond → ratio=1.0 publié."""
    from jarvis.engine.budget import BudgetGuard

    bus = EventBus()
    captured: list[BudgetThresholdReached] = []

    async def handler(ev: BudgetThresholdReached) -> None:
        captured.append(ev)

    bus.subscribe(BudgetThresholdReached, handler)

    guard = BudgetGuard(
        settings=_make_settings(10.0, 2.0, 80.0),
        tracker=_fake_tracker(),
        bus=bus,
    )
    guard._global_spent = lambda: 9.5  # noqa: SLF001 — test interne

    ok = await guard.reserve("global", 1.0)
    assert ok is False
    assert len(captured) == 1
    assert captured[0].ratio == 1.0
    assert captured[0].scope == "global"
    assert captured[0].provider == "global"


@pytest.mark.asyncio
async def test_budget_warning_publie_BudgetThresholdReached() -> None:
    """Reserve qui franchit le seuil de warn → ratio≈0.85 publié, une fois."""
    from jarvis.engine.budget import BudgetGuard

    bus = EventBus()
    captured: list[BudgetThresholdReached] = []

    async def handler(ev: BudgetThresholdReached) -> None:
        captured.append(ev)

    bus.subscribe(BudgetThresholdReached, handler)

    guard = BudgetGuard(
        settings=_make_settings(10.0, 2.0, 80.0),
        tracker=_fake_tracker(),
        bus=bus,
    )
    guard._global_spent = lambda: 7.5  # noqa: SLF001 — test interne

    ok1 = await guard.reserve("global", 1.0)  # projected 8.5 → warn
    ok2 = await guard.reserve("global", 0.5)  # déjà warné → silence
    assert ok1 is True
    assert ok2 is True
    assert len(captured) == 1
    assert 0.8 <= captured[0].ratio <= 0.9
    assert captured[0].scope == "global"


# ── MemoryIngest ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_ingest_publie_MemoryIngested() -> None:
    """Après un ingest réussi, MemoryIngested est publié avec event_id+fact_count."""
    from jarvis.providers.memory.ingest import MemoryIngest

    bus = EventBus()
    captured: list[MemoryIngested] = []

    async def handler(ev: MemoryIngested) -> None:
        captured.append(ev)

    bus.subscribe(MemoryIngested, handler)

    fake_kernel = MagicMock()
    fake_event = MagicMock()
    fake_event.id = "evt_001"
    fake_kernel.log_event = MagicMock(return_value=fake_event)

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value="[]")  # 0 candidats extraits

    ingest = MemoryIngest(kernel=fake_kernel, llm=fake_llm, bus=bus)
    await ingest.ingest(content="rien d'intéressant", source="conversation")

    assert len(captured) == 1
    assert captured[0].event_id == "evt_001"
    assert captured[0].fact_count == 0
    assert captured[0].source == "conversation"
