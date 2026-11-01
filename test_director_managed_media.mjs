// Actual fixed peer script, injected WebRTC/device/browser effects. No WebKit, device or network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(process.argv[2], 'utf8');
const script=source.match(/<script nonce="DIRECTOR_NONCE">([\s\S]*?)<\/script>/)[1];
const sdp='v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n';
function fixture({denied=false,pending=false,ice=false}={}) {
 const events=[],timers=[],peers=[],tracks=[];let permissions=0,resolvePermission;
 const player={muted:true,srcObject:null,plays:0,pauses:0,play(){this.plays++;return Promise.resolve();},pause(){this.pauses++;}};
 const makeStream=()=>{const track={kind:'audio',stopped:false,stop(){this.stopped=true;}};tracks.push(track);return {getTracks:()=>[track],getAudioTracks:()=>[track]};};
 class Peer {
  constructor(){peers.push(this);this.iceGatheringState=ice?'gathering':'complete';this.connectionState='new';}
  addTransceiver(kind,options){assert.equal(kind,'audio');assert.equal(options.direction,'sendrecv');this.sender={track:null,replaceTrack:async track=>{this.sender.track=track;}};return {sender:this.sender};}
  createDataChannel(){return {close(){},send(){throw new Error('client event injection forbidden');}};}
  async createOffer(){return {type:'offer',sdp};}async setLocalDescription(value){this.localDescription=value;}
  async setRemoteDescription(value){assert.equal(value.type,'answer');this.answer=value;}
  addEventListener(){} removeEventListener(){} close(){this.closed=true;}
 }
 const window={isSecureContext:true,RTCPeerConnection:Peer,webkit:{messageHandlers:{directorMedia:{postMessage(value){events.push(value);}}}},addEventListener(){}};
 vm.runInNewContext(script,{window,RTCPeerConnection:Peer,MediaStream:class {constructor(items){this.items=items;}},document:{getElementById:()=>player},
  navigator:{mediaDevices:{getUserMedia:()=>{permissions++;if(denied)return Promise.reject(new Error('PRIVATE_DEVICE_ERROR'));if(pending)return new Promise(resolve=>{resolvePermission=()=>resolve(makeStream());});return Promise.resolve(makeStream());}}},
  setTimeout:callback=>{timers.push(callback);return timers.length;},clearTimeout(){}});
 const call=(type,fields={})=>window.directorPeer({type,generation:'current',...fields});
 return {events,timers,peers,tracks,player,call,permissions:()=>permissions,resolve:()=>resolvePermission()};
}
{
 const f=fixture();assert.equal(f.permissions(),0);await f.call('prepare');assert.equal(f.permissions(),0);
 assert.equal(f.events.at(-1).type,'offer');await f.call('answer',{sdp});assert.equal(f.permissions(),0);
 await f.call('capture');assert.equal(f.permissions(),1);assert.equal(f.events.at(-1).type,'capturing');assert.equal(f.peers[0].sender.track,f.tracks[0]);
 // No remote audio packet is required to acknowledge actual capture readiness.
 assert.equal(f.player.plays,0);f.peers[0].ontrack({track:{kind:'audio'}});assert.equal(f.player.plays,1);
 await f.call('mute');assert(f.tracks[0].stopped);assert.equal(f.peers[0].sender.track,null);assert(f.player.muted);
 await f.call('unmute');assert.equal(f.permissions(),2);assert.equal(f.events.at(-1).type,'capturing');
 await f.call('stop');assert(f.tracks.every(t=>t.stopped));assert(f.peers[0].closed);assert.equal(f.player.srcObject,null);
}
{
 const f=fixture({pending:true});await f.call('prepare');await f.call('answer',{sdp});const capturing=f.call('capture');await Promise.resolve();
 await f.call('stop');f.resolve();await capturing;assert(f.tracks[0].stopped);assert(!f.events.some(e=>e.type==='capturing'));
}
{
 const f=fixture({pending:true});await f.call('prepare');await f.call('answer',{sdp});const capturing=f.call('capture');await Promise.resolve();
 await f.call('mute');f.resolve();await capturing;assert(f.tracks[0].stopped);assert(!f.events.some(e=>e.type==='capturing'));
}
{
 const f=fixture({denied:true});await f.call('prepare');await f.call('answer',{sdp});await f.call('capture');assert(f.peers[0].closed);assert.equal(f.events.at(-1).type,'error');
 assert(!JSON.stringify(f.events).includes('PRIVATE_DEVICE_ERROR'));
}
{
 const f=fixture({ice:true});const preparing=f.call('prepare');await new Promise(setImmediate);
 assert.equal(f.permissions(),0);assert.equal(f.timers.length,1);f.timers[0]();await preparing;assert.equal(f.events.at(-1).type,'error');assert(f.peers[0].closed);
}
{
 const f=fixture();await f.call('prepare');await f.call('answer',{sdp,generation:'old'});assert.equal(f.peers[0].answer,undefined);
 await f.call('take');assert.equal(f.events.at(-1).type,'error');assert.equal(f.permissions(),0);
}
console.log('PASS: fixed WebRTC page with injected media/ICE/permission/stop/mute effects; no real WebKit, audio or network.');
