import re


_INTERNAL_INSTRUCTION_PATTERNS = (
    r'只依据上述证据撰写本章',
    r'先给出结论.{0,20}再展开事实.{0,10}原因.{0,10}影响',
    r'重要事实用\s*\[编号\]\s*引用',
    r'没有证据的数字不得编造',
    r'证据不足时明确写出.{0,8}证据不足',
    r'需要补充的数据.{0,10}不要用常识填充',
    r'使用中文\s*Markdown',
    r'控制在\s*1200\s*字以内',
    r'不得复述.{0,20}(任务|规则|指令|写作要求)',
)
_INTERNAL_RE = re.compile('|'.join(f'(?:{pattern})' for pattern in _INTERNAL_INSTRUCTION_PATTERNS), re.I)


def _plain_text_math(content: str) -> str:
    """Translate common model-produced LaTeX into renderer-safe plain text.

    Reports are displayed as Markdown and exported to Word, neither of which
    evaluates LaTeX in this application.  This conversion is intentionally
    topic/chapter agnostic and preserves values and variable names; it only
    changes mathematical typesetting syntax.
    """
    text = content or ''

    # Remove math delimiters while preserving a lone currency marker such as
    # "$100". Paired dollar signs are mathematical delimiters here.
    text = re.sub(r'\$\$(.*?)\$\$', lambda match: match.group(1).strip(), text, flags=re.S)
    text = re.sub(
        r'(?<![$￥])\$(?!\d+(?:[.,]\d+)?(?:/|元|美元|USD|RMB|\b))([^$\n]{1,500})\$(?!\$)',
        lambda match: match.group(1).strip(),
        text,
    )
    text = re.sub(r'\\\[(.*?)\\\]', lambda match: match.group(1).strip(), text, flags=re.S)
    text = re.sub(r'\\\((.*?)\\\)', lambda match: match.group(1).strip(), text, flags=re.S)
    text = re.sub(r'(?m)^\s*\\(?:\[|\])\s*$', '', text)

    # Environments and visual sizing commands do not carry business meaning.
    text = re.sub(r'\\(?:begin|end)\{(?:aligned|align\*?|equation\*?|gathered|cases)\}', '', text)
    text = re.sub(r'\\(?:left|right)\b', '', text)
    text = text.replace('&=', '=').replace('&', ' ')

    # Commands that wrap readable labels should retain their contents.
    wrapper = re.compile(r'\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}')
    for _ in range(4):
        updated = wrapper.sub(r'\1', text)
        if updated == text:
            break
        text = updated

    # Subscript braces often occur inside a fraction argument. Flatten them
    # first so the fraction itself becomes a simple, safely convertible form.
    text = re.sub(r'_\{([^{}]+)\}', r'_\1', text)

    # Flatten simple fractions from the inside out. Wrapper removal above also
    # makes expressions such as \frac{\text{收入}}{\text{销量}} convertible.
    fraction = re.compile(r'\\(?:d?frac)\s*\{([^{}]+)\}\s*\{([^{}]+)\}')
    for _ in range(8):
        updated = fraction.sub(lambda match: f'({match.group(1)}) ÷ ({match.group(2)})', text)
        if updated == text:
            break
        text = updated
    text = re.sub(r'\\sqrt\s*\{([^{}]+)\}', r'√(\1)', text)

    replacements = {
        r'\Delta': 'Δ', r'\times': '×', r'\cdot': '×', r'\div': '÷',
        r'\sum': '求和', r'\prod': '连乘', r'\geq': '≥', r'\leq': '≤',
        r'\neq': '≠', r'\approx': '≈', r'\pm': '±', r'\rightarrow': '→',
        r'\to': '→', r'\infty': '∞', r'\%': '%', r'\quad': ' ',
        r'\,': ' ', r'\;': ' ', r'\:': ' ', r'\!': '',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    # Keep subscripts and powers readable without TeX braces. This never
    # changes numeric values: V_{0} -> V_0 and x^{2} -> x^2.
    text = re.sub(
        r'\^\{([^{}]+)\}',
        lambda match: '^(' + match.group(1) + ')' if re.search(r'[+×÷/\s-]', match.group(1))
        else '^' + match.group(1),
        text,
    )

    # A model can emit an uncommon command despite the prompt. Retain its name
    # as plain text instead of failing an otherwise valid report or silently
    # deleting the associated expression. A TeX line break becomes a newline.
    text = text.replace('\\\\', '\n')
    text = re.sub(r'\\([A-Za-z]+)', r'\1', text)
    return text


def sanitize_generated_content(content: str) -> str:
    """Remove internal prompt text accidentally echoed by a model."""
    cleaned = []
    for raw in (content or '').splitlines():
        visible = re.sub(r'^[#>*\s-]+|[#*\s]+$', '', raw).strip()
        if visible and _INTERNAL_RE.search(visible):
            continue
        cleaned.append(raw.rstrip())
    text = _plain_text_math('\n'.join(cleaned))
    for source, target in {'Quantity Sold':'销量', 'Material Cost':'单位材料成本',
                           'Unit Cost':'单位成本', 'Profit':'利润', 'Price':'单位售价',
                           'Yield':'良率', 'Utilization':'产能利用率'}.items():
        text = text.replace(source, target)
    # Repair the exact legacy pattern whose dimensions are wrong. It is shown
    # as a method and data requirement, not replaced with invented inputs.
    text = re.sub(
        r'(?s)3\.\s*\*\*良率或利用率变动对利润的影响\*\*：.*?其中，.*?是单位成本。',
        '3. **良率与产能利用率需要分别测算**：\n\n'
        '- 良率：先根据投料量与良率计算合格产出，再计入废料残值、返工成本和实际可售数量。'
        '缺少投料量、基准良率和返工成本时，不输出利润变化值。\n'
        '- 产能利用率：先用有效产能×利用率计算产量；只有新增产量可以售出时，才按新增销量×单位贡献估算利润变化，'
        '并单独计入新增班次或固定成本。缺少需求约束和单位贡献时，不输出利润变化值。',
        text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def _sentences_for_review(content):
    result = []
    for line in (content or '').splitlines():
        if line.lstrip().startswith(('#', '|')):
            continue
        line = re.sub(r'^\s*(?:[-*+]\s+|\d+[.)、]\s*)', '', line)
        for sentence in re.split(r'[。！？\n]', line):
            normalized = re.sub(r'\[\d+(?:-\d+)?\]|[\s*`]', '', sentence)
            if len(normalized) >= 25:
                result.append(normalized)
    return result


def deduplicate_exact_paragraphs(content, previous_contents=()):
    """Remove only identical prose paragraphs, including identical citations.

    Tables/lists and different references remain intact for human/model review.
    """
    blocks = re.split(r'\n\s*\n', content.strip())
    seen = set()
    for previous in previous_contents:
        for block in re.split(r'\n\s*\n', (previous or '').strip()):
            lines = block.splitlines()
            prose = all(not re.match(r'^\s*(?:[#|>]|[-*+]\s|\d+[.)、]\s)', line) for line in lines)
            key = re.sub(r'\s+', '', block)
            if prose and len(key) >= 40:
                seen.add(key)
    kept, removed = [], []
    for block in blocks:
        lines = block.splitlines()
        prose = all(not re.match(r'^\s*(?:[#|>]|[-*+]\s|\d+[.)、]\s)', line) for line in lines)
        key = re.sub(r'\s+', '', block)
        if prose and len(key) >= 40:
            if key in seen:
                removed.append(block)
                continue
            seen.add(key)
        kept.append(block)
    # Drop headings whose only paragraph was removed; retain headings with children.
    result = []
    for block in reversed(kept):
        match = re.fullmatch(r'(#{1,6})\s+[^\n]+', block.strip())
        if match:
            following = result[-1].strip() if result else ''
            next_heading = re.match(r'^(#{1,6})\s+', following)
            if not following or (next_heading and len(next_heading[1]) <= len(match[1])):
                continue
        result.append(block)
    return '\n\n'.join(reversed(result)), removed


def repeated_passages(content, previous_contents=()):
    previous = {s for text in previous_contents for s in _sentences_for_review(text)}
    seen, repeated = set(), []
    for sentence in _sentences_for_review(content):
        if sentence in seen or sentence in previous:
            if sentence not in repeated:
                repeated.append(sentence)
        seen.add(sentence)
    return repeated


def remove_repeated_material(content, previous_contents=()):
    """Remove exact repeated prose sentences and numeric rows before AI补写.

    This is deliberately narrower than semantic rewriting: only material that
    the existing quality gate can prove is duplicated is removed. Headings and
    unique statements remain as the draft skeleton for the supplementary pass.
    """
    previous_sentences = {
        sentence for text in previous_contents for sentence in _sentences_for_review(text)
    }

    def data_key(line):
        if not re.match(r'^\s*(?:[-*+]\s+|\d+[.)、]\s*|\|)', line):
            return ''
        row = re.sub(r'^\s*(?:[-*+]\s+|\d+[.)、]\s*)', '', line)
        row = re.sub(r'\[\d+(?:-\d+)?\]|[\s*`|]', '', row).strip('。；;')
        return row if len(row) >= 6 and re.search(r'\d', row) else ''

    previous_rows = {
        key for text in previous_contents for line in (text or '').splitlines()
        if (key := data_key(line))
    }
    seen_sentences, seen_rows = set(), set()
    kept, removed = [], []
    for raw_line in (content or '').splitlines():
        row_key = data_key(raw_line)
        if row_key and (row_key in previous_rows or row_key in seen_rows):
            removed.append(raw_line.strip())
            continue
        if row_key:
            seen_rows.add(row_key)

        prefix_match = re.match(r'^(\s*(?:[-*+]\s+|\d+[.)、]\s*))', raw_line)
        prefix = prefix_match.group(1) if prefix_match else ''
        body = raw_line[len(prefix):]
        parts = re.split(r'(?<=[。！？])', body)
        unique_parts = []
        for part in parts:
            normalized = re.sub(r'\[\d+(?:-\d+)?\]|[\s*`]', '', part.rstrip('。！？'))
            duplicate = (
                len(normalized) >= 25
                and (normalized in previous_sentences or normalized in seen_sentences)
            )
            if duplicate:
                removed.append(part.strip())
                continue
            if len(normalized) >= 25:
                seen_sentences.add(normalized)
            unique_parts.append(part)
        rebuilt = ''.join(unique_parts).strip()
        if rebuilt:
            kept.append(prefix + rebuilt)
        elif not body.strip():
            kept.append(raw_line)

    # Reuse the existing orphan-heading cleanup without treating the retained
    # unique text as previously published material.
    cleaned, _ = deduplicate_exact_paragraphs('\n'.join(kept))
    return cleaned, removed


def remove_unready_location_conclusions(content):
    """Strip unsupported city scoring/ranking when location inputs are absent.

    The function does not invent substitute scores. It retains qualitative
    methodology and evidence gaps, then states the decision boundary explicitly.
    """
    unsafe_heading = re.compile(
        r'候选城市评分|权重变化敏感性|推荐城市|备选城市|不推荐条件|'
        r'综合排名|城市排名|选址排名|结论与建议'
    )
    sections = re.split(r'(?m)(?=^#{3,6}\s+)', content or '')
    kept, removed = [], []
    for section in sections:
        heading = section.splitlines()[0] if section.splitlines() else ''
        if unsafe_heading.search(heading):
            removed.append(section.strip())
            continue
        kept.append(section)
    text = ''.join(kept)

    def table_filter(match):
        block = match.group(0)
        header = '\n'.join(block.splitlines()[:2])
        if re.search(r'总分|综合得分|评分|权重\s*[%（(]', header):
            removed.append(block.strip())
            return ''
        return block

    text = re.sub(r'(?:^\s*\|[^\n]+\|\s*$\n?){2,}', table_filter, text, flags=re.M)
    safe_lines = []
    unsafe_line = re.compile(
        r'(?:推荐|首选|备选|优先(?:选择|布局|落地|考虑)|不推荐).{0,30}'
        r'(?:城市|地区|区域|基地|园区|选址|落地)|'
        r'(?:城市|地区|区域|基地|园区|选址).{0,30}'
        r'(?:推荐|首选|备选|优先|排名第)|'
        r'(?:综合)?总分.{0,20}\d|评分最高|排名第\s*[一二三四五六七八九十\d]'
    )
    for line in text.splitlines():
        if unsafe_line.search(re.sub(r'[*`]', '', line)):
            removed.append(line.strip())
            continue
        safe_lines.append(line)
    text = '\n'.join(safe_lines).strip()
    boundary = (
        '### 选址结论边界\n\n'
        '当前结构化选址测算尚未就绪。正文中的城市仅作为候选对象进行定性比较；评价权重须由用户确认，'
        '并补齐客户密度、物流、厂房、人工、能源、环保和供应链指标后由程序统一计算。现阶段不形成地点排序、'
        '综合得分或工厂落地结论。'
    )
    if '### 选址结论边界' not in text:
        text = (text + '\n\n' + boundary).strip()
    cleaned, _ = deduplicate_exact_paragraphs(text)
    return cleaned, [item for item in removed if item]


def remove_unready_final_decisions(content):
    """Downgrade unsupported entry decisions to an explicit verification hold."""
    unsafe_heading = re.compile(
        r'分阶段门槛与决策|条件进入、暂缓或退出条件|决策结论|分阶段门槛$|'
        r'进入结论|投资结论|最终结论'
    )
    sections = re.split(r'(?m)(?=^#{3,6}\s+)', content or '')
    kept, removed = [], []
    for section in sections:
        heading = section.splitlines()[0] if section.splitlines() else ''
        if unsafe_heading.search(re.sub(r'[*`]', '', heading)):
            removed.append(section.strip())
            continue
        kept.append(section)
    text = ''.join(kept)

    def table_filter(match):
        block = match.group(0)
        header = '\n'.join(block.splitlines()[:2]).upper()
        if re.search(r'GO|NO\s*[-–—]?\s*GO|HOLD|决策门槛|退出条件', header):
            removed.append(block.strip())
            return ''
        return block

    text = re.sub(r'(?:^\s*\|[^\n]+\|\s*$\n?){2,}', table_filter, text, flags=re.M)
    state_line = re.compile(
        r'(?<![A-Z])(?:NO\s*[-–—]?\s*GO|GO|HOLD)(?![A-Z]).{0,100}(?:门槛|条件|：|:)|'
        r'(?:决策状态|决策结论|最终结论|综合判断|进入建议|投资建议).{0,80}'
        r'(?<![A-Z-])(?:NO\s*[-–—]?\s*GO|GO)(?![A-Z-])', re.I
    )
    safe_lines = []
    for line in text.splitlines():
        visible = re.sub(r'[*`#]', '', line)
        if state_line.search(visible):
            removed.append(line.strip())
            continue
        safe_lines.append(line)
    text = '\n'.join(safe_lines).strip()
    boundary = (
        '### 决策状态：待验证（HOLD）\n\n'
        '当前尚未形成经过用户确认或程序计算的进入门槛，因此本报告不输出确定性的进入或退出结论。'
        '现阶段状态为待验证（HOLD）：先完成设备与工艺验证、客户认证与试单、批量交付能力、回款周期、'
        '单位经济和现金需求核验，再由统一数据底座计算决策结果。\n\n'
        '### GO／HOLD／NO-GO门槛框架\n\n'
        '- **GO**：所有关键输入已经核实，并由程序计算达到用户确认的进入边界后方可采用。\n'
        '- **HOLD**：任一关键输入缺失、来源冲突或尚未完成客户与生产验证时维持待验证状态。\n'
        '- **NO-GO**：只有用户先确认退出边界，且经核实数据和程序计算触发该边界后方可采用。\n\n'
        '上述三档仅是决策流程定义，不代表本项目当前已经满足任何进入或退出条件。'
    )
    if '### 决策状态：待验证（HOLD）' not in text:
        text = (text + '\n\n' + boundary).strip()
    cleaned, _ = deduplicate_exact_paragraphs(text)
    return cleaned, [item for item in removed if item]


def repetition_issues(content, previous_contents=()):
    sentences = _sentences_for_review(content)
    previous = {s for text in previous_contents for s in _sentences_for_review(text)}
    seen = set(); repeated = []
    for sentence in sentences:
        if sentence in seen or sentence in previous:
            repeated.append(sentence)
        seen.add(sentence)
    total = sum(map(len, sentences))
    issues = []
    if len(repeated) >= 3 and sum(map(len, repeated)) >= max(120, total * .25):
        issues.append(f'正文存在大段重复（{len(repeated)}条长句与本章或前文章节相同），请重新生成该章并突出本章问题')
    def data_rows(text):
        rows=[]
        for line in (text or '').splitlines():
            if not re.match(r'^\s*(?:[-*+]\s+|\d+[.)、]\s*|\|)',line):continue
            row=re.sub(r'^\s*(?:[-*+]\s+|\d+[.)、]\s*)','',line)
            row=re.sub(r'\[\d+(?:-\d+)?\]|[\s*`|]','',row).strip('。；;')
            if len(row)>=6 and re.search(r'\d',row):rows.append(row)
        return rows
    prior={r for text in previous_contents for r in data_rows(text)}
    seen=set(); duplicates=set()
    for row in data_rows(content):
        if row in prior or row in seen:duplicates.add(row)
        seen.add(row)
    if len(duplicates)>=3:
        issues.append(f'重复数据列表：{len(duplicates)}条数据与前文或本章重复，请保留在主要分析章节，其他章节仅交叉引用')
    return issues


def complete_context(text, limit):
    """Limit model input at a complete line/sentence, never mid-fact."""
    text=(text or '').strip()
    if len(text)<=limit:return text
    prefix=text[:limit]
    ends=list(re.finditer(r'[。！？](?:\[\d+(?:-\d+)?\])*|\n',prefix))
    if not ends:return '〔原始段落超过输入预算，未提供不完整片段〕'
    return prefix[:ends[-1].end()].rstrip()+'\n〔后续内容未纳入本次上下文〕'


def chapter_issues(content, chapter_no, research_template='general'):
    """Conservative rule checks, not a general semantic/factual verifier."""
    issues=[]
    lines=[line.strip() for line in (content or '').splitlines() if line.strip()]
    if not lines:return issues
    tail=lines[-1].replace('**','')
    if re.match(r'^#{1,6}\s+',tail) or tail.endswith(('：',':','，',',')):
        issues.append('尾部内容不完整：以标题或未完句结尾')
    if re.search(r'(?:抖音|快手|平台)\s*TO(?:P)?\s*$',tail,re.I):
        issues.append('尾部内容不完整：平台榜单名称或描述未写完')
    if re.search(r'(?i)(?<![A-Za-z])near\s*\d',content):
        issues.append('中文正文残留 near 数值拼接，请核对来源并规范表述')
    if re.search(r'\\(?:\[|\]|\(|\)|text\{|Delta\b|times\b|frac\{)', content):
        issues.append('正文含未渲染LaTeX公式；改用中文变量名和普通文本公式')
    if chapter_no in (8, 9):
        compact = re.sub(r'\s+', '', content)
        if (re.search(r'(?:良率|Yield).{0,40}(?:利用率|Utilization)', compact, re.I)
                and re.search(r'(?:Δ良率|DeltaYield|良率变动).{0,50}(?:销量|QuantitySold).{0,30}(?:单位成本|UnitCost)', compact, re.I)):
            issues.append('敏感性公式错误：良率与产能利用率不能合并，且良率变化不能直接按销量×单位成本计算')
    sections=re.split(r'(?m)^\s*#{1,6}\s+',content)
    for section in sections:
        heading=section.split('\n',1)[0].replace('**','').strip()
        if not re.search(r'市场规模.*(?:增速|增长)|市场规模与增速',heading):continue
        rows=re.findall(r'(?m)^\s*[-*+]\s+.*20\d{2}年.*$',section)
        if (chapter_no == 1 or (chapter_no == 2 and research_template != 'manufacturing')) and len(rows)>=3:
            issues.append('章节职责不符：定义或发展历程章展开了完整年度市场规模列表，应集中到第4章')
        # Detect mixed parent/sub-market series without knowing the industry in
        # advance. Explicit labels before “市场/市场规模” are treated as scopes;
        # geography prefixes are normalized so 中国X and X do not look like two
        # products merely because of wording.
        scopes = set()
        for row in rows:
            visible = re.sub(r'^\s*[-*+]\s+', '', row)
            visible = re.sub(r'^.*?20\d{2}年[，,:：\s]*', '', visible)
            match = re.search(
                r'([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·（）()\-/]{1,29}?)'
                r'(?:市场规模|市场[：:])',
                visible,
            )
            if match:
                scope = re.sub(r'^(?:中国|国内|全国|全球)', '', match.group(1)).strip('的：: ')
                if scope:
                    scopes.add(scope)
        if len(scopes)>1:
            issues.append('市场数据口径混用：同一数据列表包含不同上位或细分市场范围，请分别标明指标与范围后分组呈现')
    return list(dict.fromkeys(issues))


def quality_issues(content: str) -> list[str]:
    issues = []
    if _INTERNAL_RE.search(content or ''):
        issues.append('模型复述了内部写作指令')
    if len(re.sub(r'\s+', '', content or '')) < 80:
        issues.append('正文过短')
    if re.search(r'市场规模[、，]销量或装机量分别为', content or ''):
        issues.append('疑似将研究问题直接拼接到答案，市场规模、销量与装机量口径未分别说明')
    return issues
