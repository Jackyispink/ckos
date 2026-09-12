"""Deterministic staged GO/HOLD/NO-GO decision gates.

The module deliberately contains no industry defaults.  Both the observed
value and the two decision thresholds must be supplied with review metadata;
otherwise the scenario remains ``待验证`` and no investment decision is
returned.
"""

from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Direction = Literal['higher_better', 'lower_better']
GateState = Literal['GO', 'HOLD', 'NO-GO', '待验证']
FactBasis = Literal['actual', 'quote', 'assumption', 'calculated', 'unverified']


class GateFact(BaseModel):
    """A current metric value with enough provenance to audit it."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    value: Decimal | None = None
    unit: str = Field(min_length=1, max_length=60)
    date: Date | None = None
    source: str = Field(default='', max_length=1000)
    origin_id: str = Field(default='', max_length=300)
    basis: FactBasis = 'unverified'
    verified: bool = False
    conflict: bool = False

    @field_validator('value', mode='before')
    @classmethod
    def reject_ambiguous_numeric_text(cls, value):
        if isinstance(value, (str, bool)):
            raise ValueError('当前值必须是JSON数值或null，不能是文本或布尔值')
        return value

    @field_validator('value')
    @classmethod
    def finite_value(cls, value: Decimal | None):
        if value is not None and not value.is_finite():
            raise ValueError('当前值必须是有限数值')
        return value


class GateMetric(BaseModel):
    """One user-defined decision threshold; no defaults are inferred."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    stage: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    current: GateFact
    direction: Direction
    go_threshold: Decimal | None = None
    no_go_threshold: Decimal | None = None
    threshold_source: str = Field(default='', max_length=1000)
    threshold_confirmed: bool = False

    @field_validator('go_threshold', 'no_go_threshold')
    @classmethod
    def finite_threshold(cls, value: Decimal | None):
        if value is not None and not value.is_finite():
            raise ValueError('门槛必须是有限数值')
        return value

    @model_validator(mode='after')
    def validate_threshold_order(self):
        # Missing thresholds are a research gap, not a malformed request.  If
        # both values exist, however, an inverted/overlapping interval would
        # make HOLD ambiguous and must be rejected.
        if self.go_threshold is None or self.no_go_threshold is None:
            return self
        if self.direction == 'higher_better' and self.go_threshold <= self.no_go_threshold:
            raise ValueError('higher_better指标必须满足GO阈值大于NO-GO阈值')
        if self.direction == 'lower_better' and self.go_threshold >= self.no_go_threshold:
            raise ValueError('lower_better指标必须满足GO阈值小于NO-GO阈值')
        return self


class DecisionGateInputs(BaseModel):
    model_config = ConfigDict(extra='forbid')

    metrics: list[GateMetric] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_metrics(self):
        keys = [(item.stage, item.name) for item in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError('同一阶段的指标名称不能重复')
        return self


def _pending_reasons(metric: GateMetric) -> tuple[list[str], list[str]]:
    """Return missing-value gaps and unreviewed/conflicting inputs."""

    gaps: list[str] = []
    pending: list[str] = []
    if metric.current.value is None:
        gaps.append('current.value')
    if metric.go_threshold is None:
        gaps.append('go_threshold')
    if metric.no_go_threshold is None:
        gaps.append('no_go_threshold')

    fact = metric.current
    if fact.value is not None:
        if not fact.verified:
            pending.append('current.verified')
        if fact.conflict:
            pending.append('current.conflict')
        if fact.basis in ('assumption', 'unverified'):
            pending.append('current.basis')
        if not fact.source:
            pending.append('current.source')
        if not fact.origin_id:
            pending.append('current.origin_id')
        if fact.date is None:
            pending.append('current.date')
    if not metric.threshold_confirmed:
        pending.append('threshold_confirmed')
    if not metric.threshold_source:
        pending.append('threshold_source')
    return gaps, pending


def _classify(metric: GateMetric) -> Literal['GO', 'HOLD', 'NO-GO']:
    value = metric.current.value
    go = metric.go_threshold
    no_go = metric.no_go_threshold
    # Called only after gap checks; the assertions document that invariant and
    # keep the arithmetic below explicit to type checkers/readers.
    assert value is not None and go is not None and no_go is not None
    if metric.direction == 'higher_better':
        if value >= go:
            return 'GO'
        if value <= no_go:
            return 'NO-GO'
    else:
        if value <= go:
            return 'GO'
        if value >= no_go:
            return 'NO-GO'
    return 'HOLD'


def calculate_gate(body: DecisionGateInputs) -> dict:
    """Evaluate every gate and then aggregate it with conservative precedence."""

    items = []
    all_gaps: list[str] = []
    all_pending: list[str] = []
    completed_states: list[str] = []

    for metric in body.metrics:
        gaps, pending = _pending_reasons(metric)
        if gaps or pending:
            state: GateState = '待验证'
        else:
            state = _classify(metric)
            completed_states.append(state)

        prefix = f'{metric.stage}/{metric.name}'
        all_gaps.extend(f'{prefix}:{item}' for item in gaps)
        all_pending.extend(f'{prefix}:{item}' for item in pending)
        items.append({
            'stage': metric.stage,
            'name': metric.name,
            'state': state,
            'current_value': str(metric.current.value) if metric.current.value is not None else None,
            'unit': metric.current.unit,
            'direction': metric.direction,
            'go_threshold': str(metric.go_threshold) if metric.go_threshold is not None else None,
            'no_go_threshold': (
                str(metric.no_go_threshold) if metric.no_go_threshold is not None else None
            ),
            'gaps': gaps,
            'pending': pending,
        })

    if all_gaps or all_pending:
        decision = None
        scenario_state: GateState = '待验证'
        status = '待验证'
    else:
        if 'NO-GO' in completed_states:
            scenario_state = 'NO-GO'
        elif all(state == 'GO' for state in completed_states):
            scenario_state = 'GO'
        else:
            scenario_state = 'HOLD'
        decision = scenario_state
        status = '门槛判定完成'

    return {
        'status': status,
        'decision': decision,
        'scenario_state': scenario_state,
        'metrics': items,
        'gaps': all_gaps,
        'pending': all_pending,
        'inputs': body.model_dump(mode='json'),
        'rules': {
            'metric': '达到GO阈值为GO，触及NO-GO阈值为NO-GO，中间区间为HOLD。',
            'overall': '任一NO-GO则整体NO-GO；全部GO才整体GO；其余为HOLD。',
            'evidence_gate': '任一当前值或门槛缺失、未核实、冲突或未确认时不输出决策。',
        },
        'limitations': [
            '本模块不包含任何行业默认阈值，阈值必须由用户或可追溯证据提供并确认。',
            '假设值只能用于情景观察；程序计算值须引用其上游测算记录并经人工核对。',
            '程序只执行门槛比较，不替代客户验证、报价、合规审查和投资委员会判断。',
        ],
    }
