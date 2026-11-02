global.Blob = global.Blob || require('node:buffer').Blob;
const assert = require('node:assert/strict');
const {PushToTalk} = require('../web/ptt.js');
async function main(){
  let stops=0, sent=0, replies=0, resolveMic;
  const api = async (path, data) => {
    if(path.endsWith('/start')) return {token:'capture'};
    if(path.endsWith('/finish')) { sent++; return {answer:'Ready'}; }
    return {};
  };
  const media = () => new Promise(resolve => resolveMic=resolve);
  class Recorder {
    constructor(){this.state='inactive';}
    start(){this.state='recording';}
    stop(){this.state='inactive'; this.ondataavailable({data:new Blob(['audio'])}); this.onstop();}
  }
  const options={api,media,Recorder,encode:async()=> 'YXVkaW8=',onreply:()=>replies++,onstatus:()=>{}};
  let ptt=new PushToTalk(options);
  const down=ptt.press();
  await Promise.resolve();
  ptt.release(); // Release before microphone permission must not leave an open mic.
  resolveMic({getTracks:()=>[{stop:()=>stops++}]});
  await down;
  assert.equal(stops,1); assert.equal(sent,0);
  ptt=new PushToTalk({...options,media:async()=>({getTracks:()=>[{stop:()=>stops++}]})});
  await ptt.press(); await ptt.release();
  assert.equal(sent,1); assert.equal(replies,1); assert.equal(stops,2);
  await ptt.press(); await ptt.cancel();
  assert.equal(sent,1); assert.equal(stops,3);
  console.log('PTT: early release, complete clip, stop tracks, cancel discard PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
