from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from . import ppt, database, writer

router=APIRouter(prefix='/api/industry/projects/{project_id}/ppt',tags=['report presentations'])


def _call(fn,*args):
    try: return fn(*args)
    except FileNotFoundError as e: raise HTTPException(404,str(e)) from None
    except ValueError as e: raise HTTPException(409,str(e)) from None


def _exists(project_id):
    if not database.project(project_id): raise HTTPException(404,'报告不存在')


@router.get('')
def listing(project_id:str):
    _exists(project_id)
    return ppt.listing(project_id)


@router.post('',status_code=202)
def create(project_id:str,body:ppt.Create):
    _exists(project_id)
    # Serialize the availability check and snapshot creation. Repeated requests
    # must not create extra report versions before being rejected as busy.
    with ppt.LOCK:
        _call(ppt.ensure_available, project_id)
        return _create_available(project_id, body)


def _create_available(project_id, body):
    if body.version_id:
        version=database.get_version(project_id,body.version_id)
        if not version: raise HTTPException(404,'报告版本不存在')
        snapshot=version['snapshot']
    else:
        if writer.is_running(project_id): raise HTTPException(409,'报告正在生成，请等待完成或选择历史版本')
        # Copy the report and evidence into an immutable PPT job snapshot.
        with database.connect() as db:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            vid=database.snapshot_version(db,project_id,'生成 PPT 时保存报告快照')
            row=db.execute('SELECT snapshot FROM industry_versions WHERE id=%s',(vid,)).fetchone()
            if not row: raise HTTPException(409,'报告尚无内容')
            snapshot=row['snapshot']
    return ppt.public(_call(ppt.create,project_id,snapshot,body.ai,body.mode))


@router.get('/{jid}')
def get(project_id:str,jid:str):
    _exists(project_id)
    return ppt.public(_call(ppt.read,project_id,jid))


@router.put('/{jid}')
def save(project_id:str,jid:str,body:ppt.Outline):
    _exists(project_id)
    return ppt.public(_call(ppt.save,project_id,jid,body))


@router.post('/{jid}/export',status_code=202)
def export(project_id:str,jid:str):
    _exists(project_id)
    return ppt.public(_call(ppt.export,project_id,jid))


@router.get('/{jid}/download')
def download(project_id:str,jid:str):
    _exists(project_id)
    file=_call(ppt.asset,project_id,jid,'report.pptx')
    return FileResponse(file,filename='行业研究演示.pptx',media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',headers={'Cache-Control':'no-store'})


@router.get('/{jid}/slides/{number}')
def preview(project_id:str,jid:str,number:int):
    _exists(project_id)
    return FileResponse(_call(ppt.asset,project_id,jid,f'slide-{number}.png'),media_type='image/png',headers={'Cache-Control':'no-store'})
