import json
from decimal import Decimal

from app.industry_research import decision_auto_calculation as auto_calc


def _evidence(evidence_id, excerpt, *, url='https://stats.gov.cn/series'):
    return {
        'id': evidence_id,
        'chapter_no': 2,
        'title': '同口径年度统计',
        'publisher': '国家统计局',
        'url': url,
        'published_at': '2025-01-01',
        'excerpt': excerpt,
        'source_type': 'official_statistics',
        'metadata': {},
    }


def _record(record_id, evidence_id, quote, *, metric='国内瓦楞纸箱市场规模',
            scope='全国｜成品销售额', conflict=False):
    return {
        'id': record_id,
        'record_type': 'market',
        'basis': 'unverified',
        'verified': False,
        'fields': {
            'metric': metric,
            'scope': scope,
            'conflict': conflict,
            'auto_extraction': {
                'managed': True,
                'exact_quote': quote,
                'origin_evidence_ids': [evidence_id],
                'origin_keys': ['origin-1'],
            },
        },
    }


def test_exact_same_scope_series_calculates_decimal_cagr():
    q1 = '2022年国内瓦楞纸箱市场规模为100亿元。'
    q2 = '2024年国内瓦楞纸箱市场规模为121亿元。'
    evidence = [_evidence('e1', q1), _evidence('e2', q2)]
    records = [_record('r1', 'e1', q1), _record('r2', 'e2', q2)]

    calculations, blocked = auto_calc.build_calculations('p1', records, evidence)

    assert blocked == []
    assert len(calculations) == 1
    result = calculations[0]
    fields = result['fields']
    assert result['basis'] == 'calculated' and result['verified'] is False
    assert fields['start_year'] == 2022 and fields['end_year'] == 2024
    assert fields['period_years'] == 2
    assert fields['start_value'] == '100' and fields['end_value'] == '121'
    assert Decimal(fields['cagr_pct']).quantize(Decimal('0.000001')) == Decimal('10.000000')
    assert fields['formula'] == 'CAGR=(终值/起值)^(1/期间年数)-1'
    assert fields['auto_calculation']['upstream_record_ids'] == ['r1', 'r2']
    assert fields['auto_calculation']['upstream_evidence_ids'] == ['e1', 'e2']
    assert fields['pending']


def test_ranges_approximations_multiple_values_and_conflicts_are_blocked():
    quotes = {
        'approx': '2022年市场规模约100亿元。',
        'range': '2023年市场规模为100-120亿元。',
        'multi': '2024年市场规模为121亿元，同比增长10%。',
        'conflict_a': '2022年国内瓦楞纸箱市场规模为100亿元。',
        'conflict_b': '2022年国内瓦楞纸箱市场规模为110亿元。',
        'end': '2024年国内瓦楞纸箱市场规模为121亿元。',
    }
    evidence = [_evidence(key, quote) for key, quote in quotes.items()]
    records = [
        _record(key, key, quote, metric='测试指标' if key in {'approx', 'range', 'multi'} else '冲突指标')
        for key, quote in quotes.items()
    ]

    calculations, blocked = auto_calc.build_calculations('p1', records, evidence)

    assert calculations == []
    assert any('区间、约数或上下界' in item for item in blocked)
    assert any('数值与单位不能唯一绑定' in item for item in blocked)
    assert any('2022年存在冲突值' in item for item in blocked)


def test_generic_scope_never_combines_different_original_sources():
    q1 = '2022年市场规模为100亿元。'
    q2 = '2024年市场规模为121亿元。'
    evidence = [
        _evidence('e1', q1, url='https://stats.gov.cn/a'),
        _evidence('e2', q2, url='https://stats.gov.cn/b'),
    ]
    r1 = _record('r1', 'e1', q1, scope='仅限原文引文所述口径')
    r2 = _record('r2', 'e2', q2, scope='仅限原文引文所述口径')
    r1['fields']['auto_extraction']['origin_keys'] = ['source-a']
    r2['fields']['auto_extraction']['origin_keys'] = ['source-b']

    calculations, blocked = auto_calc.build_calculations('p1', [r1, r2], evidence)

    assert calculations == []
    assert sum('少于2个' in item for item in blocked) == 2


def test_explicit_scope_still_requires_one_original_source_group():
    q1 = '2022年国内瓦楞纸箱市场规模为100亿元。'
    q2 = '2024年国内瓦楞纸箱市场规模为121亿元。'
    evidence = [
        _evidence('e1', q1, url='https://stats.gov.cn/a'),
        _evidence('e2', q2, url='https://stats.gov.cn/b'),
    ]
    r1 = _record('r1', 'e1', q1, scope='全国｜成品销售额')
    r2 = _record('r2', 'e2', q2, scope='全国｜成品销售额')
    r1['fields']['auto_extraction']['origin_keys'] = ['source-a']
    r2['fields']['auto_extraction']['origin_keys'] = ['source-b']

    calculations, blocked = auto_calc.build_calculations('p1', [r1, r2], evidence)

    assert calculations == []
    assert sum('少于2个' in item for item in blocked) == 2


def test_generic_scope_never_combines_different_geographies_from_same_source():
    q1 = '2022年长三角市场规模为100亿元。'
    q2 = '2024年珠三角市场规模为121亿元。'
    evidence = [_evidence('e1', q1), _evidence('e2', q2)]
    r1 = _record('r1', 'e1', q1, scope='仅限原文引文所述口径')
    r2 = _record('r2', 'e2', q2, scope='仅限原文引文所述口径')
    r1['fields']['geography'] = '长三角'
    r2['fields']['geography'] = '珠三角'

    calculations, blocked = auto_calc.build_calculations('p1', [r1, r2], evidence)

    assert calculations == []
    assert sum('少于2个' in item for item in blocked) == 2


def test_product_numbers_remain_part_of_metric_and_bounds_are_blocked():
    exact = '2022年3层瓦楞箱价格为3元/平方米。'
    bounded = '2024年3层瓦楞箱价格超4元/平方米。'
    other_product = '2024年5层瓦楞箱价格为5元/平方米。'
    evidence = [
        _evidence('e1', exact), _evidence('e2', bounded),
        _evidence('e3', other_product),
    ]
    records = [
        _record('r1', 'e1', exact, metric='2022年3层瓦楞箱价格'),
        _record('r2', 'e2', bounded, metric='2024年3层瓦楞箱价格'),
        _record('r3', 'e3', other_product, metric='2024年5层瓦楞箱价格'),
    ]

    calculations, blocked = auto_calc.build_calculations('p1', records, evidence)

    assert calculations == []
    assert any('区间、约数或上下界' in item for item in blocked)
    assert sum('少于2个' in item for item in blocked) == 2


def test_advanced_calculation_gaps_are_explicit_without_inventing_inputs():
    gaps = auto_calc.decision_gaps([])

    assert set(gaps) == {'market', 'finance', 'city', 'gate'}
    assert all(gaps.values())
    assert '不自动输出GO' in gaps['gate'][0]


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _MemoryDB:
    def __init__(self):
        self.records = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=()):
        sql = ' '.join(statement.split())
        if sql.startswith('SELECT 1 FROM industry_projects'):
            return _Result({'exists': True})
        if sql.startswith('SELECT basis,verified,fields FROM industry_decision_records'):
            return _Result(self.records.get(params[1]))
        if sql.startswith('INSERT INTO industry_decision_records'):
            record_id, project_id, record_type, name, fields, source, as_of_date = params
            old = self.records.get(record_id)
            if old and (
                old['basis'] != 'calculated' or old['verified']
                or not old.get('fields', {}).get('auto_calculation', {}).get('managed')
            ):
                return _Result()
            self.records[record_id] = {
                'id': record_id, 'project_id': project_id,
                'record_type': record_type, 'name': name,
                'fields': json.loads(fields), 'basis': 'calculated',
                'source': source, 'as_of_date': as_of_date, 'verified': False,
            }
            return _Result()
        if sql.startswith('DELETE FROM industry_decision_records'):
            project_id, current_ids = params
            for record_id, row in list(self.records.items()):
                auto = row.get('fields', {}).get('auto_calculation', {})
                if (row.get('project_id') == project_id and row.get('basis') == 'calculated'
                        and row.get('verified') is False and auto.get('managed') is True
                        and record_id not in current_ids):
                    del self.records[record_id]
            return _Result()
        raise AssertionError(sql)


def test_persistence_is_idempotent_and_does_not_overwrite_human_record(monkeypatch):
    q1 = '2022年国内瓦楞纸箱市场规模为100亿元。'
    q2 = '2024年国内瓦楞纸箱市场规模为121亿元。'
    calculation = auto_calc.build_calculations(
        'p1', [_record('r1', 'e1', q1), _record('r2', 'e2', q2)],
        [_evidence('e1', q1), _evidence('e2', q2)],
    )[0][0]
    db = _MemoryDB()
    monkeypatch.setattr(auto_calc.database, 'connect', lambda: db)

    assert auto_calc._persist('p1', [calculation]) == (1, 0)
    assert auto_calc._persist('p1', [calculation]) == (0, 1)

    saved = db.records[calculation['id']]
    saved['basis'] = 'actual'
    saved['verified'] = True
    saved['name'] = '人工确认结果'
    assert auto_calc._persist('p1', [calculation]) == (0, 1)
    assert db.records[calculation['id']]['name'] == '人工确认结果'
