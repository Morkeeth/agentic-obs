"""Preview-only show state. No program transitions or broadcast operations."""
from copy import deepcopy
import re
import threading

class Refused(ValueError):
    pass

def assert_preview_outputs(outputs):
    if not isinstance(outputs,dict) or set(outputs)!={'stream','record','virtual'} or any(type(value) is not bool for value in outputs.values()):raise Refused('Output state is unavailable')
    if outputs['record']:raise Refused('Preview refused: OBS recording is active')
    if outputs['virtual']:raise Refused('Preview refused: OBS virtual camera is active')
    # An operator-started stream is allowed; this never starts or changes an output.

class Show:
    def __init__(self, native, staging='Staging', graphics='graphics', director=None):
        self.native, self.staging, self.graphics = native, staging, graphics
        self.director = director or RehearsalDirector()
        self.enabled = False
        self.uncertain = False
        self.checkpoint = None
        self.content_checkpoint = None
        self.visuals = None
        self.live = None
        self.twitch = None
        self.browser = None
        self.revision = 0
        self.proposal = None
        self.conversation = []
        self.cancellation_check = None
        self.lock = threading.RLock()
        if hasattr(native, 'bind_guard'): native.bind_guard(self._guard)

    def state(self):
        with self.lock:
            return {'enabled': self.enabled, 'uncertain': self.uncertain,'allow_live_preview':True,
                    'revision': self.revision, 'proposal': deepcopy(self.proposal),
                    'restore_available': self.checkpoint is not None,
                    'visual': self.visuals.state() if self.visuals else None,
                    'director': self.director.name, 'browser': self.browser.state() if self.browser else None, 'live': self.live.state() if self.live else None, 'native': self.native.read()}

    def _guard(self):
        if self.cancellation_check: self.cancellation_check()
        s = self.native.read()
        if not s.get('studio'):raise Refused('Studio Mode is required')
        assert_preview_outputs(s.get('outputs'))
        scenes = s.get('scenes', {})
        if s.get('program') not in scenes or self.staging not in scenes:
            raise Refused('Scene identity is unavailable')
        def contains(node, path=()):
            if node in getattr(self.native,'protected_sources',(self.graphics,)): return True
            if node in path: raise Refused('Cyclic scene graph')
            return any(contains(child, path + (node,)) for child in scenes.get(node, []))
        if s['program'] == self.staging or contains(s['program']):
            raise Refused('Camera scene safe guard: staging graphics would affect program')
        if self.graphics not in scenes[self.staging]:
            raise Refused('Owned graphics must be a direct staging scene item')
        return s

    def enable(self):
        with self.lock:
            self._guard()
            self.enabled, self.uncertain = True, False
            return self.state()

    def disable(self):
        with self.lock:
            self.enabled = False
            return {'enabled': False}

    def _write(self, title, visible, preview):
        if not self.enabled: raise Refused('Enable preview control in the workspace first')
        try:
            before = self._guard()
            self.native.graphics_write(title, visible)
            # Read the live graph again immediately before the second write.
            self._guard()
            self.native.preview_write(preview)
            after = self._guard()
            if after['program'] != before['program'] or after['preview'] != preview or after['graphics'] != {'title': title, 'visible': visible}:
                raise Refused('Native readback did not confirm the requested preview')
            self.revision += 1
            return self.state()
        except Exception as exc:
            self.enabled, self.uncertain = False, True
            raise Refused('Preview operation uncertain; disabled, inspect native state before enabling') from exc

    def stage(self, title):
        with self.lock:
            if not self.enabled: raise Refused('Enable preview control first')
            if not isinstance(title, str) or not title.strip() or len(title) > 180 or any(ord(c) < 32 for c in title):
                raise Refused('Title must be 1–180 printable characters')
            before = self._guard() if self.enabled else None
            content_before = self.visuals.state() if self.visuals else None
            if self.visuals: self.visuals.hide()
            result = self._write(title, True, self.staging)
            self.checkpoint = deepcopy(before)
            self.content_checkpoint = content_before
            return self.state()

    def clear(self):
        with self.lock:
            if not self.enabled: raise Refused('Preview control is disabled')
            before = self._guard()
            content_before = self.visuals.state() if self.visuals else None
            result = self._write(before['graphics']['title'], False, before['preview'])
            if self.visuals: self.visuals.hide()
            self.content_checkpoint = content_before
            self.checkpoint = deepcopy(before)
            return self.state()

    def restore(self):
        with self.lock:
            if not self.checkpoint: raise Refused('No restore point')
            target = deepcopy(self.checkpoint)
            content_target = deepcopy(self.content_checkpoint)
            content_before = self.visuals.state() if self.visuals else None
            before = self._guard() if self.enabled else None
            self._write(target['graphics']['title'], target['graphics']['visible'], target['preview'])
            if self.visuals: self.visuals.restore(content_target)
            self.checkpoint = deepcopy(before)
            self.content_checkpoint = content_before
            return self.state()

    def direct(self, text, source='typed'):
        if source not in ('typed', 'voice'): raise Refused('Only the operator can direct the show')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise Refused('Direction must be 1–2000 characters')
        # Model work does not hold the mutation lock and never writes native state.
        reply = self.director.ask(text, {'revision': self.revision, 'preview_only': True, 'live_composition': self.live.state() if self.live else None,
            'conversation': deepcopy(self.conversation[-8:]), 'visual': self.visuals.state() if self.visuals else None,
            'selected_assets': self.visuals.library.catalog() if self.visuals else []})
        if not isinstance(reply, dict) or not isinstance(reply.get('answer'), str) or not 1 <= len(reply['answer']) <= 2000:
            raise Refused('Director returned no bounded answer')
        proposal = reply.get('proposal')
        if proposal is not None:
            if not isinstance(proposal, dict) or not set(proposal)<= {'title','action','asset_id','x','y','width','height'} or not isinstance(proposal.get('title'), str) or not 1 <= len(proposal['title']) <= 180 or proposal.get('action','title') not in ('title','show','slideshow','next','previous','move','clear','restore','none','live_zoom','live_wide','live_slides_left','live_pip','live_border','live_no_border','live_pan_left','live_pan_right'):
                raise Refused('Director proposal must contain only a bounded title')
        with self.lock:
            self.proposal = deepcopy(proposal)
            self.conversation.extend([{'operator':text},{'director':reply['answer'],'proposal':deepcopy(proposal)}])
            self.conversation=self.conversation[-8:]
        return {'answer': reply['answer'], 'proposal': proposal, 'source': source, 'native_writes': 0}

    def plan_direction(self,text,source='typed'):
        if source not in ('typed','voice'): raise Refused('Only the operator can direct the show')
        if not isinstance(text,str) or not 1<=len(text.strip())<=2000: raise Refused('Direction must be 1–2000 characters')
        if self.browser and self.browser.recognizes(text):return {'answer':'Opening the dedicated browser.','proposal':None,'source':source,'operator_browser':text,'native_writes':0}
        if self.live:
            from live import recognize
            if recognize(text):return {'answer':'Preparing your direction.','proposal':None,'source':source,'operator_cue':text,'native_writes':0}
        cue=re.sub(r'^director[, :]*','',text.strip(),flags=re.I).strip().rstrip('.!?').lower()
        action=None;args={}
        if cue in ('show slideshow','show the slideshow','start slideshow','show slides','show the slides'):action='slideshow'
        elif cue in ('next slide','next'):action='next'
        elif cue in ('previous slide','previous','go back one slide'):action='previous'
        elif cue in ('clear','clear graphic','clear the graphic','clear preview'):action='clear'
        elif cue in ('restore','restore preview','restore the preview','undo'):action='restore'
        elif cue in ('stop listening','stop microphone','stop the microphone'):
            return {'answer':'Microphone stopped.','proposal':None,'source':source,'native_writes':0,'stop_listening':True}
        elif self.visuals and self.visuals.current['asset_id'] and cue in ('move it left','move left','move it right','move right','make it smaller','make it bigger','centre it','center it'):
            action='move';layout=self.visuals.state()['layout']
            if 'left' in cue:args['x']=max(0,layout['x']-.1)
            elif 'right' in cue:args['x']=min(1-layout['width'],layout['x']+.1)
            elif 'smaller' in cue:args.update(width=max(.1,layout['width']*.8),height=max(.1,layout['height']*.8))
            elif 'bigger' in cue:args.update(width=min(1-layout['x'],layout['width']*1.2),height=min(1-layout['y'],layout['height']*1.2))
            else:args.update(x=(1-layout['width'])/2,y=(1-layout['height'])/2)
        if action:
            return {'answer':{'clear':'Preview cleared.','restore':'Previous preview restored.'}.get(action,'Updated in preview. Your camera stays safe.'),
                    'proposal':dict(title='Preview direction',action=action,**args),'source':source,'native_writes':0}
        return self.direct(text,source)

    def apply_plan(self,reply):
        if self.browser and reply.get('operator_browser'):
            if not self.enabled or not self.live:raise Refused('Enable preview control first')
            if self.cancellation_check:self.cancellation_check()
            page=self.browser.execute(reply['operator_browser']);self.live.stage_browser(page,self.cancellation_check)
            return {'answer':page['answer'],'staged':True,'source':reply['source'],'proposal':None,'state':self.state(),'live':self.live.state(),'browser':page}
        if self.live and reply.get('operator_cue'):
            if not self.enabled:raise Refused('Enable preview control first')
            result=self.live.execute(reply['operator_cue'],reply['source'],self.cancellation_check)
            return dict(result,source=reply['source'],proposal=None,state=self.state())
        proposal=reply.get('proposal')
        if not proposal or not self.enabled:return dict(reply,staged=False,state=self.state())
        action=proposal.get('action','title')
        if self.live and action.startswith('live_'):
            from live import LIVE_ACTIONS
            result=self.live.execute(LIVE_ACTIONS[action],reply['source'],self.cancellation_check)
            return dict(result,source=reply['source'],proposal=proposal,state=self.state())
        if self.live and action=='title':
            result=self.live.execute('lower third '+proposal['title'],reply['source'],self.cancellation_check)
            return dict(result,source=reply['source'],proposal=proposal,state=self.state())
        if action=='title':state=self.stage(proposal['title'])
        elif action=='clear':state=self.clear()
        elif action=='restore':state=self.restore()
        elif action=='none':return dict(reply,staged=False,state=self.state())
        else:
            if not self.visuals:raise Refused('Visual library is unavailable')
            state=self.visuals.command(action,**{key:proposal[key] for key in ('asset_id','x','y','width','height') if key in proposal and proposal[key] is not None and proposal[key]!=''})
        return dict({key:value for key,value in reply.items() if key!='native_writes'},staged=True,state=state)

    def chat_preview(self,command,check=None):
        # Separate fixed-intent path: chat text is never sent to the model or operator parser.
        with self.lock:
            if check:check()
            if not self.enabled:raise Refused('Enable preview control before chat commands')
            if not isinstance(command,dict) or command.get('action') not in ('title','zoom'):raise Refused('Unknown chat preview intent')
            if command['action']=='title':
                title=command.get('title')
                if not isinstance(title,str) or not 1<=len(title)<=180 or any(ord(c)<32 for c in title):raise Refused('Invalid chat title')
                if self.live:return self.live.execute('lower third '+title,'chat_preview',check)
                return self.stage(title)
            if not self.live:raise Refused('Chat zoom requires native live composition')
            return self.live.execute('zoom in on me','chat_preview',check)

    def operator_direction(self,text,source='typed'):
        reply=self.plan_direction(text,source)
        if source=='voice' or reply.get('operator_cue') or reply.get('operator_browser') or (reply.get('proposal') or {}).get('action'):
            return self.apply_plan(reply)
        return reply

class RehearsalDirector:
    name = 'Account-free rehearsal rules (no model)'
    def ask(self, text, context):
        title = 'Be right back' if re.search(r'be[- ]right[- ]back|\bbrb\b',text,re.I) else 'Demo the demo' if 'demo' in text.lower() else re.sub(r'^director[, :]*', '', text, flags=re.I).strip()
        return {'answer': 'I will prepare the title in preview. Inspect it before any further action.',
                'proposal': {'title': title[:180]}}
