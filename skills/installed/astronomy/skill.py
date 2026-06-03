from skills.base import SkillBase


class AstronomySkill(SkillBase):
    SYSTEM_PROMPT = (
        "Vue \"astronomy\" installée : Voûte céleste immersive — constellations qui s'illuminent au focus, faits stellaires "
        "Pour l'afficher : show_view(action=\"show\", view_id=\"astronomy\"). "
        "Pour la masquer : show_view(action=\"hide\", view_id=\"astronomy\")."
    )

    def get_tools(self) -> list:
        return []
