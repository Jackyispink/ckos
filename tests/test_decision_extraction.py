import asyncio
import json

from app import llm
from app.industry_research import decision_extraction as extraction


def _evidence(excerpt, *, evidence_id='e-1', chapter_no=4, metadata=None):
    return {
        'id': evidence_id,
        'chapter_no': chapter_no,
        'title': '行业统计',
        'url': 'https://stats.gov.cn/example',
        'publisher': '国家统计局',
        'published_at': '2024-01-10',
        'excerpt': excerpt,
        'source_type': 'official_statistics',
        'provider': 'test',
        'metadata': metadata or {},
        'score': 1.0,
    }


def test_rule_extracts_chinese_sentence_without_stripping_year():
    row = _evidence('2023年国内瓦楞纸箱市场规模为4800亿元，同比增长8.4%。')

    candidates = extraction.rule_candidates('project-1', {'brief': {}}, [row])

    assert len(candidates) == 1
    item = candidates[0]
    assert item['basis'] == 'unverified'
    assert item['verified'] is False
    assert item['record_type'] == 'market'
    assert item['fields']['periods'] == ['2023年']
    assert item['fields']['measurements'] == [
        {'value': '4800', 'unit': '亿元', 'raw': '4800亿元'},
        {'value': '8.4', 'unit': '%', 'raw': '8.4%'},
    ]
    auto = item['fields']['auto_extraction']
    assert auto['extractor_version'] == extraction.EXTRACTOR_VERSION
    assert auto['exact_quote'].startswith('2023年')
    assert auto['exact_quote'] in row['excerpt']
    assert auto['origin_evidence_ids'] == ['e-1']
    assert auto['source_grade'] == 'A'
    assert auto['review_state'] == 'auto_extracted_pending_review'


def test_rule_ignores_excluded_or_untraceable_evidence():
    excluded = _evidence(
        '2023年市场规模为4800亿元。',
        evidence_id='excluded',
        metadata={'review': {'decision': 'excluded'}},
    )
    missing_id = _evidence('2023年市场规模为4800亿元。', evidence_id='')

    assert extraction.rule_candidates('project-1', {}, [excluded, missing_id]) == []


def test_pre_review_metadata_does_not_invalidate_extraction_hash():
    project = {'brief': {'topic': '包装'}}
    row = _evidence(
        '2023年市场规模为4800亿元。',
        metadata={'provider_payload': {'request_id': 'request-1'}},
    )
    original = extraction._evidence_input_hash(project, [row])

    row['metadata']['pre_review'] = {
        'state': 'manual_review',
        'selection_confidence': 0.45,
    }
    assert extraction._evidence_input_hash(project, [row]) == original

    # Provider payloads and review comments are not extraction inputs. Only
    # the explicit human eligibility decision may invalidate a paid-run cache.
    row['metadata']['provider_payload']['request_id'] = 'request-2'
    assert extraction._evidence_input_hash(project, [row]) == original

    row['metadata']['review'] = {
        'decision': 'excluded',
        'reason': '人工判定口径不符',
    }
    excluded = extraction._evidence_input_hash(project, [row])
    assert excluded != original

    row['metadata']['review']['reason'] = '修改审核备注但不改变决定'
    assert extraction._evidence_input_hash(project, [row]) == excluded

    row['title'] = '另一统计口径'
    assert extraction._evidence_input_hash(project, [row]) != excluded


def test_numeric_validation_uses_complete_tokens_and_paired_units():
    quote = '2023年市场规模为4800亿元，同比增长8.4%。'

    assert extraction._number_in_quote('2023', quote)
    assert extraction._number_in_quote('4800', quote)
    assert not extraction._number_in_quote('20', quote)
    assert extraction._measurement_in_quote('4800', '亿元', quote)
    assert not extraction._measurement_in_quote('4800', '%', quote)
    assert not extraction._measurement_in_quote('5000', '亿元', quote)


def test_model_accepts_only_exact_supported_quote_and_derives_labels(monkeypatch):
    quote = '2023年国内瓦楞纸箱市场规模为4800亿元，同比增长8.4%。'
    evidence = [_evidence(quote)]
    payload = {
        'candidates': [
            {
                'record_type': 'market',
                'name': '模型编造的友好名称',
                'evidence_id': 'e-1',
                'exact_quote': quote,
                'metric': '模型编造的指标',
                'value': '4800',
                'unit': '亿元',
                'period': '2023年',
                'geography': '全球',
                'scope': '全行业',
            },
            {
                'record_type': 'market',
                'evidence_id': 'e-1',
                'exact_quote': quote,
                'value': '5000',
                'unit': '亿元',
            },
            {
                'record_type': 'market',
                'evidence_id': 'e-1',
                'exact_quote': '原文中不存在的市场规模为9999亿元。',
                'value': '9999',
                'unit': '亿元',
            },
        ],
    }

    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def complete(messages, *, output_tokens):
        assert output_tokens == 3500
        assert '不得计算、推断、补全' in messages[0]['content']
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(extraction.llm, 'complete', complete)
    candidates, method = asyncio.run(extraction.model_candidates(
        'project-1', {'brief': {}}, evidence, input_hash='hash-1',
    ))

    assert method == 'AI精确引文整理'
    assert len(candidates) == 1
    item = candidates[0]
    assert item['basis'] == 'unverified'
    assert item['verified'] is False
    assert '模型编造' not in item['name']
    assert '模型编造' not in item['fields']['metric']
    assert item['fields']['geography'] == ''
    assert item['fields']['scope'] == '仅限原文引文所述口径'
    assert item['fields']['auto_extraction']['exact_quote'] == quote


def test_model_candidate_parser_accepts_common_provider_envelopes(monkeypatch):
    quote = '2023年国内瓦楞纸箱市场规模为4800亿元。'
    evidence = [_evidence(quote)]
    candidate = {
        'record_type': 'market',
        'evidence_id': 'e-1',
        'exact_quote': quote,
        'value': '4800',
        'unit': '亿元',
        'period': '2023年',
    }
    responses = [
        {'data': {'candidates': [candidate]}},
        {'result': {'items': [candidate]}},
        [candidate],
        candidate,
        {'candidates': json.dumps([candidate], ensure_ascii=False)},
    ]
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    for payload in responses:
        async def complete(_messages, *, output_tokens, payload=payload):
            assert output_tokens == 3500
            return json.dumps(payload, ensure_ascii=False)

        monkeypatch.setattr(extraction.llm, 'complete', complete)
        candidates, method = asyncio.run(extraction.model_candidates(
            'project-1', {'brief': {}}, evidence, input_hash='hash-1',
        ))
        assert len(candidates) == 1
        assert candidates[0]['fields']['auto_extraction']['exact_quote'] == quote
        assert 'AI' in method


def test_model_schema_drift_without_candidates_falls_back_safely(monkeypatch):
    evidence = [_evidence('2023年国内瓦楞纸箱市场规模为4800亿元。')]
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def complete(_messages, *, output_tokens):
        return json.dumps({'analysis': '没有按要求输出候选数组'}, ensure_ascii=False)

    monkeypatch.setattr(extraction.llm, 'complete', complete)
    candidates, method = asyncio.run(extraction.model_candidates(
        'project-1', {'brief': {}}, evidence, input_hash='hash-1',
    ))

    assert candidates == []
    assert method == 'AI响应无可验证候选，已使用程序规则整理'


def test_model_extraction_batches_many_sources_and_omits_long_focus(monkeypatch):
    evidence = [
        _evidence(
            f'资料{i}明确说明客户认证和量产验证仍需逐项核验。',
            evidence_id=f'e-{i}', chapter_no=(i % 10) + 1,
        )
        for i in range(18)
    ]
    calls = []
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def complete(messages, *, output_tokens):
        request = json.loads(messages[1]['content'])
        calls.append((output_tokens, request))
        return json.dumps({'candidates': [
            {
                'record_type': 'risk',
                'evidence_id': source['evidence_id'],
                'exact_quote': source['excerpt'],
                'value': None,
                'unit': '',
                'period': '',
                'geography': '',
                'scope': '',
            }
            for source in request['sources']
        ]}, ensure_ascii=False)

    monkeypatch.setattr(extraction.llm, 'complete', complete)
    candidates, method = asyncio.run(extraction.model_candidates(
        'project-1', {'brief': {
            'topic': '汽车零部件',
            'product_scope': '电子膨胀阀' * 300,
            'focus': '很长的重点关注' * 1000,
        }}, evidence, input_hash='hash-many',
    ))

    assert len(calls) == 3
    assert all(tokens == 1800 for tokens, _ in calls)
    assert all(len(request['sources']) <= 6 for _, request in calls)
    assert all('focus' not in request['research_brief'] for _, request in calls)
    assert all(len(request['research_brief']['product_scope']) <= 600
               for _, request in calls)
    assert len(candidates) == 18
    assert method == 'AI分批精确引文整理（3批）'


def test_successful_empty_ai_result_is_cached_and_not_charged_twice(monkeypatch):
    row = _evidence('这里有资料，但没有可结构化的数值或实体。')
    cache = {}
    calls = {'model': 0, 'persist': 0}

    monkeypatch.setattr(extraction.database, 'project', lambda project_id: {
        'id': project_id, 'brief': {'research_template': 'manufacturing'},
    })
    monkeypatch.setattr(extraction.database, 'all_evidence', lambda project_id: [row])
    monkeypatch.setattr(extraction.database, 'decision_records', lambda project_id: [])
    monkeypatch.setattr(extraction, 'rule_candidates', lambda *args, **kwargs: [])
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def model_candidates(*args, **kwargs):
        calls['model'] += 1
        return [], 'AI精确引文整理'

    def persist(*args, **kwargs):
        calls['persist'] += 1
        return 0, 0

    def load_cache(*args):
        return cache.get('payload')

    def save_cache(project_id, input_hash, use_ai, candidate_ids, result):
        cache['payload'] = {'candidate_ids': candidate_ids, 'result': dict(result)}

    monkeypatch.setattr(extraction, 'model_candidates', model_candidates)
    monkeypatch.setattr(extraction, '_persist', persist)
    monkeypatch.setattr(extraction, '_load_run_cache', load_cache)
    monkeypatch.setattr(extraction, '_save_run_cache', save_cache)

    first = asyncio.run(extraction.extract_project('project-1'))
    second = asyncio.run(extraction.extract_project('project-1'))

    assert first['cached'] is False
    assert second['cached'] is True
    assert second['candidates'] == 0
    assert calls == {'model': 1, 'persist': 1}


def test_failed_ai_result_remains_retryable(monkeypatch):
    row = _evidence('这里有资料，但没有可结构化的数值或实体。')
    calls = {'model': 0, 'cache_save': 0}

    monkeypatch.setattr(extraction.database, 'project', lambda project_id: {
        'id': project_id, 'brief': {},
    })
    monkeypatch.setattr(extraction.database, 'all_evidence', lambda project_id: [row])
    monkeypatch.setattr(extraction.database, 'decision_records', lambda project_id: [])
    monkeypatch.setattr(extraction, 'rule_candidates', lambda *args, **kwargs: [])
    monkeypatch.setattr(extraction, '_load_run_cache', lambda *args: None)
    monkeypatch.setattr(extraction, '_persist', lambda *args: (0, 0))
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def fail(*args, **kwargs):
        calls['model'] += 1
        raise llm.ModelError('temporary')

    def save(*args, **kwargs):
        calls['cache_save'] += 1

    monkeypatch.setattr(extraction, 'model_candidates', fail)
    monkeypatch.setattr(extraction, '_save_run_cache', save)

    first = asyncio.run(extraction.extract_project('project-1'))
    second = asyncio.run(extraction.extract_project('project-1'))

    assert first['warning'] == 'temporary'
    assert second['warning'] == 'temporary'
    assert calls == {'model': 2, 'cache_save': 0}


def test_provider_review_required_is_negative_cached_without_second_model_call(monkeypatch):
    row = _evidence('2023年市场规模为4800亿元。')
    cache = {}
    calls = {'model': 0, 'persist': 0, 'cache_save': 0}

    monkeypatch.setattr(extraction.database, 'project', lambda project_id: {
        'id': project_id, 'brief': {},
    })
    monkeypatch.setattr(extraction.database, 'all_evidence', lambda project_id: [row])
    monkeypatch.setattr(extraction.database, 'decision_records', lambda project_id: [])
    monkeypatch.setattr(extraction, 'rule_candidates', lambda *args, **kwargs: [])
    monkeypatch.setattr(extraction.llm, 'configured', lambda: True)

    async def blocked(*args, **kwargs):
        calls['model'] += 1
        raise llm.ModelContentReviewRequired('provider review required')

    def persist(*args, **kwargs):
        calls['persist'] += 1
        return 0, 0

    def load_cache(*args):
        return cache.get('payload')

    def save_cache(project_id, input_hash, use_ai, candidate_ids, result):
        calls['cache_save'] += 1
        cache['payload'] = {
            'candidate_ids': candidate_ids,
            'result': dict(result),
        }

    monkeypatch.setattr(extraction, 'model_candidates', blocked)
    monkeypatch.setattr(extraction, '_persist', persist)
    monkeypatch.setattr(extraction, '_load_run_cache', load_cache)
    monkeypatch.setattr(extraction, '_save_run_cache', save_cache)

    first = asyncio.run(extraction.extract_project('project-1'))
    second = asyncio.run(extraction.extract_project('project-1'))

    assert first['ai_status'] == 'provider_review_required'
    assert first['cached'] is False
    assert second['ai_status'] == 'provider_review_required'
    assert second['cached'] is True
    assert second['method'] == '缓存命中，未重复调用模型'
    assert calls == {'model': 1, 'persist': 1, 'cache_save': 1}


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _MemoryDecisionDB:
    """Tiny SQL-shaped store used to exercise _persist transaction semantics."""

    def __init__(self):
        self.records = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, params=()):
        query = ' '.join(statement.split())
        if query.startswith('SELECT 1 FROM industry_projects'):
            return _Result({'exists': 1})
        if query.startswith('SELECT basis,verified FROM industry_decision_records'):
            row = self.records.get(params[1])
            return _Result(
                {'basis': row['basis'], 'verified': row['verified']} if row else None
            )
        if query.startswith('INSERT INTO industry_decision_records'):
            record_id, project_id, record_type, name, fields, source, as_of_date = params
            old = self.records.get(record_id)
            if old and (old['verified'] or old['basis'] != 'unverified'):
                return _Result()
            self.records[record_id] = {
                'id': record_id,
                'project_id': project_id,
                'record_type': record_type,
                'name': name,
                'fields': json.loads(fields),
                'basis': 'unverified',
                'source': source,
                'as_of_date': as_of_date,
                'verified': False,
            }
            return _Result()
        if query.startswith('DELETE FROM industry_decision_records'):
            project_id, current_ids = params
            for record_id, row in list(self.records.items()):
                auto = (row.get('fields') or {}).get('auto_extraction') or {}
                if (
                    row['project_id'] == project_id
                    and row['basis'] == 'unverified'
                    and row['verified'] is False
                    and auto.get('managed') is True
                    and record_id not in current_ids
                ):
                    del self.records[record_id]
            return _Result()
        raise AssertionError(f'unexpected SQL: {query}')


def test_persist_is_idempotent_and_never_overwrites_confirmed_record(monkeypatch):
    db = _MemoryDecisionDB()
    monkeypatch.setattr(extraction.database, 'connect', lambda: db)
    candidate = extraction.rule_candidates(
        'project-1', {'brief': {}},
        [_evidence('2023年市场规模为4800亿元。')],
    )[0]

    assert extraction._persist('project-1', [candidate], 'hash-1') == (1, 0)
    assert extraction._persist('project-1', [candidate], 'hash-1') == (0, 1)
    assert len(db.records) == 1

    saved = db.records[candidate['id']]
    saved['verified'] = True
    saved['basis'] = 'actual'
    saved['name'] = '人工确认名称'
    assert extraction._persist('project-1', [candidate], 'hash-1') == (0, 1)
    assert db.records[candidate['id']]['name'] == '人工确认名称'

    db.records['stale-auto'] = {
        'id': 'stale-auto', 'project_id': 'project-1', 'basis': 'unverified',
        'verified': False, 'fields': {'auto_extraction': {'managed': True}},
    }
    db.records['manual'] = {
        'id': 'manual', 'project_id': 'project-1', 'basis': 'unverified',
        'verified': False, 'fields': {},
    }
    extraction._persist('project-1', [], 'hash-2')

    assert 'stale-auto' not in db.records
    assert 'manual' in db.records
    assert candidate['id'] in db.records
