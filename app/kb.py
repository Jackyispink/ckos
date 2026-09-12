import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import jieba
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from .database import connect, init

ROOT = Path(__file__).resolve().parents[1]


def tokens(text):
    return [t.lower() for t in jieba.lcut(text) if re.search(r'[\w\u4e00-\u9fff]', t) and len(t.strip()) > 1]


def extract(path):
    doc = Document(path)
    paragraph = table = 0
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            paragraph += 1
            if block.text.strip():
                yield f'正文第 {paragraph} 段', block.text.strip()
        elif isinstance(block, Table):
            table += 1
            for row_number, row in enumerate(block.rows, 1):
                cells = list(dict.fromkeys(cell.text.strip() for cell in row.cells))
                if any(cells):
                    yield f'表 {table} 第 {row_number} 行', ' | '.join(cells)


def ingest(paths=None, *, initialize=True):
    if initialize:
        init()
    result = {'indexed': 0, 'unchanged': 0, 'errors': []}
    for path in sorted(paths if paths is not None else (ROOT / 'data').glob('*.docx')):
        if path.name.startswith('~$'):
            continue
        doc_id = hashlib.sha256(path.name.encode()).hexdigest()[:20]
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        with connect() as db:
            old = db.execute('SELECT fingerprint FROM documents WHERE id=%s', (doc_id,)).fetchone()
            if old and old['fingerprint'] == fingerprint:
                result['unchanged'] += 1
                continue
        try:
            chunks = []
            pending, locs = [], []
            def flush():
                if pending:
                    chunks.append(('；'.join(locs), '\n'.join(pending)))
                    pending.clear()
                    locs.clear()
            for loc, text in extract(path):
                for start in range(0, len(text), 850):
                    part = text[start:start + 1000]
                    if sum(map(len, pending)) + len(part) > 1200:
                        flush()
                    pending.append(part)
                    locs.append(loc)
                    if start + 1000 >= len(text):
                        break
            flush()
            if not chunks:
                raise ValueError('未提取到正文或表格文字')
            with connect() as db:
                db.execute('DELETE FROM documents WHERE id=%s', (doc_id,))
                db.execute('INSERT INTO documents VALUES (%s,%s,%s,%s)', (doc_id, path.name, fingerprint, len(chunks)))
                with db.cursor() as cursor:
                    cursor.executemany('INSERT INTO chunks VALUES (%s,%s,%s,%s,%s)',
                        [(f'{doc_id}-{i}', doc_id, loc, text, json.dumps(tokens(path.stem + ' ' + text), ensure_ascii=False)) for i,(loc,text) in enumerate(chunks)])
            result['indexed'] += 1
        except Exception as exc:
            result['errors'].append({'file': path.name, 'error': str(exc)})
    return result


class Retriever:
    def __init__(self):
        with connect() as db:
            self.rows = [dict(r) for r in db.execute('SELECT c.*, d.name FROM chunks c JOIN documents d ON d.id=c.document_id')]
        self.counts = [Counter(json.loads(r.pop('tokens'))) for r in self.rows]
        self.df = Counter(t for c in self.counts for t in c)
        self.avg = sum(sum(c.values()) for c in self.counts) / max(1, len(self.counts))

    def context(self, query, document_id=None):
        """Resolve named companies before ranking; broad report questions need coverage."""
        normalize = lambda value: re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', value)).lower()
        normalized_query = normalize(query)
        names = {r['document_id']: r['name'] for r in self.rows}
        matched = []
        for did, name in names.items():
            company = re.sub(r'^\d+\s*', '', Path(name).stem)
            company = re.sub(r'(管理)?诊断报告.*$', '', company).strip()
            if len(normalize(company)) >= 4 and normalize(company) in normalized_query:
                matched.append(did)
        target = document_id or (matched[0] if len(matched) == 1 else None)
        broad = any(word in query for word in ('诊断建议', '改善建议', '改进建议', '总结', '概括', '综述', '整体', '全部', '全面'))
        if target and broad:
            rows = sorted((r for r in self.rows if r['document_id'] == target), key=lambda r: int(r['id'].rsplit('-', 1)[1]))
            # For these company reports, a complete document often fits in one request.
            if sum(len(r['text']) for r in rows) <= 40000:
                return [dict(r) for r in rows], '已提供该企业全部已入库正文和表格；图片内容未识别。'
        return self.search(query, target), '已提供相关检索片段，不代表报告全文或全量企业统计。'

    def search(self, query, document_id=None, limit=10):
        query_tokens = set(tokens(query))
        scored = []
        for row, counts in zip(self.rows, self.counts):
            if document_id and row['document_id'] != document_id:
                continue
            length = sum(counts.values())
            score = sum(math.log(1 + (len(self.rows) - self.df[t] + .5) / (self.df[t] + .5)) * counts[t] * 2.5 / (counts[t] + 1.5 * (.25 + .75 * length / max(1, self.avg))) for t in query_tokens if counts[t])
            if score > 0:
                scored.append(dict(row, score=round(score, 4)))
        scored.sort(key=lambda r: r['score'], reverse=True)
        return scored[:limit]


if __name__ == '__main__':
    print(json.dumps(ingest(), ensure_ascii=False, indent=2))
