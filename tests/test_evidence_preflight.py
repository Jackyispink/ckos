import pytest
from app.industry_research import writer, database, sources


def setup(monkeypatch, found):
    monkeypatch.setattr(database, 'all_evidence', lambda _: found)
    monkeypatch.setattr(writer, '_check_cancel', lambda _: None)
    monkeypatch.setattr(writer, '_update', lambda *a, **kw: None)


def test_collect_missing_and_reuse(monkeypatch):
    found = [{'chapter_no': 1, 'excerpt': '已有证据'}]
    setup(monkeypatch, found)
    calls = []
    async def collect(pid, number, **kwargs):
        calls.append(number)
        found.append({'chapter_no': number, 'excerpt': '新证据'})
    monkeypatch.setattr(sources, 'collect_chapter', collect)
    writer._prepare_evidence('p', [{'chapter_no': n, 'status': 'planned'} for n in [1, 2]], 'resume')
    assert calls == [2]


def test_empty_collection_stops(monkeypatch):
    setup(monkeypatch, [])
    async def collect(*a, **kw):
        return {}
    monkeypatch.setattr(sources, 'collect_chapter', collect)
    with pytest.raises(ValueError, match='仍无可用证据'):
        writer._prepare_evidence('p', [{'chapter_no': 1, 'status': 'planned'}], 'resume')


def test_old_empty_report_requires_regenerate(monkeypatch):
    setup(monkeypatch, [])
    with pytest.raises(ValueError, match='请点击重新生成'):
        writer._prepare_evidence('p', [{'chapter_no': 1, 'status': 'complete', 'content': '旧正文'}], 'resume')


def test_search_error_is_preserved(monkeypatch):
    setup(monkeypatch, [])
    async def collect(*args, **kwargs):
        return {'web_error': 'Exa 搜索超时，请稍后重试。'}
    monkeypatch.setattr(sources, 'collect_chapter', collect)
    with pytest.raises(ValueError, match='Exa 搜索超时'):
        writer._prepare_evidence('p', [{'chapter_no': 1, 'status': 'planned'}], 'resume')


def test_database_evidence_contract_includes_excerpt(monkeypatch):
    # Exercise the actual database helper, not a mocked all_evidence response.
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params):
            selected = sql.lower().split('from industry_evidence')[0]
            assert 'excerpt' in selected
            compact = ' '.join(sql.lower().split())
            assert 'order by chapter_no,score desc nulls last,created,id' in compact
            assert params == ('p',)
            return [{'chapter_no': 1, 'excerpt': '已入库正文'}]
    monkeypatch.setattr(database, 'connect', Connection)
    monkeypatch.setattr(writer, '_check_cancel', lambda _: None)
    async def forbidden(*args, **kwargs):
        pytest.fail('已有正文不得再次搜索')
    monkeypatch.setattr(sources, 'collect_chapter', forbidden)
    writer._prepare_evidence('p', [{'chapter_no': 1, 'status': 'planned'}], 'resume')


def test_writer_chapter_evidence_uses_stable_database_order():
    class DB:
        def execute(self, sql, params):
            compact = ' '.join(sql.lower().split())
            assert 'order by score desc nulls last,created,id' in compact
            assert params == ('project', 3)
            return [{'id': 'a'}, {'id': 'b'}]

    assert [row['id'] for row in writer._ordered_chapter_evidence(DB(), 'project', 3)] == ['a', 'b']
