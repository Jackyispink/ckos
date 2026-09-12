"""Auditable automatic triage for chapter evidence.

The feature deliberately separates *selection confidence* from factual
confidence.  Rules and the optional language model may identify useful exact
quotes and review risks, but they never approve a source, verify a number, or
clear a provider-moderation review gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .. import llm
from . import database, decision_extraction
from .evidence_grading import classify
from .evidence_review import PRE_REVIEW_VERSION, current_pre_review, evidence_fingerprint


CONFIDENCE_MEANING = (
    '仅表示程序对资料分流及逐字摘录选择的把握，不表示来源真实、数字准确或统计口径已核验。'
)
_NUMERIC_FACT = re.compile(
    r'(?<![A-Za-z0-9_.])-?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?\s*'
    r'(?:万亿元|亿元|万元|元/吨|元/平方米|元/㎡|亿平方米|万平方米|平方米|'
    r'亿㎡|万㎡|㎡|万吨|吨|万台|万套|万人|%|％|倍|天|公里|家|台|套)'
)
_YEAR = re.compile(r'20\d{2}年?')
_IMPORTANT = re.compile(
    r'市场规模|需求量|销量|产量|出货量|渗透率|增长率|增速|CAGR|市场份额|占比|'
    r'产能|利用率|良率|价格|成本|毛利率|净利率|投资额|CAPEX|OPEX|账期|回收期|'
    r'客户|供应商|设备|认证|标准|政策|风险|工艺|原材料|选址|区域', re.I
)
_METRICS = (
    '市场规模', '需求量', '销量', '产量', '出货量', '渗透率', '增长率', '增速',
    'CAGR', '市场份额', '占比', '产能', '利用率', '良率', '价格', '成本',
    '毛利率', '净利率', '投资额', '账期', '回收期',
)
_MARKETING = re.compile(r'领先品牌|实力厂家|欢迎咨询|专业生产|厂家直销|品质保证|联系我们')
_GENERIC_TERMS = {
    '行业', '研究', '报告', '分析', '发展', '市场', '企业', '产品', '中国', '主要',
    '情况', '相关', '以及', '进行', '本章', '影响', '现状', '趋势', '数据', '资料',
}


def _compact(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _normal(value: Any) -> str:
    return re.sub(r'[\s\W_]+', '', str(value or '')).lower()


def _chapter_fingerprint(project: dict, chapter: dict, rows: list[dict]) -> str:
    payload = {
        'version': PRE_REVIEW_VERSION,
        'brief': project.get('brief') or {},
        'chapter': {
            'chapter_no': chapter.get('chapter_no'),
            'title': chapter.get('title'),
            'questions': chapter.get('questions'),
            'queries': chapter.get('queries'),
        },
        'evidence': [
            evidence_fingerprint(row)
            for row in sorted(rows, key=lambda item: str(item.get('id') or ''))
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _sentences(text: str):
    """Yield literal substrings so every returned quote can be re-located."""
    seen = set()
    for part in re.split(r'(?<=[。！？；!?;])|\r?\n+', text or ''):
        quote = part.strip()
        if not 8 <= len(quote) <= 500 or quote in seen:
            continue
        seen.add(quote)
        yield quote


def _program_quotes(row: dict, chapter: dict | None = None,
                    limit: int = 5) -> list[dict]:
    excerpt = row.get('excerpt') or ''
    chapter_terms = _ngrams(' '.join(map(str, (
        (chapter or {}).get('title') or '',
        (chapter or {}).get('questions') or '',
        (chapter or {}).get('queries') or '',
    ))))
    candidates = []
    for position, sentence in enumerate(_sentences(excerpt)):
        has_number = bool(_NUMERIC_FACT.search(sentence))
        has_key_fact = bool(_IMPORTANT.search(sentence))
        if not has_number and not has_key_fact:
            continue
        overlap = len(chapter_terms & _ngrams(sentence))
        score = (4 if has_number else 0) + (2 if has_key_fact else 0)
        score += min(3, overlap) + (1 if _YEAR.search(sentence) else 0)
        score -= 2 if ('...' in sentence or '…' in sentence) else 0
        candidates.append((score, position, {
            'quote': sentence,
            'kind': '关键数字' if has_number else '关键事实',
            'method': 'program_exact_quote',
        }))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    # Defensive invariant: a transformed or fabricated string must never be
    # exposed as an exact quote.
    return [item for _, _, item in candidates[:limit]
            if item['quote'] in excerpt]


def _ngrams(value: Any) -> set[str]:
    result = set()
    for ascii_word in re.findall(r'[A-Za-z][A-Za-z0-9+.-]{1,}', str(value or '')):
        result.add(ascii_word.lower())
    for chunk in re.findall(r'[\u4e00-\u9fff]{2,}', str(value or '')):
        if len(chunk) <= 6 and chunk not in _GENERIC_TERMS:
            result.add(chunk)
        for size in (2, 3, 4):
            for index in range(max(0, len(chunk) - size + 1)):
                term = chunk[index:index + size]
                if term not in _GENERIC_TERMS:
                    result.add(term)
    return result


def _relevance(project: dict, chapter: dict, row: dict) -> tuple[float, bool]:
    brief = project.get('brief') or {}
    core = _ngrams(' '.join(str(brief.get(key) or '') for key in (
        'topic', 'industry', 'product_scope', 'specific_product',
        'downstream_application', 'included_scope', 'focus', 'geography',
    )))
    chapter_terms = _ngrams(' '.join(map(str, (
        chapter.get('title') or '', chapter.get('questions') or '',
        chapter.get('queries') or '',
    ))))
    haystack = _ngrams(' '.join(str(row.get(key) or '') for key in (
        'title', 'excerpt', 'publisher', 'search_query',
    )))
    if not core and not chapter_terms:
        return 0.5, False
    core_hits = len(core & haystack)
    chapter_hits = len(chapter_terms & haystack)
    denominator = max(1, min(12, len(core) + len(chapter_terms)))
    score = min(1.0, (core_hits * 2 + chapter_hits) / denominator)
    provider_score = float(row.get('score') or 0)
    # This is intentionally conservative: absence of token overlap alone is
    # not enough to silently reject evidence.
    obvious_low = bool(core and core_hits == 0 and chapter_hits == 0 and provider_score < 0.15)
    return score, obvious_low


def _claim_keys(row: dict) -> list[tuple[tuple[str, str, str, str, str], str]]:
    result = []
    for sentence in _sentences(row.get('excerpt') or ''):
        metric = next((item.upper() if item == 'CAGR' else item
                       for item in _METRICS if re.search(re.escape(item), sentence, re.I)), '')
        if not metric:
            continue
        year = (_YEAR.search(sentence).group(0).rstrip('年')
                if _YEAR.search(sentence) else '')
        geography_match = re.search(
            r'全球|中国|全国|长三角|珠三角|[京津沪渝粤浙苏鲁豫川鄂湘闽皖冀晋辽吉黑陕甘青琼云贵桂内蒙宁新藏]省?',
            sentence,
        )
        geography = geography_match.group(0) if geography_match else ''
        metric_at = sentence.lower().find(metric.lower())
        subject_raw = sentence[:metric_at] if metric_at >= 0 else ''
        subject_raw = _YEAR.sub('', subject_raw)
        subject_raw = re.sub(
            r'^(?:据[^，,：:]{0,20}[，,：:]?|报告显示|数据显示|预计|约)+',
            '', subject_raw,
        )
        subject = _normal(subject_raw)[-30:]
        for match in _NUMERIC_FACT.finditer(sentence):
            raw = match.group(0).replace('，', ',').replace('％', '%').replace(' ', '')
            unit_match = re.search(r'[^\d.,-]+$', raw)
            unit = unit_match.group(0) if unit_match else ''
            value = raw[:-len(unit)] if unit else raw
            try:
                canonical = format(Decimal(value.replace(',', '')).normalize(), 'f')
            except InvalidOperation:
                canonical = value.replace(',', '')
            result.append(((metric, year, unit, geography, subject), canonical))
    return result


def program_assessments(project: dict, chapter: dict, rows: list[dict]) -> dict[str, dict]:
    """Create deterministic triage metadata without changing human review."""
    batch = _chapter_fingerprint(project, chapter, rows)
    duplicate_owner: dict[str, str] = {}
    claims: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        for key, value in _claim_keys(row):
            claims[key][value].add(str(row.get('id') or ''))
    conflicting_ids = set()
    for values in claims.values():
        if len(values) > 1:
            for ids in values.values():
                conflicting_ids.update(ids)

    result = {}
    for row in rows:
        row_id = str(row.get('id') or '')
        excerpt = row.get('excerpt') or ''
        grade = classify(row)
        reasons, risks = [], []
        # Duplicate detection may ignore whitespace, but it must preserve numeric
        # punctuation.  Removing '-' or '.' would incorrectly collapse -10% into
        # 10%, or 1.2% into 12%, and could hide materially different evidence.
        normalized = re.sub(r'\s+', '', excerpt).lower()
        duplicate_of = ''
        if normalized:
            duplicate_of = duplicate_owner.get(normalized, '')
            duplicate_owner.setdefault(normalized, row_id)
        relevance, obvious_low = _relevance(project, chapter, row)
        if not excerpt.strip():
            state = 'empty'
            reasons.append('正文摘录为空，程序无法提取可引用内容。')
            confidence = 1.0
        elif duplicate_of:
            state = 'duplicate'
            reasons.append('与本章另一条资料的正文摘录完全重复。')
            risks.append('重复资料不构成独立交叉验证；原始记录仍保留。')
            confidence = 0.98
        else:
            if obvious_low:
                risks.append('标题、查询词与摘录未命中研究主题或本章关键表达，且搜索相关分较低。')
            if row_id in conflicting_ids:
                risks.append('本章其他资料对相同年份、单位和指标出现不同数值，需核对统计口径。')
            if '...' in excerpt or '…' in excerpt:
                risks.append('摘录存在省略或截断，需打开原始来源核对上下文。')
            if grade['grade'] == 'D':
                risks.append('来源身份不完整或属于文库/二次资料，只宜作为线索。')
            if not row.get('publisher'):
                risks.append('发布机构缺失。')
            if not row.get('url') and row.get('source_type') != '结构化数据':
                risks.append('缺少可回查网址。')
            if _MARKETING.search(excerpt):
                risks.append('文本含明显营销表达，需区分宣传主张与可核验事实。')
            state = ('manual_review' if obvious_low or row_id in conflicting_ids
                     or grade['grade'] == 'D' or '...' in excerpt or '…' in excerpt
                     else 'recommended_for_review')
            confidence = 0.45 if state == 'manual_review' else (0.86 if grade['grade'] in 'AB' else 0.72)
            reasons.append(
                '建议优先核对其逐字摘录、来源日期与统计口径。'
                if state == 'recommended_for_review'
                else '存在需要人工判断的相关性、来源或口径风险。'
            )
        result[row_id] = {
            'version': PRE_REVIEW_VERSION,
            'evidence_fingerprint': evidence_fingerprint(row),
            'batch_fingerprint': batch,
            'chapter_no': row.get('chapter_no'),
            'state': state,
            'selection_confidence': confidence,
            'confidence_meaning': CONFIDENCE_MEANING,
            'relevance_signal': round(relevance, 3),
            'source_grade': grade['grade'],
            'reasons': reasons,
            'risks': risks,
            'exact_quotes': _program_quotes(row, chapter),
            'duplicate_of': duplicate_of or None,
            'ai_requested': False,
            'ai_status': 'not_requested',
            'quote_validation': {'accepted': 0, 'rejected': 0},
        }
    return result


def _shared_exact_quotes(records: list[dict], rows: list[dict]) -> tuple[dict[str, list[str]], int]:
    """Reuse decision extraction instead of issuing a second paid model call.

    The shared extractor already has a durable evidence-fingerprint cache.  At
    this UI boundary we deliberately require a literal source substring before
    displaying anything as a word-for-word quote.
    """
    by_id = {str(row.get('id') or ''): row for row in rows}
    accepted: dict[str, list[str]] = defaultdict(list)
    rejected = 0
    for record in records:
        fields = record.get('fields') or {}
        if not isinstance(fields, dict):
            continue
        auto = fields.get('auto_extraction') or {}
        quote = str(auto.get('exact_quote') or '').strip()
        origin_ids = auto.get('origin_evidence_ids') or []
        if not quote or not isinstance(origin_ids, list):
            continue
        for raw_id in origin_ids:
            evidence_id = str(raw_id or '')
            source = by_id.get(evidence_id)
            if source and 8 <= len(quote) <= 500 and quote in (source.get('excerpt') or ''):
                if quote not in accepted[evidence_id]:
                    accepted[evidence_id].append(quote)
            else:
                rejected += 1
    return dict(accepted), rejected


def _cache_valid(rows: list[dict], batch_fingerprint: str, use_ai: bool,
                 ai_configured: bool) -> bool:
    if not rows:
        return True
    for row in rows:
        assessment = current_pre_review(row)
        if not assessment or assessment.get('batch_fingerprint') != batch_fingerprint:
            return False
        if bool(assessment.get('ai_requested')) != use_ai:
            return False
        status = assessment.get('ai_status')
        if use_ai and ai_configured and status not in {
                'success', 'no_ai_quote', 'provider_review_required'}:
            return False
    return True


def review_summary(project: dict, chapter_no: int, rows: list[dict]) -> dict:
    counts = defaultdict(int)
    human = defaultdict(int)
    quote_count = 0
    pending_manual_review = 0
    for row in rows:
        assessment = current_pre_review(row)
        counts[assessment.get('state') or 'not_pre_reviewed'] += 1
        decision = ((row.get('metadata') or {}).get('review') or {}).get('decision')
        human[decision or 'pending'] += 1
        if assessment.get('state') == 'manual_review' and not decision:
            pending_manual_review += 1
        quote_count += len(assessment.get('exact_quotes') or [])
    chapter = next((item for item in project.get('chapters', [])
                    if item.get('chapter_no') == chapter_no), {})
    review_complete = bool(rows) and human.get('pending', 0) == 0 and human.get('approved', 0) > 0
    return {
        'total': len(rows),
        'states': dict(counts),
        'human_decisions': dict(human),
        'exact_quote_count': quote_count,
        'pending_manual_review': pending_manual_review,
        'review_complete': review_complete,
        'report_update_required': bool(chapter.get('evidence_stale')),
        'provider_review_gate': project.get('review_required_chapter') == chapter_no,
        'auto_review_cannot_clear_provider_gate': True,
        'confidence_note': CONFIDENCE_MEANING,
    }


def _shared_ai_status(records: list[dict], *, use_ai: bool, warning: str = '',
                      explicit_status: str = '') -> str:
    if not use_ai:
        return 'not_requested'
    if explicit_status in {
            'success', 'failed', 'provider_review_required', 'not_configured'}:
        return explicit_status
    statuses = []
    for record in records:
        fields = record.get('fields') or {}
        auto = fields.get('auto_extraction') or {} if isinstance(fields, dict) else {}
        if auto.get('managed') is True and auto.get('ai_status'):
            statuses.append(str(auto['ai_status']))
    if 'provider_review_required' in statuses or '-20058' in warning or '内容审核' in warning:
        return 'provider_review_required'
    if warning or 'failed' in statuses:
        return 'failed'
    if 'success' in statuses:
        return 'success'
    return 'not_configured' if not llm.configured() else 'rules_only'


def _apply_shared_quotes(assessments: dict[str, dict], rows: list[dict],
                         records: list[dict], *, use_ai: bool,
                         warning: str = '', explicit_status: str = '') -> int:
    selected, rejected = _shared_exact_quotes(records, rows)
    status = _shared_ai_status(
        records, use_ai=use_ai, warning=warning,
        explicit_status=explicit_status)
    for row in rows:
        assessment = assessments[str(row.get('id') or '')]
        quotes = assessment['exact_quotes']
        existing = {item['quote'] for item in quotes}
        accepted_here = 0
        for quote in selected.get(str(row.get('id') or ''), []):
            if quote not in existing:
                quotes.append({
                    'quote': quote,
                    'kind': 'AI建议摘录' if status == 'success' else '自动结构化摘录',
                    'method': 'shared_model_exact_quote',
                })
                existing.add(quote)
            accepted_here += 1
        assessment['ai_requested'] = bool(use_ai)
        assessment['ai_status'] = (
            'success' if status == 'success' and accepted_here
            else 'no_ai_quote' if status == 'success'
            else status
        )
        assessment['quote_validation'] = {
            'accepted': accepted_here,
            'rejected': rejected,
        }
        if status == 'provider_review_required':
            assessment['risks'].append(
                '模型厂商要求人工复核；自动整理未批准资料，也未清除复核门槛。'
            )
    return sum(len(values) for values in selected.values())


def refresh_chapter_from_existing(project_id: str, chapter_no: int, *,
                                  use_ai: bool = False,
                                  warning: str = '') -> dict:
    """Build one chapter's review index without making a model request."""
    project = database.project(project_id)
    chapter = database.chapter(project_id, chapter_no)
    if not project or not chapter:
        raise ValueError('章节不存在')
    rows = database.review_evidence(project_id, chapter_no)
    assessments = program_assessments(project, chapter, rows)
    records = database.decision_records(project_id)
    total_quotes = _apply_shared_quotes(
        assessments, rows, records, use_ai=use_ai, warning=warning)
    saved = database.save_evidence_pre_reviews(
        project_id, chapter_no, assessments)
    return {
        'rows': saved,
        'shared_exact_quotes': total_quotes,
        'model_called': False,
        'summary': review_summary(
            project, chapter_no, database.review_evidence(project_id, chapter_no)),
    }


def refresh_project_from_existing(project_id: str, *, use_ai: bool = True,
                                  warning: str = '', ai_status: str = '') -> dict:
    """Populate all chapter review views from the already-paid extraction.

    This function never calls a model.  It is invoked after the normal shared
    decision extraction, so opening the review workbench does not require a
    second paid pass merely to expose the same exact quotes.
    """
    project = database.project(project_id)
    if not project:
        raise ValueError('行业研究项目不存在')
    records = database.decision_records(project_id)
    chapters = {int(row.get('chapter_no') or 0): row
                for row in project.get('chapters') or []}
    total_rows = total_quotes = 0
    for chapter_no in range(1, 11):
        chapter = chapters.get(chapter_no) or database.chapter(project_id, chapter_no)
        if not chapter:
            continue
        rows = database.review_evidence(project_id, chapter_no)
        assessments = program_assessments(project, chapter, rows)
        total_quotes += _apply_shared_quotes(
            assessments, rows, records, use_ai=use_ai, warning=warning,
            explicit_status=ai_status)
        total_rows += database.save_evidence_pre_reviews(
            project_id, chapter_no, assessments)
    return {'rows': total_rows, 'shared_exact_quotes': total_quotes,
            'model_called': False}


async def run(project_id: str, chapter_no: int, *, use_ai: bool = True,
              force: bool = False) -> dict:
    project = database.project(project_id)
    chapter = database.chapter(project_id, chapter_no)
    if not project or not chapter:
        raise ValueError('章节不存在')
    rows = database.review_evidence(project_id, chapter_no)
    batch = _chapter_fingerprint(project, chapter, rows)
    ai_configured = bool(use_ai and llm.configured())
    if not force and _cache_valid(rows, batch, use_ai, ai_configured):
        return {
            'cached': True,
            'method': '缓存命中，未重复调用模型',
            'summary': review_summary(project, chapter_no, rows),
        }

    assessments = program_assessments(project, chapter, rows)
    warning = ''
    selected: dict[str, list[str]] = {}
    extraction_result: dict = {}
    try:
        # The same cached pass feeds both the decision-data workbench and this
        # review UI.  The writer's later automatic extraction therefore does
        # not issue a duplicate paid request for an unchanged evidence set.
        extraction_result = await decision_extraction.extract_project(
            project_id, use_ai=use_ai, force=force,
        )
        records = database.decision_records(project_id)
        selected, _ = _shared_exact_quotes(records, rows)
        warning = str(extraction_result.get('warning') or '')
        _apply_shared_quotes(
            assessments, rows, records, use_ai=use_ai, warning=warning,
            explicit_status=str(extraction_result.get('ai_status') or ''))
    except llm.ModelContentReviewRequired as exc:
        # Defensive: the shared extractor currently returns this as a warning,
        # but a future refactor must still never turn -20058 into approval.
        warning = str(exc)
        for assessment in assessments.values():
            assessment['ai_requested'] = bool(use_ai)
            assessment['ai_status'] = 'provider_review_required'
            assessment['risks'].append(
                '模型厂商要求人工复核；自动整理未批准资料，也未清除复核门槛。'
            )
    except (llm.ModelError, ValueError, TypeError) as exc:
        warning = str(exc)
        for assessment in assessments.values():
            assessment['ai_requested'] = bool(use_ai)
            assessment['ai_status'] = 'failed'

    database.save_evidence_pre_reviews(project_id, chapter_no, assessments)
    refreshed = database.review_evidence(project_id, chapter_no)
    result = {
        'cached': False,
        'method': ('程序预筛 + 复用结构化整理的逐字摘录'
                   if selected else '程序预筛'),
        'summary': review_summary(project, chapter_no, refreshed),
    }
    if warning:
        result['warning'] = warning
    return result
