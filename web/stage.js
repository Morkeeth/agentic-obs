const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function moment(show,started){
 if(!started||show.theme==='normal')return{phase:-1,remaining:show.duration};
 let t=Math.max(0,Date.now()/1000-started),sum=0;
 for(let i=0;i<show.beats.length;i++){sum+=show.beats[i].seconds;if(t<sum)return{phase:i,remaining:Math.ceil(sum-t),elapsed:t};}
 return{phase:4,remaining:0,elapsed:t};
}
function paintStage(el,show,started,{overlay=false,fallback=null}={}){
 let m=moment(show,started),actual=show;
 if(m.phase===4&&fallback){actual=fallback;m={phase:-1,remaining:actual.duration};}
 const key=[actual.id,m.phase,overlay].join(':');
 if(el.dataset.key!==key){
  el.dataset.key=key;el.className='stage '+(el.classList.contains('small')?'small ':'')+actual.theme+' camera-'+actual.camera+' '+actual.motion+(overlay?' overlay':'');
  let content=actual.theme==='normal'?'<div class="return-label">Back to the stream</div>':m.phase===2?'<div class="kicker">The moment</div><div class="reveal">'+esc(actual.reveal)+'</div>':m.phase===3?'<div class="return-label">And we’re back.</div>':'<div class="kicker">'+(m.phase===0?'Setting the scene':m.phase===-1?'Countdown ready':'Until the reveal')+'</div><div class="count"><span>'+String(m.remaining).padStart(2,'0')+'</span><small> sec</small></div><div class="orbit"></div>';
  el.innerHTML='<div class="set"></div><div class="grid"></div><div class="show-name">'+esc(actual.title)+'</div><div class="onair">'+(overlay?'LOCAL SOURCE':'REHEARSAL STAGE')+'</div><div class="camera"><div class="head"></div><div class="body"></div><div class="placeholder">YOUR CAMERA · PLACEHOLDER</div></div><div class="graphic">'+content+'</div><div class="phase-tag">'+(actual.theme==='normal'?'NORMAL LAYOUT':m.phase===-1?'READY TO REHEARSE':'BEAT '+(m.phase+1)+' / 4')+'</div><div class="baseline">'+(overlay?'':'LOCAL VISUAL PROTOTYPE · NO OBS / TWITCH CONNECTION')+'</div>';
 }
 let count=el.querySelector('.count span');if(count)count.textContent=String(m.remaining).padStart(2,'0');
 return m;
}
