"""Bounded, resumable image-table recognition. Results require review before retrieval."""
import argparse
import asyncio
import base64
import json
import mimetypes
import os
import time

from app import database, llm, structured


async def run(limit, model):
    os.environ['LLM_MODEL'] = model
    os.environ['LLM_MAX_TOKENS'] = '5000'
    structured.init()
    with database.connect() as db:
        blocks = list(db.execute('''SELECT b.* FROM kb_blocks b JOIN kb_reports r ON r.id=b.report_id
            WHERE r.active AND b.kind='image' AND b.metadata->>'extraction_status'='pending_ocr'
            AND b.module=ANY(%s) ORDER BY b.report_id,b.ordinal LIMIT %s''', (list(structured.MODULES), limit)))
    result = {'recognized': 0, 'failed': 0}
    for block in blocks:
        started = time.monotonic()
        path = database.ROOT / block['metadata']['asset']
        mime = mimetypes.guess_type(path.name)[0] or 'image/png'
        content = [{'type': 'text', 'text': '识别此图。若为表格，逐行逐列转录，不推断缺失数字。仅返回JSON对象：{"kind":"table或photo或chart或other","rows":[["单元格"]],"uncertain_cells":[],"description":"简述"}。保持多级指标、管理现状、分值、得分。模糊单元格填null。'}, {'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode()}}]
        try:
            raw = await llm.complete([{'role': 'user', 'content': content}])
            cleaned = raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict) or not isinstance(parsed.get('rows'), list):
                raise ValueError('invalid schema')
            metadata = dict(block['metadata'], extraction_status='recognized_pending_review', recognition=parsed, recognition_model=model)
            with database.connect() as db:
                db.execute('UPDATE kb_blocks SET metadata=%s::jsonb WHERE id=%s', (json.dumps(metadata, ensure_ascii=False), block['id']))
            result['recognized'] += 1
        except Exception as exc:
            result['failed'] += 1
            print(json.dumps({'block_id': block['id'], 'error_type': type(exc).__name__, 'detail': str(exc) if isinstance(exc, llm.ModelError) else '图片识别结果未通过格式校验'}, ensure_ascii=False), flush=True)
        # Respect the documented 30 requests/minute limit for this single worker.
        await asyncio.sleep(max(0, 2.1 - (time.monotonic() - started)))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--model', default='internvl-latest')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    asyncio.run(run(args.limit, args.model))
