from app.industry_research import decision_auto_calculation, decision_extraction, writer


def _chapters(done=0):
    return [
        {
            'chapter_no': number,
            'status': 'complete' if number <= done else 'planned',
            'content': '已完成正文。' if number <= done else '',
        }
        for number in range(1, 11)
    ]


def test_manufacturing_generation_auto_extracts_after_collection(monkeypatch):
    calls = []
    calculation_calls = []
    updates = []

    async def extract(project_id, *, use_ai, force=False):
        calls.append((project_id, use_ai, force))
        return {
            'created': 6,
            'skipped': 0,
            'candidates': 6,
            'method': 'AI与程序规则整理',
            'cached': False,
        }

    monkeypatch.setattr(decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(
        decision_auto_calculation,
        'calculate_project',
        lambda project_id: calculation_calls.append(project_id) or {
            'computed': 1, 'reused': 0, 'calculations': 1,
            'blocked': 0, 'gap_count': 2, 'gaps': {},
        },
    )
    monkeypatch.setattr(writer, '_update', lambda *args, **kwargs: updates.append((args, kwargs)))

    result = writer._auto_extract_decision_records(
        'project-1', {'research_template': 'manufacturing'}, _chapters(done=3), 'resume')

    assert result['created'] == 6
    assert result['calculation']['computed'] == 1
    assert calls == [('project-1', True, False)]
    assert calculation_calls == ['project-1']
    assert updates[0][0][2] == '资料采集完成，正在AI自动整理结构化研究数据（不影响正文）'
    assert updates[0][1]['completed'] == 3


def test_auto_extraction_failure_does_not_stop_report_generation(monkeypatch):
    async def extract(*args, **kwargs):
        raise RuntimeError('temporary extraction failure')

    monkeypatch.setattr(decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(writer, '_update', lambda *args, **kwargs: None)

    assert writer._auto_extract_decision_records(
        'project-2', {'research_template': 'manufacturing'}, _chapters(), 'regenerate') is None


def test_auto_calculation_failure_does_not_discard_extraction(monkeypatch):
    async def extract(*args, **kwargs):
        return {'created': 3, 'candidates': 3}

    def calculate(_project_id):
        raise RuntimeError('temporary calculation failure')

    monkeypatch.setattr(decision_extraction, 'extract_project', extract)
    monkeypatch.setattr(decision_auto_calculation, 'calculate_project', calculate)
    monkeypatch.setattr(writer, '_update', lambda *args, **kwargs: None)

    result = writer._auto_extract_decision_records(
        'project-2', {'research_template': 'manufacturing'}, _chapters(), 'resume')

    assert result['created'] == 3
    assert result['calculation']['error'] == 'temporary calculation failure'


def test_non_manufacturing_report_does_not_run_decision_extraction(monkeypatch):
    monkeypatch.setattr(
        decision_extraction, 'extract_project',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not run')),
    )
    monkeypatch.setattr(
        writer, '_update',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not update')),
    )

    assert writer._auto_extract_decision_records(
        'project-3', {'research_template': 'general'}, _chapters(), 'resume') is None
