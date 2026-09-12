"""Local visual fixture, no database writes and no model requests."""
import json
import subprocess
import uuid
import sys
import copy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'config/ppt_runtime.json').read_text(encoding='utf-8'))
folder=ROOT/'storage'/('ppt-layout-sample-'+uuid.uuid4().hex[:8]);folder.mkdir(exist_ok=True)
slides=[
 dict(title='行业研究演示版式样板',chapter=0,layout='cover',bullets=[]),
 dict(title='行业研究的核心判断',chapter=0,layout='conclusions',bullets=['每页聚焦一个结论，并保留影响判断的条件。','关键数字必须对应原报告中的统计口径。','未来预测需要与历史事实分开表达。']),
 dict(title='市场规模与增长',chapter=4,layout='chart',chart_id='sample',bullets=['演示数据只用于检查图表版式。','图表保留年份、数值及计量单位。']),
 dict(title='产业链的三个环节',chapter=6,layout='flow',bullets=['上游：内容与知识产权供给。','中游：制作与技术服务。','下游：分发与用户付费。']),
 dict(title='企业对比的分析维度',chapter=8,layout='comparison',bullets=['收入结构：比较主营业务及收入来源。','盈利能力：核对毛利率与净利率的口径。','研发投入：比较研发支出及技术方向。']),
 dict(title='风险与判断失效条件',chapter=10,layout='risk',bullets=['需求变化：观察用户付费意愿及留存变化。','竞争变化：跟踪价格与供给扩张速度。','监管变化：核对政策适用范围及生效时间。'])]
if '--alternating' in sys.argv:
    slides=[slides[0]]+[copy.deepcopy(s) for s in slides[1:] for _ in range(2)]
    # Exercise maximum supported density as well as consecutive compositions.
    for s in slides:
        if s['layout'] in ('conclusions','flow'):
            s['bullets']=['版式边界测试：'+('测'*56)]*4
if '--dense' in sys.argv:
    for s in slides:
        if s['layout']=='cover': continue
        limit=65 if s['layout']=='chart' else 110
        s['bullets']=[(f'维度{n}：'+('正文容量检查，保留判断与依据。'*10))[:limit] for n in range(3 if s['layout']=='chart' else 4)]
for s in slides:s.update(enabled=True);s.setdefault('chart_id',None)
payload=dict(runtime=config,output=str(folder),slides=slides,snapshot=dict(project=dict(brief=dict(geography='版式演示',history_start=2022,history_end=2024),chapters=[]),evidence=[],charts=[dict(id='sample',chapter_no=4,unit='亿元',labels=['2022','2023','2024'],values=[100,150,210],selected_type='column')]))
file=folder/'input.json';file.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
subprocess.run([config['node'],str(ROOT/'scripts/render_presentation.mjs'),str(file)],cwd=ROOT,check=True)
