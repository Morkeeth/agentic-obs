'use strict';
const el=id=>document.getElementById(id);
let proposal=null;
const music=new MusicBed({audio:new Audio(),context:new AudioContext()});
const status=text=>el('status').textContent=text;
async function api(path,data){
  const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
}
function paint(state){
  const n=state.native;
  const streaming=!!n.outputs.stream;const blocked=n.outputs.record||n.outputs.virtual||(streaming&&!state.allow_live_preview);const controlEnabled=state.enabled&&!blocked;
  document.body.classList.toggle('live-mode',!!state.live);
  el('take-rule').hidden=!state.live;el('live-cues').hidden=!state.live;
  if(state.live){const bed=state.live.composition.music;if(bed)music.play(bed).catch(e=>status('Music could not start. Click the music item to retry.'));else music.stop();document.querySelector('h1').textContent='Your next shot.';el('mode-explanation').textContent='Preview by default. Only your explicit spoken Take changes local Program. Broadcast outputs stay off.';}
  if(state.live&&streaming){el('take-rule').textContent='Stream running. Edits stay in preview. Choose your live shot in OBS.';el('mode-explanation').textContent=state.allow_live_preview?'Live preview editing enabled. Program stays protected; output controls stay in OBS.':'Preview editing is paused while the stream runs.';}
  const visual=state.visual;
  if(visual){
    for(const key of ['x','y','width','height'])el('layout-'+key).value=Math.round(visual.layout[key]*100);
    const image=el('local-visual');
    image.hidden=!n.synthetic||!visual.visible||!visual.asset_id;
    if(!image.hidden){image.src='/asset/'+visual.asset_id+'.png';image.style.left=(visual.layout.x*100)+'%';image.style.top=(visual.layout.y*100)+'%';image.style.width=(visual.layout.width*100)+'%';image.style.height=(visual.layout.height*100)+'%';}
  }
  el('connection').textContent=(controlEnabled?'Preview control enabled':'Preview control paused')+' · '+(n.synthetic?'Rehearsal':'OBS');
  el('proof').textContent=n.synthetic?'Synthetic rehearsal · no devices':'Native state readback · inspect the picture in OBS';
  el('program-name').textContent=n.program;
  el('camera-caption').textContent=state.live?.composition.camera_clip?'Pre-recorded camera · silent desk footage':n.synthetic?'Synthetic camera fixture · no device connected':'Program scene in OBS · this panel is a status display';
  el('title').textContent=n.graphics.visible?n.graphics.title:visual?.visible?'Selected visual staged':'Preview is clear';
  el('preview-caption').textContent=state.live?'Composition staged in '+n.preview:n.graphics.visible||visual?.visible?'Staged in '+n.preview:'Preview content hidden';
  el('revision').textContent=state.live?('Preview composition · '+(state.live.bank||'not staged')):'Revision '+state.revision;
  ['stage','clear','restore'].forEach(id=>el(id).disabled=!controlEnabled||(id==='restore'&&!(state.live?.restore_available||state.restore_available)));
  el('enable').disabled=state.enabled||blocked;el('enable').hidden=controlEnabled;el('enable').textContent=blocked?'Preview paused while outputs run':'Enable preview control';el('disable').hidden=!state.enabled;
  if(!n.synthetic)monitor.start();else monitor.stop();
}
const monitor=new FrameMonitor({
  load:()=>api('/api/frames'),
  paint:frames=>{
    for(const key of ['program','preview']){const image=el(key+'-frame');image.src=frames[key];image.hidden=false;}
    el('proof').textContent='OBS frames · continuously refreshed · not full-rate video';
  },
  fail:()=>{
    for(const key of ['program','preview'])el(key+'-frame').hidden=true;
    el('proof').textContent='Native frames unavailable · inspect OBS';
  },
  visible:()=>!document.hidden
});
function speak(text,sample=false){
  if(!sample&&!el('spoken').checked)return;
  if(!('speechSynthesis'in window)){status('Spoken replies unavailable in this browser. Read the director reply.');return;}
  speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);
  const local=chooseVoice(speechSynthesis.getVoices(),el('voice-choice').value);
  if(!local){status('No local browser voice is ready. Read the director reply.');return;}
  utterance.voice=local;
  utterance.onstart=()=>music.duck('director',true);utterance.onend=()=>music.duck('director',false);
  utterance.onerror=()=>{music.duck('director',false);status('Spoken reply failed; the written answer is available.');};
  speechSynthesis.speak(utterance);
}
async function answer(reply){
  if(reply.stop_listening){await continuous.stop();el('listen').disabled=false;el('stop-listen').disabled=true;el('ptt').disabled=false;}
  proposal=reply.proposal;el('answer').textContent=reply.answer;
  if(proposal)el('title-input').value=proposal.title;
  el('transcript').textContent=reply.transcript?'You said: '+reply.transcript:'';
  el('latency').textContent=reply.latency_ms===undefined?'':`Speech to action: ${reply.latency_ms} ms · excludes spoken playback`;
  if(reply.state)paint(reply.state);else paint(await api('/api/state'));
  status(reply.taken?'Accepted in local Program · broadcast outputs OFF':reply.staged?'Preview updated. You choose what reaches Program.':'Direction ready. Stage the title when ready.');
  speak(reply.answer);
}
async function microphoneStream(){
 const id=el('microphone').value;
 const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,...(id?{deviceId:{exact:id}}:{})}});
 const active=stream.getAudioTracks()[0].getSettings().deviceId;
 let devices;
 try{devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='audioinput');}catch(e){return stream;}
 el('microphone').replaceChildren(...devices.map(d=>{const option=document.createElement('option');option.value=d.deviceId;option.textContent=d.label||'Microphone';return option;}));
 if(active)el('microphone').value=active;
 return stream;
}
el('microphone').onchange=()=>{if(continuous.active)el('stop-listen').click();status('Microphone selected. Start listening to use it.');};
const ptt=new PushToTalk({api,media:microphoneStream,Recorder:window.MediaRecorder,
  encode:blob=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);}),
  onreply:reply=>answer(reply).catch(e=>status(e.message)),onstatus:status});
function encodeClip(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});}
const continuous=new ContinuousVoice({api,media:microphoneStream,Recorder:window.MediaRecorder,encode:encodeClip,detect:(stream,level)=>detectSpeech(stream,rms=>{music.level(rms);el('mic-level').value=Math.min(1,rms*8);level(rms);}),onreply:reply=>answer(reply).catch(e=>status(e.message)),onstatus:status});
el('listen').onclick=async()=>{
  await music.unlock();await ptt.cancel();await continuous.start();el('listen').disabled=continuous.active;el('stop-listen').disabled=!continuous.active;el('ptt').disabled=continuous.active;
};
el('stop-listen').onclick=async()=>{
  await continuous.stop();music.duck('mic',false);el('listen').disabled=false;el('stop-listen').disabled=true;el('ptt').disabled=false;el('mic-level').value=0;status('Microphone stopped.');
};
function voicesChanged(){
 if(!window.speechSynthesis)return;
 const voices=speechSynthesis.getVoices().filter(v=>v.localService&&v.lang.replace('_','-').startsWith('en-'));
 const selected=chooseVoice(voices,el('voice-choice').value);
 el('voice-choice').replaceChildren(...voices.map(v=>{const option=document.createElement('option');option.value=v.name;option.textContent=v.name;return option;}));
 if(selected)el('voice-choice').value=selected.name;
}
if(window.speechSynthesis){speechSynthesis.onvoiceschanged=voicesChanged;voicesChanged();}
el('voice-sample').onclick=()=>speak('I’ll prepare that in preview. Your camera stays exactly where it is.',true);
el('spoken').onchange=()=>{if(!el('spoken').checked&&window.speechSynthesis)speechSynthesis.cancel();};
el('ptt').onpointerdown=e=>{e.preventDefault();el('ptt').setPointerCapture(e.pointerId);el('ptt').classList.add('listening');ptt.press();};
el('ptt').onpointerup=()=>{el('ptt').classList.remove('listening');ptt.release();};
el('ptt').onpointercancel=()=>{el('ptt').classList.remove('listening');ptt.cancel();};
el('ptt').onkeydown=e=>{if((e.key===' '||e.key==='Enter')&&!e.repeat){e.preventDefault();ptt.press();}};
el('ptt').onkeyup=e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();ptt.release();}};
el('cancel').onclick=()=>{ptt.cancel();continuous.stop();el('listen').disabled=false;el('stop-listen').disabled=true;el('ptt').disabled=false;if(window.speechSynthesis)speechSynthesis.cancel();status('Voice cancelled.');};
window.addEventListener('blur',()=>{if(ptt.held)ptt.cancel();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){ptt.cancel();continuous.stop();el('listen').disabled=false;el('stop-listen').disabled=true;el('ptt').disabled=false;}});
el('direction').onsubmit=async e=>{e.preventDefault();status('Director is thinking…');try{await answer(await api('/api/direct',{text:el('text').value}));}catch(error){status(error.message);}};
for(const name of ['enable','disable','clear','restore','stage'])el(name).onclick=async()=>{
  try{
    if(name==='disable'){await ptt.cancel();await continuous.stop();el('listen').disabled=false;el('stop-listen').disabled=true;el('ptt').disabled=false;if(window.speechSynthesis)speechSynthesis.cancel();}
    await api('/api/'+name,name==='stage'?{title:el('title-input').value}:{});
    paint(await api('/api/state'));status(name==='stage'?'Title staged in preview. Program unchanged.':'Preview control: '+name);
  }catch(error){status(error.message);try{paint(await api('/api/state'));}catch{}}
};
api('/api/state').then(paint).catch(e=>status(e.message));

async function refreshAssets(){
 const selected=el('assets').value,assets=await api('/api/catalog');
 el('assets').replaceChildren(...assets.map(asset=>{const option=document.createElement('option');option.value=asset.id;option.textContent=asset.name;return option;}));
 if(assets.some(a=>a.id===selected))el('assets').value=selected;
}
async function visualAction(data){try{paint(await api('/api/visual',data));status('Visual updated in preview. Camera program unchanged.');}catch(error){status(error.message);}}
el('slides').onclick=()=>visualAction({action:'slideshow'});
el('next-slide').onclick=()=>visualAction({action:'next'});
el('previous-slide').onclick=()=>visualAction({action:'previous'});
el('show-asset').onclick=()=>visualAction({action:'show',asset_id:el('assets').value});
el('images').onchange=async()=>{
 try{for(const file of el('images').files){if(file.size>4000000)throw Error('Choose images under 4 MB');await api('/api/image',{name:file.name.slice(0,90),image:await encodeClip(file)});}await refreshAssets();status('Images selected. Choose one and show it in preview.');}catch(error){status(error.message);}
};
el('page-form').onsubmit=async event=>{event.preventDefault();try{const asset=await api('/api/page',{url:el('page-url').value});await refreshAssets();el('assets').value=asset.id;await visualAction({action:'show',asset_id:asset.id});}catch(error){status(error.message);}};
el('layout-form').onsubmit=event=>{event.preventDefault();const data={action:'move'};for(const key of ['x','y','width','height'])data[key]=Number(el('layout-'+key).value)/100;visualAction(data);};
refreshAssets().catch(error=>status(error.message));

for(const button of document.querySelectorAll('[data-cue]'))button.onclick=async()=>{try{await answer(await api('/api/direct',{text:button.dataset.cue}));}catch(e){status(e.message);}};

async function libraryPanel(){const items=await api('/api/library');el('library-panel').hidden=!items.length;el('library-items').replaceChildren(...items.map(item=>{const button=document.createElement('button');button.className='library-item';if(item.thumbnail){const image=document.createElement('img');image.src=item.thumbnail;image.alt='';button.append(image);}const title=document.createElement('strong');title.textContent=item.title;const type=document.createElement('span');type.textContent=item.type;button.append(title,type);button.onclick=async()=>{try{await music.unlock();await answer(await api('/api/library/use',{id:item.id}));}catch(e){status(e.message);}};return button;}));}
libraryPanel().catch(e=>status('Library unavailable.'));

el('twitch-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/twitch/connect',{channel:el('twitch-channel').value.trim().toLowerCase()});status('Connecting to public Twitch chat. No account or chat posting.');}catch(e){status(e.message);}};
async function twitchStatus(){try{const data=await api('/api/twitch');if(data.channel&&document.activeElement!==el('twitch-channel'))el('twitch-channel').value=data.channel;el('twitch-state').textContent=data.connected?'Connected to #'+data.channel+' · '+data.received+' real messages received'+(data.room?' · Slow mode '+data.room.slow_seconds+'s':''):data.error||'Not connected';const commands=data.commands;el('chat-commands').checked=!!commands?.enabled;const trigger=commands?.last;el('twitch-command').textContent=trigger?trigger.message.name+': '+trigger.message.text+' → '+(trigger.answer||(trigger.status==='rate_limited'?'Wait two seconds between commands.':trigger.status)):commands?.enabled?'Allowed preview commands: !brb, !title <text>, !zoom. No Take.':'Chat commands off. No chat can Take.';const last=data.messages.at(-1);el('twitch-last').textContent=last?last.name+': '+last.text:'';}catch{}finally{setTimeout(twitchStatus,1000);}}twitchStatus();

el('chat-commands').onchange=async()=>{try{await api('/api/twitch/commands',{enabled:el('chat-commands').checked});}catch(e){status(e.message);}};
el('prepare-bandwidth').onclick=async()=>{try{const result=await api('/api/twitch/bandwidth-test',{});el('bandwidth-status').textContent=result.message;}catch(e){el('bandwidth-status').textContent=e.message;}};
