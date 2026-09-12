from app.industry_research.content_quality import repeated_passages, repetition_issues


def test_internal_repeat_is_available_to_repair():
    sentence = '目前缺乏该细分市场的具体占比以及同口径的产品单价数据，因此无法进行准确测算'
    content = '。\n'.join([sentence] * 6)
    assert repeated_passages(content) == [sentence]
    assert repetition_issues(content)


def test_cross_chapter_and_distinct_text():
    sentence = '企业在进入目标客户供应链之前需要完成产品可靠性验证并获得正式采购资格'
    assert repeated_passages(sentence, [sentence]) == [sentence]
    assert repeated_passages(sentence) == []
