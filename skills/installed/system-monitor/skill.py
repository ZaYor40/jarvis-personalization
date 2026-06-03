from skills.base import SkillBase


class SystemMonitorSkill(SkillBase):
    SYSTEM_PROMPT = (
        "Vue \"system-monitor\" installée : Cockpit système temps réel — jauges CPU/RAM/disque, cerveau LLM, services, missions "
        "Pour l'afficher : show_view(action=\"show\", view_id=\"system-monitor\"). "
        "Pour la masquer : show_view(action=\"hide\", view_id=\"system-monitor\")."
    )

    def get_tools(self) -> list:
        return []
