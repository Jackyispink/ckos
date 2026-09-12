"""Compare original documents before publishing or splitting incoming reports."""
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from zipfile import ZipFile
from threading import RLock

from fastapi import HTTPException
from lxml import etree

from . import kb

LOCK = 724603091  # Serializes name checks, similarity checks and publication.
VERSION = 2
DEFAULT_THRESHOLD = 90
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
_index_lock = RLock()
_index_key = None
_index = None


def prepared_index(items):
    """Reuse immutable shingle sets; invalidate scores whenever the corpus changes."""
    global _index_key, _index
    key = tuple((row['id'], profile['text_hash']) for row, profile in items)
    with _index_lock:
        if key == _index_key:
            return _index
        previous = dict(zip(_index_key, _index[0])) if _index_key is not None else {}
        sets = [previous[k] if k in previous else shingles(profile)
                for k, (_, profile) in zip(key, items)]
        weights, unseen = frequency_weights(sets)
        totals = [sum(weights[s] for s in parts) for parts in sets]
        _index = (sets, weights, unseen, totals)
        _index_key = key
        return _index


def name_key(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold().removesuffix('.docx')


def normalized(value):
    # Keep punctuation and digits: decimal points, signs and percentages matter.
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def inventory(db):
    return list(db.execute('''SELECT d.id,d.name AS storage_name,d.fingerprint,
      COALESCE(l.report_title,d.name) AS title,COALESCE(l.company_name,c.name,'待确认企业') AS company,
      COALESCE(s.deleted,FALSE) AS deleted,
      EXISTS(SELECT 1 FROM document_versions v WHERE v.previous_document_id=d.id) AS superseded
      FROM documents d LEFT JOIN document_labels l ON l.document_id=d.id
      LEFT JOIN document_state s ON s.document_id=d.id
      LEFT JOIN kb_reports r ON r.document_id=d.id AND r.active
      LEFT JOIN kb_companies c ON c.id=r.company_id ORDER BY d.id'''))


def public(row):
    return {k: row[k] for k in ('id', 'title', 'company', 'deleted')}


def check_names(rows, company, title, replace_id=None, exclude_id=None):
    target = next((r for r in rows if r['id'] == replace_id), None)
    if replace_id and (not target or target['deleted'] or name_key(target['company']) != name_key(company)):
        raise HTTPException(409, {'code': 'invalid_version', 'message': '只能更新同一企业尚未删除的报告，请重新选择。'})
    matches = [public(r) for r in rows if r['id'] not in (replace_id, exclude_id)
               and not (r['superseded'] and r['deleted']) and name_key(r['company']) == name_key(company)
               and name_key(r['title']) == name_key(title)]
    if matches:
        raise HTTPException(409, {'code': 'name_conflict', 'message': '该企业已有同名报告，请修改报告名称或选择更新已有报告。', 'matches': matches})
    return target


def extract(source):
    """No chunking, model calls, assets or production records are created here."""
    try:
        with ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(i.file_size for i in entries) > 250 * 1024 * 1024:
                raise HTTPException(422, '文档解压后过大，请拆分后上传。')
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            root = etree.fromstring(archive.read('word/document.xml'), parser)
            paragraphs = [''.join(p.xpath('.//w:t/text()', namespaces=NS))
                          for p in root.xpath('.//w:p', namespaces=NS)]
            paragraphs = [normalized(p) for p in paragraphs if normalized(p)]
            if not paragraphs:
                raise HTTPException(422, '未找到可读取的正文或表格，纯图片文档暂不支持上传。')
            assets = sorted(hashlib.sha256(archive.read(i.filename)).hexdigest() for i in entries
                            if i.filename.startswith(('word/media/', 'word/charts/')) and not i.is_dir())
            text = ''.join(paragraphs)
            tables = [[[normalized(''.join(cell.xpath('.//w:t/text()', namespaces=NS)))
                        for cell in row.xpath('./w:tc', namespaces=NS)]
                       for row in table.xpath('./w:tr', namespaces=NS)]
                      for table in root.xpath('.//w:tbl', namespaces=NS)]
            return {'paragraphs': paragraphs, 'text_hash': hashlib.sha256(text.encode()).hexdigest(),
                    'tables_hash': hashlib.sha256(json.dumps(tables, ensure_ascii=False).encode()).hexdigest(),
                    'assets': assets, 'characters': len(text)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, '无法读取文档，请确认它是未加密且未损坏的 .docx 文件。') from None


def profiles(db, rows):
    cached = {r['document_id']: r for r in db.execute('SELECT * FROM original_profiles WHERE document_id=ANY(%s)', ([r['id'] for r in rows],))}
    result = []
    for row in rows:
        cache = cached.get(row['id'])
        if cache and cache['fingerprint'] == row['fingerprint'] and cache['version'] == VERSION:
            profile = cache['profile']
        else:
            path = kb.ROOT / 'data' / row['storage_name']
            try:
                profile = extract(path)
            except HTTPException:
                # Do not silently publish when an existing original cannot be compared.
                raise HTTPException(409, {'code': 'comparison_unavailable', 'message': '已有原文件无法读取，重复检查未完成：' + row['title']}) from None
            cache_profile(db, row['id'], row['fingerprint'], profile)
        result.append((row, profile))
    return result


def cache_profile(db, did, fingerprint, profile):
    db.execute('''INSERT INTO original_profiles VALUES (%s,%s,%s,%s::jsonb)
      ON CONFLICT(document_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,version=EXCLUDED.version,profile=EXCLUDED.profile''',
               (did, fingerprint, VERSION, json.dumps(profile, ensure_ascii=False)))


def shingles(profile):
    text = ''.join(profile['paragraphs'])
    return {text[i:i+5] for i in range(max(1, len(text)-4))}


def weights_for(items):
    sets = [shingles(p) for _, p in items]
    weights, unseen = frequency_weights(sets)
    return sets, weights, unseen


def frequency_weights(sets):
    frequencies = Counter(s for parts in sets for s in parts)
    n = len(sets)
    if n < 5:
        # With too few originals, frequency cannot distinguish a template from unique content.
        return {s: 1.0 for s in frequencies}, 1.0
    # Repeated template passages contribute less; do not remove numbers or company facts.
    weights = {s: 0.1 + math.log((n+1)/(count+1)) for s, count in frequencies.items()}
    return weights, 0.1 + math.log(n+1)


def similarity(left, right, weights, unseen):
    union = left | right
    return sum(weights.get(s, unseen) for s in left & right) / max(1e-12, sum(weights.get(s, unseen) for s in union))


def differences(incoming, existing):
    a, b = existing['paragraphs'], incoming['paragraphs']
    changes = []
    for tag, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != 'equal':
            changes.append({'before': ' / '.join(a[i:j])[:450], 'after': ' / '.join(b[k:l])[:450]})
        if len(changes) == 3:
            break
    return changes


def compare(incoming, items, threshold, company, replace_id=None):
    sets, weights, unseen, totals = prepared_index(items)
    candidate = shingles(incoming)
    candidate_total = sum(weights.get(s, unseen) for s in candidate)
    matches = []
    for (row, profile), parts, total in zip(items, sets, totals):
        exact_text = incoming['text_hash'] == profile['text_hash']
        same_assets = incoming['assets'] == profile['assets']
        same_tables = incoming.get('tables_hash') == profile.get('tables_hash')
        intersection = sum(weights[s] for s in candidate & parts)
        score = min(1.0, intersection / max(1e-12, candidate_total + total - intersection))
        exact = exact_text and same_assets and same_tables
        if exact or score >= threshold / 100 or row['id'] == replace_id:
            matches.append(dict(public(row), similarity=round(score*100, 2), exact=exact,
                                same_company=name_key(company) == name_key(row['company']),
                                tables_changed=not same_tables,
                                images_changed=not same_assets, differences=differences(incoming, profile)))
    return sorted(matches, key=lambda r: (r['exact'], r['similarity']), reverse=True)
