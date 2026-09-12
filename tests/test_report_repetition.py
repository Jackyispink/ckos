from app.industry_research.content_quality import repetition_issues, quality_issues
from app.industry_research.content_quality import chapter_issues, complete_context

def test_repeated_chapter_is_blocked():
    text='。'.join(('不同用户对多样化和高质量娱乐内容的需求不断增加需要明确说明样本范围','行业各环节的盈利能力取决于技术成本渠道费用以及客户回款条件','行业竞争格局发生变化需要结合企业市场份额与客户认证门槛分析','研究结论需要区分已发生事实以及未来预测并清楚标明每条证据的来源'))
    assert repetition_issues(text,[text])
    assert repetition_issues(text+'。'+text)

def test_single_reused_fact_does_not_block():
    text='行业各环节的盈利能力取决于技术成本渠道费用以及客户回款条件'
    assert not repetition_issues(text,[text])

def test_broken_question_answer_splice_is_flagged():
    assert any('拼接' in x for x in quality_issues('当前市场规模、销量或装机量分别为2025年AI短剧用户规模快速增长。'))


def test_short_data_list_duplicates():
    rows='- 2022年：101.7亿元\n- 2023年：373.9亿元\n- 2024年：504.4亿元'
    assert any('数据列表' in x for x in repetition_issues(rows,[rows]))
    assert any('数据列表' in x for x in repetition_issues(rows+'\n'+rows))
    assert not repetition_issues('- 2024年：504.4亿元',[rows])


def test_tail_fragments_and_legitimate_english_names():
    assert chapter_issues('### 内容产量与传播趋势\n- 2025年1月，抖音TO',4)
    assert chapter_issues('完整的正文。\n### 后续趋势',4)
    assert chapter_issues('未来主要包括：',4)
    assert not chapter_issues('- 核心厂商：MiniMax',8)
    assert not chapter_issues('- 2024年：504.4亿元',4)


def test_chapter_scope_and_metric_mixing():
    rows='### 市场规模与增速\n- 2022年微短剧市场：101.7亿元\n- 2023年：373.9亿元\n- 2024年：504.4亿元'
    assert any('章节职责' in x for x in chapter_issues(rows,1))
    assert not chapter_issues(rows,4)
    mixed=rows+'\n- 2025年：AI漫剧市场规模189.8亿元'
    assert any('口径' in x for x in chapter_issues(mixed,4))
    assert any('near' in x for x in chapter_issues('2025年总产值near 900亿元',4))


def test_context_never_cuts_mid_sentence():
    assert complete_context('短句。',100)=='短句。'
    result=complete_context('完整句子。\n2025年1月，抖音TOP榜单相关描述。',18)
    assert '抖音' not in result and '未纳入' in result
    assert complete_context('长'*100,20)=='〔原始段落超过输入预算，未提供不完整片段〕'
