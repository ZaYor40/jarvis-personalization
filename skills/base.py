"""Classe de base pour tous les skills Jarvis."""
from __future__ import annotations
from abc import ABC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.base import Tool


class SkillBase(ABC):
    """
    Un skill est une extension de capacité pour Jarvis.

    SYSTEM_PROMPT est injecté automatiquement dans le contexte
    de Jarvis à chaque conversation quand le skill est installé.

    get_tools() permet à un skill d'exposer des outils qui seront
    automatiquement enregistrés dans le ToolRegistry.
    """

    SYSTEM_PROMPT: str = ""

    def __init__(self, metadata: dict = None):
        self.metadata = metadata or {}
        self.name = metadata.get("name", self.__class__.__name__)
        self.version = metadata.get("version", "1.0.0")
        self.author = metadata.get("author", "unknown")
        self.description = metadata.get("description", "")
        self.tags = metadata.get("tags", [])

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT.strip()

    def get_tools(self) -> list["Tool"]:
        """Retourne les outils fournis par ce skill (vide par défaut)."""
        return []

    def is_active(self) -> bool:
        return bool(self.SYSTEM_PROMPT)

    def __repr__(self):
        return f"<Skill {self.name} v{self.version} by {self.author}>"
