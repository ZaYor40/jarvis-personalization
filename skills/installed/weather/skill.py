from skills.base import SkillBase


class WeatherSkill(SkillBase):
    SYSTEM_PROMPT = (
        "Vue \"weather\" installée : Météo immersive — scène de ciel animée, conditions et prévisions horaires (Open-Meteo) "
        "Pour l'afficher : show_view(action=\"show\", view_id=\"weather\"). "
        "Pour la masquer : show_view(action=\"hide\", view_id=\"weather\")."
    )

    def get_tools(self) -> list:
        return []
