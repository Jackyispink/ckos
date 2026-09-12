import json
import pytest
from app.industry_research import ppt


@pytest.fixture
def snapshot():
    return dict(project=dict(id='p1',title='行业研究',status='complete',brief={},chapters=[dict(chapter_no=i,title='章节',content='这是完整的第一条研究结论。\n这是第二条研究结论。\n这是第三条研究结论。\n这是第四条研究结论。\n这是第五条研究结论。\n这是第六条研究结论。') for i in range(11)]),evidence=[],charts=[])


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(ppt,'STORE',tmp_path/'presentations')
    monkeypatch.setattr(ppt.POOL,'submit',lambda *args:None)
    ppt.ACTIVE.clear()
    yield
    ppt.ACTIVE.clear()


def draft(snapshot):
    job=ppt.create('p1',snapshot)
    ppt._plan(job)
    return ppt.read('p1',job['id'])


def test_outline_18_pages_and_independent_snapshot(snapshot):
    job=draft(snapshot)
    assert job['status']=='draft' and len(job['slides'])==18
    snapshot['project']['chapters'][0]['content']='Changed'
    assert 'Changed' not in job['snapshot']['project']['chapters'][0]['content']
    assert 'snapshot' not in ppt.public(job)
    assert len(ppt.listing('p1'))==1


def test_save_revision_cross_project_and_chart_validation(snapshot):
    job=draft(snapshot)
    body=ppt.Outline(revision=1,slides=job['slides'])
    saved=ppt.save('p1',job['id'],body)
    assert saved['revision']==2
    with pytest.raises(ValueError,match='已更新'):ppt.save('p1',job['id'],body)
    with pytest.raises(FileNotFoundError):ppt.read('p2',job['id'])
    body.revision=2;body.slides[1].chart_id='invented'
    with pytest.raises(ValueError,match='图表'):ppt.save('p1',job['id'],body)


def test_restart_recovers_and_empty_outline_cannot_export(snapshot):
    job=ppt.create('p1',snapshot)
    ppt.ACTIVE.clear()
    assert ppt.read('p1',job['id'])['status']=='interrupted'
    with pytest.raises(ValueError,match='大纲'):ppt.export('p1',job['id'])
    with pytest.raises(ValueError):ppt.read('p1','../../elsewhere')


def test_failed_model_does_not_touch_report(snapshot,monkeypatch):
    monkeypatch.setattr(ppt.llm,'configured',lambda:True)
    async def broken(*args): raise ppt.llm.ModelError('测试模型错误')
    monkeypatch.setattr(ppt.llm,'complete',broken)
    job=ppt.create('p1',snapshot,True);ppt._plan(job)
    assert ppt.read('p1',job['id'])['status']=='failed'
    assert snapshot['project']['status']=='complete'


def test_render_success_and_invalidated_download(snapshot,monkeypatch):
    job=draft(snapshot)
    def fake_render(args,**kwargs):
        data=json.loads(__import__('pathlib').Path(args[-1]).read_text(encoding='utf-8'))
        folder=__import__('pathlib').Path(data['output'])
        (folder/'output').mkdir()
        (folder/'output'/'report.pptx').write_bytes(b'fake-test-pptx')
        (folder/'manifest.json').write_text('{"count":18}')
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(ppt,'runtime',lambda:{'node':'node'})
    monkeypatch.setattr(ppt.subprocess,'run',fake_render)
    ppt.export('p1',job['id']);ppt._render(job)
    complete=ppt.read('p1',job['id'])
    assert complete['status']=='complete'
    assert ppt.asset('p1',job['id'],'report.pptx').exists()
    ppt.save('p1',job['id'],ppt.Outline(revision=1,slides=job['slides']))
    with pytest.raises(ValueError):ppt.asset('p1',job['id'],'report.pptx')


def test_api_history_snapshot_and_project_isolation(snapshot,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.industry_research import ppt_router
    app=FastAPI();app.include_router(ppt_router.router)
    monkeypatch.setattr(ppt_router.database,'project',lambda pid: {'id':pid})
    monkeypatch.setattr(ppt_router.database,'get_version',lambda pid,vid: {'snapshot':snapshot} if pid=='p1' and vid=='v1' else None)
    client=TestClient(app)
    base='/api/industry/projects/p1/ppt'
    response=client.post(base,json={'version_id':'v1'})
    assert response.status_code==202
    jid=response.json()['id']
    ppt._plan(ppt.read('p1',jid))
    job=client.get(base+'/'+jid).json()
    assert len(job['slides'])==18
    assert client.get('/api/industry/projects/p2/ppt/'+jid).status_code==404
    assert client.get(base+'/'+jid+'/download').status_code==409
    assert client.put(base+'/'+jid,json={'revision':1,'slides':job['slides']}).status_code==200
    assert client.put(base+'/'+jid,json={'revision':1,'slides':job['slides']}).status_code==409
    assert client.post(base,json={'version_id':'missing'}).status_code==404


def test_invalid_ai_page_count_falls_back_without_retry(snapshot, monkeypatch):
    monkeypatch.setattr(ppt.llm,'configured',lambda:True)
    calls=[]
    async def invalid(messages):
        calls.append(messages)
        return '[]'
    monkeypatch.setattr(ppt.llm,'complete',invalid)
    job=ppt.create('p1',snapshot,True);ppt._plan(job)
    result=ppt.read('p1',job['id'])
    assert result['status']=='draft'
    assert len(calls)==11
    assert result['slides']==ppt.build_outline(snapshot)
    assert result['planning_warnings']
    ppt.save('p1',job['id'],ppt.Outline(revision=1,slides=result['slides']))


def test_model_pages_atomic_length_validation():
    pages=[dict(title='页面',chapter=4,layout='chart',bullets=['原文'],chart_id='c',enabled=True)]*2
    response=json.dumps([{'title':'新标题','bullets':['合格']},{'title':'错误','bullets':['字'*66]}])
    with pytest.raises(ValueError,match='限制'):ppt._model_pages(response,pages)
    assert pages[0]['title']=='页面'
    valid=json.dumps({'pages':[{'title':'新标题','bullets':['合格']}]*2})
    assert len(ppt._model_pages(valid,pages))==2


def test_save_identifies_page_and_disabled_page_can_be_kept(snapshot):
    job=draft(snapshot)
    body=ppt.Outline(revision=1,slides=job['slides'])
    body.slides[1].bullets=['字'*111]
    with pytest.raises(ValueError,match='第2页.*第1条.*111字'):ppt.save('p1',job['id'],body)
    body.slides[1].enabled=False
    assert ppt.save('p1',job['id'],body)['status']=='draft'


def test_outline_fills_from_later_valid_sentences(snapshot):
    chapter=snapshot['project']['chapters'][1]
    chapter['content']='长'*90+'。\n'+'\n'.join(f'有效事实{n}包含统计口径及条件。' for n in range(6))
    slides=ppt.build_outline(snapshot)
    page=next(p for p in slides if p['chapter']==1)
    assert len(page['bullets'])<=4
    assert all(p in chapter['content'].replace('\n','') for p in page['bullets'])
    assert sum(map(len,page['bullets']))>150


def test_outline_reserves_material_for_later_pages(snapshot):
    slides=[p for p in ppt.build_outline(snapshot) if p['chapter']==8]
    assert len(slides)==2 and all(p['bullets'] for p in slides)
    assert not set(slides[0]['bullets']) & set(slides[1]['bullets'])


def test_model_allows_four_text_points_but_not_four_chart_points():
    page=dict(title='正文',chapter=1,layout='conclusions',bullets=[],enabled=True,chart_id=None)
    response=json.dumps([dict(title='正文',bullets=['事实一','事实二','原因','限制'])])
    assert len(ppt._model_pages(response,[page])[0]['bullets'])==4
    page['layout']='chart'
    with pytest.raises(ValueError,match='数量'):ppt._model_pages(response,[page])


def test_richer_source_sentences_are_not_discarded(snapshot):
    texts=[f'研究维度{n}：'+('具体判断及其依据和适用条件。'*5) for n in range(4)]
    assert all(65<len(t)<=110 for t in texts)
    # One complete sentence per item, preserving wording without truncation.
    texts=[t.replace('。','，').rstrip('，')+'。' for t in texts]
    snapshot['project']['chapters'][1]['content']='\n'.join(texts)
    page=next(s for s in ppt.build_outline(snapshot) if s['chapter']==1)
    assert page['bullets']==texts
    assert sum(map(len,page['bullets']))>260


def test_single_page_object_and_linebreaks_are_losslessly_normalized():
    page=dict(title='正文',chapter=3,layout='conclusions',bullets=[],enabled=True,chart_id=None)
    response=json.dumps({'title':'政策环境','bullets':['具体政策\n及其适用范围。']})
    output=ppt._model_pages(response,[page])
    assert output[0]['bullets']==['具体政策 及其适用范围。']
    assert output[0]['chapter']==3


@pytest.mark.parametrize('response,reason',[
    ('not json','有效JSON'), ('[]','需要1页'),
    ('[{"title":"标题","bullets":[12]}]','非字符串'),
    ('[{"title":"标题"}]','缺少'),
])
def test_model_failure_reason_is_actionable(response,reason):
    page=dict(title='正文',chapter=3,layout='conclusions',bullets=[],enabled=True,chart_id=None)
    with pytest.raises(ValueError,match=reason):ppt._model_pages(response,[page])


def test_busy_guard_rejects_without_creating_another_job(snapshot):
    job=ppt.create('p1',snapshot)
    with pytest.raises(ValueError,match='不要重复'):ppt.ensure_available('p1')
    assert len(list(ppt.STORE.glob('*/job.json')))==1
    ppt._plan(job)
    ppt.ensure_available('p1')


def test_public_limits_match_backend_and_allow_110_char_flow(snapshot):
    job=draft(snapshot)
    assert ppt.public(job)['point_limits']['flow']==110
    assert ppt.public(job)['point_limits']['chart']==65
    body=ppt.Outline(revision=job['revision'],slides=job['slides'])
    body.slides[3].layout='flow'
    body.slides[3].bullets=['字'*110]
    assert ppt.save('p1',job['id'],body)['status']=='draft'
