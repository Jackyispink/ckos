from app.industry_research.evidence_review import usable, warnings


def test_review_preserves_original_and_filters():
    rows=[{'excerpt':'政策原文','metadata':{'review':{'decision':'approved'}}},
          {'excerpt':'未审核'}, {'excerpt':'排除原文','metadata':{'review':{'decision':'excluded'}}}]
    assert len(usable(rows,3)) == 2
    assert len(usable(rows,4)) == 2
    assert rows[2]['excerpt'] == '排除原文'


def test_quality_notes_not_sensitive_word_filter():
    assert len(warnings({'chapter_no':3,'excerpt':'市场规模...'})) == 3
    assert len(warnings({'chapter_no':3,'excerpt':'正常政策引用'})) == 1
