from app.industry_research.content_quality import chapter_issues
from app.industry_research.writer import (
    _decision_guard, _decision_readiness, _manufacturing_summary_issues,
    _manufacturing_decision_issues,
)


BRIEF = {'research_template': 'manufacturing', 'excluded_segments': '3C包装'}


def test_market_chapter_can_contain_year_series():
    text = '### 市场规模与增速\n- 2023年：100亿元\n- 2024年：120亿元\n- 2025年：140亿元'
    assert not any('应集中到第4章' in issue for issue in chapter_issues(text, 2, 'manufacturing'))


def test_scope_drift_and_market_percentage_are_blocked():
    text = '市场规模为20.3%。3C包装增长。3C包装客户较多。'
    issues = _manufacturing_decision_issues(text, 2, BRIEF)
    assert any('统计口径错误' in issue for issue in issues)
    assert any('研究范围漂移' in issue for issue in issues)


def test_market_size_range_is_blocked_but_growth_and_share_are_not():
    bad = '食品饮料瓦楞箱市场规模在2020年约为20.3%至21.2%。'
    assert any('统计口径错误' in issue
               for issue in _manufacturing_decision_issues(bad, 2, BRIEF))

    valid = ('2025年市场规模为100亿元，同比增长20.3%。'
             '食品饮料在目标市场中的市场规模占比为21.2%。')
    assert not any('统计口径错误' in issue
                   for issue in _manufacturing_decision_issues(valid, 2, BRIEF))

    table = '| 指标 | 数值 |\n| --- | --- |\n| 市场规模 | 20.3% |'
    assert any('统计口径错误' in issue
               for issue in _manufacturing_decision_issues(table, 2, BRIEF))


def test_definite_decision_requires_numeric_bands_and_basis():
    vague = ('### 决策结论\n决策结论：GO。结论来自已确认来源。\n'
             '### SWOT\nSWOT已完成。\nGO、HOLD、NO-GO门槛另行讨论。')
    issues = _manufacturing_decision_issues(vague, 10, BRIEF)
    assert any('缺少完整数字门槛' in issue for issue in issues)
    assert not any('缺少经确认' in issue for issue in issues)

    complete = ('### 决策结论\n决策结论：GO，依据为用户确认的结构化决策记录。\n'
                '### SWOT\nSWOT已完成。\n'
                '| 指标 | GO | HOLD | NO-GO |\n'
                '| --- | --- | --- | --- |\n'
                '| 毛利率 | ≥15% | 10%–15% | <10% |')
    assert not any('确定性GO' in issue
                   for issue in _manufacturing_decision_issues(complete, 10, BRIEF))

    pending = complete + '\n上述门槛来源待确认。'
    assert any('表述矛盾' in issue
               for issue in _manufacturing_decision_issues(pending, 10, BRIEF))


def test_latex_residue_and_vague_conditions_are_blocked():
    formula = r'利润使用 $$\frac{收入}{销量}$$ 计算。'
    assert any('LaTeX' in issue or '转义' in issue
               for issue in _manufacturing_decision_issues(formula, 8, BRIEF))

    vague = '如果企业具备足够的技术能力和足够资金，条件成熟时建议进入。'
    assert any('空泛' in issue
               for issue in _manufacturing_decision_issues(vague, 10, BRIEF))

    summary = ('决策状态：GO，毛利率≥15%，来源已确认。优先区域为苏州；优先产品为高强产品；'
               '优先客户为饮料企业；生产模式为外购加工；投资与流动资金由程序计算；'
               '盈亏平衡利用率为60%；核心风险为获客；NO-GO退出条件见第10章。')
    assert not any('确定性GO' in issue
                   for issue in _manufacturing_summary_issues(summary, BRIEF))
    assert any('空泛' in issue
               for issue in _manufacturing_summary_issues(summary + '需具备足够资金。', BRIEF))


def test_decision_summary_contract_and_go_basis():
    incomplete = '决策结论：GO。优先产品为高强度产品。'
    issues = _manufacturing_summary_issues(incomplete, BRIEF)
    assert any('缺少' in issue for issue in issues)
    assert any('确定性GO' in issue for issue in issues)

    complete = ('决策状态：条件进入。优先区域为苏州；优先产品为高强产品；优先客户群待验证；'
                '生产模式为外购加工；投资与流动资金待验证；盈亏平衡利用率待计算；'
                '核心风险为客户认证；NO-GO条件待用户确认。')
    assert _manufacturing_summary_issues(complete, BRIEF) == []


def test_decision_readiness_requires_verified_resolved_record():
    rows = [
        {'record_type': 'market', 'basis': 'calculated', 'verified': True,
         'fields': {'gaps': [], 'pending': []}},
        {'record_type': 'finance', 'basis': 'calculated', 'verified': True,
         'fields': {'gaps': [], 'pending': ['unit_price']}},
        {'record_type': 'threshold', 'basis': 'assumption', 'verified': True,
         'fields': {'gaps': [], 'pending': []}},
    ]
    ready = _decision_readiness(rows)
    assert ready['market'] is True
    assert ready['finance'] is False
    assert ready['threshold'] is False
    assert '不得给出项目CAPEX' in _decision_guard(8, ready)


def test_unready_modules_block_model_invented_decision_numbers():
    ready = _decision_readiness([])
    market = 'TAM：100亿元；SAM：30亿元；SOM：2亿元。'
    finance = '初始投资：5000万元；盈亏平衡利用率：60%。'
    decision = ('### SWOT\nSWOT已完成。\n### 决策结论\n决策结论：GO。'
                '\nGO：毛利率≥15%\nHOLD：毛利率10%–15%\nNO-GO：毛利率<10%\n来源已确认。')
    assert any('市场测算未就绪' in item
               for item in _manufacturing_decision_issues(market, 2, BRIEF, ready))
    assert any('财务测算未就绪' in item
               for item in _manufacturing_decision_issues(finance, 8, BRIEF, ready))
    assert any('决策门槛未就绪' in item
               for item in _manufacturing_decision_issues(decision, 10, BRIEF, ready))
