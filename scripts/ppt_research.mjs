// Native, editable research pages. No model calls and no image-based charts.
import {wrapText} from './ppt_layouts.mjs';
export function renderResearch(slide,page,index,context){
  const {text,job,chartOwners,tableOwners,font,ink,green,gray,applyChartFont}=context;
  const block=page.research;if(!block)throw Error('研究页缺少内容块');
  function fit(value,x,y,w,h,max=26,min=22){
    value=String(value).replace(/\n\s*\n/g,'\n').replace(/^\s*[-*+]\s+/gm,'');
    let size=max;
    while(size>min&&wrapText(value,Math.max(1,Math.floor((w-28)/(size*1.15)))).split('\n').length*size*1.35>h)size--;
    text(slide,value,x,y,w,h,size,ink);
  }
  const charts=block.chart_ids.map(id=>{
    const spec=job.snapshot.charts.find(c=>c.id===id&&c.chapter_no===page.chapter);
    if(!spec)throw Error('研究页引用了不存在或跨章节的图表');return spec;
  });
  let top=174;
  if(block.claim){fit(block.claim,64,top,1152,104,28);top+=110;}
  if(charts.length){
    if(block.content){fit(block.content,64,top,1152,140,24);top+=144;}
    const width=charts.length===2?554:1152;
    charts.forEach((spec,i)=>{
      const x=64+i*598;
      fit(`图 ${index+1}-${i+1}  ${spec.title}（${spec.unit}）`,x,top,width,60,20,18);
      if(!spec.values.length||spec.values.length!==spec.labels.length)throw Error('图表标签与数值数量不一致');
      if(spec.values.length===1){fit(`${spec.labels[0]}：${spec.values[0]} ${spec.unit}`,x,top+90,width,120,32);return;}
      const type=['bar','column'].includes(spec.selected_type)?'bar':spec.selected_type==='area'?'area':spec.selected_type==='pie'?'pie':spec.selected_type==='scatter'?'scatter':'line';
      if(type==='pie'&&(spec.values.some(v=>v<0)||Math.abs(spec.values.reduce((a,b)=>a+b,0)-100)>.5))throw Error('饼图必须是经核对的完整占比');
      const chart=slide.charts.add(type,{position:{left:x,top:top+66,width,height:Math.max(130,604-top-66)},
        categories:spec.labels,series:[{name:spec.unit,values:spec.values,fill:green,...(type==='scatter'?{xValues:spec.labels.map(Number)}:{})}],hasLegend:type==='pie',
        barOptions:{direction:spec.selected_type==='bar'?'bar':'column',grouping:'clustered'},
        dataLabels:{showValue:true,textStyle:{typeface:font,fontSize:16}},
        xAxis:{textStyle:{typeface:font,fontSize:16}},yAxis:{textStyle:{typeface:font,fontSize:16}}});
      applyChartFont(chart,{fontFamily:font});if(!chartOwners.includes(index+1))chartOwners.push(index+1);
    });
  }else if(block.rows.length){
    if(block.content){fit(block.content,64,top,1152,90,23);top+=94;}
    const values=[block.columns,...block.rows],w=1152/block.columns.length;
    const size=block.columns.length>3?20:23;
    const wrapped=values.map(row=>row.map(v=>wrapText(v,Math.max(1,Math.floor((w-30)/(size*1.15))))));
    const heights=wrapped.map(row=>Math.max(48,...row.map(v=>v.split('\n').length*size*1.35+14)));
    if(heights.reduce((a,b)=>a+b,0)>640-top)throw Error('比较表内容过密，请拆分行或缩短单元格，原文未删除');
    const table=slide.tables.add({rows:values.length,columns:block.columns.length,left:64,top,width:1152,height:heights.reduce((a,b)=>a+b,0),values:wrapped,columnWidths:block.columns.map(()=>w)});
    table.borders.assign({fill:'#DCE5E0',width:1,style:'solid'});
    heights.forEach((h,r)=>{table.rows[r].height=h;values[r].forEach((_,c)=>{
      const cell=table.getCell(r,c);cell.fill=r===0?green:r%2?'#FFFFFF':'#F3F6F4';
      cell.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':ink,bold:r===0};
    });});tableOwners.push(index+1);
  }else{
    const body=block.content.replace(/\n\s*\n/g,'\n').replace(/^\s*[-*+]\s+/gm,'');
    let size=body.length<260?32:26;
    const height=block.limitation?550-top:638-top;
    const linesAt=size=>body.split('\n').flatMap(line=>wrapText(line,Math.floor((1152-28)/(size*1.15))).split('\n').map(t=>({t,bold:line.length<=24&&!/[。！？：:，,\[\]]/.test(line)})));
    while(size>22&&linesAt(size).length*size*1.35>height)size--;
    const lines=linesAt(size);
    if(lines.length*size*1.35>height)throw Error('研究内容块过密，请拆页保留完整正文');
    lines.forEach((line,i)=>text(slide,line.t,64,top+i*size*1.35,1152,size*1.35,size,line.bold?green:ink,line.bold));
  }
  if(block.limitation)fit('适用条件：'+block.limitation,64,610,1152,44,18,16);
}
