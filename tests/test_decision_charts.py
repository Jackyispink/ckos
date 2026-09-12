import pytest

from app.industry_research.charts import decision_charts


def test_market_result_becomes_chapter_two_chart_without_model():
    project = {'decision_records': [{
        'record_type': 'market', 'name': '食品饮料瓦楞箱', 'verified': True,
        'as_of_date': '2025', 'source': '逐项输入',
        'fields': {'status': '测算可复核（非投资结论）', 'results': {
            'tam_yuan': '1000', 'sam_yuan': '400', 'som_yuan': '80'}},
    }]}
    charts = decision_charts(project)
    assert len(charts) == 1
    assert charts[0]['chapter_no'] == 2
    assert charts[0]['labels'] == ['TAM', 'SAM', 'SOM']
    assert charts[0]['values'] == [1000, 400, 80]
    assert 'pie' not in charts[0]['chart_types']


def test_finance_result_generates_separate_unit_consistent_charts():
    project = {'decision_records': [{
        'record_type': 'finance', 'name': '方案A', 'verified': False,
        'as_of_date': '2026', 'source': '程序计算',
        'fields': {'status': '待验证', 'results': {
            'revenue': '1000', 'operating_profit': '120', 'net_working_capital': '180',
            'initial_funding_floor': '680', 'utilization_pct': '65',
            'breakeven_utilization_pct': '52', 'receivables': '200',
            'inventory': '90', 'payables': '110'}},
    }]}
    charts = decision_charts(project)
    assert {chart['unit'] for chart in charts} == {'元', '%'}
    assert all(chart['chapter_no'] == 8 for chart in charts)
    assert all('待验证' in chart['title'] for chart in charts)


def test_city_result_generates_score_and_raw_indicator_charts():
    project = {'decision_records': [{
        'id': 'city-1',
        'record_type': 'city',
        'name': '苏州 VS 东莞',
        'verified': True,
        'as_of_date': '2025-12-31',
        'source': '程序计算',
        'fields': {
            'status': '测算可复核（非投资结论）',
            'results': {'weighted_scores': {'苏州': '72', '东莞': '68'}},
            'inputs': {'indicators': [{
                'name': '目标客户密度',
                'direction': 'higher_better',
                'unit': '家/百平方公里',
                'values': {'苏州': {'value': '30'}, '东莞': {'value': '20'}},
            }]},
        },
    }]}
    found = decision_charts(project)
    assert len(found) == 2
    assert all(item['chapter_no'] == 7 for item in found)
    assert found[0]['labels'] == ['苏州', '东莞']
    assert {item['unit'] for item in found} == {'分', '家/百平方公里'}


def test_gate_result_generates_one_comparable_chart_per_metric():
    project = {'decision_records': [{
        'id': 'gate-1',
        'record_type': 'threshold',
        'name': '进入门槛',
        'verified': True,
        'as_of_date': '2026-09-08',
        'source': '程序计算',
        'fields': {
            'status': '门槛判定完成',
            'decision': 'HOLD',
            'metrics': [{
                'stage': '量产', 'name': '产能利用率', 'state': 'HOLD',
                'current_value': '60', 'unit': '%',
                'go_threshold': '70', 'no_go_threshold': '50',
            }],
        },
    }]}
    found = decision_charts(project)
    assert len(found) == 1
    assert found[0]['chapter_no'] == 10
    assert found[0]['labels'] == ['当前值', 'GO阈值', 'NO-GO阈值']
    assert found[0]['values'] == [60, 70, 50]


def _auto_fact(record_id, evidence_id, year, value, *, grade='A', model_shape=False):
    quote = f'{year}年国内食品饮料瓦楞箱市场规模为{value}亿元。'
    fields = {
        'metric': '国内食品饮料瓦楞箱市场规模',
        'scope': '全国｜成品纸箱销售额',
        'status': '自动提取，待复核',
        'auto_extraction': {
            'managed': True,
            'chapter_no': 4,
            'source_grade': grade,
            'origin_evidence_ids': [evidence_id],
            'exact_quote': quote,
        },
    }
    if model_shape:
        fields.update({'value': str(value), 'unit': '亿元', 'period': f'{year}年'})
    else:
        fields.update({
            'measurements': [{'value': str(value), 'unit': '亿元', 'raw': f'{value}亿元'}],
            'periods': [f'{year}年'],
        })
    return {
        'id': record_id,
        'record_type': 'market',
        'name': f'市场｜{year}年规模',
        'basis': 'unverified',
        'verified': False,
        'source': f'国家统计局｜年度统计｜https://example.com/{evidence_id}',
        'fields': fields,
    }


def _cagr_record(points, upstream_ids, evidence_ids):
    return {
        'id': 'calc-cagr-1',
        'record_type': 'market',
        'name': '国内食品饮料瓦楞箱市场规模 CAGR（待复核）',
        'basis': 'calculated',
        'verified': False,
        'source': '程序计算｜上游证据：' + '、'.join(evidence_ids),
        'fields': {
            'metric': '国内食品饮料瓦楞箱市场规模',
            'scope': '全国｜成品纸箱销售额',
            'unit': '亿元',
            'cagr_pct': '22.474487',
            'points': points,
            'pending': ['上游事实为自动提取，计算结果待人工复核'],
            'auto_calculation': {
                'managed': True,
                'calculation_type': 'cagr',
                'input_hash': 'stable-input-hash',
                'upstream_record_ids': upstream_ids,
                'upstream_evidence_ids': evidence_ids,
            },
        },
    }


def test_auto_extracted_scalar_is_auditable_card_never_pie():
    # Use the AI exact-quote storage shape (value/unit/period) because it differs
    # from the rule extractor's measurements list and must remain chartable.
    project = {'decision_records': [_auto_fact('r1', 'e1', 2024, '504.4', grade='B', model_shape=True)]}

    found = decision_charts(project)

    assert len(found) == 1
    chart = found[0]
    assert chart['kind'] == 'decision_auto_fact'
    assert chart['chart_types'] == ['card']
    assert chart['labels'] == ['2024年 国内食品饮料瓦楞箱市场规模']
    assert chart['values'] == [504.4]
    assert chart['evidence_ids'] == ['e1']
    assert chart['source_grade'] == 'B'
    assert chart['scope'] == '全国｜成品纸箱销售额'
    assert chart['source_excerpts'] == ['2024年国内食品饮料瓦楞箱市场规模为504.4亿元。']
    assert chart['pending_review'] is True
    assert chart['verification_status'] == '待复核'
    assert 'pie' not in chart['chart_types']


def test_auto_extracted_lone_percentage_stays_card_and_incomplete_fact_is_hidden():
    percentage = _auto_fact('share', 'e-share', 2024, '30')
    percentage['fields']['metric'] = '食品饮料下游占比'
    percentage['fields']['measurements'] = [{'value': '30', 'unit': '%', 'raw': '30%'}]
    percentage['fields']['auto_extraction']['exact_quote'] = '2024年食品饮料下游占比为30%。'
    incomplete = _auto_fact('bad', 'e-bad', 2024, '100')
    incomplete['fields']['auto_extraction']['exact_quote'] = (
        '2024年市场规模为100亿元，2025年市场规模为120亿元。'
    )

    found = decision_charts({'decision_records': [percentage, incomplete]})

    assert len(found) == 1
    assert found[0]['values'] == [30.0]
    assert found[0]['unit'] == '%'
    assert found[0]['chart_types'] == ['card']


def test_multi_number_exact_quote_becomes_separate_scalar_cards():
    quote = '2024年国内食品饮料瓦楞箱市场规模为100亿元，同比增长20%。'
    record = _auto_fact('multi', 'e-multi', 2024, '100')
    record['fields']['auto_extraction']['exact_quote'] = quote
    record['fields']['measurements'] = [
        {'value': '100', 'unit': '亿元', 'raw': '100亿元'},
        {'value': '20', 'unit': '%', 'raw': '20%'},
    ]

    found = decision_charts({'decision_records': [record]})

    assert len(found) == 2
    assert {(item['unit'], item['values'][0]) for item in found} == {
        ('亿元', 100.0), ('%', 20.0),
    }
    assert all(item['chart_types'] == ['card'] for item in found)
    assert all(item['source_excerpts'] == [quote] for item in found)
    assert len({item['id'] for item in found}) == 2


def test_thousands_separator_is_parsed_as_one_complete_measurement():
    record = _auto_fact('thousands', 'e-thousands', 2024, '1,200')

    found = decision_charts({'decision_records': [record]})

    assert len(found) == 1
    assert found[0]['kind'] == 'decision_auto_fact'
    assert found[0]['values'] == [1200.0]
    assert found[0]['source_excerpts'] == [
        '2024年国内食品饮料瓦楞箱市场规模为1,200亿元。',
    ]


def test_different_metrics_with_the_same_unit_never_become_a_year_series():
    quote = '2022年营业收入为100亿元，2023年净利润为20亿元。'
    record = _auto_fact('mixed-metrics', 'e-mixed', 2022, '100')
    record['fields']['metric'] = '营业收入'
    record['fields']['auto_extraction']['exact_quote'] = quote
    record['fields']['periods'] = ['2022年', '2023年']
    record['fields']['measurements'] = [
        {'value': '100', 'unit': '亿元', 'raw': '100亿元'},
        {'value': '20', 'unit': '亿元', 'raw': '20亿元'},
    ]

    found = decision_charts({'decision_records': [record]})

    assert not any(item['kind'] == 'decision_auto_series' for item in found)
    assert {item['title'].split('（', 1)[0] for item in found} == {'营业收入', '净利润'}
    assert {item['values'][0] for item in found} == {100.0, 20.0}


def test_ambiguous_respective_year_value_pairing_produces_no_auto_chart():
    quote = '2022年和2023年国内食品饮料瓦楞箱市场规模分别为100亿元和120亿元。'
    record = _auto_fact('respective', 'e-respective', 2022, '100')
    record['fields']['auto_extraction']['exact_quote'] = quote
    record['fields']['periods'] = ['2022年', '2023年']
    record['fields']['measurements'] = [
        {'value': '100', 'unit': '亿元', 'raw': '100亿元'},
        {'value': '120', 'unit': '亿元', 'raw': '120亿元'},
    ]

    assert decision_charts({'decision_records': [record]}) == []


def test_multi_year_exact_quote_adds_complete_selectable_series():
    quote = (
        '2022年国内食品饮料瓦楞箱市场规模为100亿元；'
        '2023年为120亿元；2024年为150亿元。'
    )
    record = _auto_fact('series', 'e-series', 2022, '100')
    record['fields']['auto_extraction']['exact_quote'] = quote
    record['fields']['periods'] = ['2022年', '2023年', '2024年']
    record['fields']['measurements'] = [
        {'value': '100', 'unit': '亿元', 'raw': '100亿元'},
        {'value': '120', 'unit': '亿元', 'raw': '120亿元'},
        {'value': '150', 'unit': '亿元', 'raw': '150亿元'},
    ]

    found = decision_charts({'decision_records': [record]})
    series = next(item for item in found if item['kind'] == 'decision_auto_series')

    assert series['labels'] == ['2022', '2023', '2024']
    assert series['values'] == [100.0, 120.0, 150.0]
    assert set(series['chart_types']) >= {'line', 'bar', 'area'}
    assert series['source_excerpts'] == [quote]


@pytest.mark.parametrize('evidence', [
    [],
    [{
        'id': 'e1',
        'excerpt': '2024年国内食品饮料瓦楞箱市场规模为100亿元。',
        'metadata': {'review': {'decision': 'excluded', 'reason': '口径不符'}},
    }],
    [{
        'id': 'e1',
        'excerpt': '原始资料没有这句市场规模表述。',
        'metadata': {},
    }],
])
def test_production_chart_path_rejects_missing_excluded_or_nonliteral_evidence(evidence):
    record = _auto_fact('r1', 'e1', 2024, '100')

    found = decision_charts({
        'decision_records': [record],
        'evidence': evidence,
    })

    assert found == []


def test_calculated_cagr_chart_keeps_all_three_years_and_all_provenance():
    upstream = [
        _auto_fact('r1', 'e1', 2022, '100', grade='A'),
        _auto_fact('r2', 'e2', 2023, '120', grade='B'),
        _auto_fact('r3', 'e3', 2024, '150', grade='A'),
    ]
    calculation = _cagr_record(
        [
            {'year': 2024, 'value': '150', 'forecast': True},
            {'year': 2022, 'value': '100', 'forecast': False},
            {'year': 2023, 'value': '120', 'forecast': False},
        ],
        ['r1', 'r2', 'r3'],
        ['e1', 'e2', 'e3'],
    )

    found = decision_charts({'decision_records': [*upstream, calculation]})
    chart = next(item for item in found if item['kind'] == 'decision_auto_cagr')

    assert chart['labels'] == ['2022', '2023', '2024']
    assert chart['values'] == [100.0, 120.0, 150.0]
    assert len(chart['labels']) == len(calculation['fields']['points']) == 3
    assert chart['evidence_ids'] == ['e1', 'e2', 'e3']
    assert chart['source_grade'] == 'A/B'
    assert chart['scope'] == '全国｜成品纸箱销售额'
    assert len(chart['source_excerpts']) == 3
    assert all(str(year) in '\n'.join(chart['source_excerpts']) for year in (2022, 2023, 2024))
    assert chart['pending_review'] is True
    assert '待复核' in chart['title'] and '预测值' in chart['note']
    assert 'pie' not in chart['chart_types']


def test_calculated_cagr_with_missing_or_mismatched_upstream_never_degrades_series():
    r1 = _auto_fact('r1', 'e1', 2022, '100')
    r2 = _auto_fact('r2', 'e2', 2023, '120')
    calculation = _cagr_record(
        [
            {'year': 2022, 'value': '100', 'forecast': False},
            {'year': 2023, 'value': '120', 'forecast': False},
            {'year': 2024, 'value': '150', 'forecast': False},
        ],
        ['r1', 'r2', 'r3'],
        ['e1', 'e2', 'e3'],
    )

    found = decision_charts({'decision_records': [r1, r2, calculation]})

    assert not any(item['kind'] == 'decision_auto_cagr' for item in found)
    assert {item['kind'] for item in found} == {'decision_auto_fact'}


def test_duplicate_auto_facts_merge_provenance_stably():
    first = _auto_fact('r1', 'e1', 2024, '504.4', grade='A')
    second = _auto_fact('r2', 'e2', 2024, '504.4', grade='B')

    forward = decision_charts({'decision_records': [first, second]})
    backward = decision_charts({'decision_records': [second, first]})

    assert forward == backward
    assert len(forward) == 1
    assert forward[0]['evidence_ids'] == ['e1', 'e2']
    assert forward[0]['source_grade'] == 'A/B'
    assert len(forward[0]['source_references']) == 2
