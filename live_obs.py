"""OBS composition renderer. Only owned, off-Program banks may be mutated."""
from pathlib import Path
import hashlib,time
from PIL import Image,ImageDraw,ImageFont
from streamer import Refused

LIVE_WRITES={'CreateScene','CreateSceneItem','CreateInput','SetInputSettings','SetSceneItemEnabled','SetSceneItemTransform','SetCurrentPreviewScene','SetCurrentProgramScene','SetSceneItemIndex','SetInputMute','CreateSourceFilter','SetSourceFilterSettings','SetSourceFilterEnabled'}

def media_settings(path):
    return {'local_file':str(path),'is_local_file':True,'looping':True,'restart_on_activate':False,'close_when_inactive':False}

def _font(size):
    for name in ('Arial.ttf','DejaVuSans.ttf'):
        try:return ImageFont.truetype(name,size)
        except OSError:pass
    return ImageFont.load_default(size=size)

def lower_third_image(folder,title):
    path=Path(folder)/('lower-slim-'+hashlib.sha256(title.encode()).hexdigest()[:24]+'.png')
    if not path.exists():
        image=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(image);font=_font(40)
        while d.textlength(title,font=font)>1712 and font.size>8:font=_font(font.size-1)
        width=min(1792,max(200,round(d.textlength(title,font=font))+80))
        d.rounded_rectangle((64,920,64+width,1004),radius=14,fill='#18152E',outline='#9665FF',width=2)
        d.rounded_rectangle((64,920,72,1004),radius=4,fill='#AEFFCF')
        bounds=d.textbbox((0,0),title,font=font);y=962-(bounds[3]-bounds[1])/2-bounds[1]
        d.text((104,y),title,font=font,fill='white');image.save(path)
    return path

class LiveObs:
    def __init__(self,wire,folder,library,camera_scenes=('Camera',),assets=None,port=60212):
        self.overlay_url=f'http://127.0.0.1:{int(port)}/overlay/twitch'
        self.assets=assets
        self.camera_scenes=tuple(camera_scenes)
        self.wire=wire;self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.library=library
        bg=self.folder/'studio-background.png';border=self.folder/'studio-border.png'
        if not bg.exists():
            im=Image.new('RGB',(1920,1080),'#0d1019');d=ImageDraw.Draw(im)
            for i in range(0,1080,6):d.line((0,i,1920,i),fill=(13+i//70,16+i//100,25+i//40),width=6)
            im.save(bg)
        if not border.exists():
            im=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(im);d.rounded_rectangle((12,12,1907,1067),radius=34,outline='#9665FF',width=14)
            d.line((90,16,500,16),fill='#AEFFCF',width=14);d.line((1420,1063,1830,1063),fill='#AEFFCF',width=14);im.save(border)
        self.background=bg.resolve();self.border=border.resolve()
        label=self.folder/'camera-label.png'
        if not label.exists():
            image=Image.new('RGBA',(1920,1080));d=ImageDraw.Draw(image);d.rounded_rectangle((20,20,360,78),radius=12,fill='#000000AA');d.text((36,32),'Pre-recorded camera',font=_font(28),fill='white');image.save(label)
        self.camera_label=label.resolve()
    def ask(self,method,data=None):return self.wire.request(method,data)
    def status(self):
        return {'studio':self.ask('GetStudioModeEnabled')['studioModeEnabled'],
                'program':self.ask('GetCurrentProgramScene')['currentProgramSceneName'],
                'preview':self.ask('GetCurrentPreviewScene')['currentPreviewSceneName'],
                'outputs':{k:self.ask(m)['outputActive'] for k,m in [('stream','GetStreamStatus'),('record','GetRecordStatus'),('virtual','GetVirtualCamStatus')]}}
    def reaches(self,program,bank):
        scenes={s['sceneName'] for s in self.ask('GetSceneList')['scenes']}
        def walk(name,path=(),group=False):
            if name==bank or name.startswith(bank+':'):return True
            if name in path:raise Refused('Scene graph cycle')
            if name not in scenes and not group:return False
            items=self.ask('GetGroupSceneItemList' if group else 'GetSceneItemList',{'sceneName':name})['sceneItems']
            return any(walk(i['sourceName'],path+(name,),i.get('isGroup',False)) for i in items)
        return walk(program)
    def items(self,bank):return self.ask('GetSceneItemList',{'sceneName':bank})['sceneItems']
    def write(self,bank,method,data,check):
        if method not in LIVE_WRITES:raise Refused('Native mutation refused')
        check(bank);return self.ask(method,data)
    def render(self,bank,c,check):
        scenes={s['sceneName'] for s in self.ask('GetSceneList')['scenes']}
        if bank not in scenes:self.write(bank,'CreateScene',{'sceneName':bank},check)
        if c['camera'] not in self.camera_scenes or c['camera'] not in scenes or self.reaches(c['camera'],bank):raise Refused('Configured camera scene is unavailable or cyclic')
        allowed={*self.camera_scenes,*(bank+':'+key for key in ('background','visual','border','lower','camera-media','clip','animation','camera-label','chat','browser'))}
        if any(i['sourceName'] not in allowed for i in self.items(bank)):raise Refused('Owned composition contains an unexpected source')
        camera=next((i for i in self.items(bank) if i['sourceName']==c['camera']),None)
        # Background first, visual second, camera third, decorations last.
        def input_item(key,kind,settings):
            name=bank+':'+key;inputs={i['inputName']:i['inputKind'] for i in self.ask('GetInputList')['inputs']}
            if name not in inputs:self.write(bank,'CreateInput',{'sceneName':bank,'inputName':name,'inputKind':kind,'inputSettings':settings,'sceneItemEnabled':False},check)
            else:
                if inputs[name]!=kind:raise Refused('Owned input kind changed')
                previous=self.ask('GetInputSettings',{'inputName':name})['inputSettings']
                if any(previous.get(k)!=v for k,v in settings.items()):self.write(bank,'SetInputSettings',{'inputName':name,'inputSettings':settings,'overlay':True},check)
            matches=[i for i in self.items(bank) if i['sourceName']==name]
            if len(matches)!=1:raise Refused('Owned input missing or shared unexpectedly')
            actual=self.ask('GetInputSettings',{'inputName':name})['inputSettings']
            if any(actual.get(k)!=v for k,v in settings.items()):raise Refused('Input settings readback differs')
            return matches[0]['sceneItemId']
        video=self.ask('GetVideoSettings');w,h=video['baseWidth'],video['baseHeight']
        def place(ident,box,visible=True,crop=None):
            x,y,bw,bh=box;t={'positionX':x*w,'positionY':y*h,'boundsType':'OBS_BOUNDS_SCALE_INNER','boundsWidth':bw*w,'boundsHeight':bh*h,'alignment':5,'boundsAlignment':0,'rotation':0,**(crop or {'cropLeft':0,'cropRight':0,'cropTop':0,'cropBottom':0})}
            data={'sceneName':bank,'sceneItemId':ident};self.write(bank,'SetSceneItemTransform',dict(data,sceneItemTransform=t),check)
            self.write(bank,'SetSceneItemEnabled',dict(data,sceneItemEnabled=visible),check)
            actual=self.ask('GetSceneItemTransform',data)['sceneItemTransform']
            if any(abs(actual.get(k,float('inf'))-v)>.6 for k,v in t.items() if isinstance(v,(int,float))):raise Refused('Transform not confirmed')
            actual_item=next(i for i in self.items(bank) if i['sceneItemId']==ident)
            if actual_item['sceneItemEnabled']!=visible:raise Refused('Visibility not confirmed')
        background=input_item('background','image_source',{'file':str(self.background)});place(background,(0,0,1,1))
        visual_id=None
        if c['visual']:
            asset=self.library.assets.get(c['visual'])
            if not asset or asset['kind']!='image':raise Refused('Choose a selected slide or image')
            visual_id=input_item('visual','image_source',{'file':str(self.library.path(asset['id']))})
        else:
            prior=next((i for i in self.items(bank) if i['sourceName']==bank+':visual'),None)
            if prior:place(prior['sceneItemId'],(0,0,1,1),False)
        def media(key,ident,kind):
            if not self.assets or ident not in self.assets.assets or self.assets.assets[ident]['type']!=kind:raise Refused('Choose indexed media')
            item=input_item(key,'ffmpeg_source',media_settings(self.assets.path(ident)))
            self.write(bank,'SetInputMute',{'inputName':bank+':'+key,'inputMuted':True},check)
            if not self.ask('GetInputMute',{'inputName':bank+':'+key})['inputMuted']:raise Refused('Media mute was not confirmed')
            for _ in range(50):
                state=self.ask('GetMediaInputStatus',{'inputName':bank+':'+key})
                geometry=self.ask('GetSceneItemTransform',{'sceneName':bank,'sceneItemId':item})['sceneItemTransform']
                if state['mediaState']=='OBS_MEDIA_STATE_PLAYING' and geometry['sourceWidth']>0 and geometry['sourceHeight']>0:break
                time.sleep(.02)
            else:raise Refused('Native media is not playing with decoded video dimensions')
            return item
        camera_clip=c.get('camera_clip')
        for item in self.items(bank):
            if item['sourceName'] in self.camera_scenes and (camera_clip or item['sourceName']!=c['camera']):
                self.write(bank,'SetSceneItemEnabled',{'sceneName':bank,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':False},check)
        if camera_clip:
            camera={'sceneItemId':media('camera-media',camera_clip,'camera'),'sourceName':bank+':camera-media'}
        else:
            old=next((i for i in self.items(bank) if i['sourceName']==bank+':camera-media'),None)
            if old:self.write(bank,'SetSceneItemEnabled',{'sceneName':bank,'sceneItemId':old['sceneItemId'],'sceneItemEnabled':False},check)
            if not camera:
                self.write(bank,'CreateSceneItem',{'sceneName':bank,'sourceName':c['camera'],'sceneItemEnabled':False},check)
                camera=next(i for i in self.items(bank) if i['sourceName']==c['camera'])
        extras=[]
        for key in ('clip','animation'):
            ident=c.get(key)
            if ident:
                item=media(key,ident,key);box=(.58,.06,.38,.38) if key=='animation' and c.get('clip') else (.04,.04,.92,.92)
                place(item,box,c['layout']!='camera');extras.append(item)
            else:
                old=next((i for i in self.items(bank) if i['sourceName']==bank+':'+key),None)
                if old:place(old['sceneItemId'],(0,0,1,1),False)
        look=c.get('look')
        if look and not camera_clip:raise Refused('LUTs require an owned camera media input')
        if camera_clip:
            name=bank+':camera-media';filters=self.ask('GetSourceFilterList',{'sourceName':name})['filters'];existing=next((f for f in filters if f['filterName']=='Director look'),None)
            if look:
                if self.assets.assets[look]['type']!='lut':raise Refused('Choose an indexed LUT')
                settings={'image_path':str(self.assets.path(look)),'clut_amount':1.0}
                data={'sourceName':name,'filterName':'Director look'}
                if existing is None:self.write(bank,'CreateSourceFilter',dict(data,filterKind='clut_filter',filterSettings=settings),check)
                else:
                    if existing['filterKind']!='clut_filter':raise Refused('Owned LUT filter kind changed')
                    previous=self.ask('GetSourceFilter',data)['filterSettings']
                    if any(previous.get(k)!=v for k,v in settings.items()):self.write(bank,'SetSourceFilterSettings',dict(data,filterSettings=settings),check)
                self.write(bank,'SetSourceFilterEnabled',dict(data,filterEnabled=True),check)
                actual=self.ask('GetSourceFilter',data)
                if not actual['filterEnabled'] or any(actual['filterSettings'].get(k)!=v for k,v in settings.items()):raise Refused('LUT filter not confirmed')
            elif existing:self.write(bank,'SetSourceFilterEnabled',{'sourceName':name,'filterName':'Director look','filterEnabled':False},check)
        cropx=round(w*(1-1/c['zoom'])/2);cropy=round(h*(1-1/c['zoom'])/2);pan=round(c['pan']*w);pan=max(-cropx,min(cropx,pan))
        camera_box=(0,0,1,1)
        if c['layout']=='split':camera_box=(.65,.16,.31,.68)
        elif c['layout']=='pip':camera_box=(.70,.63,.27,.32)
        if visual_id:
            place(visual_id,(.04,.13,.58,.74) if c['layout']=='split' else (.04,.04,.92,.92),c['layout']!='camera')
        place(camera['sceneItemId'],camera_box,True,{'cropLeft':cropx+pan,'cropRight':cropx-pan,'cropTop':cropy,'cropBottom':cropy})
        lower_id=None
        if c['lower_third']:
            path=lower_third_image(self.folder,c['lower_third'])
            lower_id=input_item('lower','image_source',{'file':str(path.resolve())});place(lower_id,(0,0,1,1))
        else:
            prior=next((i for i in self.items(bank) if i['sourceName']==bank+':lower'),None)
            if prior:place(prior['sceneItemId'],(0,0,1,1),False)
        decoration=input_item('border','image_source',{'file':str(self.border)});place(decoration,(0,0,1,1),c['border'])
        browser_id=None
        if c.get('browser'):
            page=c['browser'];css='body { margin: 0 !important; transform: translateY(-'+str(round(page['scroll_y']))+'px) !important; }'
            browser_id=input_item('browser','browser_source',{'url':page['url'],'width':1920,'height':1080,'is_local_file':False,'reroute_audio':False,'css':css});place(browser_id,(.04,.04,.92,.92))
        else:
            old=next((i for i in self.items(bank) if i['sourceName']==bank+':browser'),None)
            if old:place(old['sceneItemId'],(0,0,1,1),False)
        chat_id=None
        if c.get('chat'):
            chat_id=input_item('chat','browser_source',{'url':self.overlay_url,'width':640,'height':1000,'is_local_file':False,'reroute_audio':False});place(chat_id,(.03,.06,.32,.82))
        else:
            old=next((i for i in self.items(bank) if i['sourceName']==bank+':chat'),None)
            if old:place(old['sceneItemId'],(0,0,1,1),False)
        label_id=None
        if camera_clip:
            label_id=input_item('camera-label','image_source',{'file':str(self.camera_label)});place(label_id,(0,0,1,1))
        else:
            old=next((i for i in self.items(bank) if i['sourceName']==bank+':camera-label'),None)
            if old:place(old['sceneItemId'],(0,0,1,1),False)
        order=[background]+([browser_id] if browser_id else [])+([visual_id] if visual_id else [])+extras+[camera['sceneItemId'],decoration]+([lower_id] if lower_id else [])+([label_id] if label_id else [])+([chat_id] if chat_id else [])
        for index,ident in enumerate(order):self.write(bank,'SetSceneItemIndex',{'sceneName':bank,'sceneItemId':ident,'sceneItemIndex':index},check)
        self.write(bank,'SetCurrentPreviewScene',{'sceneName':bank},check)
        if self.status()['preview']!=bank:raise Refused('Preview bank not confirmed')
    def program_take(self,bank,check):self.write(bank,'SetCurrentProgramScene',{'sceneName':bank},check)
