"""OBS WebSocket v5 connector with a fixed, preview-only method allowlist."""
import base64
import hashlib
import json
import threading
import uuid
from streamer import Refused

READS = {'GetStudioModeEnabled', 'GetStreamStatus', 'GetRecordStatus', 'GetVirtualCamStatus',
         'GetCurrentProgramScene', 'GetCurrentPreviewScene', 'GetSceneList',
         'GetSceneItemList', 'GetGroupSceneItemList', 'GetInputSettings', 'GetSourceScreenshot', 'GetInputList', 'GetSceneItemTransform', 'GetVideoSettings','GetSourceFilterList','GetSourceFilterDefaultSettings','GetSourceFilter','GetInputMute','GetMediaInputStatus','GetInputKindList','GetInputDefaultSettings','GetStats','GetStreamServiceSettings'}
WRITES = {'SetInputSettings', 'SetSceneItemEnabled', 'SetCurrentPreviewScene', 'CreateInput', 'SetSceneItemTransform', 'CreateScene', 'CreateSceneItem', 'SetCurrentProgramScene', 'SetSceneItemIndex','SetInputMute','CreateSourceFilter','SetSourceFilterSettings','SetSourceFilterEnabled','SetStreamServiceSettings'}

class ObsSocket:
    def __init__(self, port=4455, password=''):
        import websocket
        self.lock = threading.RLock()
        self.ws = websocket.create_connection(f'ws://127.0.0.1:{int(port)}', timeout=15, suppress_origin=True)
        try:
            hello = json.loads(self.ws.recv())
            if hello.get('op') != 0: raise Refused('OBS did not send Hello')
            identify = {'rpcVersion':1, 'eventSubscriptions':0}
            auth = hello['d'].get('authentication')
            if auth:
                secret = base64.b64encode(hashlib.sha256((password+auth['salt']).encode()).digest()).decode()
                identify['authentication'] = base64.b64encode(hashlib.sha256((secret+auth['challenge']).encode()).digest()).decode()
            self.ws.send(json.dumps({'op':1, 'd':identify}))
            if json.loads(self.ws.recv()).get('op') != 2: raise Refused('OBS authentication failed')
        except Exception:
            self.ws.close()
            raise Refused('OBS connection failed') from None
    def request(self, method, data=None):
        if method not in READS | WRITES: raise Refused('OBS method is not allowed')
        with self.lock:
            ident = uuid.uuid4().hex
            self.ws.send(json.dumps({'op':6, 'd':{'requestType':method, 'requestId':ident, 'requestData':data or {}}}))
            # Subscriptions are disabled. Reject unrelated replies rather than replay.
            reply = json.loads(self.ws.recv())
            d = reply.get('d', {})
            if reply.get('op') != 7 or d.get('requestId') != ident or not d.get('requestStatus', {}).get('result'):
                raise Refused('OBS request was not confirmed')
            return d.get('responseData', {})
    def close(self): self.ws.close()

class ObsAdapter:
    def __init__(self, wire, staging='Staging', graphics='graphics'):
        self.wire, self.staging, self.graphics = wire, staging, graphics
        self.before_write = None
        self.protected_sources = (graphics,'preview-image','preview-page')
    def bind_guard(self, guard): self.before_write = guard
    def _safe(self):
        if self.before_write is None: raise Refused('Preview controller is not bound')
        self.before_write()
    def read(self):
        ask = self.wire.request
        studio = ask('GetStudioModeEnabled')['studioModeEnabled']
        outputs = {key: ask(method)['outputActive'] for key,method in (
            ('stream','GetStreamStatus'),('record','GetRecordStatus'),('virtual','GetVirtualCamStatus'))}
        program = ask('GetCurrentProgramScene')['currentProgramSceneName']
        preview = ask('GetCurrentPreviewScene')['currentPreviewSceneName'] if studio else None
        graph, items = {}, {}
        def visit(name, group=False):
            if name in graph: return
            graph[name] = []
            response = ask('GetGroupSceneItemList' if group else 'GetSceneItemList', {'sceneName':name})
            items[name] = response['sceneItems']
            for item in items[name]:
                graph[name].append(item['sourceName'])
                if item.get('isGroup') or item.get('sourceType') == 'OBS_SOURCE_TYPE_SCENE':
                    visit(item['sourceName'], item.get('isGroup', False))
        for scene in ask('GetSceneList')['scenes']: visit(scene['sceneName'])
        settings = ask('GetInputSettings', {'inputName':self.graphics})
        if settings.get('inputKind') not in ('text_gdiplus','text_gdiplus_v2','text_gdiplus_v3','text_ft2_source','text_ft2_source_v2'):
            raise Refused('Owned title must be a native OBS text input')
        own = [item for item in items.get(self.staging, []) if item['sourceName'] == self.graphics]
        if len(own) != 1: raise Refused('Expected one owned title item in staging')
        return {'studio':studio, 'outputs':outputs, 'program':program, 'preview':preview,
                'scenes':graph, 'graphics':{'title':settings['inputSettings'].get('text',''),
                                           'visible':own[0]['sceneItemEnabled']}}
    def _visual_item(self,name):
        items=self.wire.request('GetSceneItemList',{'sceneName':self.staging})['sceneItems']
        found=[item for item in items if item['sourceName']==name]
        if len(found)!=1:raise Refused('Owned visual must occur once in staging')
        return found[0]
    def visual_hide(self):
        items=self.wire.request('GetSceneItemList',{'sceneName':self.staging})['sceneItems']
        for item in items:
            if item['sourceName'] in ('preview-image','preview-page'):
                self._safe()
                self.wire.request('SetSceneItemEnabled',{'sceneName':self.staging,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':False})
                if self._visual_item(item['sourceName'])['sceneItemEnabled']:raise Refused('Visual hide not confirmed')
    def visual_write(self,kind,value,layout):
        if kind not in ('image','page'):raise Refused('Unsupported visual kind')
        name='preview-image' if kind=='image' else 'preview-page'
        input_kind='image_source' if kind=='image' else 'browser_source'
        settings={'file':str(value)} if kind=='image' else {'url':value,'width':1920,'height':1080,'is_local_file':False,'reroute_audio':False}
        inputs=self.wire.request('GetInputList')['inputs']
        existing=[x for x in inputs if x['inputName']==name]
        self._safe()
        if not existing:
            self.wire.request('CreateInput',{'sceneName':self.staging,'inputName':name,'inputKind':input_kind,'inputSettings':settings,'sceneItemEnabled':False})
        elif len(existing)!=1 or existing[0]['inputKind']!=input_kind:
            raise Refused('Owned visual source kind changed')
        item=self._visual_item(name)
        actual=self.wire.request('GetInputSettings',{'inputName':name})
        if actual['inputKind']!=input_kind:raise Refused('Owned visual identity changed')
        self.visual_hide()
        self._safe();self.wire.request('SetInputSettings',{'inputName':name,'inputSettings':settings,'overlay':True})
        video=self.wire.request('GetVideoSettings')
        transform={'positionX':layout['x']*video['baseWidth'],'positionY':layout['y']*video['baseHeight'],
                   'boundsType':'OBS_BOUNDS_SCALE_INNER','boundsWidth':layout['width']*video['baseWidth'],
                   'boundsHeight':layout['height']*video['baseHeight'],'alignment':5,'boundsAlignment':0,'rotation':0}
        self._safe();self.wire.request('SetSceneItemTransform',{'sceneName':self.staging,'sceneItemId':item['sceneItemId'],'sceneItemTransform':transform})
        self._safe();self.wire.request('SetSceneItemEnabled',{'sceneName':self.staging,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':True})
        confirmed=self.wire.request('GetInputSettings',{'inputName':name})['inputSettings']
        geometry=self.wire.request('GetSceneItemTransform',{'sceneName':self.staging,'sceneItemId':item['sceneItemId']})['sceneItemTransform']
        if any(confirmed.get(k)!=v for k,v in settings.items()) or not self._visual_item(name)['sceneItemEnabled']:
            raise Refused('Visual input not confirmed')
        if any(abs(geometry.get(k,float('inf'))-v)>.5 for k,v in transform.items() if isinstance(v,(int,float))):
            raise Refused('Visual geometry not confirmed')
    def frames(self):
        before = self.read()
        result = {}
        for key in ('program','preview'):
            source = before[key]
            if source is None: raise Refused('Native preview frame is unavailable')
            image = self.wire.request('GetSourceScreenshot', {'sourceName':source, 'imageFormat':'png',
                                      'imageWidth':1280, 'imageHeight':720})['imageData']
            if not isinstance(image,str) or not image.startswith('data:image/png;base64,') or len(image)>4_000_000:
                raise Refused('Native screenshot was not confirmed')
            result[key] = image
        after = self.read()
        if any(before[k] != after[k] for k in ('program','preview','graphics')):
            raise Refused('Scene changed during capture; request fresh native frames')
        return result
    def graphics_write(self, title, visible):
        # Fresh item lookup: IDs may change after operator edits a scene.
        items = self.wire.request('GetSceneItemList', {'sceneName':self.staging})['sceneItems']
        owned = [x for x in items if x['sourceName'] == self.graphics]
        if len(owned) != 1: raise Refused('Owned title identity changed')
        self._safe()
        self.wire.request('SetInputSettings', {'inputName':self.graphics, 'inputSettings':{'text':title}, 'overlay':True})
        self._safe()
        self.wire.request('SetSceneItemEnabled', {'sceneName':self.staging, 'sceneItemId':owned[0]['sceneItemId'], 'sceneItemEnabled':visible})
    def preview_write(self, scene):
        self._safe()
        self.wire.request('SetCurrentPreviewScene', {'sceneName':scene})

class RehearsalNative:
    """Explicitly synthetic adapter; never connects to OBS or devices."""
    def __init__(self):
        self.preview, self.program = 'Staging', 'Camera'
        self.title, self.visible = '', False
        self.active_visual=None
    def read(self):
        return {'studio':True, 'outputs':{'stream':False,'record':False,'virtual':False},
                'program':self.program, 'preview':self.preview,
                'scenes':{'Camera':['synthetic-camera'],'Staging':['graphics']},
                'graphics':{'title':self.title,'visible':self.visible}, 'synthetic':True}
    def visual_write(self,kind,value,layout):self.active_visual={'kind':kind,'value':str(value),'layout':dict(layout)}
    def visual_hide(self):self.active_visual=None
    def graphics_write(self, title, visible): self.title, self.visible = title, visible
    def preview_write(self, scene): self.preview = scene
