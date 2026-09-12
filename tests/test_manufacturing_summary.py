from app.industry_research.content_quality import chapter_issues
from app.industry_research.writer import _manufacturing_decision_issues, _manufacturing_summary_issues


BRIEF = {'research_template': 'manufacturing', 'excluded_segments': '传统消费品'}


def test_market_chapter_not_treated_as_old_lifecycle_chapter():
    text = '### 市场规模与增速\n- 2023年：100亿元\n- 2024年：120亿元\n- 2025年：140亿元'
    assert not any('应集中到第4章' in issue
                   for issue in chapter_issues(text, 2, 'manufacturing'))


def test_market_percent_and_scope_drift_are_blocked():
    text = '市场规模约为21%。传统消费品是另一市场。传统消费品案例继续展开。'
    issues = _manufacturing_decision_issues(text, 2, BRIEF)
    assert any('市场规模使用百分比' in issue for issue in issues)
    assert any('研究范围漂移' in issue for issue in issues)


def test_decision_summary_contract():
    issues = _manufacturing_summary_issues('决策结论：GO。', BRIEF)
    assert any('缺少' in issue for issue in issues)
    assert any('确定性GO' in issue for issue in issues)
    complete = ('决策状态：条件进入。优先区域为苏州，优先产品为高强箱，优先客户群待验证；'
                '生产模式为外购纸板，投资与流动资金待验证，盈亏平衡利用率待计算；'
                '三个核心风险包括获客风险，NO-GO条件待确认。')
    assert _manufacturing_summary_issues(complete, BRIEF) == []
