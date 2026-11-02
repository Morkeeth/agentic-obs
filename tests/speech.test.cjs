const assert=require('node:assert/strict');
const {chooseVoice}=require('../web/speech.js');
const voices=[{name:'Albert',lang:'en-US',localService:true},{name:'Samantha',lang:'en-US',localService:true},{name:'Remote',lang:'en-US',localService:false},{name:'Daniel',lang:'en-GB',localService:true}];
assert.equal(chooseVoice(voices).name,'Samantha');
assert.equal(chooseVoice(voices,'Daniel').name,'Daniel');
assert.equal(chooseVoice([voices[0],voices[2]]),null);
console.log('Speech: prefer natural installed voices, honour selection, exclude novelty/remote fallback PASS');
