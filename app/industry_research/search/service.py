import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .. import database
from .base import SearchProvider, SearchProviderError, SearchRequest, SearchResult
from .factory import get_provider


_FATAL_PROVIDER_ERROR_MARKERS = (
    '请先在 .env 中配置 exa_api_key',
    'exa 鉴权失败',
    'exa 账户余额不足',
    'http 401',
    'http 402',
    'http 403',
)


def _must_stop_after_provider_error(exc: SearchProviderError):
    """Stop only for errors where more queries cannot safely or usefully succeed."""
    message = str(exc).strip().lower()
    return any(marker in message for marker in _FATAL_PROVIDER_ERROR_MARKERS)


def _safe_provider_error(exc: SearchProviderError, provider: SearchProvider):
    """Keep actionable diagnostics while ensuring credentials never enter job state/logs."""
    message = str(exc).strip() or '搜索服务返回未知错误。'
    api_key = getattr(provider, 'api_key', '')
    if isinstance(api_key, str) and len(api_key.strip()) >= 4:
        message = message.replace(api_key.strip(), '[REDACTED]')
    message = re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1[REDACTED]', message)
    message = re.sub(
        r'(?i)((?:exa[_ -]?api[_ -]?key|api[_ -]?key|authorization)\s*[:=]\s*)[^\s,;]+',
        r'\1[REDACTED]', message)
    return message[:600]


def _search_error_summary(succeeded: int, failed: int, errors: list[str], stopped_early: bool):
    if failed <= 0:
        return None
    outcome = '全部查询失败' if succeeded == 0 else '部分查询失败，成功结果已逐批保存'
    stop = '；遇到鉴权、余额或配置错误后已停止后续查询' if stopped_early else ''
    unique_errors = list(dict.fromkeys(errors))
    detail = '；'.join(unique_errors[:2]) or '搜索服务未返回错误详情。'
    return (f'网页搜索执行{succeeded + failed}个查询：成功{succeeded}个，失败{failed}个；'
            f'{outcome}{stop}。失败详情：{detail}')


def canonical_url(url: str):
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(('utm_', 'spm', 'ref'))])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix('www.'), parts.path.rstrip('/'), query, ''))


async def search_chapter(project_id: str, chapter_no: int, max_queries: int = 3, results_per_query: int = 8,
                         provider: SearchProvider | None = None, progress=None):
    chapter = database.chapter(project_id, chapter_no)
    if not chapter:
        raise SearchProviderError('行业研究项目或章节不存在。')
    provider = provider or get_provider()
    # A source can support multiple chapters. Deduplicate within this chapter only.
    existing = database.all_evidence(project_id)
    seen = {canonical_url(e['url']) for e in existing if e['chapter_no'] == chapter_no and e.get('url')}
    completed_queries = {e.get('search_query') for e in existing
                         if e['chapter_no'] == chapter_no and e.get('excerpt', '').strip()
                         and e.get('provider') == provider.name}
    collected: list[tuple[str, SearchResult]] = []
    saved, queries_run = 0, 0
    queries_succeeded, queries_failed, queries_skipped = 0, 0, 0
    errors: list[str] = []
    stopped_early = False
    queries = chapter['queries'][:max_queries]
    for index, query in enumerate(queries, 1):
        if query in completed_queries:
            queries_skipped += 1
            continue
        if progress:
            progress(index - 1, len(queries), query, len(collected))
        request = SearchRequest(query=query, limit=results_per_query, summary_query='提取与该行业研究问题直接相关的事实、数字、日期、地区、统计口径和因果关系。')
        queries_run += 1
        try:
            results = await provider.search(request)
        except SearchProviderError as exc:
            queries_failed += 1
            errors.append(_safe_provider_error(exc, provider))
            if progress:
                progress(index, len(queries), query, len(collected))
            if _must_stop_after_provider_error(exc):
                stopped_early = True
                break
            # The provider already applied its tightly bounded request retry policy.
            # Continue with a *different* query; never replay this query here.
            continue
        queries_succeeded += 1
        batch = []
        for result in results:
            key = canonical_url(result.url)
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append((query, result))
            batch.append((query, result))
        # Commit each successful query before the next network call can fail.
        saved += database.add_search_results(project_id, chapter_no, batch)
        if progress:
            progress(index, len(queries), query, len(collected))
    error = _search_error_summary(queries_succeeded, queries_failed, errors, stopped_early)
    return {
        'provider': provider.name,
        'queries_run': queries_run,
        'queries_succeeded': queries_succeeded,
        'queries_failed': queries_failed,
        'queries_skipped': queries_skipped,
        'found': len(collected),
        'saved': saved,
        'partial': queries_failed > 0,
        'all_failed': queries_failed > 0 and queries_succeeded == 0,
        'stopped_early': stopped_early,
        'error': error,
    }
