// A deliberately small Markdown renderer. All model text enters text nodes;
// raw HTML, URLs and event handlers are never interpreted.
function renderMarkdown(root, value) {
  const text=String(value||'').replace(/&#(?:x20|32);|&nbsp;/gi,' ').replace(/\\([*#~])/g,'$1').trim();
  function inline(node,text){
    for(const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)){
      if(part.startsWith('**')&&part.endsWith('**')){const el=document.createElement('strong');el.textContent=part.slice(2,-2);node.append(el)}
      else if(part.startsWith('`')&&part.endsWith('`')){const el=document.createElement('code');el.textContent=part.slice(1,-1);node.append(el)}
      else node.append(document.createTextNode(part));
    }
  }
  let list=null, paragraph=null, code=null, table=null;
  const lines=text.split(/\r?\n/);
  for(let i=0;i<lines.length;i++){
    const line=lines[i], t=line.trim();
    if(t.startsWith('```')){if(code)code=null;else{code=document.createElement('pre');root.append(code)}list=paragraph=table=null;continue}
    if(code){code.textContent+=line+'\n';continue}
    if(!t){list=paragraph=table=null;continue}
    const heading=t.match(/^#{1,6}\s+(.+)$/);
    if(heading){const el=document.createElement('h3');inline(el,heading[1]);root.append(el);list=paragraph=table=null;continue}
    if(/^[-*_]{3,}$/.test(t)){root.append(document.createElement('hr'));list=paragraph=table=null;continue}
    if(t.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      table=document.createElement('table');root.append(table);const row=document.createElement('tr');table.append(row);
      for(const cell of t.replace(/^\||\|$/g,'').split('|')){const th=document.createElement('th');inline(th,cell.trim());row.append(th)}i++;paragraph=list=null;continue;
    }
    if(table&&t.includes('|')){const row=document.createElement('tr');table.append(row);for(const cell of t.replace(/^\||\|$/g,'').split('|')){const td=document.createElement('td');inline(td,cell.trim());row.append(td)}continue}table=null;
    const item=t.match(/^(?:[-*+]\s+|\d+[.)]\s+)(.+)$/);
    if(item){const kind=/^\d/.test(t)?'OL':'UL';if(!list||list.tagName!==kind){list=document.createElement(kind.toLowerCase());root.append(list)}const li=document.createElement('li');inline(li,item[1]);list.append(li);paragraph=null;continue}
    list=null;if(!paragraph){paragraph=document.createElement('p');root.append(paragraph)}else paragraph.append(document.createElement('br'));inline(paragraph,t);
  }
}
