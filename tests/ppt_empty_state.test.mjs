import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
// Minimal DOM harness for initial-state and failed-load event handlers.
const nodes=[];
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.value='';nodes.push(this)}
  append(...items){this.children.push(...items)}
  setAttribute(){} addEventListener(){} remove(){}
  showModal(){this.open=true} close(){this.open=false}
  replaceChildren(...items){this.children=items}
}
const context={window:{},document:{createElement:t=>new Element(t),getElementById:()=>null,body:new Element('body'),createTextNode:t=>t},Option:class extends Element{constructor(t,v){super('option');this.textContent=t;this.value=v}},fetch:async()=>({ok:true,json:async()=>[]}),clearTimeout,setTimeout,confirm:()=>true};
vm.runInNewContext(fs.readFileSync('static/ppt.js','utf8'),context);
await context.window.openPpt('p1');
const button=text=>nodes.find(n=>n.tag==='button'&&n.textContent===text);
const save=button('保存大纲'),generate=button('确认大纲并生成 PPT'),add=button('增加一页');
assert.ok(save.disabled&&generate.disabled&&add.disabled);
assert.ok(nodes.find(n=>n.children.includes(save)).hidden);
await save.onclick();await generate.onclick();add.onclick();
assert.ok(save.disabled&&generate.disabled&&add.disabled);
assert.ok(nodes.some(n=>n.textContent==='请先生成或打开 PPT 大纲'));
assert.match(fs.readFileSync('static/ppt.css','utf8'),/\[hidden\]\{display:none!important\}/);
console.log('PPT empty-state guards passed');
