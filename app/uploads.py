import hashlib
import json
import uuid
from pathlib import Path
from threading import BoundedSemaphore
from fastapi import HTTPException, UploadFile

from . import database, kb, structured, duplicates, duplicate_index

MAX_BYTES = 50 * 1024 * 1024
UPLOAD_PARALLELISM = 3
_upload_slots = BoundedSemaphore(UPLOAD_PARALLELISM)


def save_report(file: UploadFile, company_name: str, report_title: str, similarity_threshold: float = 90, replace_document_id: str | None = None, confirm_update: bool = False, check_mode: str = 'fast', progress=lambda percent,stage:None):
    progress(3,'等待处理名额')
    with _upload_slots:
        progress(7,'检查名称')
        return _process_report(file, company_name, report_title, similarity_threshold, replace_document_id, confirm_update, check_mode, progress)


def _process_report(file, company_name, report_title, similarity_threshold, replace_document_id, confirm_update, check_mode, progress):
    if check_mode not in ('fast','strict'):
        raise HTTPException(422, '请选择快速检查或严格检查')
    company_name, report_title = company_name.strip(), report_title.strip()
    for value in (company_name, report_title):
        if not 2 <= len(value) <= 120 or any(ord(c) < 32 for c in value):
            raise HTTPException(422, '企业名称和报告名称请填写 2～120 个字符')
    if not 50 <= similarity_threshold <= 99.9:
        raise HTTPException(422, '相似度阈值须在 50%～99.9% 之间')
    if not (file.filename or '').lower().endswith('.docx'):
        raise HTTPException(422, '目前仅支持 .docx 文件')
    # Name screening and expensive file reads can run concurrently. Recheck after acquiring the publication lock.
    with database.connect() as db:
        snapshot = duplicates.inventory(db)
        duplicates.check_names(snapshot, company_name, report_title, replace_document_id)
    progress(14,'读取暂存文件')
    digest, size = hashlib.sha256(), 0
    while chunk := file.file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, '文件超过 50 MB，请压缩后再上传。')
        digest.update(chunk)
    file.file.seek(0)
    fingerprint = digest.hexdigest()
    def reject_exact(rows):
        exact_file = next((r for r in rows if r['fingerprint'] == fingerprint), None)
        if exact_file:
            raise HTTPException(409, {'code': 'exact_duplicate', 'message': '文件完全重复，不能再次入库。回收站内的报告可直接恢复。', 'matches': [duplicates.public(exact_file)]})
    reject_exact(snapshot)
    incoming = duplicates.extract(file.file)
    file.file.seek(0)
    progress(24,'等待最终查重锁')
    with database.connect() as db:
        db.execute('SELECT pg_advisory_xact_lock(%s)', (duplicates.LOCK,))
        progress(30,'重新核对名称与文件指纹')
        rows = duplicates.inventory(db)
        target = duplicates.check_names(rows, company_name, report_title, replace_document_id)
        reject_exact(rows)
        progress(38,'查找疑似重复报告')
        matches, stats, index_model = duplicate_index.check(db, rows, incoming, similarity_threshold, company_name, replace_document_id, check_mode)
        progress(51,f"精确比较 {stats['candidates']} / {stats['documents']} 份原文")
        exact = [r for r in matches if r['exact']]
        if exact:
            raise HTTPException(409, {'code': 'exact_duplicate', 'message': '规范化后的正文、表格及图片/图表内容重复，不能再次入库。', 'matches': exact[:5], 'check': stats})
        # A selected version target does not authorize a duplicate of a different report.
        lineage = {replace_document_id} if replace_document_id else set()
        links = list(db.execute('SELECT * FROM document_versions'))
        for _ in range(len(links)):
            lineage.update(v['previous_document_id'] for v in links if v['new_document_id'] in lineage)
        blocking = [r for r in matches if r['similarity'] >= similarity_threshold and r['id'] not in lineage]
        if blocking:
            raise HTTPException(409, {'code': 'similar_content', 'message': '原文高度相似，尚未入库。请核对差异，必要时选择同一企业的报告作为更新目标。', 'matches': blocking[:5], 'check': stats})
        if target and not confirm_update:
            raise HTTPException(409, {'code': 'version_review', 'message': '请核对新旧报告差异。确认更新后，旧版移入回收站，旧版人工修改不会自动复制到新版。', 'matches': [r for r in matches if r['id'] == replace_document_id], 'check': stats})
        result = _save_report(file, company_name, report_title, progress)
        did = result['document_id']
        duplicates.cache_profile(db, did, fingerprint, incoming)
        duplicate_index.add(db, {'id':did,'fingerprint':fingerprint}, incoming, *index_model)
        progress(94,'保存查重索引与版本信息')
        if target:
            db.execute('INSERT INTO document_versions(new_document_id,previous_document_id) VALUES (%s,%s)', (did, target['id']))
            db.execute('INSERT INTO document_state VALUES (%s,TRUE) ON CONFLICT(document_id) DO UPDATE SET deleted=TRUE', (target['id'],))
            db.execute("INSERT INTO content_audit(target_id,action,before_value) VALUES (%s,'new_version',%s::jsonb)", (did, json.dumps({'previous_document_id': target['id'], 'similarity_threshold': similarity_threshold})))
        db.execute('UPDATE document_state SET deleted=FALSE WHERE document_id=%s', (did,))
        result['previous_document_id'] = replace_document_id
        result['check'] = stats
        return result


def _save_report(file: UploadFile, company_name: str, report_title: str, progress=lambda percent,stage:None):
    company_name, report_title = company_name.strip(), report_title.strip()
    for label, value in [('企业名称', company_name), ('报告名称', report_title)]:
        if not 2 <= len(value) <= 120 or any(ord(c) < 32 for c in value):
            raise HTTPException(422, label + '请填写 2～120 个字符')
    if not (file.filename or '').lower().endswith('.docx'):
        raise HTTPException(422, '目前支持 Word .docx 文件，请先将其他格式另存为 .docx。')
    folder = kb.ROOT / 'data'
    folder.mkdir(parents=True, exist_ok=True)
    # A generated filename prevents overwrites and path traversal; display names live in PostgreSQL.
    path = folder / ('upload_' + uuid.uuid4().hex + '.docx')
    did = hashlib.sha256(path.name.encode()).hexdigest()[:20]
    try:
        size = 0
        with path.open('xb') as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, '文件超过 50 MB，请压缩图片后再上传。')
                output.write(chunk)
        progress(60,'生成知识切片')
        with database.connect() as db:
            db.execute('INSERT INTO document_state VALUES (%s,TRUE)', (did,))
            db.execute('INSERT INTO document_labels VALUES (%s,%s,%s,%s)', (did, company_name, report_title, Path(file.filename).name))
        result = kb.ingest([path], initialize=False)
        if result['errors']:
            raise RuntimeError('text ingestion failed')
        progress(73,'提取企业、模块、问题、建议和证据')
        result = structured.ingest(kb.ROOT, [path], initialize=False)
        if result['errors']:
            raise RuntimeError('structured ingestion failed')
        progress(89,'核对结构化入库结果')
        with database.connect() as db:
            report = db.execute('SELECT quality FROM kb_reports WHERE document_id=%s AND active', (did,)).fetchone()
        return {'document_id': did, 'company_name': company_name, 'report_title': report_title, 'quality': report['quality']}
    except Exception as exc:
        # Roll back only this newly generated upload; existing reports are never replaced.
        with database.connect() as db:
            db.execute('DELETE FROM kb_reports WHERE document_id=%s', (did,))
            db.execute('DELETE FROM documents WHERE id=%s', (did,))
            db.execute('DELETE FROM document_labels WHERE document_id=%s', (did,))
            db.execute('DELETE FROM document_state WHERE document_id=%s', (did,))
        path.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, '文档入库失败，本次上传已撤回，请重试。') from None
