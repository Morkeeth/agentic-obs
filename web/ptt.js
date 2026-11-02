/* Reusable held push-to-talk lifecycle; microphone tracks always close. */
(function(root){
class PushToTalk {
  constructor({api,media,Recorder,encode,onreply,onstatus}) {
    Object.assign(this,{api,media,Recorder,encode,onreply,onstatus});
    this.held=false; this.busy=false; this.stream=null; this.recorder=null; this.token=null;
  }
  closeTracks(){if(this.stream) this.stream.getTracks().forEach(t=>t.stop()); this.stream=null;}
  async press(){
    if(this.held || this.busy) return;
    this.held=true; this.busy=true; this.discard=false;
    try {
      const {token}=await this.api('/api/voice/start',{}); this.token=token;
      if(!this.held) return await this.cancel();
      this.stream=await this.media();
      if(!this.held) return await this.cancel();
      const chunks=[]; this.finished=new Promise(resolve=>this.finishResolve=resolve); this.recorder=new this.Recorder(this.stream);
      this.recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      this.recorder.onstop=async()=>{
        this.closeTracks(); clearTimeout(this.timer);
        try {
          if(this.discard)return;
          this.onstatus('Transcribing, directing and staging preview…');
          const audio=await this.encode(new Blob(chunks,{type:this.recorder.mimeType}));
          if(this.discard)return;
          const reply=await this.api('/api/voice/finish',{token:this.token,audio});
          if(!this.discard)this.onreply(reply);
        }catch(e){this.onstatus(e.message);}
        finally{this.busy=false;this.token=null;this.recorder=null;this.finishResolve();}
      };
      this.recorder.start(); this.onstatus('Listening · release to send');
      this.timer=setTimeout(()=>this.release(),15000);
    }catch(e){await this.cancel();this.onstatus(e.message);}
  }
  async release(){
    this.held=false;
    if(this.recorder && this.recorder.state==='recording'){
      this.recorder.stop(); // Complete clip, not arbitrary MediaRecorder slices.
      this.closeTracks();
      return this.finished;
    }
  }
  async cancel(){
    this.held=false;this.discard=true;clearTimeout(this.timer);
    this.closeTracks();
    if(this.recorder && this.recorder.state==='recording')this.recorder.stop();
    try{await this.api('/api/voice/cancel',{});}finally{this.busy=false;this.token=null;}
  }
}
if(typeof module!=='undefined')module.exports={PushToTalk};else root.PushToTalk=PushToTalk;
})(globalThis);
