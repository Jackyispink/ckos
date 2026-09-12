"""Small in-process job registry for observable staged commits."""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from fastapi import HTTPException, UploadFile

from . import upload_preview, uploads

_pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='ckos-upload')
_jobs={};_lock=Lock();_TTL=24*60*60


def _set(jid,**values):
    with _lock:
        if jid in _jobs:_jobs[jid].update(values,updated=time.time())


def start(body):
    path,info=upload_preview.resolve(body.token)
    jid=uuid.uuid4().hex
    with _lock:
        now=time.time()
        for old in [k for k,v in _jobs.items() if now-v['updated']>_TTL]:_jobs.pop(old,None)
        _jobs[jid]={'id':jid,'status':'queued','percent':0,'stage':'等待后台处理','result':None,'error':None,'updated':now}
    def run():
        try:
            _set(jid,status='running',percent=2,stage='开始处理')
            with path.open('rb') as stream:
                file=UploadFile(file=stream,filename=info['original_filename'])
                result=uploads.save_report(file,body.company_name,body.report_title,body.similarity_threshold,
                    body.replace_document_id,body.confirm_update,body.check_mode,
                    progress=lambda percent,stage:_set(jid,percent=percent,stage=stage))
            upload_preview.discard(body.token)
            _set(jid,status='complete',percent=100,stage='已完成',result=result)
        except HTTPException as exc:
            _set(jid,status='failed',percent=100,stage='未入库',error=exc.detail)
        except Exception:
            _set(jid,status='failed',percent=100,stage='未入库',error={'message':'后台处理失败，请保留暂存文件后重试。'})
    _pool.submit(run)
    return {'job_id':jid}


def get(jid):
    with _lock:job=_jobs.get(jid)
    if not job:raise HTTPException(404,'上传任务不存在或服务已重启，请重新提交暂存文件')
    return dict(job)
