import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import database, structured, duplicates

router = APIRouter(prefix='/api/manage')


class Names(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    report_title: str = Field(min_length=2, max_length=120)

    @field_validator('company_name','report_title')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if len(value)<2 or any(ord(c)<32 for c in value):
            raise ValueError('名称至少两个字且不能包含控制字符')
        return value


class Content(BaseModel):
    module: str = Field(min_length=1,max_length=100)
    section: str = Field(min_length=1,max_length=50)
    text: str = Field(min_length=1,max_length=30000)

    @field_validator('module','section','text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():
            raise ValueError('内容不能为空')
        return value.strip()


class State(BaseModel):
    deleted: bool


def audit(db,target,action,before):
    db.execute('INSERT INTO content_audit(target_id,action,before_value) VALUES (%s,%s,%s::jsonb)',(target,action,json.dumps(before,ensure_ascii=False,default=str)))


def report(db,did):
    row=db.execute('SELECT * FROM documents WHERE id=%s',(did,)).fetchone()
    if not row: raise HTTPException(404,'报告不存在')
    return row


@router.get('/reports')
def reports():
    with database.connect() as db:
        return list(db.execute('''SELECT d.id,COALESCE(l.report_title,d.name) AS title,
          COALESCE(l.company_name,c.name,'待确认企业') AS company,COALESCE(s.deleted,FALSE) AS deleted
          FROM documents d LEFT JOIN document_labels l ON l.document_id=d.id
          LEFT JOIN document_state s ON s.document_id=d.id
          LEFT JOIN kb_reports r ON r.document_id=d.id AND r.active LEFT JOIN kb_companies c ON c.id=r.company_id ORDER BY title'''))


@router.patch('/reports/{did}/names')
def names(did:str,body:Names):
    with database.connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(%s)', (duplicates.LOCK,))
        old=report(db,did)
        duplicates.check_names(duplicates.inventory(db),body.company_name,body.report_title,exclude_id=did)
        label=db.execute('SELECT * FROM document_labels WHERE document_id=%s',(did,)).fetchone()
        audit(db,did,'rename',label or old)
        cid=structured.ident(structured.norm(body.company_name))
        db.execute('INSERT INTO kb_companies VALUES (%s,%s,%s::jsonb) ON CONFLICT(id) DO NOTHING',(cid,body.company_name,json.dumps([body.company_name],ensure_ascii=False)))
        db.execute('INSERT INTO document_labels VALUES (%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET company_name=EXCLUDED.company_name,report_title=EXCLUDED.report_title',(did,body.company_name,body.report_title,old['name']))
        db.execute('UPDATE kb_reports SET company_id=%s WHERE document_id=%s',(cid,did))
    return {'saved':True}


@router.patch('/reports/{did}/state')
def report_state(did:str,body:State):
    with database.connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(%s)', (duplicates.LOCK,))
        report(db,did)
        if not body.deleted:
            rows=duplicates.inventory(db)
            row=next(r for r in rows if r['id']==did)
            duplicates.check_names(rows,row['company'],row['title'],exclude_id=did)
        audit(db,did,'trash' if body.deleted else 'restore',db.execute('SELECT * FROM document_state WHERE document_id=%s',(did,)).fetchone())
        db.execute('INSERT INTO document_state VALUES (%s,%s) ON CONFLICT(document_id) DO UPDATE SET deleted=EXCLUDED.deleted',(did,body.deleted))
    return {'deleted':body.deleted}


@router.get('/reports/{did}/contents')
def contents(did:str):
    with database.connect() as db:
        report(db,did)
        return list(db.execute('''SELECT b.id,COALESCE(e.module,b.module) AS module,COALESCE(e.section,b.section) AS section,
          COALESCE(e.text,b.text) AS text,b.kind,b.locator,COALESCE(e.deleted,FALSE) AS deleted
          FROM kb_blocks b JOIN kb_reports r ON r.id=b.report_id LEFT JOIN content_edits e ON e.block_id=b.id
          WHERE r.document_id=%s AND r.active ORDER BY b.ordinal''',(did,)))


@router.post('/reports/{did}/contents',status_code=201)
def add_content(did:str,body:Content):
    bid=uuid.uuid4().hex
    with database.connect() as db:
        report(db,did)
        r=db.execute('SELECT id FROM kb_reports WHERE document_id=%s AND active FOR UPDATE',(did,)).fetchone()
        if not r: raise HTTPException(409,'报告尚未解析')
        n=db.execute('SELECT COALESCE(max(ordinal),0)+1 AS n FROM kb_blocks WHERE report_id=%s',(r['id'],)).fetchone()['n']
        db.execute("INSERT INTO kb_blocks VALUES (%s,%s,%s,%s,%s,'paragraph',%s,%s::jsonb,'{}'::jsonb)",(bid,r['id'],n,body.module,body.section,body.text,json.dumps({'manual':True})))
        audit(db,bid,'add',None)
    return {'id':bid}


@router.put('/contents/{bid}')
def edit_content(bid:str,body:Content):
    with database.connect() as db:
        old=db.execute('SELECT * FROM kb_blocks WHERE id=%s',(bid,)).fetchone()
        if not old: raise HTTPException(404,'内容不存在')
        if old['kind']=='image': raise HTTPException(422,'图片原件不能以文字替换，可新增说明或移除该图片内容。')
        audit(db,bid,'edit',db.execute('SELECT * FROM content_edits WHERE block_id=%s',(bid,)).fetchone() or old)
        db.execute('INSERT INTO content_edits(block_id,text,module,section) VALUES (%s,%s,%s,%s) ON CONFLICT(block_id) DO UPDATE SET text=EXCLUDED.text,module=EXCLUDED.module,section=EXCLUDED.section',(bid,body.text,body.module,body.section))
    return {'saved':True}


@router.patch('/contents/{bid}/state')
def content_state(bid:str,body:State):
    with database.connect() as db:
        if not db.execute('SELECT 1 FROM kb_blocks WHERE id=%s',(bid,)).fetchone(): raise HTTPException(404,'内容不存在')
        audit(db,bid,'trash' if body.deleted else 'restore',db.execute('SELECT * FROM content_edits WHERE block_id=%s',(bid,)).fetchone())
        db.execute('INSERT INTO content_edits(block_id,deleted) VALUES (%s,%s) ON CONFLICT(block_id) DO UPDATE SET deleted=EXCLUDED.deleted',(bid,body.deleted))
    return {'deleted':body.deleted}
