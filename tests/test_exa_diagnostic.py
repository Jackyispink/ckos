import httpx
import asyncio
import json
import pytest
from app.industry_research.search import exa
from app.industry_research.search.exa import connection_diagnostic
from app.industry_research.search.exa import ExaSearchProvider
from app.industry_research.search.base import SearchRequest, SearchProviderError


def test_diagnostic_omits_sensitive_messages():
    error = httpx.ConnectError('https://secret.invalid/?api_key=private')
    error.__cause__ = OSError(10054, 'private credential')
    detail = connection_diagnostic(error)
    assert 'ConnectError' in detail
    assert '10054' in detail
    assert 'private' not in detail
    assert 'secret' not in detail


def test_diagnostic_handles_cycle():
    error = httpx.ConnectError('private')
    error.__cause__ = error
    assert connection_diagnostic(error) == 'ConnectError'


def test_minimal_request_and_highlights(monkeypatch):
    monkeypatch.delenv('EXA_INCLUDE_SUMMARY', raising=False)
    def handler(request):
        payload = json.loads(request.content)
        assert request.method == 'POST'
        assert request.headers['x-api-key'] == 'test-key'
        assert payload['numResults'] == 1
        assert payload['contents'] == {'highlights': {'maxCharacters': 1800}}
        return httpx.Response(200, json={'results': [{'url': 'https://example.org', 'highlights': ['证据原文']} ]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器', limit=1))
            assert result[0].text == '证据原文'
    asyncio.run(run())


def test_disconnect_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setenv('EXA_RETRY_BASE_DELAY_SECONDS', '0')
    monkeypatch.setenv('EXA_RETRY_JITTER_SECONDS', '0')
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError('Server disconnected without sending a response.')
        return httpx.Response(200, json={
            'results': [{'url': 'https://example.org/recovered', 'highlights': ['恢复后的证据']}],
        })
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    result = asyncio.run(run())
    assert len(calls) == 2
    assert result[0].text == '恢复后的证据'


def test_persistent_disconnect_stops_after_one_retry(monkeypatch):
    # Even an unsafe local setting cannot exceed the hard cost-control cap.
    monkeypatch.setenv('EXA_TRANSPORT_MAX_RETRIES', '99')
    monkeypatch.setenv('EXA_RETRY_BASE_DELAY_SECONDS', '0')
    monkeypatch.setenv('EXA_RETRY_JITTER_SECONDS', '0')
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.RemoteProtocolError('Server disconnected without sending a response.')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SearchProviderError, match='已尝试2次.*重复计费'):
                await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert len(calls) == 2


def test_transport_retry_can_be_disabled(monkeypatch):
    monkeypatch.setenv('EXA_TRANSPORT_MAX_RETRIES', '0')
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.ConnectError('connection reset')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SearchProviderError, match='已尝试1次.*重试已通过.*禁用'):
                await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert len(calls) == 1


def test_transport_retry_is_hard_capped_at_one(monkeypatch):
    monkeypatch.setenv('EXA_TRANSPORT_MAX_RETRIES', '99')
    monkeypatch.setenv('EXA_RETRY_BASE_DELAY_SECONDS', '0')
    monkeypatch.setenv('EXA_RETRY_JITTER_SECONDS', '0')
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.ConnectError('connection reset')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SearchProviderError, match='已尝试2次'):
                await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert len(calls) == 2


def test_retry_uses_configured_backoff_and_jitter(monkeypatch):
    monkeypatch.setenv('EXA_RETRY_BASE_DELAY_SECONDS', '0.2')
    monkeypatch.setenv('EXA_RETRY_JITTER_SECONDS', '0.1')
    monkeypatch.setattr(exa.random, 'uniform', lambda lower, upper: 0.05)
    delays = []
    async def fake_sleep(delay):
        delays.append(delay)
    monkeypatch.setattr(exa.asyncio, 'sleep', fake_sleep)
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout('read timed out')
        return httpx.Response(200, json={'results': []})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert delays == pytest.approx([0.25])
    assert len(calls) == 2


@pytest.mark.parametrize('status', [400, 401, 402, 403, 429, 500])
def test_http_errors_are_never_retried(status):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={'error': 'do not retry'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SearchProviderError, match='已尝试1次.*不属于传输重试范围'):
                await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert len(calls) == 1


def test_local_protocol_error_is_not_retried():
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.LocalProtocolError('invalid local request')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SearchProviderError, match='已尝试1次.*不属于可重试'):
                await ExaSearchProvider(api_key='test-key', client=client).search(SearchRequest('减速器'))
    asyncio.run(run())
    assert len(calls) == 1
