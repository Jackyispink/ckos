import asyncio

import pytest
from fastapi import HTTPException

from app.industry_research import router


def test_auto_extract_uses_defaults_without_body(monkeypatch):
    calls = []
    calculation_calls = []

    async def extract(project_id, *, use_ai, force):
        calls.append((project_id, use_ai, force))
        return {'created': 2, 'candidates': 2}

    monkeypatch.setattr(router.database, 'project', lambda project_id: {'id': project_id})
    monkeypatch.setattr(router.writer, 'is_running', lambda project_id: False)
    monkeypatch.setattr(router.decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(
        router.decision_auto_calculation,
        'calculate_project',
        lambda project_id: calculation_calls.append(project_id) or {
            'computed': 1, 'reused': 0, 'calculations': 1,
            'blocked': 0, 'gap_count': 2, 'gaps': {},
        },
    )

    result = asyncio.run(router.auto_extract_decision_records('project-1'))

    assert result == {
        'created': 2,
        'candidates': 2,
        'calculation': {
            'computed': 1, 'reused': 0, 'calculations': 1,
            'blocked': 0, 'gap_count': 2, 'gaps': {},
        },
    }
    assert calls == [('project-1', True, False)]
    assert calculation_calls == ['project-1']


def test_auto_extract_forwards_options(monkeypatch):
    calls = []

    async def extract(project_id, *, use_ai, force):
        calls.append((project_id, use_ai, force))
        return {'created': 0}

    monkeypatch.setattr(router.database, 'project', lambda project_id: {'id': project_id})
    monkeypatch.setattr(router.writer, 'is_running', lambda project_id: False)
    monkeypatch.setattr(router.decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(
        router.decision_auto_calculation,
        'calculate_project',
        lambda _project_id: {'computed': 0, 'gap_count': 4},
    )

    body = router.DecisionAutoExtractRequest(use_ai=False, force=True)
    asyncio.run(router.auto_extract_decision_records('project-2', body))

    assert calls == [('project-2', False, True)]


def test_auto_extract_keeps_result_when_calculation_fails(monkeypatch):
    async def extract(*args, **kwargs):
        return {'created': 2, 'candidates': 2}

    def calculate(_project_id):
        raise RuntimeError('temporary calculation failure')

    monkeypatch.setattr(router.database, 'project', lambda project_id: {'id': project_id})
    monkeypatch.setattr(router.writer, 'is_running', lambda project_id: False)
    monkeypatch.setattr(router.decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(router.decision_auto_calculation, 'calculate_project', calculate)

    result = asyncio.run(router.auto_extract_decision_records('project-3'))

    assert result['created'] == 2
    assert result['calculation']['error'] == 'temporary calculation failure'


@pytest.mark.parametrize(
    ('exists', 'running', 'expected_status'),
    [(False, False, 404), (True, True, 409)],
)
def test_auto_extract_rejects_missing_or_running_project(
        monkeypatch, exists, running, expected_status):
    monkeypatch.setattr(router.database, 'project', lambda project_id: {'id': project_id} if exists else None)
    monkeypatch.setattr(router.writer, 'is_running', lambda project_id: running)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.auto_extract_decision_records('project-3'))

    assert exc.value.status_code == expected_status
