const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {Blob}=require('node:buffer');
const {HoldCapture,pcmWav}=require('./director_web/voice-ptt.js');
function rig(media){
  const out={stops:0,sends:[],contexts:0,node:null};
  const stream={getTracks:()=>[{stop:()=>out.stops++}]};
  const deps={media:media||(()=>Promise.resolve(stream)),status:()=>{},timer:()=>1,clearTimer:()=>{},send:x=>out.sends.push(x),context:()=>{out.contexts++;return {sampleRate:48000,createMediaStreamSource:()=>({connect:()=>{}}),createScriptProcessor:()=>out.node={connect:()=>{},disconnect:()=>{}},createGain:()=>({gain:{value:1},connect:()=>{}}),close:()=>Promise.resolve(),destination:{}};}};
  return {out,stream,capture:new HoldCapture(deps)};
}
async function run(){
  let r=rig();assert.equal(r.out.contexts,0);assert.equal(r.out.stops,0);
  await r.capture.down();r.out.node.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(9600).fill(.2)}});r.capture.up(true);
  assert.equal(r.out.stops,1);assert.equal(r.out.sends.length,1);const wav=new DataView(r.out.sends[0]);assert.equal(wav.getUint32(24,true),24000);assert.equal(wav.getUint32(40,true),9600);
  r=rig();await r.capture.down();r.capture.up(false);assert.equal(r.out.stops,1);assert.equal(r.out.sends.length,0);
  let resolve;const promise=new Promise(x=>resolve=x);r=rig(()=>promise);const waiting=r.capture.down();r.capture.up(false);resolve(r.stream);await waiting;assert.equal(r.out.stops,1);assert.equal(r.out.contexts,0);assert.equal(r.out.sends.length,0);
  // Exercise the actual DOM handler wiring: release while stopping old playback
  // must not open a mic when that asynchronous request eventually completes.
  const elements={},events={};for(const id of ['voice-reply','voice-state','hold-talk','stop-voice','voice-words','voice-file','send-fixture'])elements[id]={paused:true,files:[],pause(){this.paused=true;},removeAttribute(){},setPointerCapture(){}};
  let finishStop,mediaCalls=0;const stopPending=new Promise(x=>finishStop=x);
  const sandbox={console,DataView,Float32Array,ArrayBuffer,Uint8Array,Blob,AbortController,setTimeout,clearTimeout,URL,
    navigator:{mediaDevices:{getUserMedia:()=>{mediaCalls++;throw Error('No real device in tests');}},sendBeacon:()=>{}},
    document:{hidden:false,getElementById:id=>elements[id],addEventListener:(n,f)=>events[n]=f},addEventListener:(n,f)=>events[n]=f,
    fetch:async url=>url==='/api/realtime'?{json:async()=>({enabled:true,model:'fixture'})}:stopPending};
  vm.runInNewContext(fs.readFileSync('director_web/voice-ptt.js','utf8'),sandbox);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(mediaCalls,0);elements['voice-reply'].paused=false;
  elements['hold-talk'].onpointerdown({button:0,pointerId:1,preventDefault(){}});elements['hold-talk'].onpointerup();finishStop({});await new Promise(resolve=>setImmediate(resolve));assert.equal(mediaCalls,0);
  assert.ok(events.visibilitychange&&events.blur&&events.pagehide);
  console.log('PASS: no startup capture; release sends; cancel discards; permission race closes; playback-interruption race cannot open mic; real DOM stop/blur/hidden handlers present');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
