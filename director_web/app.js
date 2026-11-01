'use strict';
const $=id=>document.getElementById(id);let state=null,busy=false,recording=null,recordTimer=null,micStream=null,voiceReady=false;
function notice(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);}
async function read(url){const response=await fetch(url,{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Local request failed');return data;}
async function post(url,data){const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const value=await response.json();if(!response.ok)throw Error(value.error||'Local request failed');return value;}
async function action(command,message='Staged. Preview this revision before taking it.'){
 if(!state||busy)return;busy=true;update();
 try{state=await post('/api/action',{expected:state.version,command});notice(message);update();}
 catch(error){notice(error.message,true);try{state=await read('/api/state');update();}catch(_){}}
 finally{busy=false;update();}
}
function fillSelect(id,values,emptyLabel){const el=$(id),selected=el.value;const old=JSON.stringify([...el.options].map(x=>[x.value,x.textContent]));const entries=(emptyLabel!==null?[['',emptyLabel]]:[]).concat(values.map(v=>Array.isArray(v)?v:[v,v]));if(old===JSON.stringify(entries))return;el.replaceChildren(...entries.map(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;}));if(entries.some(x=>x[0]===selected))el.value=selected;}
function requestQueue(){
 const labels={'celebration':'Celebration','hydrate':'Hydrate!','dismiss-alert':'Dismiss fixed alert'};
 $('chat-requests').replaceChildren(...(state.chat_requests||[]).map(item=>{
  const row=document.createElement('li'),message=document.createElement('p'),hint=document.createElement('p'),menu=document.createElement('select');
  message.textContent=item.text;hint.textContent=item.suggested?'Suggested: '+labels[item.suggested]:'No suggested intent. Choose deliberately.';
  const empty=document.createElement('option');empty.value='';empty.textContent='Choose fixed intent…';menu.append(empty);
  for(const [value,label] of Object.entries(labels)){const option=document.createElement('option');option.value=value;option.textContent=label;menu.append(option);}
  menu.value=item.selected||'';menu.disabled=busy;
  menu.onchange=()=>action({action:'request_select',id:item.id,revision:item.revision,intent:menu.value},'Fixed intent selected for this request; Accept remains a separate decision.');
  const accept=document.createElement('button');accept.textContent='Accept selected intent';accept.disabled=busy||!item.selected||!state.armed||state.paused||!state.audience_enabled||!state.program_native||state.program.mode!=='live';
  accept.onclick=()=>action({action:'request_accept',id:item.id,revision:item.revision,intent:item.selected},'Selected fixed request consumed. Inspect the resulting graphic.');
  const reject=document.createElement('button');reject.textContent='Reject';reject.disabled=busy;
  reject.onclick=()=>action({action:'request_reject',id:item.id,revision:item.revision},'Request rejected.');
  row.append(message,hint,menu,accept,reject);return row;
 }));
}
function update(){if(!state)return;
 if(document.activeElement!==$('target'))$('target').value=state.destination;
 $('revision').textContent='Revision '+state.stage_id;
 $('preview-status').textContent=state.preview_refresh_required?'Readiness expired · Preview again':state.previewed?'Rendered · operator review required':state.preview_target?(state.controller_reviewed&&state.preview_target==='obs'?'Waiting for OBS bank '+state.prepared_bank:'Waiting for controller preview'):'Not rendered';
 if(state.staged_page)$('preview-status').textContent+=' · Graphics ACK only; external page loading/pixels unverified. Inspect OBS preview.';
 $('take').disabled=busy||!state.previewed||state.paused||state.preview_target!==$('target').value;
 $('approve-agent').disabled=busy||!state.rendered_ready||state.paused||state.agent_take_approved;
 $('agent-approval').textContent=state.agent_take_approved?'Agent take approved · revision '+state.stage_id:'Agent take not approved';
 $('restore').disabled=busy||!state.can_restore;
 $('undo-camera').disabled=busy||!state.can_undo_camera_layout;
 $('pause').textContent=state.paused?'Resume':'Pause';$('pause').classList.toggle('active',state.paused);
 $('motion').textContent=state.reduced_motion?'Full motion':'Reduce motion';
 $('connection').textContent=(state.obs.connected?'OBS connected · '+(state.armed?'owned control armed':'disarmed'):'OBS disconnected')+' · '+(state.paused?'paused':'local renderer available');
 $('obs-badge').textContent=state.obs.connected?(state.armed?'Armed':'Connected'):'Disconnected';$('obs-detail').textContent=state.error||state.obs.detail;
 $('arm').textContent=(state.arm_preparing||(state.payload_recovery_pending&&state.armed))?'Cancel native preparation':state.armed?'Disarm owned OBS control':'Arm owned OBS control';$('arm').classList.toggle('active',state.armed);
 $('program-mode').textContent=state.program.mode.toUpperCase()+' · '+(state.program_native?(state.current_native_layout||'native layout unknown'):state.program.layout);
 if(document.activeElement!==$('mode'))$('mode').value=state.staged.mode;if(document.activeElement!==$('layout'))$('layout').value=state.staged.layout;
 fillSelect('media',state.catalog,'No media');fillSelect('recipe-list',state.recipes.map(x=>x.name),'Choose…');recipeSteps();
 $('audience').textContent=state.audience_enabled?'Disable local audience input':'Enable local audience input';$('audience').classList.toggle('active',state.audience_enabled);
 const poll=state.local_director_poll;
 $('local-director-polls').textContent=poll&&poll.feature_enabled?'Disable local director Twitch numeric polls':'Enable local director Twitch numeric polls · DEFAULT OFF';
 $('local-poll-status').textContent=poll?(poll.open?'Director numeric gate open (receiver flag/live connection also required)':'Numeric input off/closed')+' · epoch '+(poll.epoch||'none')+' · counters only; streamer directs the next reviewed visual.':'Numeric input DEFAULT OFF';
 $('audience-state').textContent=state.vote?`${state.vote.open?'Open':'Closed'} · ${state.vote.counts.reduce((a,b)=>a+b,0)} local votes. Check numeric-input flag/epoch above.`:'No taken poll; creative requests remain in the approval queue.';
 $('media-state').textContent=`OBS media: ${state.media.state||'unknown'} · volume ${state.media.volume==null?'unknown':Math.round(state.media.volume*100)+'%'}`;
 $('events').replaceChildren(...state.events.slice(-15).reverse().map(e=>{const li=document.createElement('li');li.textContent=new Date(e.at*1000).toLocaleTimeString()+' / '+e.action+' / '+e.outcome;return li;}));
 $('markers').replaceChildren(...state.markers.slice(-8).reverse().map(e=>{const li=document.createElement('li');li.textContent=e.utc.slice(11,19)+' / '+e.label;return li;}));
 fillSelect('page-select',(state.page_catalog||[]).map(x=>[x.id,x.name]),'No page selected');
 const selectedPage=(state.page_catalog||[]).find(x=>state.selected_page&&x.id===state.selected_page.id);
 $('page-stage').disabled=busy||!state.selected_page;
 $('page-status').textContent='Program content: '+(state.program_page?state.program_page.id:'ordinary bound content')+' · Staged: '+(state.staged_page?state.staged_page.id:'ordinary bound content')+'. Selected approved URL: '+(selectedPage?selectedPage.url:'none')+'. Page loading is not verified.';
 fillSelect('material-select',(state.material_catalog||[]).map(x=>[x.id,x.name]),'No material selected');
 $('material-status').textContent=state.selected_material?'Selected reference: '+state.selected_material.id+' · '+state.selected_material.revision.slice(0,12):'No reference selected; no material content sent to a model.';
 requestQueue();
 $('sync').textContent='Local state synced · v'+state.version;
}
function recipeSteps(){const name=$('recipe-list').value;const recipe=state.recipes.find(x=>x.name===name);fillSelect('recipe-step',recipe?recipe.steps.map((s,i)=>[String(i),`${i+1}. ${s.mode} / ${s.composition.name||'Untitled'}`]):[],null);}
async function poll(){try{state=await read('/api/state');update();}catch(_){$('sync').textContent='Controller disconnected · last state only';$('connection').textContent='Controller unreachable';$('take').disabled=true;$('approve-agent').disabled=true;notice('Controller unreachable. No action completion can be confirmed.',true);}setTimeout(poll,700);}
$('operator-form').onsubmit=e=>{e.preventDefault();action({action:'operator',text:$('operator').value,target:$('target').value},'Direction applied through the shared validated grammar.');};
$('mode').onchange=()=>action({action:'stage_patch',fields:{mode:$('mode').value}});
$('layout').onchange=()=>action({action:'stage_patch',fields:{layout:$('layout').value}});
$('compose').onclick=()=>action({action:'compose',title:$('title').value,subtitle:$('subtitle').value,template:$('template').value,accent:$('accent').value,motion:$('animation').value,duration:Number($('duration').value)});
$('revise').onclick=()=>action({action:'revise',title:$('title').value,subtitle:$('subtitle').value,color:$('accent').value,motion:$('animation').value,duration:Number($('duration').value)});
$('preview-button').onclick=()=>action({action:'preview',target:$('target').value},'Preview requested. Watch this revision before taking it.');
$('approve-agent').onclick=()=>action({action:'approve_agent_take'},'This exact preview is approved for one agent take. Changes require new approval.');
$('take').onclick=()=>action({action:'take'},'Take completed. OBS changes, when selected, were checked with state readback; pixels still require review.');
$('undo-camera').onclick=()=>action({action:'undo_camera_layout'},'Previous camera/content arrangement restored. Preview again before another take.');
$('restore').onclick=()=>action({action:'restore'},'Previous segment restored. Media playback remains stopped.');
$('clear').onclick=()=>action({action:'clear'},'Graphics cleared. Scene remains selected.');
$('pause').onclick=()=>action({action:'pause',paused:!state.paused},state.paused?'Director resumed.':'Director paused. Timers and motion frozen; owned media stopped.');
$('motion').onclick=()=>action({action:'reduced_motion',enabled:!state.reduced_motion},'Motion preference updated.');
$('lower-save').onclick=()=>action({action:'stage_patch',fields:{lower:{title:$('lower-title').value,subtitle:$('lower-subtitle').value}}});
$('lower-hide').onclick=()=>action({action:'stage_patch',fields:{lower:null}});
$('timer-stage').onclick=()=>action({action:'stage_patch',fields:{timer:{kind:$('timer-kind').value,seconds:Number($('timer-seconds').value),label:$('timer-label').value}}});
$('timer-remove').onclick=()=>action({action:'stage_patch',fields:{timer:null}});
document.querySelectorAll('[data-timer]').forEach(b=>b.onclick=()=>action({action:'timer_control',operation:b.dataset.timer},'Live timer updated.'));
$('local-director-polls').onclick=()=>action({action:'local_director_polls',enabled:!state.local_director_poll.feature_enabled},'Local director numeric-input permission changed. Receiver flag is also required; no native Twitch poll is created.');
$('vote-stage').onclick=()=>action({action:'stage_patch',fields:{vote:{question:$('vote-question').value,options:$('vote-options').value.split('\n').map(x=>x.trim()).filter(Boolean),kind:$('vote-kind').value}}});
$('vote-remove').onclick=()=>action({action:'stage_patch',fields:{vote:null}});
document.querySelectorAll('[data-vote]').forEach(b=>b.onclick=()=>action({action:'vote_control',operation:b.dataset.vote},'Local vote updated.'));
$('json-load').onclick=()=>{$('json-editor').value=JSON.stringify(state.staged.composition,null,2);};
$('json-apply').onclick=()=>{try{action({action:'stage_patch',fields:{composition:JSON.parse($('json-editor').value)}});}catch(_){notice('Composition JSON could not be parsed.',true);}};
$('recipe-save').onclick=()=>action({action:'recipe_save',name:$('recipe-name').value},'Recipe saved locally.');
$('recipe-append').onclick=()=>action({action:'recipe_save',name:$('recipe-name').value,append:true},'Staged segment appended to the local recipe.');
$('recipe-load').onclick=()=>action({action:'recipe_load',name:$('recipe-list').value,index:Number($('recipe-step').value)});
$('recipe-next').onclick=()=>{const name=$('recipe-list').value;const index=state.recipe_name===name?(state.recipe_index??-1)+1:0;action({action:'recipe_load',name,index});};
$('recipe-delete').onclick=()=>{if(confirm('Delete this locally saved recipe?'))action({action:'recipe_delete',name:$('recipe-list').value},'Recipe deleted.');};
$('recipe-list').onchange=recipeSteps;
$('connect').onclick=()=>{const password=$('obs-password').value;$('obs-password').value='';action({action:'connect',password,port:Number($('obs-port').value)},'Authenticated local OBS connection checked. Set up or refresh owned scenes before arming.');};
$('disconnect').onclick=()=>action({action:'disconnect'},'OBS disconnected. No automatic retry.');
$('refresh-obs').onclick=()=>action({action:'refresh'},'OBS scene state read back.');
$('inputs').onclick=async()=>{try{const data=await read('/api/inputs');const values=data.inputs.map(v=>[v.name,v.name+' / '+v.kind]);fillSelect('camera',values,'None');fillSelect('content',values,'None');notice('Existing inputs listed. Choose operator-owned camera/content.');}catch(e){notice(e.message,true);}};
$('setup-fixtures').onclick=()=>{if(confirm('Set up owned scenes with local synthetic camera/content fixtures? Outputs must be off. This replaces the show recovery checkpoint; it does not use physical devices or external pages.'))action({action:'setup',fixtures:true},'Local fixture scenes set up. Arm explicitly before preview/take.');};
$('setup').onclick=()=>{if(confirm('Set up paired Director scenes in the dedicated collection? Stream, recording and virtual camera must be off.'))action({action:'setup',camera:$('camera').value,content:$('content').value},'Owned scenes set up with outputs off. Arm explicitly before native preview/take.');};
$('arm').onclick=()=>{if(state.arm_preparing||(state.payload_recovery_pending&&state.armed)){post('/api/action',{expected:state.version,command:{action:'arm',enabled:false}}).then(value=>{state=value;notice('Native preparation cancelled. Inspect preview; re-arm explicitly to recover.');update();}).catch(error=>notice(error.message,true));return;}action({action:'arm',enabled:!state.armed},state.armed?'OBS disarmed.':'Owned renderer preparation and identity checks completed. Real frame verification is still required.');};
$('media-stage').onclick=()=>action({action:'stage_patch',fields:{media:$('media').value||null,volume:Number($('volume').value)}});
$('media-play').onclick=()=>action({action:'media_play',name:$('media').value,volume:Number($('volume').value)},'Owned media restart requested and status read back.');
$('media-stop').onclick=()=>action({action:'media_stop'},'Owned OBS media stopped.');
$('page-register').onclick=()=>action({action:'page_register',id:$('page-id').value,name:$('page-name').value,url:$('page-url').value},'Public page registered. Select the exact revision explicitly.');
$('page-remove').onclick=()=>{if($('page-select').value)action({action:'page_remove',id:$('page-select').value},'Page catalog entry removed. Current picture retained; old staging revisions revoked.');};
$('page-choose').onclick=()=>action({action:'page_select',id:$('page-select').value||null},'Page selected; program source unchanged.');
$('page-stage').onclick=()=>{if(state.selected_page)action({action:'stage_selected_page',...state.selected_page},'Page staged as data only. Preview it in OBS before reviewing and taking.');};
$('page-bound').onclick=()=>action({action:'stage_bound_content'},'Ordinary bound content staged. Preview before take.');
$('material-choose').onclick=()=>action({action:'material_select',id:$('material-select').value||null},'Selected one reference revision. Content remains data.');
$('material-register').onclick=()=>action({action:'material_register',id:$('material-id').value,name:$('material-name').value,file:$('material-file').value},'Bounded local material registered; select it explicitly.');
$('requests-clear').onclick=()=>action({action:'requests_clear'},'Pending chat requests cleared.');
$('audience').onclick=()=>action({action:'audience',enabled:!state.audience_enabled},'Local audience forwarding gate updated.');
async function audience(body){try{const receipt=await post('/api/audience',body);notice('Audience receipt: '+receipt.result);}catch(e){notice(e.message,true);}}
$('test-vote').onclick=()=>audience({voter:$('voter').value,message:'!vote '+$('vote-number').value});
$('test-alert').onclick=()=>audience({cue:'Director party'});
$('marker-add').onclick=()=>action({action:'marker',label:$('marker').value},'Local marker added. Export CSV before stopping the controller.');
document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-panel]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.panel').forEach(x=>x.hidden=x.id!=='panel-'+b.dataset.panel);});
addEventListener('keydown',e=>{if(e.target.closest('input,textarea,select,button')||e.repeat)return;if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();$('take').click();}else if(e.key==='Escape'){$('clear').click();}else if(e.key.toLowerCase()==='p'){$('preview-button').click();}else if(e.key.toLowerCase()==='r'){$('restore').click();}else if(e.code==='Space'){e.preventDefault();$('pause').click();}});
async function sendAudio(blob){if(!voiceReady)return notice('Configure local transcription first.',true);$('mic').disabled=true;notice('Transcribing locally. No cloud request.');try{const response=await fetch('/api/audio',{method:'POST',headers:{'Content-Type':blob.type||'audio/wav','X-Event-Id':crypto.randomUUID()},body:blob});const result=await response.json();if(!response.ok)throw Error(result.error);notice(result.silence?'Silence ignored.':'Local transcript: '+result.text+' / '+result.delivery.result);}catch(e){notice(e.message,true);}finally{$('mic').disabled=false;}}
$('audio-send').onclick=()=>{const file=$('audio-file').files[0];if(file)sendAudio(file);else notice('Choose a local WAV, WebM or Ogg clip.',true);};
$('mic').onclick=()=>{location.href='/voice.html';};
read('/api/voice').then(v=>{voiceReady=v.ready;$('voice-status').textContent=v.detail+' · physical microphone not verified.';}).catch(()=>{$('voice-status').textContent='Voice status unavailable.';});
poll();

$('target').onchange=()=>action({action:'destination',target:$('target').value},'Direction destination saved for keyboard, typed and local voice cues.');

$('checkpoint').onclick=()=>action({action:'checkpoint'},'Restore point saved for this sequence of takes.');

async function probeOBS(){try{if(state?.obs.connected&&!busy){state=await read('/api/obs');update();}}catch(_){/* Main state poll reports HTTP failure. */}setTimeout(probeOBS,3000);}probeOBS();

addEventListener('beforeunload',()=>{clearTimeout(recordTimer);micStream?.getTracks().forEach(t=>t.stop());});
