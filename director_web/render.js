'use strict';
// Schema data only: never innerHTML, eval, code generation or remote assets.
const channel = new URLSearchParams(location.search).get('channel') || 'program';
// New identity per document lifetime: a fast CEF reload cannot inherit review.
const rendererInstance=channel.startsWith('bank-')&&new URLSearchParams(location.search).get('renderer')==='obs'?crypto.randomUUID().replaceAll('-',''):null;
const canvas = document.querySelector('#canvas');
const layers = Object.fromEntries(['mode','composition','lower','timer','vote','alert'].map(id=>[id,document.getElementById(id)]));
let state=null, key=null, received=0, animations=[], previewStart=0, lastGood=0;
function resize(){canvas.style.transform=`scale(${Math.min(innerWidth/1920,innerHeight/1080)})`;}
addEventListener('resize',resize);resize();
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=String(text);return el;}
const motions={none:[{},{}],fade:[{opacity:0},{opacity:1,offset:.15},{opacity:1,offset:.85},{opacity:0}],rise:[{transform:'translateY(70px)',opacity:0},{transform:'translateY(0)',opacity:1,offset:.18},{transform:'translateY(0)',opacity:1,offset:.85},{transform:'translateY(-20px)',opacity:0}],slide:[{transform:'translateX(-100px)',opacity:0},{transform:'translateX(0)',opacity:1,offset:.2},{transform:'translateX(0)',opacity:1,offset:.85},{transform:'translateX(60px)',opacity:0}],pulse:[{transform:'scale(.8)',opacity:0},{transform:'scale(1)',opacity:1,offset:.2},{transform:'scale(1.07)',opacity:1,offset:.5},{transform:'scale(1)',opacity:1,offset:.8},{transform:'scale(.9)',opacity:0}],orbit:[{transform:'translate(-45px,0)',opacity:0},{transform:'translate(0,-45px)',opacity:1,offset:.25},{transform:'translate(45px,0)',opacity:1,offset:.5},{transform:'translate(0,45px)',opacity:1,offset:.75},{transform:'translate(-45px,0)',opacity:0}]};
function build(s){
 animations.forEach(a=>a.anim.cancel());animations=[];layers.composition.replaceChildren();
 const c=s.segment.composition;previewStart=s.started;
 layers.mode.replaceChildren();layers.mode.style.display=s.mode_look?'block':'none';if(s.mode_look){layers.mode.style.backgroundColor=s.mode_look.background;layers.mode.append(node('div','mode-title',s.mode_look.title),node('div','mode-subtitle',s.mode_look.subtitle));}
 for(const p of c.elements){
  const el=node('div','primitive',p.kind==='text'?p.text:'');
  Object.assign(el.style,{left:p.x+'px',top:p.y+'px',width:p.w+'px',height:p.h+'px',color:p.color,fontSize:p.size+'px',opacity:p.opacity,borderRadius:(p.kind==='circle'?999:p.radius)+'px'});
  if(p.kind!=='text')el.style.backgroundColor=p.color;
  layers.composition.append(el);
  const reduced=s.reduced_motion||matchMedia('(prefers-reduced-motion: reduce)').matches;
  const frames=reduced||p.motion==='none'?[{opacity:1},{opacity:1}]:motions[p.motion];
  const anim=el.animate(frames,{duration:(p.end-p.start)*1000,fill:'both',easing:'ease-in-out'});anim.pause();
  animations.push({el,anim,p});
 }
 layers.lower.replaceChildren();if(s.segment.lower){layers.lower.append(node('div','title',s.segment.lower.title),node('div','subtitle',s.segment.lower.subtitle));}
 layers.timer.replaceChildren();if(s.segment.timer){layers.timer.append(node('div','label',s.segment.timer.label),node('div','time','00:00'));}
}
function format(seconds){seconds=Math.max(0,Math.floor(seconds));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;return(h?h.toString().padStart(2,'0')+':':'')+m.toString().padStart(2,'0')+':'+s.toString().padStart(2,'0');}
function draw(){
 if(state){
  // Freeze at the last confirmed state if polling fails; stale graphics never restart.
  const delta=state.paused?0:Math.max(0,Math.min(1.8,(performance.now()-received)/1000));
  const now=state.clock+delta;
  const start=state.started;
  const c=state.segment.composition;
  let age=Math.max(0,now-start);const elapsed=age>=c.duration*c.repeat;
  if(elapsed&&state.phase==='prepared')age=c.elements.length?Math.min(...c.elements.map(p=>p.start+(p.end-p.start)*.25)):0;
  const cycle=age%c.duration,finished=elapsed&&state.phase!=='prepared';
  for(const {el,anim,p} of animations){el.style.visibility=finished||cycle<p.start||cycle>p.end?'hidden':'visible';anim.currentTime=Math.max(0,Math.min(p.end-p.start,cycle-p.start))*1000;}
  // Keep the persistent background, but avoid drawing identical base text
  // beneath currently visible composition text. Expiry restores the base copy.
  for(const base of layers.mode.children){
   const duplicate=animations.some(({el,p})=>p.kind==='text'&&p.text===base.textContent&&p.opacity>0&&el.style.visibility!=='hidden');
   base.style.visibility=duplicate?'hidden':'visible';
  }
  if(state.segment.timer&&state.timer){const t=state.timer,passed=t.offset+(t.running?Math.max(0,now-t.anchor):0);const secs=state.segment.timer.kind==='countdown'?state.segment.timer.seconds-passed:state.segment.timer.seconds+passed;layers.timer.querySelector('.time').textContent=format(secs);}
  const alert=state.alert;layers.alert.textContent=alert&&(state.phase==='prepared'||(now<alert.until&&now>=alert.start))?alert.title:'';
 }
 requestAnimationFrame(draw);
}
let voteKey='';
function renderVote(s){const vote=s.segment.vote,v=s.vote;const next=JSON.stringify([vote,v,s.poll_epoch]);if(next===voteKey)return;voteKey=next;layers.vote.replaceChildren();if(!vote||!v)return;const total=v.counts.reduce((a,b)=>a+b,0);layers.vote.append(node('div','tag',`LOCAL ${vote.kind.toUpperCase()} · ${v.open?'!vote 1–'+vote.options.length:'CLOSED'}${vote.kind==='prediction'?' · NO STAKES':''}`),node('h2','',vote.question));vote.options.forEach((option,i)=>{const row=node('div','option',`${i+1}. ${option}  ·  ${v.counts[i]}`);const bar=node('div','bar');bar.style.width=(total?100*v.counts[i]/total:0)+'%';row.append(bar);layers.vote.append(row);});layers.vote.append(node('div','total',`${total} local votes · one per eligible voter per tally round`));}
async function poll(){
 try{const response=await fetch('/api/render?channel='+encodeURIComponent(channel),{cache:'no-store'});if(!response.ok)throw Error();const s=await response.json();if(document.fonts)await document.fonts.ready;const next=JSON.stringify([s.id,s.reduced_motion,s.preview_serial,s.segment]);if(next!==key){key=next;build(s);}state=s;received=performance.now();lastGood=received;renderVote(s);
  if(channel.startsWith('bank-')&&new URLSearchParams(location.search).get('renderer')==='obs'){if(document.fonts)await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));await fetch('/api/rendered',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bank:channel.slice(-1),id:s.id,serial:s.serial,renderer:'obs',renderer_instance:rendererInstance,...(s.warm_epoch===undefined?{}:{warm_epoch:s.warm_epoch})})});}
  if(channel==='preview'&&s.review_requested){await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));const ack=await fetch('/api/previewed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage_id:s.id})});if(ack.ok){parent.postMessage({type:'director-preview',stage_id:s.id},location.origin);}}
 }catch(_){/* Keep the last frame; controller reports the failed connection. */}
 setTimeout(poll,300);
}
poll();draw();
