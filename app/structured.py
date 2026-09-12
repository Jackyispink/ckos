"""Versioned, source-preserving diagnostic ingestion and scoped retrieval."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from . import database

VERSION = 'diagnostic-v2'
MODULES = ('战略管理', '人力资源', '创新管理', '生产管理', '供应链管理', '营销管理', '财务管理', '决策管理', '公共形象')


def norm(text):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', text)).lower()


def ident(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def init():
    with database.connect() as db:
        db.execute('''
        CREATE TABLE IF NOT EXISTS kb_companies(id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases JSONB NOT NULL);
        CREATE TABLE IF NOT EXISTS kb_reports(id TEXT PRIMARY KEY, document_id TEXT NOT NULL, company_id TEXT REFERENCES kb_companies(id), fingerprint TEXT NOT NULL, pipeline_version TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, status TEXT NOT NULL, quality JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE TABLE IF NOT EXISTS kb_blocks(id TEXT PRIMARY KEY, report_id TEXT REFERENCES kb_reports(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, module TEXT NOT NULL, section TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, locator JSONB NOT NULL, metadata JSONB NOT NULL);
        CREATE TABLE IF NOT EXISTS kb_relations(id TEXT PRIMARY KEY, report_id TEXT REFERENCES kb_reports(id) ON DELETE CASCADE, module TEXT NOT NULL, issue_id TEXT REFERENCES kb_blocks(id), recommendation_id TEXT REFERENCES kb_blocks(id), basis TEXT NOT NULL, review_status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS kb_jobs(id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, filename TEXT, fingerprint TEXT, status TEXT, error TEXT, created TIMESTAMPTZ DEFAULT now());
        CREATE INDEX IF NOT EXISTS kb_report_company ON kb_reports(company_id,active);
        CREATE INDEX IF NOT EXISTS kb_block_report_module ON kb_blocks(report_id,module,ordinal);
        CREATE INDEX IF NOT EXISTS kb_relation_issue ON kb_relations(issue_id);
        CREATE OR REPLACE VIEW kb_effective_blocks AS
          SELECT b.id,b.report_id,b.ordinal,COALESCE(e.module,b.module) AS module,
            COALESCE(e.section,b.section) AS section,
            CASE WHEN e.text IS NOT NULL THEN 'paragraph' ELSE b.kind END AS kind,
            COALESCE(e.text,b.text) AS text,b.locator || jsonb_build_object('edited',e.text IS NOT NULL) AS locator,b.metadata
          FROM kb_blocks b LEFT JOIN content_edits e ON e.block_id=b.id WHERE NOT COALESCE(e.deleted,FALSE);
        ''')


def parse(path, company_override=None):
    doc = Document(path)
    filename_company = re.sub(r'^\d+\s*', '', path.stem)
    filename_company = re.sub(r'(管理)?诊断报告.*$', '', filename_company).strip()
    company = filename_company
    for p in doc.paragraphs[:35]:
        text = p.text.strip()
        if len(text) < 100 and ('有限公司' in text or '股份公司' in text):
            company = re.sub(r'(管理)?诊断报告.*$', '', text).strip()
            break
    aliases = sorted(set(filter(None, (company, filename_company))))
    if company_override:
        company = company_override
        aliases = [company_override]
    if not company or len(norm(company)) < 2:
        company = '待核实企业：' + path.stem
        aliases = []
    blocks = []
    module, section = '报告概况', '说明'
    pno = tno = 0
    headings = []
    def add(kind, text, locator, metadata=None):
        blocks.append(dict(ordinal=len(blocks), module=module, section=section, kind=kind, text=text,
                           locator=locator, metadata=metadata or {}))
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            pno += 1
            text = item.text.strip()
            clean = re.sub(r'^[\d一二三四五六七八九十、.．（）()\s]+', '', text)
            found = next((m for m in MODULES if m in text), None)
            is_module = found and len(text) < 45 and ('诊断' in text or '建议' in text or 'Heading' in item.style.name)
            if is_module:
                module, section = found, '综合评价'
                headings.append(found)
            elif 'Heading 1' == item.style.name and len(text) < 50:
                module, section = text, '说明'
            if clean in ('存在现状', '现状分析', '存在问题', '主要问题', '问题分析', '问题分析：'):
                section = '问题'
            elif clean in ('改善建议', '改进建议', '改善建议：', '建议措施', '实施步骤', '实施步骤：'):
                section = '建议'
            elif clean in ('综合评价', '预期效果', '预期效果：'):
                section = clean.rstrip('：')
            if text:
                add('heading' if is_module or 'Heading' in item.style.name or clean.rstrip('：') in ('存在现状', '改善建议', '综合评价', '预期效果', '实施步骤', '问题分析') else 'paragraph', text, {'paragraph': pno})
            for rid in item._p.xpath('.//a:blip/@r:embed'):
                part = doc.part.related_parts[rid]
                digest = hashlib.sha256(part.blob).hexdigest()
                suffix = Path(str(part.partname)).suffix
                target = database.ROOT / 'storage' / 'assets' / (digest + suffix)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(part.blob)
                add('image', '', {'paragraph': pno, 'relationship': rid}, {'asset': str(target.relative_to(database.ROOT)), 'sha256': digest, 'extraction_status': 'pending_ocr', 'context': text})
            for rid in item._p.xpath('.//*[local-name()="chart"]/@r:id'):
                part = doc.part.related_parts[rid]
                xml = etree.fromstring(part.blob)
                ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
                series = []
                for ser in xml.xpath('//c:ser', namespaces=ns):
                    series.append({'name': ser.xpath('./c:tx//c:v/text()', namespaces=ns),
                                   'categories': ser.xpath('./c:cat//c:pt/c:v/text()', namespaces=ns),
                                   'values': ser.xpath('./c:val//c:pt/c:v/text()', namespaces=ns)})
                add('chart', json.dumps(series, ensure_ascii=False), {'paragraph': pno, 'relationship': rid}, {'series': series, 'extraction_status': 'native_chart'})
        elif isinstance(item, Table):
            tno += 1
            header = [c.text for c in item.rows[0].cells] if item.rows else []
            for rowno, row in enumerate(item.rows, 1):
                cells = []
                for colno, cell in enumerate(row.cells, 1):
                    cells.append({'column': colno, 'text': cell.text, 'xml_cell_path': cell._tc.getroottree().getpath(cell._tc)})
                add('table_row', ' | '.join(c['text'] for c in cells), {'table': tno, 'row': rowno}, {'headers': header, 'cells': cells})
    conflicts = []
    summary_scores = {}
    for b in blocks:
        if b['kind'] == 'table_row':
            cells = [c['text'].strip() for c in b['metadata']['cells']]
            if len(cells) >= 3 and cells[0] in MODULES and re.fullmatch(r'\d+(\.\d+)?', cells[1]):
                summary_scores[cells[0]] = (float(cells[1]), b['locator'])
    for b in blocks:
        if b['kind'] == 'paragraph' and b['module'] in summary_scores:
            match = re.search(r'(?:满分|总分(?:数|值)?)(?:设定)?(?:为|是)(\d+(?:\.\d+)?)分', b['text'].replace(' ', ''))
            if match and float(match[1]) != summary_scores[b['module']][0]:
                conflicts.append({'module': b['module'], 'field': 'maximum_score', 'table_value': summary_scores[b['module']][0], 'text_value': float(match[1]), 'table_locator': summary_scores[b['module']][1], 'text_locator': b['locator'], 'status': 'pending_review'})
    quality = {'missing_modules': [m for m in MODULES if m not in headings], 'score_conflicts': conflicts,
               'pending_images': sum(b['kind'] == 'image' for b in blocks), 'company_needs_review': not aliases,
               'native_charts': sum(b['kind'] == 'chart' for b in blocks)}
    return company, aliases, blocks, quality


def ingest(root, paths=None, *, initialize=True):
    if initialize:
        init()
    result = {'processed': 0, 'unchanged': 0, 'errors': []}
    for path in sorted(paths if paths is not None else (root / 'data').glob('*.docx')):
        if path.name.startswith('~$'):
            continue
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        did = hashlib.sha256(path.name.encode()).hexdigest()[:20]
        with database.connect() as db:
            label = db.execute('SELECT company_name FROM document_labels WHERE document_id=%s', (did,)).fetchone()
        company_override = label['company_name'] if label else None
        rid = ident(did + fingerprint + VERSION + (company_override or ''))
        with database.connect() as db:
            exists = db.execute('SELECT id FROM kb_reports WHERE document_id=%s AND fingerprint=%s AND pipeline_version=%s AND active', (did,fingerprint,VERSION)).fetchone()
        if exists:
            result['unchanged'] += 1
            continue
        try:
            company, aliases, blocks, quality = parse(path, company_override)
            cid = ident(norm(company))
            with database.connect() as db:
                db.execute('INSERT INTO kb_companies VALUES (%s,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET aliases=EXCLUDED.aliases', (cid, company, json.dumps(aliases, ensure_ascii=False)))
                db.execute('UPDATE kb_reports SET active=FALSE WHERE document_id=%s', (did,))
                db.execute('INSERT INTO kb_reports(id,document_id,company_id,fingerprint,pipeline_version,status,quality) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET active=TRUE', (rid, did, cid, fingerprint, VERSION, 'needs_review' if quality['pending_images'] or quality['missing_modules'] or quality['company_needs_review'] else 'ready', json.dumps(quality)))
                for b in blocks:
                    b['id'] = ident(rid + str(b['ordinal']))
                with db.cursor() as cursor:
                    cursor.executemany('INSERT INTO kb_blocks VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING',
                        [(b['id'],rid,b['ordinal'],b['module'],b['section'],b['kind'],b['text'],json.dumps(b['locator']),json.dumps(b['metadata'],ensure_ascii=False)) for b in blocks])
                    # Candidate relationships retain the same meaning; only write batching changes.
                    relations=[]
                    for m in MODULES:
                        issues=[b for b in blocks if b['module']==m and b['section']=='问题' and b['kind']=='paragraph']
                        recommendations=[b for b in blocks if b['module']==m and b['section']=='建议' and b['kind']=='paragraph']
                        relations.extend((ident(issue['id']+rec['id']),rid,m,issue['id'],rec['id'],'same_module_candidate','pending') for issue in issues for rec in recommendations)
                    cursor.executemany('INSERT INTO kb_relations VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',relations)
                db.execute('INSERT INTO kb_jobs(filename,fingerprint,status) VALUES (%s,%s,%s)', (path.name, fingerprint, 'completed'))
            result['processed'] += 1
        except Exception as exc:
            result['errors'].append({'file': path.name, 'error': type(exc).__name__})
            with database.connect() as db:
                db.execute('INSERT INTO kb_jobs(filename,fingerprint,status,error) VALUES (%s,%s,%s,%s)', (path.name, fingerprint, 'failed', type(exc).__name__))
    return result


def resolve(query, document_id=None, previous_sources=None):
    """Scope first. Never use keyword retrieval as company identification."""
    with database.connect() as db:
        reports = list(db.execute('SELECT r.*, c.name,c.aliases,COALESCE(l.report_title,d.name) AS filename FROM kb_reports r JOIN kb_companies c ON c.id=r.company_id JOIN documents d ON d.id=r.document_id LEFT JOIN document_labels l ON l.document_id=d.id WHERE r.active AND NOT EXISTS (SELECT 1 FROM document_state ds WHERE ds.document_id=d.id AND ds.deleted)'))
    matches = [r for r in reports if any(len(norm(a)) >= 2 and norm(a) in norm(query) for a in r['aliases'])]
    if document_id:
        selected = [r for r in reports if r['document_id'] == document_id]
        if matches and any(r['document_id'] != document_id for r in matches):
            return [], '问题中的企业与所选报告不一致，请先切换报告筛选。'
    elif matches:
        selected = matches
    elif any(w in query for w in ('它', '这家', '该企业', '该公司', '继续', '那么', '那应该')) and previous_sources:
        ids = {s.get('document_id') for s in previous_sources}
        selected = [r for r in reports if r['document_id'] in ids]
    elif any(w in query for w in ('哪些企业', '所有企业', '各企业', '85家', '跨企业')):
        return [], '跨企业结构化统计尚未发布，请指定企业或选择报告，避免将部分检索结果当作全部企业结论。'
    else:
        return [], '请指定企业名称或在右上角选择报告；暂不凭关键词猜测企业。'
    if len(selected) != 1:
        return [], '匹配到多个企业或报告版本，请选择一份具体报告后提问。' if selected else '未找到对应的已处理报告，请检查企业名称或选择报告。'
    report = selected[0]
    modules = [m for m in MODULES if m in query or (m == '人力资源' and any(w in query for w in ('人才', '绩效', '薪酬'))) or (m == '生产管理' and any(w in query for w in ('设备', '精益', '产能')))]
    with database.connect() as db:
        blocks = list(db.execute('SELECT * FROM kb_effective_blocks WHERE report_id=%s ORDER BY ordinal', (report['id'],)))
    if modules:
        blocks = [b for b in blocks if b['module'] in modules]
    diagnostic = any(w in query for w in ('建议', '问题', '改进', '诊断', '改善', '怎么'))
    if diagnostic:
        blocks = [b for b in blocks if b['module'] in MODULES and b['section'] in ('问题', '建议', '综合评价') and b['kind'] == 'paragraph']
    else:
        blocks = [b for b in blocks if b['text'] and b['kind'] != 'heading']
    # Keep source boundaries and ensure each module has a place in a broad answer.
    groups = {}
    for b in blocks:
        groups.setdefault(b['module'], []).append(b)
    sources = []
    for m, group in groups.items():
        selected_blocks, size = [], 0
        # Alternate issue and recommendation blocks so long introductory text cannot consume the budget.
        prioritized = []
        queues = [[b for b in group if b['section'] == sec] for sec in ('问题', '建议', '综合评价')]
        if diagnostic:
            while any(queues):
                for queue in queues:
                    if queue:
                        prioritized.append(queue.pop(0))
        else:
            prioritized = group
        for b in prioritized:
            if size + len(b['text']) > 3500:
                continue
            selected_blocks.append(b)
            size += len(b['text'])
        if not selected_blocks:
            continue
        selected_blocks.sort(key=lambda b: b['ordinal'])
        sources.append({'id': report['id'] + ':' + m, 'document_id': report['document_id'], 'company_id': report['company_id'], 'report_id': report['id'], 'module': m, 'name': report['filename'], 'location': m, 'text': '\n'.join(('【人工维护内容】' if b['locator'].get('edited') or b['locator'].get('manual') else '') + '【' + b['section'] + '】' + b['text'] for b in selected_blocks), 'evidence': [{'block_id': b['id'], 'locator': b['locator']} for b in selected_blocks]})
    return sources, '按企业、报告和模块限定的资料；标注人工维护的内容来自用户修改或补充，不是原报告逐字引用；问题与建议按模块共同提供，不代表已核实的一一对应关系。图片仍有待识别项；每模块最多3500字，不能声称覆盖全部原文。'


if __name__ == '__main__':
    result = ingest(database.ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['errors'] else 0)
