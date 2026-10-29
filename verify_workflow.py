"""Exercise the running prototype through its actual local HTTP interface."""
import json, urllib.request, urllib.error, datetime
from pathlib import Path
BASE='http://127.0.0.1:8873';ROOT=Path(__file__).resolve().parent;checks=[]
def api(path,data=None):
 r=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r) as q:return json.load(q)
def check(label,condition):
 assert condition,label
 checks.append({'check':label,'result':'PASS'})
start=api('/api/state');normal=start['program']
s=api('/api/compile',{'prompt':'Weather report. Camera right. 9 second countdown. Reveal: 80% CHANCE OF SKILL ISSUE. Make it playful.'});weather=s['draft'];check('Unseen brief changes look, camera and timing',weather['theme']=='weather' and weather['camera']=='right' and weather['duration']==9 and weather['motion']=='playful');check('Draft creation leaves local program intact',s['program']==normal)
s=api('/api/compile',{'prompt':'Camera left. Less movement. Hold reveal for 8 seconds.','revise':True});check('Revision keeps countdown and theme while changing hold/motion',s['draft']['duration']==9 and s['draft']['hold']==8 and s['draft']['motion']=='quiet' and s['draft']['camera']=='left' and s['draft']['theme']=='weather')
s=api('/api/rehearse',{});check('Rehearsal owns an independent draft snapshot',s['rehearsal']['show']==s['draft'] and s['program']==normal)
s=api('/api/take',{});first=s['program'];first_started=s['program_started'];check('Take changes only local program and snapshots prior program',first==s['draft'] and s['restore']['show']==normal)
s=api('/api/compile',{'prompt':'Space mission. Camera right. 15 second countdown. Reveal: COFFEE HAS LANDED.'});check('New draft cannot alter an already taken program',s['program']==first)
s=api('/api/take',{});check('Second take snapshots complete previous program',s['restore']['show']==first and s['restore']['started']==first_started)
s=api('/api/restore',{});check('Restore recovers exact previous program plus clock',s['program']==first and s['program_started']==first_started and s['restore'] is None)
s=api('/api/save',{});saved=s['draft'];s=api('/api/compile',{'prompt':'Science show. 7 second countdown. Reveal: NEW EXPERIMENT.'});s=api('/api/load',{'index':len(s['saved'])-1});check('Save and load roundtrip preserves complete show',s['draft']==saved)
try:api('/api/update',{'fields':{'duration':-1}});raise AssertionError('Invalid countdown accepted')
except urllib.error.HTTPError as e:check('Invalid structured edit rejected',e.code==400)
req=urllib.request.Request(BASE+'/api/take',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://untrusted.example'})
try:urllib.request.urlopen(req);raise AssertionError('Cross-origin action accepted')
except urllib.error.HTTPError as e:check('Cross-origin action rejected',e.code==403)
for path in ['/','/overlay.html','/app.js','/stage.js','/style.css']:
 with urllib.request.urlopen(BASE+path) as q:check('Actual asset serves '+path,q.status==200 and len(q.read())>100)
# Restore presentation to original first example, normal local program, no saved testcases.
# The state API deliberately has no reset endpoint, so use restore by taking normal only in local process restart later.
receipt={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'interface':'actual local HTTP','checks':checks,'limitations':['No subjective live browser or OBS/Twitch proof inferred from HTTP checks.','Prompt compiler is deterministic and limited; no model call.']}
(ROOT/'WORKFLOW-VERIFICATION.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))
