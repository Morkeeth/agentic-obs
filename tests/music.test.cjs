const assert=require('node:assert/strict');
const {MusicBed}=require('../web/music.js');
async function main(){
 let time=0;const audio={loop:false,play:async()=>{},pause:()=>{},addEventListener:()=>{}};
 const values=[];const gain={gain:{setTargetAtTime:(v)=>values.push(v)},connect:()=>{}};
 const context={currentTime:0,destination:{},resume:async()=>{},createGain:()=>gain,createMediaElementSource:()=>({connect:()=>{}})};
 const m=new MusicBed({audio,context,now:()=>time});await m.play('bed');assert.equal(audio.src,'/library/bed');assert.equal(audio.loop,true);assert.equal(values.at(-1),.12);
 m.level(.1);assert.equal(values.at(-1),.025);time=400;m.level(0);assert.equal(values.at(-1),.025);time=1200;m.level(0);assert.equal(values.at(-1),.12);
 m.duck('director',true);m.level(0);assert.equal(values.at(-1),.025);m.duck('director',false);assert.equal(values.at(-1),.12);m.stop();assert.equal(values.at(-1),0);console.log('Music starts, loops, ducks for operator and director, releases and stops PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
