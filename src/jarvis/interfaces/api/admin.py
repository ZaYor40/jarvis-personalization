# Copyright (C) 2026 Barthélemy Houot
# This file is part of Jarvis OS, licensed under the GNU AGPL-3.0-or-later.
# See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from jarvis.engine.background.notifications import NotificationQueue
from jarvis.engine.background.scheduler import Scheduler
from jarvis.engine.background.worker import BackgroundWorker
from jarvis.interfaces.api.ui import inject_client_config
from jarvis.kernel.error_collector import collector  # jrv: autofix
from jarvis.kernel.http_errors import raise_api_error
from jarvis.kernel.paths import PROJECT_ROOT, UI_STATIC_DIR
from jarvis.kernel.settings import settings
from jarvis.providers.memory.sessions import SessionStore

_PROJECT_ROOT = PROJECT_ROOT

router = APIRouter(prefix="/admin/api")
_ui_router = APIRouter()


@_ui_router.get("/admin", include_in_schema=False)
async def admin_ui() -> Response:
    content = (UI_STATIC_DIR / "admin.html").read_text(encoding="utf-8")
    return Response(
        content=inject_client_config(content),
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


# ── Models ────────────────────────────────────────────────────


class ContentBody(BaseModel):
    content: str


class SessionMeta(BaseModel):
    session_id: str
    name: str
    date: str
    message_count: int


class SessionMessage(BaseModel):
    role: str
    content: str
    ts: str


class TopicMeta(BaseModel):
    name: str
    mtime: str
    size: int


class MemoryOverview(BaseModel):
    index: str
    user_prefs: str
    topics: list[TopicMeta]


# ── Helpers ───────────────────────────────────────────────────


def _memory_dir(request: Request) -> Path:

    return Path(settings.memory_dir)


# ── Sessions ──────────────────────────────────────────────────


@router.get("/sessions", response_model=list[SessionMeta])
async def list_sessions(request: Request) -> list[SessionMeta]:

    store: SessionStore = SessionStore(_memory_dir(request) / "sessions")
    result = []
    for path in store.list_recent(50):
        parts = path.stem.split("_", 1)
        date = parts[0] if len(parts) == 2 else "?"
        session_id = parts[1] if len(parts) == 2 else path.stem
        try:
            lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            count = len(lines)
        except OSError:
            collector.error("JRV-API-001", "JRV-API-001")
            count = 0
        result.append(
            SessionMeta(
                session_id=session_id,
                name=path.stem,
                date=date,
                message_count=count,
            )
        )
    return result


@router.get("/sessions/{session_id}", response_model=list[SessionMessage])
async def get_session(session_id: str, request: Request) -> list[SessionMessage]:

    store: SessionStore = SessionStore(_memory_dir(request) / "sessions")
    path = store._find(session_id)  # noqa: SLF001
    if not path:
        raise_api_error("JRV-API-003", 404, "Session introuvable.")
    messages: list[SessionMessage] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            messages.append(
                SessionMessage(
                    role=entry.get("role", "?"),
                    content=entry.get("content", ""),
                    ts=entry.get("ts", ""),
                )
            )
        except json.JSONDecodeError:
            collector.error("JRV-API-001", "JRV-API-001")
            continue
    return messages


# ── Mémoire ───────────────────────────────────────────────────


@router.get("/memory", response_model=MemoryOverview)
async def get_memory(request: Request) -> MemoryOverview:
    mem_dir = _memory_dir(request)
    index_path = mem_dir / "MEMORY.md"
    prefs_path = mem_dir / "user_prefs.md"
    topics_dir = mem_dir / "topics"

    index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    prefs = prefs_path.read_text(encoding="utf-8") if prefs_path.exists() else ""

    topics: list[TopicMeta] = []
    if topics_dir.exists():
        for p in sorted(topics_dir.glob("*.md")):
            stat = p.stat()
            import datetime as dt

            mtime = dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            topics.append(TopicMeta(name=p.name, mtime=mtime, size=stat.st_size))

    return MemoryOverview(index=index, user_prefs=prefs, topics=topics)


@router.get("/memory/index")
async def get_memory_index(request: Request) -> dict:
    path = _memory_dir(request) / "MEMORY.md"
    return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}


@router.put("/memory/index")
async def put_memory_index(body: ContentBody, request: Request) -> dict:
    path = _memory_dir(request) / "MEMORY.md"
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True}


@router.get("/memory/prefs")
async def get_memory_prefs(request: Request) -> dict:
    path = _memory_dir(request) / "user_prefs.md"
    return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}


@router.put("/memory/prefs")
async def put_memory_prefs(body: ContentBody, request: Request) -> dict:
    path = _memory_dir(request) / "user_prefs.md"
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True}


@router.get("/memory/topics/{filename}")
async def get_topic(filename: str, request: Request) -> dict:
    if "/" in filename or "\\" in filename:
        raise_api_error("JRV-API-004", 400, "Nom de fichier invalide.")
    path = _memory_dir(request) / "topics" / filename
    if not path.exists():
        raise_api_error("JRV-API-003", 404, "Fichier introuvable.")
    return {"content": path.read_text(encoding="utf-8")}


@router.put("/memory/topics/{filename}")
async def put_topic(filename: str, body: ContentBody, request: Request) -> dict:
    if "/" in filename or "\\" in filename:
        raise_api_error("JRV-API-004", 400, "Nom de fichier invalide.")
    path = _memory_dir(request) / "topics" / filename
    if not path.exists():
        raise_api_error("JRV-API-003", 404, "Fichier introuvable.")
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True}


@router.delete("/memory/topics/{filename}")
async def delete_topic(filename: str, request: Request) -> dict:
    if "/" in filename or "\\" in filename:
        raise_api_error("JRV-API-004", 400, "Nom de fichier invalide.")
    path = _memory_dir(request) / "topics" / filename
    if not path.exists():
        raise_api_error("JRV-API-003", 404, "Fichier introuvable.")
    path.unlink()
    return {"ok": True}


# ── Tasks ─────────────────────────────────────────────────────


@router.get("/tasks")
async def get_tasks(request: Request) -> dict:

    scheduler: Scheduler = request.app.state.scheduler
    worker: BackgroundWorker = request.app.state.worker

    history = [
        {
            "session_id": r.session_id,
            "instruction": r.instruction,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "result": r.result,
            "error": r.error,
        }
        for r in worker.history()
    ]
    return {"scheduler": scheduler.status(), "history": history}


# ── Mise à jour ───────────────────────────────────────────────


def _run_sync(cmd: str) -> tuple[int, str]:
    # CREATE_NEW_PROCESS_GROUP isole git/uv du groupe de processus de la
    # console qui héberge le serveur : sans ça, un Ctrl+C/Break envoyé à
    # cette console se propage aussi aux sous-processus, qui se font tuer
    # en plein vol (code 130, sortie vide) dès qu'une commande prend plus
    # de quelques ms — typiquement `git pull`/`git fetch` (accès réseau)
    # contrairement à `git stash` (local, quasi instantané).
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    result = subprocess.run(  # noqa: S602 — commandes fixes (git/uv), pas d'entrée utilisateur
        cmd,
        shell=True,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


async def _run(cmd: str) -> tuple[int, str]:
    # asyncio.create_subprocess_shell lève NotImplementedError sur cette
    # installation Windows (la boucle asyncio active — imposée ailleurs dans
    # l'app pour la voix/LiveKit — ne supporte pas les sous-processus natifs
    # d'asyncio). subprocess.run() dans un thread contourne complètement
    # cette limitation, sans dépendre du support subprocess de la boucle.
    return await asyncio.to_thread(_run_sync, cmd)


@router.post("/system/check-update")
async def system_check_update() -> dict:
    """Vérifie s'il y a une mise à jour en amont sans rien appliquer (fetch seul, pas de pull)."""
    code, detail = await _run("git fetch origin main")
    if code != 0:
        return {"ok": False, "error": detail}
    code, detail = await _run("git rev-list --count HEAD..origin/main")
    if code != 0:
        return {"ok": False, "error": detail}
    behind = int(detail or "0")
    return {"ok": True, "available": behind > 0, "commits_behind": behind}


@router.post("/system/update")
async def system_update() -> dict:
    """git pull + uv sync sans toucher aux données locales (.env, memory, skills, config)."""
    steps: list[dict] = []

    # 1. Stash les éventuelles modifs locales non committées
    code, detail = await _run("git stash")
    stashed = code == 0 and "No local changes" not in detail
    steps.append({"step": "stash", "ok": True, "detail": detail})

    # 2. Pull
    code, detail = await _run("git pull origin main --ff-only")
    if code != 0:
        if stashed:
            await _run("git stash pop")
        return {"ok": False, "error": detail, "steps": steps}
    already_up_to_date = "Already up to date" in detail
    steps.append({"step": "pull", "ok": True, "detail": detail})

    # 3. Restaurer le stash si besoin
    if stashed:
        code, detail = await _run("git stash pop")
        steps.append({"step": "restore", "ok": code == 0, "detail": detail})
        if code != 0:
            # Conflit entre la mise à jour et des modifs locales non committées :
            # le stash n'est PAS supprimé par git dans ce cas (rien n'est perdu),
            # mais le working tree contient des marqueurs de conflit. Ne surtout
            # pas continuer vers uv sync ni annoncer un succès.
            _, conflicted = await _run("git diff --name-only --diff-filter=U")
            conflicted_files = [f for f in conflicted.splitlines() if f.strip()]
            return {
                "ok": False,
                "error": (
                    "Conflit entre la mise à jour et tes modifications locales. "
                    "Rien n'est perdu (tes modifs sont toujours dans `git stash list`), "
                    "mais il faut résoudre les conflits manuellement avant de continuer. "
                    + detail
                ),
                "conflicted_files": conflicted_files,
                "steps": steps,
            }

    # 4. Sync dépendances (uv)
    code, detail = await _run("uv sync --quiet")
    steps.append({"step": "deps", "ok": code == 0, "detail": detail or "ok"})

    return {
        "ok": True,
        "already_up_to_date": already_up_to_date,
        "restart_required": not already_up_to_date,
        "steps": steps,
    }


# ── Notifications ─────────────────────────────────────────────


@router.get("/notifications")
async def get_notifications(request: Request) -> dict:

    queue: NotificationQueue = request.app.state.notifications
    return {
        "pending": [
            {"content": n.content, "created_at": n.created_at.isoformat()}
            for n in queue._pending  # noqa: SLF001
        ]
    }
