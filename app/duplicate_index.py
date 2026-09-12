"""Persistent exact hashes and deterministic MinHash LSH; fixed weight generations."""
import hashlib
import json
import uuid
from collections import OrderedDict
from threading import RLock

import numpy as np
from fastapi import HTTPException

from . import duplicates, structured

VERSION = 'minhash-64-32x2-v1'
_PRIME = (1 << 31) - 1
_A = np.array([int.from_bytes(hashlib.sha256(f'ckos-a-{i}'.encode()).digest()[:4], 'big') % (_PRIME-1)+1 for i in range(64)], dtype=np.uint64)
_B = np.array([int.from_bytes(hashlib.sha256(f'ckos-b-{i}'.encode()).digest()[:4], 'big') % _PRIME for i in range(64)], dtype=np.uint64)
_models = OrderedDict()
_lock = RLock()


def exact_hash(profile):
    data=[profile['text_hash'],profile.get('tables_hash'),profile['assets']]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False).encode()).hexdigest()


def bands(parts):
    if not parts:
        return []
    values=np.array([int.from_bytes(hashlib.sha256(s.encode()).digest()[:4],'big') % _PRIME for s in parts],dtype=np.uint64)
    signature=np.full(64,_PRIME,dtype=np.uint64)
    for offset in range(0,len(values),1024):
        permutations=(values[offset:offset+1024,None]*_A+_B) % _PRIME
        signature=np.minimum(signature,permutations.min(axis=0))
    return [(i, int.from_bytes(hashlib.sha256(signature[i*2:i*2+2].astype('>u8').tobytes()).digest()[:8],'big',signed=True)) for i in range(32)]


def scopes(profile, parts, weights, unseen):
    yield 'whole', parts
    # Another route emphasizes distinctive passages, while retaining the full-text route.
    distinctive={s for s in parts if weights.get(s,unseen)>=unseen*.5}
    if len(distinctive)>=20 and distinctive!=parts:
        yield 'distinctive', distinctive
    modules={}; current=None
    for text in profile['paragraphs']:
        module=next((m for m in structured.MODULES if m in text and len(text)<45 and ('诊断' in text or '建议' in text)),None)
        if module: current=module
        if current: modules.setdefault(current,[]).append(text)
    for module,paragraphs in modules.items():
        if sum(map(len,paragraphs))>=100:
            yield module,duplicates.shingles({'paragraphs':paragraphs})


def model(db, mid):
    with _lock:
        if mid in _models:
            _models.move_to_end(mid)
            return _models[mid]
        row=db.execute('SELECT weights,unseen FROM dedup_models WHERE id=%s',(mid,)).fetchone()
        _models[mid]=(row['weights'],row['unseen'])
        while len(_models)>2: _models.popitem(last=False)
        return _models[mid]


def add(db,row,profile,mid,weights,unseen):
    parts=duplicates.shingles(profile)
    total=sum(weights.get(s,unseen) for s in parts)
    db.execute('''INSERT INTO dedup_documents VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
      ON CONFLICT(document_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,profile_version=EXCLUDED.profile_version,index_version=EXCLUDED.index_version,model_id=EXCLUDED.model_id,exact_hash=EXCLUDED.exact_hash,shingles=EXCLUDED.shingles,weight_total=EXCLUDED.weight_total''',
      (row['id'],row['fingerprint'],duplicates.VERSION,VERSION,mid,exact_hash(profile),json.dumps(sorted(parts),ensure_ascii=False),total))
    db.execute('DELETE FROM dedup_buckets WHERE document_id=%s',(row['id'],))
    entries=[(row['id'],mid,scope,band,bucket) for scope,values in scopes(profile,parts,weights,unseen) for band,bucket in bands(values)]
    with db.cursor() as cursor:
        cursor.executemany('INSERT INTO dedup_buckets VALUES (%s,%s,%s,%s,%s)',entries)


def ensure(db,rows,refresh_weights=False):
    """Caller holds the publication lock. Rebuild only missing/stale entries."""
    active=db.execute('SELECT id FROM dedup_models WHERE active').fetchone()
    items=None
    if not active or refresh_weights:
        items=duplicates.profiles(db,rows)
        _,weights,unseen=duplicates.weights_for(items)
        mid=uuid.uuid4().hex
        db.execute('INSERT INTO dedup_models(id,weights,unseen) VALUES (%s,%s::jsonb,%s)',(mid,json.dumps(weights,ensure_ascii=False),unseen))
    else:
        mid=active['id'];weights,unseen=model(db,mid)
    indexed={r['document_id']:r for r in db.execute('SELECT document_id,fingerprint,profile_version,index_version,model_id FROM dedup_documents')}
    missing=[r for r in rows if not (r['id'] in indexed and indexed[r['id']]['fingerprint']==r['fingerprint'] and indexed[r['id']]['profile_version']==duplicates.VERSION and indexed[r['id']]['index_version']==VERSION and indexed[r['id']]['model_id']==mid)]
    if missing:
        for row,profile in (items if items is not None else duplicates.profiles(db,missing)):
            add(db,row,profile,mid,weights,unseen)
    if not active or refresh_weights:
        db.execute('UPDATE dedup_models SET active=FALSE WHERE active')
        db.execute('UPDATE dedup_models SET active=TRUE WHERE id=%s',(mid,))
    return mid,weights,unseen,len(missing)


def check(db,rows,incoming,threshold,company,replace_id=None,mode='fast'):
    if mode not in ('fast','strict'):
        raise HTTPException(422,'请选择快速检查或严格检查')
    mid,weights,unseen,rebuilt=ensure(db,rows)
    candidate_parts=duplicates.shingles(incoming)
    exact_ids={r['document_id'] for r in db.execute('SELECT document_id FROM dedup_documents WHERE model_id=%s AND exact_hash=%s',(mid,exact_hash(incoming)))}
    if exact_ids:
        # Exact equality already decides rejection; no need to hash LSH keys or score the corpus.
        matches=[dict(duplicates.public(row),exact=True,similarity=100.,
                 same_company=duplicates.name_key(company)==duplicates.name_key(row['company']),
                 tables_changed=False,images_changed=False,differences=[]) for row in rows if row['id'] in exact_ids]
        return matches,{'mode':mode,'candidates':len(matches),'documents':len(rows),'indexes_updated':rebuilt,'weight_version':mid,'route':'exact'},(mid,weights,unseen)
    if mode=='strict':
        ids={r['id'] for r in rows}
    else:
        keys=[(scope,band,bucket) for scope,parts in scopes(incoming,candidate_parts,weights,unseen) for band,bucket in bands(parts)]
        ids=set(exact_ids)
        if keys:
            scope_values,band_values,bucket_values=map(list,zip(*keys))
            ids.update(r['document_id'] for r in db.execute('''SELECT DISTINCT b.document_id FROM dedup_buckets b
              JOIN unnest(%s::text[],%s::integer[],%s::bigint[]) AS q(scope,band,bucket)
              ON b.scope=q.scope AND b.band=q.band AND b.bucket=q.bucket WHERE b.model_id=%s''',
              (scope_values,band_values,bucket_values,mid)))
        # Extra recall protection; never restrict cross-company LSH candidates to a top K.
        ids.update(r['id'] for r in rows if duplicates.name_key(r['company'])==duplicates.name_key(company))
        if replace_id: ids.add(replace_id)
    selected=[r for r in rows if r['id'] in ids]
    feature_rows={r['document_id']:r for r in db.execute('SELECT document_id,shingles,weight_total FROM dedup_documents WHERE document_id=ANY(%s)',([r['id'] for r in selected],))}
    items=duplicates.profiles(db,selected) if selected else []
    incoming_total=sum(weights.get(s,unseen) for s in candidate_parts)
    matches=[]
    for row,profile in items:
        indexed=feature_rows[row['id']]
        intersection=sum(weights.get(s,unseen) for s in candidate_parts & set(indexed['shingles']))
        score=min(1.,intersection/max(1e-12,incoming_total+indexed['weight_total']-intersection))
        exact=row['id'] in exact_ids
        if exact or score>=threshold/100 or row['id']==replace_id:
            matches.append(dict(duplicates.public(row),exact=exact,similarity=round(score*100,2),
                same_company=duplicates.name_key(company)==duplicates.name_key(row['company']),
                tables_changed=incoming.get('tables_hash')!=profile.get('tables_hash'),images_changed=incoming['assets']!=profile['assets'],
                differences=duplicates.differences(incoming,profile)))
    stats={'mode':mode,'candidates':len(selected),'documents':len(rows),'indexes_updated':rebuilt,'weight_version':mid}
    return sorted(matches,key=lambda r:(r['exact'],r['similarity']),reverse=True),stats,(mid,weights,unseen)
