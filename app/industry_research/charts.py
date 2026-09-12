"""Deterministic chart discovery and rendering; no language model is used."""
import hashlib
import math
import re
from threading import Lock
from pathlib import Path

from ..kb import ROOT
from .evidence_review import is_usable

CHART_DIR = ROOT / 'storage' / 'charts'
_RENDER_LOCK = Lock()
DATE_TOKEN = re.compile(r'20\d{2}年?')
NUMBER_TEXT = r'(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?'
YEAR_VALUE = re.compile(
    rf'(?P<year>20\d{{2}})年(?P<context>[^。；;\n]{{0,48}}?)'
    rf'(?<![A-Za-z0-9_.,，])(?P<value>{NUMBER_TEXT})\s*'
    r'(?P<unit>万亿元|亿元人民币|亿元|万元|元/吨|元/平方米|元/㎡|亿平方米|万平方米|平方米|'
    r'亿㎡|万㎡|㎡|万吨|吨|万箱|箱|万件|件|亿人|万人|万台|万套|万户|%)'
)
PERCENT_ITEM = re.compile(r'(?P<label>[\u4e00-\u9fffA-Za-z0-9]{2,16})[^。；;\n]{0,20}?(?P<value>\d+(?:\.\d+)?)%')
NUMBER_VALUE = re.compile(
    rf'(?<![A-Za-z0-9_.,，])(?P<value>{NUMBER_TEXT})\s*(?P<unit>万亿元|亿元人民币|亿元|万元|元/吨|元/平方米|元/㎡|元|'
    r'亿平方米|万平方米|平方米|亿㎡|万㎡|㎡|万吨|吨|万箱|箱|万件|件|亿人|亿|万人|'
    r'万部|万台|万套|万户|%|倍|天|小时|分钟|公里|家|项|台|套|部)')
METRICS = ('市场规模', '行业总产值', '总产值', '用户规模', '制作占比', '市场渗透率', '渗透率',
           '同比增长', '复合增速', '增长率', '毛利率', '净利率', '市场份额', '占比', '产量', '销量', '出货量',
           '装机量', '需求量', '需求', '平均价格', '价格', '制作成本', '材料成本', '单位成本', '成本',
           '产能利用率', '开工率', '良率', '账期', '应收账款天数', 'CAPEX', '投资额',
           '流动资金', '盈亏平衡利用率', '市场', '规模')


def _id(chapter_no, title, unit, labels, values):
    raw = repr((chapter_no, title, unit, labels, values)).encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:16]


def _fact_label(line, start):
    prefix = re.sub(r'[#*\[\]]', '', line[:start])
    prefix = re.sub(r'^\s*[-+\d.)、]+\s*', '', prefix)
    prefix = re.sub(r'20\d{2}年', '', prefix)
    prefix = re.split(r'[：:；;。→，,]', prefix)[-1].strip()
    prefix = re.sub(r'^(?:预计|约|达到|为|突破|增至|达到)+', '', prefix)
    prefix = re.sub(r'(?:预计|约|达到|为|突破|增至|达到|超过|仅|超|从|（|\()+$', '', prefix)
    return prefix.strip()


def table_charts(chapter):
    """Conservative Markdown tables: explicit unit, complete numeric column."""
    output = []
    blocks = re.findall(r'(?:^\s*\|[^\n]+\|\s*$\n?){3,}', chapter.get('content', ''), re.M)
    for block in blocks:
        rows = [[re.sub(r'\*\*|__', '', c).strip() for c in line.strip().strip('|').split('|')]
                for line in block.strip().splitlines()]
        header = rows[0]
        if len(header) < 2 or not all(re.fullmatch(r':?-{3,}:?', c.strip()) for c in rows[1]):
            continue
        body = rows[2:]
        if not 2 <= len(body) <= 30 or any(len(r) != len(header) for r in body):
            continue
        labels = [r[0] for r in body]
        if any(not x for x in labels) or len(set(labels)) != len(labels):
            continue
        for col in range(1, len(header)):
            unit_match = re.search(
                r'[（(](亿平方米|万平方米|平方米|亿㎡|万㎡|㎡|万吨|吨|万台|台|万套|套|'
                r'万箱|箱|万件|件|亿元|万元|元/吨|元/平方米|元/㎡|元|%|天|小时|分钟|公里|家|分)[)）]',
                header[col])
            if not unit_match:
                continue
            unit = unit_match[1]
            values = []
            for row in body:
                cell = re.sub(r'\[\d+(?:-\d+)?\]', '', row[col]).strip()
                if cell.endswith(unit):
                    cell = cell[:-len(unit)].strip()
                if not re.fullmatch(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', cell):
                    break
                values.append(float(cell.replace(',', '')))
            if len(values) != len(body):
                continue
            time_series = '年' in header[0] and all(re.fullmatch(r'20\d{2}年?', x) for x in labels)
            title = header[col]
            output.append(dict(id=_id(chapter['chapter_no'], title, unit, labels, values),
                               chapter_no=chapter['chapter_no'], title=title, unit=unit,
                               labels=labels, values=values,
                               chart_types=['line','column','bar','area','lollipop'] if time_series else ['bar','column','lollipop'],
                               kind='table_series', source_excerpts=[block.strip()],
                               note='来源为正文表格；请人工确认各行地区、期间、产品及实际/预测口径可比。'))
    return output


def _numeric(value):
    if isinstance(value, str):
        value = value.strip().replace(',', '').replace('，', '')
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalized_measurement_text(value):
    return re.sub(r'\s+', '', str(value or '')).replace('，', ',').replace('％', '%')


def _source_grade(values):
    grades = sorted(
        {str(value).upper() for value in values if str(value).upper() in {'A', 'B', 'C', 'D'}},
        key='ABCD'.index,
    )
    return '/'.join(grades) if grades else '待分级'


_SERIES_SHORTHAND_METRICS = {
    '规模', '市场规模', '需求', '需求量', '产量', '销量', '出货量', '装机量',
}


def _ambiguous_respective_year_binding(text, number_matches):
    """Reject ``分别`` clauses unless position alone gives a one-to-one pairing."""
    if '分别' not in text or len(number_matches) < 2:
        return False
    years = list(DATE_TOKEN.finditer(text))
    if len(years) < 2:
        return False
    owners = []
    for number in number_matches:
        preceding = [year for year in years if year.end() <= number.start()]
        if not preceding:
            return True
        owners.append(preceding[-1].start())
    # ``2022年和2023年……分别为100、120`` assigns both numbers to
    # 2023 with a nearest-preceding-year heuristic.  Do not guess the intended
    # pairing.  Extra years or values are equally unsafe.
    return len(years) != len(number_matches) or len(set(owners)) != len(number_matches)


def _local_series_metric(text, token_match):
    """Return the literal metric phrase immediately governing one measurement."""
    years = [year for year in DATE_TOKEN.finditer(text) if year.end() <= token_match.start()]
    if not years:
        return ''
    context = text[years[-1].end():token_match.start()]
    context = re.split(r'[。；;，,！？!?\n]', context)[-1]
    context = re.sub(r'^[\s：:、]*(?:(?:预计|预测|约|大约|将|可达|达到|为)\s*)+', '', context)
    context = re.sub(r'(?:(?:预计|预测|约|大约|将|可达|达到|为)\s*)+$', '', context)
    return re.sub(r'[\s*`#（）()]', '', context).strip('：:、-—')


def _series_metric_signature(local_metric, inherited):
    if not local_metric:
        return inherited
    if (inherited and local_metric in _SERIES_SHORTHAND_METRICS
            and inherited.endswith(local_metric)):
        return inherited
    return local_metric


def _auto_fact_charts(record, fields, evidence_by_id=None, enforce_evidence=False):
    """Turn every exact measurement in one quote into a scalar card.

    Multiple numbers in the same source sentence are separate cards, never an
    invented series.  When immutable evidence is supplied (the production
    path), every quote is re-located before the candidate is exposed.
    """
    auto = fields.get('auto_extraction') or {}
    measurements = fields.get('measurements')
    if not isinstance(auto, dict):
        return []
    quote = str(auto.get('exact_quote') or '').strip()
    evidence_ids = sorted({str(value) for value in auto.get('origin_evidence_ids') or [] if str(value)})
    if (
        auto.get('managed') is not True
        or fields.get('conflict') or len(quote) < 6 or not evidence_ids
    ):
        return []
    if enforce_evidence:
        evidence_by_id = evidence_by_id or {}
        if any(
            evidence_id not in evidence_by_id
            or quote not in (evidence_by_id[evidence_id].get('excerpt') or '')
            for evidence_id in evidence_ids
        ):
            return []
    quote_measurements = list(NUMBER_VALUE.finditer(quote))
    if _ambiguous_respective_year_binding(quote, quote_measurements):
        return []
    if isinstance(measurements, list) and measurements:
        candidates = [item for item in measurements if isinstance(item, dict)]
        # A rule record must account for every value-unit token in its quote.
        # Otherwise a stale/edited record could silently chart only part of a
        # multi-number statement.
        if len(candidates) != len(quote_measurements):
            return []
    elif not measurements:
        # AI exact-quote candidates store the selected scalar directly instead
        # of the rule extractor's ``measurements`` array. Re-parse the quote so
        # the model cannot supply a detached number.
        expected_value = _numeric(fields.get('value'))
        expected_unit = str(fields.get('unit') or '').strip().replace('％', '%')
        matches = [
            match for match in quote_measurements
            if _numeric(match.group('value')) == expected_value
            and match.group('unit').replace('％', '%') == expected_unit
        ]
        if len(matches) != 1:
            return []
        candidates = [{
            'value': fields.get('value'), 'unit': fields.get('unit'), 'raw': matches[0].group(0),
        }]
    else:
        return []

    try:
        chapter_no = int(auto.get('chapter_no'))
    except (TypeError, ValueError):
        return []
    if not 1 <= chapter_no <= 10:
        return []
    periods = fields.get('periods')
    if periods is None:
        period = str(fields.get('period') or '').strip()
        periods = [period] if period else []
    periods = periods or []
    if not isinstance(periods, list):
        return []
    periods = list(dict.fromkeys(str(item).strip() for item in periods if str(item).strip()))
    period = '—'.join(periods) if len(periods) <= 2 else ''
    base_metric = re.sub(
        r'\s+', ' ', str(fields.get('metric') or record.get('name') or '关键指标')
    ).strip()[:75]
    grade = _source_grade([auto.get('source_grade')])
    output = []
    series_points = []
    inherited_series_metric = ''
    for index, measurement in enumerate(candidates):
        value = _numeric(measurement.get('value'))
        unit = str(measurement.get('unit') or '').strip().replace('％', '%')
        raw = str(measurement.get('raw') or '').strip()
        # Require one literal value-unit token from the quote. Normalisation is
        # used only to compare numeric formatting, never to establish provenance.
        quote_matches = [
            match for match in NUMBER_VALUE.finditer(quote)
            if match.group(0) == raw
            and _numeric(match.group('value')) == value
            and match.group('unit').replace('％', '%') == unit
        ]
        if value is None or not unit or not raw or len(quote_matches) != 1:
            continue
        token_match = quote_matches[0]
        preceding_years = [
            match.group(0) for match in DATE_TOKEN.finditer(quote)
            if match.start() < token_match.start()
        ]
        item_period = preceding_years[-1] if preceding_years else period
        local_metric = _local_series_metric(quote, token_match)
        metric_signature = _series_metric_signature(
            local_metric, inherited_series_metric)
        if metric_signature:
            inherited_series_metric = metric_signature
        if len(candidates) == 1:
            metric = base_metric
        elif local_metric:
            metric = local_metric[:75]
        elif unit == '%' and re.search(r'同比|增长|增速|CAGR', quote, re.I):
            metric = f'{base_metric}—增长指标'
        else:
            metric = f'{base_metric}—{unit}指标{index + 1}'
        label = f'{item_period} {metric}'.strip()
        title = f'{metric}（自动摘录／待核对口径）'
        output.append(dict(
            id=_id(chapter_no, title, unit, [label], [value]),
            chapter_no=chapter_no, title=title, unit=unit,
            labels=[label], values=[value], chart_types=['card'],
            kind='decision_auto_fact', source_excerpts=[quote],
            evidence_ids=evidence_ids, source_grade=grade,
            source_grades=[] if grade == '待分级' else grade.split('/'),
            source_references=[str(record.get('source') or '')] if record.get('source') else [],
            scope=str(fields.get('scope') or '仅限原文引文所述口径'),
            pending_review=True, verification_status='待复核',
            note=(f'程序从证据 {"、".join(evidence_ids)} 逐字摘录；来源等级 {grade}。'
              '展示不等于事实或统计口径已核验，请在导出前核对。'),
        ))
        if (item_period and metric_signature
                and re.fullmatch(r'20\d{2}年?', item_period)):
            series_points.append(
                (item_period.rstrip('年'), value, unit, metric_signature))
    if (
        len(series_points) >= 2
        and len({point[0] for point in series_points}) == len(series_points)
        and len({point[2] for point in series_points}) == 1
        and len({point[3] for point in series_points}) == 1
    ):
        series_points.sort(key=lambda point: point[0])
        labels = [point[0] for point in series_points]
        values = [point[1] for point in series_points]
        unit = series_points[0][2]
        title = f'{base_metric}（自动摘录年度序列／待核对口径）'
        output.append(dict(
            id=_id(chapter_no, title, unit, labels, values),
            chapter_no=chapter_no, title=title, unit=unit,
            labels=labels, values=values,
            chart_types=['line', 'bar', 'column', 'area', 'scatter', 'lollipop'],
            kind='decision_auto_series', source_excerpts=[quote],
            evidence_ids=evidence_ids, source_grade=grade,
            source_grades=[] if grade == '待分级' else grade.split('/'),
            source_references=[str(record.get('source') or '')] if record.get('source') else [],
            scope=str(fields.get('scope') or '仅限原文引文所述口径'),
            pending_review=True, verification_status='待复核',
            note=(f'程序从同一逐字引文中绑定 {len(labels)} 个年份和同单位数值；'
                  f'来源等级 {grade}。系列待核对指标、地域和实际／预测口径。'),
        ))
    return output


def _auto_fact_chart(record, fields):
    """Backward-compatible first-card helper used by older integrations."""
    candidates = _auto_fact_charts(record, fields)
    return candidates[0] if candidates else None


def _auto_cagr_chart(record, fields, records_by_id, evidence_by_id=None,
                     enforce_evidence=False):
    """Expose every saved point behind a deterministic CAGR calculation."""
    auto = fields.get('auto_calculation') or {}
    points = fields.get('points')
    if (
        record.get('basis') != 'calculated' or not isinstance(auto, dict)
        or auto.get('managed') is not True or auto.get('calculation_type') != 'cagr'
        or not isinstance(points, list) or len(points) < 2
    ):
        return None
    parsed = []
    seen_years = set()
    for point in points:
        if not isinstance(point, dict):
            return None
        raw_year = point.get('year')
        if isinstance(raw_year, bool) or not re.fullmatch(r'20\d{2}', str(raw_year or '')):
            return None
        year = int(raw_year)
        value = _numeric(point.get('value'))
        if value is None or year in seen_years:
            return None
        seen_years.add(year)
        parsed.append((year, value, bool(point.get('forecast'))))
    parsed.sort(key=lambda item: item[0])
    unit = str(fields.get('unit') or '').strip().replace('％', '%')
    metric = re.sub(r'\s+', ' ', str(fields.get('metric') or record.get('name') or '')).strip()[:90]
    cagr = _numeric(fields.get('cagr_pct'))
    scope = str(fields.get('scope') or '').strip()
    if not unit or not metric or cagr is None or not scope:
        return None

    upstream_ids = sorted({str(value) for value in auto.get('upstream_record_ids') or [] if str(value)})
    evidence_ids = set(str(value) for value in auto.get('upstream_evidence_ids') or [] if str(value))
    if len(upstream_ids) < 2 or not evidence_ids:
        return None
    quotes_by_year = {year: [] for year, _, _ in parsed}
    grades = []
    chapters = []
    references = []
    for record_id in upstream_ids:
        upstream = records_by_id.get(record_id)
        # A calculated series is selectable only while every saved input still
        # has its auditable upstream record. Never silently degrade a three-year
        # calculation into a two-year visual.
        if not isinstance(upstream, dict):
            return None
        upstream_fields = upstream.get('fields') or {}
        if not isinstance(upstream_fields, dict):
            return None
        upstream_auto = upstream_fields.get('auto_extraction') or {}
        if not isinstance(upstream_auto, dict) or upstream_auto.get('managed') is not True:
            return None
        quote = str(upstream_auto.get('exact_quote') or '').strip()
        origin_evidence_ids = [
            str(value) for value in upstream_auto.get('origin_evidence_ids') or [] if str(value)
        ]
        if not quote or not origin_evidence_ids:
            return None
        if enforce_evidence:
            evidence_by_id = evidence_by_id or {}
            if any(
                evidence_id not in evidence_by_id
                or quote not in (evidence_by_id[evidence_id].get('excerpt') or '')
                for evidence_id in origin_evidence_ids
            ):
                return None
        for evidence_id in origin_evidence_ids:
            if str(evidence_id):
                evidence_ids.add(str(evidence_id))
        grades.append(upstream_auto.get('source_grade'))
        try:
            chapter = int(upstream_auto.get('chapter_no'))
        except (TypeError, ValueError):
            chapter = 0
        if 1 <= chapter <= 10:
            chapters.append(chapter)
        if upstream.get('source'):
            references.append(str(upstream['source']))
        for year, point_value, _ in parsed:
            if str(year) not in quote:
                continue
            for match in NUMBER_VALUE.finditer(quote):
                matched_value = _numeric(match.group('value'))
                matched_unit = match.group('unit').replace('％', '%')
                if matched_value == point_value and matched_unit == unit:
                    quotes_by_year[year].append(quote)
                    break

    # Every plotted point must still have an exact upstream quote. Missing
    # evidence makes the whole chart incomplete; it must not become a shorter
    # and potentially misleading series.
    if any(not quotes_by_year[year] for year, _, _ in parsed):
        return None
    excerpts = []
    for year, _, _ in parsed:
        excerpts.extend(quotes_by_year[year])
    excerpts = list(dict.fromkeys(excerpts))
    references.append(str(record.get('source') or ''))
    references = sorted({item for item in references if item})
    evidence_ids = sorted(evidence_ids)
    grade = _source_grade(grades)
    if chapters:
        counts = {chapter: chapters.count(chapter) for chapter in set(chapters)}
        chapter_no = min(counts, key=lambda chapter: (-counts[chapter], chapter))
    else:
        chapter_no = 4
    labels = [str(year) for year, _, _ in parsed]
    values = [value for _, value, _ in parsed]
    forecast = any(flag for _, _, flag in parsed)
    title = f'{metric}：年度序列与CAGR {cagr:g}%（程序计算／待复核）'
    identity_title = f'{metric}|cagr={cagr:g}|{auto.get("input_hash") or ""}'
    return dict(
        id=_id(chapter_no, identity_title, unit, labels, values),
        chapter_no=chapter_no, title=title, unit=unit,
        labels=labels, values=values,
        chart_types=['line', 'bar', 'column', 'area', 'scatter', 'lollipop'],
        kind='decision_auto_cagr', source_excerpts=excerpts,
        evidence_ids=evidence_ids, source_grade=grade,
        source_grades=[] if grade == '待分级' else grade.split('/'),
        source_references=references, scope=scope,
        pending_review=True, verification_status='待复核',
        note=(f'程序根据自动摘录的同口径时间点计算CAGR，已保留 {len(labels)} 个年份全部数据；'
              f'来源等级 {grade}。' + ('序列含预测值；' if forecast else '')
              + '该图待人工核对指标、地域、范围及实际/预测口径。'),
    )


def _dedupe_decision_charts(items):
    """Merge semantically identical candidates without losing provenance."""
    output = []
    positions = {}
    for item in items:
        signature = (
            item.get('chapter_no'), item.get('kind'), item.get('title'), item.get('unit'),
            tuple(item.get('labels') or []), tuple(item.get('values') or []),
        )
        if signature not in positions:
            clone = dict(item)
            for key in ('source_excerpts', 'evidence_ids', 'source_grades', 'source_references'):
                if key in clone:
                    clone[key] = sorted({str(value) for value in clone.get(key) or [] if str(value)})
            output.append(clone)
            positions[signature] = len(output) - 1
            continue
        current = output[positions[signature]]
        # A stable semantic chart id must not depend on database row order.
        current['id'] = min(str(current.get('id') or ''), str(item.get('id') or ''))
        for key in ('source_excerpts', 'evidence_ids', 'source_grades', 'source_references'):
            merged = {
                str(value) for value in (current.get(key) or []) + (item.get(key) or []) if str(value)
            }
            if merged or key in current or key in item:
                current[key] = sorted(merged)
        grade = _source_grade(current.get('source_grades') or [])
        if 'source_grade' in current or 'source_grade' in item:
            current['source_grade'] = grade
        if current.get('kind') == 'decision_auto_fact':
            current['note'] = (
                f'程序从证据 {"、".join(current.get("evidence_ids") or [])} 逐字摘录；'
                f'来源等级 {grade}。展示不等于事实或统计口径已核验，请在导出前核对。'
            )
    return output


def decision_charts(project):
    """Build auditable charts from saved deterministic decision records."""
    output = []
    records = [record for record in project.get('decision_records', []) if isinstance(record, dict)]
    records_by_id = {
        str(record.get('id')): record for record in records if str(record.get('id') or '')
    }
    enforce_evidence = 'evidence' in project
    evidence_by_id = {
        str(row.get('id')): row for row in project.get('evidence', [])
        if isinstance(row, dict) and str(row.get('id') or '') and is_usable(row)
    }
    for record in records:
        fields = record.get('fields') or {}
        if not isinstance(fields, dict):
            continue
        auto_extraction = fields.get('auto_extraction') or {}
        if isinstance(auto_extraction, dict) and auto_extraction.get('managed') is True:
            output.extend(_auto_fact_charts(
                record, fields, evidence_by_id, enforce_evidence))
            # Invalid or incomplete auto-extraction data must not fall through
            # to a less strict legacy chart path.
            continue
        auto_calculation = fields.get('auto_calculation') or {}
        if isinstance(auto_calculation, dict) and auto_calculation.get('managed') is True:
            candidate = _auto_cagr_chart(
                record, fields, records_by_id, evidence_by_id, enforce_evidence)
            if candidate:
                output.append(candidate)
            continue
        results = fields.get('results') or {}
        record_type = record.get('record_type')
        status = fields.get('status') or ('已核对' if record.get('verified') else '待验证')
        provenance = (f"{record.get('name', '程序测算')}；状态：{status}；"
                      f"日期：{record.get('as_of_date') or '待补'}；来源：{record.get('source') or '见输入明细'}")
        suffix = '' if record.get('verified') else '（情景／待验证）'
        record_key = str(record.get('id') or record.get('name') or '')

        if record_type == 'market' and isinstance(results, dict):
            keys = [('tam_yuan','TAM'),('sam_yuan','SAM'),('som_yuan','SOM')]
            pairs = [(label, _numeric(results.get(key))) for key, label in keys]
            pairs = [(label, value) for label, value in pairs if value is not None]
            if len(pairs) >= 2:
                labels, values = map(list, zip(*pairs))
                title = f"{record.get('name', '市场空间')}：TAM/SAM/SOM{suffix}"
                output.append(dict(id=_id(2,title+'|'+record_key,'元',labels,values), chapter_no=2, title=title,
                    unit='元', labels=labels, values=values, chart_types=['bar','column','lollipop'],
                    kind='decision_market', source_excerpts=[provenance],
                    note='由程序按已保存输入计算；情景或待验证状态不代表已确认市场事实。'))
        elif record_type == 'finance' and isinstance(results, dict):
            groups = [
                ('收入、利润与资金需求', '元', [('revenue','收入'),('operating_profit','营业利润'),
                    ('net_working_capital','净营运资金'),('initial_funding_floor','初始资金下限')]),
                ('利用率与盈亏平衡', '%', [('utilization_pct','产能利用率'),
                    ('breakeven_utilization_pct','盈亏平衡利用率')]),
                ('营运资金构成', '元', [('receivables','应收账款'),('inventory','存货占用'),('payables','应付账款')]),
            ]
            for group_title, unit, keys in groups:
                pairs = [(label, _numeric(results.get(key))) for key, label in keys]
                pairs = [(label, value) for label, value in pairs if value is not None]
                if len(pairs) < 2:
                    continue
                labels, values = map(list, zip(*pairs))
                title = f"{record.get('name', '财务测算')}：{group_title}{suffix}"
                output.append(dict(id=_id(8,title+'|'+record_key,unit,labels,values), chapter_no=8, title=title,
                    unit=unit, labels=labels, values=values, chart_types=['bar','column','lollipop'],
                    kind='decision_finance', source_excerpts=[provenance],
                    note='由程序按同一销量、售价、产能和账期口径计算；须结合输入状态解读。'))
        elif record_type == 'city' and isinstance(results, dict):
            scores = results.get('weighted_scores') or {}
            pairs = [(city, _numeric(value)) for city, value in scores.items()]
            pairs = [(city, value) for city, value in pairs if value is not None]
            if len(pairs) >= 2:
                labels, values = map(list, zip(*pairs))
                title = f"{record.get('name', '城市选址')}：综合加权得分{suffix}"
                output.append(dict(id=_id(7,title+'|'+record_key,'分',labels,values), chapter_no=7,
                    title=title, unit='分', labels=labels, values=values,
                    chart_types=['bar','column','lollipop'], kind='decision_city',
                    source_excerpts=[provenance],
                    note='程序按已保存权重和同口径城市输入进行Min-Max标准化；得分领先不等于投资结论。'))
            for indicator in (fields.get('inputs') or {}).get('indicators', []):
                values_by_city = indicator.get('values') or {}
                pairs = [(city, _numeric((fact or {}).get('value'))) for city, fact in values_by_city.items()]
                pairs = [(city, value) for city, value in pairs if value is not None]
                unit = indicator.get('unit') or ''
                if len(pairs) < 2 or not unit:
                    continue
                labels, values = map(list, zip(*pairs))
                title = f"{record.get('name', '城市选址')}：{indicator.get('name', '选址指标')}{suffix}"
                output.append(dict(id=_id(7,title+'|'+record_key,unit,labels,values), chapter_no=7,
                    title=title, unit=unit, labels=labels, values=values,
                    chart_types=['bar','column','lollipop'], kind='decision_city_metric',
                    source_excerpts=[provenance],
                    note=('由程序使用已保存的城市原始值绘制；方向：' +
                          ('越高越好' if indicator.get('direction') == 'higher_better' else '越低越好') +
                          '。来源、日期与核验状态见结构化输入。')))
        elif record_type == 'threshold':
            for metric in fields.get('metrics') or []:
                pairs = [('当前值', _numeric(metric.get('current_value'))),
                         ('GO阈值', _numeric(metric.get('go_threshold'))),
                         ('NO-GO阈值', _numeric(metric.get('no_go_threshold')))]
                if any(value is None for _, value in pairs):
                    continue
                labels, values = map(list, zip(*pairs))
                unit = metric.get('unit') or ''
                title = (f"{metric.get('stage', '阶段')}：{metric.get('name', '决策门槛')}"
                         f"（{metric.get('state', '待验证')}）{suffix}")
                output.append(dict(id=_id(10,title+'|'+record_key,unit,labels,values), chapter_no=10,
                    title=title, unit=unit, labels=labels, values=values,
                    chart_types=['bar','column','lollipop'], kind='decision_gate',
                    source_excerpts=[provenance],
                    note='当前值与企业确认的GO/NO-GO门槛对照；待验证状态不得解释为投资结论。'))
    return _dedupe_decision_charts(output)


def discover(project):
    result = decision_charts(project)
    for chapter in project.get('chapters', []):
        if chapter.get('chapter_no') == 0:
            continue
        content = chapter.get('content') or ''
        result.extend(table_charts(chapter))
        groups = {}
        facts = []
        section = 0
        inherited = None
        for raw in content.splitlines():
            line = re.sub(r'\*\*|__', '', raw).strip()
            if not line:
                continue
            if re.match(r'^#{1,6}\s', raw) or re.match(r'^\s*[-*+]\s+\*\*.+?\*\*[:：]?\s*$', raw):
                section += 1
                inherited = None
            number_matches = list(NUMBER_VALUE.finditer(line))
            if _ambiguous_respective_year_binding(line, number_matches):
                continue
            matches = list(YEAR_VALUE.finditer(line)) if len(re.findall(r'20\d{2}年', line)) == 1 else []
            for match in matches:
                context = match.group('context')
                unit = match.group('unit')
                mentions = [(context.rfind(name), name) for name in METRICS if name in context]
                # Prefer a complete metric over a suffix (market size vs size).
                position, metric = max(mentions, key=lambda item: (item[0] + len(item[1]), len(item[1])), default=(-1, None))
                if metric:
                    subject = context[:position].strip(' ：:，,')
                    # Preserve the named industry/entity; revenue and market size
                    # must never become one series solely because both use yuan.
                    if len(subject) <= 18:
                        metric = subject + metric
                    # A bare shorthand in the same section inherits its explicit
                    # metric, not a new series. Never merge named subjects or units.
                    shorthand_metrics = ('规模', '市场', '需求', '需求量', '产量', '销量', '出货量', '装机量')
                    if not subject and metric in shorthand_metrics and inherited and inherited.endswith(metric):
                        metric = inherited
                    if any(x in context for x in ('增长', '增速', '占比', '率')) and unit != '%':
                        continue
                    inherited = metric
                elif inherited and re.fullmatch(r'[：:，,\s]*(?:预计|约|达到|为|突破|规模|市场规模)*', context):
                    metric = inherited
                else:
                    continue
                key = (section, metric, unit)
                points = groups.setdefault(key, {})
                year, value = match.group('year'), _numeric(match.group('value'))
                if value is None:
                    continue
                if year in points and points[year][0] != value:
                    points[year] = (None, line)
                else:
                    points[year] = (value, line)
            # Preserve each fact on its own when comparability is not established.
            # Ranges and bare magnitudes such as "亿" need manual interpretation.
            for match in number_matches:
                if match.group('unit') == '亿':
                    continue
                start = match.start()
                if start and line[start - 1] in '0123456789.–—-~至':
                    continue
                value = _numeric(match.group('value'))
                if value is None:
                    continue
                unit = match.group('unit')
                if unit == '%' and value > 100 and any(word in _fact_label(line, start) for word in ('占比', '份额', '渗透率')):
                    continue
                label = _fact_label(line, start)
                if not label:
                    label = inherited or ''
                if len(label) < 2:
                    continue
                source = line.lstrip('# -*+')
                title = label
                years = re.findall(r'20\d{2}年', line[:match.end()])
                if years and len(re.findall(r'20\d{2}年', line)) == 1:
                    title = years[-1] + ' ' + label
                facts.append(dict(
                    id=_id(chapter['chapter_no'], title, unit, [title], [value]),
                    chapter_no=chapter['chapter_no'], title=title, unit=unit,
                    labels=[title], values=[value], chart_types=['card'], kind='fact',
                    source_excerpts=[source], note='数值及其限定条件见原文摘录。'))
        for (_, metric, unit), points in groups.items():
            if len(points) < 2 or any(v[0] is None for v in points.values()):
                continue
            labels = sorted(points)
            values = [points[y][0] for y in labels]
            title = f"{chapter['title']}：{metric}"
            result.append(dict(
                id=_id(chapter['chapter_no'], title, unit, labels, values),
                chapter_no=chapter['chapter_no'], title=title, unit=unit,
                labels=labels, values=values, chart_types=['line', 'bar', 'column', 'area', 'scatter', 'lollipop'], kind='time_series',
                source_excerpts=[points[y][1] for y in labels], note='按原文年份排列；预测值以原文标注为准。'))
        result.extend(facts)
    unique, seen = [], set()
    for item in result:
        signature = (item['chapter_no'], item['kind'], item['unit'], tuple(item['labels']),
                     tuple(item['values']), item['id'] if item['kind'].startswith('decision_') else None)
        if signature not in seen:
            unique.append(item); seen.add(signature)
    # Universal presentation rule for every report: charts express a
    # comparison or trend whenever possible.  Scalar KPI cards are supporting
    # material only, never a wall of repeated single points.  Boundary/
    # definition chapters do not receive automatically guessed KPI cards.
    filtered, scalar_seen, scalar_counts = [], set(), {}
    for item in unique:
        is_scalar = item.get('chart_types') == ['card'] or len(item.get('values') or []) == 1
        if not is_scalar:
            filtered.append(item)
            continue
        chapter_no = int(item.get('chapter_no') or 0)
        if chapter_no == 1:
            continue
        values = item.get('values') or []
        scalar_key = (chapter_no, item.get('unit') or '', values[0] if values else None)
        if scalar_key in scalar_seen or scalar_counts.get(chapter_no, 0) >= 3:
            continue
        scalar_seen.add(scalar_key)
        scalar_counts[chapter_no] = scalar_counts.get(chapter_no, 0) + 1
        filtered.append(item)
    return filtered


def render(project_id, spec):
    import os
    import threading
    from io import BytesIO
    from textwrap import fill

    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'storage' / 'matplotlib'))
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties

    labels, values = spec['labels'], spec['values']
    kind = spec['selected_type']
    folder = CHART_DIR / project_id
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(repr((spec['title'], labels, values, kind)).encode()).hexdigest()[:20]
    path = folder / f"{spec['id']}-{fingerprint}.png"
    font = FontProperties(family=['Microsoft YaHei', 'SimHei', 'DejaVu Sans'])
    fig = Figure(figsize=(8.4, 2.5 if kind == 'card' else 4.4), dpi=180, layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    if kind == 'card':
        ax.axis('off')
        ax.text(.02, .55, f'{values[0]:g} {spec["unit"]}', transform=ax.transAxes,
                fontsize=32, color='#1e6874', fontproperties=font, fontweight='bold')
        ax.text(.02, .15, fill(labels[0], 36), transform=ax.transAxes,
                fontsize=12, color='#52616a', fontproperties=font)
    elif kind == 'bar':
        # Horizontal bars keep long industry/company labels readable.
        bars = ax.barh(range(len(values)), values, color='#1e6874', height=.6)
        ax.set_yticks(range(len(labels)), [fill(str(x), 20) for x in labels], fontproperties=font, fontsize=9)
        ax.invert_yaxis()
        ax.bar_label(bars, labels=[f'{v:g}' for v in values], padding=4, fontsize=9)
        ax.set_xlim(min(0, min(values)) * 1.15, max(1, max(values)) * 1.2)
        ax.set_xlabel(spec['unit'], fontproperties=font)
        ax.grid(axis='x', alpha=.18); ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
    elif kind in ('line', 'area', 'scatter', 'lollipop', 'column'):
        xs = [float(x) for x in labels] if all(re.fullmatch(r'\d{4}', str(x)) for x in labels) else list(range(len(labels)))
        if kind == 'column':
            # Columns compare discrete years; do not imply equal time intervals.
            xs = list(range(len(labels)))
            ax.bar(xs, values, color='#1e6874', width=.6)
        elif kind == 'scatter':
            ax.scatter(xs, values, color='#1e6874', s=48, zorder=3)
        elif kind == 'lollipop':
            ax.vlines(xs, 0, values, color='#80aab0', linewidth=3)
            ax.scatter(xs, values, color='#1e6874', s=60, zorder=3)
        else:
            ax.plot(xs, values, color='#1e6874', marker='o', linewidth=2.2)
            if kind == 'area':
                ax.fill_between(xs, values, 0, color='#1e6874', alpha=.18)
        ax.set_xticks(xs, labels, fontproperties=font)
        ax.set_ylim(min(0, min(values)), max(1, max(values)) * 1.22)
        for x, value in zip(xs, values):
            ax.annotate(f'{value:g}', (x, value), xytext=(0, 8), textcoords='offset points', ha='center', fontsize=9)
        ax.set_ylabel(spec['unit'], fontproperties=font)
        ax.grid(axis='y', alpha=.18); ax.spines[['top', 'right']].set_visible(False)
    elif kind == 'pie':
        if len(values) < 2 or any(v < 0 for v in values) or not 99.5 <= sum(values) <= 100.5:
            raise ValueError('Pie chart requires a verified complete composition')
        ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'fontproperties': font},
               colors=['#1e6874', '#315f7d', '#5b8295', '#91adb6', '#c0d2d7'])
        ax.axis('equal')
    else:
        raise ValueError('Unsupported chart type')
    ax.set_title(fill(spec['title'], 38), loc='left', fontproperties=font, fontsize=12, pad=14)
    # Serialize matplotlib rendering only; figure instances never share pyplot state.
    with _RENDER_LOCK:
        buffer = BytesIO()
        fig.savefig(buffer, format='png', facecolor='white')
        temp = path.with_suffix(f'.{threading.get_ident()}.tmp')
        temp.write_bytes(buffer.getvalue())
        temp.replace(path)
    return path
