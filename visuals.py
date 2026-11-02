"""Operator-selected visual library and bounded preview composition."""
from copy import deepcopy
import hashlib
import io
import ipaddress
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from streamer import Refused

def validate_page_url(url):
    if not isinstance(url,str) or len(url)>2000:raise Refused('Choose a public HTTPS page')
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise Refused('Choose a public HTTPS page without credentials')
    if p.hostname=='localhost' or p.hostname.endswith(('.local','.internal')):raise Refused('Local pages are not supported')
    try:
        if not ipaddress.ip_address(p.hostname).is_global:raise Refused('Private addresses are not supported')
    except ValueError:pass

class VisualLibrary:
    def __init__(self, folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.assets={};self.slides=[]
        self._demo_slides()
    def catalog(self):return [dict(v) for v in self.assets.values()]
    def path(self,ident):
        if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{24}',ident):raise Refused('Select an existing visual')
        asset=self.assets.get(ident)
        if not asset or asset['kind']!='image':raise Refused('Image is not in the selected library')
        p=self.folder/(ident+'.png')
        if p.is_symlink() or not p.is_file():raise Refused('Selected image is unavailable')
        return p.resolve()
    def add_image(self,name,data):
        if not isinstance(name,str) or not 1<=len(name)<=90 or not 1<=len(data)<=4_000_000:raise Refused('Image name or size refused')
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>20_000_000:raise Refused('Use a PNG, JPEG or WebP under 20 megapixels')
                source.load();image=source.convert('RGBA');image.thumbnail((1920,1080))
            clean=io.BytesIO();image.save(clean,format='PNG');encoded=clean.getvalue()
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:raise Refused('Image decoding failed') from exc
        ident=hashlib.sha256(encoded).hexdigest()[:24]
        path=self.folder/(ident+'.png')
        if not path.exists():path.write_bytes(encoded)
        elif path.read_bytes()!=encoded:raise Refused('Selected image identity differs')
        self.assets[ident]={'id':ident,'name':name,'kind':'image'}
        return dict(self.assets[ident])
    def add_page(self,url):
        validate_page_url(url)
        p=urlsplit(url)
        ident=hashlib.sha256(url.encode()).hexdigest()[:24]
        self.assets[ident]={'id':ident,'name':p.hostname,'kind':'page','url':url}
        return dict(self.assets[ident])
    def _demo_slides(self):
        slides=[('Run your show.','Stay in the conversation.','#85A6FF'),
                ('Ask. Inspect. Refine.','Your next idea stays in preview.','#B9E0C6'),
                ('The director gets a director.','Demo the demo.','#E7BF8B')]
        try:font=ImageFont.truetype('Arial.ttf',104);small=ImageFont.truetype('Arial.ttf',42)
        except OSError:font=ImageFont.load_default(size=100);small=ImageFont.load_default(size=40)
        for index,(title,subtitle,accent) in enumerate(slides):
            image=Image.new('RGB',(1920,1080),'#10151F');draw=ImageDraw.Draw(image)
            draw.ellipse((1450,-150,2050,450),fill=accent)
            draw.text((120,150),'AGENTIC STREAMER',font=small,fill=accent)
            # Keep long slide titles readable on two lines.
            words=title.split();lines=[];line=''
            for word in words:
                candidate=(line+' '+word).strip()
                if draw.textlength(candidate,font=font)>1550:lines.append(line);line=word
                else:line=candidate
            lines.append(line)
            for row,text in enumerate(lines):draw.text((120,370+row*125),text,font=font,fill='white')
            draw.text((120,790),subtitle,font=small,fill='#B5BECC')
            draw.text((120,940),f'{index+1:02d} / 03',font=small,fill=accent)
            output=io.BytesIO();image.save(output,format='PNG')
            asset=self.add_image(f'Demo slide {index+1}',output.getvalue());self.slides.append(asset['id'])

class PreviewVisuals:
    def __init__(self,show,library):
        self.show,self.library=show,library
        self.current={'asset_id':None,'visible':False,'layout':{'x':.05,'y':.05,'width':.9,'height':.9}}
        show.visuals=self
    def state(self):return deepcopy(self.current)
    def _native(self,target):
        if not target['visible'] or not target['asset_id']:
            self.show.native.visual_hide();return
        asset=self.library.assets.get(target['asset_id'])
        if not asset:raise Refused('Visual is no longer selected')
        value=self.library.path(asset['id']) if asset['kind']=='image' else asset['url']
        self.show.native.visual_write(asset['kind'],value,target['layout'])
    def _replace(self,target):
        try:
            self.show._guard()
            self._native(target)
            self.current=deepcopy(target)
        except Exception as exc:
            self.show.enabled=False;self.show.uncertain=True
            raise Refused('Visual operation uncertain; preview control disabled') from exc
    def hide(self):
        self._replace(dict(self.current,visible=False))
    def restore(self,target):
        if target is not None:self._replace(target)
    def command(self,action,asset_id=None,x=None,y=None,width=None,height=None):
        with self.show.lock:
            if not self.show.enabled:raise Refused('Enable preview control first')
            target=self.state()
            if action=='slideshow':target['asset_id']=self.library.slides[0];target['visible']=True
            elif action in ('next','previous'):
                slides=self.library.slides
                if target['asset_id'] not in slides:raise Refused('Start the slideshow first')
                target['asset_id']=slides[(slides.index(target['asset_id'])+(1 if action=='next' else -1))%len(slides)];target['visible']=True
            elif action=='show':
                if asset_id not in self.library.assets:raise Refused('Select an image or page from the library')
                target['asset_id']=asset_id;target['visible']=True
            elif action!='move':raise Refused('Unknown visual action')
            for key,value in {'x':x,'y':y,'width':width,'height':height}.items():
                if value is not None:
                    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):raise Refused('Use bounded numeric layout values')
                    target['layout'][key]=float(value)
            layout=target['layout']
            if not (0<=layout['x']<=1 and 0<=layout['y']<=1 and .1<=layout['width']<=1 and .1<=layout['height']<=1 and layout['x']+layout['width']<=1.001 and layout['y']+layout['height']<=1.001):raise Refused('Keep the visual inside the preview canvas')
            before=self.show._guard();prior=self.state()
            try:
                self._native(target)
                self.show._write(before['graphics']['title'],False,self.show.staging)
                self.current=target
                self.show.checkpoint=deepcopy(before);self.show.content_checkpoint=prior
                return self.show.state()
            except Exception as exc:
                self.show.enabled=False;self.show.uncertain=True
                raise Refused('Visual operation uncertain; preview control disabled') from exc
