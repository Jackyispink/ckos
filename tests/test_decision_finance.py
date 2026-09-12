from app.industry_research.decision_finance import FinanceInputs, calculate_finance


def fixture():
    units=['台','台','元/台','元/台','元/年','元/年','元','元/年','天','天','天']
    keys=['sales','capacity','price','variable_cost','fixed_cash_cost','depreciation','capex','annual_credit_purchases','receivable_days','inventory_days','payable_days']
    values=[100,200,100,60,1000,1000,10000,6000,90,15,30]
    return FinanceInputs(scope='产品A',year=2025,quantity_unit='台',facts={k:dict(value=v,unit=u,scope='产品A',basis='assumption') for k,u,v in zip(keys,units,values)})


def test_arithmetic_and_no_go():
    result=calculate_finance(fixture())
    assert result['results']['operating_profit']=='2000'
    assert result['results']['breakeven_quantity']=='50'
    assert result['results']['ccc_days']=='75'
    assert result['decision'] is None and result['status']=='待验证'


def test_missing_is_not_zero():
    body=fixture();del body.facts['capex']
    result=calculate_finance(body)
    assert result['results']=={} and 'capex' in result['gaps']


def test_nonpositive_contribution():
    body=fixture();body.facts['variable_cost'].value=120
    assert calculate_finance(body)['results']['breakeven_quantity'] is None
