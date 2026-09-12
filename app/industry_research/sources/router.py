import logging

from .. import database
from ..search.base import SearchProviderError
from ..search.service import search_chapter
from .akshare_provider import AkshareProvider
from .requirements import requirements_for

logger = logging.getLogger(__name__)


async def collect_chapter(project_id: str, chapter_no: int, max_web_queries: int = 3, results_per_query: int = 8,
                          structured_provider=None, search_provider=None, progress=None):
    project = database.project(project_id)
    if not project:
        return None
    provider = structured_provider or AkshareProvider()
    logger.info('industry collection project=%s chapter=%s started', project_id, chapter_no)
    requirements = requirements_for(chapter_no, project['brief'])
    structured_saved, structured_failed = 0, []
    if progress:
        progress('structured', 3, '正在检查AKShare与本地缓存', 0, len(requirements), 0)
    for index, requirement in enumerate(requirements, 1):
        if progress:
            progress('structured', 5 + index * 5, f'AKShare：{requirement.label}', index - 1, len(requirements), structured_saved)
        cached = database.get_source_cache(provider.name, requirement.key, requirement.params)
        try:
            evidence = cached or await provider.fetch(requirement)
            if not cached:
                database.put_source_cache(provider.name, requirement.key, requirement.params, evidence)
            structured_saved += database.add_structured_evidence(project_id, chapter_no, requirement, evidence)
        except Exception as exc:
            structured_failed.append({'requirement': requirement.label, 'error': str(exc)})

    # Structured macro evidence reduces one broad web query, but never replaces policy/industry-specific research.
    reduction = 1 if structured_saved and chapter_no == 3 else 0
    web_budget = max(1, max_web_queries - reduction)
    try:
        def web_progress(done, total, query, found):
            percent = 25 + int(65 * done / max(total, 1))
            if progress:
                progress('web', percent, f'网页搜索 {done}/{total}：{query}', done, total, structured_saved + found)
        web = await search_chapter(project_id, chapter_no, web_budget, results_per_query,
                                   provider=search_provider, progress=web_progress)
        web_error = web.get('error')
        if web_error:
            logger.warning('industry collection project=%s chapter=%s retained=%s search interrupted: %s',
                           project_id, chapter_no, web.get('saved', 0), web_error)
    except SearchProviderError as exc:
        web = {'provider': '', 'queries_run': 0, 'found': 0, 'saved': 0}
        web_error = str(exc)
        logger.warning('industry collection project=%s chapter=%s web search failed: %s',
                       project_id, chapter_no, web_error)
    result = {
        'strategy': 'akshare_first_web_gap_fill', 'structured_saved': structured_saved,
        'structured_failed': structured_failed, 'web_query_budget': web_budget, 'web': web, 'web_error': web_error,
    }
    try:
        # Immediately prepare deterministic exact-quote previews.  This makes
        # newly collected numeric evidence visible in the review workbench
        # without a second model call or a separate user action.
        if progress:
            progress('pre_review', 94, '正在去重并逐字截取关键数字',
                     web.get('queries_run', 0), web_budget,
                     structured_saved + web.get('saved', 0))
        from ..evidence_pre_review import refresh_chapter_from_existing
        result['pre_review'] = refresh_chapter_from_existing(
            project_id, chapter_no, use_ai=False)
    except Exception:
        # Pre-review is a convenience index over immutable evidence.  Its
        # failure must not discard an otherwise successful collection.
        logger.exception(
            'industry collection project=%s chapter=%s pre-review indexing failed',
            project_id, chapter_no)
        result['pre_review'] = {'error': '自动摘录索引暂时未完成，原始资料已保留'}
    if progress:
        progress('complete', 100, ('网页搜索失败：' + web_error) if web_error else '资料采集完成', web.get('queries_run', 0), web_budget,
                 structured_saved + web.get('saved', 0))
    return result
