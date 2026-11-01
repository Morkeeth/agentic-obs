'use strict';
// Capture is allocated only during an actual hold. Release-before-permission,
// cancellation, blur, hidden page and Stop all retire the exact capture lease.
function pcmWav(chunks, inputRate) {
  const length=chunks.reduce((n,x)=>n+x.length,0), joined=new Float32Array(length);
  let at=0;for(const x of chunks){joined.set(x,at);at+=x.length;}
  const count=Math.floor(length*24000/inputRate), bytes=new ArrayBuffer(44+count*2), view=new DataView(bytes);
  const str=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
  str(0,'RIFF');view.setUint32(4,36+count*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,24000,true);view.setUint32(28,48000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,count*2,true);
  for(let i=0;i<count;i++){const pos=i*inputRate/24000, lo=Math.floor(pos), fraction=pos-lo;const x=Math.max(-1,Math.min(1,joined[lo]*(1-fraction)+(joined[lo+1]??joined[lo])*fraction));view.setInt16(44+i*2,x<0?x*32768:x*32767,true);}
  return bytes;
}
class HoldCapture {
  constructor(deps){this.d=deps;this.lease=null;}
  async down(){
    if(this.lease)return;
    const lease={stream:null,ctx:null,node:null,timer:null,chunks:[],frames:0};this.lease=lease;
    try {
      const stream=await this.d.media();lease.stream=stream;
      if(this.lease!==lease){stream.getTracks().forEach(t=>t.stop());return;}
      const ctx=this.d.context();lease.ctx=ctx;
      const input=ctx.createMediaStreamSource(stream), node=ctx.createScriptProcessor(2048,1,1), mute=ctx.createGain();lease.node=node;mute.gain.value=0;
      node.onaudioprocess=e=>{if(this.lease!==lease)return;const chunk=new Float32Array(e.inputBuffer.getChannelData(0));lease.frames+=chunk.length;if(lease.frames>ctx.sampleRate*12){this.up(true);return;}lease.chunks.push(chunk);};
      input.connect(node);node.connect(mute);mute.connect(ctx.destination);
      lease.timer=this.d.timer(()=>this.up(true),12000);this.d.status('Recording while held. Release to send.');
    } catch(_){if(this.lease===lease)this.up(false);this.d.status('Microphone unavailable; use an audio file.');}
  }
  up(send){
    const lease=this.lease;if(!lease)return;this.lease=null;
    this.d.clearTimer(lease.timer);lease.stream?.getTracks().forEach(t=>t.stop());
    if(lease.node){lease.node.onaudioprocess=null;lease.node.disconnect();}
    if(lease.ctx){const rate=lease.ctx.sampleRate;lease.ctx.close();if(send&&lease.chunks.length)this.d.send(pcmWav(lease.chunks,rate));}
    this.d.status('Microphone off.');
  }
}
if(typeof module!=='undefined')module.exports={HoldCapture,pcmWav};
if(typeof document!=='undefined'){
  const $=id=>document.getElementById(id), player=$('voice-reply');let ready=false,pending=null,url=null,holding=false,holdGeneration=0;
  const status=text=>$('voice-state').textContent=text;
  async function stopRemote(){await fetch('/api/realtime-stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}
  async function send(data){
    if(!ready||pending)return;
    pending=new AbortController();$('hold-talk').disabled=true;$('send-fixture').disabled=true;status('Microphone off. Director is answering…');
    try{
      const signal=pending.signal;const response=await fetch('/api/realtime-turn',{method:'POST',headers:{'Content-Type':'audio/wav'},body:data,signal});const result=await response.json();if(signal.aborted)return;if(!response.ok)throw Error(result.error||'Voice turn failed');
      if(url)URL.revokeObjectURL(url);const raw=Uint8Array.from(atob(result.audio_wav),c=>c.charCodeAt(0));url=URL.createObjectURL(new Blob([raw],{type:'audio/wav'}));player.src=url;$('voice-words').textContent=result.text||'Spoken guidance ready.';
      try{await player.play();}catch(_){status('Microphone off. Press Play to hear the director.');}
    }catch(e){status(e.name==='AbortError'?'Voice stopped.':e.message);}finally{pending=null;$('hold-talk').disabled=!ready;$('send-fixture').disabled=!ready;}
  }
  const capture=new HoldCapture({media:()=>navigator.mediaDevices.getUserMedia({audio:true,video:false}),context:()=>new AudioContext(),timer:setTimeout,clearTimer:clearTimeout,status,send});
  async function down(){if(!ready||pending)return;holding=true;const generation=++holdGeneration;if(!player.paused){player.pause();player.removeAttribute('src');try{await stopRemote();}catch(_){holding=false;status('Stop could not be confirmed.');return;}}if(holding&&generation===holdGeneration)capture.down();}
  function up(send){holding=false;holdGeneration++;capture.up(send);}
  const button=$('hold-talk');button.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();button.setPointerCapture(e.pointerId);down();};button.onpointerup=()=>up(true);button.onpointercancel=()=>up(false);button.onlostpointercapture=()=>up(false);
  button.onkeydown=e=>{if(e.code==='Space'&&!e.repeat){e.preventDefault();down();}};button.onkeyup=e=>{if(e.code==='Space'){e.preventDefault();up(true);}};button.onblur=()=>up(false);
  async function stop(){up(false);pending?.abort();player.pause();player.removeAttribute('src');if(url){URL.revokeObjectURL(url);url=null;}try{await stopRemote();status('Voice stopped. Microphone off.');}catch(_){status('Microphone off. Server Stop could not be confirmed.');}}
  $('stop-voice').onclick=stop;addEventListener('blur',()=>up(false));document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});addEventListener('pagehide',()=>{up(false);pending?.abort();player.pause();navigator.sendBeacon('/api/realtime-stop',new Blob(['{}'],{type:'application/json'}));});
  $('send-fixture').onclick=async()=>{up(false);const generation=holdGeneration;if(!player.paused){player.pause();await stopRemote();}const file=$('voice-file').files[0];if(!file)return status('Choose a WAV file first.');if(file.size>580096)return status('Choose a clip of at most 12 seconds.');const data=await file.arrayBuffer();if(generation===holdGeneration)send(data);};
  fetch('/api/realtime').then(r=>r.json()).then(s=>{ready=s.enabled;button.disabled=!ready;$('send-fixture').disabled=!ready;status(ready?'Microphone off. Hold to talk to '+s.model+'.':'Voice is off. Explicit server-side API configuration is required.');}).catch(()=>status('Voice status unavailable. Microphone off.'));
}
