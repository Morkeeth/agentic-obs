// Production selected-source controls in simulated DOM; no actual browser/page loading.
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
class Element{constructor(){this.children=[];this.options=[];this.value='';this.textContent='';this.classList={toggle(){}};}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}set innerHTML(_){throw Error('Unsafe HTML');}}
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}
const fixture={version:1,staged:{mode:'live',layout:'pip'},program:{mode:'live',layout:'pip'},program_native:true,current_native_layout:'pip',armed:true,obs:{connected:true},events:[],markers:[],catalog:[],recipes:[],media:{state:'stopped',volume:0},page_catalog:[{id:'article',name:'Approved article',url:'https://example.org/article',revision:'rev'}],selected_page:null,staged_page:null,material_catalog:[{id:'story',name:'Story',revision:'reference-rev'}],selected_material:null};
const sent=[];const context={fixture,document:{getElementById:node,createElement:()=>new Element(),activeElement:null},recipeSteps(){},fetch:async(_url,options)=>{const body=JSON.parse(options.body);sent.push(body);fixture.version++;return {ok:true,json:async()=>structuredClone(fixture)};}};
vm.createContext(context);const source=fs.readFileSync('director_web/app.js','utf8');
const handlers=source.split('\n').filter(line=>line.startsWith("$('page-stage').onclick=")||line.startsWith("$('page-bound').onclick=")||line.startsWith("$('material-choose').onclick=")).join('\n');
vm.runInContext(source.split('function recipeSteps()')[0]+';state=fixture;update();\n'+handlers,context);
assert.equal(sent.length,0);await node('page-stage').onclick();assert.equal(sent.length,0);
fixture.selected_page={id:'article',revision:'rev'};vm.runInContext('state=fixture;update()',context);
await node('page-stage').onclick();await new Promise(setImmediate);assert.deepEqual(sent[0].command,{action:'stage_selected_page',id:'article',revision:'rev'});
assert.equal(JSON.stringify(sent[0]).includes('https://'),false);
await node('page-bound').onclick();assert.deepEqual(sent[1].command,{action:'stage_bound_content'});
node('material-select').value='story';await node('material-choose').onclick();assert.deepEqual(sent[2].command,{action:'material_select',id:'story'});
fixture.staged_page={id:'article',revision:'rev'};vm.runInContext('state=fixture;update()',context);
assert.match(node('preview-status').textContent,/external page loading\/pixels unverified/);
console.log('PASS simulated selected-source UI: explicit selection, ID-only staging, bound content and page-load caveat');
