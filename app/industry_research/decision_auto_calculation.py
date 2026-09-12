"""Safe automatic calculations over evidence-backed decision records.

The module deliberately starts with one high-value calculation: CAGR.  It
does not ask a model to perform arithmetic and it does not coerce estimates,
ranges, bounds or conflicting observations into precise point values.  Empty
inputs become research gaps and never block ordinary report generation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from . import database
from .decision_extraction import MEASURE_RE
from .evidence_grading import classify
from .evidence_review import usable


CALCULATOR_VERSION = 'decision-auto-calc-20260909-v1'
YEAR_RE = re.compile(r'(?<!\d)(20\d{2})(?!\d)')
AMBIGUOUS_RE = re.compile(
    r'(?:大约|约为|约有|约(?:人民币)?\s*(?=\d)|近(?:人民币)?\s*(?=\d)|'
    r'接近|左右|上下|超过|超出|突破|超(?=\s*\d)|逾(?=\s*\d)|'
    r'高于|低于|多于|少于|不足|至少|至多|不低于|不高于|不少于|'
    r'不超过|以上|以下|区间|范围)'
)
RANGE_RE = re.compile(
    r'(?<!\d)\d+(?:\.\d+)?\s*(?:[-~～—–至到])\s*\d+(?:\.\d+)?(?!\d)'
)
GENERIC_SCOPES = {'', '仅限原文引文所述口径', '原文口径', '待确认', '待验证'}


def _fields(row: dict) -> dict:
    value = row.get('fields') or {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normal(text: Any) -> str:
    return re.sub(r'[\s，,*_`]+', '', str(text or '')).lower()


def _clean_metric(text: Any) -> str:
    metric = re.sub(r'20\d{2}(?:年)?', '', str(text or ''))
    # Keep product-defining numbers such as "三层/五层" and "3C".  The
    # extractor builds a metric from text before the measured value, so broad
    # numeric stripping would silently merge genuinely different products.
    metric = re.sub(
        r'(?:预计|预测|实现|达到|达|增至|降至|约为|为|是|同比|较上年)\s*$',
        '', metric.strip(), flags=re.I,
    )
    metric = re.sub(r'[：:，,。；;|\s]+$', '', metric).strip()
    return metric[:160]


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).replace(',', '').replace('，', '').strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _has_conflict(fields: dict) -> bool:
    auto = fields.get('auto_extraction') or {}
    pending = fields.get('pending') or []
    text = ' '.join(map(str, pending if isinstance(pending, list) else [pending]))
    return bool(
        fields.get('conflict') or fields.get('conflicts')
        or auto.get('conflict') or '冲突' in text
    )


def _source_scope(fields: dict, auto: dict, evidence: dict) -> tuple[str, str]:
    """Return a display scope and a grouping key that cannot cross a source scope."""
    scope = str(fields.get('scope') or '').strip()
    geography = str(fields.get('geography') or '').strip()
    origin_keys = auto.get('origin_keys') or []
    origin_key = str(origin_keys[0]) if len(origin_keys) == 1 else ''
    if not origin_key:
        origin_key = classify(evidence)['origin_key']
    explicit = scope not in GENERIC_SCOPES
    if explicit:
        display = '｜'.join(item for item in (geography, scope) if item)
        # Text such as "全国市场" alone does not prove two publishers use the
        # same product and statistical definition.  Keep the original-source
        # group in the series key even when scope wording is explicit.
        return display or scope, 'explicit:' + _normal(display or scope) + '|source:' + origin_key
    display = '｜'.join(item for item in (
        geography, evidence.get('publisher'), evidence.get('title')
    ) if item)
    geography_key = _normal(geography)
    return (
        display or '单一原始来源口径',
        'source:' + origin_key + ('|geo:' + geography_key if geography_key else ''),
    )


def extract_fact_atoms(records: list[dict], evidence: list[dict]) -> tuple[list[dict], list[str]]:
    """Build exact point facts from automatic extraction records.

    A fact is admitted only when one exact quote maps to one evidence row, one
    year and one measured value/unit pair.  Returned values stay as ``Decimal``
    until the persistence boundary.
    """
    evidence_by_id = {
        str(row.get('id') or ''): row for row in usable(evidence)
        if str(row.get('id') or '')
    }
    atoms: list[dict] = []
    blocked: list[str] = []
    for row in records:
        fields = _fields(row)
        auto = fields.get('auto_extraction') or {}
        if auto.get('managed') is not True:
            continue
        record_id = str(row.get('id') or '')
        evidence_ids = [str(item) for item in auto.get('origin_evidence_ids') or []]
        quote = str(auto.get('exact_quote') or '').strip()
        reason = ''
        if len(evidence_ids) != 1 or evidence_ids[0] not in evidence_by_id:
            reason = '缺少唯一可用的上游证据'
        elif not quote or quote not in (evidence_by_id[evidence_ids[0]].get('excerpt') or ''):
            reason = '精确引文无法在上游证据中定位'
        elif _has_conflict(fields):
            reason = '记录已标记为冲突'
        elif AMBIGUOUS_RE.search(quote) or RANGE_RE.search(quote):
            reason = '区间、约数或上下界不能作为精确点值'
        years = YEAR_RE.findall(quote)
        measures = list(MEASURE_RE.finditer(quote))
        if not reason and len(set(years)) != 1:
            reason = '年份不能唯一绑定'
        if not reason and len(measures) != 1:
            reason = '数值与单位不能唯一绑定'
        metric = _clean_metric(fields.get('metric'))
        if not reason and not metric:
            reason = '指标名称不能唯一绑定'
        if reason:
            blocked.append(f'{record_id or "未知记录"}：{reason}')
            continue
        match = measures[0]
        value = _decimal(match.group('value'))
        if value is None:
            blocked.append(f'{record_id or "未知记录"}：数值不是有限十进制数')
            continue
        evidence_row = evidence_by_id[evidence_ids[0]]
        scope, scope_key = _source_scope(fields, auto, evidence_row)
        unit = match.group('unit').replace('％', '%')
        atoms.append({
            'record_id': record_id,
            'evidence_ids': evidence_ids,
            'record_type': str(row.get('record_type') or ''),
            'metric': metric,
            'metric_key': _normal(metric),
            'scope': scope,
            'scope_key': scope_key,
            'year': int(years[0]),
            'value': value,
            'unit': unit,
            'quote': quote,
            'forecast': bool(re.search(r'预计|预测|有望', quote)),
        })
    return atoms, blocked


def _cagr(start: Decimal, end: Decimal, years: int) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        return ((end / start) ** (Decimal(1) / Decimal(years)) - Decimal(1)) * Decimal(100)


def build_calculations(project_id: str, records: list[dict], evidence: list[dict]) -> tuple[list[dict], list[str]]:
    """Create deterministic CAGR records and explanations for blocked series."""
    atoms, blocked = extract_fact_atoms(records, evidence)
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for atom in atoms:
        groups[(atom['record_type'], atom['metric_key'], atom['unit'], atom['scope_key'])].append(atom)

    results: list[dict] = []
    for ((record_type, _, unit, _), items) in sorted(groups.items(), key=lambda pair: pair[0]):
        by_year: dict[int, list[dict]] = defaultdict(list)
        for item in items:
            by_year[item['year']].append(item)
        conflicts = [
            year for year, rows in by_year.items()
            if len({row['value'] for row in rows}) != 1
        ]
        label = items[0]['metric']
        if conflicts:
            blocked.append(f'{label}：{",".join(map(str, sorted(conflicts)))}年存在冲突值')
            continue
        points = []
        for year in sorted(by_year):
            rows = by_year[year]
            points.append({
                'year': year,
                'value': rows[0]['value'],
                'upstream_record_ids': sorted({row['record_id'] for row in rows}),
                'evidence_ids': sorted({eid for row in rows for eid in row['evidence_ids']}),
                'forecast': any(row['forecast'] for row in rows),
            })
        if len(points) < 2:
            blocked.append(f'{label}：同口径精确时间点少于2个，暂不能计算CAGR')
            continue
        start, end = points[0], points[-1]
        periods = end['year'] - start['year']
        if periods <= 0 or start['value'] <= 0 or end['value'] < 0:
            blocked.append(f'{label}：CAGR要求起值大于0、终值非负且期间大于0')
            continue
        rate = _cagr(start['value'], end['value'], periods)
        upstream_ids = sorted({rid for point in points for rid in point['upstream_record_ids']})
        evidence_ids = sorted({eid for point in points for eid in point['evidence_ids']})
        identity = json.dumps({
            'version': CALCULATOR_VERSION, 'project_id': project_id,
            'record_type': record_type,
            'metric': items[0]['metric_key'], 'unit': unit,
            'scope_key': items[0]['scope_key'],
            'points': [(point['year'], str(point['value'])) for point in points],
        }, ensure_ascii=False, sort_keys=True)
        record_id = 'calc-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:27]
        serialized_points = [
            {'year': point['year'], 'value': str(point['value']),
             'forecast': point['forecast']}
            for point in points
        ]
        pending = ['上游事实为自动提取，计算结果待人工复核']
        if any(point['forecast'] for point in points):
            pending.append('序列含预测值，不代表实际实现')
        fields = {
            'status': '程序自动计算（待复核）',
            'metric': label,
            'scope': items[0]['scope'],
            'unit': unit,
            'start_year': start['year'],
            'end_year': end['year'],
            'period_years': periods,
            'start_value': str(start['value']),
            'end_value': str(end['value']),
            'cagr_pct': str(rate),
            'points': serialized_points,
            'formula': 'CAGR=(终值/起值)^(1/期间年数)-1',
            'formula_expression': (
                f'({end["value"]}/{start["value"]})^(1/{periods})-1'
            ),
            'pending': pending,
            'gaps': [],
            'auto_calculation': {
                'managed': True,
                'calculator_version': CALCULATOR_VERSION,
                'calculation_type': 'cagr',
                'input_hash': hashlib.sha256(identity.encode('utf-8')).hexdigest(),
                'upstream_record_ids': upstream_ids,
                'upstream_evidence_ids': evidence_ids,
            },
        }
        results.append({
            'id': record_id, 'project_id': project_id,
            'record_type': 'market',
            'name': f'{label} {start["year"]}—{end["year"]} CAGR（待复核）'[:200],
            'fields': fields, 'basis': 'calculated',
            'source': '程序计算｜上游证据：' + '、'.join(evidence_ids),
            'as_of_date': str(end['year']), 'verified': False,
        })
    return results, blocked


def decision_gaps(records: list[dict]) -> dict[str, list[str]]:
    """Report missing advanced-model outputs without requesting manual input."""
    fields = [_fields(row) for row in records]
    market = any(
        all(key in ((item.get('results') or item)) for key in ('tam_yuan', 'sam_yuan', 'som_yuan'))
        for item in fields
    )
    finance = any(
        all(key in ((item.get('results') or item)) for key in ('operating_profit', 'breakeven_quantity'))
        for item in fields
    )
    city = any(bool((item.get('results') or item).get('ranking')) for item in fields)
    gate = any(
        (item.get('decision') or item.get('scenario_state')) in {'GO', 'HOLD', 'NO-GO'}
        for item in fields
    )
    return {
        'market': [] if market else ['TAM/SAM/SOM：现有资料不足以唯一绑定全部程序输入，保持待验证'],
        'finance': [] if finance else ['财务：现有资料不足以唯一绑定单位经济、盈亏平衡和资金需求输入'],
        'city': [] if city else ['城市：缺少同口径、可比且完整的候选城市指标矩阵'],
        'gate': [] if gate else ['决策门槛：缺少经企业确认的阈值，不自动输出GO/HOLD/NO-GO'],
    }


def _persist(project_id: str, calculations: list[dict]) -> tuple[int, int]:
    """Persist managed calculations without overwriting any human record."""
    computed = reused = 0
    current_ids = [item['id'] for item in calculations]
    with database.connect() as db:
        if not db.execute('SELECT 1 FROM industry_projects WHERE id=%s', (project_id,)).fetchone():
            raise ValueError('行业研究项目不存在')
        for item in calculations:
            old = db.execute(
                'SELECT basis,verified,fields FROM industry_decision_records '
                'WHERE project_id=%s AND id=%s', (project_id, item['id']),
            ).fetchone()
            old_auto = _fields(old).get('auto_calculation') if old else None
            if old:
                reused += 1
                if old['basis'] != 'calculated' or old['verified'] or not (old_auto or {}).get('managed'):
                    continue
            else:
                computed += 1
            db.execute(
                '''INSERT INTO industry_decision_records(
                     id,project_id,record_type,name,fields,basis,source,as_of_date,verified)
                   VALUES (%s,%s,%s,%s,%s::jsonb,'calculated',%s,%s,FALSE)
                   ON CONFLICT(id) DO UPDATE SET
                     record_type=excluded.record_type,name=excluded.name,
                     fields=excluded.fields,source=excluded.source,
                     as_of_date=excluded.as_of_date,updated=now()
                   WHERE industry_decision_records.project_id=excluded.project_id
                     AND industry_decision_records.basis='calculated'
                     AND industry_decision_records.verified=FALSE
                     AND industry_decision_records.fields->'auto_calculation'->>'managed'='true' ''',
                (item['id'], project_id, item['record_type'], item['name'],
                 json.dumps(item['fields'], ensure_ascii=False), item['source'], item['as_of_date']),
            )
        db.execute(
            '''DELETE FROM industry_decision_records
               WHERE project_id=%s AND basis='calculated' AND verified=FALSE
                 AND fields->'auto_calculation'->>'managed'='true'
                 AND NOT (id=ANY(%s::text[]))''',
            (project_id, current_ids),
        )
    return computed, reused


def calculate_project(project_id: str) -> dict:
    """Run safe automatic calculations for a project; gaps are normal output."""
    if not database.project(project_id):
        raise ValueError('行业研究项目不存在')
    records = database.decision_records(project_id)
    evidence = database.all_evidence(project_id)
    calculations, blocked_reasons = build_calculations(project_id, records, evidence)
    computed, reused = _persist(project_id, calculations)
    gaps = decision_gaps(records + calculations)
    gap_count = sum(len(items) for items in gaps.values())
    return {
        'computed': computed,
        'blocked': len(blocked_reasons),
        'reused': reused,
        'calculations': len(calculations),
        'gap_count': gap_count,
        'gaps': gaps,
        'blocked_reasons': blocked_reasons,
        'method': 'Decimal程序计算；未调用大模型；缺失或歧义输入保持待验证',
    }
