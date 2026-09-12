"""Transparent heuristic evidence grades used in report prompts.

Grades help triage sources; they do not verify statistical scope or truth.
"""
from hashlib import sha1
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_D_HOSTS = ('book118.com', 'renrendoc.com', 'docin.com', 'wenku.baidu.com')
_A_HOSTS = ('stats.gov.cn', 'customs.gov.cn', 'gov.cn', 'cninfo.com.cn',
            'sse.com.cn', 'szse.cn', 'samr.gov.cn')
_B_HINTS = ('证券', '研究院', '咨询', '大学', '学报', '协会', '研究所')


def _is_host(host, domain):
    return host == domain or host.endswith('.' + domain)


def canonical_url(url):
    """Drop tracking parameters so repost/click variants share one origin key."""
    try:
        parts = urlsplit((url or '').strip())
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query)
                           if not k.lower().startswith(('utm_', 'spm', 'from'))])
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                           parts.path.rstrip('/'), query, ''))
    except ValueError:
        return (url or '').strip()


def classify(item):
    """Return grade, rationale and a stable original-source grouping key."""
    url = canonical_url(item.get('url') or '')
    host = urlsplit(url).netloc.lower()
    publisher = (item.get('publisher') or '').strip()
    source_type = (item.get('source_type') or '').lower()
    if any(_is_host(host, x) for x in _D_HOSTS):
        grade, why = 'D', '文库或二次资料，仅作为线索'
    elif any(_is_host(host, x) for x in _A_HOSTS) or source_type in {'annual_report', 'official_statistics', 'standard'}:
        grade, why = 'A', '政府、交易所、法定披露或标准来源'
    elif any(x in publisher for x in _B_HINTS) or source_type in {'research_report', 'academic'}:
        grade, why = 'B', '专业研究、协会或学术来源'
    elif publisher or host:
        grade, why = 'C', '企业、行业媒体或其他网页来源'
    else:
        grade, why = 'D', '来源身份不完整，仅作为线索'
    raw_key = url or f"{publisher}|{item.get('title') or ''}"
    return {'grade': grade, 'reason': why,
            'origin_key': sha1(raw_key.encode('utf-8')).hexdigest()[:10]}


def audit(items):
    """Summarise source types and independent A/B origin groups.

    This is a triage signal only: two sources can still repeat the same
    underlying dataset, so statistical scope remains a human review task.
    """
    counts = {grade: 0 for grade in 'ABCD'}
    origins, ab_origins = set(), set()
    for item in items:
        meta = classify(item)
        counts[meta['grade']] += 1
        origins.add(meta['origin_key'])
        if meta['grade'] in ('A', 'B'):
            ab_origins.add(meta['origin_key'])
    return {
        'grade_counts': counts,
        'origin_groups': len(origins),
        'independent_ab_origin_groups': len(ab_origins),
        'critical_cross_check_ready': len(ab_origins) >= 2,
        'note': '来源类型统计不等于指标口径核验；跨站转载仍需人工识别。',
    }


def format_for_prompt(item, number):
    meta = classify(item)
    return (f'[{number}][等级{meta["grade"]}][原始来源组{meta["origin_key"]}] '
            f'{item.get("title") or "无标题"}｜{item.get("publisher") or "发布机构待核实"}｜'
            f'{item.get("published_at") or "日期待核实"}\n{item.get("excerpt") or ""}')
