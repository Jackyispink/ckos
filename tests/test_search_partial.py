import asyncio
from app.industry_research.search import service
from app.industry_research.search.base import SearchResult, SearchProviderError


def test_success_is_saved_before_disconnect_and_resumed(monkeypatch):
    rows = []
    monkeypatch.setattr(service.database, 'chapter', lambda *a: {'queries': ['one', 'two']})
    monkeypatch.setattr(service.database, 'all_evidence', lambda *a: rows)
    def save(pid, chapter, batch):
        rows.extend(dict(chapter_no=chapter, url=r.url, excerpt=r.text,
                         provider='fake', search_query=q) for q, r in batch)
        return len(batch)
    monkeypatch.setattr(service.database, 'add_search_results', save)
    class Provider:
        name = 'fake'
        calls = []
        async def search(self, request):
            self.calls.append(request.query)
            if request.query == 'two':
                assert len(rows) == 1
                raise SearchProviderError('disconnect')
            return [SearchResult('title', 'https://example.org', 'text')]
    provider = Provider()
    result = asyncio.run(service.search_chapter('p', 10, provider=provider))
    assert result['saved'] == 1 and result['partial']
    assert result['queries_succeeded'] == 1
    assert result['queries_failed'] == 1
    asyncio.run(service.search_chapter('p', 10, provider=provider))
    assert provider.calls == ['one', 'two', 'two']


def test_middle_query_failure_does_not_stop_later_queries_and_redacts_key(monkeypatch):
    rows = []
    batches = []
    monkeypatch.setattr(service.database, 'chapter', lambda *a: {'queries': ['one', 'two', 'three']})
    monkeypatch.setattr(service.database, 'all_evidence', lambda *a: rows)

    def save(pid, chapter, batch):
        batches.append([query for query, _ in batch])
        rows.extend(dict(chapter_no=chapter, url=result.url, excerpt=result.text,
                         provider='fake', search_query=query) for query, result in batch)
        return len(batch)

    monkeypatch.setattr(service.database, 'add_search_results', save)

    class Provider:
        name = 'fake'
        api_key = 'exa-super-secret-key'
        calls = []

        async def search(self, request):
            self.calls.append(request.query)
            if request.query == 'two':
                raise SearchProviderError(f'disconnect using {self.api_key}')
            return [SearchResult(request.query, f'https://example.org/{request.query}', 'text')]

    provider = Provider()
    result = asyncio.run(service.search_chapter('p', 4, provider=provider))

    assert provider.calls == ['one', 'two', 'three']
    assert batches == [['one'], ['three']]
    assert result['saved'] == result['found'] == 2
    assert result['queries_run'] == 3
    assert result['queries_succeeded'] == 2
    assert result['queries_failed'] == 1
    assert result['partial'] is True
    assert result['all_failed'] is False
    assert '成功2个，失败1个' in result['error']
    assert provider.api_key not in result['error']
    assert '[REDACTED]' in result['error']


def test_all_query_failures_return_clear_partial_error(monkeypatch):
    monkeypatch.setattr(service.database, 'chapter', lambda *a: {'queries': ['one', 'two', 'three']})
    monkeypatch.setattr(service.database, 'all_evidence', lambda *a: [])
    monkeypatch.setattr(service.database, 'add_search_results', lambda *a: 0)

    class Provider:
        name = 'fake'
        calls = []

        async def search(self, request):
            self.calls.append(request.query)
            raise SearchProviderError('temporary disconnect')

    provider = Provider()
    result = asyncio.run(service.search_chapter('p', 4, provider=provider))

    assert provider.calls == ['one', 'two', 'three']
    assert result['queries_run'] == 3
    assert result['queries_succeeded'] == 0
    assert result['queries_failed'] == 3
    assert result['saved'] == result['found'] == 0
    assert result['partial'] is True
    assert result['all_failed'] is True
    assert result['stopped_early'] is False
    assert '成功0个，失败3个' in result['error']
    assert '全部查询失败' in result['error']


def test_auth_error_stops_remaining_queries_without_replay(monkeypatch):
    monkeypatch.setattr(service.database, 'chapter', lambda *a: {'queries': ['one', 'two', 'three']})
    monkeypatch.setattr(service.database, 'all_evidence', lambda *a: [])
    monkeypatch.setattr(service.database, 'add_search_results', lambda p, c, batch: len(batch))

    class Provider:
        name = 'fake'
        calls = []

        async def search(self, request):
            self.calls.append(request.query)
            if request.query == 'two':
                raise SearchProviderError('Exa 鉴权失败，请检查 EXA_API_KEY。请求已尝试1次。')
            return [SearchResult(request.query, f'https://example.org/{request.query}', 'text')]

    provider = Provider()
    result = asyncio.run(service.search_chapter('p', 4, provider=provider))

    assert provider.calls == ['one', 'two']
    assert result['queries_succeeded'] == 1
    assert result['queries_failed'] == 1
    assert result['stopped_early'] is True
    assert '遇到鉴权、余额或配置错误后已停止后续查询' in result['error']


def test_source_can_support_other_chapter(monkeypatch):
    monkeypatch.setattr(service.database, 'chapter', lambda *a: {'queries': ['q']})
    monkeypatch.setattr(service.database, 'all_evidence', lambda *a: [dict(chapter_no=1, url='https://example.org')])
    monkeypatch.setattr(service.database, 'add_search_results', lambda p, c, batch: len(batch))
    class Provider:
        name = 'fake'
        async def search(self, request):
            return [SearchResult('title', 'https://example.org', 'chapter 10 text')]
    result = asyncio.run(service.search_chapter('p', 10, provider=Provider()))
    assert result['saved'] == 1
