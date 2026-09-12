"""Deterministic TAM/SAM/SOM calculation for manufacturing entry studies.

The model intentionally does not infer, search for, or invent an input.  Every
number remains attached to its unit, scope, year, source and evidence basis.
"""

from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FactBasis = Literal['actual', 'quote', 'assumption', 'unverified']


class MarketFact(BaseModel):
    """One auditable input to the market-sizing calculation."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    value: Decimal | None
    unit: str = Field(min_length=1, max_length=60)
    scope: str = Field(min_length=1, max_length=300)
    year: int = Field(strict=True, ge=2000, le=2100)
    source: str = Field(max_length=1000)
    origin_id: str = Field(default='', max_length=300)
    date: Date | None = None
    basis: FactBasis
    verified: bool = Field(strict=True)
    conflict: bool = Field(default=False, strict=True)

    @field_validator('value', mode='before')
    @classmethod
    def reject_non_numeric_text(cls, value):
        # API callers must send a JSON number (or null), not an ambiguous string.
        if isinstance(value, (str, bool)):
            raise ValueError('value必须是数值或null，不能是文本或布尔值')
        return value

    @field_validator('value')
    @classmethod
    def non_negative(cls, value: Decimal | None):
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError('value必须是有限的非负数')
        return value


class MarketInputs(BaseModel):
    """Inputs for one product, geography, year and statistical definition."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    scope: str = Field(min_length=2, max_length=300)
    year: int = Field(strict=True, ge=2000, le=2100)
    base_unit: str = Field(min_length=1, max_length=30)
    demand_unit: str = Field(min_length=1, max_length=30)
    facts: dict[str, MarketFact]

    @model_validator(mode='after')
    def validate_dimensions(self):
        expected_units = {
            'base': self.base_unit,
            'unit_demand': f'{self.demand_unit}/{self.base_unit}',
            'unit_price': f'元/{self.demand_unit}',
            'regional_coverage_pct': '%',
            'product_fit_pct': '%',
            'service_coverage_pct': '%',
            'acquisition_rate_pct': '%',
            'effective_capacity': self.demand_unit,
        }
        unknown = sorted(set(self.facts) - set(expected_units))
        if unknown:
            raise ValueError('未知指标：' + '、'.join(unknown))

        for key, fact in self.facts.items():
            expected = expected_units[key]
            if fact.unit != expected:
                raise ValueError(f'{key}单位不兼容：应为{expected}')
            if fact.scope != self.scope:
                raise ValueError(f'{key}适用范围与本次测算口径不一致')
            if fact.year != self.year:
                raise ValueError(f'{key}年份与本次测算年份不一致')
            if key.endswith('_pct') and fact.value is not None and fact.value > 100:
                raise ValueError(f'{key}必须使用0—100的百分比')
        return self


REQUIRED_FACTS = (
    'base',
    'unit_demand',
    'unit_price',
    'regional_coverage_pct',
    'product_fit_pct',
    'service_coverage_pct',
    'acquisition_rate_pct',
    'effective_capacity',
)


def _blank_result(body: MarketInputs) -> dict:
    return {
        'status': '待验证',
        'decision': None,
        'gaps': [],
        'pending': [],
        'inputs': body.model_dump(mode='json'),
        'results': {},
        'formulas': {
            'tam': '基数×单位需求×单位价格',
            'sam': 'TAM×地域覆盖率×产品适配率×可服务覆盖率',
            'som': 'min(SAM×预计获取率, 有效产能×单位价格)',
        },
        'limitations': [
            '百分比输入采用0—100，计算时由程序除以100。',
            '仅适用于同一产品、地域组合、年份和统计口径；不同口径必须分别测算。',
            'SOM只受给定获取率和有效产能约束，不代表已取得客户订单。',
            '本模块只计算市场空间，不自动给出GO或其他投资结论。',
        ],
    }


def calculate_market(body: MarketInputs) -> dict:
    """Calculate TAM/SAM/SOM only when all required inputs are usable.

    A missing value, an unverified fact, a blank source or an explicitly
    unverified basis prevents calculation.  Verified assumptions may be used
    for a labelled scenario, but keep the result in ``待验证`` status.
    """

    result = _blank_result(body)
    for key in REQUIRED_FACTS:
        fact = body.facts.get(key)
        if fact is None or fact.value is None:
            result['gaps'].append(key)
            continue
        if (not fact.verified or fact.conflict or not fact.source.strip()
                or not fact.origin_id.strip() or fact.date is None or fact.basis == 'unverified'):
            result['pending'].append(key)

    # Do not turn absent or unreviewed evidence into apparently precise output.
    if result['gaps'] or result['pending']:
        return result

    values = {key: body.facts[key].value for key in REQUIRED_FACTS}
    hundred = Decimal('100')
    tam = values['base'] * values['unit_demand'] * values['unit_price']
    sam = (
        tam
        * values['regional_coverage_pct'] / hundred
        * values['product_fit_pct'] / hundred
        * values['service_coverage_pct'] / hundred
    )
    demand_limited_som = sam * values['acquisition_rate_pct'] / hundred
    capacity_limited_som = values['effective_capacity'] * values['unit_price']
    som = min(demand_limited_som, capacity_limited_som)

    result['results'] = {
        'tam_yuan': str(tam),
        'sam_yuan': str(sam),
        'som_yuan': str(som),
        'som_demand_ceiling_yuan': str(demand_limited_som),
        'som_capacity_ceiling_yuan': str(capacity_limited_som),
        'binding_constraint': (
            '有效产能'
            if capacity_limited_som < demand_limited_som
            else '市场获取率'
            if demand_limited_som < capacity_limited_som
            else '市场获取率与有效产能'
        ),
    }

    assumptions = [
        key for key in REQUIRED_FACTS if body.facts[key].basis == 'assumption'
    ]
    if assumptions:
        result['pending'] = assumptions
        result['status'] = '情景测算（含已确认假设，待验证）'
    else:
        result['status'] = '测算可复核（非投资结论）'
    return result
