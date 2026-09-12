import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {compositionVariants,compositionPlan,wrapText,pointNumber} from './ppt_layouts.mjs';
import {renderResearch} from './ppt_research.mjs';

const job=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
process.env.RUNTIME_NODE_MODULES=path.resolve(path.dirname(job.runtime.module),'../../..');
const {Presentation,PresentationFile}=await import(pathToFileURL(job.runtime.module).href);
const {applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(path.join(job.runtime.skill,'container_tools/artifact_tool_utils.mjs')).href);
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const FONT='Microsoft YaHei', INK='#18342D', GREEN='#27654F', GRAY='#63746D';
const enabled=job.slides.filter(s=>s.enabled), chartOwners=[],tableOwners=[],slides=[];
const variants=compositionVariants(job.slides);
const compositions=compositionPlan(job.slides);

function wrap(value,max){
  return wrapText(value,max);
}
function fitted(slide,value,x,y,w,h,max=34,color=INK,bold=false){
  let size=max;
  while(size>24&&wrap(value,Math.max(1,Math.floor((w-28)/(size*1.15)))).split('\n').length*size*1.35>h-14)size--;
  return text(slide,value,x,y,w,h,size,color,bold);
}
function editorial(slide,points,kind){
  const n=points.length;
  if(!n)return;
  if(kind==='lead'){
    text(slide,'01',64,182,90,55,32,GREEN,true);
    fitted(slide,points[0],64,248,420,380,38,GREEN,true);
    const height=444/(n-1);
    points.slice(1).forEach((p,i)=>{
      text(slide,pointNumber(i+1),558,182+i*height,62,48,27,GREEN,true);
      fitted(slide,p,632,182+i*height,580,height-12,32);
    });return;
  }
  points.forEach((p,i)=>{
    if(kind==='columns'){
      const stride=1180/n,w=stride-34,x=64+i*stride;
      text(slide,pointNumber(i),x,184,w,66,42,GREEN,true);
      fitted(slide,p,x,272,w,360,32);return;
    }
    if(kind==='matrix'){
      const x=64+(i%2)*590,y=180+Math.floor(i/2)*228;
      text(slide,pointNumber(i),x,y,65,48,28,GREEN,true);
      fitted(slide,p,x+74,y,490,214,34);return;
    }
    const height=456/n,y=178+i*height;
    const match=kind==='timeline'?p.match(/^([^：:]{1,22})[：:](.*)$/s):null;
    fitted(slide,match?match[1]:pointNumber(i),64,y,match?232:65,height-12,match?28:32,GREEN,true);
    fitted(slide,match?match[2]:p,match?326:152,y,match?886:1060,height-12,32);
  });
}
function text(slide,value,x,y,w,h,size=28,color=INK,bold=false){
  const s=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  const content=/^\d{1,2}$/.test(String(value))?String(value):wrap(value,Math.max(1,Math.floor((w-28)/(size*1.15))));
  if(content.split('\n').length*size*1.35>h)throw Error('文字超出固定版式，请拆页或缩短：'+String(value).slice(0,35));
  s.text=content;s.text.style={typeface:FONT,fontSize:size,color,bold,autoFit:'none'};
  return s;
}
function footer(slide,index,page){
  text(slide,page.chapter?`来源：报告第${page.chapter}章，原文与出处见备注`:'来源：报告摘要，原文见备注',64,662,1030,30,15,GRAY);
  text(slide,String(index+1).padStart(2,'0'),1150,655,65,40,20,GRAY);
}
function table(slide,page,index,variant){
  const rows=page.bullets.map((p,i)=>{
    const at=p.search(/[：:]/);
    return at>0&&at<15?[p.slice(0,at),p.slice(at+1)]:['要点 '+(i+1),p];
  });
  if(!rows.length){text(slide,'本页暂无要点',64,220,1000,80);return}
  const compact=page.bullets.some(p=>p.length>90),bodySize=compact?23:26,bodyWidth=compact?38:32;
  const values=[[page.layout==='risk'?'风险事项':'比较项目','报告要点'],...rows].map(row=>variant?[row[1],row[0]]:row);
  const t=slide.tables.add({rows:values.length,columns:2,left:64,top:176,width:1152,height:468,
    columnWidths:variant?[950,202]:[202,950],values:values.map(row=>row.map((v,i)=>wrap(v,i===(variant?1:0)?6:bodyWidth)))});
  t.borders.assign({fill:'#DCE5E0',width:1,style:'solid'});
  t.rows[0].height=48;
  for(let r=1;r<values.length;r++){
    const lines=Math.max(...values[r].map((v,c)=>wrap(v,c===(variant?1:0)?6:bodyWidth).split('\n').length));
    t.rows[r].height=Math.max(96,lines*(bodySize*1.35)+12);
  }
  for(let r=0;r<values.length;r++)for(let c=0;c<2;c++){
    const cell=t.getCell(r,c);cell.fill=r===0?(page.layout==='risk'?'#8C4B36':GREEN):(r%2?'#FFFFFF':'#F3F6F4');
    cell.text.style={typeface:FONT,fontSize:r===0?25:bodySize,bold:r===0||c===(variant?1:0),color:r===0?'#FFFFFF':INK};
  }
  tableOwners.push(index+1);
}
for(const [index,page] of enabled.entries()){
  const variant=variants[index];
  const slide=deck.slides.add();slides.push(slide);slide.background.fill='#FFFFFF';
  const chapter=job.snapshot.project.chapters.find(c=>c.chapter_no===page.chapter);
  const sources=job.snapshot.evidence.filter(e=>e.chapter_no===page.chapter);
  slide.speakerNotes.textFrame.setText((chapter?.content||'')+'\n\n章节资料（编号请以原报告核对）：\n'+sources.map(e=>`${e.title}\n${e.url||''}`).join('\n'));
  if(page.layout==='cover'){
    slide.background.fill=INK;
    text(slide,'行业研究',68,120,1000,60,25,'#A9C9B9');
    text(slide,page.title,64,230,1130,185,56,'#FFFFFF',true);
    const brief=job.snapshot.project.brief;
    text(slide,`${brief.geography||''}  ${brief.history_start||''}—${brief.history_end||''}`,68,470,1100,70,27,'#A9C9B9');
    text(slide,'CKOS 企业研究工作台',68,600,900,40,20,'#A9C9B9');continue;
  }
  text(slide,page.chapter?`第${page.chapter}章`:'研究结论',64,34,1100,35,18,GREEN);
  text(slide,page.title,60,80,1160,104,42,INK,true);
  if(page.layout==='research')renderResearch(slide,page,index,{text,job,chartOwners,tableOwners,font:FONT,ink:INK,green:GREEN,gray:GRAY,applyChartFont:applyPresentationChartFont});
  else if(compositions[index]==='table')table(slide,page,index,0);
  else if(page.layout!=='chart')editorial(slide,page.bullets,compositions[index]);
  else if(page.layout==='chart'){
    const wide=page.bullets.length<=2&&!variant;
    const chartX=variant?564:60,notesX=variant?64:740;
    const spec=job.snapshot.charts.find(c=>c.id===page.chart_id);
    if(!spec)throw Error('图表数据不在报告快照中');
    if(spec.labels.length>10)throw Error('图表超过10个数据点，请在大纲选择更精简的图表');
    text(slide,'单位：'+spec.unit,wide?64:chartX,183,690,34,18,GRAY);
    if(spec.values.length===1){
      text(slide,String(spec.values[0])+' '+spec.unit,chartX+8,270,634,110,64,GREEN,true);
      text(slide,spec.labels[0],chartX+8,400,634,130,28);
    }else{
      let type=['bar','column'].includes(spec.selected_type)?'bar':spec.selected_type==='area'?'area':'line';
      if(spec.selected_type==='scatter')type='scatter';
      const chart=slide.charts.add(type,{position:{left:wide?60:chartX,top:230,width:wide?1152:650,height:wide?285:366},
        categories:spec.labels,series:[{name:spec.unit,values:spec.values,fill:GREEN,
        ...(type==='scatter'?{xValues:spec.labels.map(Number)}:{})}],
        hasLegend:false,barOptions:{direction:spec.selected_type==='bar'?'bar':'column',grouping:'clustered'},
        scatterOptions:{style:'marker'},dataLabels:{showValue:true,textStyle:{typeface:FONT,fontSize:18}},
        xAxis:{textStyle:{typeface:FONT,fontSize:18}},yAxis:{textStyle:{typeface:FONT,fontSize:18},numberFormatCode:'General'}});
      applyPresentationChartFont(chart,{fontFamily:FONT});chartOwners.push(index+1);
    }
    page.bullets.forEach((p,i)=>wide
      ?text(slide,p,64+i*585,540,555,104,23)
      :text(slide,p,notesX,210+i*140,465,134,23));
  }
  footer(slide,index,page);
}
const candidate=path.join(job.output,'candidate.pptx');
await fs.mkdir(path.join(job.output,'output'),{recursive:true});
await (await PresentationFile.exportPptx(deck)).save(candidate);
await finalizePresentation({workspaceDir:job.output,candidatePath:candidate,finalPath:path.join(job.output,'output/report.pptx'),
  pythonExecutable:job.runtime.python,
  integrityValidatorPath:path.join(job.runtime.skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(job.runtime.skill,'container_tools/inspect_presentation_layout_geometry.py'),
  explicitTotalSlideCount:enabled.length,requiredNativeChartOwnerSlides:chartOwners,requiredNativeTableOwnerSlides:tableOwners,
  materializeLiteralChartWorkbooks:true,verifyArtifactToolImport:true,
  fontPolicy:{basis:'design',families:[FONT]},
  layoutArgs:['--expected-slide-size-emu','12192000,6858000',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],
  receiptPath:path.join(job.output,'validation.json')});
for(let i=0;i<enabled.length;i++){
  const blob=await deck.export({slide:slides[i],format:'png',scale:1});
  await fs.writeFile(path.join(job.output,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));
}
await fs.writeFile(path.join(job.output,'manifest.json'),JSON.stringify({count:enabled.length}));
console.log('PPT exported:',enabled.length,'slides');
