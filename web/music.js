(function(root){
class MusicBed{
 constructor({audio,context,now=()=>performance.now()}){Object.assign(this,{audio,context,now});this.reasons=new Set();this.current=null;this.lastSpeech=-Infinity;this.gain=context.createGain();this.gain.gain.setTargetAtTime(0,context.currentTime,.05);this.gain.connect(context.destination);this.source=context.createMediaElementSource(audio);this.source.connect(this.gain);this.events=[];}
 async unlock(){await this.context.resume();}
 update(){const volume=!this.current?0:this.reasons.size?.025:.12;this.gain.gain.setTargetAtTime(volume,this.context.currentTime,.12);if(this.events.at(-1)?.volume!==volume)this.events.push({at:this.now(),volume});}
 async play(ident){if(this.current===ident)return;await this.unlock();this.audio.src='/library/'+ident;this.audio.loop=true;await this.audio.play();this.current=ident;this.update();}
 stop(){this.audio.pause();this.current=null;this.update();}
 duck(reason,active){if(active)this.reasons.add(reason);else this.reasons.delete(reason);this.update();}
 level(rms){if(rms>.02)this.lastSpeech=this.now();this.duck('mic',this.now()-this.lastSpeech<800);}
}
if(typeof module!=='undefined')module.exports={MusicBed};else root.MusicBed=MusicBed;
})(globalThis);
