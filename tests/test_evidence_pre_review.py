from app.industry_research import evidence_pre_review, evidence_review


def _row(evidence_id='e1', excerpt='2024年市场规模为100亿元。', **overrides):
    row = {
        'id': evidence_id,
        'chapter_no': 4,
        'title': '食品饮料瓦楞纸箱年度数据',
        'publisher': '国家统计局',
        'published_at': '2025-01-01',
        'url': f'https://stats.gov.cn/{evidence_id}',
        'source_type': 'official_statistics',
        'provider': 'exa',
        'search_query': '食品饮料瓦楞纸箱 市场规模',
        'score': 0.8,
        'excerpt': excerpt,
        'metadata': {},
    }
    row.update(overrides)
    return row


def _project():
    return {
        'id': 'p1',
        'brief': {'topic': '食品饮料瓦楞纸箱'},
        'review_required_chapter': 4,
    }


def _chapter():
    return {
        'chapter_no': 4,
        'title': '下游需求与市场空间',
        'questions': ['市场规模多大'],
        'queries': ['市场规模'],
    }


def test_program_triage_keeps_literal_quotes_and_marks_conflicts_for_people():
    first = _row('e1', '2024年市场规模为100亿元。')
    second = _row('e2', '2024年市场规模为120亿元。')
    duplicate = _row('e3', first['excerpt'])

    result = evidence_pre_review.program_assessments(
        _project(), _chapter(), [first, second, duplicate],
    )

    assert result['e1']['state'] == result['e2']['state'] == 'manual_review'
    assert any('不同数值' in item for item in result['e1']['risks'])
    assert result['e3']['state'] == 'duplicate'
    assert result['e1']['exact_quotes'][0]['quote'] == first['excerpt']
    assert result['e1']['exact_quotes'][0]['quote'] in first['excerpt']
    assert '不表示' in result['e1']['confidence_meaning']
    assert '已核验' in result['e1']['confidence_meaning']


def test_conflict_detection_is_scope_aware_and_normalizes_thousands_separator():
    global_row = _row(
        'global', '2024年全球食品饮料瓦楞箱市场规模为100亿元。',
    )
    china_row = _row(
        'china', '2024年中国食品饮料瓦楞箱市场规模为120亿元。',
    )
    plain = _row(
        'plain', '2023年中国食品饮料瓦楞箱市场规模为1000亿元。',
    )
    comma = _row(
        'comma', '2023年中国食品饮料瓦楞箱市场规模为1,000亿元。',
    )
    same_scope_first = _row(
        'same-100', '2022年中国食品饮料瓦楞箱市场规模为100亿元。',
    )
    same_scope_second = _row(
        'same-120', '2022年中国食品饮料瓦楞箱市场规模为120亿元。',
    )

    result = evidence_pre_review.program_assessments(
        _project(), _chapter(), [
            global_row, china_row, plain, comma,
            same_scope_first, same_scope_second,
        ],
    )

    conflict_note = '不同数值'
    assert not any(conflict_note in item for item in result['global']['risks'])
    assert not any(conflict_note in item for item in result['china']['risks'])
    assert not any(conflict_note in item for item in result['plain']['risks'])
    assert not any(conflict_note in item for item in result['comma']['risks'])
    assert any(conflict_note in item for item in result['same-100']['risks'])
    assert any(conflict_note in item for item in result['same-120']['risks'])


def test_automatic_triage_never_silently_excludes_and_human_decision_wins():
    row = _row(metadata={'pre_review': {
        'version': evidence_review.PRE_REVIEW_VERSION,
        'evidence_fingerprint': '',
        'chapter_no': 4,
        'state': 'manual_review',
    }})
    row['metadata']['pre_review']['evidence_fingerprint'] = (
        evidence_review.evidence_fingerprint(row)
    )

    assert evidence_review.is_usable(row) is True

    row['metadata']['review'] = {'decision': 'excluded', 'reason': '口径不符'}
    assert evidence_review.is_usable(row) is False

    row['metadata']['review'] = {'decision': 'approved', 'reason': '已核对'}
    assert evidence_review.is_usable(row) is True


def test_shared_model_quote_must_be_literal_source_substring():
    row = _row()
    valid = {'fields': {'auto_extraction': {
        'managed': True,
        'origin_evidence_ids': ['e1'],
        'exact_quote': row['excerpt'],
    }}}
    fabricated = {'fields': {'auto_extraction': {
        'managed': True,
        'origin_evidence_ids': ['e1'],
        'exact_quote': '2024年市场规模为999亿元。',
    }}}

    accepted, rejected = evidence_pre_review._shared_exact_quotes(
        [valid, fabricated], [row],
    )

    assert accepted == {'e1': [row['excerpt']]}
    assert rejected == 1


def test_duplicate_detection_preserves_numeric_sign_and_decimal_point():
    negative = _row('negative', '2024年市场增速为-10%。')
    positive = _row('positive', '2024年市场增速为10%。')
    decimal = _row('decimal', '2024年市场增速为1.2%。')
    integer = _row('integer', '2024年市场增速为12%。')

    result = evidence_pre_review.program_assessments(
        _project(), _chapter(), [negative, positive, decimal, integer],
    )

    assert all(item['state'] != 'duplicate' for item in result.values())


def test_refresh_from_existing_does_not_call_model_or_clear_provider_gate(monkeypatch):
    row = _row()
    project = dict(_project(), chapters=[_chapter()])
    record = {'fields': {'auto_extraction': {
        'managed': True,
        'ai_status': 'success',
        'origin_evidence_ids': ['e1'],
        'exact_quote': row['excerpt'],
    }}}
    saved = []

    monkeypatch.setattr(evidence_pre_review.database, 'project', lambda _pid: project)
    monkeypatch.setattr(
        evidence_pre_review.database, 'decision_records', lambda _pid: [record],
    )
    monkeypatch.setattr(evidence_pre_review.database, 'chapter', lambda *_args: None)
    monkeypatch.setattr(
        evidence_pre_review.database,
        'review_evidence',
        lambda _pid, chapter_no: [row] if chapter_no == 4 else [],
    )
    monkeypatch.setattr(
        evidence_pre_review.database,
        'save_evidence_pre_reviews',
        lambda _pid, chapter_no, assessments: (
            saved.append((chapter_no, assessments)) or len(assessments)
        ),
    )
    monkeypatch.setattr(
        evidence_pre_review.llm,
        'complete',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('model must not run')
        ),
    )

    result = evidence_pre_review.refresh_project_from_existing('p1')

    assert result == {
        'rows': 1,
        'shared_exact_quotes': 1,
        'model_called': False,
    }
    assessment = next(value['e1'] for chapter, value in saved if chapter == 4)
    assert assessment['ai_status'] == 'success'
    assert assessment['exact_quotes'][0]['quote'] == row['excerpt']
    assert project['review_required_chapter'] == 4


def test_refresh_chapter_from_existing_reuses_quotes_without_model(monkeypatch):
    row = _row()
    project = _project()
    chapter = _chapter()
    record = {'fields': {'auto_extraction': {
        'managed': True,
        'ai_status': 'success',
        'origin_evidence_ids': ['e1'],
        'exact_quote': row['excerpt'],
    }}}

    monkeypatch.setattr(evidence_pre_review.database, 'project', lambda _pid: project)
    monkeypatch.setattr(
        evidence_pre_review.database, 'chapter', lambda _pid, _chapter_no: chapter,
    )
    monkeypatch.setattr(
        evidence_pre_review.database, 'decision_records', lambda _pid: [record],
    )
    monkeypatch.setattr(
        evidence_pre_review.database, 'review_evidence', lambda *_args: [row],
    )

    def save(_project_id, _chapter_no, assessments):
        row['metadata']['pre_review'] = assessments['e1']
        return 1

    monkeypatch.setattr(
        evidence_pre_review.database, 'save_evidence_pre_reviews', save,
    )
    monkeypatch.setattr(
        evidence_pre_review.llm,
        'complete',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('refreshing an existing index must not call the model')
        ),
    )

    result = evidence_pre_review.refresh_chapter_from_existing(
        'p1', 4, use_ai=True,
    )

    assert result['model_called'] is False
    assert result['rows'] == 1
    assert result['shared_exact_quotes'] == 1
    assert result['summary']['provider_review_gate'] is True
    assessment = evidence_review.current_pre_review(row)
    assert assessment['ai_status'] == 'success'
    assert assessment['exact_quotes'][0]['quote'] in row['excerpt']
