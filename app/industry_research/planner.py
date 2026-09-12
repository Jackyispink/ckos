from datetime import date

from .schemas import ResearchBrief
from .manufacturing import CHAPTERS as MANUFACTURING_CHAPTERS, FOCUS


CHAPTERS = [
    (1, '行业定义与分类', ['行业的严格定义、产品边界和统计口径是什么？', '行业包含哪些细分市场，各细分市场之间是什么关系？', '本报告应纳入和排除哪些业务？']),
    (2, '行业发展历程与生命周期', ['哪些政策、技术和商业事件构成行业关键转折点？', '行业当前处于哪个生命周期阶段，判断依据是什么？', '历史增长阶段与调整阶段分别由什么驱动？']),
    (3, '宏观与政策环境', ['现行国家和地方政策通过什么机制影响需求、供给与盈利？', '经济、人口和社会因素如何影响行业？', '关键技术路线的成熟度与替代关系如何？']),
    (4, '市场规模、结构与增长预测', ['当前市场规模、销量或装机量分别是多少，统计口径是什么？', '过去五年的增速、拐点与原因是什么？', '市场按产品、地区、客户和场景如何拆分？', '未来市场规模预测基于哪些可验证假设？']),
    (5, '供需、产能与价格', ['现有及新增产能、产量、开工率和库存如何？', '需求量、渗透率、出口和主要应用场景如何变化？', '供需增速差如何传导至价格和企业盈利？']),
    (6, '产业链与价值链', ['上中下游分别提供什么产品，代表企业是谁？', '各环节价值量、毛利率、集中度和议价能力如何？', '利润与稀缺能力集中在哪些环节，为什么？']),
    (7, '行业竞争格局', ['主要企业的份额、梯队和行业集中度如何？', '企业依靠哪些要素竞争，真正的竞争规则是什么？', '新进入者面临哪些技术、资金、认证、品牌和渠道壁垒？']),
    (8, '重点企业与商业模式', ['代表企业的业务、财务、研发和客户结构如何比较？', '客户为何付费，企业如何定价、回款和形成利润？', '龙头企业为何能获得更高份额或盈利能力？']),
    (9, '驱动因素、制约因素与核心矛盾', ['行业增长的完整因果链是什么？', '主要制约因素通过什么路径影响商业化？', '真正决定行业未来的1—3个核心变量是什么？']),
    (10, '未来趋势、机会与风险', ['未来三至五年行业结构、技术和商业模式将如何变化？', '哪些细分市场可能获得超额增长，依据是什么？', '主要风险的触发事件、传导路径和影响对象是什么？', '在什么条件下本报告判断会失效？']),
]


def _query_fragment(value, limit=140):
    """Compact rich brief text for search while preserving the stored brief."""
    text = ' '.join((value or '').split()).strip('，,；;。 ')
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    boundary = max(prefix.rfind(mark) for mark in ('；', ';', '。', '，', ',', '、', ' '))
    if boundary >= limit // 2:
        prefix = prefix[:boundary]
    return prefix.rstrip('，,；;。 ')


def build_plan(brief: ResearchBrief):
    qualifier = ' '.join(part.strip() for part in (
        f'{_query_fragment(brief.geography, 60)}{brief.topic}',
        _query_fragment(brief.product_scope), _query_fragment(brief.included_segments)
    ) if part and part.strip())
    compact_focus = _query_fragment(brief.focus, 160)
    focus_hint = (' 重点 ' + compact_focus) if compact_focus else ''
    years = f'{brief.history_start}-{brief.history_end}'
    plans = []
    template = MANUFACTURING_CHAPTERS if brief.research_template=='manufacturing' else CHAPTERS
    for no, title, base_questions in template:
        questions=list(base_questions)
        if brief.research_template=='manufacturing':
            if brief.depth == 'deep':
                from .manufacturing import DEEP_QUESTIONS
                questions.extend(DEEP_QUESTIONS.get(no, []))
            if no == 10 and brief.target_company:
                questions.append(f'{brief.target_company}的内部优势劣势有哪些可验证证据，哪些仍待企业确认？')
            if no == 3 and brief.downstream_applications:
                questions.append(f'{_query_fragment(brief.downstream_applications, 180)}客户的采购链、认证、份额分配和账期如何验证？')
            if no == 9 and brief.key_companies:
                questions.append(f'{_query_fragment(brief.key_companies, 180)}中哪些是同一目标业务口径的直接可比企业？')
            if no in (2,3,4,5,6,8,9):
                questions.append(FOCUS[brief.manufacturing_type]+'有哪些公开证据和待补数据？')
            if no==10 and brief.target_company:questions.append(f'针对{brief.target_company}，有证据支持的内部优势劣势和外部机会威胁分别是什么？')
        queries = []
        for question in questions:
            stem = question.rstrip('？').replace('如何', '').replace('是什么', '')
            queries.append(f'{qualifier} {stem} {years}{focus_hint}'.replace('  ',' '))
        if brief.research_template=='manufacturing':
            manufacturing_queries={
              1:[f'{qualifier} 产品标准 统计口径 国家标准'],
              2:[f'{qualifier} {_query_fragment(brief.downstream_applications)} 市场规模 产量 单价 {years}',f'{qualifier} 区域市场 服务半径 需求测算'],
              3:[f'{qualifier} {_query_fragment(brief.downstream_applications)} 供应商准入 采购 招标 厂审 账期'],
              4:[f'{qualifier} 区域生产企业 产能 工厂',f'{qualifier} 原材料供应商 基地 价格 交期'],
              5:[f'{qualifier} 产品规格 性能 认证 标准 毛利率'],
              6:[f'{qualifier} 生产线 设备 报价 产能 能耗 良率'],
              7:[f'{qualifier} 工厂选址 客户密度 原料 物流 厂房 能源 环保'],
              8:[f'{qualifier} 设备投资 单位成本 盈亏平衡 流动资金 账期'],
              9:[f'{qualifier} 上市公司 分部收入 毛利率 应收 存货 产能'],
              10:[f'{qualifier} 新建工厂 项目风险 进入条件 退出条件'],
            }
            priority_queries = list(manufacturing_queries[no])
            if no == 9 and brief.key_companies:
                priority_queries.insert(0, f'{_query_fragment(brief.key_companies, 180)} 年报 分部收入 毛利率 应收 存货 产能')
            if no == 10 and brief.target_company:
                priority_queries.insert(0, f'{brief.target_company} 设备 技术 客户 资金 团队 能力 证据')
            if no == 1 and brief.excluded_segments.strip():
                priority_queries.insert(0, f'{qualifier} 与 {_query_fragment(brief.excluded_segments)} 产品边界 统计口径 区别')
            queries = priority_queries + queries
        elif no == 3:
            queries.extend([f'{qualifier} 政策 site:gov.cn', f'{qualifier} 行业标准'])
        elif no == 4:
            queries.extend([f'{qualifier} 市场规模 CAGR 预测', f'{qualifier} 销量 出货量'])
        elif no == 8 and brief.key_companies:
            queries.append(f'{_query_fragment(brief.key_companies, 180)} 年报 营收 毛利率 研发投入')
        plans.append({'chapter_no': no, 'title': title, 'questions': questions, 'queries': list(dict.fromkeys(queries))})
    return plans


def brief_summary(brief: ResearchBrief):
    return {
        'scope': f'{brief.geography} · {brief.topic}',
        'period': f'{brief.history_start}—{brief.history_end}，预测至{brief.forecast_end}',
        'purpose': brief.purpose,
        'data_cutoff': date.today().isoformat(),
    }
