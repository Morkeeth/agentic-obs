// Rehearsal duplicate-title regression. Production renderer, simulated DOM, not OBS pixels.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
class Element {
 constructor(){this.style={};this.children=[];this.textContent='';}
 append(...x){this.children.push(...x);} replaceChildren(...x){this.children=x;}
 querySelector(s){return this.children.find(x=>x.className===s.slice(1));}
 animate(){return {pause(){},cancel(){},currentTime:0};}
}
const fixtures=JSON.parse(execFileSync('.venv/bin/python',['-c',`
import json,tempfile
from director import Director,ROOT
from director_schema import mode_look
folder=tempfile.TemporaryDirectory(dir=ROOT,prefix=".director-test-")
values=[]
for mode in ('starting','brb','ending'):
 x=Director(data_dir=folder.name)
 x.execute({'action':'stage_patch','fields':{'mode':mode}},x.version)
 x.execute({'action':'compose','title':{'starting':'Starting soon','brb':'Be right back','ending':'Thanks for watching'}[mode],'subtitle':mode_look(mode)['subtitle']},x.version)
 x.execute({'action':'preview'},x.version);x.preview_ack(x.stage_id)
 x.execute({'action':'take'},x.version)
 value=x.render('program');value['clock']=value['started']+2;values.append(value)
print(json.dumps(values));folder.cleanup()
`],{encoding:'utf8'}));
for(const [index,fixture] of fixtures.entries()){
const nodes=Object.fromEntries(['canvas','mode','composition','lower','timer','vote','alert'].map(x=>[x,new Element()]));
const frames=[];
const context={URLSearchParams,location:{search:'?channel=program',origin:'http://127.0.0.1:8880'},innerWidth:1920,innerHeight:1080,
 document:{querySelector:s=>nodes[s.slice(1)],getElementById:id=>nodes[id],createElement:()=>new Element()},
 performance:{now:()=>0},matchMedia:()=>({matches:false}),addEventListener(){},requestAnimationFrame:f=>frames.push(f),
 setTimeout(){},parent:{postMessage(){}},fetch:async()=>({ok:true,json:async()=>fixture}),console};
vm.createContext(context);vm.runInContext(fs.readFileSync('director_web/render.js','utf8'),context);
await new Promise(resolve=>setImmediate(resolve));frames.shift()();
const title=['Starting soon','Be right back','Thanks for watching'][index];
assert.equal(nodes.composition.children.filter(x=>x.textContent===title&&x.style.visibility!=='hidden').length,1);
assert.equal(nodes.mode.children.find(x=>x.textContent===title).style.visibility,'hidden','identical persistent and animated titles must not overlap');
assert.equal(nodes.mode.children[1].style.visibility,'hidden','matching subtitle must not overlap either');
fixture.clock=fixture.started+20;
// Same state object advances here; the draw loop must restore the persistent title.
frames.shift()();
assert.equal(nodes.mode.children.find(x=>x.textContent===title).style.visibility,'visible');
assert.equal(nodes.mode.children[1].style.visibility,'visible');
assert.equal(nodes.mode.style.display,'block');
}
console.log('PASS: identical animated/base titles do not overlap and persistent title returns on expiry (simulated DOM).');
