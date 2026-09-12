from .base import DataRequirement


def requirements_for(chapter_no: int, brief: dict):
    """Only claim coverage where a generic dataset directly supports the chapter."""
    if chapter_no == 3 and brief.get('geography', '中国') == '中国':
        return [
            DataRequirement('china_gdp', '经济增长', 3),
            DataRequirement('china_ppi', '工业价格环境', 3),
            DataRequirement('china_pmi', '制造业景气度', 3),
        ]
    return []
