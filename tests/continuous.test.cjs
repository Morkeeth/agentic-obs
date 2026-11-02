global.Blob=global.Blob||require('node:buffer').Blob;
const assert=require('node:assert/strict');
const {ContinuousVoice}=require('../web/continuous.js');
async function main(){
 let stopped=0,requests=[],replies=0,held,resolveReply,time=0;
 class Recorder{constructor(){this.state='inactive'}start(){this.state='recording'}stop(){this.state='inactive';this.ondataavailable({data:new Blob(['complete audio'])});this.onstop()}}
 const api=async(path,data)=>{requests.push(path);if(path.endsWith('/start'))return {token:'t'};if(path.endsWith('/finish'))return await new Promise(resolve=>resolveReply=resolve);return {}};
 const voice=new ContinuousVoice({api,media:async()=>({getTracks:()=>[{stop:()=>stopped++}]}),Recorder,encode:async()=> 'YXVkaW8=',onreply:()=>replies++,onstatus:()=>{},detect:()=>()=>{},schedule:()=>1,unschedule:()=>{},now:()=>time});
 await voice.start();
 voice.cut();await Promise.resolve();assert.equal(requests.length,0); // silence never consumes a model call
 voice.level(.1);time=1000;voice.level(.1);time=2000;voice.level(0);time=2800;voice.level(0);
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(requests.filter(p=>p.endsWith('/finish')).length,1);
 assert.equal(voice.recorder.state,'recording'); // microphone continues while director thinks
 voice.heard=true;voice.cut();voice.heard=true;voice.cut();
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(requests.filter(p=>p.endsWith('/finish')).length,1); // one request, one pending clip
 await voice.stop();resolveReply({answer:'Late'});
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(replies,0);assert.equal(stopped,1);assert.equal(voice.active,false);
 console.log('Continuous voice: silence ignored, capture during model work, bounded queue, stop discards late reply PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
async function browserTimerBinding(){
 const oldSet=global.setTimeout,oldClear=global.clearTimeout;
 try{
  global.setTimeout=function(){assert.equal(this,global);return 1};
  global.clearTimeout=function(){assert.equal(this,global)};
  class Recorder{start(){this.state='recording'}stop(){this.state='inactive';this.onstop()}}
  let closed=0;
  const voice=new ContinuousVoice({api:async()=>({}),media:async()=>({getTracks:()=>[{stop:()=>closed++}]}),Recorder,encode:async()=>'',onreply:()=>{},onstatus:()=>{},detect:()=>()=>{}});
  await voice.start();assert.equal(voice.active,true);await voice.stop();assert.equal(closed,1);
  console.log('Browser timer receiver and microphone cleanup PASS');
 }finally{global.setTimeout=oldSet;global.clearTimeout=oldClear;}
}
browserTimerBinding().catch(e=>{console.error(e);process.exitCode=1});

async function detectorCleanupFailure(){
 let tracks=0;
 class Recorder{start(){this.state='recording'}stop(){this.state='inactive';this.onstop()}}
 const voice=new ContinuousVoice({api:async()=>({}),media:async()=>({getTracks:()=>[{stop:()=>tracks++}]}),Recorder,encode:async()=>'',onreply:()=>{},onstatus:()=>{},detect:()=>()=>{throw Error('detector failed')},schedule:()=>1,unschedule:()=>{}});
 await voice.start();await voice.stop();assert.equal(tracks,1);assert.equal(voice.active,false);
 console.log('Detector cleanup failure still releases microphone PASS');
}
detectorCleanupFailure().catch(e=>{console.error(e);process.exitCode=1});
async function transientNoiseIgnored(){
 let time=0,requests=0;
 class Recorder{start(){this.state='recording'}stop(){this.state='inactive';this.ondataavailable({data:new Blob(['noise'])});this.onstop()}}
 const voice=new ContinuousVoice({api:async()=>{requests++;return{}},media:async()=>({getTracks:()=>[{stop:()=>{}}]}),Recorder,encode:async()=>'',onreply:()=>{},onstatus:()=>{},detect:()=>()=>{},schedule:()=>1,unschedule:()=>{},now:()=>time});
 await voice.start();voice.level(.1);time=100;voice.level(0);time=1200;voice.level(0);voice.cut();
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(requests,0);await voice.stop();console.log('Brief noise burst does not create director request PASS');
}
transientNoiseIgnored().catch(e=>{console.error(e);process.exitCode=1});

async function preserveQueuedPhrases(){
 let number=0,received=[],resolveCurrent;
 class Recorder{start(){this.state='recording'}stop(){this.state='inactive';this.ondataavailable({data:new Blob([String(++number)])});this.onstop()}}
 const voice=new ContinuousVoice({api:async(path,data)=>{if(path.endsWith('/start'))return{token:'t'};if(path.endsWith('/finish')){received.push(data.audio);return await new Promise(r=>resolveCurrent=r)}return{}},media:async()=>({getTracks:()=>[{stop:()=>{}}]}),Recorder,encode:async blob=>blob.text(),onreply:()=>{},onstatus:()=>{},detect:()=>()=>{},schedule:()=>1,unschedule:()=>{}});
 await voice.start();voice.heard=true;voice.cut();
 for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));
 voice.heard=true;voice.cut();voice.heard=true;voice.cut();
 for(let j=0;j<3;j++){
  resolveCurrent({answer:'ok'});
  for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));
 }
 assert.deepEqual(received,['1','2','3']);await voice.stop();console.log('Several queued phrases execute in order without a reset PASS');
}
preserveQueuedPhrases().catch(e=>{console.error(e);process.exitCode=1});
