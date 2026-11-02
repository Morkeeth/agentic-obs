"""Fast operator cues and independent preview/program composition banks."""
from copy import deepcopy
import re
import threading
from streamer import Refused,assert_preview_outputs

BANKS=('Director A','Director B')
LIVE_ACTIONS={'live_zoom':'zoom in on me','live_wide':'switch to the wide shot','live_slides_left':'put the slides left','live_pip':'go picture in picture','live_border':'add a border','live_no_border':'remove border','live_pan_left':'pan left','live_pan_right':'pan right'}
CUES={
 'zoom in on me':'zoom','zoom in':'zoom','zoom out':'wide','switch to the wide shot':'wide','wide shot':'wide',
 'close up':'close','close-up':'close','switch to the close up':'close','switch to the close-up':'close',
 'put the slides left':'slides_left','slides left':'slides_left','show the slides':'slides_left',
 'add a border':'border','remove the border':'no_border','remove border':'no_border',
 'go picture-in-picture':'pip','go picture in picture':'pip','picture in picture':'pip',
 'pan left':'pan_left','pan right':'pan_right','pan write':'pan_right','center the camera':'center',
 'clear preview':'clear','clear the graphic':'clear','restore preview':'restore','undo':'restore',
 'show chat':'chat','show the chat':'chat','hide chat':'hide_chat','hide the chat':'hide_chat','start slideshow':'slides_left','show slideshow':'slides_left','show the slideshow':'slides_left','next slide':'next','previous slide':'previous','take it':'take','go live':'take',
 'make it warmer':'warm','warmer':'warm','cinematic look':'cinematic','make it cinematic':'cinematic','normal':'normal','normal look':'normal','cool look':'cool','make it cooler':'cool',
 'play some music':'music','play music':'music','stop music':'stop_music','stop the music':'stop_music',
 'stop animation':'stop_animation','stop the animation':'stop_animation','show the desk clip':'desk',
}
def clean(text):return re.sub(r'^director[, :]*','',text.strip(),flags=re.I).strip().rstrip('.!?')
def parts(text):return [p.strip() for p in re.split(r'[.,;!?]\s*(?:and\s+)?|\n+|\s+and\s+',clean(text),flags=re.I) if p.strip()]
def recognize(text):
    if not isinstance(text,str):return None
    cue=clean(text).lower()
    if cue in CUES:return CUES[cue]
    if cue.startswith('switch to camera '):return 'camera'
    if re.match(r'^(?:add a )?lower third(?: that says| saying| says)?(?: |$)',cue):return 'lower'
    segments=parts(text)
    if 1<len(segments)<=6 and all(recognize(p) not in (None,'take','batch') for p in segments):return 'batch'
    if re.fullmatch(r'(?:show|play)(?: the)? .+ clip',cue):return 'clip'
    if re.fullmatch(r'(?:show|play)(?: the)? .+',cue):return 'animation'
    return None

class LiveStudio:
    def __init__(self,native,slides,camera_scenes=('Camera',),assets=None,chat_status=None):
        self.camera_scenes=tuple(camera_scenes)
        if not self.camera_scenes or any(x in BANKS or ':' in x for x in self.camera_scenes):raise Refused('Choose independent camera scenes')
        self.native=native;self.slides=list(slides);self.assets=assets;self.chat_status=chat_status;self.lock=threading.RLock();self.uncertain=False
        wide=assets.find('wide','camera')['id'] if assets else None
        self.current={'zoom':1.,'pan':0.,'layout':'camera','border':False,'visual':None,'lower_third':'','camera':self.camera_scenes[0],'camera_clip':wide,'clip':None,'animation':None,'look':None,'music':None,'chat':False,'browser':None}
        self.previous=None;self.staged_bank=None
    def state(self):return {'composition':deepcopy(self.current),'bank':self.staged_bank,'uncertain':self.uncertain,'restore_available':self.previous is not None}
    def safe(self,bank,expected_program=None):
        s=self.native.status()
        if not s['studio']:raise Refused('Studio Mode is required')
        assert_preview_outputs(s['outputs'])
        if expected_program is not None and s['program']!=expected_program:
            self.uncertain=True
            raise Refused('Program changed during preview staging; inspect OBS before retrying')
        if self.native.reaches(s['program'],bank):raise Refused('This composition is in Program; edit the other preview bank')
        return s
    def selected(self,tag,kind):
        if not self.assets:raise Refused('The approved asset library is unavailable')
        return self.assets.find(tag,kind)['id']
    def target(self,target,text,action):
        if action=='zoom':target['zoom']=min(2.,target['zoom']+.25)
        elif action in ('wide','desk','close'):
            target.update(zoom=1.,pan=0.,layout='camera')
            if self.assets:target['camera_clip']=self.selected('close' if action=='close' else 'wide','camera')
        elif action in ('pan_left','pan_right'):target['pan']=max(-.25,min(.25,target['pan']+(-.1 if action=='pan_left' else .1)))
        elif action=='center':target['pan']=0.
        elif action=='camera':
            chosen=re.sub(r'^switch to camera +','',clean(text),flags=re.I)
            if chosen not in self.camera_scenes:raise Refused('Choose a configured camera scene')
            target.update(camera=chosen,camera_clip=None,zoom=1.,pan=0.)
        elif action in ('slides_left','pip'):
            if not self.slides:raise Refused('Select slides first')
            if action=='slides_left':target.update(clip=None,animation=None,visual=target['visual'] or self.slides[0])
            elif not target['clip'] and not target['animation']:target['visual']=target['visual'] or self.slides[0]
            target['layout']='split' if action=='slides_left' else 'pip'
        elif action in ('next','previous'):
            if target['visual'] not in self.slides:raise Refused('Show the slides first')
            target['visual']=self.slides[(self.slides.index(target['visual'])+(1 if action=='next' else -1))%len(self.slides)]
        elif action in ('border','no_border'):target['border']=action=='border'
        elif action=='lower':
            title=re.sub(r'^(?:add a )?lower third(?: that says| saying| says)?[ :]*','',clean(text),flags=re.I).strip() or 'Agentic Streamer'
            if len(title)>180 or any(ord(c)<32 for c in title):raise Refused('Use a printable lower third under 180 characters')
            target['lower_third']=title
        elif action in ('warm','cinematic','cool'):target['look']=self.selected('warmer' if action=='warm' else action,'lut')
        elif action=='chat':
            if not self.chat_status or not self.chat_status()['connected']:raise Refused('Connect a public Twitch channel first')
            target['chat']=True
        elif action=='hide_chat':target['chat']=False
        elif action=='normal':target['look']=None
        elif action=='music':target['music']=self.selected('music','music')
        elif action=='stop_music':target['music']=None
        elif action in ('clip','animation'):
            tag=re.sub(r'^(?:show|play)(?: the)? +','',clean(text),flags=re.I)
            tag=re.sub(r' (?:clip|animation|overlay)$','',tag,flags=re.I)
            target[action]=self.selected(tag.lower(),action);target['layout']='pip'
        elif action=='stop_animation':target['animation']=None;target['layout']='pip' if target['clip'] or target['visual'] else 'camera'
        elif action=='clear':target.update(border=False,visual=None,clip=None,animation=None,chat=False,browser=None,lower_third='',layout='camera')
        elif action=='restore':
            if self.previous is None:raise Refused('No composition to restore')
            target=deepcopy(self.previous)
        else:raise Refused('Unknown preview action')
        return target
    def stage_browser(self,page,check=None):
        from visuals import validate_page_url
        import math
        validate_page_url(page['url']);scroll=page.get('scroll_y',0)
        if not isinstance(scroll,(int,float)) or not math.isfinite(scroll) or not 0<=scroll<=100000:raise Refused('Invalid browser scroll position')
        with self.lock:
            state=self.native.status();bank=next((b for b in BANKS if not self.native.reaches(state['program'],b)),None)
            if bank is None:raise Refused('Both preview banks are in Program')
            def guard(b):
                if check:check()
                return self.safe(b,expected_program=state['program'])
            guard(bank);target=deepcopy(self.current);target.update(browser={k:page[k] for k in ('url','title','scroll_y')},clip=None,animation=None,visual=None,layout='pip')
            try:self.native.render(bank,target,guard);guard(bank)
            except Exception as exc:self.uncertain=True;raise Refused('Browser preview uncertain; inspect OBS') from exc
            self.previous=deepcopy(self.current);self.current=target;self.staged_bank=bank;self.uncertain=False
    def execute(self,text,source='typed',check=None):
        action=recognize(text)
        if not action or source not in ('typed','voice','chat_preview'):raise Refused('Unrecognized operator cue')
        if source=='chat_preview' and action not in ('zoom','lower'):raise Refused('Chat can only stage a bounded title or zoom')
        with self.lock:
            s=self.native.status();bank=next((b for b in BANKS if not self.native.reaches(s['program'],b)),None)
            if bank is None:raise Refused('Both preview banks are referenced in Program')
            def guard(target):
                if check:check()
                return self.safe(target,expected_program=s['program'])
            if action=='take':
                if source!='voice':raise Refused('Say Take it yourself to accept this preview')
                if any(s['outputs'].values()):raise Refused('Local Take requires all outputs off; choose your live shot in OBS')
                if self.uncertain or self.staged_bank!=s['preview'] or self.staged_bank not in BANKS:raise Refused('Stage and inspect an owned preview first')
                guard(self.staged_bank);self.native.program_take(self.staged_bank,guard)
                after=self.native.status()
                if after['program']!=self.staged_bank or any(after['outputs'].values()):self.uncertain=True;raise Refused('Local Program take was not confirmed')
                return {'answer':'Accepted in local Program. Broadcast outputs remain off.','staged':True,'taken':True,'live':self.state()}
            guard(bank);target=deepcopy(self.current)
            for segment in (parts(text) if action=='batch' else [text]):target=self.target(target,segment,recognize(segment))
            try:self.native.render(bank,target,guard);guard(bank)
            except Exception as exc:
                self.uncertain=True
                raise Refused('Composition uncertain: '+str(exc) if isinstance(exc,Refused) else 'Composition transport failed; inspect OBS') from exc
            self.previous=deepcopy(self.current);self.current=target;self.staged_bank=bank;self.uncertain=False
            return {'answer':{'zoom':'Closer.','wide':'Wide shot.','close':'Close-up.','slides_left':'Slides left, camera right.','pip':'Picture in picture.','border':'Border added.','batch':'Scene ready in preview.'}.get(action,'Updated in preview.'),'staged':True,'taken':False,'live':self.state()}
