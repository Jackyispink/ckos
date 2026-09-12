"""Deterministic, same-period manufacturing scenarios; no model or persistence."""
from decimal import Decimal

from pydantic import BaseModel, Field, ConfigDict, field_validator


class ManufacturingScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product: str = Field(min_length=1, max_length=120)
    period: str = Field(min_length=1, max_length=80)
    quantity_unit: str = Field(min_length=1, max_length=30)
    currency: str = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=500)
    effective_capacity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    output: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    sales: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    unit_price: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    unit_variable_cost: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    fixed_cost: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    price_change_pct: Decimal = Field(ge=-100, le=1000)

    @field_validator('product', 'period', 'quantity_unit', 'currency', 'source')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()


def calculate(body: ManufacturingScenario):
    def economics(price):
        revenue = body.sales * price
        cost = body.sales * body.unit_variable_cost + body.fixed_cost
        profit = revenue - cost
        return {'revenue': str(revenue), 'modeled_gross_profit': str(profit),
                'modeled_gross_margin_pct': str(profit / revenue * 100) if revenue else None}

    warnings = ['简化情景测算，不等同于财报毛利：假设单位变动成本、销量和当期固定制造成本不变；未模拟存货成本结转、税费及期间费用。',
                '产能、产量、销量及固定成本须为同一期间、同一产品范围；单价和单位变动成本须同币种、同数量单位、同税口径。来源由用户提供，程序未验证。']
    if body.output > body.effective_capacity:
        warnings.append('产能利用率超过100%，请核对有效产能、班次与统计期间。')
    if body.sales > body.output:
        warnings.append('销量超过当期产量，请核对期初存货或外购转售，不应直接视为错误。')
    return {'inputs': body.model_dump(mode='json'),
            'utilization_pct': str(body.output / body.effective_capacity * 100),
            'baseline': economics(body.unit_price),
            'scenario': economics(body.unit_price * (1 + body.price_change_pct / 100)),
            'formulas': ['产能利用率 = 当期产量 ÷ 当期有效产能 × 100%',
                         '收入 = 销量 × 单价', '测算毛利 = 收入 − 销量 × 单位变动成本 − 当期固定制造成本',
                         '测算毛利率 = 测算毛利 ÷ 收入 × 100%（收入为0时不计算）',
                         '情景单价 = 基准单价 × (1 + 价格变化百分比 ÷ 100)'],
            'warnings': warnings}
