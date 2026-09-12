import asyncio
import json

from app.industry_research import writer
from app.industry_research.chapter_contracts import CHAPTER_CONTRACTS


def test_all_chapters_have_distinct_scope():
    assert set(CHAPTER_CONTRACTS) == set(range(1, 11))
    assert len(set(CHAPTER_CONTRACTS.values())) == 10
    prompt = writer._chapter_prompt({'topic': 'AI短剧'},
        {'chapter_no': 1, 'title': '定义', 'questions': []}, [], '')
    assert '不写市场规模年表' in prompt
    assert '允许短章' in prompt


def test_evidence_budget_dedup_and_complete_excerpt():
    def row(text, score):
        return dict(title='来源', publisher='机构', published_at='2026', excerpt=text, score=score)
    result = writer._fit_evidence([row('相同证据。', 5), row('相同 证据。', 4),
        row('没有句号的超长片段' * 300, 9), row('另一条证据。', 3)])
    assert len(result) == 3
    assert result[0]['excerpt'].endswith('〔超长原文，仅截取开头；引用前须核对原文〕')
    assert [r['excerpt'] for r in result[1:]] == ['相同证据。', '另一条证据。']


def test_repair_receives_repeated_material(monkeypatch):
    sentence = '这是前文已经讨论过的市场增长因素和相关影响，不应再次作为本章的全部分析。'
    bad = '\n'.join([sentence] * 4)
    calls = []
    monkeypatch.setenv('REPORT_QUALITY_REPAIR_ATTEMPTS', '1')
    async def complete(messages):
        calls.append(messages)
        return bad if len(calls) == 1 else '本章仅解释企业之间的竞争规则。现有资料不足以计算同口径市场份额，需要补充对应年份企业业务收入和市场总额。'
    monkeypatch.setattr(writer.llm, 'complete', complete)
    asyncio.run(writer._validated_chapter([], 7, [sentence], lambda: None, lambda _: None))
    repair = json.loads(calls[1][-1]['content'])
    assert sentence in repair['already_covered_do_not_repeat']
    assert '份额及CR指标' in repair['chapter_contract']
