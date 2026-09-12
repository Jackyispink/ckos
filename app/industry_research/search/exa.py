import asyncio
import math
import os
import random
import ssl
from urllib.parse import urlparse

import httpx

from .base import SearchProvider, SearchProviderError, SearchRequest, SearchResult


_MAX_TRANSPORT_RETRIES = 1
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.25
_DEFAULT_RETRY_JITTER_SECONDS = 0.10
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)


def _bounded_env_number(name, default, lower, upper):
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return max(lower, min(value, upper))


def _retry_settings():
    raw_retries = os.getenv('EXA_TRANSPORT_MAX_RETRIES', '').strip().lower()
    if raw_retries in ('false', 'no', 'off'):
        retries = 0
    else:
        try:
            retries = int(raw_retries) if raw_retries else _MAX_TRANSPORT_RETRIES
        except ValueError:
            retries = _MAX_TRANSPORT_RETRIES
    # A transport failure can happen after the remote service accepted the request.
    # Never allow configuration to exceed one potentially billable replay.
    retries = max(0, min(retries, _MAX_TRANSPORT_RETRIES))
    base_delay = _bounded_env_number(
        'EXA_RETRY_BASE_DELAY_SECONDS', _DEFAULT_RETRY_BASE_DELAY_SECONDS, 0.0, 5.0)
    jitter = _bounded_env_number(
        'EXA_RETRY_JITTER_SECONDS', _DEFAULT_RETRY_JITTER_SECONDS, 0.0, 2.0)
    return retries, base_delay, jitter


def _is_retryable_transport_error(exc):
    return isinstance(exc, _RETRYABLE_TRANSPORT_ERRORS)


def _attempt_detail(attempts, max_attempts, retryable):
    if attempts > 1:
        return (f'请求已尝试{attempts}次（含{attempts - 1}次有限重试）仍失败；'
                '为控制潜在的重复计费，未继续重试。')
    if retryable and max_attempts == 1:
        return ('请求已尝试1次；传输重试已通过 '
                'EXA_TRANSPORT_MAX_RETRIES=0 禁用。')
    return '请求已尝试1次；该错误不属于可重试的瞬态传输错误，未重试。'


def _transport_error_message(exc, attempts, max_attempts):
    retryable = _is_retryable_transport_error(exc)
    attempt_detail = _attempt_detail(attempts, max_attempts, retryable)
    diagnostic = connection_diagnostic(exc)
    if isinstance(exc, httpx.TimeoutException):
        return f'Exa 搜索超时。{attempt_detail}请稍后重试。连接诊断：{diagnostic}'
    if isinstance(exc, httpx.RemoteProtocolError):
        return ('Exa连接被对端或中间网络设备中断，未收到完整HTTP响应；'
                f'这不是已确认的密钥或余额错误。{attempt_detail}连接诊断：{diagnostic}')
    return (f'无法连接 Exa，请检查网络和 EXA_SEARCH_URL。{attempt_detail}'
            f'连接诊断：{diagnostic}')


def _response_attempt_detail(attempts):
    return f'请求已尝试{attempts}次；已收到HTTP响应，不属于传输重试范围。'


def connection_diagnostic(exc):
    """Only class names and numeric OS codes; never URLs, headers or raw messages."""
    parts, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen and len(parts) < 6:
        seen.add(id(current))
        label = type(current).__name__
        if isinstance(current, httpx.RemoteProtocolError) and 'disconnected without sending a response' in str(current).lower():
            label += '（对端未返回HTTP响应便断开）'
        for attr in ('errno', 'winerror'):
            code = getattr(current, attr, None)
            if isinstance(code, int):
                label += f' {attr}={code}'
        if isinstance(current, ssl.SSLCertVerificationError):
            label += '（TLS证书验证失败）'
        parts.append(label)
        current = current.__cause__ or current.__context__
    return ' → '.join(parts)


class ExaSearchProvider(SearchProvider):
    name = 'exa'

    @classmethod
    def configured(cls) -> bool:
        return bool(os.getenv('EXA_API_KEY', '').strip())

    def __init__(self, api_key: str | None = None, url: str | None = None, client: httpx.AsyncClient | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv('EXA_API_KEY', '')).strip()
        self.url = (url or os.getenv('EXA_SEARCH_URL', '') or 'https://api.exa.ai/search').strip()
        self.client = client

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.api_key:
            raise SearchProviderError('请先在 .env 中配置 EXA_API_KEY。')
        if not request.query.strip():
            raise SearchProviderError('搜索词不能为空。')
        payload = {
            'query': request.query.strip(),
            'type': 'auto',
            'numResults': max(1, min(request.limit, 25)),
            'contents': {
                'highlights': {'maxCharacters': 1800},
            },
        }
        # Use the documented default crawl fallback, not the deprecated livecrawl parameter.
        # Summaries are optional: highlights already provide extractive evidence.
        if os.getenv('EXA_INCLUDE_SUMMARY', '').strip().lower() in ('1', 'true', 'yes'):
            payload['contents']['summary'] = {'query': request.summary_query or '提取与研究问题相关的事实及统计口径。'}
        if request.include_domains:
            payload['includeDomains'] = list(request.include_domains)
        if request.exclude_domains:
            payload['excludeDomains'] = list(request.exclude_domains)
        if request.start_published_date:
            payload['startPublishedDate'] = request.start_published_date
        if request.end_published_date:
            payload['endPublishedDate'] = request.end_published_date
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10))
        retries, base_delay, jitter = _retry_settings()
        max_attempts = 1 + retries
        attempt = 0
        try:
            while True:
                attempt += 1
                try:
                    response = await client.post(
                        self.url,
                        headers={'x-api-key': self.api_key, 'Content-Type': 'application/json'},
                        json=payload,
                    )
                    break
                except httpx.RequestError as exc:
                    if _is_retryable_transport_error(exc) and attempt < max_attempts:
                        delay = min(5.0, base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, jitter))
                        if delay:
                            await asyncio.sleep(delay)
                        continue
                    raise SearchProviderError(
                        _transport_error_message(exc, attempt, max_attempts)) from None
        finally:
            if own_client:
                await client.aclose()
        response_attempt_detail = _response_attempt_detail(attempt)
        if response.status_code in (401, 403):
            raise SearchProviderError(f'Exa 鉴权失败，请检查 EXA_API_KEY。{response_attempt_detail}')
        if response.status_code == 402:
            raise SearchProviderError(f'Exa 账户余额不足或当前功能不可用。{response_attempt_detail}')
        if response.status_code == 429:
            raise SearchProviderError(f'Exa 调用频率已达上限，请稍后重试。{response_attempt_detail}')
        if response.is_error:
            raise SearchProviderError(f'Exa 搜索失败（HTTP {response.status_code}）。{response_attempt_detail}')
        try:
            items = response.json().get('results', [])
        except (ValueError, AttributeError):
            raise SearchProviderError(f'Exa 返回了无法解析的结果。{response_attempt_detail}') from None
        results = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get('url'):
                continue
            highlights = tuple(x.strip() for x in item.get('highlights', []) if isinstance(x, str) and x.strip())
            summary = item.get('summary') if isinstance(item.get('summary'), str) else ''
            text = summary.strip() or '\n'.join(highlights).strip()
            if not text and isinstance(item.get('text'), str):
                text = item['text'].strip()[:2500]
            if not text:
                continue
            host = urlparse(item['url']).netloc.removeprefix('www.')
            results.append(SearchResult(
                title=str(item.get('title') or host or item['url'])[:300], url=item['url'], text=text[:3500],
                published_at=str(item.get('publishedDate') or '')[:40], publisher=str(item.get('author') or host)[:200],
                highlights=highlights, score=_score(item), provider=self.name,
                provider_result_id=str(item.get('id') or '')[:500], metadata={'image': item.get('image'), 'favicon': item.get('favicon')},
            ))
        return results


def _score(item):
    scores = item.get('highlightScores')
    if isinstance(scores, list) and scores:
        valid = [float(x) for x in scores if isinstance(x, (int, float))]
        return max(valid) if valid else None
    return item.get('score') if isinstance(item.get('score'), (int, float)) else None
