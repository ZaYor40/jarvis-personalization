"""Tests des endpoints /api/budget.

Cas couverts :
  - GET /api/budget/status quand le guard est actif (guard.status() proxié)
  - GET /api/budget/status quand le guard est None (budget désactivé)
  - GET /api/budget/remaining avec scope connu (valeur bornée)
  - GET /api/budget/remaining scope illimité (remaining_usd: null)
  - GET /api/budget/remaining quand désactivé
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.http_budget import router as budget_router

# ── Helpers ───────────────────────────────────────────────────────────────────


def _app_with_guard(guard: object) -> FastAPI:
    """Monte le router budget sur une mini-app avec le guard mocké."""
    app = FastAPI()
    app.include_router(budget_router)
    return app


_STATUS_PAYLOAD = {
    "enabled": True,
    "global": {
        "spent_usd": 2.5,
        "limit_usd": 10.0,
        "remaining_usd": 7.5,
        "utilization_pct": 25.0,
        "status": "ok",
    },
    "projects": {
        "proj1": {
            "spent_usd": 0.5,
            "limit_usd": 2.0,
            "remaining_usd": 1.5,
            "status": "ok",
        }
    },
}


# ── Tests /api/budget/status ──────────────────────────────────────────────────


def test_status_quand_guard_actif() -> None:
    guard = MagicMock()
    guard.status.return_value = _STATUS_PAYLOAD
    app = _app_with_guard(guard)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=guard):
        with TestClient(app) as c:
            res = c.get("/api/budget/status")

    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is True
    assert data["global"]["spent_usd"] == 2.5
    assert "proj1" in data["projects"]
    guard.status.assert_called_once()


def test_status_quand_guard_absent() -> None:
    """Quand get_budget_guard() retourne None, l'endpoint retourne enabled=false."""
    app = _app_with_guard(None)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=None):
        with TestClient(app) as c:
            res = c.get("/api/budget/status")

    assert res.status_code == 200
    assert res.json() == {"enabled": False}


# ── Tests /api/budget/remaining ───────────────────────────────────────────────


def test_remaining_scope_global() -> None:
    guard = MagicMock()
    guard.remaining.return_value = 7.5
    app = _app_with_guard(guard)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=guard):
        with TestClient(app) as c:
            res = c.get("/api/budget/remaining?scope=global")

    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is True
    assert data["scope"] == "global"
    assert data["remaining_usd"] == pytest.approx(7.5)
    guard.remaining.assert_called_once_with("global")


def test_remaining_scope_illimite() -> None:
    """Un scope run: retourne remaining_usd: null (infini non sérialisable)."""
    guard = MagicMock()
    guard.remaining.return_value = float("inf")
    app = _app_with_guard(guard)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=guard):
        with TestClient(app) as c:
            res = c.get("/api/budget/remaining?scope=run%3Asome-run")

    assert res.status_code == 200
    data = res.json()
    assert data["remaining_usd"] is None


def test_remaining_quand_desactive() -> None:
    app = _app_with_guard(None)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=None):
        with TestClient(app) as c:
            res = c.get("/api/budget/remaining?scope=global")

    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is False
    assert data["remaining_usd"] is None
    assert data["scope"] == "global"


def test_remaining_scope_par_defaut_est_global() -> None:
    guard = MagicMock()
    guard.remaining.return_value = 5.0
    app = _app_with_guard(guard)

    with patch("jarvis.engine.budget.get_budget_guard", return_value=guard):
        with TestClient(app) as c:
            res = c.get("/api/budget/remaining")

    assert res.status_code == 200
    guard.remaining.assert_called_once_with("global")
