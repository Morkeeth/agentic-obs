// Node DOM/animation contract test. Simulated DOM only, not browser pixel evidence.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element {
 set innerHTML(_){throw Error('Unsafe HTML write');}
 constructor(tag){this.tag=tag;this.style={};this.children=[];this.textContent='';this.animations=[];}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 querySelector(selector){return this.children.find(x=>x.className===selector.slice(1));}
 animate(frames,options){const a={frames,options,pause(){},cancel(){this.cancelled=true;},currentTime:0};this.animations.push(a);return a;}
}
const nodes=Object.fromEntries(['canvas','mode','composition','lower','timer','vote','alert'].map(x=>[x,new Element('div')]));
let now=0;let state={segment:{composition:{duration:8,repeat:1,elements:[{id:'safe',kind:'text',text:'<script>plain text</script>',x:50,y:50,w:900,h:120,color:'#ffffff',size:64,opacity:1,radius:0,start:0,end:8,motion:'rise'}]},lower:{title:'Guest',subtitle:'Maker'},timer:{kind:'countdown',seconds:90,label:'Back'},vote:{kind:'vote',question:'Choose',options:['Build','Explore']}},id:1,clock:100,started:100,paused:false,reduced_motion:false,timer:{anchor:100,offset:0,running:true},vote:{counts:[2,1],open:true},alert:{title:'Celebration',start:100,until:105},preview_serial:null,review_requested:false};
const tasks=[],frames=[],requests=[];
const context={URLSearchParams,location:{search:'?channel=program',origin:'http://127.0.0.1:8880'},innerWidth:960,innerHeight:540,
 document:{querySelector:s=>nodes[s.slice(1)],getElementById:id=>nodes[id],createElement:tag=>new Element(tag)},
 performance:{now:()=>now},matchMedia:()=>({matches:false}),addEventListener(){},requestAnimationFrame:f=>frames.push(f),
 setTimeout:f=>tasks.push(f),parent:{postMessage(){}},fetch:async url=>{requests.push(url);return{ok:true,json:async()=>structuredClone(state)};},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('director_web/render.js','utf8'),context);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(nodes.canvas.style.transform,'scale(0.5)');
assert.equal(nodes.composition.children[0].textContent,'<script>plain text</script>');
assert.equal(nodes.lower.children[0].textContent,'Guest');
assert.match(nodes.vote.children[0].textContent,/LOCAL VOTE/);
frames.shift()();assert.equal(nodes.timer.querySelector('.time').textContent,'01:30');assert.equal(nodes.alert.textContent,'Celebration');
now=1000;frames.shift()();assert.equal(nodes.timer.querySelector('.time').textContent,'01:29');
state.clock=101;state.paused=true;tasks.shift()();await new Promise(resolve=>setImmediate(resolve));now=1500;frames.shift()();assert.equal(nodes.timer.querySelector('.time').textContent,'01:29');
state.id=2;state.segment.composition.elements=[];state.segment.lower=null;tasks.shift()();await new Promise(resolve=>setImmediate(resolve));assert.equal(nodes.composition.children.length,0);assert.equal(nodes.lower.children.length,0);
state.id=3;state.phase='prepared';state.clock=110;state.alert={title:'Celebration',start:100,until:105};
tasks.shift()();await new Promise(resolve=>setImmediate(resolve));frames.shift()();
assert.equal(nodes.alert.textContent,'Celebration','hidden preparation holds intended fixed alert until ready');
state.phase='program';state.alert={title:'Celebration',start:110,until:115};
tasks.shift()();await new Promise(resolve=>setImmediate(resolve));frames.shift()();
assert.equal(nodes.alert.textContent,'Celebration');
state.clock=116;tasks.shift()();await new Promise(resolve=>setImmediate(resolve));frames.shift()();
assert.equal(nodes.alert.textContent,'','released fixed alert still has bounded lifetime');
state.segment.vote.question='<script>fixed operator question</script>';state.segment.vote.options[0]='<img src=x onerror=bad>';state.poll_epoch='new-round';
tasks.shift()();await new Promise(resolve=>setImmediate(resolve));
assert.equal(nodes.vote.children[1].textContent,'<script>fixed operator question</script>');
assert.match(nodes.vote.children[2].textContent,/<img src=x onerror=bad>/);
assert.ok(requests.every(x=>x.startsWith('/api/')));
console.log('PASS: simulated DOM renderer text safety, transparent layer clearing, timer pause, vote display and local-only requests. Pixels unverified.');
