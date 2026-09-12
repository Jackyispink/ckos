import pytest
from pydantic import ValidationError

from app.industry_research.decision_gate import DecisionGateInputs, calculate_gate


def metric(name, value, *, direction='higher_better', go=70, no_go=50, **overrides):
    item = {
        'stage': '量产验证',
        'name': name,
        'current': {
            'value': value,
            'unit': '%',
            'date': '2026-09-08',
            'source': '客户验证台账',
            'origin_id': 'interview-batch-01',
            'basis': 'actual',
            'verified': True,
            'conflict': False,
        },
        'direction': direction,
        'go_threshold': go,
        'no_go_threshold': no_go,
        'threshold_source': '经管理层确认的项目门槛V1',
        'threshold_confirmed': True,
    }
    for key, value in overrides.items():
        if key.startswith('current__'):
            item['current'][key.removeprefix('current__')] = value
        else:
            item[key] = value
    return item


def calculate(*metrics):
    return calculate_gate(DecisionGateInputs(metrics=list(metrics)))


def test_higher_better_boundary_and_all_go():
    result = calculate(metric('利用率', 70), metric('良率', 98, go=98, no_go=94))

    assert [item['state'] for item in result['metrics']] == ['GO', 'GO']
    assert result['scenario_state'] == 'GO'
    assert result['decision'] == 'GO'
    assert result['status'] == '门槛判定完成'


def test_lower_better_and_hold():
    result = calculate(metric('应收账款天数', 75, direction='lower_better', go=60, no_go=90))

    assert result['metrics'][0]['state'] == 'HOLD'
    assert result['scenario_state'] == 'HOLD'


def test_any_no_go_overrides_go_and_hold():
    result = calculate(
        metric('利用率', 80),
        metric('毛利率', 60),
        metric('应收账款天数', 100, direction='lower_better', go=60, no_go=90),
    )

    assert result['metrics'][-1]['state'] == 'NO-GO'
    assert result['scenario_state'] == 'NO-GO'
    assert result['decision'] == 'NO-GO'


@pytest.mark.parametrize(
    ('override', 'expected'),
    [
        ({'current__value': None}, 'current.value'),
        ({'current__verified': False}, 'current.verified'),
        ({'current__conflict': True}, 'current.conflict'),
        ({'current__source': ''}, 'current.source'),
        ({'current__origin_id': ''}, 'current.origin_id'),
        ({'current__date': None}, 'current.date'),
        ({'current__basis': 'unverified'}, 'current.basis'),
        ({'current__basis': 'assumption'}, 'current.basis'),
        ({'go_threshold': None}, 'go_threshold'),
        ({'no_go_threshold': None}, 'no_go_threshold'),
        ({'threshold_source': ''}, 'threshold_source'),
        ({'threshold_confirmed': False}, 'threshold_confirmed'),
    ],
)
def test_any_missing_unverified_conflicting_or_unconfirmed_input_blocks_decision(override, expected):
    result = calculate(metric('利用率', 80, **override))

    assert result['metrics'][0]['state'] == '待验证'
    assert result['scenario_state'] == '待验证'
    assert result['decision'] is None
    assert any(expected in item for item in result['gaps'] + result['pending'])


def test_one_pending_metric_blocks_overall_even_if_other_metric_is_go():
    result = calculate(
        metric('利用率', 80),
        metric('毛利率', 75, threshold_confirmed=False),
    )

    assert result['metrics'][0]['state'] == 'GO'
    assert result['metrics'][1]['state'] == '待验证'
    assert result['decision'] is None
    assert result['scenario_state'] == '待验证'


@pytest.mark.parametrize(
    'item',
    [
        metric('利用率', 60, direction='higher_better', go=50, no_go=50),
        metric('应收天数', 60, direction='lower_better', go=90, no_go=60),
    ],
)
def test_invalid_or_overlapping_threshold_order_is_rejected(item):
    with pytest.raises(ValidationError):
        DecisionGateInputs(metrics=[item])


def test_no_embedded_default_thresholds():
    item = metric('利用率', 80)
    item.pop('go_threshold')
    item.pop('no_go_threshold')
    result = calculate_gate(DecisionGateInputs(metrics=[item]))

    assert result['decision'] is None
    assert result['metrics'][0]['go_threshold'] is None
    assert result['metrics'][0]['no_go_threshold'] is None


def test_reviewed_calculated_value_can_feed_gate_but_numeric_text_is_rejected():
    result = calculate(metric('利用率', 80, current__basis='calculated',
                              current__source='财务测算记录 finance-01'))
    assert result['decision'] == 'GO'

    item = metric('利用率', 80)
    item['current']['value'] = '80'
    with pytest.raises(ValidationError):
        DecisionGateInputs(metrics=[item])


def test_duplicate_stage_and_metric_name_is_rejected():
    item = metric('利用率', 80)
    with pytest.raises(ValidationError):
        DecisionGateInputs(metrics=[item, item])


def test_verified_program_calculation_can_feed_a_gate_but_numeric_text_is_rejected():
    result = calculate(metric('产能利用率', 80, current__basis='calculated'))
    assert result['decision'] == 'GO'

    item = metric('产能利用率', 80)
    item['current']['value'] = '80'
    with pytest.raises(ValidationError):
        DecisionGateInputs(metrics=[item])
