(()=>{
const layouts={cover:'封面',conclusions:'核心结论',chart:'图表分析',comparison:'企业或指标对比',flow:'流程／产业链',risk:'风险分析',research:'阅读版研究内容块'};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
async function request(url,options={}){const r=await fetch(url,{...options,headers:{'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:Array.isArray(d.detail)?d.detail.map(e=>e.msg).join('；'):'内容不符合要求，请检查字数和版式');return d}
window.openPpt=async projectId=>{
  document.getElementById('ppt-dialog')?.remove();
  const dialog=el('dialog',undefined,'ppt-dialog');dialog.id='ppt-dialog';
  const close=el('button','关闭','secondary-action');close.onclick=()=>dialog.close();
  const header=el('header');header.append(el('h2','报告转 PPT'),close);
  const help=el('p','阅读版保留小节、分析和比较表，按出处绑定图表，不调用模型；汇报版用于压缩演示。编辑内容块不会覆盖原始报告。');
  const controls=el('div',undefined,'ppt-controls'),version=el('select'),ai=el('input');ai.type='checkbox';
  version.append(new Option('当前报告',''));version.setAttribute('aria-label','报告版本');
  const aiLabel=el('label');aiLabel.append(ai,document.createTextNode('AI 提炼（调用现有模型，产生费用）'));
  const create=el('button','生成新大纲'),history=el('select');history.setAttribute('aria-label','PPT 历史任务');history.append(new Option('打开已保存的 PPT 任务',''));
  const mode=el('select');mode.setAttribute('aria-label','输出用途');mode.append(new Option('阅读版：保留小节、正文和表格','reading'),new Option('汇报版：压缩为演示要点','presentation'));
  mode.value='reading';mode.onchange=()=>{ai.disabled=mode.value==='reading';if(ai.disabled)ai.checked=false};mode.onchange();
  controls.append(version,mode,aiLabel,create,history);
  const status=el('p','请选择报告版本生成大纲','ppt-status');status.setAttribute('role','status');
  const progress=el('progress');progress.max=100;progress.value=0;
  const warnings=el('div',undefined,'ppt-warnings'),editor=el('div'),actions=el('div',undefined,'ppt-controls'),previews=el('div',undefined,'ppt-previews');
  const save=el('button','保存大纲'),generate=el('button','确认大纲并生成 PPT'),add=el('button','增加一页','secondary-action');
  actions.append(save,generate,add);actions.hidden=true;save.disabled=generate.disabled=add.disabled=true;
  dialog.append(header,help,controls,status,progress,warnings,actions,editor,previews);document.body.append(dialog);dialog.showModal();
  const base=`/api/industry/projects/${projectId}/ppt`;let job=null,timer=null,dirty=false,creating=false,runningId=null;
  function markDirty(){dirty=true;previews.replaceChildren();status.textContent='大纲有未保存修改，请保存并重新生成 PPT 后下载';}
  editor.addEventListener('input',markDirty);
  editor.addEventListener('change',markDirty);
  dialog.addEventListener('close',()=>{clearTimeout(timer);dialog.remove()});
  function ready(){return !!job&&Array.isArray(job.slides)}
  function syncActions(){const active=!!job&&['planning','rendering'].includes(job.status);if(job?.id===runningId&&!active)runningId=null;const busy=!ready()||active;actions.hidden=!ready();save.disabled=generate.disabled=busy||!job?.slides?.length;add.disabled=busy;create.disabled=creating||active||!!runningId;create.textContent=create.disabled?'已有任务处理中…':'生成新大纲';}
  const fail=e=>{status.textContent=e.message;syncActions()};
  async function refreshHistory(){const list=await request(base);runningId=list.find(j=>['planning','rendering'].includes(j.status))?.id||null;history.replaceChildren(new Option('打开已保存的 PPT 任务',''));for(const j of list)history.append(new Option(new Date(j.created).toLocaleString()+' '+j.stage,j.id));syncActions();if(!job&&runningId){job={id:runningId};history.value=runningId;await poll()}}
  function state(){status.textContent=job.stage+(job.error?'：'+job.error:'');progress.value=job.percent||0;warnings.replaceChildren();for(const w of job.warnings||[])warnings.append(el('p',w));}
  function draw(){
    editor.replaceChildren();previews.replaceChildren();syncActions();if(!ready())return;state();
    const busy=['planning','rendering'].includes(job.status);
    job.slides.forEach((s,index)=>{
      const card=el('section',undefined,'ppt-page-editor'),top=el('div',undefined,'ppt-controls');
      const enable=el('input');enable.type='checkbox';enable.checked=s.enabled;enable.setAttribute('aria-label','保留第'+(index+1)+'页');enable.onchange=()=>{s.enabled=enable.checked;dirty=true};
      const label=el('strong','第 '+(index+1)+' 页');
      const layout=el('select');layout.setAttribute('aria-label','版式');Object.entries(layouts).forEach(([v,t])=>layout.append(new Option(t,v)));layout.value=s.layout;layout.onchange=()=>{s.layout=layout.value;if(s.layout==='research')s.research??={id:'manual-'+Date.now(),question:'',claim:'',content:s.bullets.join('\n'),limitation:'',chart_ids:[],columns:[],rows:[],binding_confirmed:false};dirty=true;draw()};
      const chapter=el('select');chapter.setAttribute('aria-label','来源章节');for(let n=0;n<=10;n++)chapter.append(new Option(n?'第'+n+'章':'摘要',n));chapter.value=s.chapter;chapter.onchange=()=>{s.chapter=Number(chapter.value);s.chart_id=null;if(s.research){s.research.chart_ids=[];s.research.binding_confirmed=false}dirty=true;draw()};
      const up=el('button','上移','secondary-action'),down=el('button','下移','secondary-action'),remove=el('button','删除页','danger-action');
      up.disabled=index===0;down.disabled=index===job.slides.length-1;
      up.onclick=()=>{[job.slides[index-1],job.slides[index]]=[s,job.slides[index-1]];dirty=true;draw()};
      down.onclick=()=>{[job.slides[index+1],job.slides[index]]=[s,job.slides[index+1]];dirty=true;draw()};
      remove.onclick=()=>{job.slides.splice(index,1);dirty=true;draw()};top.append(enable,label,layout,chapter,up,down,remove);
      const title=el('input');title.value=s.title;title.maxLength=44;title.setAttribute('aria-label','页面标题');title.oninput=()=>{s.title=title.value;dirty=true};
      const points=el('textarea');points.value=s.bullets.join('\n');points.rows=6;points.setAttribute('aria-label','每行一条要点');points.placeholder='每行一条要点，可包含结论、依据和条件。普通页最多四条、每条110字；图表页最多三条、每条65字';points.oninput=()=>{s.bullets=points.value.split('\n').filter(x=>x.trim());dirty=true};
      const charts=el('select');charts.setAttribute('aria-label','本章图表');charts.append(new Option('不使用图表',''));for(const c of job.charts.filter(x=>x.chapter_no===s.chapter))charts.append(new Option(c.title+'（'+c.unit+'）',c.id));charts.value=s.chart_id||'';charts.onchange=()=>{s.chart_id=charts.value||null;if(s.chart_id){s.layout='chart';layout.value='chart'}dirty=true};
      const source=el('details'),sourceTitle=el('summary','核对原报告章节');source.append(sourceTitle);const text=el('pre',job.source_chapters?.find(c=>c.chapter_no===s.chapter)?.content||'');source.append(text);
      card.append(top,title);
      if(s.layout==='research'&&s.research){
        const b=s.research;
        for(const [key,label,max] of [['question','研究问题（仅用于编辑，不印在页面）',160],['claim','核心判断（可选，须有证据支持）',140],['content','原文与分析（纯文字页最多520字；图表页180字）',520],['limitation','适用条件与数据缺口',120]]){
          const field=el('textarea');field.rows=key==='content'?8:2;field.value=b[key]||'';field.maxLength=max;field.setAttribute('aria-label',label);field.oninput=()=>{b[key]=field.value;b.binding_confirmed=false;dirty=true};card.append(el('label',label),field);
        }
        const picker=el('fieldset');picker.append(el('legend','绑定图表（最多两张，按出处核对，不按章节自动猜测）'));
        for(const c of job.charts.filter(c=>c.chapter_no===s.chapter)){
          const item=el('label'),check=el('input');check.type='checkbox';check.checked=b.chart_ids.includes(c.id);
          check.onchange=()=>{if(check.checked&&b.chart_ids.length>=2){check.checked=false;return}b.chart_ids=check.checked?[...b.chart_ids,c.id]:b.chart_ids.filter(id=>id!==c.id);b.binding_confirmed=false;dirty=true};
          item.append(check,document.createTextNode(c.title+'（'+c.unit+'）'));picker.append(item);
          const detail=el('details');detail.append(el('summary','核对指标、时间、数值与出处'),el('pre',JSON.stringify(job.datasets?.find(d=>d.id===c.id)||{labels:c.labels,values:c.values,source_excerpts:c.source_excerpts,note:c.note},null,2)));picker.append(detail);
        }
        const confirmBinding=el('input');confirmBinding.type='checkbox';confirmBinding.checked=b.binding_confirmed;confirmBinding.onchange=()=>{b.binding_confirmed=confirmBinding.checked;dirty=true};const bindingLabel=el('label');bindingLabel.append(confirmBinding,document.createTextNode('已核对图表与本页论点、范围、单位及时间一致'));picker.append(bindingLabel);card.append(picker);
        const table=el('textarea');table.rows=6;table.value=b.columns.length?[b.columns,...b.rows].map(r=>r.join('\t')).join('\n'):'';table.placeholder='第一行为表头，单元格用Tab分隔；最多5列、5行数据。留空不使用表格';table.setAttribute('aria-label','比较表数据');table.oninput=()=>{const rows=table.value.split('\n').filter(r=>r.trim()).map(r=>r.split('\t'));b.columns=rows.shift()||[];b.rows=rows;dirty=true};card.append(el('label','比较表（可从Excel粘贴）'),table);
      }else card.append(points,charts);
      card.append(source);editor.append(card);
      card.querySelectorAll('input,textarea,select,button').forEach(n=>{if(busy)n.disabled=true});
    });
    if(dirty)markDirty();
    if(job.status==='complete'&&!dirty){
      const link=el('a','下载可编辑 PPTX','download-report');link.href=base+'/'+job.id+'/download';previews.append(link);
      for(let i=1;i<=job.preview_count;i++){const img=el('img');img.loading='lazy';img.alt='第'+i+'页预览';img.src=base+'/'+job.id+'/slides/'+i;previews.append(img)}
    }
  }
  async function poll(){if(!dialog.open||!job?.id)return;try{const next=await request(base+'/'+job.id);if(!next||!Array.isArray(next.slides))throw Error('PPT 任务未加载成功，请重新选择已保存的 PPT 任务');job=next;draw();if(['planning','rendering'].includes(job.status))timer=setTimeout(poll,1500);else await refreshHistory()}catch(e){fail(e)}}
  async function persist(){
    if(!ready())throw Error('请先点击“生成新大纲”，或在右侧打开已保存的 PPT 任务');
    for(const [index,s] of job.slides.entries()){
      if(!s.enabled||s.layout==='research')continue;
      const limit=job.point_limits?.[s.layout]??(s.layout==='chart'?65:110);
      const bad=s.bullets.findIndex(p=>Array.from(p).length>limit);
      if(bad!==-1){
        const field=editor.children[index]?.querySelector('textarea');field?.scrollIntoView({block:'center'});field?.focus();
        throw Error(`第${index+1}页「${s.title}」第${bad+1}条要点有${Array.from(s.bullets[bad]).length}字，最多${limit}字。请精简，或取消保留该页。`);
      }
    }
    job=await request(base+'/'+job.id,{method:'PUT',body:JSON.stringify({revision:job.revision,slides:job.slides})});dirty=false;draw();
  }
  save.onclick=async()=>{save.disabled=true;try{await persist()}catch(e){fail(e)}};
  generate.onclick=async()=>{generate.disabled=true;try{await persist();job=await request(base+'/'+job.id+'/export',{method:'POST'});draw();await poll()}catch(e){fail(e)}};
  add.onclick=()=>{if(!ready()){fail(Error('请先生成或打开 PPT 大纲'));return}if(job.slides.length>=120)return;job.slides.push({chapter:1,title:'新增分析页',layout:'conclusions',bullets:[],chart_id:null,enabled:true});dirty=true;draw()};
  create.onclick=async()=>{if(create.disabled||creating)return;if(dirty&&!confirm('当前大纲尚未保存，确定新建任务？'))return;creating=true;syncActions();try{clearTimeout(timer);job=await request(base,{method:'POST',body:JSON.stringify({version_id:version.value||null,ai:ai.checked,mode:mode.value})});dirty=false;await poll()}catch(e){fail(e)}finally{creating=false;syncActions()}};
  history.onchange=async()=>{if(!history.value)return;if(dirty&&!confirm('当前修改尚未保存，确定切换？'))return;clearTimeout(timer);job={id:history.value};dirty=false;draw();status.textContent='正在加载 PPT 大纲…';await poll()};
  try{const versions=await request(`/api/industry/projects/${projectId}/versions`);for(const v of versions)version.append(new Option(new Date(v.created).toLocaleString()+' '+v.reason,v.id));await refreshHistory()}catch(e){fail(e)}
};
})();
