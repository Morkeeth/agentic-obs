/* Continuously refreshed OBS frames. Bounded sampling, not a video transport. */
(function(root){
class FrameMonitor {
 constructor({load,paint,fail,visible,schedule=fn=>setTimeout(fn,250)}){
  Object.assign(this,{load,paint,fail,visible,schedule});this.running=false;
 }
 start(){if(this.running)return;this.running=true;this.tick();}
 stop(){this.running=false;}
 async tick(){
  if(!this.running)return;
  if(this.visible()){
   try{const frame=await this.load();if(this.running)this.paint(frame);}
   catch(error){if(this.running)this.fail(error);}
  }
  if(this.running)this.schedule(()=>this.tick());
 }
}
if(typeof module!=='undefined')module.exports={FrameMonitor};else root.FrameMonitor=FrameMonitor;
})(globalThis);
