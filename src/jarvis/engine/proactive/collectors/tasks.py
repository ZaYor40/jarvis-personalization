"""
TaskCollector — récupère les tâches Notion non cochées.
Réutilise le tool notion existant.
"""

from __future__ import annotations

from datetime import datetime

from jarvis.capabilities.tools.notion import NotionTasksTool
from jarvis.engine.proactive.collectors.base import CollectorBase
from jarvis.engine.proactive.schemas import ContextItem, ItemType, Priority


class TaskCollector(CollectorBase):
    name = "tasks"

    async def _collect(self) -> list[ContextItem]:

        tool = NotionTasksTool()
        result = await tool.execute()

        if result.is_error or not result.content:
            return []

        items = []
        now = datetime.now()

        for line in result.content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            items.append(
                ContextItem(
                    type=ItemType.TASK,
                    title=line,
                    summary=line,
                    raw=line,
                    source="notion",
                    timestamp=now,
                    priority=Priority.MEDIUM,
                )
            )

        return items
