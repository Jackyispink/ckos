from app.industry_research.evidence_grading import audit, canonical_url, classify, format_for_prompt
from app.industry_research.writer import _fit_evidence


def test_official_and_document_hosts_are_distinguished():
    assert classify({'url':'https://www.stats.gov.cn/a','publisher':'国家统计局'})['grade'] == 'A'
    assert classify({'url':'https://www.book118.com/a','publisher':'转载'})['grade'] == 'D'
    assert classify({'url':'https://notgov.cn/a','publisher':'未知'})['grade'] != 'A'
    assert classify({'url':'https://evilcninfo.com.cn/a','publisher':'未知'})['grade'] != 'A'


def test_tracking_variants_share_original_group():
    first={'url':'https://example.com/report?utm_source=x&id=1','publisher':'行业媒体','title':'报告'}
    second={'url':'https://example.com/report?id=1','publisher':'行业媒体','title':'报告'}
    assert canonical_url(first['url']) == canonical_url(second['url'])
    assert classify(first)['origin_key'] == classify(second)['origin_key']


def test_prompt_exposes_grade_and_origin_group():
    text=format_for_prompt({'url':'https://www.gov.cn/a','title':'政策','publisher':'国务院',
                            'published_at':'2026-01-01','excerpt':'正文'},1)
    assert '[1][等级A]' in text and '[原始来源组' in text


def test_writer_keeps_original_citation_indices_when_items_are_skipped():
    from app.industry_research.writer import _fit_evidence
    items = [
        {'title':'高分但超长','excerpt':'没有句号' * 1000,'score':1},
        {'title':'第二条','excerpt':'可用事实。','score':.9},
    ]
    chosen = _fit_evidence(items, budget=1000)
    assert len(chosen) == 1
    assert chosen[0]['title'] == '第二条'
    assert chosen[0]['_citation_index'] == 2


def test_fitted_evidence_keeps_full_list_citation_index():
    rows=[{'title':'高分','excerpt':'有效内容。','score':1.0},
          {'title':'超预算','excerpt':'很长的内容。'*100,'score':.9},
          {'title':'低分','excerpt':'另一条内容。','score':.8}]
    fitted=_fit_evidence(rows,budget=180)
    assert [row['_citation_index'] for row in fitted] == [1,3]


def test_audit_counts_independent_ab_origins_without_claiming_scope_validation():
    result = audit([
        {'url': 'https://stats.gov.cn/a', 'title': '统计'},
        {'url': 'https://stats.gov.cn/a?utm_source=x', 'title': '参数变体'},
        {'url': 'https://example.edu.cn/paper', 'publisher': '某大学'},
        {'url': 'https://book118.com/a', 'title': '文库'},
    ])
    assert result['grade_counts'] == {'A': 2, 'B': 1, 'C': 0, 'D': 1}
    assert result['independent_ab_origin_groups'] == 2
    assert result['critical_cross_check_ready'] is True
    assert '不等于指标口径核验' in result['note']
