import json
import pytest

from app.industry_research import database, evidence_pre_review, router
from app.industry_research.evidence_review import BulkReviewRequest


def _row(evidence_id, excerpt, *, metadata=None):
    return {
        'id': evidence_id,
        'chapter_no': 4,
        'title': '食品饮料瓦楞纸箱资料',
        'publisher': '国家统计局',
        'published_at': '2025-01-01',
        'url': f'https://stats.gov.cn/{evidence_id}',
        'source_type': 'official_statistics',
        'provider': 'exa',
        'search_query': '瓦楞纸箱 市场规模',
        'score': 0.8,
        'excerpt': excerpt,
        'metadata': metadata or {},
    }


def _rows_with_current_triage():
    rows = [
        _row('recommended', '2024年市场规模为100亿元。'),
        _row('duplicate', '2024年市场规模为100亿元。'),
        _row('manual', '2024年平均价格为50元/吨...'),
        _row(
            'human',
            '2023年市场规模为90亿元。',
            metadata={'review': {'decision': 'approved', 'reason': '已人工核验'}},
        ),
        _row('empty', ''),
    ]
    project = {'id': 'p1', 'brief': {'topic': '食品饮料瓦楞纸箱'}}
    chapter = {
        'chapter_no': 4,
        'title': '下游需求与市场空间',
        'questions': ['市场规模多大'],
        'queries': ['瓦楞纸箱 市场规模'],
    }
    assessments = evidence_pre_review.program_assessments(project, chapter, rows)
    for row in rows:
        row['metadata']['pre_review'] = assessments[row['id']]
    assert assessments['recommended']['state'] == 'recommended_for_review'
    assert assessments['duplicate']['state'] == 'duplicate'
    assert assessments['manual']['state'] == 'manual_review'
    assert assessments['empty']['state'] == 'empty'
    return project, chapter, rows


def test_bulk_safe_routing_only_applies_allowlisted_suggestions(monkeypatch):
    project, chapter, rows = _rows_with_current_triage()
    captured = {}

    monkeypatch.setattr(router.writer, 'is_running', lambda _pid: False)
    monkeypatch.setattr(router.database, 'project', lambda _pid: project)
    monkeypatch.setattr(router.database, 'chapter', lambda *_args: chapter)
    monkeypatch.setattr(router.database, 'review_evidence', lambda *_args: rows)
    monkeypatch.setattr(
        router.evidence_pre_review,
        'refresh_chapter_from_existing',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('current pre-review rows must not be refreshed')
        ),
    )

    def save(_project_id, _chapter_no, decisions):
        captured.update(decisions)
        for row in rows:
            if row['id'] in decisions:
                row['metadata']['review'] = decisions[row['id']]
        return len(decisions)

    monkeypatch.setattr(router.database, 'save_evidence_reviews_bulk', save)
    monkeypatch.setattr(
        router.database, 'clear_review_requirement_if_complete', lambda *_args: False,
    )

    result = router.apply_evidence_review_suggestions(
        'p1', 4, BulkReviewRequest(confirm='apply_safe_suggestions'),
    )

    assert set(captured) == {'recommended', 'duplicate', 'empty'}
    assert captured['recommended']['decision'] == 'approved'
    assert captured['duplicate']['decision'] == 'excluded'
    assert captured['empty']['decision'] == 'excluded'
    assert 'manual' not in captured
    assert 'human' not in captured
    assert result == {
        'saved': 3,
        'retained': 1,
        'excluded': 2,
        'manual_remaining': 1,
        'pending_remaining': 1,
        'review_complete': False,
        'fact_verification': False,
    }


@pytest.mark.parametrize(('confirm', 'expected_decision'), [
    ('approve_all_pending', 'approved'),
    ('exclude_all_pending', 'excluded'),
])
def test_one_click_review_handles_every_pending_row_without_typed_reasons(
        monkeypatch, confirm, expected_decision):
    project, chapter, rows = _rows_with_current_triage()
    captured = {}
    monkeypatch.setattr(router.writer, 'is_running', lambda _pid: False)
    monkeypatch.setattr(router.database, 'project', lambda _pid: project)
    monkeypatch.setattr(router.database, 'chapter', lambda *_args: chapter)
    monkeypatch.setattr(router.database, 'review_evidence', lambda *_args: rows)

    def save(_project_id, _chapter_no, decisions):
        captured.update(decisions)
        for row in rows:
            if row['id'] in decisions:
                row['metadata']['review'] = decisions[row['id']]
        return len(decisions)

    monkeypatch.setattr(router.database, 'save_evidence_reviews_bulk', save)
    monkeypatch.setattr(router.database, 'clear_review_requirement_if_complete', lambda *_args: False)
    monkeypatch.setattr(router.database, 'evidence_review_state', lambda *_args: {
        'total': 5, 'pending': 0, 'approved': 4 if expected_decision == 'approved' else 1,
        'complete': True,
    })

    result = router.apply_evidence_review_suggestions(
        'p1', 4, BulkReviewRequest(confirm=confirm))

    assert set(captured) == {'recommended', 'duplicate', 'manual', 'empty'}
    assert all(len(item['reason']) >= 2 for item in captured.values())
    if expected_decision == 'approved':
        assert captured['recommended']['decision'] == 'approved'
        assert captured['empty']['decision'] == 'excluded'
    else:
        assert {item['decision'] for item in captured.values()} == {'excluded'}
    assert result['pending_remaining'] == 0
    assert result['review_complete'] is True


class _UpdateResult:
    rowcount = 1


class _BulkReviewDB:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, params=()):
        self.calls.append((' '.join(statement.split()), params))
        return _UpdateResult()


def test_bulk_review_database_uses_one_snapshot_and_scoped_review_updates(monkeypatch):
    fake = _BulkReviewDB()
    snapshots = []
    decisions = {
        'keep': {'decision': 'approved', 'reason': '保留逐字摘录'},
        'drop': {'decision': 'excluded', 'reason': '完全重复'},
    }
    monkeypatch.setattr(database, 'connect', lambda: fake)
    monkeypatch.setattr(
        database,
        'snapshot_version',
        lambda db, project_id, reason: snapshots.append((db, project_id, reason)),
    )

    saved = database.save_evidence_reviews_bulk('p1', 4, decisions)

    assert saved == 2
    assert snapshots == [(fake, 'p1', '资料批量审核前自动备份')]
    assert len(fake.calls) == 2
    for (statement, params), evidence_id in zip(fake.calls, decisions):
        assert "'{review}'" in statement
        assert 'pre_review' not in statement
        assert json.loads(params[0]) == decisions[evidence_id]
        assert params[1:] == ('p1', 4, evidence_id)
