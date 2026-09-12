"""Deterministic, auditable city-site scoring for manufacturing studies.

The module performs arithmetic only.  It neither invents missing inputs nor
turns a weighted score into an investment (GO) decision.
"""

from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FactBasis = Literal['actual', 'quote', 'assumption', 'unverified']
Direction = Literal['higher_better', 'lower_better']


class CityValue(BaseModel):
    """One city's raw value for one indicator, including its provenance."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    value: Decimal | None
    unit: str = Field(min_length=1, max_length=60)
    date: Date | None = None
    source: str = Field(default='', max_length=1000)
    origin_id: str = Field(default='', max_length=300)
    basis: FactBasis = 'unverified'
    verified: bool = Field(default=False, strict=True)
    conflict: bool = Field(default=False, strict=True)
    # The request already has one global scope.  A per-value scope is optional,
    # but, when supplied, it must agree with that global statistical definition.
    scope: str = Field(default='', max_length=300)

    @field_validator('value', mode='before')
    @classmethod
    def reject_ambiguous_numeric_text(cls, value):
        if isinstance(value, (str, bool)):
            raise ValueError('value必须是JSON数值或null，不能是文本或布尔值')
        return value

    @field_validator('value')
    @classmethod
    def finite_value(cls, value: Decimal | None):
        if value is not None and not value.is_finite():
            raise ValueError('value必须是有限数值')
        return value


class CityIndicator(BaseModel):
    """One weighted criterion and the comparable raw values by city."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    weight: Decimal = Field(gt=0, le=100)
    direction: Direction
    unit: str = Field(min_length=1, max_length=60)
    values: dict[str, CityValue]

    @field_validator('weight', mode='before')
    @classmethod
    def reject_weight_text(cls, value):
        if isinstance(value, (str, bool)):
            raise ValueError('weight必须是JSON数值')
        return value


class CityInputs(BaseModel):
    """A single comparable city-selection scenario."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    scope: str = Field(min_length=2, max_length=300)
    cities: list[str] = Field(min_length=2)
    indicators: list[CityIndicator] = Field(min_length=2)
    weights_confirmed: bool = Field(default=False, strict=True)
    weight_rationale: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def validate_matrix(self):
        if len(set(self.cities)) != len(self.cities):
            raise ValueError('城市名称不得重复')
        if any(not city.strip() for city in self.cities):
            raise ValueError('城市名称不得为空')
        if len({item.name for item in self.indicators}) != len(self.indicators):
            raise ValueError('指标名称不得重复')
        if sum((item.weight for item in self.indicators), Decimal('0')) != Decimal('100'):
            raise ValueError('指标权重合计必须等于100')

        city_set = set(self.cities)
        for indicator in self.indicators:
            unknown = sorted(set(indicator.values) - city_set)
            if unknown:
                raise ValueError(f'{indicator.name}包含未声明城市：' + '、'.join(unknown))
            for city, fact in indicator.values.items():
                if fact.unit != indicator.unit:
                    raise ValueError(f'{indicator.name}/{city}单位不一致，应为{indicator.unit}')
                if fact.scope and fact.scope != self.scope:
                    raise ValueError(f'{indicator.name}/{city}适用范围与测算口径不一致')
        return self


def _base_result(body: CityInputs) -> dict:
    return {
        'status': '待验证',
        'decision': None,
        'recommendation': None,
        'gaps': [],
        'pending': [],
        'inputs': body.model_dump(mode='json'),
        'results': {},
        'formulas': {
            'higher_better': '(原始值−最小值)/(最大值−最小值)×100',
            'lower_better': '(最大值−原始值)/(最大值−最小值)×100',
            'equal_values': '同一指标所有城市值相同时，标准化分统一记50分',
            'weighted_score': 'Σ(指标标准化分×指标权重/100)',
        },
        'limitations': [
            '仅对本次输入的城市、指标、权重和统计口径作相对比较。',
            'Min-Max标准化对极端值敏感，新增或删除城市会改变全部标准化分。',
            '评分领先不等于已完成客户、土地、环保、供应链或财务尽调。',
            '本模块不自动给出GO；投资结论必须由企业结合门槛和尽调人工决定。',
        ],
    }


def calculate_city(body: CityInputs) -> dict:
    """Min-Max normalise, weight and rank a complete city matrix.

    Missing values stop calculation.  Assumptions, unverified values and
    conflicts may still be calculated as an explicitly labelled scenario, but
    they suppress the programmatic city recommendation.
    """

    result = _base_result(body)
    if not body.weights_confirmed:
        result['pending'].append('指标权重尚未由企业确认')
    if not body.weight_rationale.strip():
        result['pending'].append('缺少指标权重依据')
    for indicator in body.indicators:
        for city in body.cities:
            key = f'{indicator.name}/{city}'
            fact = indicator.values.get(city)
            if fact is None or fact.value is None:
                result['gaps'].append(key)
                continue
            if (
                not fact.verified
                or fact.conflict
                or fact.basis in ('assumption', 'unverified')
                or not fact.source.strip()
                or not fact.origin_id.strip()
                or fact.date is None
            ):
                result['pending'].append(key)

    # A partial matrix would create incomparable totals, so emit no scores.
    if result['gaps']:
        return result

    normalized: dict[str, dict[str, Decimal]] = {}
    totals = {city: Decimal('0') for city in body.cities}
    for indicator in body.indicators:
        raw = {city: indicator.values[city].value for city in body.cities}
        low, high = min(raw.values()), max(raw.values())
        if high == low:
            scores = {city: Decimal('50') for city in body.cities}
        elif indicator.direction == 'higher_better':
            scores = {
                city: (value - low) / (high - low) * Decimal('100')
                for city, value in raw.items()
            }
        else:
            scores = {
                city: (high - value) / (high - low) * Decimal('100')
                for city, value in raw.items()
            }
        normalized[indicator.name] = scores
        for city, score in scores.items():
            totals[city] += score * indicator.weight / Decimal('100')

    ordered = sorted(body.cities, key=lambda city: (-totals[city], body.cities.index(city)))
    ranking = []
    prior_score: Decimal | None = None
    prior_rank = 0
    for position, city in enumerate(ordered, 1):
        if prior_score is None or totals[city] != prior_score:
            prior_rank = position
        ranking.append({'rank': prior_rank, 'city': city, 'weighted_score': str(totals[city])})
        prior_score = totals[city]

    result['results'] = {
        'normalized_scores': {
            indicator: {city: str(score) for city, score in city_scores.items()}
            for indicator, city_scores in normalized.items()
        },
        'weighted_scores': {city: str(totals[city]) for city in body.cities},
        'ranking': ranking,
    }

    if result['pending']:
        result['status'] = '情景测算（含未核实、冲突或假设输入，待验证）'
        return result

    if len(ordered) > 1 and totals[ordered[0]] == totals[ordered[1]]:
        result['status'] = '测算可复核（最高分并列，非投资结论）'
        result['pending'].append('最高分并列，无法形成唯一评分领先城市')
        return result

    result['status'] = '测算可复核（非投资结论）'
    result['recommendation'] = {
        'city': ordered[0],
        'label': '程序评分领先（仍需人工决策）',
    }
    return result
