"""Human relevance review and eligibility rules.

Original evidence is immutable.  Automatic pre-review is deliberately a
triage aid: it can identify a traceable quote candidate, but it never turns a
source grade or a model choice into a verified fact.
"""
import hashlib
import json

from pydantic import BaseModel, Field
from typing import Literal


PRE_REVIEW_VERSION = 'evidence-pre-review-20260909-v1'


class ReviewDecision(BaseModel):
    decision: Literal['approved', 'excluded']
    reason: str = Field(min_length=2, max_length=500)


class PreReviewRequest(BaseModel):
    use_ai: bool = True
    force: bool = False


class BulkReviewRequest(BaseModel):
    """Explicit one-click chapter review operation."""

    confirm: Literal[
        'apply_safe_suggestions',
        'approve_all_pending',
        'exclude_all_pending',
    ]


def evidence_fingerprint(row):
    """Fingerprint immutable/source fields used by an automatic assessment."""
    payload = {
        'id': row.get('id'),
        'chapter_no': row.get('chapter_no'),
        'title': row.get('title'),
        'url': row.get('url'),
        'publisher': row.get('publisher'),
        'published_at': row.get('published_at'),
        'excerpt': row.get('excerpt'),
        'source_type': row.get('source_type'),
        'provider': row.get('provider'),
        'search_query': row.get('search_query'),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def current_pre_review(row):
    """Return only an assessment that still points to this exact evidence."""
    metadata = row.get('metadata') or {}
    assessment = metadata.get('pre_review') or {}
    if not isinstance(assessment, dict):
        return {}
    if assessment.get('version') != PRE_REVIEW_VERSION:
        return {}
    if assessment.get('evidence_fingerprint') != evidence_fingerprint(row):
        return {}
    if assessment.get('chapter_no') != row.get('chapter_no'):
        return {}
    return assessment


def warnings(row):
    text = row.get('excerpt', '')
    notes = []
    if '...' in text or '…' in text:
        notes.append('存在省略或截断，请核对原文上下文。')
    if row.get('chapter_no') == 3 and any(t in text for t in ('市场份额', '市占率', 'CAGR', '市场规模')):
        notes.append('含规模或竞争指标，核对是否属于第3章；需要时在对应章节补充，勿重复展开。')
    assessment = current_pre_review(row)
    if assessment.get('state') in {'auto_approved_candidate', 'recommended_for_review'}:
        notes.append('自动预审只确认摘录可回定位且与本章较相关，不代表数字、口径或事实已核验。')
    elif assessment.get('state') == 'manual_review':
        notes.append('自动预审发现低相关、冲突或可疑信号，需人工判断后才能使用。')
    elif assessment.get('state') in {'auto_duplicate', 'duplicate'}:
        notes.append('程序识别为重复资料，原始记录仍保留，可由人工审核覆盖。')
    notes.append('核对原始来源、日期、口径和本章相关性；审核通过不代表厂商一定接受。')
    return notes


def is_usable(row):
    """Return whether evidence may participate in writing, audits, and exports.

    Human review never deletes the original row.  Keeping this predicate here
    prevents each consumer from interpreting ``review.excluded`` differently.
    """
    metadata = row.get('metadata') or {}
    review = metadata.get('review') or {}
    if not (row.get('excerpt') or '').strip() or review.get('decision') == 'excluded':
        return False
    # An explicit human decision always wins over automatic triage.  This also
    # makes a false-positive duplicate/relevance flag fully reversible.
    if review.get('decision') == 'approved':
        return True
    # Automatic triage is a UI prioritisation aid, not a truth verdict.  A
    # duplicate, low-relevance or risky signal must never silently remove a
    # non-empty source from writing.  Only an explicit human exclusion does.
    return True


def usable(rows, chapter_no=None):
    # ``chapter_no`` remains optional for backward compatibility with callers;
    # eligibility itself is deliberately chapter-independent.
    return [row for row in rows if is_usable(row)]
