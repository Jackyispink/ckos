import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from fastapi import HTTPException

from .sources import collect_chapter

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ckos-collection')
_jobs = {}
_lock = Lock()
_ttl = 24 * 60 * 60


def _set(job_id, **values):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(values, updated=time.time())


def start(project_id, chapter_no, max_web_queries, results_per_query):
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        for old in [key for key, value in _jobs.items() if now - value['updated'] > _ttl]:
            _jobs.pop(old, None)
        _jobs[job_id] = {'id': job_id, 'project_id': project_id, 'chapter_no': chapter_no,
            'status': 'queued', 'stage': '等待采集', 'percent': 0, 'done': 0, 'total': 0,
            'saved': 0, 'result': None, 'warning': None, 'error': None, 'updated': now}

    def progress(stage, percent, message, done, total, saved):
        _set(job_id, status='running', stage=stage, message=message, percent=percent,
             done=done, total=total, saved=saved)

    def run():
        try:
            _set(job_id, status='running', stage='starting', message='正在准备数据源', percent=1)
            result = asyncio.run(collect_chapter(project_id, chapter_no, max_web_queries,
                                                 results_per_query, progress=progress))
            web = result.get('web') or {}
            saved = result.get('structured_saved', 0) + web.get('saved', 0)
            warning = result.get('web_error') or web.get('error')
            partial = bool(warning or web.get('partial'))
            _set(job_id,
                 status='complete_with_warning' if partial else 'complete',
                 stage='complete_with_warning' if partial else 'complete',
                 message=(f'网页搜索中断，已保留本次新增 {saved} 条资料，可再次采集'
                          if partial else '资料采集完成'),
                 percent=100, result=result, saved=saved, warning=warning)
        except Exception as exc:
            _set(job_id, status='failed', stage='failed', message='资料采集失败', percent=100,
                 error=str(exc) or '资料采集失败，请检查后台日志。')
    _pool.submit(run)
    return {'job_id': job_id}


def get(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, '采集任务不存在或服务已重启，请重新开始采集')
        return dict(job)
