# Copyright (C) 2026 Barthélemy Houot
# This file is part of Jarvis OS, licensed under the GNU AGPL-3.0-or-later.
# See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Bibliothèque locale du player natif Jarvis (provider 'jarvis').

Contrairement à spotify.py/deezer.py, ce module ne télécommande rien à
distance : il se contente de lister et streamer des fichiers audio locaux.
La lecture elle-même a lieu dans le navigateur (élément <audio>), pilotée
via les événements WebSocket 'player_play'/'player_control' (cf.
capabilities/tools/player.py, seul point d'entrée qui déclenche une lecture).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from jarvis.kernel.error_collector import collector  # jrv: autofix
from jarvis.kernel.http_errors import raise_api_error
from jarvis.kernel.settings import settings

router = APIRouter(prefix="/api/player")

_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav", ".ogg"}

# Hôtes autorisés pour /proxy — évite d'exposer un proxy HTTP ouvert
# (SSRF) tout en couvrant les CDN de streaming SoundCloud connus.
_PROXY_ALLOWED_HOST_SUFFIXES = (".sndcdn.com", ".soundcloud.cloud", ".soundcloud.com")


def _library_dir() -> Path:
    """Résolu à chaque appel (pas au chargement du module) pour respecter un
    changement de MUSIC_LIBRARY_DIR à chaud, comme memory_dir ailleurs."""
    return Path(settings.music_library_dir)


def list_library() -> list[dict]:
    """Scanne le dossier bibliothèque. Utilisé par la route ET par PlayerTool."""
    library_dir = _library_dir()
    if not library_dir.exists():
        return []
    tracks = []
    for path in sorted(library_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS:
            tracks.append({"filename": path.name, "title": path.stem})
    return tracks


@router.get("/library")
async def get_library() -> list[dict]:
    return list_library()


@router.get("/library/stream/{filename}")
async def stream_track(filename: str) -> FileResponse:
    # Path(filename).name retire tout composant de dossier (../, chemins absolus)
    # avant de résoudre sous le dossier bibliothèque — empêche de sortir du dossier.
    safe_name = Path(filename).name
    path = _library_dir() / safe_name
    if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise_api_error("JRV-API-003", 404, "Piste introuvable.")
    return FileResponse(path)


@router.get("/proxy")
async def proxy_stream(request: Request, url: str) -> StreamingResponse:
    """Relaie un flux SoundCloud à travers notre origine.

    <audio src> pointé directement sur le CDN SoundCloud échoue en silence
    (probable protection anti-hotlink basée sur le Referer/Origin) — le
    navigateur n'obtient jamais d'événement exploitable pour prévenir
    l'utilisateur. En passant par notre propre serveur, la requête sortante
    porte le Referer/Origin de Jarvis, pas celui du navigateur du client.
    """
    host = urlparse(url).hostname or ""
    if not any(host == s.lstrip(".") or host.endswith(s) for s in _PROXY_ALLOWED_HOST_SUFFIXES):
        raise_api_error("JRV-API-004", 400, "Hôte non autorisé pour le proxy audio.")

    fwd_headers: dict[str, str] = {}
    if "range" in request.headers:
        fwd_headers["Range"] = request.headers["range"]

    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        upstream_req = client.build_request("GET", url, headers=fwd_headers)
        upstream = await client.send(upstream_req, stream=True)
    except httpx.RequestError as e:
        await client.aclose()
        collector.error("JRV-API-001", "JRV-API-001", cause=e)
        logger.warning("PlayerProxy upstream error", url=url, error=str(e))
        raise_api_error("JRV-API-005", 502, "Flux audio distant inaccessible.", cause=e)

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")
    }
    resp_headers.setdefault("accept-ranges", "bytes")

    return StreamingResponse(body(), status_code=upstream.status_code, headers=resp_headers)
