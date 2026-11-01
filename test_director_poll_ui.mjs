// Local poll permission control in production controller JS, simulated DOM only.
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
class Element{constructor(){this.children=[];this.options=[];this.value='';this.textContent='';this.classList={toggle(){}};}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}set innerHTML(_){throw Error('Unsafe HTML');}}
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}
const fixture={version:1,staged:{mode:'live',layout:'pip'},program:{mode:'live',layout:'pip'},program_native:true,obs:{connected:true},events:[],markers:[],catalog:[],recipes:[],media:{state:'stopped',volume:0},vote:{counts:[1,2],open:true},local_director_poll:{feature_enabled:false,epoch:'exact-epoch',open:false}};
const sent=[];const source=fs.readFileSync('director_web/app.js','utf8');
const context={fixture,document:{getElementById:node,createElement:()=>new Element(),activeElement:null},recipeSteps(){},fetch:async(_url,options)=>{const body=JSON.parse(options.body);sent.push(body);fixture.local_director_poll.feature_enabled=body.command.enabled;fixture.version++;return {ok:true,json:async()=>structuredClone(fixture)};}};
vm.createContext(context);const handler=source.split('\n').find(x=>x.startsWith("$('local-director-polls').onclick="));
vm.runInContext(source.split('function recipeSteps()')[0]+';state=fixture;update();\n'+handler,context);
assert.match(node('local-director-polls').textContent,/DEFAULT OFF/);assert.equal(sent.length,0);
assert.match(node('local-poll-status').textContent,/exact-epoch/);assert.match(node('local-poll-status').textContent,/counters only/);
await node('local-director-polls').onclick();
assert.deepEqual(sent[0].command,{action:'local_director_polls',enabled:true});
assert.match(node('local-director-polls').textContent,/Disable/);
console.log('PASS simulated controller local-poll DEFAULT-OFF flag and explicit epoch/counter-only status');
