if(location.pathname!=='/industry'){
 const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n};
 const key=s=>s.normalize('NFKC').replace(/\s+/g,'').toLowerCase().replace(/\.docx$/i,'');
 const d=el('dialog');d.className='upload-dialog batch-dialog';
 d.innerHTML='<h2>批量上传企业报告</h2><p>① 选择文件并自动识别名称 → ② 集中核对、修改 → ③ 名称与内容查重后入库。支持 .docx，每份最多 50 MB。名称预览只在本机暂存24小时，不会切片或写入知识库。</p><p>同一企业下报告名称不能重复。相似度阈值越低，拦截越严格；90% 为试用默认值，可逐份调整。完全重复的内容始终拦截。</p><p>比较正文和表格，降低共有模板的影响；图片只比较文件指纹，尚未比较图片中的文字。相似度不是重复概率。</p><p>快速检查先找疑似报告，可能漏掉部分相似资料；严格检查逐份比较全库，更稳妥但较慢。两种模式都会检查完全重复。</p><label>同时处理份数<select class="parallelism" aria-label="同时处理份数"><option value="1">1 份（顺序处理）</option><option value="2">2 份</option><option value="3" selected>3 份（推荐）</option></select></label><input type="file" multiple accept=".docx" aria-label="选择多个报告"><p class="review-summary" role="status"></p><button class="sort-names" type="button">按名称重新分组排序</button><label>核对范围<select class="name-filter" aria-label="核对范围"><option value="all">全部文件</option><option value="same">相同名称的文件</option><option value="review">识别结果需核对</option></select></label><div class="batch-overall" hidden><progress max="100" value="0"></progress><span>等待开始</span></div><div class="batch-rows"></div><p role="status" class="batch-status"></p><div class="report-actions"><button class="close">关闭</button><button class="submit">已核对名称，开始查重入库</button></div>';
 document.body.append(d);
 let rows=[],busy=false,reports=[];
 const file=d.querySelector('input'),host=d.querySelector('.batch-rows'),status=d.querySelector('.batch-status');
 async function api(path,options){const res=await fetch(path,options);const body=await res.json();if(!res.ok)throw body.detail||{message:'请求失败'};return body}
 for(const tabs of document.querySelectorAll('.knowledge-tabs')){const b=el('button','＋ 批量上传');b.type='button';b.className='upload-open';b.onclick=async()=>{d.showModal();try{reports=await api('/api/manage/reports');for(const r of rows)updateTargets(r)}catch(e){status.textContent='已有报告列表读取失败，请关闭后重新打开。'}};tabs.append(b)}
 d.querySelector('.close').onclick=()=>{if(!busy){d.close();if(rows.some(r=>r.done))location.reload()}};
 d.oncancel=e=>{e.preventDefault();if(!busy)d.querySelector('.close').click()};
 function updateTargets(r){const selected=r.target.value;r.target.replaceChildren();const first=el('option','新增一份报告');first.value='';r.target.append(first);for(const p of reports.filter(p=>!p.deleted&&key(p.company)===key(r.company.value))){const opt=el('option','更新已有报告：'+p.title);opt.value=p.id;r.target.append(opt)}r.target.value=selected;if(r.target.selectedIndex<0)r.target.value=''}
 function names(r){return {company_name:r.company.value.trim(),report_title:r.title.value.trim(),replace_document_id:r.target.value||null}}
 const overallBox=d.querySelector('.batch-overall'),overallBar=overallBox.querySelector('progress'),overallText=overallBox.querySelector('span');
 function progress(r,percent,stage){r.progress=Math.max(0,Math.min(100,Number(percent)||0));r.progressBox.hidden=false;r.progressBar.value=r.progress;r.progressText.textContent=`${Math.round(r.progress)}% · ${stage}`;const active=rows.filter(x=>x.token&&!x.done);const total=rows.filter(x=>x.token);const value=total.length?total.reduce((sum,x)=>sum+(x.done?100:(x.progress||0)),0)/total.length:0;overallBox.hidden=false;overallBar.value=value;overallText.textContent=`整体进度 ${Math.round(value)}% · ${total.filter(x=>x.done).length} / ${total.length} 份已入库`}
 const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 async function waitJob(jobId,r){let failures=0;while(true){let job;try{job=await api('/api/uploads/jobs/'+jobId);failures=0}catch(e){if(++failures>=3)throw e;await delay(800);continue}progress(r,job.percent,job.stage);if(job.status==='complete')return job.result;if(job.status==='failed')throw job.error||'后台处理失败';await delay(450)}}
 function showError(r,error){r.state.replaceChildren(el('p',typeof error==='string'?error:error.message||'请检查填写内容'));
  if(error.check)r.state.append(el('p',`本次精确比较 ${error.check.candidates} / ${error.check.documents} 份原文。`));
  for(const match of error.matches||[]){const box=el('div');box.className='duplicate-match';box.append(el('strong',match.company+' / '+match.title),el('p',(match.similarity===undefined?'':`原文相似度 ${match.similarity}% · `)+(match.deleted?'位于回收站':'已入库')));
   if(match.tables_changed)box.append(el('p','表格文字或单元格排列有变化，请核对原表。'));
   if(match.images_changed)box.append(el('p','图片或图表文件有变化，尚未识别其中的文字差异。'));
   for(const change of match.differences||[]){const diff=el('details');diff.append(el('summary','查看一处文字差异'),el('p','已有原文：'+(change.before||'（无）')),el('p','本次上传：'+(change.after||'（无）')));box.append(diff)}
   if(error.code!=='exact_duplicate'&&error.code!=='version_review'&&!match.deleted&&key(match.company)===key(r.company.value)){const pick=el('button','选择更新这份报告');pick.type='button';pick.disabled=busy;pick.onclick=()=>{if(!reports.some(p=>p.id===match.id))reports.push(match);updateTargets(r);r.target.value=match.id;r.confirmUpdate=false;r.state.replaceChildren(el('p','已选择更新目标。再次点击“已核对名称，开始查重入库”可查看新旧差异。'))};box.append(pick)}r.state.append(box)
  }
  if(error.code==='version_review'){const confirm=el('button','已核对差异，确认更新');confirm.type='button';confirm.disabled=busy;confirm.onclick=()=>{r.confirmUpdate=true;r.state.replaceChildren(el('p','已确认更新目标，请点击底部“已核对名称，开始查重入库”完成保存。'))};r.state.append(confirm)}
 }
 function sortNames(){
  const companies=new Map(),pairs=new Map(),titles=new Map();
  for(const r of rows){const c=key(r.company.value),t=key(r.title.value),p=c+'\0'+t;companies.set(c,(companies.get(c)||0)+1);titles.set(t,(titles.get(t)||0)+1);pairs.set(p,(pairs.get(p)||0)+1)}
  for(const r of rows){const c=key(r.company.value),t=key(r.title.value),n=pairs.get(c+'\0'+t);r.grouped=(companies.get(c)>1||titles.get(t)>1);r.flag.textContent=n>1?`同一企业下同名报告共 ${n} 份，全部保留，请核对是否修改或更新已有报告。`:r.grouped?'同企业或同报告名的文件已排在一起，未合并或删除。':'';r.box.classList.toggle('duplicate-name',n>1)}
  const ordered=[...rows].sort((a,b)=>Number(a.grouped)-Number(b.grouped)||key(a.company.value).localeCompare(key(b.company.value),'zh-CN')||key(a.title.value).localeCompare(key(b.title.value),'zh-CN')||a.order-b.order);
  for(const r of ordered)host.append(r.box);applyFilter();
  d.querySelector('.review-summary').textContent=`共 ${rows.length} 份；${rows.filter(r=>r.token).length} 份已读取，${rows.filter(r=>r.needsReview).length} 份识别结果需重点核对。同名项排在后面，所有文件均保留。`;
 }
 function applyFilter(){const value=d.querySelector('.name-filter').value;for(const r of rows)r.box.hidden=value==='same'?!r.grouped:value==='review'?!r.needsReview:false}
 d.querySelector('.name-filter').onchange=applyFilter;
 d.querySelector('.sort-names').onclick=sortNames;
 async function recognize(){busy=true;for(const input of d.querySelectorAll('input,select,button'))input.disabled=true;let cursor=0,finished=0;const parallelism=Number(d.querySelector('.parallelism').value);
  async function worker(){while(cursor<rows.length){const r=rows[cursor++];r.state.textContent='正在读取文件、识别名称…';try{if(r.file.size>50*1024*1024)throw '文件超过50 MB';const body=new FormData();body.append('file',r.file);const info=await api('/api/uploads/preview',{method:'POST',body});r.token=info.token;r.company.value=info.company_name;r.title.value=info.report_title;r.needsReview=info.needs_review;r.recognition.textContent=info.reason+(info.candidates.length>1?'；候选企业：'+info.candidates.join(' / '):'');r.state.textContent='已暂存，等待你核对名称。';updateTargets(r)}catch(e){r.needsReview=true;showError(r,e)}finally{finished++;status.textContent=`名称识别进度 ${finished} / ${rows.length}；全部完成后可集中核对。`}}}
  try{await Promise.all(Array.from({length:Math.min(parallelism,rows.length)},()=>worker()))}finally{busy=false;for(const input of d.querySelectorAll('input,select,button'))input.disabled=false;sortNames();status.textContent='名称识别完成。请核对或修改下方名称，确认后点击“已核对名称，开始查重入库”。尚未进行名称去重、内容查重或切片。'}
 }
 file.onchange=()=>{d.querySelector('.name-filter').value='all';rows=[];host.replaceChildren();status.textContent='';overallBox.hidden=true;overallBar.value=0;for(const f of file.files){const box=el('div');box.className='batch-row';box.append(el('h3',`文件 ${rows.length+1} · ${f.name}`));const company=el('input'),title=el('input'),threshold=el('input'),mode=el('select'),target=el('select'),state=el('div'),recognition=el('p'),flag=el('p'),progressBox=el('div'),progressBar=el('progress'),progressText=el('span');for(const [value,label] of [['fast','快速检查：先筛选疑似报告'],['strict','严格检查：比较全部原文']]){const o=el('option',label);o.value=value;mode.append(o)}
  company.maxLength=title.maxLength=120;company.placeholder='请填写企业全称';title.value=f.name.replace(/\.docx$/i,'');threshold.type='number';threshold.min='50';threshold.max='99.9';threshold.step='0.1';threshold.value='90';
  const options=el('details');options.className='upload-options';options.append(el('summary','查重与版本选项（默认快速检查、90%阈值、新增报告）'));
  for(const [label,input] of [['企业名称',company],['报告名称',title],['相似度拦截阈值（%）',threshold],['查重方式',mode],['保存方式',target]]){const l=el('label',label);input.setAttribute('aria-label',f.name+' · '+label);l.append(input);if(input===company||input===title)box.append(l);else options.append(l)}box.append(options);
  progressBox.className='upload-progress';progressBox.hidden=true;progressBar.max=100;progressBar.value=0;progressBox.append(progressBar,progressText);box.append(recognition,flag,progressBox,state);host.append(box);const r={file:f,box,company,title,threshold,mode,target,state,recognition,flag,progressBox,progressBar,progressText,progress:0,token:null,needsReview:false,order:rows.length,done:false,failed:false,confirmUpdate:false,serial:0};rows.push(r);updateTargets(r);
  for(const input of [company,title,threshold,mode,target])input.onchange=()=>{r.confirmUpdate=false;r.serial++;if(input===company)updateTargets(r);r.flag.textContent='名称已修改，可点击上方按钮重新分组；确认后再检查是否重名。'};
 }void recognize();};
 d.querySelector('.submit').onclick=async()=>{if(busy)return;if(!rows.length){status.textContent='请先选择报告。';return}
  const parallelism=Number(d.querySelector('.parallelism').value);
  busy=true;for(const r of rows)r.serial++;for(const input of d.querySelectorAll('input,select,button'))input.disabled=true;
  let added=0,failed=0;
  try{const counts=new Map();for(const r of rows.filter(r=>!r.done)){const k=key(r.company.value)+'\0'+key(r.title.value);counts.set(k,(counts.get(k)||0)+1)}
   const pending=rows.filter(r=>!r.done);let cursor=0,completed=0;
   if(!pending.length){status.textContent=`全部可入库文件已处理完成：累计成功 ${rows.filter(r=>r.done).length} 份，未入库 ${rows.filter(r=>r.failed&&!r.done).length} 份。`;return}
   for(const r of pending){r.failed=false;r.progress=0;r.state.replaceChildren(el('p','排队等待处理…'));progress(r,0,'排队等待处理')}
   async function worker(){while(cursor<pending.length){const r=pending[cursor++];status.textContent=`已完成 ${completed} / ${pending.length}，最多同时处理 ${parallelism} 份，请勿关闭页面`;r.state.replaceChildren(el('p','正在检查名称…'));
    try{const n=names(r),threshold=Number(r.threshold.value);if(n.company_name.length<2||n.report_title.length<2)throw '企业名称和报告名称至少填写两个字';if(!r.threshold.value||!Number.isFinite(threshold)||threshold<50||threshold>99.9)throw '相似度阈值须在50%～99.9%之间';if(counts.get(key(r.company.value)+'\0'+key(r.title.value))>1)throw '本批次存在相同企业、相同报告名称，请先修改名称';
     await api('/api/uploads/check-name',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(n)});
     if(!r.token)throw '文件读取失败，尚未暂存，请重新选择有效文件';r.state.replaceChildren(el('p','后台任务已提交，正在检查重复…'));
     const started=await api('/api/uploads/commit/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...n,token:r.token,similarity_threshold:threshold,check_mode:r.mode.value,confirm_update:r.confirmUpdate})});const saved=await waitJob(started.job_id,r);r.done=true;added++;progress(r,100,'已完成');r.state.replaceChildren(el('p',r.target.value?'新版已保存，旧版已移入回收站。':'检查通过，已加入知识库。'));if(saved.check)r.state.append(el('p',`本次精确比较 ${saved.check.candidates} / ${saved.check.documents} 份原文。`));
    }catch(e){r.failed=true;failed++;progress(r,100,'未入库');showError(r,e)}finally{completed++;status.textContent=`已完成 ${completed} / ${pending.length}，新增 ${added} 份，未入库 ${failed} 份`;}
   }}
   await Promise.all(Array.from({length:Math.min(parallelism,pending.length)},()=>worker()));
   try{reports=await api('/api/manage/reports')}catch{}
   status.textContent=`处理完成：累计成功 ${rows.filter(r=>r.done).length} 份，当前未入库 ${rows.filter(r=>r.failed&&!r.done).length} 份。请处理各文件下方提示后重试，已成功项不会再次提交。`;
  }finally{busy=false;for(const input of d.querySelectorAll('input,select,button'))input.disabled=false;for(const r of rows.filter(r=>r.done))for(const input of r.box.querySelectorAll('input,select,button'))input.disabled=true}
 };
}
