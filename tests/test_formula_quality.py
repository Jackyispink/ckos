from app.industry_research.content_quality import sanitize_generated_content, chapter_issues
from app.industry_research.manufacturing import rules


def test_latex_is_rendered_as_plain_text():
    raw='\\[\n\\Delta \\text{Profit} = \\Delta \\text{Price} \\times \\text{Quantity Sold}\n\\]\n其中，\\(\\Delta \\text{Price}\\) 是变动量。'
    cleaned=sanitize_generated_content(raw)
    assert '\\[' not in cleaned and '\\text' not in cleaned and '\\(' not in cleaned
    assert 'Δ 利润 = Δ 单位售价 × 销量' in cleaned


def test_inline_display_sum_from_any_chapter_is_plain_text():
    raw = ('#### TAM公式\n\n'
           '\\[ TAM = \\sum (下游需求 \\times 渗透率 \\times (1 + 增长率)^n) \\]')
    cleaned = sanitize_generated_content(raw)
    assert 'TAM = 求和 (下游需求 × 渗透率 × (1 + 增长率)^n)' in cleaned
    assert not any('LaTeX' in issue for issue in chapter_issues(cleaned, 2))
    assert '\\' not in cleaned


def test_nested_cagr_and_wrapped_fraction_are_preserved_as_readable_math():
    raw = (r'$$ CAGR=\left(\frac{V_{t}}{V_{0}}\right)^{\frac{1}{n}}-1 $$' '\n'
           r'单价=\frac{\text{收入}}{\text{销量}}，阈值\geq 15\%。')
    cleaned = sanitize_generated_content(raw)
    assert 'CAGR=((V_t) ÷ (V_0))^((1) ÷ (n))-1' in cleaned
    assert '单价=(收入) ÷ (销量)' in cleaned
    assert '阈值≥ 15%' in cleaned
    assert '\\' not in cleaned and '$$' not in cleaned


def test_lone_dollar_currency_is_not_treated_as_math_delimiter():
    cleaned = sanitize_generated_content('海外报价为$100/台，公式为 $收入/销量$。')
    assert '$100/台' in cleaned
    assert '公式为 收入/销量。' in cleaned


def test_wrong_yield_utilization_formula_is_blocked():
    text='良率或利用率变动影响：Δ良率 × 销量 × 单位成本。'
    assert any('良率与产能利用率不能合并' in x for x in chapter_issues(text,9))


def test_chapter_eight_prompt_separates_drivers():
    text=rules({'research_template':'manufacturing','manufacturing_type':'other'},8)
    assert '二者不得共用公式' in text and '不输出LaTeX' in text


def test_known_legacy_bad_formula_is_replaced_without_numbers():
    raw=('3. **良率或利用率变动对利润的影响**：良率或利用率变动对利润的影响可以通过以下公式计算：\n\n'
         '\\[\n\\Delta \\text{Profit} = \\Delta \\text{Yield} \\times \\text{Quantity Sold} \\times \\text{Unit Cost}\n\\]\n\n'
         '其中，\\(\\Delta \\text{Yield}\\) 是良率或利用率变动量，\\(\\text{Quantity Sold}\\) 是销售数量，\\(\\text{Unit Cost}\\) 是单位成本。')
    cleaned=sanitize_generated_content(raw)
    assert '良率与产能利用率需要分别测算' in cleaned
    assert '新增销量×单位贡献' in cleaned
    assert 'Δ 良率 × 销量 × 单位成本' not in cleaned
