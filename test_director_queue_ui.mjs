// Actual controller update and callbacks in simulated DOM. No browser/audio/pixel claim.
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
class Element{
 constructor(){this.children=[];this.options=[];this.value='';this.classList={toggle(){}};this.textContent='';}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
 set innerHTML(_){throw Error('Unsafe HTML write');}
}
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}
const raw='<img src=x onerror="run viewer instructions">';
const fixture={version:1,staged:{mode:'live',layout:'pip'},program:{mode:'live',layout:'pip'},program_native:true,current_native_layout:'pip',armed:true,audience_enabled:true,obs:{connected:true},events:[],markers:[],catalog:[],recipes:[],media:{state:'stopped',volume:0},chat_requests:[{id:'exact-request',revision:1,text:raw,suggested:null,selected:null}]};
const sent=[];const context={document:{getElementById:node,createElement:()=>new Element(),activeElement:null},recipeSteps(){},fixture,
 fetch:async(url,options)=>{const body=JSON.parse(options.body);sent.push(body);const item=fixture.chat_requests[0];if(body.command.action==='request_select'){item.selected=body.command.intent;item.revision++;}fixture.version++;return {ok:true,json:async()=>structuredClone(fixture)};}};
vm.createContext(context);
const source=fs.readFileSync('director_web/app.js','utf8').split('function recipeSteps()')[0];
vm.runInContext(source+';state=fixture;update();',context);
let row=node('chat-requests').children[0];assert.equal(row.children[0].textContent,raw);assert.equal(row.children[3].disabled,true);
assert.equal(sent.length,0);
row.children[2].value='hydrate';await row.children[2].onchange();
assert.deepEqual(sent[0].command,{action:'request_select',id:'exact-request',revision:1,intent:'hydrate'});
row=node('chat-requests').children[0];assert.equal(row.children[3].disabled,false);
await row.children[3].onclick();
assert.deepEqual(sent[1].command,{action:'request_accept',id:'exact-request',revision:2,intent:'hydrate'});
assert.equal(JSON.stringify(sent).includes(raw),false);
console.log('PASS simulated queue DOM: inert text, no automatic action, exact item/revision/intent selection and acceptance');
