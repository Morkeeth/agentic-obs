/* Continuous operator capture, complete utterances, four queued clips. */
(function(root){
class ContinuousVoice{
 constructor({api,media,Recorder,encode,onreply,onstatus,detect,schedule=(fn,ms)=>setTimeout(fn,ms),unschedule=id=>clearTimeout(id),now=()=>performance.now()}){
  Object.assign(this,{api,media,Recorder,encode,onreply,onstatus,detect,schedule,unschedule,now});
  this.active=false;this.busy=false;this.pending=[];this.epoch=0;
 }
 async start(){
  if(this.active)return;
  const epoch=++this.epoch;this.active=true;
  try{
   const stream=await this.media();
   if(!this.active||epoch!==this.epoch){stream.getTracks().forEach(t=>t.stop());return;}
   this.stream=stream;this.closeDetector=this.detect(stream,rms=>this.level(rms));
   this.begin();this.onstatus('Listening continuously · pause between directions · Stop listening ends capture');
  }catch(e){await this.stop();this.onstatus(e.message);}
 }
 begin(){
  if(!this.active)return;
  const chunks=[],epoch=this.epoch;
  this.heard=false;this.lastSpeech=0;this.speechStart=null;
  const recorder=new this.Recorder(this.stream);this.recorder=recorder;
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  recorder.onstop=()=>{
   this.unschedule(this.timer);
   const speech=this.heard;
   if(!this.active||epoch!==this.epoch)return;
   if(speech){
    if(this.pending.length>=4)this.onstatus('Four phrases are waiting · pause before the next direction');
    else this.pending.push({blob:new Blob(chunks,{type:recorder.mimeType}),epoch});
   }
   this.begin();this.drain();
  };
  recorder.start();this.timer=this.schedule(()=>this.cut(),12000);
 }
 level(rms){
  if(!this.active)return;
  const now=this.now();
  if(rms>.02){
   if(this.speechStart===null)this.speechStart=now;
   if(now-this.speechStart>=200)this.heard=true;
   this.lastSpeech=now;
  }else{
   if(!this.heard)this.speechStart=null;
   if(this.heard&&now-this.lastSpeech>800)this.cut();
  }
 }
 cut(){if(this.recorder&&this.recorder.state==='recording')this.recorder.stop();}
 async drain(){
  if(this.busy||!this.pending.length||!this.active)return;
  this.busy=true;const clip=this.pending.shift();
  try{
   const audio=await this.encode(clip.blob);
   if(!this.active||clip.epoch!==this.epoch)return;
   const {token}=await this.api('/api/voice/start',{});
   if(!this.active||clip.epoch!==this.epoch){await this.api('/api/voice/cancel',{});return;}
   this.onstatus('Listening · director is processing your last phrase');
   const reply=await this.api('/api/voice/finish',{audio,token});
   if(this.active&&clip.epoch===this.epoch)this.onreply(reply);
  }catch(e){if(this.active)this.onstatus(e.message+' · microphone remains on');}
  finally{this.busy=false;if(this.active)this.drain();}
 }
 async stop(){
  this.active=false;this.epoch++;this.pending=[];this.unschedule(this.timer);
  try{if(this.closeDetector)this.closeDetector();}catch(e){/* Always release the microphone even if the analyser failed. */}this.closeDetector=null;
  if(this.stream)this.stream.getTracks().forEach(t=>t.stop());this.stream=null;
  this.cut();await this.api('/api/voice/cancel',{});
 }
}
function detectSpeech(stream,level){
 const context=new (window.AudioContext||window.webkitAudioContext)();
 context.resume().catch(()=>{});
 const source=context.createMediaStreamSource(stream),analyser=context.createAnalyser();
 analyser.fftSize=1024;source.connect(analyser);const samples=new Float32Array(analyser.fftSize);
 const timer=setInterval(()=>{analyser.getFloatTimeDomainData(samples);level(Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length));},100);
 return()=>{clearInterval(timer);source.disconnect();context.close();};
}
if(typeof module!=='undefined')module.exports={ContinuousVoice};else{root.ContinuousVoice=ContinuousVoice;root.detectSpeech=detectSpeech;}
})(globalThis);
