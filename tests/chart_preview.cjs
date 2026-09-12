// Minimal DOM regression: previews must use the chosen geometry, not all fall back to lines.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('static/industry.js', 'utf8');
const fragment = source.slice(source.indexOf('function drawChart('), source.indexOf('async function flushChartChanges('));
const document = {createElementNS: (_, tag) => ({tag, attrs: {}, children: [], setAttribute(k,v){this.attrs[k]=v}, append(child){this.children.push(child)}})};
const context = vm.createContext({document});
vm.runInContext(fragment, context);
for (const [kind, geometry] of Object.entries({area:'polygon', column:'rect', scatter:'circle', lollipop:'line'})) {
  const svg = context.drawChart({title:'市场规模', unit:'亿元', labels:['2022','2024','2030'], values:[100,150,300], selected_type:kind});
  assert(svg.children.some(node=>node.tag===geometry), kind);
  if (kind==='scatter'||kind==='lollipop') assert(!svg.children.some(node=>node.tag==='polyline'), kind);
  if (kind==='area') assert(svg.children.some(node=>node.tag==='polyline'));
}
console.log('4 chart preview geometry checks passed');
