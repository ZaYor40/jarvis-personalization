from __future__ import annotations

from typing import Callable

import httpx

from tools.base import Tool, ToolResult

CITY_COORDS: dict[str, tuple[float, float]] = {
    "paris":         (48.8566,   2.3522),
    "lyon":          (45.7640,   4.8357),
    "marseille":     (43.2965,   5.3698),
    "bordeaux":      (44.8378,  -0.5792),
    "nice":          (43.7102,   7.2620),
    "toulouse":      (43.6047,   1.4442),
    "strasbourg":    (48.5734,   7.7521),
    "nantes":        (47.2184,  -1.5536),
    "saint-lunaire": (48.6340,  -2.1270),
    "new york":      (40.7128, -74.0060),
    "los angeles":   (34.0522, -118.2437),
    "tokyo":         (35.6762, 139.6503),
    "beijing":       (39.9042, 116.4074),
    "london":        (51.5074,  -0.1278),
    "berlin":        (52.5200,  13.4050),
    "madrid":        (40.4168,  -3.7038),
    "rome":          (41.9028,  12.4964),
    "dubai":         (25.2048,  55.2708),
    "sydney":        (-33.8688, 151.2093),
    "moscou":        (55.7558,  37.6176),
}


class ShowViewTool(Tool):
    name = "show_view"
    description = (
        "Affiche ou contrôle une vue visuelle sur l'écran principal de Jarvis.\n\n"
        "Utilise cet outil quand l'utilisateur demande :\n"
        "- \"Montre-moi [ville/lieu]\" / \"Va à Tokyo\" → action: fly_to, location: \"...\"\n"
        "- \"Montre le globe\" / \"Vue monde\" → action: show, view_id: \"globe\"\n"
        "- \"Cache le globe\" / \"Retour\" → action: hide, view_id: \"globe\"\n"
        "- \"Dézoom\" / \"Vue globale\" → action: globe_view\n"
        "- \"Zoom avant\" → action: zoom_in\n"
        "- \"Dézoom\" → action: zoom_out\n\n"
        "Pour fly_to, le globe est automatiquement affiché avant la navigation."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["show", "hide", "fly_to", "zoom_out", "zoom_in", "globe_view"],
                "description": "Action à effectuer.",
            },
            "view_id": {
                "type": "string",
                "description": "ID de la vue (défaut: globe).",
                "default": "globe",
            },
            "location": {
                "type": "string",
                "description": "Nom du lieu à afficher (requis pour fly_to).",
            },
            "zoom": {
                "type": "integer",
                "description": "Niveau de zoom (2–18). Défaut: 10 pour les villes, 5 pour les pays.",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    def __init__(self, broadcast_event: Callable[[dict], None]) -> None:
        self._broadcast = broadcast_event

    async def execute(
        self,
        action: str,
        view_id: str = "globe",
        location: str | None = None,
        zoom: int = 10,
        **_: object,
    ) -> ToolResult:
        if action == "show":
            self._broadcast({"type": "show_view", "view_id": view_id})
            return ToolResult(content=f"Vue {view_id} affichée.")

        if action == "hide":
            self._broadcast({"type": "hide_view", "view_id": view_id})
            return ToolResult(content=f"Vue {view_id} masquée.")

        if action == "fly_to":
            if not location:
                return ToolResult(content="Paramètre location requis pour fly_to.", is_error=True)
            coords = await self._geocode(location)
            if not coords:
                return ToolResult(content=f"Lieu introuvable : {location}", is_error=True)
            lat, lon = coords
            self._broadcast({"type": "show_view", "view_id": "globe"})
            self._broadcast({
                "type": "view_command",
                "view_id": "globe",
                "command": "fly_to",
                "params": {
                    "lat": lat, "lon": lon,
                    "zoom": max(2, min(18, zoom)),
                    "location_name": location,
                },
            })
            return ToolResult(content=f"Navigation vers {location}.")

        if action == "zoom_out":
            self._broadcast({"type": "view_command", "view_id": "globe", "command": "zoom_out", "params": {}})
            return ToolResult(content="Vue dézoomée.")

        if action == "zoom_in":
            self._broadcast({"type": "view_command", "view_id": "globe", "command": "zoom_in", "params": {}})
            return ToolResult(content="Zoom avant.")

        if action == "globe_view":
            self._broadcast({"type": "show_view", "view_id": "globe"})
            self._broadcast({"type": "view_command", "view_id": "globe", "command": "globe_view", "params": {}})
            return ToolResult(content="Vue globe globale.")

        return ToolResult(content=f"Action inconnue : {action}", is_error=True)

    async def _geocode(self, location: str) -> tuple[float, float] | None:
        key = location.lower().strip()
        if key in CITY_COORDS:
            return CITY_COORDS[key]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": location, "format": "json", "limit": 1},
                    headers={"User-Agent": "Jarvis/3.0"},
                )
                results = r.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            pass
        return None
