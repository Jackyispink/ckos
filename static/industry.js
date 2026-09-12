if(location.pathname==='/industry'){
const $=id=>document.getElementById(id);let active=null,timer=null,creating=false,loadVersion=0,currentProject=null,decisionUiProject=null;
const chartSessions=new Map();
// Explicit inputs only: this calculator never derives assumptions from model text.
const calcPanel=document.createElement('details');calcPanel.className='manufacturing-calculator advanced-tool-section';
calcPanel.hidden=true;
const calcSummary=document.createElement('summary');calcSummary.textContent='辅助试算：产能利用率与价格情景';calcPanel.append(calcSummary);
const calcIntro=document.createElement('p');calcIntro.textContent='独立试算，不调用模型、不自动保存到报告。请填写同一产品、同一期间、同一单位的数据；金额字段均使用下方填写的币种单位（不要混用元与万元）。';calcPanel.append(calcIntro);
const calcForm=document.createElement('form'),calcGrid=document.createElement('div');calcGrid.className='industry-grid';
const calcFields=[['product','产品范围'],['period','统计期间'],['quantity_unit','数量单位（如台、吨）'],['currency','金额单位（如元、万元）'],['source','数据来源／假设说明'],['effective_capacity','当期有效产能',0],['output','当期产量',0],['sales','当期销量',0],['unit_price','单位售价（金额单位／数量单位）',0],['unit_variable_cost','单位变动制造成本（金额单位／数量单位）',0],['fixed_cost','当期固定制造成本（金额单位）',0],['price_change_pct','售价变化（%，例如降价10%填-10）',-100]];
for(const [name,title,min] of calcFields){const label=document.createElement('label'),input=document.createElement('input');label.textContent=title;input.name=name;input.required=true;input.type=min===undefined?'text':'number';if(min!==undefined){input.min=String(min);input.step='any';}label.append(input);calcGrid.append(label);}
const calcButton=document.createElement('button');calcButton.type='submit';calcButton.textContent='计算情景';
const calcResult=document.createElement('div');calcResult.setAttribute('aria-live','polite');
const calcActions=document.createElement('div');calcActions.className='industry-actions';calcActions.append(calcButton);
calcForm.append(calcGrid,calcActions);calcPanel.append(calcForm,calcResult);$('project-panel').after(calcPanel);
calcForm.onsubmit=async event=>{event.preventDefault();calcButton.disabled=true;calcResult.textContent='正在计算…';try{
 const response=await fetch('/api/industry/manufacturing/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(calcForm)))});
 const data=await response.json();if(!response.ok)throw Error(Array.isArray(data.detail)?data.detail.map(e=>`${e.loc.at(-1)}：${e.msg}`).join('；'):data.detail||'测算失败');
 calcResult.replaceChildren();const line=text=>{const p=document.createElement('p');p.textContent=text;calcResult.append(p);};
 const num=value=>value===null?'不适用（收入为0）':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});
 line(`产能利用率：${num(data.utilization_pct)}%`);
 for(const [key,title] of [['baseline','基准'],['scenario','价格变化后']]){const r=data[key];line(`${title}：收入 ${num(r.revenue)} ${data.inputs.currency}；测算毛利 ${num(r.modeled_gross_profit)} ${data.inputs.currency}；测算毛利率 ${num(r.modeled_gross_margin_pct)}${r.modeled_gross_margin_pct===null?'':'%'}`);}
 for(const formula of data.formulas)line(formula);for(const warning of data.warnings)line('说明：'+warning);
}catch(error){calcResult.textContent=error.message;}finally{calcButton.disabled=false;}};
calcForm.addEventListener('input',()=>{calcResult.textContent='输入已变更，请重新计算。';});
const decisionPanel=document.createElement('details');decisionPanel.className='decision-data-panel advanced-tool-section';
decisionPanel.hidden=true;
const decisionSummary=document.createElement('summary');decisionSummary.textContent='查看自动整理与计算结果';
const decisionIntro=document.createElement('p');decisionIntro.textContent='生成行业研究报告时，系统会自动读取 AKShare 与网页资料、整理结构化研究数据，并用口径完整的数据执行可复核计算，无需用户填表或手工计算。无法确认的内容会保留为待验证缺口，不会模拟真实数据。';
const decisionForm=document.createElement('form');decisionForm.className='decision-data-form';
decisionForm.innerHTML='<input type="hidden" name="record_id"><div class="industry-grid"><label>数据类型<select name="record_type"><option value="market">市场</option><option value="customer">客户</option><option value="supplier">供应商</option><option value="equipment">设备</option><option value="city">城市</option><option value="finance">财务</option><option value="threshold">决策门槛</option></select></label><label>记录名称<input name="name" required maxlength="200" placeholder="例如：苏州目标客户A"></label><label>状态<select name="basis"><option value="unverified">待验证</option><option value="actual">实际数据</option><option value="quote">真实报价</option><option value="assumption">用户假设</option><option value="calculated">程序计算</option></select></label><label>数据日期<input name="as_of_date" placeholder="YYYY-MM-DD或统计期间"></label><label class="wide">来源<input name="source" maxlength="1000" placeholder="公开来源、报价单编号或访谈记录"></label><label class="wide">字段（JSON对象）<textarea name="fields" required placeholder=\'{"城市":"苏州","年采购量":{"value":null,"unit":"万㎡","status":"待验证"}}\'></textarea></label><label><input name="verified" type="checkbox"> 已人工核对来源与口径</label></div><div class="industry-actions"><button type="submit">保存结构化数据</button><button type="button" class="secondary-action" data-cancel-edit>取消编辑</button><span data-status role="status"></span></div>';
const decisionTypeSelect=decisionForm.elements.namedItem('record_type');
for(const [value,title] of Object.entries({competitor:'直接竞争者',product:'产品定位',certification:'认证准入',risk:'进入风险',swot:'SWOT事实',interview:'一手访谈'})){const option=document.createElement('option');option.value=value;option.textContent=title;decisionTypeSelect.append(option);}
const decisionTemplates={
  market:{metric:'食品饮料瓦楞箱市场规模',value:null,unit:'亿元',year:null,region:'全国/长三角/珠三角',scope:'产品×客户×统计口径',calculation_role:'TAM/SAM/SOM',status:'待验证'},
  customer:{customer_name:'',factory_location:'',segment:'饮料/乳制品/休闲食品等',estimated_annual_demand:{value:null,unit:'万㎡',status:'待验证'},current_suppliers:[],procurement_mode:'',certification_cycle_days:null,payment_terms_days:null,entry_difficulty:'待验证'},
  supplier:{supplier_name:'',base_location:'',material_or_service:'原纸/油墨/设备等',distance_km:null,moq:null,payment_terms_days:null,pricing_mechanism:'',lead_time_days:null,status:'待验证'},
  equipment:{scheme:'轻资产加工/纸板纸箱一体化/高端食品饮料包装',equipment_name:'',quantity:null,speed_or_capacity:'',domestic_or_imported:'',quoted_price:{value:null,unit:'万元',status:'待报价'},annual_capacity:'',energy_requirement:'',status:'待验证'},
  city:{city:'',target_customer_density:null,paper_delivered_cost:null,average_delivery_distance_km:null,factory_cost:null,energy_cost:null,labor_cost:null,environmental_compliance_cost:null,ecosystem_score:null,receivable_days:null,scope:'统一产品与服务半径'},
  finance:{product:'',period:'',annual_sales_volume:null,unit_price:null,material_cost_per_unit:null,other_variable_cost_per_unit:null,annual_fixed_cost:null,effective_capacity:null,yield_rate_pct:null,receivable_days:null,inventory_days:null,payable_days:null,capex:null,unit:'请逐字段注明单位',status:'待验证'},
  threshold:{stage:'试制/客户验证/量产/财务/投资',metric:'',current_value:null,unit:'',direction:'higher_better/lower_better',go_threshold:null,no_go_threshold:null,threshold_basis:'',confirmed:false},
  competitor:{company:'',factory_locations:[],competing_product:'',target_customers:[],service_radius_km:null,estimated_capacity:null,price_positioning:'',competitive_basis:'技术/成本/交付/客户认证',same_market_scope:false,status:'待验证'},
  product:{product_name:'',target_segment:'',structure_or_specification:'',customer_value:'',average_price:null,unit:'元/㎡或项目实际单位',gross_margin:null,certification_requirement:'',recommendation:'不建议/建议/重点验证',status:'待验证'},
  certification:{standard_or_certification:'',mandatory:false,customer_segment:'',cycle_days:null,cost:null,unit:'万元',equipment_or_process_impact:'',evidence_type:'法规/客户要求/加分项',status:'待验证'},
  risk:{risk_event:'',entry_stage:'市场/客户/建设/量产/现金流',impact_path:'事件→经营影响→财务结果',affected_object:'',trigger_indicator:'',trigger_threshold:null,response_action:'',exit_condition:'',status:'待验证'},
  swot:{target_company:'',dimension:'S/W/O/T',fact:'',decision_implication:'',source_scope:'企业内部/行业外部',status:'待验证'},
  interview:{interviewee_role:'采购/纸箱厂/设备商/原纸商/专家',organization:'',interview_date:'',question:'',verbatim_or_summary:'',metric_value:null,unit:'',permission_scope:'仅内部/可引用',follow_up:'',status:'待验证'},
};
const decisionTemplateBar=document.createElement('div');decisionTemplateBar.className='decision-template-bar';
const decisionTemplateSelect=document.createElement('select');
for(const [value,title] of Object.entries({market:'市场空间模板',customer:'目标客户模板',supplier:'供应商模板',competitor:'直接竞争者模板',product:'产品定位模板',certification:'认证准入模板',equipment:'设备方案模板',city:'城市资料模板',finance:'财务输入模板',risk:'进入风险模板',swot:'SWOT事实模板',interview:'一手访谈模板',threshold:'决策门槛模板'})){const option=document.createElement('option');option.value=value;option.textContent=title;decisionTemplateSelect.append(option);}
const decisionTemplateButton=document.createElement('button');decisionTemplateButton.type='button';decisionTemplateButton.className='secondary-action';decisionTemplateButton.textContent='载入字段模板';
const decisionTemplateHelp=document.createElement('small');decisionTemplateHelp.textContent='模板中的 null 表示资料缺口；请补充真实数据或保留待验证，系统不会自动编造。';
decisionTemplateBar.append(decisionTemplateSelect,decisionTemplateButton,decisionTemplateHelp);
decisionForm.querySelector('.industry-actions').before(decisionTemplateBar);
decisionTemplateButton.onclick=()=>{const type=decisionTemplateSelect.value;decisionForm.elements.namedItem('record_type').value=type;decisionForm.elements.namedItem('basis').value='unverified';decisionForm.elements.namedItem('verified').checked=false;decisionForm.elements.namedItem('fields').value=JSON.stringify(decisionTemplates[type],null,2);decisionForm.querySelector('[data-status]').textContent='已载入模板，请补充数据、来源和日期后保存。';};
const decisionList=document.createElement('div');decisionList.className='decision-record-list';
const decisionAutoPanel=document.createElement('section');decisionAutoPanel.className='decision-auto-extract';
const decisionAutoHeading=document.createElement('h3');decisionAutoHeading.textContent='随报告生成自动整理与计算';
const decisionAutoIntro=document.createElement('p');decisionAutoIntro.textContent='系统从已采集资料中提取市场、客户、竞争、供应链、设备、城市、财务与风险等候选数据，保留原文和来源并自动去重；口径完整时继续自动计算，缺少或冲突的输入会列入测算缺口。下方按钮只在资料更新后需要立即重整时使用。';
const decisionAutoButton=document.createElement('button');decisionAutoButton.type='button';decisionAutoButton.className='decision-auto-button';decisionAutoButton.textContent='重新整理已采集资料';
const decisionAutoStatus=document.createElement('p');decisionAutoStatus.className='decision-auto-status';decisionAutoStatus.dataset.state='idle';decisionAutoStatus.setAttribute('role','status');decisionAutoStatus.setAttribute('aria-live','polite');decisionAutoStatus.textContent='正常生成报告时会自动执行，无需点击，也无需填写人工表单。';
const decisionAutoActions=document.createElement('div');decisionAutoActions.className='decision-auto-actions';decisionAutoActions.append(decisionAutoButton,decisionAutoStatus);
decisionAutoPanel.append(decisionAutoHeading,decisionAutoIntro,decisionAutoActions);
const decisionManualTools=document.createElement('details');decisionManualTools.className='decision-manual-tools';
const decisionManualSummary=document.createElement('summary');decisionManualSummary.textContent='人工校正与企业内部数据（通常无需使用）';
const decisionManualIntro=document.createElement('p');decisionManualIntro.textContent='只有要加入公开资料中不存在的企业内部数据、报价，或修正自动识别结果时才展开；留空不影响十章研报、Word 或 PPT 生成。';
decisionManualTools.append(decisionManualSummary,decisionManualIntro,decisionForm);
decisionPanel.append(decisionSummary,decisionIntro,decisionAutoPanel,decisionList,decisionManualTools);calcPanel.after(decisionPanel);
const advancedToolsPanel=document.createElement('details');advancedToolsPanel.className='industry-card industry-advanced-tools';advancedToolsPanel.hidden=true;
const advancedToolsSummary=document.createElement('summary');advancedToolsSummary.textContent='研报自动整理与计算（无需填写）';
const advancedToolsIntro=document.createElement('p');advancedToolsIntro.textContent='正常点击“生成十章与摘要”即可：系统会自动搜索资料、整理结构化数据、计算可用指标并完成研报。这里仅用于查看整理与计算结果，或在少数情况下补充企业内部资料。';
calcPanel.before(advancedToolsPanel);advancedToolsPanel.append(advancedToolsSummary,advancedToolsIntro,decisionPanel);decisionManualTools.append(calcPanel);calcPanel.hidden=false;decisionPanel.hidden=false;
advancedToolsPanel.addEventListener('toggle',()=>{if(!advancedToolsPanel.open){calcPanel.open=false;decisionManualTools.open=false;decisionPanel.open=false;}});
async function refreshDecisionRecords(){
  decisionList.replaceChildren();
  if(!active){decisionList.textContent='请先选择研究项目。';return;}
  const projectId=active;
  const rows=await api(`/api/industry/projects/${projectId}/decision-records`);
  if(projectId!==active)return;
  if(!rows.length){decisionList.textContent='尚无自动整理结果。生成正文后系统会自动整理；仅在刚补充了新资料时，才需要点击上方“重新整理”。';return;}
  for(const row of rows){
    const card=document.createElement('article'),heading=document.createElement('strong'),meta=document.createElement('small'),source=document.createElement('small'),pre=document.createElement('pre'),edit=document.createElement('button'),remove=document.createElement('button');
    card.className='decision-record';heading.textContent=row.name;meta.textContent=`${row.record_type} · ${row.basis} · ${row.verified?'已核对':'待验证'} · ${row.as_of_date||'日期待补'}`;source.textContent='来源：'+(row.source||'待补');pre.textContent=JSON.stringify(row.fields,null,2);
    edit.type=remove.type='button';edit.textContent='编辑';remove.textContent='删除';remove.className='danger-action';
    edit.onclick=()=>{if(projectId!==active)return;decisionForm.elements.namedItem('record_id').value=row.id;for(const key of ['record_type','name','basis','source','as_of_date'])decisionForm.elements.namedItem(key).value=row[key]||'';decisionForm.elements.namedItem('fields').value=JSON.stringify(row.fields,null,2);decisionForm.elements.namedItem('verified').checked=!!row.verified;decisionPanel.open=true;decisionManualTools.open=true;decisionForm.scrollIntoView({behavior:'smooth',block:'center'});};
    remove.onclick=async()=>{if(projectId!==active||!confirm(`删除“${row.name}”？`))return;remove.disabled=true;try{await api(`/api/industry/projects/${projectId}/decision-records/${row.id}`,{method:'DELETE'});if(projectId===active)await refreshDecisionRecords();}catch(error){alert('删除失败：'+error.message);}finally{remove.disabled=false;}};
    card.append(heading,meta,source,pre,edit,remove);decisionList.append(card);
  }
}
let decisionAutoRun=0;
const decisionResultCount=value=>{if(Array.isArray(value))return value.length;if(value&&typeof value==='object')return Object.keys(value).length;const count=Number(value);return Number.isFinite(count)&&count>=0?count:0;};
const decisionGapSummary=gaps=>{if(typeof gaps==='string')return gaps.trim()?`资料缺口：${gaps.trim()}`:'';const count=decisionResultCount(gaps);return count?`仍有 ${count} 项资料缺口待补`:'';};
const decisionCalculationGapCount=value=>{if(Array.isArray(value))return value.reduce((total,item)=>total+decisionCalculationGapCount(item),0);if(value&&typeof value==='object')return Object.values(value).reduce((total,item)=>total+decisionCalculationGapCount(item),0);if(typeof value==='string')return value.trim()?1:0;const count=Number(value);return Number.isFinite(count)&&count>0?count:0;};
function resetDecisionAutoState(){decisionAutoRun++;decisionAutoButton.disabled=false;decisionAutoButton.textContent='重新整理已采集资料';decisionAutoPanel.removeAttribute('aria-busy');delete decisionAutoStatus.dataset.reportGeneration;decisionAutoStatus.dataset.state='idle';decisionAutoStatus.textContent='正常生成报告时会自动执行，无需点击，也无需填写人工表单。';}
function syncDecisionAutoAvailability(project){
  if(decisionAutoPanel.hasAttribute('aria-busy'))return;
  const generating=!!project?.generation_active;
  decisionAutoButton.disabled=generating;
  decisionAutoButton.textContent=generating?'随报告自动整理中…':'重新整理已采集资料';
  if(generating){
    decisionAutoStatus.dataset.reportGeneration='true';
    decisionAutoStatus.dataset.state='running';
    decisionAutoStatus.textContent='报告正在生成，系统会同步整理资料并自动计算可用指标，无需重复操作。';
  }else if(decisionAutoStatus.dataset.reportGeneration==='true'){
    delete decisionAutoStatus.dataset.reportGeneration;
    decisionAutoStatus.dataset.state='idle';
    decisionAutoStatus.textContent='报告生成已结束。可展开查看整理与计算结果；资料和测算缺口会明确标出。';
  }
}
decisionAutoButton.onclick=async()=>{
  if(!active){decisionAutoStatus.dataset.state='error';decisionAutoStatus.textContent='请先选择研究项目。';return;}
  const projectId=active,runId=++decisionAutoRun;
  decisionAutoButton.disabled=true;decisionAutoButton.textContent='正在自动整理与计算…';decisionAutoPanel.setAttribute('aria-busy','true');decisionAutoStatus.dataset.state='running';decisionAutoStatus.textContent='正在读取已采集的章节资料，识别候选数据、去重并计算可用指标，请稍候…';
  try{
    const result=await api(`/api/industry/projects/${projectId}/decision-records/auto-extract`,{method:'POST'});
    if(projectId!==active||runId!==decisionAutoRun)return;
    let refreshWarning='';
    try{await refreshDecisionRecords();}catch(error){refreshWarning='决策记录列表刷新失败：'+error.message;}
    if(projectId!==active||runId!==decisionAutoRun)return;
    const created=decisionResultCount(result?.created),skipped=decisionResultCount(result?.skipped),candidates=decisionResultCount(result?.candidates);
    const summary=[`自动整理完成：新增 ${created} 条，跳过 ${skipped} 条，共识别 ${candidates} 条候选数据`];
    const gaps=decisionGapSummary(result?.gaps);if(gaps)summary.push(gaps);
    const calculation=result?.calculation;
    if(calculation?.error){summary.push(`自动计算未完成：${calculation.error}`);}
    else if(calculation){const computed=decisionResultCount(calculation.computed),reused=decisionResultCount(calculation.reused),blocked=decisionResultCount(calculation.blocked),calculationCount=decisionResultCount(calculation.calculations),reportedGapCount=Number(calculation.gap_count),gapCount=Number.isFinite(reportedGapCount)&&reportedGapCount>=0?reportedGapCount:decisionCalculationGapCount(calculation.gaps);summary.push(`自动计算：共 ${calculationCount} 项结果，新增 ${computed} 项，复用 ${reused} 项，${blocked} 组暂不可计算`);summary.push(`测算缺口：${gapCount} 项`);}
    if(typeof result?.method==='string'&&result.method.trim())summary.push(`整理方式：${result.method.trim()}`);
    if(refreshWarning)summary.push(refreshWarning);
    decisionAutoStatus.dataset.state=refreshWarning?'warning':'success';decisionAutoStatus.textContent=summary.join('；')+'。';
  }catch(error){if(projectId===active&&runId===decisionAutoRun){decisionAutoStatus.dataset.state='error';decisionAutoStatus.textContent='自动整理失败：'+error.message;}}
  finally{if(projectId===active&&runId===decisionAutoRun){decisionAutoButton.disabled=false;decisionAutoButton.textContent='重新整理已采集资料';decisionAutoPanel.removeAttribute('aria-busy');}}
};
decisionPanel.addEventListener('toggle',()=>{if(decisionPanel.open)refreshDecisionRecords().catch(e=>decisionList.textContent=e.message)});
decisionForm.querySelector('[data-cancel-edit]').onclick=()=>{decisionForm.reset();decisionForm.elements.namedItem('record_id').value='';};
document.addEventListener('ckos:industry-project-changed',()=>{resetDecisionAutoState();decisionManualTools.open=false;calcPanel.open=false;decisionForm.reset();decisionForm.elements.namedItem('record_id').value='';decisionForm.querySelector('[data-status]').textContent='';decisionList.replaceChildren();});
decisionForm.onsubmit=async event=>{
  event.preventDefault();if(!active){decisionForm.querySelector('[data-status]').textContent='请先选择研究项目。';return;}
  const projectId=active;
  const data=Object.fromEntries(new FormData(decisionForm)),id=data.record_id;delete data.record_id;data.verified=decisionForm.elements.namedItem('verified').checked;
  try{data.fields=JSON.parse(data.fields);if(!data.fields||Array.isArray(data.fields)||typeof data.fields!=='object')throw Error('字段必须是JSON对象');
    await api(`/api/industry/projects/${projectId}/decision-records${id?'/'+id:''}`,{method:id?'PATCH':'POST',body:JSON.stringify(data)});if(projectId!==active)return;decisionForm.reset();decisionForm.elements.namedItem('record_id').value='';decisionForm.querySelector('[data-status]').textContent='已保存；下次生成时写入对应章节。';await refreshDecisionRecords();
  }catch(error){decisionForm.querySelector('[data-status]').textContent='保存失败：'+error.message;}
};
const calcSave=document.createElement('button'),calcLoad=document.createElement('button'),calcStatus=document.createElement('p');
calcSave.type=calcLoad.type='button';calcSave.textContent='确认口径并保存到所选研究';calcLoad.textContent='读取所选研究的测算';calcStatus.setAttribute('aria-live','polite');
const calcStorageActions=document.createElement('div');calcStorageActions.className='calculator-storage-actions';calcStorageActions.append(calcLoad,calcSave);calcPanel.append(calcStorageActions,calcStatus);
calcSave.onclick=async()=>{
 if(!active){calcStatus.textContent='请先在左侧选择一个研究项目。';return;}
 if(!calcForm.reportValidity())return;
 const projectId=active,payload=Object.fromEntries(new FormData(calcForm));calcSave.disabled=true;
 try{const project=await api(`/api/industry/projects/${projectId}`);
  if(!confirm(`保存到「${project.title}」？\n请确认产品、期间、单位和数据来源一致。已有测算将被替换；结果只是简化情景，不是已核实的财报数据。`))return;
  await api(`/api/industry/projects/${projectId}/manufacturing-scenario`,{method:'PUT',body:JSON.stringify(payload)});
  calcStatus.textContent=`已保存到「${project.title}」。不会自动改写正文或插入下载报告。`;
 }catch(error){calcStatus.textContent=error.message;}finally{calcSave.disabled=false;}
};
calcLoad.onclick=async()=>{
 if(!active){calcStatus.textContent='请先在左侧选择一个研究项目。';return;}
 if(!confirm('读取已保存测算会替换当前表单的未保存输入，是否继续？'))return;
 const projectId=active;calcLoad.disabled=true;
 try{const result=await api(`/api/industry/projects/${projectId}/manufacturing-scenario`);
  if(projectId!==active){calcStatus.textContent='研究项目已切换，请重新读取。';return;}
  if(!result){calcStatus.textContent='此研究尚未保存测算。';return;}
  for(const [key,value] of Object.entries(result.inputs))if(calcForm.elements.namedItem(key))calcForm.elements.namedItem(key).value=value;
  calcResult.textContent='已读取保存的输入，请点击计算情景查看结果。';calcStatus.textContent='已读取所选研究的测算。';
 }catch(error){calcStatus.textContent=error.message;}finally{calcLoad.disabled=false;}
};
// New projects default to manufacturing; stored legacy briefs remain general.
const manufacturingFields=document.createElement('fieldset');
manufacturingFields.className='manufacturing-fields';
manufacturingFields.innerHTML='<legend>研究模板与制造业边界</legend><label>研究模板<select name="research_template"><option value="manufacturing">制造业研究</option><option value="general">通用行业研究</option></select></label><label>制造类型<select name="manufacturing_type"><option value="other">待确认／其他制造</option><option value="process">流程制造（材料、化工等）</option><option value="components">标准化零部件</option><option value="equipment">定制装备</option><option value="consumer">消费品制造</option></select></label><label>具体产品或产业链环节<input name="product_scope" maxlength="300" placeholder="例如：工业机器人减速器"></label><label>主要下游应用<input name="downstream_applications" maxlength="300" placeholder="例如：汽车、电子制造"></label><label>目标企业（选填，填写后启用有证据的SWOT）<input name="target_company" maxlength="200"></label><p>研究目的请填写市场进入、产品规划、扩产、供应链选择或投资研究。产能、良率、成本等缺失数据不会估造。</p>';
const manufacturingGrid=document.createElement('div');manufacturingGrid.className='industry-grid';
for(const field of manufacturingFields.querySelectorAll('label'))manufacturingGrid.append(field);
manufacturingFields.querySelector('legend').after(manufacturingGrid);
$('industry-form').prepend(manufacturingFields);
for(const [name,limit] of Object.entries({geography:500,purpose:1000,focus:6000,included_segments:3000,excluded_segments:3000,key_companies:2000,product_scope:2000,downstream_applications:2000,target_company:300})){
  $('industry-form').elements.namedItem(name)?.setAttribute('maxlength',String(limit));
}
const targetCompanyInput=$('industry-form').elements.namedItem('target_company');
if(targetCompanyInput){targetCompanyInput.closest('label').firstChild.nodeValue='研究主体／拟进入企业（选填）';targetCompanyInput.placeholder='填贵司或唯一评估对象；用于有证据的内部优势与劣势分析';}
const keyCompaniesInput=$('industry-form').elements.namedItem('key_companies');
if(keyCompaniesInput){keyCompaniesInput.closest('label').firstChild.nodeValue='对标与竞争企业';keyCompaniesInput.placeholder='填写同行、龙头或海外对标企业，多家公司用顿号分隔';}
const companyHelp=document.createElement('p');companyHelp.className='wide field-help';companyHelp.textContent='研究主体用于SWOT中的内部优势/劣势；对标与竞争企业用于竞争格局和横向比较。没有明确研究主体时可以留空。';manufacturingGrid.append(companyHelp);
manufacturingFields.querySelector('[name="research_template"]').onchange=e=>{for(const field of manufacturingFields.querySelectorAll('input,select'))if(field.name!=='research_template')field.disabled=e.target.value==='general'};
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Content-Type':'application/json'}});const data=await r.json().catch(()=>({}));if(!r.ok){const detail=Array.isArray(data.detail)?data.detail.map(e=>`${Array.isArray(e.loc)?e.loc.at(-1)+'：':''}${e.msg||'参数错误'}`).join('；'):(typeof data.detail==='string'?data.detail:'请求失败');throw Error(detail)}return data}
function label(s){return {interrupted:'已中断 · 可继续',planned:'计划已生成',writing:'生成中',running:'生成中',complete:'已完成',failed:'失败',blocked:'等待复核或配置'}[s]||s}
async function projects(){
  if(!active){advancedToolsPanel.hidden=true;advancedToolsPanel.open=false;calcPanel.open=false;decisionPanel.open=false;}
  const rows=await api('/api/industry/projects'),box=$('industry-projects');box.replaceChildren();const h=document.createElement('h2');h.textContent='研究项目';box.append(h);if(!rows.length){const p=document.createElement('p');p.textContent='还没有研究项目';box.append(p)}for(const row of rows){const b=document.createElement('button');b.type='button';b.className=row.id===active?'active':'';b.innerHTML='<strong></strong><small></small>';b.querySelector('strong').textContent=row.title;b.querySelector('small').textContent=label(row.status)+' · '+new Date(row.created).toLocaleDateString();b.onclick=()=>load(row.id);box.append(b)}
}
function evidenceForm(no){const f=document.createElement('form');f.className='evidence-form';f.innerHTML='<h3>补充证据</h3><div><input name="title" required placeholder="来源标题"><input name="publisher" placeholder="发布机构"><input name="published_at" placeholder="发布日期"><input name="url" type="url" placeholder="来源网址（可选）"><textarea name="excerpt" required placeholder="粘贴支持本章结论的原文片段"></textarea><button>保存证据</button></div>';f.onsubmit=async e=>{e.preventDefault();const b=Object.fromEntries(new FormData(f));b.chapter_no=no;try{await api(`/api/industry/projects/${active}/evidence`,{method:'POST',body:JSON.stringify(b)});await load(active)}catch(err){alert(err.message)}};return f}
const preReviewLabels={recommended_for_review:'建议优先核对',manual_review:'需人工判断',duplicate:'重复资料',empty:'无可用正文',not_pre_reviewed:'尚未自动整理'};
const reviewDecisionLabels={approved:'已人工保留',excluded:'已人工排除'};
function evidenceReviewRows(payload){return Array.isArray(payload)?payload:(Array.isArray(payload?.rows)?payload.rows:[])}
function renderEvidenceReview(box,payload,projectId,chapterNo,notice='',initialFilter=''){
  const rows=evidenceReviewRows(payload),summary=Array.isArray(payload)?{}:(payload.summary||{});box.replaceChildren();box.className='evidence-review-workbench';
  if(!rows.length){box.textContent='尚无资料，请先采集。';return}
  const toolbar=document.createElement('div');toolbar.className='evidence-review-toolbar';
  const overview=document.createElement('div');overview.className='evidence-review-overview';
  overview.innerHTML='<strong></strong><small></small>';
  const updateOverview=()=>{const processed=rows.filter(row=>row.metadata?.review?.decision).length,pendingManual=rows.filter(row=>(row.pre_review||row.metadata?.pre_review||{}).state==='manual_review'&&!row.metadata?.review?.decision).length,quoteCount=rows.reduce((sum,row)=>sum+(Array.isArray((row.pre_review||row.metadata?.pre_review||{}).exact_quotes)?(row.pre_review||row.metadata?.pre_review||{}).exact_quotes.length:0),0);overview.querySelector('strong').textContent=`已整理 ${quoteCount} 条关键摘录 · 仍需人工判断 ${pendingManual} 条`;overview.querySelector('small').textContent=`共 ${summary.total||rows.length} 条资料 · 人工已处理 ${processed} 条。自动置信度只表示摘录选择把握，不代表事实已核验。`};
  updateOverview();
  const actions=document.createElement('div');actions.className='evidence-review-actions';
  const auto=document.createElement('button');auto.type='button';auto.className='evidence-auto-review';auto.textContent='AI增强关键摘录';auto.title='复用整份报告的结构化提取缓存；资料未变化时不会重复收费';
  const batch=document.createElement('button');batch.type='button';batch.className='evidence-bulk-review';batch.textContent='一键确认安全分流';batch.title='保留含可回查摘录的建议项；排除空白与完全重复项；冲突和低相关项仍需逐条判断';
  const keepAll=document.createElement('button');keepAll.type='button';keepAll.className='evidence-bulk-review';keepAll.textContent='一键保留全部待处理';keepAll.title='保留本章所有尚未处理的非空资料，空白资料自动排除；无需逐条填写理由';
  const excludeAll=document.createElement('button');excludeAll.type='button';excludeAll.className='evidence-bulk-review';excludeAll.textContent='一键排除全部待处理';excludeAll.title='排除本章所有尚未处理的资料；已经人工处理的决定保持不变';
  const refreshReport=document.createElement('button');refreshReport.type='button';refreshReport.className='evidence-bulk-review';refreshReport.textContent='根据复核更新本章';refreshReport.hidden=!summary.report_update_required;
  refreshReport.onclick=async()=>{if(!confirm('将保留当前报告历史版本，只重新生成本章并更新摘要。是否继续？'))return;refreshReport.disabled=true;try{await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/refresh-from-evidence`,{method:'POST'});await load(projectId)}catch(error){status.textContent='启动更新失败：'+error.message;refreshReport.disabled=false}};
  actions.append(auto,batch,keepAll,excludeAll,refreshReport);
  const filter=document.createElement('select');filter.setAttribute('aria-label','筛选待复核资料');
  for(const [value,text] of [['priority','关键摘录优先（全部资料）'],['manual','只看待人工判断'],['pending','只看未人工处理'],['quotes','只看有关键摘录'],['all','按来源顺序查看全部资料']]){const option=document.createElement('option');option.value=value;option.textContent=text;filter.append(option)}
  const handledCount=rows.filter(row=>row.metadata?.review?.decision).length;
  const remainingRiskCount=rows.filter(row=>(row.pre_review||row.metadata?.pre_review||{}).state==='manual_review'&&!row.metadata?.review?.decision).length;
  const preferredFilter=initialFilter||(handledCount&&remainingRiskCount?'manual':'priority');
  filter.value=[...filter.options].some(option=>option.value===preferredFilter)?preferredFilter:'priority';
  const status=document.createElement('span');status.className='evidence-auto-status';status.setAttribute('role','status');
  status.textContent=notice||(summary.report_update_required?'资料决定已变更：当前正文尚未采用本次复核结果，请点击“根据已复核资料更新本章”。':(summary.review_complete?'本章复核已完成，可以继续生成正文。':''));toolbar.append(overview,actions,filter,status);box.append(toolbar);
  if(summary.provider_review_gate){const warning=document.createElement('p');warning.className='evidence-provider-gate';warning.textContent='本章曾触发模型厂商内容审核。自动摘录可减少阅读量，但不会代替你做最终保留/排除决定。';box.append(warning)}
  const list=document.createElement('div');list.className='evidence-review-list';box.append(list);
  const renderRows=()=>{
    list.replaceChildren();let visible=0;
    const ordered=filter.value==='priority'?[...rows].sort((a,b)=>{const aq=(a.pre_review||a.metadata?.pre_review||{}).exact_quotes?.length||0,bq=(b.pre_review||b.metadata?.pre_review||{}).exact_quotes?.length||0;return Number(Boolean(bq))-Number(Boolean(aq))}):rows;
    for(const row of ordered){
      const pre=row.pre_review||row.metadata?.pre_review||{},decision=row.metadata?.review?.decision||'',quotes=Array.isArray(pre.exact_quotes)?pre.exact_quotes:[];
      const state=pre.state||'not_pre_reviewed';
      if(filter.value==='quotes'&&!quotes.length)continue;
      if(filter.value==='manual'&&(state!=='manual_review'||decision))continue;
      if(filter.value==='pending'&&decision)continue;
      visible++;
      const card=document.createElement('article');card.className=`evidence-review-card state-${state}${decision?` decision-${decision}`:''}`;
      const head=document.createElement('div');head.className='evidence-review-head';
      const heading=document.createElement('strong');heading.textContent=`[${row.evidence_grade?.grade||'?'}级] ${row.title||'无标题'}`;
      const badges=document.createElement('span');badges.className='evidence-review-badges';
      for(const text of [reviewDecisionLabels[decision]||preReviewLabels[state]||'待核对',quotes.length?`${quotes.length}条摘录`:null].filter(Boolean)){const badge=document.createElement('i');badge.textContent=text;badges.append(badge)}
      head.append(heading,badges);card.append(head);
      const meta=document.createElement('p');meta.className='evidence-review-meta';meta.textContent=`${row.publisher||'发布机构待补'} · ${row.published_at||'日期待补'} · 来源组 ${row.evidence_grade?.origin_key||'待补'}`;card.append(meta);
      if(quotes.length){const quoteBox=document.createElement('div');quoteBox.className='evidence-key-quotes';const qh=document.createElement('b');qh.textContent='系统逐字摘录';quoteBox.append(qh);for(const item of quotes){const q=document.createElement('blockquote');q.textContent=typeof item==='string'?item:(item.quote||'');if(q.textContent)quoteBox.append(q)}card.append(quoteBox)}
      const risks=[...(pre.risks||[]),...(row.review_warnings||[])];if(risks.length){const risk=document.createElement('p');risk.className='evidence-review-risk';risk.textContent='核对提示：'+[...new Set(risks)].join(' ');card.append(risk)}
      const full=document.createElement('details');full.className='evidence-full-source';const fullSummary=document.createElement('summary');fullSummary.textContent='查看完整原始摘录';const text=document.createElement('p');text.textContent=row.excerpt||'';full.append(fullSummary,text);if(/^https?:\/\//i.test(row.url)){const link=document.createElement('a');link.href=row.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='打开原始来源核对';full.append(link)}card.append(full);
      const controls=document.createElement('div');controls.className='evidence-review-controls';const reason=document.createElement('input');reason.placeholder='核对理由（至少2个字）';reason.setAttribute('aria-label',`${row.title||'本条资料'}的核对理由`);reason.value=row.metadata?.review?.reason||'';reason.maxLength=500;controls.append(reason);
      const decisionButtons=[];for(const [nextDecision,text] of [['approved','确认保留'],['excluded','排除（原资料仍保留）']]){const button=document.createElement('button');button.type='button';button.textContent=text;decisionButtons.push(button);button.onclick=async()=>{if(reason.value.trim().length<2){alert('请填写至少2个字的核对理由');return}decisionButtons.forEach(item=>item.disabled=true);reason.disabled=true;try{const result=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review/${row.id}`,{method:'PUT',body:JSON.stringify({decision:nextDecision,reason:reason.value.trim()})});row.metadata=row.metadata||{};row.metadata.review={decision:nextDecision,reason:reason.value.trim()};refreshReport.hidden=!result.report_update_required;status.textContent=`已保存：${text}。`+(result.review_complete?(result.report_update_required?'本章复核已完成，正文已标记待更新。':'本章复核已完成，可继续生成。'):'');updateOverview();renderRows()}catch(error){status.textContent='保存失败：'+error.message}finally{decisionButtons.forEach(item=>item.disabled=false);reason.disabled=false}};controls.append(button)}
      card.append(controls);list.append(card);
    }
    if(!visible){const empty=document.createElement('p');empty.className='evidence-review-empty';empty.textContent=filter.value==='quotes'?'尚未截取关键片段；采集会先由程序自动摘录，也可点击“AI增强关键摘录”。':'当前筛选下没有资料。';list.append(empty)}
  };
  filter.onchange=renderRows;
  auto.onclick=async()=>{const selectedFilter=filter.value;auto.disabled=true;batch.disabled=true;status.textContent='正在复用结构化提取结果，并逐字校验关键句…';try{const result=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review/auto`,{method:'POST',body:JSON.stringify({use_ai:true,force:false})});const message=(result.cached?'已使用缓存，无重复模型费用。':'AI增强整理完成。')+(result.warning?` 部分AI整理未完成：${result.warning}`:'');const refreshed=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review`);renderEvidenceReview(box,refreshed,projectId,chapterNo,message,selectedFilter)}catch(error){status.textContent='自动整理失败：'+error.message;auto.disabled=false;batch.disabled=false}};
  batch.onclick=async()=>{if(!confirm('将批量保留含可回查关键摘录的建议项，并排除空白或完全重复资料。冲突、低相关和弱来源仍留给你逐条判断；这不代表关键数字已核实。是否继续？'))return;auto.disabled=true;batch.disabled=true;status.textContent='正在应用已确认的安全分流…';try{const result=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review/apply-suggestions`,{method:'POST',body:JSON.stringify({confirm:'apply_safe_suggestions'})});const remaining=result.pending_remaining||0;const message=`已批量保留 ${result.retained||0} 条、排除 ${result.excluded||0} 条；剩余未人工处理 ${remaining} 条，其中风险项 ${result.manual_remaining||0} 条。`+(remaining?'下方已切换为只显示剩余风险项。':'')+(result.review_complete?'本章复核门槛已完成，可继续生成。':'');const refreshed=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review`);renderEvidenceReview(box,refreshed,projectId,chapterNo,message,remaining?'manual':'priority')}catch(error){status.textContent='批量处理失败：'+error.message;auto.disabled=false;batch.disabled=false}};
  const decideAll=async(confirmValue,verb)=>{const pending=rows.filter(row=>!row.metadata?.review?.decision).length;if(!pending){status.textContent='本章没有待处理资料。';return}if(!confirm(`将${verb}本章剩余 ${pending} 条待处理资料，已经处理的决定不变。系统会自动记录批量审核理由，是否继续？`))return;for(const button of [auto,batch,keepAll,excludeAll])button.disabled=true;status.textContent=`正在${verb}全部待处理资料…`;try{const result=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review/apply-suggestions`,{method:'POST',body:JSON.stringify({confirm:confirmValue})});const message=`本章批量处理完成：保留 ${result.retained||0} 条、排除 ${result.excluded||0} 条，剩余 ${result.pending_remaining||0} 条。`+(result.review_complete?'现在可以直接继续生成。':'本章至少需要保留一条有效资料。');const refreshed=await api(`/api/industry/projects/${projectId}/chapters/${chapterNo}/evidence-review`);renderEvidenceReview(box,refreshed,projectId,chapterNo,message,'pending')}catch(error){status.textContent='批量处理失败：'+error.message;for(const button of [auto,batch,keepAll,excludeAll])button.disabled=false}};
  keepAll.onclick=()=>decideAll('approve_all_pending','保留');
  excludeAll.onclick=()=>decideAll('exclude_all_pending','排除');
  renderRows();
}
async function watchCollection(jobId,panel,button){
  for(;;){
    const job=await api('/api/industry/collection-jobs/'+jobId);
    panel.hidden=false;
    panel.querySelector('i').style.width=`${job.percent||0}%`;
    panel.querySelector('strong').textContent=job.message||job.stage;
    panel.querySelector('small').textContent=`${job.percent||0}% · 查询 ${job.done||0}/${job.total||0} · 当前新增/已保留 ${job.saved||0} 条`;
    if(job.status==='complete'){
      const r=job.result,web=r.web||{};
      panel.classList.remove('failed','warning');
      panel.querySelector('strong').textContent='采集完成';
      panel.querySelector('small').textContent=`本次新增并保留 ${job.saved||0} 条 · AKShare ${r.structured_saved||0} 条 · 网页 ${web.saved||0} 条 · 实际网页查询 ${web.queries_run||0} 个`;
      button.disabled=false;button.textContent='再次采集本章资料';
      setTimeout(()=>load(active).catch(console.error),800);return;
    }
    if(job.status==='complete_with_warning'||job.status==='partial'){
      const r=job.result||{},web=r.web||{},webError=r.web_error||web.error||job.warning||'未完成全部网页查询';
      panel.classList.remove('failed');panel.classList.add('warning');
      panel.querySelector('strong').textContent='网页搜索中断：'+webError;
      panel.querySelector('small').textContent=`已保留本次新增 ${job.saved||0} 条 · AKShare ${r.structured_saved||0} 条 · 网页 ${web.saved||0} 条 · 实际网页查询 ${web.queries_run||0} 个；可再次采集`;
      button.disabled=false;button.textContent='再次采集本章资料';
      setTimeout(()=>load(active).catch(console.error),800);return;
    }
    if(job.status==='failed'){
      panel.classList.remove('warning');panel.classList.add('failed');
      panel.querySelector('strong').textContent='采集失败：'+job.error;
      button.disabled=false;button.textContent='重试采集';return;
    }
    await new Promise(resolve=>setTimeout(resolve,800));
  }
}
function chapter(c,chartSpecs=[],projectId=active,session){
  const d=document.createElement('details');
  d.className='industry-chapter';
  if(c.status==='writing')d.open=true;
  const s=document.createElement('summary');
  s.innerHTML='<span></span><em></em>';
  s.querySelector('span').textContent=c.chapter_no===0?'摘要':`第${c.chapter_no}章 · ${c.title}`;
  const audit=c.evidence_audit;
  let chapterStatus=label(c.status);
  if(c.chapter_no>0&&audit?.grade_counts){
    const grades=audit.grade_counts;
    const usable=Object.values(grades).reduce((sum,value)=>sum+Number(value||0),0);
    const total=Number(c.evidence_count||0);
    chapterStatus=`${usable} 条可用资料${total!==usable?` / 共 ${total} 条`:''} · A${grades.A||0}/B${grades.B||0}/C${grades.C||0}/D${grades.D||0} · ${label(c.status)}`;
    s.querySelector('em').title=`独立A/B原始来源组：${audit.independent_ab_origin_groups||0}；来源等级仅辅助筛选，不代表指标口径已经核验。`;
  }
  if(c.evidence_stale)chapterStatus+=' · 复核资料已变更，正文待更新';
  s.querySelector('em').textContent=chapterStatus;
  d.append(s);
  const body=document.createElement('div');body.className='chapter-body';
  if(c.chapter_no>0){
    const reviewButton=document.createElement('button'),reviewBox=document.createElement('div');reviewButton.type='button';reviewButton.textContent='复核本章资料';reviewButton.className='chapter-search';body.append(reviewButton,reviewBox);
    reviewButton.onclick=async()=>{reviewButton.disabled=true;reviewBox.textContent='正在读取原始资料…';try{
      const payload=await api(`/api/industry/projects/${projectId}/chapters/${c.chapter_no}/evidence-review`);renderEvidenceReview(reviewBox,payload,projectId,c.chapter_no);
    }catch(e){reviewBox.textContent=e.message;}finally{reviewButton.disabled=false;}};
    if(c.evidence_stale&&c.content){
      const refresh=document.createElement('button');refresh.type='button';refresh.className='chapter-search';refresh.textContent='根据已复核资料更新本章';
      refresh.onclick=async()=>{if(!confirm('将保留当前报告历史版本，只重新生成本章并更新摘要。是否继续？'))return;refresh.disabled=true;try{await api(`/api/industry/projects/${projectId}/chapters/${c.chapter_no}/refresh-from-evidence`,{method:'POST'});await load(projectId)}catch(e){alert(e.message);refresh.disabled=false}};
      body.append(refresh);
    }
  }
  if(c.content){
    const a=document.createElement('article');a.className='body';renderMarkdown(a,c.content);
    const edit=document.createElement('button');edit.type='button';edit.className='edit-chapter';edit.textContent='编辑本章';
    edit.onclick=async()=>{
      try{await flushChartChanges(projectId)}catch(e){alert('请先保存图表选择：'+e.message);return}
      const area=document.createElement('textarea');area.className='chapter-editor';area.value=c.content;
      const save=document.createElement('button');save.textContent='保存修改';
      save.onclick=async()=>{
        save.disabled=true;
        try{await api(`/api/industry/projects/${projectId}/chapters/${c.chapter_no}`,{method:'PATCH',body:JSON.stringify({content:area.value})});await load(projectId)}
        catch(e){alert(e.message);save.disabled=false}
      };
      body.replaceChildren(area,save);
    };
    if(c.chapter_no>0)body.append(chapterChartPanel(chartSpecs,projectId,session,count=>{
      s.querySelector('em').textContent=chapterStatus+` · 已选 ${count} 张图`;
    }));
    body.append(edit,a);
  }else{
    if(session)body.append(chapterChartPanel(chartSpecs,projectId,session));
    const plan=document.createElement('div');plan.className='chapter-plan';plan.innerHTML='<h3>研究问题</h3>';
    const ul=document.createElement('ul');
    for(const q of c.questions||[]){const li=document.createElement('li');li.textContent=q;ul.append(li)}
    plan.append(ul);const h=document.createElement('h3');h.textContent='建议搜索词';plan.append(h);
    for(const q of c.queries||[]){const code=document.createElement('code');code.textContent=q;plan.append(code)}
    if(c.chapter_no>0){
      const search=document.createElement('button');search.type='button';search.className='chapter-search';search.textContent='低成本采集本章资料';
      const progress=document.createElement('div');progress.className='collection-progress';progress.hidden=true;progress.innerHTML='<div><i></i></div><strong></strong><small></small>';
      search.onclick=async()=>{
        search.disabled=true;search.textContent='采集中…';progress.classList.remove('failed','warning');
        try{const r=await api(`/api/industry/projects/${projectId}/chapters/${c.chapter_no}/collect/start`,{method:'POST',body:JSON.stringify({max_web_queries:3,results_per_query:8})});await watchCollection(r.job_id,progress,search)}
        catch(e){progress.hidden=false;progress.classList.add('failed');progress.querySelector('strong').textContent=e.message;search.disabled=false;search.textContent='重试采集'}
      };
      plan.append(search,progress);
    }
    body.append(plan);if(c.chapter_no>0)body.append(evidenceForm(c.chapter_no));
  }
  d.append(body);return d;
}

function drawChart(spec){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 640 270');svg.setAttribute('role','img');svg.setAttribute('aria-label',spec.title);
  const add=(tag,attributes,text)=>{
    const element=document.createElementNS(ns,tag);
    for(const [key,value] of Object.entries(attributes))element.setAttribute(key,value);
    if(text!==undefined)element.textContent=text;svg.append(element);return element;
  };
  const fmt=v=>Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
  const values=spec.values,labels=spec.labels,kind=spec.selected_type;
  add('text',{x:20,y:24,fill:'#60756c','font-size':13},'单位：'+spec.unit);
  if(kind==='card'){
    add('text',{x:28,y:128,fill:'#1e6874','font-size':48,'font-weight':700},fmt(values[0])+' '+spec.unit);
    const title=labels[0]||spec.title;
    for(let i=0;i<title.length;i+=30)add('text',{x:28,y:178+(i/30)*23,fill:'#536a5e','font-size':16},title.slice(i,i+30));
    return svg;
  }
  if(kind==='pie'){
    let angle=-Math.PI/2;const total=values.reduce((a,b)=>a+b,0);
    const colors=['#1e6874','#427b93','#769aa6','#abc6ca','#ccdadd'];
    values.forEach((v,i)=>{
      const next=angle+v/total*Math.PI*2;
      const x1=165+Math.cos(angle)*90,y1=145+Math.sin(angle)*90;
      const x2=165+Math.cos(next)*90,y2=145+Math.sin(next)*90;
      add('path',{d:'M165 145 L'+x1+' '+y1+' A90 90 0 '+(next-angle>Math.PI?1:0)+' 1 '+x2+' '+y2+' Z',fill:colors[i%colors.length]});
      add('text',{x:290,y:70+i*27,'font-size':13,fill:'#33483e'},labels[i]+'  '+fmt(v)+'%');angle=next;
    });return svg;
  }
  const max=Math.max(...values,1),limit=max*1.15;
  if(kind==='bar'){
    const rowHeight=32,height=Math.max(220,labels.length*rowHeight+60);
    svg.setAttribute('viewBox','0 0 640 '+height);
    for(let i=0;i<=4;i++){
      const x=225+330*i/4;
      add('line',{x1:x,y1:38,x2:x,y2:height-30,stroke:'#e4ebe7'});
      add('text',{x,y:height-10,'text-anchor':'middle','font-size':11,fill:'#718178'},fmt(limit*i/4));
    }
    labels.forEach((label,i)=>{
      const y=42+i*rowHeight;
      add('text',{x:210,y:y+16,'text-anchor':'end','font-size':12,fill:'#3a5145'},String(label).slice(0,18));
      add('rect',{x:225,y,width:Math.max(0,values[i])/limit*330,height:22,rx:3,fill:'#1e6874'});
      add('text',{x:230+Math.max(0,values[i])/limit*330,y:y+16,'font-size':11,fill:'#334b3e'},fmt(values[i]));
    });return svg;
  }
  const numeric=kind!=='column'&&labels.every(v=>/^\d{4}$/.test(String(v)));
  const times=numeric?labels.map(Number):labels.map((_,i)=>i);
  const low=Math.min(...times),high=Math.max(...times),points=[];
  for(let i=0;i<=4;i++){
    const y=225-170*i/4;
    add('line',{x1:72,y1:y,x2:600,y2:y,stroke:'#e4ebe7'});
    add('text',{x:62,y:y+4,'text-anchor':'end','font-size':11,fill:'#718178'},fmt(limit*i/4));
  }
  values.forEach((value,i)=>{
    const x=90+(times[i]-low)/(high-low||1)*485,y=225-value/limit*170;points.push([x,y]);
    add('text',{x,y:249,'text-anchor':'middle','font-size':12,fill:'#60756c'},labels[i]);
  });
  if(kind==='area')add('polygon',{points:[[points[0][0],225],...points,[points.at(-1)[0],225]].map(p=>p.join(',')).join(' '),fill:'#1e6874','fill-opacity':.18});
  if(kind==='line'||kind==='area')add('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#1e6874','stroke-width':3});
  if(kind==='lollipop')points.forEach(([x,y])=>add('line',{x1:x,y1:225,x2:x,y2:y,stroke:'#80aab0','stroke-width':4}));
  if(kind==='column')points.forEach(([x,y])=>add('rect',{x:x-Math.min(38,220/points.length)/2,y,width:Math.min(38,220/points.length),height:225-y,fill:'#1e6874',rx:2}));
  points.forEach(([x,y],i)=>{add('circle',{cx:x,cy:y,r:4,fill:'#1e6874'});add('text',{x,y:y-12,'text-anchor':'middle','font-size':12,fill:'#2c4337'},fmt(values[i]))});
  return svg;
}

async function flushChartChanges(projectId){
  const session=chartSessions.get(projectId);
  if(!session)return;
  await Promise.all(session.controllers.map(controller=>controller.flush()));
}

async function showVersions(projectId,actions){
  await flushChartChanges(projectId);
  const old=document.getElementById('version-history');if(old)old.remove();
  const panel=document.createElement('section');panel.id='version-history';panel.className='version-history';
  const heading=document.createElement('h3');heading.textContent='版本历史';
  const hint=document.createElement('p');hint.textContent='重新生成成功前自动备份旧稿；恢复时也保留当前版本。功能启用前已覆盖的正文无法找回。';
  const save=document.createElement('button');save.textContent='保存当前版本';save.onclick=async()=>{save.disabled=true;try{await api(`/api/industry/projects/${projectId}/versions`,{method:'POST'});await showVersions(projectId,actions)}catch(e){alert(e.message);save.disabled=false}};
  panel.append(heading,hint,save);actions.parentElement.after(panel);
  const rows=await api(`/api/industry/projects/${projectId}/versions`);
  if(!rows.length){const empty=document.createElement('p');empty.textContent='暂无历史版本，可以先保存当前版本。';panel.append(empty)}
  for(const row of rows){
    const item=document.createElement('details'),label=document.createElement('summary');label.textContent=new Date(row.created).toLocaleString()+' · '+row.reason+' · '+row.title;item.append(label);
    const download=document.createElement('a');download.textContent='下载此版本';download.href=`/api/industry/projects/${projectId}/versions/${row.id}/download/docx`;
    const restore=document.createElement('button');restore.textContent='恢复此版本';restore.onclick=async()=>{if(!confirm('恢复此版本？当前正文和选图配置会先保存到历史版本，不会丢失。'))return;restore.disabled=true;try{await flushChartChanges(projectId);await api(`/api/industry/projects/${projectId}/versions/${row.id}/restore`,{method:'POST'});panel.remove();await load(projectId)}catch(e){alert(e.message);restore.disabled=false}};
    const preview=document.createElement('div');item.append(download,restore,preview);let loaded=false;
    item.ontoggle=async()=>{if(!item.open||loaded)return;loaded=true;try{const version=await api(`/api/industry/projects/${projectId}/versions/${row.id}`);for(const c of version.snapshot.project.chapters){const h=document.createElement('h4');h.textContent=c.chapter_no===0?'摘要':`第${c.chapter_no}章 · ${c.title}`;const article=document.createElement('article');renderMarkdown(article,c.content);preview.append(h,article)}}catch(e){loaded=false;preview.textContent=e.message}};
    panel.append(item);
  }
}

function chapterChartPanel(specs,projectId,session,onCount=()=>{}){
  const panel=document.createElement('section');panel.className='chapter-charts';
  const heading=document.createElement('h3'),hint=document.createElement('p');
  heading.textContent='本章图表';hint.textContent='选择后自动保存；不绘图的内容不会进入 Word。可展开数据核对数值与原文。';
  panel.append(heading,hint);
  if(!specs.length){hint.textContent='本章暂无可识别的数值图表，可以不绘图；补充正文数字后会重新提取。';return panel}
  const grid=document.createElement('div');grid.className='chapter-chart-grid';panel.append(grid);
  const updateCount=()=>{const count=specs.filter(s=>s.selected).length;heading.textContent='本章图表 · 已选 '+count+'/'+specs.length;onCount(count)};
  updateCount();
  for(const spec of specs){
    const card=document.createElement('article');card.className='chapter-chart-card';
    const title=document.createElement('input');title.value=spec.title;title.className='chart-title';title.maxLength=200;title.setAttribute('aria-label','图表标题');
    const select=document.createElement('select');select.setAttribute('aria-label','图形选择 '+spec.title);
    for(const type of ['none',...spec.chart_types]){
      const option=document.createElement('option');option.value=type;
      option.textContent={none:'不绘图',line:'折线图',bar:'横向条形图',column:'纵向柱状图',area:'面积图',scatter:'散点图',lollipop:'棒棒糖图',pie:'饼图',card:'关键数字'}[type];select.append(option);
    }
    select.value=spec.selected?spec.selected_type:'none';
    const status=document.createElement('small');status.setAttribute('role','status');
    const view=document.createElement('div');view.className='chart-view';
    const retry=document.createElement('button');retry.type='button';retry.textContent='重试保存';retry.hidden=true;
    const top=document.createElement('div');top.className='chart-choice';top.append(title,select);
    const details=document.createElement('details');details.className='chart-source';
    const summary=document.createElement('summary');summary.textContent='核对数据与原文';details.append(summary);
    const table=document.createElement('table');
    const header=document.createElement('tr');for(const text of ['指标/年份','数值（'+spec.unit+'）']){const th=document.createElement('th');th.textContent=text;header.append(th)}table.append(header);
    spec.labels.forEach((label,i)=>{const row=document.createElement('tr');for(const text of [label,spec.values[i]]){const td=document.createElement('td');td.textContent=text;row.append(td)}table.append(row)});
    details.append(table);
    for(const excerpt of spec.source_excerpts||[]){const quote=document.createElement('p');quote.textContent=typeof excerpt==='string'?excerpt:(excerpt.excerpt||excerpt.text||'');details.append(quote)}
    let version=0,savedVersion=0,pending=null,error=null;
    const redraw=()=>{view.replaceChildren(drawChart({...spec,title:title.value,selected_type:select.value==='none'?spec.chart_types[0]:select.value}));card.classList.toggle('chart-included',select.value!=='none')};
    const stableStatus=()=>{status.textContent=spec.selected?'已选入报告':'不绘图';retry.hidden=true};
    const drain=()=>{
      if(pending)return pending;
      pending=(async()=>{
        while(savedVersion<version){
          const atVersion=version;
          const body={id:spec.id,selected:select.value!=='none',chart_type:select.value==='none'?spec.chart_types[0]:select.value,title:title.value.trim()||spec.title};
          status.textContent='保存中…';error=null;retry.hidden=true;
          try{
            const saved=await api('/api/industry/projects/'+projectId+'/charts/'+spec.id,{method:'PUT',body:JSON.stringify(body)});
            savedVersion=atVersion;spec.selected=saved.selected;spec.selected_type=saved.selected_type;spec.title=saved.title;
            updateCount();
          }catch(e){error=e;status.textContent='保存失败：'+e.message;retry.hidden=false;break}
        }
        if(!error)stableStatus();
      })().finally(()=>{pending=null});
      return pending;
    };
    const change=()=>{version++;redraw();drain()};
    const controller={flush:async()=>{await drain();if(error)throw error;if(savedVersion<version)throw Error('图表仍未保存')}};
    if(session)session.controllers.push(controller);
    select.onchange=change;title.oninput=change;retry.onclick=()=>{error=null;drain()};
    redraw();stableStatus();card.append(top,status,view,details,retry);grid.append(card);
  }
  return panel;
}

async function downloadReport(projectId,link){
  if(link.dataset.busy==='true')return;
  link.dataset.busy='true';link.setAttribute('aria-disabled','true');link.textContent='正在保存选图并排版…';
  try{
    await flushChartChanges(projectId);
    const response=await fetch('/api/industry/projects/'+projectId+'/download/docx?t='+Date.now(),{cache:'no-store'});
    if(!response.ok){const body=await response.json().catch(()=>({}));throw Error(body.detail||'下载失败')}
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    const disposition=response.headers.get('content-disposition')||'';
    const match=disposition.match(/filename\*=utf-8''([^;]+)/i);
    a.download=match?decodeURIComponent(match[1]):'行业研究报告.docx';a.href=url;a.click();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    link.textContent='已下载 · 含 '+(response.headers.get('x-report-chart-count')||'0')+' 张图';
  }catch(e){alert(e.message);link.textContent='重新下载完整Word报告 ↓'}
  finally{link.dataset.busy='false';link.removeAttribute('aria-disabled')}
}

async function load(id){const version=++loadVersion;await flushChartChanges(active);document.getElementById('version-history')?.remove();active=id;localStorage.setItem('ckos-industry-project',id);clearTimeout(timer);const p=await api('/api/industry/projects/'+id);if(version!==loadVersion||id!==active)return;currentProject=p;$('brief-panel').hidden=true;$('project-panel').hidden=false;const st=$('project-status');st.replaceChildren();const hd=document.createElement('div');hd.className='progress-info';hd.innerHTML='<h2></h2><p class="stage"></p><div class="progress-track"><i></i></div><p class="progress-meta"></p><p class="project-error" hidden></p>';hd.querySelector('h2').textContent=p.title;hd.querySelector('.stage').textContent=p.current_stage;hd.querySelector('.progress-track i').style.width=`${p.progress_percent||0}%`;const started=p.started_at?new Date(p.started_at).toLocaleTimeString():'尚未开始';const updated=p.updated?new Date(p.updated).toLocaleTimeString():'--';hd.querySelector('.progress-meta').textContent=`${p.progress_percent||0}% · 已完成 ${p.completed_chapters||0}/10 章 · 开始 ${started} · 最近更新 ${updated}`;if(p.error){const err=hd.querySelector('.project-error');err.hidden=false;err.textContent='失败原因：'+p.error}const actions=document.createElement('div');actions.className='report-actions';const gen=document.createElement('button');gen.textContent=p.generation_active?'正在生成…':(p.status==='complete'?'已全部完成':((p.completed_chapters||0)>0||['failed','interrupted','blocked'].includes(p.status)?'继续生成':'生成十章与摘要'));gen.disabled=!!p.generation_active||p.status==='complete';gen.onclick=async()=>{try{await api(`/api/industry/projects/${id}/resume`,{method:'POST'});await load(id)}catch(e){alert(e.message)}};const rename=document.createElement('button');rename.className='secondary-action';rename.textContent='重命名';rename.onclick=async()=>{const title=prompt('报告名称',p.title);if(title&&title.trim()!==p.title){await api(`/api/industry/projects/${id}`,{method:'PATCH',body:JSON.stringify({title:title.trim()})});await load(id)}};const remove=document.createElement('button');remove.className='danger-action';remove.textContent='删除报告';remove.onclick=async()=>{if(confirm(`确定删除“${p.title}”及其章节和证据吗？此操作不可撤销。`)){await api(`/api/industry/projects/${id}`,{method:'DELETE'});localStorage.removeItem('ckos-industry-project');active=null;loadVersion++;currentProject=null;calcPanel.hidden=true;calcPanel.open=false;decisionPanel.hidden=true;decisionPanel.open=false;decisionList.replaceChildren();$('project-panel').hidden=true;$('brief-panel').hidden=false;await projects()}};const regen=document.createElement('button');regen.className='secondary-action';regen.textContent='重新生成';regen.disabled=!!p.generation_active;regen.onclick=async()=>{if(!confirm('重新调用模型生成十章和摘要，会产生新的 API 费用。成功后替换正文；取消或失败保留原报告。确定继续？'))return;regen.disabled=true;try{await api(`/api/industry/projects/${id}/regenerate`,{method:'POST'});await load(id)}catch(e){alert(e.message);regen.disabled=false}};const cancel=document.createElement('button');cancel.className='danger-action';cancel.textContent=p.cancel_requested?'正在取消…':(p.generation_mode==='regenerate'?'取消重新生成':'取消生成');cancel.hidden=!p.generation_active;cancel.disabled=!!p.cancel_requested;cancel.onclick=async()=>{cancel.disabled=true;try{await api(`/api/industry/projects/${id}/cancel`,{method:'POST'});await load(id)}catch(e){alert(e.message);cancel.disabled=false}};const history=document.createElement('button');history.textContent='版本历史';history.className='secondary-action';history.onclick=()=>showVersions(id,actions).catch(e=>alert(e.message));const pptButton=document.createElement('button');pptButton.textContent='生成 PPT';pptButton.className='secondary-action';pptButton.onclick=async()=>{try{await flushChartChanges(id);window.openPpt(id)}catch(e){alert(e.message)}};actions.append(pptButton,gen,regen,cancel,history,rename,remove);if(p.status==='complete'){const download=document.createElement('a');download.className='download-report';download.href=`/api/industry/projects/${id}/download/docx`;download.textContent='下载完整Word报告 ↓';download.onclick=e=>{e.preventDefault();downloadReport(id,download)};actions.prepend(download)}st.append(hd,actions);const list=$('chapter-list');list.className=p.status==='complete'?'complete-report':'';list.replaceChildren();const chartData=p.status==='complete'?await api(`/api/industry/projects/${id}/charts`):{charts:[]};const session={controllers:[]};chartSessions.set(id,session);if(chartData.stale_selected_count){const clear=document.createElement('button');clear.textContent='清除 '+chartData.stale_selected_count+' 个失效选图后重新选择';clear.onclick=async()=>{await api('/api/industry/projects/'+id+'/charts/stale',{method:'DELETE'});await load(id)};list.append(clear)}for(const c of p.chapters)list.append(chapter(c,chartData.charts.filter(x=>x.chapter_no===c.chapter_no),id,session));$('chart-dashboard')?.remove();await projects();if(version!==loadVersion||id!==active)return;if(p.generation_active)timer=setTimeout(()=>load(id).catch(console.error),2500)}
const loadWithoutPlanUpgrade=load;
load=async function(id){
  await loadWithoutPlanUpgrade(id);
  if(id!==active||!currentProject)return;
  const project=currentProject;
  if(decisionUiProject!==id){decisionUiProject=id;advancedToolsPanel.open=false;calcPanel.open=false;decisionPanel.open=false;calcForm.reset();calcResult.replaceChildren();decisionForm.reset();decisionForm.elements.namedItem('record_id').value='';decisionList.replaceChildren();document.dispatchEvent(new CustomEvent('ckos:industry-project-changed',{detail:{projectId:id,projectTitle:project.title}}));}
  const manufacturing=project.brief?.research_template==='manufacturing';
  advancedToolsPanel.hidden=!manufacturing;
  calcPanel.hidden=false;
  decisionPanel.hidden=false;
  if(!manufacturing){advancedToolsPanel.open=false;calcPanel.open=false;decisionPanel.open=false;decisionList.replaceChildren();return;}
  syncDecisionAutoAvailability(project);
  if(decisionPanel.open)await refreshDecisionRecords();
  if(project.manufacturing_plan_current!==false)return;
  const actions=document.querySelector('#project-status .report-actions');
  if(!actions)return;
  const upgrade=document.createElement('button');
  upgrade.className='secondary-action';
  upgrade.textContent='升级为制造业决策版';
  upgrade.title='先保存当前版本，再重建十章并重新归类已有资料';
  upgrade.disabled=!!project.generation_active;
  upgrade.onclick=async()=>{
    if(project.generation_active){alert('请先取消生成并等待任务停止。');return;}
    if(!confirm('系统会先把当前报告保存到版本历史，再清空当前正文并改用“市场—客户—竞争—设备—工厂—财务—决策”十章。已有原始资料保留并重新归类。是否继续？'))return;
    upgrade.disabled=true;
    try{await api(`/api/industry/projects/${id}/upgrade-manufacturing-plan`,{method:'POST'});await load(id)}catch(error){alert(error.message);upgrade.disabled=false}
  };
  actions.insertBefore(upgrade,actions.firstChild);
};
$('industry-form').onsubmit=async e=>{e.preventDefault();if(creating)return;creating=true;$('industry-error').textContent='';const form=e.currentTarget,submit=form.querySelector('button[type="submit"],button:not([type])'),oldText=submit?.textContent;if(submit){submit.disabled=true;submit.textContent='正在生成计划…'}const body=Object.fromEntries(new FormData(form));for(const k of ['history_start','history_end','forecast_end'])body[k]=Number(body[k]);try{const p=await api('/api/industry/projects',{method:'POST',body:JSON.stringify(body)});await load(p.id)}catch(err){$('industry-error').textContent=err.message}finally{creating=false;if(submit){submit.disabled=false;submit.textContent=oldText}}};
$('industry-new').onclick=()=>{active=null;loadVersion++;currentProject=null;decisionUiProject=null;document.dispatchEvent(new CustomEvent('ckos:industry-project-changed',{detail:{projectId:null}}));clearTimeout(timer);advancedToolsPanel.hidden=true;advancedToolsPanel.open=false;calcPanel.open=false;decisionPanel.open=false;decisionList.replaceChildren();$('brief-panel').hidden=false;$('project-panel').hidden=true;projects()};
window.ckosDecisionContext={getProjectId:()=>active,getProject:()=>currentProject,api,
  refreshDecisionRecords,decisionPanel,reloadProject:()=>active?load(active):Promise.resolve()};
(async()=>{await projects();const id=localStorage.getItem('ckos-industry-project');if(id)try{await load(id)}catch(e){localStorage.removeItem('ckos-industry-project')}})().catch(e=>$('industry-error').textContent=e.message)
}
