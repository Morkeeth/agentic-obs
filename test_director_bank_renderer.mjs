// Real production renderer in simulated DOM, production protocol against simulated OBS.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const fixtures=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`
import copy,json,tempfile
from director_obs import BASES,SCENES
from director import Director,ROOT
from director_simulator import SimulatedOBS
from test_director_cold_renderers import ColdRenderer
with tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-test-') as tmp, SimulatedOBS() as sim:
 d=Director(data_dir=tmp)
 def act(action,**kw):return d.execute({'action':action,**kw},d.version)
 act('connect',password=sim.password,port=sim.port);act('setup',camera='Camera',content='Content')
 with ColdRenderer(d,sim):act('arm',enabled=True)
 a=d.render('bank-A')
 def base_items():return {mode:{scene:[copy.deepcopy(item) for item in sim.scenes[scene] if item['sourceName']==name] for scene in SCENES[mode]} for mode,name in BASES.items()}
 bases_before=copy.deepcopy({name:sim.inputs[name] for name in BASES.values()});items_before=base_items()
 program_before=sim.program;geometry_before=copy.deepcopy(sim.scenes[sim.program])
 graphics_before=copy.deepcopy(d.native.graphics_item(sim.program))
 act('stage_patch',fields={'mode':'brb'});act('compose',title='A distinct new draft');act('preview',target='obs')
 b=d.render('bank-B');unchanged=d.render('bank-A')
 program_staged=sim.program;geometry_staged=copy.deepcopy(sim.scenes[sim.program])
 graphics_staged=copy.deepcopy(d.native.graphics_item(sim.program))
 d.preview_ack(d.stage_id);d.bank_ack('B',b['id'],b['serial'],'obs');act('take')
 print(json.dumps({'a':a,'unchanged':unchanged,'prepared':b,'taken':d.render('bank-B'),'bases_before':bases_before,'bases_after':{name:sim.inputs[name] for name in BASES.values()},'items_before':items_before,'items_after':base_items(),'program_before':program_before,'program_staged':program_staged,'program_taken':sim.program,'geometry_before':geometry_before,'geometry_staged':geometry_staged,'graphics_before':graphics_before,'graphics_staged':graphics_staged,'graphics_taken':d.native.graphics_item(sim.program)}))
 d.close()
`],{encoding:'utf8'}));
class Element{
 constructor(){this.style={};this.children=[];this.textContent='';this.animations=[];}
 append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}
 querySelector(s){return this.children.find(x=>x.className===s.slice(1));}
 animate(){const a={pause(){},cancel(){this.cancelled=true;},currentTime:0};this.animations.push(a);return a;}
}
async function renderer(bank,initial){
 const nodes=Object.fromEntries(['canvas','mode','composition','lower','timer','vote','alert'].map(x=>[x,new Element()]));
 const frames=[],tasks=[],requests=[];let payload=initial;
 const context={crypto:webcrypto,URLSearchParams,location:{search:`?channel=bank-${bank}&renderer=obs`,origin:'http://127.0.0.1:8880'},innerWidth:1920,innerHeight:1080,
  document:{querySelector:s=>nodes[s.slice(1)],getElementById:id=>nodes[id],createElement:()=>new Element(),fonts:{ready:Promise.resolve()}},
  performance:{now:()=>500},matchMedia:()=>({matches:false}),addEventListener(){},requestAnimationFrame:f=>frames.push(f),setTimeout:f=>tasks.push(f),
  parent:{postMessage(){}},fetch:async(url,options)=>{requests.push([url,options]);return {ok:true,json:async()=>structuredClone(payload)};},console};
 vm.createContext(context);vm.runInContext(fs.readFileSync('director_web/render.js','utf8'),context);
 async function settle(){for(let i=0;i<8;i++){await new Promise(r=>setImmediate(r));const batch=frames.splice(0);batch.forEach(f=>f());}}
 await settle();
 return {nodes,requests,async poll(value){payload=value;tasks.shift()();await settle();}};
}
const a=await renderer('A',fixtures.a),b=await renderer('B',fixtures.prepared);
// A hidden Graphics source may retain a base-looking DOM/texture. Native owned
// base identity and item visibility, not that texture, establish the mode contract.
assert.deepEqual(fixtures.bases_before,fixtures.bases_after,'immutable base identity/settings survive preview/take');
assert.deepEqual(fixtures.items_before,fixtures.items_after,'immutable base item identities/transforms/enabled states survive preview/take');
for(const [mode,title] of [['starting','Starting soon'],['brb','Be right back'],['ending','Thanks for watching']]){
 const name='Director / Base '+mode[0].toUpperCase()+mode.slice(1),base=fixtures.bases_before[name];
 assert.equal(base.kind,'browser_source');
 const url=new URL(base.settings.url);assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.equal(url.pathname,'/base-'+mode+'.html');
 assert.equal(base.settings.width,1920);assert.equal(base.settings.height,1080);assert.equal(base.settings.shutdown,false);
 const html=fs.readFileSync('director_web'+url.pathname,'utf8');
 assert.ok(html.includes('class="mode-title">'+title+'</div>'),'persistent mode title comes from its actual immutable asset');
 assert.ok(!html.includes('<script'),'immutable base does not depend on mutable rendering');
 for(const items of Object.values(fixtures.items_before[mode])){assert.equal(items.length,1);assert.equal(items[0].sourceName,name);assert.equal(items[0].sceneItemEnabled,true);}
}
assert.equal(fixtures.program_before,fixtures.program_staged,'draft/preview cannot cut program');
assert.deepEqual(fixtures.geometry_before,fixtures.geometry_staged,'draft/preview cannot change program geometry/visibility');
assert.equal(fixtures.graphics_before.sceneItemEnabled,false,'empty active Graphics is hidden; immutable Starting remains visible');
assert.deepEqual(fixtures.graphics_before,fixtures.graphics_staged,'inactive preview cannot reveal/rewrite active Graphics');
assert.equal(fixtures.graphics_taken.sceneItemEnabled,true,'taking authored B reveals its correct native Graphics item');
assert.notEqual(fixtures.program_taken,fixtures.program_before);
for(const key of ['id','serial','started'])assert.equal(fixtures.a[key],fixtures.unchanged[key],'active bank identity/clock survives inactive drafting');
assert.deepEqual(fixtures.a.segment,fixtures.unchanged.segment,'active payload remains unchanged');
assert.equal(a.nodes.mode.children[0].textContent,'Starting soon','hidden source DOM is not program-pixel proof');
assert.equal(b.nodes.composition.children[1].textContent,'A distinct new draft');
assert.equal(b.nodes.mode.children[0].textContent,'Be right back');
const titleNode=b.nodes.composition.children[1];
await a.poll(fixtures.unchanged);await b.poll(fixtures.taken);
assert.equal(a.nodes.mode.children[0].textContent,'Starting soon','source DOM stays unchanged; native program/base visibility is independently checked above');
assert.equal(b.nodes.composition.children[1],titleNode,'take must not rebuild/blank/replace the already rendered title');
const receipt=b.requests.find(([url])=>url==='/api/rendered');assert.ok(receipt);
const firstAck=JSON.parse(receipt[1].body);
assert.match(firstAck.renderer_instance,/^[a-f0-9]{32}$/);
assert.deepEqual(firstAck,{bank:'B',id:fixtures.prepared.id,serial:fixtures.prepared.serial,renderer:'obs',renderer_instance:firstAck.renderer_instance});
assert.ok(b.requests.filter(([url])=>url==='/api/rendered').every(([,options])=>JSON.parse(options.body).renderer_instance===firstAck.renderer_instance),'document identity stable across polls');
const restarted=await renderer('B',fixtures.prepared);
assert.notEqual(JSON.parse(restarted.requests.find(([url])=>url==='/api/rendered')[1].body).renderer_instance,firstAck.renderer_instance,'fresh document cannot inherit identity');
assert.ok(a.requests.filter(([url])=>url.startsWith('/api/render?')).every(([url])=>url.endsWith('bank-A')));
await b.poll({...fixtures.taken,warm_epoch:77});
const warmReceipt=b.requests.filter(([url])=>url==='/api/rendered').at(-1);
assert.equal(JSON.parse(warmReceipt[1].body).warm_epoch,77,'fresh server warm challenge must be echoed after render frames');
assert.equal(b.nodes.composition.children[1],titleNode,'warming metadata cannot rebuild or restart program composition');
await b.poll(fixtures.taken);
assert.equal(Object.hasOwn(JSON.parse(b.requests.filter(([url])=>url==='/api/rendered').at(-1)[1].body),'warm_epoch'),false);
console.log('PASS: independent A/B DOM payloads, bank-specific rendered acknowledgment and no DOM rebuild on take (simulated, pixels unverified).');
