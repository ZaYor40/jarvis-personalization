# Copyright (C) 2026 Barthélemy Houot
# This file is part of Jarvis OS, licensed under the GNU AGPL-3.0-or-later.
# See the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Player audio natif Jarvis (provider 'jarvis').

Contrairement à SpotifyTool/DeezerTool, ce tool ne télécommande pas un
appareil distant : la lecture a lieu directement dans l'onglet navigateur
(élément <audio>, cf. home.js). Ce tool se contente de (1) résoudre une
piste — recherche SoundCloud via yt-dlp (scsearch, API non-officielle mais
maintenue par la communauté — pas de vrai compte SoundCloud lié, cf.
discussion produit) ou fichier local — et (2) pousser l'ordre de lecture au
navigateur via broadcast_event (même mécanisme que ShowViewTool).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from urllib.parse import quote

from loguru import logger

from jarvis.capabilities.tools.base import Tool, ToolResult
from jarvis.interfaces.api.player import list_library
from jarvis.kernel.error_collector import collector  # jrv: autofix

_SEARCH_RESULTS = 5


class PlayerTool(Tool):
    name = "player_control"
    description = (
        "Contrôle le lecteur audio natif de Jarvis (provider 'jarvis' — distinct de "
        "Spotify/Deezer, joue directement dans l'onglet navigateur, pas d'appareil externe). "
        "Actions : 'play_mood' (cherche et joue un morceau sur SoundCloud correspondant à une "
        "ambiance/genre, ex. 'hardcore', 'lofi', 'metal' — fournir 'query'), "
        "'play_local' (joue les fichiers du dossier bibliothèque locale, mélangés — 'query' "
        "optionnel pour filtrer par nom de fichier), "
        "'pause', 'resume', 'next', 'previous' (contrôle la lecture en cours, quelle que soit "
        "sa source), 'set_volume' (fixe le volume RÉEL du périphérique de lecture Windows par "
        "défaut à 'percent', 0-100 — pas juste le volume de Jarvis), 'volume_delta' (ajuste ce "
        "même volume système de 'delta' points de pourcentage, positif ou négatif)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "play_mood", "play_local", "pause", "resume", "next", "previous",
                    "set_volume", "volume_delta",
                ],
                "description": "Action à effectuer.",
            },
            "query": {
                "type": "string",
                "description": (
                    "Pour play_mood : genre/ambiance recherché sur SoundCloud (requis). "
                    "Pour play_local : filtre optionnel sur le nom des fichiers."
                ),
            },
            "percent": {
                "type": "integer",
                "description": "Pour set_volume : niveau absolu voulu, 0-100 (requis).",
            },
            "delta": {
                "type": "integer",
                "description": (
                    "Pour volume_delta : ajustement en points de pourcentage, "
                    "positif pour monter, négatif pour baisser (requis)."
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, broadcast_event: Callable[[dict], None]) -> None:
        self._broadcast = broadcast_event

    async def execute(self, **kwargs: object) -> ToolResult:
        action = str(kwargs.get("action", ""))
        query = str(kwargs.get("query", "") or "")

        if action == "play_mood":
            return await self._play_mood(query)
        if action == "play_local":
            return self._play_local(query)
        if action in ("pause", "resume", "next", "previous"):
            self._broadcast({"type": "player_control", "action": action})
            labels = {
                "pause": "Pause.",
                "resume": "Lecture reprise.",
                "next": "Piste suivante.",
                "previous": "Piste précédente.",
            }
            return ToolResult(content=labels[action])
        if action == "set_volume":
            return self._set_volume(kwargs.get("percent"))
        if action == "volume_delta":
            return self._volume_delta(kwargs.get("delta"))

        return ToolResult(content=f"Action inconnue : {action}", is_error=True)

    def _default_endpoint_volume(self) -> object:
        """Interface IAudioEndpointVolume du périphérique de lecture Windows
        par défaut. Ne cible pas un périphérique précis (choisi dans les
        réglages Jarvis) — décision produit : moins fiable techniquement,
        le défaut Windows est le patron pycaw bien documenté."""
        from pycaw.pycaw import AudioUtilities

        return AudioUtilities.GetSpeakers().EndpointVolume

    def _set_volume(self, percent: object) -> ToolResult:
        if percent is None:
            return ToolResult(content="'percent' requis pour set_volume.", is_error=True)
        try:
            pct = max(0, min(100, int(percent)))
            vol = self._default_endpoint_volume()
            vol.SetMasterVolumeLevelScalar(pct / 100.0, None)
            return ToolResult(content=f"Volume à {pct}%.")
        except Exception as e:  # noqa: BLE001 — erreurs COM/pycaw peu prévisibles
            collector.error("JRV-TOL-001", "JRV-TOL-001", cause=e)
            logger.warning("PlayerTool set_volume error", error=str(e))
            return ToolResult(content="Impossible de régler le volume du périphérique.", is_error=True)

    def _volume_delta(self, delta: object) -> ToolResult:
        if delta is None:
            return ToolResult(content="'delta' requis pour volume_delta.", is_error=True)
        try:
            vol = self._default_endpoint_volume()
            current_pct = round(vol.GetMasterVolumeLevelScalar() * 100)
            new_pct = max(0, min(100, current_pct + int(delta)))
            vol.SetMasterVolumeLevelScalar(new_pct / 100.0, None)
            return ToolResult(content=f"Volume à {new_pct}%.")
        except Exception as e:  # noqa: BLE001 — erreurs COM/pycaw peu prévisibles
            collector.error("JRV-TOL-001", "JRV-TOL-001", cause=e)
            logger.warning("PlayerTool volume_delta error", error=str(e))
            return ToolResult(content="Impossible de régler le volume du périphérique.", is_error=True)

    async def _play_mood(self, query: str) -> ToolResult:
        if not query:
            return ToolResult(content="'query' requis pour play_mood.", is_error=True)

        try:
            import yt_dlp
        except ImportError as e:
            collector.error("JRV-TOL-001", "JRV-TOL-001", cause=e)
            return ToolResult(content="yt-dlp indisponible.", is_error=True)

        opts = {
            "format": "bestaudio",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"scsearch{_SEARCH_RESULTS}:{query}", download=False)
        except Exception as e:  # noqa: BLE001 — yt-dlp lève des erreurs peu prévisibles (réseau, extracteur)
            collector.error("JRV-TOL-001", "JRV-TOL-001", cause=e)
            logger.warning("PlayerTool SoundCloud search error", query=query, error=str(e))
            return ToolResult(content=f"Recherche SoundCloud échouée pour « {query} ».", is_error=True)

        entries = [e for e in (info or {}).get("entries", []) if e and e.get("url")]
        if not entries:
            return ToolResult(content=f"Aucun résultat SoundCloud pour « {query} ».", is_error=True)

        track = random.choice(entries)
        title = track.get("title") or query
        artist = track.get("uploader") or ""

        # Le CDN SoundCloud rejette probablement les requêtes venant du
        # navigateur (protection anti-hotlink Referer/Origin) — <audio src>
        # pointé dessus directement échouait en silence. On relaie via notre
        # propre serveur (cf. /api/player/proxy) qui porte le Referer/Origin
        # de Jarvis, pas celui du client.
        proxied_url = "/api/player/proxy?url=" + quote(track["url"], safe="")

        self._broadcast(
            {
                "type": "player_play",
                "source": "soundcloud",
                "url": proxied_url,
                "title": title,
                "artist": artist,
            }
        )
        return ToolResult(content=f"Lecture de « {title} »" + (f" ({artist})." if artist else "."))

    def _play_local(self, query: str) -> ToolResult:
        tracks = list_library()
        if query:
            q = query.lower()
            tracks = [t for t in tracks if q in t["filename"].lower()]
        if not tracks:
            msg = (
                f"Aucun fichier local ne correspond à « {query} »."
                if query
                else "Bibliothèque locale vide — dépose des fichiers audio dans music_library/."
            )
            return ToolResult(content=msg, is_error=True)

        random.shuffle(tracks)
        queue = [t["filename"] for t in tracks]

        self._broadcast(
            {
                "type": "player_play",
                "source": "local",
                "queue": queue,
                "index": 0,
            }
        )
        first_title = tracks[0]["title"]
        count = len(tracks)
        suffix = f" (+{count - 1} autres)" if count > 1 else ""
        return ToolResult(content=f"Lecture de « {first_title} »{suffix}.")
