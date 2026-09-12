import asyncio
import json

from app.industry_research import writer


def test_trace_records_attempt_without_extra_call(monkeypatch):
    calls = []; records = []
    async def complete(messages):
        calls.append(messages)
        return '本报告研究生成式人工智能参与内容生产的短剧。具体行业边界需要依据产品形态与制作环节确定。'
    monkeypatch.setattr(writer.llm, 'complete', complete)
    asyncio.run(writer._validated_chapter([], 1, [], lambda: None, lambda _: None, records.append))
    assert len(calls) == len(records) == 1
    assert records[0]['blocking_issues'] == []
    assert records[0]['raw_output'] == records[0]['cleaned_output']


def test_local_trace_and_disable(monkeypatch, tmp_path):
    monkeypatch.setattr(writer.llm, 'ROOT', tmp_path)
    monkeypatch.setenv('REPORT_GENERATION_TRACE', '1')
    writer._save_generation_trace({'chapter_no': 1, 'raw_output': '正文'})
    files = list((tmp_path / 'storage/generation_traces').glob('*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding='utf-8'))['raw_output'] == '正文'
    monkeypatch.setenv('REPORT_GENERATION_TRACE', '0')
    writer._save_generation_trace({'chapter_no': 2})
    assert len(list(files[0].parent.glob('*.json'))) == 1
