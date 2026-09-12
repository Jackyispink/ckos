(() => {
  if (location.pathname !== '/industry') return;
  const ctx = window.ckosDecisionContext;
  if (!ctx?.decisionPanel) return;

  const basisLabels = {
    actual: '实际数据',
    quote: '真实报价',
    assumption: '用户假设',
    unverified: '待验证',
  };
  const number = value => Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 2});
  const valueOrNull = input => input.value.trim() === '' ? null : Number(input.value);
  const field = (labelText, input) => {
    const label = document.createElement('label');
    label.append(document.createTextNode(labelText), input);
    return label;
  };
  const input = (name, type = 'text') => {
    const node = document.createElement('input');
    node.name = name;
    node.type = type;
    if (type === 'number') {
      node.step = 'any';
      node.min = '0';
    }
    return node;
  };
  const basisSelect = name => {
    const select = document.createElement('select');
    select.name = name;
    for (const [value, title] of Object.entries(basisLabels)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = title;
      select.append(option);
    }
    select.value = 'unverified';
    return select;
  };
  const gateBasisSelect = name => {
    const select = basisSelect(name);
    const option = document.createElement('option');
    option.value = 'calculated';
    option.textContent = '程序计算结果';
    select.append(option);
    return select;
  };
  const resultLine = (box, text, className = '') => {
    const p = document.createElement('p');
    p.textContent = text;
    if (className) p.className = className;
    box.append(p);
  };
  const saveResult = async (kind, title, result, projectId, asOfDate = '', recordId = '') => {
    if (!projectId || projectId !== ctx.getProjectId()) throw Error('研究项目已切换，请重新计算。');
    const projectTitle = ctx.getProject()?.title || projectId;
    const unresolved = (result.gaps?.length || 0) + (result.pending?.length || 0);
    const saved = await ctx.api(`/api/industry/projects/${projectId}/decision-records${recordId ? '/' + recordId : ''}`, {
      method: recordId ? 'PATCH' : 'POST',
      body: JSON.stringify({
        record_type: kind,
        name: title,
        fields: result,
        basis: 'calculated',
        source: '程序计算；逐项原始来源、单位、范围与依据见输入明细',
        as_of_date: String(asOfDate || result.inputs?.year || new Date().toISOString().slice(0, 10)),
        verified: unresolved === 0,
      }),
    });
    const switched = projectId !== ctx.getProjectId();
    const refreshErrors = [];
    if (! switched) {
      try { await ctx.refreshDecisionRecords(); } catch (error) { refreshErrors.push('列表刷新失败：' + error.message); }
      try { await ctx.reloadProject?.(); } catch (error) { refreshErrors.push('页面刷新失败：' + error.message); }
    }
    return {
      record: saved,
      projectTitle,
      warning: switched
        ? `记录已保存到原项目（ID ${projectId}），但当前项目已切换。`
        : refreshErrors.join('；'),
    };
  };

  const calculatorResetters = [];
  const registerCalculatorReset = (form, output, save, resetState) => {
    const initial = [...form.elements].map(node => ({node, value: node.value, checked: node.checked}));
    calculatorResetters.push(() => {
      for (const item of initial) {
        if ('checked' in item.node) item.node.checked = item.checked;
        if ('value' in item.node) item.node.value = item.value;
      }
      resetState();
      save.disabled = true;
      output.textContent = '已切换研究项目，请填写或载入当前项目的数据后重新计算。';
    });
  };
  document.addEventListener('ckos:industry-project-changed', () => {
    for (const reset of calculatorResetters) reset();
  });

  const workspace = document.createElement('section');
  workspace.className = 'decision-calculator-workspace';
  const heading = document.createElement('h3');
  heading.textContent = '人工专项测算（通常无需使用）';
  const intro = document.createElement('p');
  intro.textContent = '正常生成行业研究报告不需要填写这里。仅当你要把企业内部产能、报价或投资假设加入专项情景时使用；模型不参与算术，缺失或未核对时只输出“待验证”。';
  workspace.append(heading, intro);
  const formAnchor = ctx.decisionPanel.querySelector('.decision-data-form');
  formAnchor.parentNode.insertBefore(workspace, formAnchor);

  function marketCalculator() {
    const panel = document.createElement('details');
    panel.className = 'decision-calculator';
    const summary = document.createElement('summary');
    summary.textContent = 'TAM / SAM / SOM 市场空间测算';
    const form = document.createElement('form');
    const common = document.createElement('div');
    common.className = 'decision-calculator-common';
    const scope = input('scope');
    scope.required = true;
    scope.placeholder = '产品 × 地域 × 客户口径';
    const year = input('year', 'number');
    year.required = true;
    year.min = '2000';
    year.max = '2100';
    const baseUnit = input('base_unit');
    baseUnit.required = true;
    baseUnit.placeholder = '如：吨饮料';
    const demandUnit = input('demand_unit');
    demandUnit.required = true;
    demandUnit.placeholder = '如：㎡纸箱';
    common.append(field('统一测算范围', scope), field('测算年份', year),
      field('基础业务单位', baseUnit), field('包装需求单位', demandUnit));

    const definitions = [
      ['base', '基础业务量'],
      ['unit_demand', '单位业务包装需求'],
      ['unit_price', '包装平均售价'],
      ['regional_coverage_pct', '目标地域占比'],
      ['product_fit_pct', '目标产品适配率'],
      ['service_coverage_pct', '服务半径可覆盖率'],
      ['acquisition_rate_pct', '预计市场获取率'],
      ['effective_capacity', '可兑现有效产能'],
    ];
    const table = document.createElement('table');
    table.className = 'decision-input-table market-input-table';
    table.innerHTML = '<thead><tr><th>输入</th><th>数值</th><th>自动单位</th><th>依据</th><th>数据日期</th><th>原始来源</th><th>来源组ID</th><th>已核对</th><th>冲突</th></tr></thead>';
    const tbody = document.createElement('tbody');
    for (const [key, title] of definitions) {
      const tr = document.createElement('tr');
      tr.dataset.key = key;
      const value = input(key + '_value', 'number');
      const source = input(key + '_source');
      source.placeholder = '来源名称/URL/访谈编号';
      const basis = basisSelect(key + '_basis');
      const date = input(key + '_date', 'date');
      const origin = input(key + '_origin');
      origin.placeholder = '同一原始来源填同ID';
      const verified = input(key + '_verified', 'checkbox');
      const conflict = input(key + '_conflict', 'checkbox');
      const unit = document.createElement('span');
      unit.dataset.unit = key;
      for (const node of [title, value, unit, basis, date, source, origin, verified, conflict]) {
        const td = document.createElement('td');
        typeof node === 'string' ? td.append(document.createTextNode(node)) : td.append(node);
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    const units = () => {
      const b = baseUnit.value.trim() || '基础单位';
      const d = demandUnit.value.trim() || '需求单位';
      const mapping = {
        base: b,
        unit_demand: `${d}/${b}`,
        unit_price: `元/${d}`,
        regional_coverage_pct: '%',
        product_fit_pct: '%',
        service_coverage_pct: '%',
        acquisition_rate_pct: '%',
        effective_capacity: d,
      };
      for (const [key, unit] of Object.entries(mapping)) table.querySelector(`[data-unit="${key}"]`).textContent = unit;
      return mapping;
    };
    baseUnit.addEventListener('input', units);
    demandUnit.addEventListener('input', units);
    units();

    const calculate = document.createElement('button');
    calculate.textContent = '程序计算市场空间';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary-action';
    save.textContent = '保存测算到报告';
    save.disabled = true;
    const actions = document.createElement('div');
    actions.className = 'industry-actions';
    actions.append(calculate, save);
    const output = document.createElement('div');
    output.className = 'decision-calculation-result';
    output.setAttribute('aria-live', 'polite');
    form.append(common, table, actions);
    panel.append(summary, form, output);
    workspace.append(panel);

    let last = null;
    let lastProject = null;
    let savedRecordId = '';
    registerCalculatorReset(form, output, save, () => { last = null; lastProject = null; savedRecordId = ''; });
    form.addEventListener('input', () => {
      last = null;
      save.disabled = true;
      output.textContent = '输入已变化，请重新计算。';
    });
    form.onsubmit = async event => {
      event.preventDefault();
      calculate.disabled = true;
      output.textContent = '正在执行确定性公式…';
      try {
        const unitMap = units();
        const facts = {};
        for (const [key] of definitions) {
          facts[key] = {
            value: valueOrNull(form.elements.namedItem(key + '_value')),
            unit: unitMap[key],
            scope: scope.value.trim(),
            year: Number(year.value),
            source: form.elements.namedItem(key + '_source').value.trim(),
            origin_id: form.elements.namedItem(key + '_origin').value.trim(),
            date: form.elements.namedItem(key + '_date').value || null,
            basis: form.elements.namedItem(key + '_basis').value,
            verified: form.elements.namedItem(key + '_verified').checked,
            conflict: form.elements.namedItem(key + '_conflict').checked,
          };
        }
        lastProject = ctx.getProjectId();
        last = await ctx.api('/api/industry/decision/market/calculate', {
          method: 'POST',
          body: JSON.stringify({
            scope: scope.value.trim(),
            year: Number(year.value),
            base_unit: baseUnit.value.trim(),
            demand_unit: demandUnit.value.trim(),
            facts,
          }),
        });
        output.replaceChildren();
        resultLine(output, '状态：' + last.status, 'decision-result-status');
        if (last.gaps.length) resultLine(output, '缺失输入：' + last.gaps.join('、'));
        if (last.pending.length) resultLine(output, '待核对输入：' + last.pending.join('、'));
        if (Object.keys(last.results).length) {
          resultLine(output, `TAM：${number(last.results.tam_yuan)} 元`);
          resultLine(output, `SAM：${number(last.results.sam_yuan)} 元`);
          resultLine(output, `SOM：${number(last.results.som_yuan)} 元；约束因素：${last.results.binding_constraint}`);
        }
        for (const text of last.limitations) resultLine(output, '边界：' + text);
        save.disabled = false;
      } catch (error) {
        last = null;
        save.disabled = true;
        output.textContent = '测算失败：' + error.message;
      } finally {
        calculate.disabled = false;
      }
    };
    save.onclick = async () => {
      if (!last) return;
      save.disabled = true;
      let persisted = false;
      try {
        const saved = await saveResult('market', `${last.inputs.scope} ${last.inputs.year}年 TAM/SAM/SOM`,
          last, lastProject, '', savedRecordId);
        savedRecordId = saved.record.id;
        persisted = true;
        resultLine(output, `已保存到「${saved.projectTitle}」；重新生成报告时写入第2章。`, 'decision-save-ok');
        if (saved.warning) resultLine(output, saved.warning, 'decision-save-warning');
      } catch (error) {
        resultLine(output, '保存失败：' + error.message);
      } finally {
        if (!persisted) save.disabled = false;
      }
    };
  }

  function financeCalculator() {
    const panel = document.createElement('details');
    panel.className = 'decision-calculator';
    const summary = document.createElement('summary');
    summary.textContent = 'CAPEX、单位经济、盈亏平衡与流动资金测算';
    const form = document.createElement('form');
    const common = document.createElement('div');
    common.className = 'decision-calculator-common';
    const scope = input('scope');
    scope.required = true;
    scope.placeholder = '同一产品/生产方案/区域口径';
    const year = input('year', 'number');
    year.required = true;
    year.min = '2000';
    year.max = '2100';
    const quantityUnit = input('quantity_unit');
    quantityUnit.required = true;
    quantityUnit.placeholder = '如：万㎡';
    common.append(field('统一财务范围', scope), field('测算年份', year), field('数量单位', quantityUnit));
    const definitions = [
      ['sales', '年销量'],
      ['capacity', '年有效产能'],
      ['price', '单位售价'],
      ['variable_cost', '单位变动成本'],
      ['fixed_cash_cost', '年固定现金成本'],
      ['depreciation', '年折旧'],
      ['capex', '初始CAPEX'],
      ['annual_credit_purchases', '年赊购额'],
      ['receivable_days', '应收天数'],
      ['inventory_days', '库存天数'],
      ['payable_days', '应付天数'],
    ];
    const table = document.createElement('table');
    table.className = 'decision-input-table finance-input-table';
    table.innerHTML = '<thead><tr><th>输入</th><th>数值</th><th>自动单位</th><th>依据</th><th>数据日期</th><th>原始来源</th><th>来源组ID</th><th>已核对</th><th>冲突</th></tr></thead>';
    const tbody = document.createElement('tbody');
    for (const [key, title] of definitions) {
      const tr = document.createElement('tr');
      const value = input(key + '_value', 'number');
      const basis = basisSelect(key + '_basis');
      const date = input(key + '_date', 'date');
      const source = input(key + '_source');
      source.placeholder = '年报/报价/访谈/假设说明';
      const origin = input(key + '_origin');
      origin.placeholder = '同一原始来源填同ID';
      const verified = input(key + '_verified', 'checkbox');
      const conflict = input(key + '_conflict', 'checkbox');
      const unit = document.createElement('span');
      unit.dataset.financeUnit = key;
      for (const node of [title, value, unit, basis, date, source, origin, verified, conflict]) {
        const td = document.createElement('td');
        typeof node === 'string' ? td.append(document.createTextNode(node)) : td.append(node);
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    const units = () => {
      const q = quantityUnit.value.trim() || '数量单位';
      const mapping = {
        sales: q,
        capacity: q,
        price: `元/${q}`,
        variable_cost: `元/${q}`,
        fixed_cash_cost: '元/年',
        depreciation: '元/年',
        capex: '元',
        annual_credit_purchases: '元/年',
        receivable_days: '天',
        inventory_days: '天',
        payable_days: '天',
      };
      for (const [key, unit] of Object.entries(mapping)) table.querySelector(`[data-finance-unit="${key}"]`).textContent = unit;
      return mapping;
    };
    quantityUnit.addEventListener('input', units);
    units();

    const calculate = document.createElement('button');
    calculate.textContent = '程序计算财务底座';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary-action';
    save.textContent = '保存测算到报告';
    save.disabled = true;
    const actions = document.createElement('div');
    actions.className = 'industry-actions';
    actions.append(calculate, save);
    const output = document.createElement('div');
    output.className = 'decision-calculation-result';
    output.setAttribute('aria-live', 'polite');
    form.append(common, table, actions);
    panel.append(summary, form, output);
    workspace.append(panel);

    let last = null;
    let lastProject = null;
    let savedRecordId = '';
    registerCalculatorReset(form, output, save, () => { last = null; lastProject = null; savedRecordId = ''; });
    form.addEventListener('input', () => {
      last = null;
      save.disabled = true;
      output.textContent = '输入已变化，请重新计算。';
    });
    form.onsubmit = async event => {
      event.preventDefault();
      calculate.disabled = true;
      output.textContent = '正在执行确定性公式…';
      try {
        const unitMap = units();
        const facts = {};
        for (const [key] of definitions) {
          facts[key] = {
            value: valueOrNull(form.elements.namedItem(key + '_value')),
            unit: unitMap[key],
            scope: scope.value.trim(),
            date: form.elements.namedItem(key + '_date').value || null,
            source: form.elements.namedItem(key + '_source').value.trim(),
            origin_id: form.elements.namedItem(key + '_origin').value.trim(),
            basis: form.elements.namedItem(key + '_basis').value,
            verified: form.elements.namedItem(key + '_verified').checked,
            conflict: form.elements.namedItem(key + '_conflict').checked,
          };
        }
        lastProject = ctx.getProjectId();
        last = await ctx.api('/api/industry/decision/finance/calculate', {
          method: 'POST',
          body: JSON.stringify({
            scope: scope.value.trim(),
            year: Number(year.value),
            quantity_unit: quantityUnit.value.trim(),
            facts,
          }),
        });
        output.replaceChildren();
        resultLine(output, '状态：' + last.status, 'decision-result-status');
        if (last.gaps.length) resultLine(output, '缺失输入：' + last.gaps.join('、'));
        if (last.pending.length) resultLine(output, '待核对/冲突输入：' + last.pending.join('、'));
        if (Object.keys(last.results).length) {
          const r = last.results;
          resultLine(output, `收入：${number(r.revenue)} 元；营业利润：${number(r.operating_profit)} 元`);
          resultLine(output, `产能利用率：${number(r.utilization_pct)}%；盈亏平衡利用率：${r.breakeven_utilization_pct === null ? '不可计算' : number(r.breakeven_utilization_pct) + '%'}`);
          resultLine(output, `现金转换周期：${number(r.ccc_days)} 天；净营运资金：${number(r.net_working_capital)} 元`);
          resultLine(output, `初始资金下限：${number(r.initial_funding_floor)} 元（不含现金安全垫等未纳入项）`);
        }
        for (const text of last.limitations) resultLine(output, '边界：' + text);
        save.disabled = false;
      } catch (error) {
        last = null;
        save.disabled = true;
        output.textContent = '测算失败：' + error.message;
      } finally {
        calculate.disabled = false;
      }
    };
    save.onclick = async () => {
      if (!last) return;
      save.disabled = true;
      let persisted = false;
      try {
        const saved = await saveResult('finance', `${last.inputs.scope} ${last.inputs.year}年 财务测算`,
          last, lastProject, '', savedRecordId);
        savedRecordId = saved.record.id;
        persisted = true;
        resultLine(output, `已保存到「${saved.projectTitle}」；重新生成报告时写入第8章。`, 'decision-save-ok');
        if (saved.warning) resultLine(output, saved.warning, 'decision-save-warning');
      } catch (error) {
        resultLine(output, '保存失败：' + error.message);
      } finally {
        if (!persisted) save.disabled = false;
      }
    };
  }

  function cityCalculator() {
    const panel = document.createElement('details');
    panel.className = 'decision-calculator';
    const summary = document.createElement('summary');
    summary.textContent = '城市级工厂选址评分（Min-Max 加权）';
    const note = document.createElement('p');
    note.textContent = '示例权重只用于搭建结构。未由企业确认权重，或任一城市数据未核对时，只输出情景排名，不形成推荐城市。';
    const form = document.createElement('form');
    const common = document.createElement('div');
    common.className = 'decision-calculator-common';
    const scope = input('city_scope');
    scope.required = true;
    scope.placeholder = '产品 × 客户 × 年份 × 服务半径';
    const cityA = input('city_a');
    cityA.required = true;
    cityA.placeholder = '候选城市A，如苏州';
    const cityB = input('city_b');
    cityB.required = true;
    cityB.placeholder = '候选城市B，如东莞';
    const rationale = input('weight_rationale');
    rationale.placeholder = '权重版本、决策组或战略依据';
    const evaluationDate = input('city_evaluation_date', 'date');
    evaluationDate.required = true;
    evaluationDate.value = new Date().toISOString().slice(0, 10);
    const weightsConfirmed = input('weights_confirmed', 'checkbox');
    common.append(field('统一选址口径', scope), field('候选城市A', cityA),
      field('候选城市B', cityB), field('评估日期', evaluationDate), field('权重依据', rationale),
      field('企业已确认本组权重', weightsConfirmed));

    const definitions = [
      ['customer_density', '目标客户密度', 20, 'higher_better', '家/百平方公里'],
      ['paper_cost', '原纸到厂成本', 15, 'lower_better', '元/吨'],
      ['delivery_distance', '核心客户平均物流距离', 15, 'lower_better', '公里'],
      ['factory_cost', '厂房年成本', 10, 'lower_better', '元/平方米/年'],
      ['energy_cost', '综合能源成本', 10, 'lower_better', '元/标准产量'],
      ['labor_cost', '生产人员综合成本', 10, 'lower_better', '元/人/年'],
      ['environment_cost', '环保合规年成本', 8, 'lower_better', '元/年'],
      ['ecosystem_score', '产业配套成熟度评分', 7, 'higher_better', '分'],
      ['receivable_days', '目标客户账期', 5, 'lower_better', '天'],
    ];
    const table = document.createElement('table');
    table.className = 'decision-input-table city-input-table';
    table.innerHTML = '<thead><tr><th>指标</th><th>权重%</th><th>方向</th><th>单位</th><th data-city-a>城市A逐值资料</th><th data-city-b>城市B逐值资料</th></tr></thead>';
    const tbody = document.createElement('tbody');
    for (const [key, title, weightDefault, directionDefault, unitDefault] of definitions) {
      const tr = document.createElement('tr');
      const weight = input(key + '_weight', 'number');
      weight.value = String(weightDefault);
      weight.max = '100';
      const direction = document.createElement('select');
      direction.name = key + '_direction';
      direction.innerHTML = '<option value="higher_better">越高越好</option><option value="lower_better">越低越好</option>';
      direction.value = directionDefault;
      const unit = input(key + '_unit');
      unit.value = unitDefault;
      const cityFactFields = suffix => {
        const box = document.createElement('div');
        box.className = 'city-fact-inputs';
        const value = input(key + '_' + suffix, 'number');
        const basis = basisSelect(key + '_' + suffix + '_basis');
        const date = input(key + '_' + suffix + '_date', 'date');
        const source = input(key + '_' + suffix + '_source');
        source.placeholder = '来源/报价/访谈';
        const origin = input(key + '_' + suffix + '_origin');
        origin.placeholder = '原始来源组ID';
        const verified = input(key + '_' + suffix + '_verified', 'checkbox');
        const conflict = input(key + '_' + suffix + '_conflict', 'checkbox');
        box.append(field('数值', value), field('依据', basis), field('日期', date),
          field('原始来源', source), field('来源组ID', origin),
          field('已核对', verified), field('存在冲突', conflict));
        return box;
      };
      const cityAFields = cityFactFields('a');
      const cityBFields = cityFactFields('b');
      for (const node of [title, weight, direction, unit, cityAFields, cityBFields]) {
        const td = document.createElement('td');
        typeof node === 'string' ? td.append(document.createTextNode(node)) : td.append(node);
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    const updateCityHeaders = () => {
      table.querySelector('[data-city-a]').textContent = cityA.value.trim() || '城市A';
      table.querySelector('[data-city-b]').textContent = cityB.value.trim() || '城市B';
    };
    cityA.addEventListener('input', updateCityHeaders);
    cityB.addEventListener('input', updateCityHeaders);

    const calculate = document.createElement('button');
    calculate.textContent = '程序计算选址评分';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary-action';
    save.textContent = '保存评分到报告';
    save.disabled = true;
    const actions = document.createElement('div');
    actions.className = 'industry-actions';
    actions.append(calculate, save);
    const output = document.createElement('div');
    output.className = 'decision-calculation-result';
    output.setAttribute('aria-live', 'polite');
    form.append(common, table, actions);
    panel.append(summary, note, form, output);
    workspace.append(panel);

    let last = null;
    let lastProject = null;
    let savedRecordId = '';
    registerCalculatorReset(form, output, save, () => { last = null; lastProject = null; savedRecordId = ''; });
    form.addEventListener('input', () => {
      last = null;
      save.disabled = true;
      output.textContent = '输入已变化，请重新计算。';
    });
    form.onsubmit = async event => {
      event.preventDefault();
      calculate.disabled = true;
      output.textContent = '正在执行标准化与加权计算…';
      try {
        const cities = [cityA.value.trim(), cityB.value.trim()];
        if (!cities[0] || !cities[1] || cities[0] === cities[1]) throw Error('请填写两个不同的候选城市。');
        const indicators = definitions.map(([key, title]) => {
          const unit = form.elements.namedItem(key + '_unit').value.trim();
          const cityFact = suffix => ({
            value: valueOrNull(form.elements.namedItem(key + '_' + suffix)),
            unit,
            date: form.elements.namedItem(key + '_' + suffix + '_date').value || evaluationDate.value || null,
            source: form.elements.namedItem(key + '_' + suffix + '_source').value.trim(),
            origin_id: form.elements.namedItem(key + '_' + suffix + '_origin').value.trim(),
            basis: form.elements.namedItem(key + '_' + suffix + '_basis').value,
            verified: form.elements.namedItem(key + '_' + suffix + '_verified').checked,
            conflict: form.elements.namedItem(key + '_' + suffix + '_conflict').checked,
            scope: scope.value.trim(),
          });
          return {
            name: title,
            weight: valueOrNull(form.elements.namedItem(key + '_weight')),
            direction: form.elements.namedItem(key + '_direction').value,
            unit,
            values: {
              [cities[0]]: cityFact('a'),
              [cities[1]]: cityFact('b'),
            },
          };
        });
        lastProject = ctx.getProjectId();
        last = await ctx.api('/api/industry/decision/city/calculate', {
          method: 'POST',
          body: JSON.stringify({
            scope: scope.value.trim(),
            cities,
            indicators,
            weights_confirmed: weightsConfirmed.checked,
            weight_rationale: rationale.value.trim(),
          }),
        });
        output.replaceChildren();
        resultLine(output, '状态：' + last.status, 'decision-result-status');
        if (last.gaps.length) resultLine(output, '缺失输入：' + last.gaps.join('、'));
        if (last.pending.length) resultLine(output, '待核对：' + last.pending.join('、'));
        for (const row of last.results?.ranking || []) {
          resultLine(output, `第${row.rank}名：${row.city}，加权得分 ${number(row.weighted_score)}`);
        }
        if (last.recommendation) resultLine(output, `程序评分领先：${last.recommendation.city}；仍需人工决策。`);
        for (const text of last.limitations) resultLine(output, '边界：' + text);
        save.disabled = false;
      } catch (error) {
        last = null;
        save.disabled = true;
        output.textContent = '测算失败：' + error.message;
      } finally {
        calculate.disabled = false;
      }
    };
    save.onclick = async () => {
      if (!last) return;
      save.disabled = true;
      let persisted = false;
      try {
        const saved = await saveResult('city', `${last.inputs.cities.join(' VS ')} 工厂选址评分`, last,
          lastProject, evaluationDate.value, savedRecordId);
        savedRecordId = saved.record.id;
        persisted = true;
        resultLine(output, `已保存到「${saved.projectTitle}」；重新生成报告时写入第7章。`, 'decision-save-ok');
        if (saved.warning) resultLine(output, saved.warning, 'decision-save-warning');
      } catch (error) {
        resultLine(output, '保存失败：' + error.message);
      } finally {
        if (!persisted) save.disabled = false;
      }
    };
  }

  function gateCalculator() {
    const panel = document.createElement('details');
    panel.className = 'decision-calculator';
    const summary = document.createElement('summary');
    summary.textContent = '阶段式 GO / HOLD / NO-GO 数字门槛';
    const note = document.createElement('p');
    note.textContent = '系统不内置行业阈值。必须填写并确认当前值、GO阈值、NO-GO阈值及其依据；任一项待验证时，整体不输出确定性决策。';
    const form = document.createElement('form');
    const common = document.createElement('div');
    common.className = 'decision-calculator-common';
    const evaluationDate = input('gate_evaluation_date', 'date');
    evaluationDate.required = true;
    evaluationDate.value = new Date().toISOString().slice(0, 10);
    common.append(field('决策评估日期', evaluationDate));
    const definitions = [
      ['yield', '试制', '良率', '%', 'higher_better'],
      ['test_pass', '试制', '客户测试通过率', '%', 'higher_better'],
      ['valid_customers', '客户验证', '有效意向客户数', '家', 'higher_better'],
      ['framework_orders', '客户验证', '年框订单金额', '万元', 'higher_better'],
      ['utilization', '量产', '产能利用率', '%', 'higher_better'],
      ['gross_margin', '财务', '毛利率', '%', 'higher_better'],
      ['receivable_days', '财务', '应收账款天数', '天', 'lower_better'],
      ['irr', '投资', 'IRR', '%', 'higher_better'],
      ['payback', '投资', '投资回收期', '年', 'lower_better'],
    ];
    const table = document.createElement('table');
    table.className = 'decision-input-table gate-input-table';
    table.innerHTML = '<thead><tr><th>阶段</th><th>指标</th><th>当前值</th><th>单位</th><th>方向</th><th>GO阈值</th><th>NO-GO阈值</th><th>当前值依据</th><th>数据日期</th><th>当前值来源</th><th>来源组ID</th><th>已核对</th><th>冲突</th><th>阈值依据</th><th>门槛已确认</th></tr></thead>';
    const tbody = document.createElement('tbody');
    for (const [key, stage, title, unit, direction] of definitions) {
      const tr = document.createElement('tr');
      const current = input(key + '_current', 'number');
      current.removeAttribute('min');
      const go = input(key + '_go', 'number');
      go.removeAttribute('min');
      const noGo = input(key + '_no_go', 'number');
      noGo.removeAttribute('min');
      const basis = gateBasisSelect(key + '_basis');
      const date = input(key + '_date', 'date');
      const source = input(key + '_source');
      source.placeholder = '台账/报价/验证记录';
      const origin = input(key + '_origin');
      origin.placeholder = '原始来源组ID';
      const verified = input(key + '_verified', 'checkbox');
      const conflict = input(key + '_conflict', 'checkbox');
      const thresholdSource = input(key + '_threshold_source');
      thresholdSource.placeholder = '董事会/预算/可比项目依据';
      const thresholdConfirmed = input(key + '_threshold_confirmed', 'checkbox');
      const directionText = direction === 'higher_better' ? '越高越好' : '越低越好';
      for (const node of [stage, title, current, unit, directionText, go, noGo, basis, date,
        source, origin, verified, conflict, thresholdSource, thresholdConfirmed]) {
        const td = document.createElement('td');
        typeof node === 'string' ? td.append(document.createTextNode(node)) : td.append(node);
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    const calculate = document.createElement('button');
    calculate.textContent = '程序判定决策门槛';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary-action';
    save.textContent = '保存门槛到报告';
    save.disabled = true;
    const actions = document.createElement('div');
    actions.className = 'industry-actions';
    actions.append(calculate, save);
    const output = document.createElement('div');
    output.className = 'decision-calculation-result';
    output.setAttribute('aria-live', 'polite');
    form.append(common, table, actions);
    panel.append(summary, note, form, output);
    workspace.append(panel);

    let last = null;
    let lastProject = null;
    let savedRecordId = '';
    registerCalculatorReset(form, output, save, () => { last = null; lastProject = null; savedRecordId = ''; });
    form.addEventListener('input', () => {
      last = null;
      save.disabled = true;
      output.textContent = '输入已变化，请重新计算。';
    });
    form.onsubmit = async event => {
      event.preventDefault();
      calculate.disabled = true;
      output.textContent = '正在按已确认门槛逐项判定…';
      try {
        const metrics = definitions.map(([key, stage, name, unit, direction]) => ({
          stage,
          name,
          current: {
            value: valueOrNull(form.elements.namedItem(key + '_current')),
            unit,
            date: form.elements.namedItem(key + '_date').value || evaluationDate.value || null,
            source: form.elements.namedItem(key + '_source').value.trim(),
            origin_id: form.elements.namedItem(key + '_origin').value.trim(),
            basis: form.elements.namedItem(key + '_basis').value,
            verified: form.elements.namedItem(key + '_verified').checked,
            conflict: form.elements.namedItem(key + '_conflict').checked,
          },
          direction,
          go_threshold: valueOrNull(form.elements.namedItem(key + '_go')),
          no_go_threshold: valueOrNull(form.elements.namedItem(key + '_no_go')),
          threshold_source: form.elements.namedItem(key + '_threshold_source').value.trim(),
          threshold_confirmed: form.elements.namedItem(key + '_threshold_confirmed').checked,
        }));
        lastProject = ctx.getProjectId();
        last = await ctx.api('/api/industry/decision/gate/calculate', {
          method: 'POST',
          body: JSON.stringify({metrics}),
        });
        output.replaceChildren();
        resultLine(output, `整体状态：${last.scenario_state}${last.decision ? '（程序门槛判定）' : '（尚不形成确定性决策）'}`, 'decision-result-status');
        if (last.gaps.length) resultLine(output, '缺失输入：' + last.gaps.join('、'));
        if (last.pending.length) resultLine(output, '待核对：' + last.pending.join('、'));
        for (const row of last.metrics) {
          resultLine(output, `${row.stage}｜${row.name}：${row.state}`);
        }
        for (const text of last.limitations) resultLine(output, '边界：' + text);
        save.disabled = false;
      } catch (error) {
        last = null;
        save.disabled = true;
        output.textContent = '判定失败：' + error.message;
      } finally {
        calculate.disabled = false;
      }
    };
    save.onclick = async () => {
      if (!last) return;
      save.disabled = true;
      let persisted = false;
      try {
        const saved = await saveResult('threshold', `制造业进入决策门槛（${last.scenario_state}）`, last,
          lastProject, evaluationDate.value, savedRecordId);
        savedRecordId = saved.record.id;
        persisted = true;
        resultLine(output, `已保存到「${saved.projectTitle}」；重新生成报告时写入第10章和摘要。`, 'decision-save-ok');
        if (saved.warning) resultLine(output, saved.warning, 'decision-save-warning');
      } catch (error) {
        resultLine(output, '保存失败：' + error.message);
      } finally {
        if (!persisted) save.disabled = false;
      }
    };
  }

  marketCalculator();
  financeCalculator();
  cityCalculator();
  gateCalculator();
})();
