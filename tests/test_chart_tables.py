from app.industry_research.charts import discover


def charts(content):
    return [c for c in discover({'chapters':[{'chapter_no':4,'title':'市场','content':content}]}) if c['kind']=='table_series']


def test_three_years_retained():
    data=charts('| 年份 | 需求（万㎡） |\n| --- | --- |\n| 2023 | 100 |\n| 2024 | 120 |\n| 2025 | 150 |')
    assert data[0]['values']==[100,120,150]
    assert 'line' in data[0]['chart_types']


def test_comparison_is_not_trend():
    data=charts('| 企业 | 收入（万元） |\n| --- | --- |\n| A | 1,200 |\n| B | 900[1] |')
    assert data[0]['values']==[1200,900]
    assert 'line' not in data[0]['chart_types']


def test_missing_or_range_not_silently_dropped():
    for value in ['待核实','100—200','约120']:
        assert not charts(f'| 年份 | 需求（吨） |\n| --- | --- |\n| 2023 | 100 |\n| 2024 | {value} |')


def test_no_unit_no_chart():
    assert not charts('| 客户 | 需求 |\n| --- | --- |\n| A | 100 |\n| B | 200 |')
