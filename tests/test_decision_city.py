from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.industry_research.decision_city import CityInputs, calculate_city


def fixture(*, basis='actual', verified=True, conflict=False):
    scope = '食品饮料瓦楞纸箱工厂选址（2025年同口径）'

    def fact(value, unit, city):
        return {
            'value': value,
            'unit': unit,
            'date': '2025-06-30',
            'source': f'{city}统计资料',
            'origin_id': f'official-{city}',
            'basis': basis,
            'verified': verified,
            'conflict': conflict,
            'scope': scope,
        }

    return CityInputs(
        scope=scope,
        cities=['苏州', '东莞', '嘉兴'],
        weights_confirmed=True,
        weight_rationale='经项目决策组确认的选址权重V1',
        indicators=[
            {
                'name': '目标客户密度',
                'weight': 60,
                'direction': 'higher_better',
                'unit': '家/百平方公里',
                'values': {
                    '苏州': fact(30, '家/百平方公里', '苏州'),
                    '东莞': fact(20, '家/百平方公里', '东莞'),
                    '嘉兴': fact(10, '家/百平方公里', '嘉兴'),
                },
            },
            {
                'name': '厂房租金',
                'weight': 40,
                'direction': 'lower_better',
                'unit': '元/平方米/月',
                'values': {
                    '苏州': fact(30, '元/平方米/月', '苏州'),
                    '东莞': fact(20, '元/平方米/月', '东莞'),
                    '嘉兴': fact(10, '元/平方米/月', '嘉兴'),
                },
            },
        ],
    )


def test_minmax_weighted_ranking_and_non_go_recommendation():
    result = calculate_city(fixture())

    assert result['results']['normalized_scores']['目标客户密度'] == {
        '苏州': '100', '东莞': '50.0', '嘉兴': '0',
    }
    assert result['results']['normalized_scores']['厂房租金'] == {
        '苏州': '0', '东莞': '50.0', '嘉兴': '100',
    }
    assert result['results']['weighted_scores'] == {
        '苏州': '60', '东莞': '50.0', '嘉兴': '40',
    }
    assert [row['city'] for row in result['results']['ranking']] == ['苏州', '东莞', '嘉兴']
    assert result['recommendation']['city'] == '苏州'
    assert result['decision'] is None
    assert result['status'] == '测算可复核（非投资结论）'


def test_missing_city_value_blocks_all_scoring():
    body = fixture()
    body.indicators[0].values['嘉兴'].value = None

    result = calculate_city(body)

    assert result['results'] == {}
    assert result['gaps'] == ['目标客户密度/嘉兴']
    assert result['recommendation'] is None
    assert result['decision'] is None


@pytest.mark.parametrize(
    ('change', 'expected'),
    [
        ({'basis': 'assumption'}, '情景测算'),
        ({'verified': False}, '情景测算'),
        ({'conflict': True}, '情景测算'),
        ({'source': ''}, '情景测算'),
        ({'origin_id': ''}, '情景测算'),
        ({'date': None}, '情景测算'),
    ],
)
def test_uncertain_input_allows_scenario_but_suppresses_recommendation(change, expected):
    body = fixture()
    fact = body.indicators[0].values['苏州']
    for key, value in change.items():
        setattr(fact, key, value)

    result = calculate_city(body)

    assert result['results']['ranking'][0]['city'] == '苏州'
    assert result['recommendation'] is None
    assert result['decision'] is None
    assert result['status'].startswith(expected)
    assert '目标客户密度/苏州' in result['pending']


def test_equal_indicator_values_are_neutral_and_ties_have_no_recommendation():
    body = fixture()
    for indicator in body.indicators:
        for fact in indicator.values.values():
            fact.value = Decimal('10')

    result = calculate_city(body)

    assert set(result['results']['weighted_scores'].values()) == {'50'}
    assert [row['rank'] for row in result['results']['ranking']] == [1, 1, 1]
    assert result['recommendation'] is None
    assert result['decision'] is None


@pytest.mark.parametrize('field', ['weights_confirmed', 'weight_rationale'])
def test_unconfirmed_or_unexplained_weights_suppress_recommendation(field):
    body = fixture()
    setattr(body, field, False if field == 'weights_confirmed' else '')

    result = calculate_city(body)

    assert result['results']['ranking'][0]['city'] == '苏州'
    assert result['recommendation'] is None
    assert result['decision'] is None
    assert any('权重' in item for item in result['pending'])


@pytest.mark.parametrize('mutation', ['weights', 'direction', 'unit', 'city', 'duplicate'])
def test_invalid_matrix_is_rejected(mutation):
    body = fixture().model_dump()
    if mutation == 'weights':
        body['indicators'][0]['weight'] = 59
    elif mutation == 'direction':
        body['indicators'][0]['direction'] = 'cheaper_better'
    elif mutation == 'unit':
        body['indicators'][0]['values']['苏州']['unit'] = '万元'
    elif mutation == 'city':
        body['indicators'][0]['values']['上海'] = body['indicators'][0]['values']['苏州']
    else:
        body['cities'][1] = '苏州'

    with pytest.raises(ValidationError):
        CityInputs.model_validate(body)


def test_requires_two_cities_and_two_indicators_and_rejects_numeric_text():
    body = fixture().model_dump()
    body['cities'] = ['苏州']
    with pytest.raises(ValidationError):
        CityInputs.model_validate(body)

    body = fixture().model_dump()
    body['indicators'] = body['indicators'][:1]
    body['indicators'][0]['weight'] = 100
    with pytest.raises(ValidationError):
        CityInputs.model_validate(body)

    body = fixture().model_dump()
    body['indicators'][0]['values']['苏州']['value'] = '30'
    with pytest.raises(ValidationError):
        CityInputs.model_validate(body)
