from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.industry_research.decision_market import MarketInputs, calculate_market


KEYS = (
    'base',
    'unit_demand',
    'unit_price',
    'regional_coverage_pct',
    'product_fit_pct',
    'service_coverage_pct',
    'acquisition_rate_pct',
    'effective_capacity',
)
UNITS = ('件', '平方米/件', '元/平方米', '%', '%', '%', '%', '平方米')
VALUES = (1000, 2, 3, 50, 80, 75, 20, 100)


def fixture(*, basis='actual', verified=True):
    scope = '中国食品饮料瓦楞运输箱（目标区域可服务口径）'
    return MarketInputs(
        scope=scope,
        year=2025,
        base_unit='件',
        demand_unit='平方米',
        facts={
            key: {
                'value': value,
                'unit': unit,
                'scope': scope,
                'year': 2025,
                'source': '测试来源',
                'origin_id': 'source-' + key,
                'date': '2025-12-31',
                'basis': basis,
                'verified': verified,
                'conflict': False,
            }
            for key, unit, value in zip(KEYS, UNITS, VALUES)
        },
    )


def test_verified_inputs_calculate_tam_sam_som_without_go():
    result = calculate_market(fixture())

    assert result['results']['tam_yuan'] == '6000'
    assert Decimal(result['results']['sam_yuan']) == Decimal('1800')
    assert Decimal(result['results']['som_demand_ceiling_yuan']) == Decimal('360')
    assert result['results']['som_capacity_ceiling_yuan'] == '300'
    assert result['results']['som_yuan'] == '300'
    assert result['results']['binding_constraint'] == '有效产能'
    assert result['status'] == '测算可复核（非投资结论）'
    assert result['decision'] is None


def test_missing_input_returns_gap_and_no_pseudo_value():
    body = fixture()
    del body.facts['unit_demand']

    result = calculate_market(body)

    assert result['results'] == {}
    assert result['gaps'] == ['unit_demand']
    assert result['decision'] is None


def test_unverified_input_is_pending_and_blocks_calculation():
    body = fixture()
    body.facts['regional_coverage_pct'].verified = False

    result = calculate_market(body)

    assert result['results'] == {}
    assert result['pending'] == ['regional_coverage_pct']
    assert result['status'] == '待验证'


@pytest.mark.parametrize(('field', 'value'), [('origin_id', ''), ('date', None), ('conflict', True)])
def test_missing_provenance_or_conflict_blocks_market_calculation(field, value):
    body = fixture()
    setattr(body.facts['base'], field, value)
    result = calculate_market(body)
    assert result['results'] == {}
    assert result['pending'] == ['base']


def test_verified_assumptions_are_calculated_but_remain_pending():
    result = calculate_market(fixture(basis='assumption'))

    assert result['results']['tam_yuan'] == '6000'
    assert result['pending'] == list(KEYS)
    assert result['status'] == '情景测算（含已确认假设，待验证）'
    assert result['decision'] is None


@pytest.mark.parametrize(
    ('key', 'field', 'value'),
    [
        ('base', 'unit', '吨'),
        ('base', 'scope', '另一个市场'),
        ('base', 'year', 2024),
        ('regional_coverage_pct', 'value', 101),
    ],
)
def test_incompatible_units_scope_year_or_percentage_are_rejected(key, field, value):
    body = fixture().model_dump()
    body['facts'][key][field] = value

    with pytest.raises(ValidationError):
        MarketInputs.model_validate(body)


def test_numeric_text_and_unknown_fact_are_rejected():
    body = fixture().model_dump()
    body['facts']['base']['value'] = '1000'
    with pytest.raises(ValidationError):
        MarketInputs.model_validate(body)

    body = fixture().model_dump()
    body['facts']['invented_metric'] = body['facts']['base']
    with pytest.raises(ValidationError):
        MarketInputs.model_validate(body)


def test_decimal_inputs_preserve_deterministic_precision():
    body = fixture()
    body.facts['base'].value = Decimal('10.5')
    result = calculate_market(body)
    assert result['results']['tam_yuan'] == '63.0'
