"""Widget GitHub — stars, forks, commits récents."""
import os
import httpx
from analytics.widgets.base import WidgetBase, WidgetConfig, WidgetData


class GitHubWidget(WidgetBase):

    id = "github"
    label = "GitHub"
    description = "Stars, forks et activité du repo Jarvis."
    icon = "G"
    requires_env = ["GITHUB_TOKEN", "GITHUB_REPO"]
    size = "small"

    async def fetch(self) -> WidgetData:
        if not self.is_configured():
            return WidgetData(success=False, data={}, error="Config manquante")

        token = os.getenv("GITHUB_TOKEN")
        repo = os.getenv("GITHUB_REPO")  # ex: "Grominet95/jarvis-OS"

        try:
            async with httpx.AsyncClient(
                timeout=10,
                headers={"Authorization": f"Bearer {token}"}
            ) as client:
                r = await client.get(f"https://api.github.com/repos/{repo}")
                data = r.json()

                return WidgetData(
                    success=True,
                    data={
                        "stars": data.get("stargazers_count", 0),
                        "forks": data.get("forks_count", 0),
                        "open_issues": data.get("open_issues_count", 0),
                        "watchers": data.get("watchers_count", 0),
                    }
                )
        except Exception as e:
            return WidgetData(success=False, data={}, error=str(e))
