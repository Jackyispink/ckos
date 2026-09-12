import copy
import pytest
from app.industry_research.research_blocks import ResearchBlock, build_reading_outline, chart_matches, chunks
from app.industry_research import ppt


def sample():
    return dict(project=dict(title='阅读研究',status='complete',brief={},chapters=[dict(chapter_no=4,title='市场规模',content='## 同口径规模\n2023年市场规模100亿元。\n2024年市场规模120亿元。')]),evidence=[],charts=[dict(id='c1',chapter_no=4,title='规模',unit='亿元',labels=['2023','2024'],values=[100,120],source_excerpts=['2023年市场规模100亿元。','2024年市场规模120亿元。'])])


def test_preserve_long_source_and_table():
    s=sample();s['project']['chapters'][0]['content']='## 原文\n'+('完整长句。'*180)+'\n| 企业 | 收入 |\n|---|---|\n|甲|100|\n|乙|120|'
    pages=build_reading_outline(s)
    assert ''.join(p['research']['content'] for p in pages[1:]).strip()=='完整长句。'*180
    assert pages[-1]['research']['rows']==[['甲','100'],['乙','120']]
    assert ''.join(chunks('长'*1001))=='长'*1001


def test_exact_chart_binding_not_same_chapter():
    s=sample();pages=build_reading_outline(s)
    assert pages[1]['research']['chart_ids']==['c1']
    assert not chart_matches('2023年用户规模100万人。',s['charts'][0])
    s['charts'][0]['source_excerpts']=[]
    assert build_reading_outline(s)[1]['research']['chart_ids']==[]


def test_schema_validation():
    with pytest.raises(ValueError):ResearchBlock(id='a',columns=['a'],rows=[['1','2']])
    with pytest.raises(ValueError):ResearchBlock(id='a',content='字'*181,chart_ids=['c'])
    with pytest.raises(ValueError):ResearchBlock(id='a',chart_ids=['c','c'])


def test_reading_job_save_isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(ppt,'STORE',tmp_path);monkeypatch.setattr(ppt.POOL,'submit',lambda *a:None)
    ppt.ACTIVE.clear();s=sample();original=copy.deepcopy(s)
    job=ppt.create('p',s,mode='reading');ppt._plan(job)
    assert job['status']=='draft'
    body=ppt.Outline(revision=1,slides=job['slides']);body.slides[1].research.claim='需要核对的判断'
    saved=ppt.save('p',job['id'],body)
    assert s==original and saved['revision']==2
    body.revision=2;body.slides[1].research.chart_ids=['foreign']
    with pytest.raises(ValueError,match='图表'):ppt.save('p',job['id'],body)
    with pytest.raises(FileNotFoundError):ppt.read('other',job['id'])


def test_reading_rejects_paid_ai(tmp_path,monkeypatch):
    monkeypatch.setattr(ppt,'STORE',tmp_path)
    with pytest.raises(ValueError,match='不调用模型'):ppt.create('p',sample(),ai=True,mode='reading')
