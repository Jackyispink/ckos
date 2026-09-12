"""Annual, single-product decision model. All amounts in yuan, quantities in one declared unit."""
from datetime import date as Date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Fact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    unit: str
    scope: str
    date: Date | None = None
    source: str = ''
    origin_id: str = ''  # Same original source keeps the same ID across republications.
    basis: Literal['actual', 'quote', 'assumption', 'unverified'] = 'unverified'
    verified: bool = False
    conflict: bool = False


class FinanceInputs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: str = Field(min_length=2, max_length=200)
    year: int = Field(ge=2000, le=2100)
    quantity_unit: str = Field(min_length=1, max_length=30)
    facts: dict[str, Fact]

    @model_validator(mode='after')
    def units(self):
        expected = {'sales': self.quantity_unit, 'capacity': self.quantity_unit,
                    'price': '元/'+self.quantity_unit, 'variable_cost': '元/'+self.quantity_unit,
                    'fixed_cash_cost': '元/年', 'depreciation': '元/年', 'capex': '元',
                    'annual_credit_purchases': '元/年', 'receivable_days': '天',
                    'inventory_days': '天', 'payable_days': '天'}
        for key, fact in self.facts.items():
            if key not in expected:
                raise ValueError('未知指标：'+key)
            if fact.unit != expected[key] or fact.scope != self.scope:
                raise ValueError(key+'的单位或适用范围与模型不一致')
        return self


REQUIRED = ('sales','capacity','price','variable_cost','fixed_cash_cost','depreciation',
            'capex','annual_credit_purchases','receivable_days','inventory_days','payable_days')


def calculate_finance(body: FinanceInputs):
    gaps, pending = [], []
    for key in REQUIRED:
        fact = body.facts.get(key)
        if fact is None or fact.value is None:
            gaps.append(key)
        elif (not fact.verified or fact.conflict or not fact.source.strip() or not fact.date
              or not fact.origin_id.strip() or fact.basis in ('assumption','unverified')):
            pending.append(key)
    result = {'status': '待验证', 'decision': None, 'gaps': gaps, 'pending': pending,
              'inputs': body.model_dump(mode='json'), 'results': {},
              'limitations': ['年度单产品简化情景；同一数量单位、人民币元、不含税。',
                             '销量视为当期生产并售出数量；不模拟存货增减及爬坡月度现金流。',
                             '测算营业利润不含利息和所得税，不能称为净利润。',
                             '营运资金仅覆盖应收、存货、应付，不含现金储备、预付款及建设期支出。',
                             '不自动给GO：尚需客户、报价、合规、现金安全垫及企业决策阈值验证。']}
    if gaps:
        return result
    v = {k: body.facts[k].value for k in REQUIRED}
    if v['capacity'] <= 0 or v['price'] <= 0:
        result['gaps'].append('产能和售价必须大于零')
        return result
    revenue = v['sales'] * v['price']
    cash_cost = v['sales'] * v['variable_cost'] + v['fixed_cash_cost']
    cost = cash_cost + v['depreciation']
    contribution = v['price'] - v['variable_cost']
    breakeven = (v['fixed_cash_cost'] + v['depreciation']) / contribution if contribution > 0 else None
    ar = revenue * v['receivable_days'] / 365
    inventory = cost * v['inventory_days'] / 365
    ap = v['annual_credit_purchases'] * v['payable_days'] / 365
    working = ar + inventory - ap
    numbers = dict(revenue=revenue, cash_operating_cost=cash_cost, operating_profit=revenue-cost,
                   unit_contribution=contribution, utilization_pct=v['sales']/v['capacity']*100,
                   breakeven_quantity=breakeven,
                   breakeven_utilization_pct=breakeven/v['capacity']*100 if breakeven is not None else None,
                   ccc_days=v['receivable_days']+v['inventory_days']-v['payable_days'],
                   receivables=ar, inventory=inventory, payables=ap, net_working_capital=working,
                   initial_funding_floor=v['capex']+max(working,Decimal(0)))
    result['results'] = {k: str(v) if v is not None else None for k,v in numbers.items()}
    result['formulas'] = {'operating_profit':'销量×(售价−单位变动成本)−固定现金经营成本−折旧',
                          'breakeven_quantity':'(固定现金经营成本+折旧)/(售价−单位变动成本)，贡献非正时无可实现盈亏平衡',
                          'net_working_capital':'收入×应收天数/365 + 含折旧成本×库存天数/365 − 年赊购额×应付天数/365',
                          'initial_funding_floor':'CAPEX + max(净营运资金,0)，仅为资金需求下限'}
    if v['sales'] > v['capacity']:
        result['pending'].append('销量超过有效产能，请核对外购转售或产能口径')
    if not result['pending']:
        result['status'] = '测算可复核（非投资结论）'
    return result
