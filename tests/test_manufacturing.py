from app.industry_research.schemas import ResearchBrief
from app.industry_research.planner import build_plan
from app.industry_research.manufacturing import rules

def test_legacy_template_unchanged():
    b=ResearchBrief(topic='机器人')
    assert b.research_template=='general'
    assert build_plan(b)[6]['title']=='行业竞争格局'
    assert rules(b.model_dump(),3)==''

def test_manufacturing_routing_and_swot():
    b=ResearchBrief(topic='机器人',research_template='manufacturing',manufacturing_type='equipment',target_company='甲公司',downstream_applications='汽车')
    plan=build_plan(b)
    assert len(plan)==10 and 'TAM/SAM/SOM' in plan[1]['title'] and 'GO/HOLD/NO-GO' in plan[9]['title']
    assert any('甲公司' in q for q in plan[9]['questions'])
    assert any('汽车' in q for q in plan[2]['queries'])
    assert '现金转换周期' in rules(b.model_dump(),8)
    assert '内部优势劣势' in rules(b.model_dump(),10)


def test_manufacturing_queries_include_focus_scope_and_exclusion_boundary():
    b = ResearchBrief(topic='瓦楞纸箱', research_template='manufacturing',
                      product_scope='食品饮料运输外包装', included_segments='防潮高强箱',
                      excluded_segments='食品一次包装', focus='长三角与珠三角')
    plan = build_plan(b)
    assert all('食品饮料运输外包装' in item['queries'][0] for item in plan)
    assert any('防潮高强箱' in query and '长三角与珠三角' in query
               for query in plan[1]['queries'])
    assert any('食品一次包装' in query and '区别' in query for query in plan[0]['queries'])


def test_deep_brief_keeps_long_focus_but_compacts_search_queries():
    long_focus = ('市场规模、销量、客户认证、核心工艺、设备、原材料、成本、区域产能与风险；' * 30)
    long_scope = ('新能源汽车热泵空调和电池热管理使用的电子膨胀阀；' * 20)
    brief = ResearchBrief(
        topic='新能源汽车热管理用电子膨胀阀',
        research_template='manufacturing',
        depth='deep',
        focus=long_focus,
        included_segments=long_scope,
        product_scope=long_scope,
    )
    assert brief.focus == long_focus
    plan = build_plan(brief)
    assert max(len(query) for chapter in plan for query in chapter['queries']) < 800
    assert all(long_focus not in query for chapter in plan for query in chapter['queries'])

def test_no_company_swot_marks_unknown_capabilities():
    b=ResearchBrief(topic='机床',research_template='manufacturing')
    assert '拟进入企业SWOT（待验证）' in rules(b.model_dump(),10)
    assert 'S/W仅列待核实条件' in rules(b.model_dump(),10)
    assert '权重属于企业偏好' in rules(b.model_dump(),7)


def test_entry_perspective_and_supply_customer_region():
    b=ResearchBrief(topic='机床',research_template='manufacturing')
    plan=build_plan(b)
    for chapter, term in [(3,'客户'),(4,'供应商'),(7, '选址')]:
        assert any(term in query for query in plan[chapter-1]['queries'])
        assert term in rules(b.model_dump(),chapter)
    assert '企业进入风险' in rules(b.model_dump(),9)
    assert 'SWOT' in plan[9]['title']


def test_deep_research_expands_questions_and_budgets():
    from app.industry_research.manufacturing import collection_budget, word_budget
    standard=ResearchBrief(topic='机床',research_template='manufacturing')
    deep=standard.model_copy(update={'depth':'deep'})
    assert len(build_plan(deep)[3]['questions']) > len(build_plan(standard)[3]['questions'])
    assert collection_budget(deep.model_dump(),4)['queries'] == 9
    assert collection_budget(deep.model_dump(),4)['target'] == 18
    assert word_budget(deep.model_dump(),4) == 3520
    assert '反例' in rules(deep.model_dump(),4)

def test_manufacturing_budgets_and_evidence():
    from app.industry_research.manufacturing import word_budget, evidence_checklist
    assert word_budget({},4)==1200
    b={'research_template':'manufacturing','depth':'deep'}
    assert word_budget(b,4)>word_budget(b,1)
    assert '采购量' in evidence_checklist(b,3)
    assert '基准值' in evidence_checklist(b,8)

def test_prompt_receives_manufacturing_rules():
    from app.industry_research.writer import _chapter_prompt
    b=ResearchBrief(topic='机床',research_template='manufacturing',manufacturing_type='equipment').model_dump()
    p=_chapter_prompt(b,{'chapter_no':8,'title':'经营质量','questions':[]},[], '')
    assert '2600字' in p and 'CAPEX/OPEX' in p and '现金转换周期' in p


def test_manufacturing_prompt_assigns_market_model_to_chapter_two():
    from app.industry_research.writer import _chapter_prompt
    b=ResearchBrief(topic='机床',research_template='manufacturing').model_dump()
    p=_chapter_prompt(b,{'chapter_no':2,'title':'细分需求与市场空间','questions':[]},[], '')
    assert 'TAM/SAM/SOM统一在第2章' in p
    assert '规模与增速详表集中在第4章' not in p
    assert '两个独立A/B级原始来源' in p


def test_manufacturing_summary_digest_keeps_decision_tail_and_records():
    from app.industry_research.writer import _summary_digest
    chapters=[]
    for number in range(1,11):
        tail=('## 投资与决策结论\nCAPEX为待验证，盈亏平衡利用率需要程序计算。\n'
              '| 指标 | GO | NO-GO |\n| --- | --- | --- |\n| 毛利率 | 待验证 | 待验证 |')
        chapters.append({'chapter_no':number,'title':f'标题{number}',
                         'content':f'本章开头结论{number}。\n' + ('普通分析。\n' * 300) + tail})
    records=[{'record_type':'finance','name':'基准情景','fields':{'capex':1000},
              'basis':'assumption','source':'用户录入','as_of_date':'2026-09-08','verified':False}]
    digest=_summary_digest(chapters,records,manufacturing=True,budget=12000)
    assert len(digest) <= 12000
    assert all(f'第{number}章 标题{number}' in digest for number in range(1,11))
    assert '本章开头结论10' in digest
    assert 'CAPEX为待验证' in digest
    assert '<structured_decision_records>' in digest
    assert '基准情景' in digest
