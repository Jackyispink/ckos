import asyncio
import importlib

from app.industry_research import evidence_pre_review


source_router = importlib.import_module('app.industry_research.sources.router')


def _arrange_collection(monkeypatch, web_result):
    monkeypatch.setattr(
        source_router.database,
        'project',
        lambda _project_id: {'id': 'p1', 'brief': {'geography': '中国'}},
    )
    monkeypatch.setattr(source_router, 'requirements_for', lambda *_args: [])

    async def search(*_args, **_kwargs):
        return dict(web_result)

    monkeypatch.setattr(source_router, 'search_chapter', search)


def test_collect_chapter_triggers_program_only_chapter_pre_review(monkeypatch):
    _arrange_collection(
        monkeypatch,
        {'provider': 'exa', 'queries_run': 2, 'found': 3, 'saved': 3},
    )
    calls = []

    def refresh(project_id, chapter_no, *, use_ai):
        calls.append((project_id, chapter_no, use_ai))
        return {'rows': 3, 'shared_exact_quotes': 0, 'model_called': False}

    monkeypatch.setattr(
        evidence_pre_review, 'refresh_chapter_from_existing', refresh,
    )

    result = asyncio.run(source_router.collect_chapter('p1', 4))

    assert calls == [('p1', 4, False)]
    assert result['web']['saved'] == 3
    assert result['pre_review'] == {
        'rows': 3,
        'shared_exact_quotes': 0,
        'model_called': False,
    }


def test_pre_review_failure_never_discards_successful_collection(monkeypatch):
    _arrange_collection(
        monkeypatch,
        {'provider': 'exa', 'queries_run': 1, 'found': 2, 'saved': 2},
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError('index unavailable')

    monkeypatch.setattr(
        evidence_pre_review, 'refresh_chapter_from_existing', fail,
    )

    result = asyncio.run(source_router.collect_chapter('p1', 5))

    assert result['web']['saved'] == 2
    assert result['web_error'] is None
    assert result['pre_review'] == {
        'error': '自动摘录索引暂时未完成，原始资料已保留',
    }
