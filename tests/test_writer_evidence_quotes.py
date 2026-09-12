from app.industry_research import evidence_review, writer


def _row(state='recommended_for_review', decision=None):
    row = {
        'id': 'e1',
        'chapter_no': 4,
        'title': '市场规模资料',
        'publisher': '统计机构',
        'published_at': '2025-01-01',
        'url': 'https://example.com/source',
        'source_type': 'research_report',
        'provider': 'exa',
        'search_query': '市场规模',
        'score': 0.8,
        'excerpt': '无关背景段落。2024年市场规模为100亿元。其他冗长内容。',
        'metadata': {},
    }
    row['metadata']['pre_review'] = {
        'version': evidence_review.PRE_REVIEW_VERSION,
        'evidence_fingerprint': evidence_review.evidence_fingerprint(row),
        'chapter_no': 4,
        'state': state,
        'exact_quotes': [{
            'quote': '2024年市场规模为100亿元。',
            'kind': '关键数字',
        }],
    }
    if decision:
        row['metadata']['review'] = {'decision': decision, 'reason': '已核对'}
    return row


def test_writer_uses_traceable_pre_review_quote_instead_of_full_noise():
    fitted = writer._fit_evidence([_row()])

    assert fitted[0]['excerpt'] == '2024年市场规模为100亿元。'


def test_writer_keeps_context_for_risky_row_until_person_retains_it():
    pending = writer._fit_evidence([_row(state='manual_review')])
    approved = writer._fit_evidence([_row(state='manual_review', decision='approved')])

    assert '无关背景段落' in pending[0]['excerpt']
    assert approved[0]['excerpt'] == '2024年市场规模为100亿元。'
