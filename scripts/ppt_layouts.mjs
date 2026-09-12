// Deterministic composition scheduling, based on exported (enabled) pages.
// Comparison and risk share a table family and therefore alternate together.
export function compositionVariants(pages){
  let previous=null,variant=0;
  return pages.filter(page=>page.enabled).map(page=>{
    const family=['comparison','risk'].includes(page.layout)?'table':page.layout;
    variant=family===previous?1-variant:0;
    previous=family;
    return variant;
  });
}
export const pointNumber=index=>String(index+1).padStart(2,'0');

// Keep variety across the whole deck, not only consecutive pages of one type.
export function compositionPlan(pages){
  const used=new Map();let previous='';
  return pages.filter(p=>p.enabled).map(p=>{
    let candidates;
    if(p.layout==='cover'||p.layout==='chart')candidates=[p.layout];
    else if(p.chapter===2&&p.bullets.filter(s=>/^\d{4}/.test(s)).length>=2)candidates=['timeline'];
    else if(p.layout==='risk')candidates=['rows','matrix'];
    else if(p.layout==='comparison')candidates=['columns','table','matrix'];
    else candidates=['lead','matrix','columns','rows'];
    if(p.bullets.length<2||p.bullets.slice(1).some(s=>s.length>80))candidates=candidates.filter(s=>s!=='lead');
    if(p.bullets.length>=4&&p.bullets.some(s=>s.length>80))candidates=candidates.filter(s=>s!=='columns');
    if(p.bullets.some(s=>s.length>100))candidates=candidates.filter(s=>s!=='matrix');
    if(!candidates.length)candidates=['rows'];
    const selected=candidates.slice().sort((a,b)=>((used.get(a)||0)+(a===previous?100:0))-((used.get(b)||0)+(b===previous?100:0)))[0];
    used.set(selected,(used.get(selected)||0)+1);previous=selected;return selected;
  });
}

export function wrapText(value,max){
  let result='',length=0;
  // Preserve years, decimal values, percentages and Latin names as tokens.
  const tokens=String(value).match(/[A-Za-z0-9]+(?:[.,%-][A-Za-z0-9]+)*%?|[^A-Za-z0-9]/g)||[];
  for(const token of tokens){
    if(token==='\n'){result+=token;length=0;continue}
    const units=[...token].reduce((n,c)=>n+(c.charCodeAt(0)>255?1:.55),0);
    if(units>max){for(const c of token){if(length+.55>max){result+='\n';length=0}result+=c;length+=.55}continue}
    if(length+units>max&&!/^[，。！？；：、）】]$/.test(token)){result+='\n';length=0}
    result+=token;length+=units;
  }
  return result;
}
