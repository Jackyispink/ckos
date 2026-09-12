import asyncio
import json
import pytest
from app.industry_research import writer

BAD='### 市场规模与增速\n- 2022年：101.7亿元\n- 2023年：373.9亿元\n- 2024年：504.4亿元'
GOOD='本报告将AI短剧限定为使用生成式人工智能参与主要内容生产的短剧。传统真人拍摄的微短剧不自动纳入这一范围。分类时分别说明AI漫剧与仿真人短剧的制作方式，不将二者与整个微短剧市场混为同一统计口径。'

@pytest.mark.parametrize('responses,count,success', [([BAD,GOOD],2,True),([BAD,BAD],2,False),([GOOD],1,True)])
def test_bounded_repair(monkeypatch,responses,count,success):
    monkeypatch.setenv('REPORT_QUALITY_REPAIR_ATTEMPTS','1')
    calls=[];repairs=[]
    async def complete(messages):
        calls.append(messages)
        return responses[len(calls)-1]
    monkeypatch.setattr(writer.llm,'complete',complete)
    messages=[{'role':'user','content':'原始证据'}]
    run=writer._validated_chapter(messages,1,[],lambda:None,repairs.append)
    if success:assert asyncio.run(run)==GOOD
    else:
        with pytest.raises(writer.llm.ModelError,match='已修订1次'):asyncio.run(run)
    assert len(calls)==count and len(messages)==1
    if count==2:assert '章节职责' in calls[1][-1]['content']

def test_disabled_repair_and_transport_error(monkeypatch):
    monkeypatch.setenv('REPORT_QUALITY_REPAIR_ATTEMPTS','0')
    calls=[]
    async def complete(messages):calls.append(messages);return BAD
    monkeypatch.setattr(writer.llm,'complete',complete)
    with pytest.raises(writer.llm.ModelError,match='已关闭'):
        asyncio.run(writer._validated_chapter([],1,[],lambda:None,lambda _:None))
    assert len(calls)==1
    async def broken(messages):raise writer.llm.ModelError('连接失败')
    monkeypatch.setattr(writer.llm,'complete',broken)
    with pytest.raises(writer.llm.ModelError,match='连接失败'):
        asyncio.run(writer._validated_chapter([],1,[],lambda:None,lambda _:pytest.fail('unexpected retry')))


def test_repetition_after_normal_repair_triggers_targeted_supplement(monkeypatch):
    repeated_sentences = [
        '客户采购周期需要结合实际订单、采购责任人与年度招标节点逐项核验，不能直接沿用市场规模结论。',
        '区域选择需要结合运输半径、客户密度、厂房成本与原料供应逐项核验，不能直接沿用全国结论。',
        '产品定位需要结合认证标准、包装测试、交付要求与目标毛利逐项核验，不能直接沿用通用结论。',
        '竞争判断需要结合相同服务半径内的纸箱工厂、有效产能及客户关系逐项核验，不能只引用全国集中度。',
    ]
    repeated = ''.join(repeated_sentences)
    supplemented = (
        '### 客户采购机制\n\n'
        '本章聚焦采购部门、包装研发与质量部门之间的决策关系。现有证据只能确认送样和厂审是准入环节，'
        '具体周期、首批订单比例及账期仍需通过客户访谈验证。[1]\n\n'
        '### 进入验证重点\n\n'
        '下一步应分别记录样品测试标准、审核责任人、年度招标节点和供应商分量规则，形成客户级验证清单。'
    )
    responses = [repeated, repeated, supplemented]
    calls = []

    async def complete(messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(writer.llm, 'complete', complete)
    result = asyncio.run(writer._validated_chapter(
        [{'role': 'user', 'content': '原始证据[1]'}], 4,
        ['\n\n'.join(repeated_sentences)],
        lambda: None, lambda _issues: None,
    ))

    assert result == supplemented
    assert len(calls) == 3
    payload = json.loads(calls[-1][-1]['content'])
    assert payload['task'] == '重复内容专项补写'
    assert payload['forbidden_repeated_material']
    assert '禁止再次写入' in payload['instruction']


def test_unready_city_ranking_triggers_conditional_rewrite(monkeypatch):
    invalid = (
        '### 城市选址与权重\n\n'
        '客户密度权重为25%，物流成本权重为20%。综合比较后推荐城市苏州，'
        '并将其列为第一优先落地区域。'
    )
    repaired = (
        '### 候选城市与评价权重\n\n'
        '候选城市包括苏州与嘉兴。客户密度、物流成本、厂房成本和原料供应均应纳入评价，'
        '各项权重目前待用户确认，因此本报告不计算综合得分，也不形成城市排序。\n\n'
        '如果客户订单主要集中在苏南，则苏州的运输条件需要进一步核验；如果更重视厂房成本与浙江客户覆盖，'
        '则应补充嘉兴的租金、人工、能源及服务半径数据后再比较。'
    )
    responses = [invalid, invalid, repaired]
    calls = []

    async def complete(messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(writer.llm, 'complete', complete)
    result = asyncio.run(writer._validated_chapter(
        [{'role': 'user', 'content': '第7章原始选址证据'}], 7, [],
        lambda: None, lambda _issues: None,
        brief={'research_template': 'manufacturing'},
        decision_readiness={'city': False},
    ))

    assert result == repaired
    assert len(calls) == 3
    payload = json.loads(calls[-1][-1]['content'])
    assert payload['task'] == '未就绪决策结论专项改写'
    assert '不得推荐或排序城市' in payload['instruction']


def test_stubborn_unready_city_scores_are_removed_without_fourth_model_call(monkeypatch):
    invalid = (
        '### 城市选址与权重\n\n城市比较应覆盖客户和物流。\n\n'
        '### 候选城市评分\n\n'
        '| 城市 | 客户密度 | 总分 |\n|---|---:|---:|\n| 上海 | 85 | 90 |\n| 苏州 | 80 | 88 |\n\n'
        '### 推荐城市\n\n- 推荐上海作为首选城市。\n\n'
        '### 待验证数据缺口\n\n需要补充客户密度、物流、厂房、人工、能源、环保和供应链数据。'
    )
    calls = []

    async def complete(messages):
        calls.append(messages)
        return invalid

    monkeypatch.setattr(writer.llm, 'complete', complete)
    result = asyncio.run(writer._validated_chapter(
        [{'role': 'user', 'content': '第7章原始选址证据'}], 7, [],
        lambda: None, lambda _issues: None,
        brief={'research_template': 'manufacturing'},
        decision_readiness={'city': False},
    ))

    assert len(calls) == 3
    assert '总分' not in result
    assert '推荐上海' not in result
    assert '选址结论边界' in result
    assert '不形成地点排序' in result


def test_stubborn_unready_go_is_downgraded_to_verification_hold(monkeypatch):
    invalid = (
        '### SWOT分析\n\n优势、劣势、机会与威胁均需要结合企业数据验证。\n\n'
        '### 决策结论\n\n- **GO**：建议立即进入。\n- **HOLD**：客户资料待验证。\n'
        '- **NO-GO**：回款周期过长时退出。\n\n'
        '### 下一步验证\n\n核验设备、客户、单位经济、现金需求和退出门槛。'
    )
    calls = []

    async def complete(messages):
        calls.append(messages)
        return invalid

    monkeypatch.setattr(writer.llm, 'complete', complete)
    result = asyncio.run(writer._validated_chapter(
        [{'role': 'user', 'content': '第10章原始证据'}], 10, [],
        lambda: None, lambda _issues: None,
        brief={'research_template': 'manufacturing'},
        decision_readiness={'threshold': False},
    ))

    assert len(calls) == 3
    assert '建议立即进入' not in result
    assert '决策状态：待验证（HOLD）' in result
    assert 'GO／HOLD／NO-GO门槛框架' in result
    assert writer._declared_decision_state(result) is None
