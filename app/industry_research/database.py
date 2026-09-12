import json
import hashlib
import uuid
from dataclasses import asdict

from ..database import connect
from .content_quality import sanitize_generated_content


def init():
    with connect() as db:
        db.execute('''
        CREATE TABLE IF NOT EXISTS industry_projects(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, brief JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
          current_stage TEXT NOT NULL DEFAULT '研究计划已生成', error TEXT, created TIMESTAMPTZ NOT NULL DEFAULT now(), updated TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE TABLE IF NOT EXISTS industry_versions(
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES industry_projects(id) ON DELETE CASCADE,
          reason TEXT NOT NULL, snapshot JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE TABLE IF NOT EXISTS industry_chapters(
          project_id TEXT NOT NULL REFERENCES industry_projects(id) ON DELETE CASCADE, chapter_no INTEGER NOT NULL,
          title TEXT NOT NULL, questions JSONB NOT NULL, queries JSONB NOT NULL, content TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'planned', updated TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(project_id,chapter_no));
        CREATE TABLE IF NOT EXISTS industry_evidence(
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES industry_projects(id) ON DELETE CASCADE,
          chapter_no INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', publisher TEXT NOT NULL DEFAULT '',
          published_at TEXT NOT NULL DEFAULT '', excerpt TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT '',
          created TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE INDEX IF NOT EXISTS industry_evidence_project_chapter_idx ON industry_evidence(project_id,chapter_no);
        CREATE TABLE IF NOT EXISTS industry_source_cache(
          cache_key TEXT PRIMARY KEY, provider TEXT NOT NULL, dataset TEXT NOT NULL, params JSONB NOT NULL,
          payload JSONB NOT NULL, expires TIMESTAMPTZ NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE TABLE IF NOT EXISTS industry_chart_selections(
          project_id TEXT NOT NULL REFERENCES industry_projects(id) ON DELETE CASCADE,
          chart_id TEXT NOT NULL, chart_type TEXT NOT NULL, title TEXT NOT NULL,
          selected BOOLEAN NOT NULL DEFAULT TRUE, updated TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(project_id,chart_id));
        CREATE TABLE IF NOT EXISTS industry_decision_records(
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES industry_projects(id) ON DELETE CASCADE,
          record_type TEXT NOT NULL, name TEXT NOT NULL, fields JSONB NOT NULL DEFAULT '{}'::jsonb,
          basis TEXT NOT NULL DEFAULT 'unverified', source TEXT NOT NULL DEFAULT '',
          as_of_date TEXT NOT NULL DEFAULT '', verified BOOLEAN NOT NULL DEFAULT FALSE,
          created TIMESTAMPTZ NOT NULL DEFAULT now(), updated TIMESTAMPTZ NOT NULL DEFAULT now());
        CREATE INDEX IF NOT EXISTS industry_decision_records_project_type_idx
          ON industry_decision_records(project_id,record_type);
        ''')
        db.execute("ALTER TABLE industry_evidence ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE industry_evidence ADD COLUMN IF NOT EXISTS search_query TEXT NOT NULL DEFAULT ''")
        db.execute('ALTER TABLE industry_evidence ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION')
        db.execute("ALTER TABLE industry_evidence ADD COLUMN IF NOT EXISTS provider_result_id TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE industry_evidence ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
        db.execute("ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS progress_percent INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS completed_chapters INTEGER NOT NULL DEFAULT 0")
        db.execute('ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ')
        db.execute('ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS stage_started_at TIMESTAMPTZ')
        db.execute('ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS manufacturing_scenario JSONB')
        db.execute('ALTER TABLE industry_projects ADD COLUMN IF NOT EXISTS review_required_chapter INTEGER')
        db.execute('ALTER TABLE industry_chapters ADD COLUMN IF NOT EXISTS evidence_revision INTEGER NOT NULL DEFAULT 0')
        db.execute('ALTER TABLE industry_chapters ADD COLUMN IF NOT EXISTS content_evidence_revision INTEGER NOT NULL DEFAULT 0')
        db.execute('''CREATE OR REPLACE FUNCTION industry_touch_evidence_revision() RETURNS trigger AS $$
          BEGIN
            IF (OLD.metadata->'review') IS DISTINCT FROM (NEW.metadata->'review') THEN
              UPDATE industry_chapters SET evidence_revision=evidence_revision+1,updated=now()
              WHERE project_id=NEW.project_id AND chapter_no=NEW.chapter_no;
            END IF;
            RETURN NEW;
          END; $$ LANGUAGE plpgsql''')
        db.execute('''DROP TRIGGER IF EXISTS industry_evidence_review_revision ON industry_evidence;
          CREATE TRIGGER industry_evidence_review_revision AFTER UPDATE OF metadata ON industry_evidence
          FOR EACH ROW EXECUTE FUNCTION industry_touch_evidence_revision()''')
        # Preserve genuine historical moderation blocks; clear the short-lived
        # universal chapter-3 gate added by an earlier release.
        db.execute("""UPDATE industry_projects SET review_required_chapter=3
          WHERE review_required_chapter IS NULL AND (error LIKE '%-20058%' OR current_stage LIKE '%内容审核拦截%')""")
        db.execute("""UPDATE industry_projects p SET status='complete',current_stage='十章与摘要生成完成',
          error=NULL,progress_percent=100,completed_chapters=10,updated=now()
          WHERE review_required_chapter IS NULL AND current_stage='第3章资料待人工复核'
          AND EXISTS (SELECT 1 FROM industry_chapters c WHERE c.project_id=p.id AND c.chapter_no=0 AND c.status='complete' AND c.content<>'')
          AND 10=(SELECT count(*) FROM industry_chapters c WHERE c.project_id=p.id AND c.chapter_no BETWEEN 1 AND 10 AND c.status='complete' AND c.content<>'')""")
        # One-time-safe cleanup for reports generated before prompt-leak protection existed.
        for row in db.execute("SELECT project_id,chapter_no,content FROM industry_chapters WHERE content<>''"):
            cleaned = sanitize_generated_content(row['content'])
            if cleaned != row['content']:
                db.execute('''UPDATE industry_chapters SET content=%s,updated=now()
                    WHERE project_id=%s AND chapter_no=%s''',
                    (cleaned, row['project_id'], row['chapter_no']))


def snapshot_version(db, project_id, reason):
    project = db.execute('SELECT * FROM industry_projects WHERE id=%s FOR UPDATE', (project_id,)).fetchone()
    if not project:
        return None
    chapters = list(db.execute('SELECT * FROM industry_chapters WHERE project_id=%s ORDER BY chapter_no', (project_id,)))
    if not any(c['content'].strip() for c in chapters):
        return None
    project = dict(project, chapters=chapters)
    done = sum(c['chapter_no'] > 0 and c['status'] == 'complete' and bool(c['content'].strip()) for c in chapters)
    complete = len(chapters) == 11 and all(c['status'] == 'complete' and c['content'].strip() for c in chapters)
    project.update(status='complete' if complete else 'interrupted', completed_chapters=done,
                   progress_percent=100 if complete else done * 9, error=None, current_stage='历史版本')
    evidence = list(db.execute('SELECT * FROM industry_evidence WHERE project_id=%s ORDER BY created,id', (project_id,)))
    decision_data = list(db.execute('SELECT * FROM industry_decision_records WHERE project_id=%s ORDER BY record_type,created,id', (project_id,)))
    choices = list(db.execute('SELECT * FROM industry_chart_selections WHERE project_id=%s', (project_id,)))
    from .charts import discover
    specs = discover(dict(project, decision_records=decision_data))
    saved = {x['chart_id']: x for x in choices}
    selected = []
    for spec in specs:
        choice = saved.get(spec['id'])
        if choice and choice['selected'] and choice['chart_type'] in spec['chart_types']:
            selected.append(dict(spec, title=choice['title'], selected_type=choice['chart_type']))
    vid = uuid.uuid4().hex
    payload = dict(project=project, evidence=evidence, decision_records=decision_data,
                   choices=choices, charts=selected)
    db.execute('INSERT INTO industry_versions(id,project_id,reason,snapshot) VALUES (%s,%s,%s,%s::jsonb)',
               (vid, project_id, reason, json.dumps(payload, ensure_ascii=False, default=str)))
    return vid


def list_versions(project_id):
    with connect() as db:
        return list(db.execute("SELECT id,reason,created,snapshot->'project'->>'title' AS title FROM industry_versions WHERE project_id=%s ORDER BY created DESC,id DESC", (project_id,)))


def get_version(project_id, version_id):
    with connect() as db:
        return db.execute('SELECT * FROM industry_versions WHERE project_id=%s AND id=%s', (project_id, version_id)).fetchone()


def restore_version(project_id, version_id):
    with connect() as db:
        db.execute('SELECT id FROM industry_projects WHERE id=%s FOR UPDATE', (project_id,))
        version = db.execute('SELECT snapshot FROM industry_versions WHERE project_id=%s AND id=%s', (project_id, version_id)).fetchone()
        if not version:
            return False
        snapshot_version(db, project_id, '恢复历史版本前自动备份')
        data = version['snapshot']; project = data['project']
        db.execute('UPDATE industry_projects SET manufacturing_scenario=%s::jsonb WHERE id=%s',
                   (json.dumps(project.get('manufacturing_scenario'), ensure_ascii=False), project_id))
        # Snapshots are internal database records, not user-supplied table names.
        for table, rows in [('industry_chapters', project['chapters']),
                            ('industry_evidence', data['evidence']),
                            ('industry_decision_records', data.get('decision_records', [])),
                            ('industry_chart_selections', data['choices'])]:
            if table == 'industry_chapters':
                rows = [dict(item,
                             evidence_revision=item.get('evidence_revision', 0) or 0,
                             content_evidence_revision=item.get('content_evidence_revision', 0) or 0)
                        for item in rows]
            if table == 'industry_chapters':
                rows = [dict(item,
                             evidence_revision=item.get('evidence_revision', 0) or 0,
                             content_evidence_revision=item.get('content_evidence_revision', 0) or 0)
                        for item in rows]
            db.execute(f'DELETE FROM {table} WHERE project_id=%s', (project_id,))
            db.execute(f'INSERT INTO {table} SELECT * FROM jsonb_populate_recordset(NULL::{table},%s::jsonb)', (json.dumps(rows, ensure_ascii=False),))
        db.execute('UPDATE industry_projects SET title=%s,brief=%s::jsonb,status=%s,progress_percent=%s,completed_chapters=%s,current_stage=%s,error=NULL,updated=now() WHERE id=%s',
                   (project['title'], json.dumps(project['brief'], ensure_ascii=False), project['status'], project['progress_percent'], project['completed_chapters'], '已恢复历史版本', project_id))
    return True


def save_manufacturing_scenario(project_id, result):
    with connect() as db:
        if not db.execute('SELECT id FROM industry_projects WHERE id=%s FOR UPDATE', (project_id,)).fetchone():
            return False
        snapshot_version(db, project_id, '保存制造业测算前自动备份')
        db.execute('UPDATE industry_projects SET manufacturing_scenario=%s::jsonb,updated=now() WHERE id=%s',
                   (json.dumps(result, ensure_ascii=False), project_id))
        inputs = result.get('inputs', {})
        db.execute('''INSERT INTO industry_decision_records
          (id,project_id,record_type,name,fields,basis,source,as_of_date,verified)
          VALUES (%s,%s,'finance',%s,%s::jsonb,'calculated',%s,%s,FALSE)
          ON CONFLICT(id) DO UPDATE SET fields=excluded.fields,basis=excluded.basis,
          source=excluded.source,as_of_date=excluded.as_of_date,verified=FALSE,updated=now()''',
          ('mf-' + project_id, project_id, '制造业快速情景测算（待逐项验证）',
           json.dumps(result, ensure_ascii=False), inputs.get('source', ''), inputs.get('period', '')))
    return True


def upgrade_manufacturing_plan(project_id, plan):
    """Opt-in migration: snapshot old report, remap reusable evidence, reset prose."""
    expected = {item['chapter_no']: item['title'] for item in plan}
    with connect() as db:
        project = db.execute('SELECT * FROM industry_projects WHERE id=%s FOR UPDATE', (project_id,)).fetchone()
        if not project or project.get('brief', {}).get('research_template') != 'manufacturing':
            return None
        current = {row['chapter_no']: row['title'] for row in db.execute(
            'SELECT chapter_no,title FROM industry_chapters WHERE project_id=%s AND chapter_no BETWEEN 1 AND 10',
            (project_id,))}
        if current == expected:
            return 'already_current'
        snapshot_version(db, project_id, '升级制造业决策版研究计划前自动备份')
        # Old template -> decision template. Evidence is preserved and moved to
        # the closest new responsibility; later collection fills empty chapters.
        db.execute('''UPDATE industry_evidence SET chapter_no=CASE chapter_no
          WHEN 1 THEN 1 WHEN 2 THEN 5 WHEN 3 THEN 7 WHEN 4 THEN 2 WHEN 5 THEN 4
          WHEN 6 THEN 6 WHEN 7 THEN 4 WHEN 8 THEN 9 WHEN 9 THEN 8 WHEN 10 THEN 10
          ELSE chapter_no END WHERE project_id=%s''', (project_id,))
        db.execute('DELETE FROM industry_chapters WHERE project_id=%s', (project_id,))
        with db.cursor() as cursor:
            cursor.executemany('''INSERT INTO industry_chapters(project_id,chapter_no,title,questions,queries)
              VALUES (%s,%s,%s,%s::jsonb,%s::jsonb)''', [
                (project_id, item['chapter_no'], item['title'],
                 json.dumps(item['questions'], ensure_ascii=False), json.dumps(item['queries'], ensure_ascii=False))
                for item in plan])
        db.execute('DELETE FROM industry_chart_selections WHERE project_id=%s', (project_id,))
        db.execute("""UPDATE industry_projects SET status='planned',current_stage='已升级为制造业进入决策版，等待采集与生成',
          error=NULL,progress_percent=0,completed_chapters=0,review_required_chapter=NULL,
          started_at=NULL,stage_started_at=now(),updated=now() WHERE id=%s""", (project_id,))
    return 'upgraded'


def create_project(brief, plan):
    brief_json = json.dumps(brief.model_dump(), ensure_ascii=False, sort_keys=True)
    with connect() as db:
        # Serialize identical submissions so double-clicks and network retries cannot
        # create two empty plans at the same time.
        db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (brief_json,))
        reusable = db.execute('''SELECT p.id FROM industry_projects p
            WHERE p.brief=%s::jsonb AND p.status='planned'
              AND NOT EXISTS (SELECT 1 FROM industry_evidence e WHERE e.project_id=p.id)
              AND NOT EXISTS (SELECT 1 FROM industry_chapters c
                              WHERE c.project_id=p.id AND (c.content<>'' OR c.status<>'planned'))
            ORDER BY p.created DESC LIMIT 1''', (brief_json,)).fetchone()
        if reusable:
            return reusable['id']
        project_id = uuid.uuid4().hex
        db.execute('INSERT INTO industry_projects(id,title,brief) VALUES (%s,%s,%s)',
                   (project_id, f'{brief.geography}{brief.topic}行业研究', brief_json))
        with db.cursor() as cursor:
            cursor.executemany('INSERT INTO industry_chapters(project_id,chapter_no,title,questions,queries) VALUES (%s,%s,%s,%s,%s)', [
                (project_id, p['chapter_no'], p['title'], json.dumps(p['questions'], ensure_ascii=False), json.dumps(p['queries'], ensure_ascii=False)) for p in plan
            ])
    return project_id


def project(project_id):
    with connect() as db:
        row = db.execute('SELECT * FROM industry_projects WHERE id=%s', (project_id,)).fetchone()
        if not row:
            return None
        chapters = list(db.execute('''SELECT c.*,(SELECT count(*) FROM industry_evidence e WHERE e.project_id=c.project_id AND e.chapter_no=c.chapter_no) evidence_count
            FROM industry_chapters c WHERE project_id=%s ORDER BY chapter_no''', (project_id,)))
        for chapter_row in chapters:
            chapter_row['content'] = sanitize_generated_content(chapter_row.get('content', ''))
            chapter_row['evidence_stale'] = bool(
                chapter_row['content'].strip() and
                chapter_row.get('evidence_revision', 0) > chapter_row.get('content_evidence_revision', 0)
            )
        return dict(row, chapters=chapters)


def list_projects():
    with connect() as db:
        return list(db.execute('SELECT id,title,status,current_stage,error,progress_percent,completed_chapters,started_at,stage_started_at,created,updated FROM industry_projects ORDER BY created DESC'))


def update_project(project_id, title):
    with connect() as db:
        return db.execute('UPDATE industry_projects SET title=%s,updated=now() WHERE id=%s',
                          (title, project_id)).rowcount


def delete_project(project_id):
    with connect() as db:
        return db.execute('DELETE FROM industry_projects WHERE id=%s', (project_id,)).rowcount


def decision_records(project_id, record_type=None):
    with connect() as db:
        if record_type:
            return list(db.execute('SELECT * FROM industry_decision_records WHERE project_id=%s AND record_type=%s ORDER BY created,id',
                                   (project_id, record_type)))
        return list(db.execute('SELECT * FROM industry_decision_records WHERE project_id=%s ORDER BY record_type,created,id',
                               (project_id,)))


def decision_record(project_id, record_id):
    with connect() as db:
        return db.execute('SELECT * FROM industry_decision_records WHERE project_id=%s AND id=%s',
                          (project_id, record_id)).fetchone()


def add_decision_record(project_id, item):
    record_id = uuid.uuid4().hex
    with connect() as db:
        if not db.execute('SELECT 1 FROM industry_projects WHERE id=%s', (project_id,)).fetchone():
            return None
        db.execute('''INSERT INTO industry_decision_records
          (id,project_id,record_type,name,fields,basis,source,as_of_date,verified)
          VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)''',
          (record_id, project_id, item.record_type, item.name, json.dumps(item.fields, ensure_ascii=False),
           item.basis, item.source, item.as_of_date, item.verified))
    return record_id


def update_decision_record(project_id, record_id, item):
    values = item.model_dump(exclude_unset=True)
    if not values:
        with connect() as db:
            return bool(db.execute('SELECT 1 FROM industry_decision_records WHERE project_id=%s AND id=%s',
                                   (project_id, record_id)).fetchone())
    assignments, params = [], []
    for key, value in values.items():
        if key == 'fields':
            assignments.append('fields=%s::jsonb'); params.append(json.dumps(value, ensure_ascii=False))
        else:
            assignments.append(f'{key}=%s'); params.append(value)
    params.extend([project_id, record_id])
    with connect() as db:
        return bool(db.execute(f'''UPDATE industry_decision_records SET {','.join(assignments)},updated=now()
          WHERE project_id=%s AND id=%s''', params).rowcount)


def delete_decision_record(project_id, record_id):
    with connect() as db:
        return bool(db.execute('DELETE FROM industry_decision_records WHERE project_id=%s AND id=%s',
                               (project_id, record_id)).rowcount)


def update_chapter(project_id, chapter_no, title=None, content=None):
    fields, values = [], []
    if title is not None: fields.append('title=%s'); values.append(title)
    if content is not None:
        fields.extend(['content=%s', "status='complete'", 'content_evidence_revision=evidence_revision'])
        values.append(content)
    if not fields: return bool(chapter(project_id, chapter_no))
    values.extend([project_id, chapter_no])
    with connect() as db:
        return db.execute(f"UPDATE industry_chapters SET {','.join(fields)},updated=now() WHERE project_id=%s AND chapter_no=%s", values).rowcount


def chart_selections(project_id):
    with connect() as db:
        return {row['chart_id']: row for row in db.execute(
            'SELECT chart_id,chart_type,title,selected FROM industry_chart_selections WHERE project_id=%s', (project_id,))}


def save_chart_selections(project_id, choices):
    with connect() as db:
        if not db.execute('SELECT 1 FROM industry_projects WHERE id=%s', (project_id,)).fetchone(): return False
        db.execute('DELETE FROM industry_chart_selections WHERE project_id=%s', (project_id,))
        if choices:
            with db.cursor() as cursor:
                cursor.executemany('''INSERT INTO industry_chart_selections(project_id,chart_id,chart_type,title,selected)
                    VALUES (%s,%s,%s,%s,%s)''', [(project_id, x.id, x.chart_type, x.title, x.selected) for x in choices])
    return True


def save_chart_selection(project_id, choice):
    with connect() as db:
        if not db.execute('SELECT 1 FROM industry_projects WHERE id=%s', (project_id,)).fetchone(): return False
        db.execute('''INSERT INTO industry_chart_selections(project_id,chart_id,chart_type,title,selected)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT(project_id,chart_id) DO UPDATE SET
            chart_type=excluded.chart_type,title=excluded.title,selected=excluded.selected,updated=now()''',
            (project_id, choice.id, choice.chart_type, choice.title, choice.selected))
    return True


def remove_chart_selections(project_id, chart_ids):
    if not chart_ids: return 0
    with connect() as db:
        return db.execute('DELETE FROM industry_chart_selections WHERE project_id=%s AND chart_id=ANY(%s)',
                          (project_id, chart_ids)).rowcount


def add_evidence(project_id, item):
    evidence_id = uuid.uuid4().hex
    with connect() as db:
        exists = db.execute('SELECT 1 FROM industry_projects WHERE id=%s', (project_id,)).fetchone()
        if not exists:
            return None
        db.execute('''INSERT INTO industry_evidence(id,project_id,chapter_no,title,url,publisher,published_at,excerpt,source_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (evidence_id, project_id, item.chapter_no, item.title,
            item.url, item.publisher, item.published_at, item.excerpt, item.source_type))
    return evidence_id


def chapter(project_id, chapter_no):
    with connect() as db:
        return db.execute('SELECT * FROM industry_chapters WHERE project_id=%s AND chapter_no=%s',
                          (project_id, chapter_no)).fetchone()


def evidence_urls(project_id):
    with connect() as db:
        return [row['url'] for row in db.execute("SELECT url FROM industry_evidence WHERE project_id=%s AND url<>''", (project_id,))]


def add_search_results(project_id, chapter_no, collected):
    rows = []
    for query, result in collected:
        rows.append((uuid.uuid4().hex, project_id, chapter_no, result.title, result.url, result.publisher,
                     result.published_at, result.text, '网页搜索', result.provider, query, result.score,
                     result.provider_result_id, json.dumps(result.metadata, ensure_ascii=False)))
    if not rows:
        return 0
    with connect() as db:
        with db.cursor() as cursor:
            cursor.executemany('''INSERT INTO industry_evidence(
              id,project_id,chapter_no,title,url,publisher,published_at,excerpt,source_type,
              provider,search_query,score,provider_result_id,metadata)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', rows)
    return len(rows)


def _cache_key(provider, dataset, params):
    raw = json.dumps([provider, dataset, params], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def get_source_cache(provider, dataset, params):
    from .sources.base import StructuredEvidence
    with connect() as db:
        row = db.execute('SELECT payload FROM industry_source_cache WHERE cache_key=%s AND expires>now()',
                         (_cache_key(provider, dataset, params),)).fetchone()
    return StructuredEvidence(**row['payload']) if row else None


def put_source_cache(provider, dataset, params, evidence, ttl_days=7):
    with connect() as db:
        db.execute('''INSERT INTO industry_source_cache(cache_key,provider,dataset,params,payload,expires)
          VALUES (%s,%s,%s,%s,%s,now()+(%s * interval '1 day'))
          ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload,expires=excluded.expires,created=now()''',
          (_cache_key(provider, dataset, params), provider, dataset, json.dumps(params, ensure_ascii=False),
           json.dumps(asdict(evidence), ensure_ascii=False), ttl_days))


def add_structured_evidence(project_id, chapter_no, requirement, evidence):
    metadata = dict(evidence.metadata, dataset=evidence.dataset, requirement=requirement.label)
    with connect() as db:
        exists = db.execute('''SELECT 1 FROM industry_evidence
          WHERE project_id=%s AND chapter_no=%s AND provider=%s AND provider_result_id=%s''',
          (project_id, chapter_no, evidence.provider, evidence.dataset)).fetchone()
        if exists:
            return 0
        db.execute('''INSERT INTO industry_evidence(
          id,project_id,chapter_no,title,url,publisher,published_at,excerpt,source_type,
          provider,search_query,score,provider_result_id,metadata)
          VALUES (%s,%s,%s,%s,%s,%s,'',%s,'结构化数据',%s,'',1.0,%s,%s)''',
          (uuid.uuid4().hex, project_id, chapter_no, evidence.title, evidence.source_url, evidence.provider,
           evidence.text, evidence.provider, evidence.dataset, json.dumps(metadata, ensure_ascii=False)))
    return 1


def all_evidence(project_id):
    with connect() as db:
        return list(db.execute('''SELECT chapter_no,title,url,publisher,published_at,source_type,provider,
          excerpt,search_query,score,metadata,created,id FROM industry_evidence
          WHERE project_id=%s ORDER BY chapter_no,score DESC NULLS LAST,created,id''', (project_id,)))


def review_evidence(project_id, chapter_no):
    with connect() as db:
        return list(db.execute('SELECT * FROM industry_evidence WHERE project_id=%s AND chapter_no=%s ORDER BY score DESC NULLS LAST,created,id', (project_id, chapter_no)))


def save_evidence_review(project_id, chapter_no, evidence_id, decision):
    with connect() as db:
        snapshot_version(db, project_id, '资料审核前自动备份')
        saved = db.execute('''UPDATE industry_evidence SET metadata=jsonb_set(metadata,'{review}',%s::jsonb)
          WHERE project_id=%s AND chapter_no=%s AND id=%s''',
          (json.dumps(decision, ensure_ascii=False), project_id, chapter_no, evidence_id)).rowcount
        return saved


def save_evidence_reviews_bulk(project_id, chapter_no, decisions):
    """Persist an explicitly confirmed review batch with a single version snapshot."""
    if not decisions:
        return 0
    saved = 0
    with connect() as db:
        snapshot_version(db, project_id, '资料批量审核前自动备份')
        for evidence_id, decision in decisions.items():
            saved += db.execute(
                '''UPDATE industry_evidence
                   SET metadata=jsonb_set(metadata,'{review}',%s::jsonb)
                   WHERE project_id=%s AND chapter_no=%s AND id=%s''',
                (json.dumps(decision, ensure_ascii=False), project_id,
                 chapter_no, evidence_id),
            ).rowcount
    return saved


def evidence_review_state(project_id, chapter_no):
    """Return the universal human-review gate state for one chapter."""
    rows = review_evidence(project_id, chapter_no)
    decisions = [((row.get('metadata') or {}).get('review') or {}).get('decision') for row in rows]
    approved = sum(decision == 'approved' and bool(row.get('excerpt', '').strip())
                   for decision, row in zip(decisions, rows))
    pending = sum(not decision for decision in decisions)
    return {'total': len(rows), 'pending': pending, 'approved': approved,
            'complete': bool(rows) and pending == 0 and approved > 0}


def queue_reviewed_chapter_refresh(project_id, chapter_no):
    """Queue one completed chapter for regeneration from its newly reviewed evidence."""
    state = evidence_review_state(project_id, chapter_no)
    if not state['complete']:
        return None, state
    with connect() as db:
        chapter_row = db.execute('''SELECT * FROM industry_chapters
          WHERE project_id=%s AND chapter_no=%s FOR UPDATE''', (project_id, chapter_no)).fetchone()
        if not chapter_row:
            return None, state
        snapshot_version(db, project_id, f'按复核资料更新第{chapter_no}章前自动备份')
        db.execute("UPDATE industry_chapters SET status='planned',updated=now() WHERE project_id=%s AND chapter_no=%s",
                   (project_id, chapter_no))
        db.execute("UPDATE industry_chapters SET status='planned',updated=now() WHERE project_id=%s AND chapter_no=0",
                   (project_id,))
        done = db.execute('''SELECT count(*) AS n FROM industry_chapters WHERE project_id=%s
          AND chapter_no BETWEEN 1 AND 10 AND status='complete' AND content<>'' ''', (project_id,)).fetchone()['n']
        db.execute('''UPDATE industry_projects SET status='interrupted',current_stage=%s,error=NULL,
          completed_chapters=%s,progress_percent=%s,updated=now() WHERE id=%s''',
          (f'第{chapter_no}章资料已复核，等待更新正文', done, done * 9, project_id))
    return True, state


def save_evidence_pre_reviews(project_id, chapter_no, assessments):
    """Persist automatic triage beside, never over, the human review field."""
    if not assessments:
        return 0
    saved = 0
    with connect() as db:
        for evidence_id, assessment in assessments.items():
            saved += db.execute(
                '''UPDATE industry_evidence
                   SET metadata=jsonb_set(metadata,'{pre_review}',%s::jsonb)
                   WHERE project_id=%s AND chapter_no=%s AND id=%s''',
                (json.dumps(assessment, ensure_ascii=False), project_id,
                 chapter_no, evidence_id),
            ).rowcount
    return saved


def clear_review_requirement_if_complete(project_id, chapter_no):
    with connect() as db:
        project = db.execute('SELECT review_required_chapter FROM industry_projects WHERE id=%s FOR UPDATE',
                             (project_id,)).fetchone()
        if not project or project['review_required_chapter'] != chapter_no:
            return False
        rows = list(db.execute('SELECT metadata,excerpt FROM industry_evidence WHERE project_id=%s AND chapter_no=%s',
                               (project_id, chapter_no)))
        decisions = [r.get('metadata', {}).get('review', {}).get('decision') for r in rows]
        if rows and all(decisions) and any(d == 'approved' and r['excerpt'].strip() for d, r in zip(decisions, rows)):
            db.execute("UPDATE industry_projects SET review_required_chapter=NULL,status='interrupted',current_stage=%s,error=NULL,updated=now() WHERE id=%s",
                       (f'第{chapter_no}章资料复核完成，可继续生成', project_id))
            return True
    return False
