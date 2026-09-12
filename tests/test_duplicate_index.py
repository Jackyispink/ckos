from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import database,duplicates,duplicate_index,kb
from app.main import app


def word(text,bold=False):
    doc=Document();doc.add_paragraph(text).runs[0].bold=bold
    stream=BytesIO();doc.save(stream);return stream.getvalue()


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(kb,'ROOT',tmp_path);monkeypatch.setattr(database,'ROOT',tmp_path)
    with TestClient(app) as c: yield c


def send(client,text,company='甲甲公司',title='企业报告',**fields):
    return client.post('/api/documents/upload',data={'company_name':company,'report_title':title,**fields},files={'file':('test.docx',word(text))})


def test_fixed_weights_and_incremental_persistence(client,monkeypatch):
    assert send(client,'制造企业设备保养和人才培养方案。'*20).status_code==201
    with database.connect() as db:
        before=db.execute('SELECT * FROM dedup_documents').fetchone()
        version=db.execute('SELECT id FROM dedup_models WHERE active').fetchone()['id']
    monkeypatch.setattr(duplicates,'weights_for',lambda *a:pytest.fail('must not recompute corpus weights'))
    response=send(client,'农业种植病虫害预防及滴灌节水。'*20,company='乙乙公司')
    assert response.status_code==201,response.text
    assert response.json()['check']['indexes_updated']==0
    with database.connect() as db:
        assert db.execute('SELECT * FROM dedup_documents WHERE document_id=%s',(before['document_id'],)).fetchone()==before
        assert db.execute('SELECT count(*) n FROM dedup_documents').fetchone()['n']==2
        assert db.execute('SELECT id FROM dedup_models WHERE active').fetchone()['id']==version
        # Simulate restart: database index must suffice without reopening existing DOCX files.
        duplicate_index._models.clear()
        monkeypatch.setattr(duplicates,'extract',lambda *a:pytest.fail('must use persisted profile'))
        assert duplicate_index.ensure(db,duplicates.inventory(db))[3]==0


def test_exact_hash_is_independent_of_lsh_and_company(client,monkeypatch):
    text='原文完全相同但调整了排版和企业标记。'*30
    assert send(client,text).status_code==201
    monkeypatch.setattr(duplicate_index,'bands',lambda *a:[])
    response=client.post('/api/documents/upload',data={'company_name':'其他公司','report_title':'另一个名字','check_mode':'fast'},files={'file':('new.docx',word(text,True))})
    assert response.status_code==409
    assert response.json()['detail']['code']=='exact_duplicate'


def test_lsh_finds_cross_company_revision(client):
    text=''.join(f'工序{i}的产能测量与质量管控需要建立第{i+3}号档案。' for i in range(60))
    assert send(client,text).status_code==201
    r=send(client,text+'新增季度管理复盘。',company='另一家公司')
    assert r.status_code==409,r.text
    assert r.json()['detail']['code']=='similar_content'
    assert r.json()['detail']['check']['candidates']==1


def test_strict_checks_all_when_approximate_candidates_miss(client,monkeypatch):
    text=''.join(f'生产管理第{i}项改进措施，关注设备维修效率与安全质量。' for i in range(70))
    assert send(client,text).status_code==201
    incoming=duplicates.extract(BytesIO(word(text+'修订两项指标。')))
    monkeypatch.setattr(duplicate_index,'bands',lambda *a:[])
    with database.connect() as db:
        rows=duplicates.inventory(db)
        matches,stats,_=duplicate_index.check(db,rows,incoming,90,'不同公司',mode='fast')
        assert not matches and stats['candidates']==0
        matches,stats,_=duplicate_index.check(db,rows,incoming,90,'不同公司',mode='strict')
        assert matches and stats['candidates']==stats['documents']==1


def test_backfill_only_missing_and_refresh_explicit(client):
    assert send(client,'设备维护流程与培训体系建立。'*30).status_code==201
    with database.connect() as db:
        rows=duplicates.inventory(db)
        old=db.execute('SELECT id FROM dedup_models WHERE active').fetchone()['id']
        db.execute('DELETE FROM dedup_documents WHERE document_id=%s',(rows[0]['id'],))
        mid,_,_,n=duplicate_index.ensure(db,rows)
        assert n==1 and mid==old
        mid,_,_,n=duplicate_index.ensure(db,rows,refresh_weights=True)
        assert n==1 and mid!=old
        assert db.execute('SELECT count(*) n FROM dedup_models WHERE active').fetchone()['n']==1


def test_invalid_mode_rejected_before_ingestion(client):
    r=send(client,'测试内容',check_mode='anything')
    assert r.status_code==422
    assert client.get('/api/status').json()['documents']==[]
