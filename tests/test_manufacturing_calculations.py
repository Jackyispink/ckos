from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.industry_research.manufacturing_calculations import ManufacturingScenario, calculate


def scenario(**changes):
    values = dict(product='减速器', period='2025全年', quantity_unit='台', currency='元',
                  source='测试假设', effective_capacity=100, output=80, sales=70,
                  unit_price=100, unit_variable_cost=60, fixed_cost=1000, price_change_pct=-10)
    return ManufacturingScenario(**(values | changes))


def test_known_results():
    result = calculate(scenario())
    assert Decimal(result['utilization_pct']) == 80
    assert Decimal(result['baseline']['modeled_gross_profit']) == 1800
    assert Decimal(result['scenario']['modeled_gross_profit']) == 1100


@pytest.mark.parametrize('changes', [dict(effective_capacity=0), dict(output=-1),
                                   dict(unit_price='NaN'), dict(source=' '),
                                   dict(price_change_pct=-101)])
def test_invalid_inputs(changes):
    with pytest.raises(ValidationError):
        scenario(**changes)


def test_zero_revenue_and_capacity_warning():
    result = calculate(scenario(output=110, price_change_pct=-100))
    assert result['scenario']['modeled_gross_margin_pct'] is None
    assert any('超过100%' in warning for warning in result['warnings'])
    assert calculate(scenario(sales=0))['baseline']['modeled_gross_margin_pct'] is None


def test_project_save_recalculates_and_isolates(monkeypatch):
    from app.industry_research import router
    saved = {}
    monkeypatch.setattr(router.writer, 'is_running', lambda _: False)
    def save(project_id, result):
        saved[project_id] = result
        return True
    monkeypatch.setattr(router.database, 'save_manufacturing_scenario', save)
    monkeypatch.setattr(router.database, 'project', lambda pid: {'manufacturing_scenario': saved.get(pid)})
    result = router.save_manufacturing_scenario('project-a', scenario())
    assert result == calculate(scenario())
    assert router.get_manufacturing_scenario('project-a') == result
    assert router.get_manufacturing_scenario('project-b') is None


def test_save_rejects_running_and_missing_project(monkeypatch):
    from fastapi import HTTPException
    from app.industry_research import router
    monkeypatch.setattr(router.writer, 'is_running', lambda _: True)
    with pytest.raises(HTTPException) as error:
        router.save_manufacturing_scenario('a', scenario())
    assert error.value.status_code == 409
    monkeypatch.setattr(router.writer, 'is_running', lambda _: False)
    monkeypatch.setattr(router.database, 'save_manufacturing_scenario', lambda *args: False)
    with pytest.raises(HTTPException) as error:
        router.save_manufacturing_scenario('a', scenario())
    assert error.value.status_code == 404
