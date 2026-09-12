from app.industry_research.content_quality import deduplicate_exact_paragraphs, remove_repeated_material, remove_unready_location_conclusions, remove_unready_final_decisions

TEXT = '企业需要明确本产品的采购标准和供应商准入条件，同时确认产品验证流程与回款安排，现有资料不足以量化客户认证周期。'


def test_exact_duplicate_and_empty_heading_removed():
    result, removed = deduplicate_exact_paragraphs('## 客户\n\n'+TEXT+'[1]\n\n## 验证\n\n'+TEXT+'[1]')
    assert result.count(TEXT) == 1
    assert '## 验证' not in result
    assert len(removed) == 1


def test_distinct_citations_and_table_retained():
    content = TEXT+'[1]\n\n'+TEXT+'[2]\n\n| 原料 | 成本 |\n| A | 20 |'
    result, removed = deduplicate_exact_paragraphs(content)
    assert result == content and not removed


def test_idempotent():
    result, _ = deduplicate_exact_paragraphs(TEXT+'\n\n'+TEXT)
    assert deduplicate_exact_paragraphs(result) == (result, [])


def test_exact_prose_paragraph_already_used_by_prior_chapter_is_removed():
    prior = '## 市场\n\n' + TEXT
    current = '## 客户\n\n' + TEXT + '\n\n客户采购链仍需单独访谈核实，不能由市场规模资料替代。'
    result, removed = deduplicate_exact_paragraphs(current, [prior])
    assert TEXT not in result
    assert removed == [TEXT]
    assert '客户采购链' in result


def test_remove_repeated_material_keeps_unique_skeleton_and_drops_numeric_rows():
    sentence = '市场需求需要结合地区客户密度和运输半径进行判断，不能直接沿用全国市场结论。'
    prior = sentence + '\n- 2024年市场规模：100亿元'
    current = (
        '## 区域分析\n'
        + sentence + '本章新增分析聚焦客户认证路径与区域交付差异。\n'
        '- 2024年市场规模：100亿元\n'
        '- 2025年目标客户数量：30家'
    )

    result, removed = remove_repeated_material(current, [prior])

    assert sentence not in result
    assert '本章新增分析' in result
    assert '2024年市场规模' not in result
    assert '2025年目标客户数量' in result
    assert len(removed) == 2


def test_remove_unready_location_conclusions_keeps_gaps_not_scores():
    content = (
        '### 评分维度与权重\n\n客户与物流需要比较。\n\n'
        '### 候选城市评分\n\n| 城市 | 总分 |\n|---|---:|\n| 上海 | 90 |\n\n'
        '### 推荐城市\n\n推荐上海作为首选城市。\n\n'
        '### 数据缺口\n\n需要补充客户密度和物流成本。'
    )

    result, removed = remove_unready_location_conclusions(content)

    assert '候选城市评分' not in result
    assert '推荐上海' not in result
    assert '需要补充客户密度' in result
    assert '评价权重须由用户确认' in result
    assert removed


def test_remove_unready_final_decisions_preserves_swot_and_next_steps():
    content = (
        '### SWOT分析\n\n优势与风险仍需企业数据验证。\n\n'
        '### 决策结论\n\n- GO：建议进入。\n- HOLD：暂缓。\n- NO-GO：退出。\n\n'
        '### 下一步验证\n\n核验客户订单、回款周期和单位经济。'
    )

    result, removed = remove_unready_final_decisions(content)

    assert 'SWOT分析' in result
    assert '下一步验证' in result
    assert '建议进入' not in result
    assert '待验证（HOLD）' in result
    assert removed
