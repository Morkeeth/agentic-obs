const assert=require('node:assert/strict');
const {FrameMonitor}=require('../web/monitor.js');
async function main(){
 let calls=0, pending, painted=0, timers=[],hidden=false;
 const monitor=new FrameMonitor({load:()=>{calls++;return new Promise(resolve=>pending=resolve)},paint:()=>painted++,fail:()=>{},visible:()=>!hidden,schedule:fn=>timers.push(fn)});
 monitor.start();assert.equal(calls,1);
 monitor.start();assert.equal(calls,1); // never overlap native frame requests
 pending({program:'p',preview:'v'});await Promise.resolve();await Promise.resolve();
 assert.equal(painted,1);assert.equal(timers.length,1);
 hidden=true;timers.shift()();assert.equal(calls,1);
 hidden=false;timers.shift()();assert.equal(calls,2);
 monitor.stop();pending({program:'stale',preview:'stale'});await Promise.resolve();await Promise.resolve();
 assert.equal(painted,1);assert.equal(timers.length,0);
 console.log('Native monitor: continuous refresh, one in flight, hidden pause, stale frame discard PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
