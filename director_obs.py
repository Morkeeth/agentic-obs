"""Owned OBS v5 operations. No arbitrary RPC endpoint or output controls.

Design follows obsproject's public protocol and the attributed native core;
this expanded connector never reads the old connector's private configuration.
"""
import base64
import hashlib
import json
import math
from pathlib import Path
import time
import uuid
from director_pages import public_url

import websocket

COLLECTION = 'Expanded Director'
SCENES = {mode: tuple(f'Director / {mode.title()} {bank}' for bank in ('A', 'B'))
          for mode in ('starting', 'live', 'brb', 'ending')}
OWNED = tuple(scene for pair in SCENES.values() for scene in pair)
LEGACY_OVERLAY = 'Director / Graphics'
OVERLAYS = {bank: 'Director / Graphics '+bank for bank in ('A', 'B')}
OVERLAY = OVERLAYS['A']
PAGES = {bank: 'Director / Page '+bank for bank in ('A','B')}
MEDIA = 'Director / Media'
BASES = {mode: 'Director / Base '+mode.title() for mode in ('starting','brb','ending')}
READS = {'GetCurrentSceneTransitionCursor', 'GetProfileList', 'GetSourceScreenshot', 'GetVersion', 'GetSceneCollectionList', 'GetSceneList', 'GetStudioModeEnabled',
         'GetSpecialInputs', 'GetInputList', 'GetInputKindList', 'GetInputSettings', 'GetSceneItemList', 'GetSceneItemTransform',
         'GetInputVolume', 'GetMediaInputStatus', 'GetVideoSettings', 'GetStreamStatus',
         'GetRecordStatus', 'GetVirtualCamStatus'}
WRITES = {'PressInputPropertiesButton', 'RemoveSceneItem', 'CreateScene', 'CreateInput', 'CreateSceneItem', 'SetSceneItemIndex',
          'SetSceneItemTransform', 'SetSceneItemEnabled', 'SetCurrentPreviewScene',
          'SetCurrentProgramScene', 'SetInputSettings', 'SetInputVolume', 'TriggerMediaInputAction'}


def operative_transform(transform):
    """Ignore only dimensions that OBS does not apply under OBS_BOUNDS_NONE.

    Its getter may report zero here, while its setter requires supplied bounds
    dimensions >=1. Omitting them preserves the stored values without inventing
    visible sizes. Positions/scales/crop and every active bounds value remain.
    """
    result = dict(transform)
    if result.get('boundsType') == 'OBS_BOUNDS_NONE':
        result.pop('boundsWidth', None)
        result.pop('boundsHeight', None)
    return result


class ObsError(Exception):
    """Safe operator-facing error: server bodies and credentials are never included."""


class VirtualCameraUnavailable(ObsError):
    """OBS explicitly reports the virtual-camera feature unavailable."""


class ObsClient:
    def __init__(self, password, port=4455, factory=None):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Invalid local OBS port')
        if not isinstance(password, str) or not password or len(password) > 512:
            raise ValueError('Enter the authenticated OBS password for this session')
        self.ws = None
        self.audit = []
        self.connected = False
        try:
            self.ws = (factory or websocket.create_connection)(
                f'ws://127.0.0.1:{port}', timeout=3, redirect_limit=0,
                http_no_proxy=['127.0.0.1'], suppress_origin=True)
            hello = json.loads(self.ws.recv())
            auth = hello.get('d', {}).get('authentication')
            if hello.get('op') != 0 or not isinstance(auth, dict):
                raise ObsError('Authenticated OBS v5 is required')
            enc = lambda value: base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()
            response = enc(enc(password + auth['salt']) + auth['challenge'])
            self.ws.send(json.dumps({'op': 1, 'd': {'rpcVersion': 1, 'eventSubscriptions': 0, 'authentication': response}}))
            if json.loads(self.ws.recv()).get('op') != 2:
                raise ObsError('OBS identification refused')
            self.connected = True
            self.req('GetVersion')
        except Exception:
            self.close()
            raise ObsError('OBS connection/authentication failed; check local OBS and password') from None

    def close(self):
        self.connected = False
        if self.ws is not None:
            try: self.ws.close()
            except Exception: pass
            try: self.ws.shutdown()
            except Exception: pass

    def req(self, kind, data=None, *, timeout=3):
        if kind not in READS | WRITES:
            raise ObsError('OBS request is outside director capability')
        if kind == 'PressInputPropertiesButton' and (not isinstance(data, dict) or set(data) != {'inputName','propertyName'}
                or data['inputName'] not in OVERLAYS.values() or data['propertyName'] != 'refreshnocache'):
            raise ObsError('Only the owned graphics refresh button is permitted')
        if not self.connected:
            raise ObsError('OBS disconnected; reconnect explicitly')
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        timeout = min(3, timeout)
        if timeout <= 0: raise ObsError('OBS observation deadline elapsed')
        try:
            self.ws.settimeout(timeout)
            self.ws.send(json.dumps({'op': 6, 'd': {'requestType': kind, 'requestId': request_id, 'requestData': data or {}}}))
            for _ in range(64):
                if time.monotonic() - started > timeout:
                    break
                self.ws.settimeout(max(.001, timeout-(time.monotonic()-started)))
                out = json.loads(self.ws.recv())
                result = out.get('d', {})
                if out.get('op') != 7 or result.get('requestId') != request_id:
                    continue
                if result.get('requestType') != kind:
                    raise ObsError('OBS response type mismatch')
                ok = result.get('requestStatus', {}).get('result') is True
                self.audit.append({'request': kind, 'id': request_id, 'ack': ok,
                                   'ms': round((time.monotonic()-started)*1000, 3)})
                self.audit[:] = self.audit[-400:]
                if not ok:
                    status = result.get('requestStatus', {})
                    if (kind == 'GetVirtualCamStatus' and status.get('code') == 604
                            and status.get('comment') == 'VirtualCam is not available.'):
                        raise VirtualCameraUnavailable('OBS virtual camera is unavailable')
                    raise ObsError(f'OBS refused {kind}; refresh state before retrying')
                response = result.get('responseData', {})
                if not isinstance(response, dict): raise ObsError('Malformed OBS response')
                return response
            raise ObsError('OBS response timeout or stale responses')
        except ObsError:
            raise
        except Exception:
            self.close()
            raise ObsError('OBS transport lost; action completion is uncertain, reconnect and inspect') from None


class OwnedOBS:
    def __init__(self, client, http_port=8880, media_root=None):
        self.client = client
        self.client_http_port = http_port
        self.urls = {bank: f'http://127.0.0.1:{http_port}/overlay.html?channel=bank-{bank}&renderer=obs' for bank in ('A', 'B')}
        self.url = self.urls['A']
        self.base_urls = {mode: f'http://127.0.0.1:{http_port}/base-{mode}.html' for mode in BASES}
        self.media_root = Path(media_root or Path(__file__).resolve().parent/'.director-media').resolve()
        self.profile = None
        self.bindings = {}
        self.prepared = None
        self.page_urls = {bank:'about:blank' for bank in PAGES}
        self.bank_content = {bank:False for bank in PAGES}
        self.page_reviewed = {bank:False for bank in PAGES}
        self.transition_timeout = 5.0
        self.transition_poll_interval = .02

    def req(self, kind, data=None, *, timeout=3):
        return self.client.req(kind, data, timeout=timeout)

    def wait_transition(self, expected_program=None, expected_preview=None, invariant_program=None):
        """Observe inactivity, not ACK latency. Reads only; never retry a mutation.

        OBS reports the new program before Fade finishes, then swaps Studio
        preview on completion. Cursor 1.0 means inactive. Every read shares this
        bounded observation deadline; the interval only paces active polling.
        """
        deadline = time.monotonic()+self.transition_timeout
        def read(kind):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ObsError('OBS transition completion timed out; outcome uncertain')
            return self.req(kind, timeout=min(3, remaining))
        def cursor():
            value = read('GetCurrentSceneTransitionCursor').get('transitionCursor')
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ObsError('OBS transition cursor readback invalid; outcome uncertain')
            return value
        while True:
            if cursor() == 1.0:
                actual = read('GetSceneList')
                if invariant_program is not None and actual.get('currentProgramSceneName') != invariant_program:
                    raise ObsError('OBS program changed during preview observation; outcome uncertain')
                # A transition starting during readback cannot count as settled.
                if cursor() == 1.0:
                    matches = ((expected_program is None or actual.get('currentProgramSceneName') == expected_program)
                               and (expected_preview is None or actual.get('currentPreviewSceneName') == expected_preview))
                    if matches: return actual
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ObsError('OBS transition completion timed out; outcome uncertain')
            time.sleep(min(self.transition_poll_interval, remaining))

    def guard(self):
        profile = self.req('GetProfileList').get('currentProfileName')
        if not isinstance(profile, str) or not profile:
            raise ObsError('OBS profile readback unavailable')
        if self.profile is not None and profile != self.profile:
            raise ObsError('OBS profile changed; disarmed, reconnect and inspect')
        self.profile = profile
        if self.req('GetSceneCollectionList').get('currentSceneCollectionName') != COLLECTION:
            raise ObsError('Select the dedicated Expanded Director scene collection in OBS')
        if not self.req('GetStudioModeEnabled').get('studioModeEnabled'):
            raise ObsError('Enable OBS Studio Mode')
        video = self.req('GetVideoSettings')
        if (video.get('baseWidth'), video.get('baseHeight')) != (1920, 1080):
            raise ObsError('Owned collection must use a 1920 × 1080 base canvas')

    def output_states(self):
        states = {}
        for name, kind in (('stream', 'GetStreamStatus'), ('record', 'GetRecordStatus'), ('virtual_camera', 'GetVirtualCamStatus')):
            try:
                active = self.req(kind).get('outputActive')
            except VirtualCameraUnavailable:
                if kind != 'GetVirtualCamStatus':
                    raise
                states[name] = None  # Explicitly unavailable, never an invented False.
                continue
            if type(active) is not bool:
                raise ObsError('OBS output state is unknown; refuse arming')
            states[name] = active
        return states

    def outputs_off(self):
        if any(value is True for value in self.output_states().values()):
            raise ObsError('Setup/arming requires stream, recording and virtual camera off')

    def inputs(self):
        self.guard()
        return [{'name': x['inputName'], 'kind': x['inputKind']}
                for x in self.req('GetInputList').get('inputs', []) if not x['inputName'].startswith('Director /')]

    def items(self, scene):
        if scene not in OWNED: raise ObsError('Unowned scene')
        return self.req('GetSceneItemList', {'sceneName': scene}).get('sceneItems', [])

    def item(self, scene, source):
        found = [x for x in self.items(scene) if x['sourceName'] == source]
        if len(found) != 1: raise ObsError('Owned scene item missing or duplicated; run setup with outputs off')
        return found[0]['sceneItemId']

    def source_guard(self):
        self.page_guard()
        for bank, name in OVERLAYS.items():
            info = self.req('GetInputSettings', {'inputName': name})
            settings = info.get('inputSettings', {})
            if info.get('inputKind') != 'browser_source' or settings.get('url') != self.urls[bank] or settings.get('width') != 1920 or settings.get('height') != 1080 or settings.get('shutdown') is not False:
                raise ObsError('Owned bank browser source identity changed; disarmed')
        for mode, name in BASES.items():
            info = self.req('GetInputSettings', {'inputName': name})
            settings = info.get('inputSettings', {})
            if (info.get('inputKind') != 'browser_source' or settings.get('url') != self.base_urls[mode]
                    or settings.get('width') != 1920 or settings.get('height') != 1080 or settings.get('shutdown') is not False):
                raise ObsError('Owned base browser source identity changed; run explicit outputs-off setup if missing')
        media = self.req('GetInputSettings', {'inputName': MEDIA})
        if media.get('inputKind') != 'ffmpeg_source': raise ObsError('Owned media identity changed')
        settings = media.get('inputSettings', {})
        local_file = settings.get('local_file', '')
        if settings.get('is_local_file') is not True:
            raise ObsError('Owned media must use a local file')
        if local_file:
            path = Path(local_file)
            if '..' in path.parts or path.parent != self.media_root or path.is_symlink() or path.suffix.lower() not in ('.wav', '.mp3', '.ogg', '.mp4', '.webm', '.mov'):
                raise ObsError('Owned media file is outside the selected local catalog')

    def page_guard(self):
        for bank,name in PAGES.items():
            result=self.req('GetInputSettings',{'inputName':name});settings=result.get('inputSettings',{})
            if result.get('inputKind')!='browser_source' or any(settings.get(k)!=v for k,v in
                {'url':self.page_urls[bank],'width':1920,'height':1080,'shutdown':False,'reroute_audio':False}.items()):
                raise ObsError('Owned page browser identity/settings changed')

    def set_page_url(self,bank,url,*,invariant_program=None):
        if url!='about:blank':public_url(url)
        self.verify()
        current=self.req('GetSceneList')['currentProgramSceneName']
        if invariant_program is not None and (current!=invariant_program or current[-1]==bank):
            raise ObsError('Program changed before inactive page preparation; disarmed')
        if current==SCENES['live'][0 if bank=='A' else 1] and any(x['sourceName']==PAGES[bank] and x['sceneItemEnabled'] for x in self.items(current)):
            raise ObsError('Refusing to rewrite an on-air page browser')
        if self.page_urls[bank]==url:return
        self.page_reviewed[bank]=False
        self.req('SetInputSettings',{'inputName':PAGES[bank],'inputSettings':{'url':url},'overlay':True})
        actual=self.req('GetInputSettings',{'inputName':PAGES[bank]})
        if actual.get('inputKind')!='browser_source' or actual.get('inputSettings',{}).get('url')!=url:
            raise ObsError('Page URL readback not confirmed; load and pixels remain unverified')
        self.page_urls[bank]=url
        self.page_guard()

    def layout_bindings(self,scene):
        result={k:dict(v) for k,v in self.bindings.items()}
        if self.bank_content[scene[-1]]:
            if 'content' in result:result['bound_content']=result['content']
            result['content']={'name':PAGES[scene[-1]],'kind':'browser_source'}
        return result

    def scene_sources(self, scene):
        mode = next(mode for mode, pair in SCENES.items() if scene in pair)
        return {MEDIA, OVERLAYS[scene[-1]]} | ({PAGES[scene[-1]]} if '/ Live ' in scene else set()) | ({BASES[mode]} if mode in BASES else {b['name'] for b in self.bindings.values()})

    def setup(self, camera='', content='', *, fixtures=False):
        self.guard(); self.outputs_off(); self.wait_transition()
        if 'browser_source' not in self.req('GetInputKindList').get('inputKinds', []):
            raise ObsError('Browser sources unavailable in connected OBS; use the browser-enabled fork and explicit local launch opt-in')
        if camera and camera == content: raise ObsError('Camera and content must be different inputs')
        available = {x['name']: x['kind'] for x in self.inputs()}
        fixture_definitions = []
        if fixtures:
            if camera or content: raise ObsError('Choose synthetic fixtures or existing inputs, not both')
            fixture_existing = {x['inputName'] for x in self.req('GetInputList').get('inputs', [])}
            for role in ('camera', 'content'):
                name = 'Director / Fixture '+role.title()
                settings = {'url': f'http://127.0.0.1:{self.client_http_port}/fixture-{role}.html',
                            'width':1920, 'height':1080, 'shutdown':False, 'reroute_audio':False}
                if name in fixture_existing:
                    actual = self.req('GetInputSettings', {'inputName':name})
                    if actual.get('inputKind') != 'browser_source' or any(actual.get('inputSettings',{}).get(k) != v for k,v in settings.items()):
                        raise ObsError('Synthetic fixture name conflicts with existing input; inspect manually')
                fixture_definitions.append((name, 'browser_source', settings, SCENES['live'][0]))
                available[name] = 'browser_source'
            camera, content = ('Director / Fixture Camera', 'Director / Fixture Content')
        for name in (camera, content):
            if name and name not in available: raise ObsError('Select existing camera/content inputs from this collection')
        self.bindings = {k: {'name': name, 'kind': available[name]} for k, name in (('camera', camera), ('content', content)) if name}
        existing = {x['sceneName'] for x in self.req('GetSceneList').get('scenes', [])}
        for scene in OWNED:
            if scene not in existing: self.req('CreateScene', {'sceneName': scene})
        known = {x['inputName'] for x in self.req('GetInputList').get('inputs', [])}
        definitions = fixture_definitions + [(OVERLAYS[bank], 'browser_source', {'url': self.urls[bank], 'width': 1920, 'height': 1080, 'shutdown': False, 'reroute_audio': False}, SCENES['starting'][index]) for index, bank in enumerate(('A', 'B'))]
        definitions += [(name, 'browser_source', {'url': self.base_urls[mode], 'width': 1920, 'height': 1080, 'shutdown': False, 'reroute_audio': False}, SCENES[mode][0]) for mode, name in BASES.items()]
        definitions += [(PAGES[bank], 'browser_source', {'url':'about:blank','width':1920,'height':1080,'shutdown':False,'reroute_audio':False}, SCENES['live'][index]) for index,bank in enumerate(('A','B'))]
        definitions.append((MEDIA, 'ffmpeg_source', {'is_local_file': True, 'local_file': '', 'looping': False, 'restart_on_activate': False, 'close_when_inactive': False}, OWNED[0]))
        for name, kind, settings, scene in definitions:
            if name not in known:
                self.req('CreateInput', {'sceneName': scene, 'inputName': name, 'inputKind': kind, 'inputSettings': settings, 'sceneItemEnabled': name in BASES.values()})
        # Only deliberate outputs-off setup may reconcile existing owned browser settings.
        for bank,name in PAGES.items():
            actual=self.req('GetInputSettings',{'inputName':name})
            if actual.get('inputKind')!='browser_source':raise ObsError('Owned page name conflicts with another input kind')
            expected={'url':'about:blank','width':1920,'height':1080,'shutdown':False,'reroute_audio':False}
            if any(actual.get('inputSettings',{}).get(k)!=v for k,v in expected.items()):
                self.req('SetInputSettings',{'inputName':name,'inputSettings':expected,'overlay':True})
        self.page_urls={bank:'about:blank' for bank in PAGES};self.bank_content={bank:False for bank in PAGES}
        self.page_reviewed={bank:False for bank in PAGES}
        self.source_guard()
        for scene in OWNED:
            # Explicit outputs-off migration from the rejected shared graphics design.
            for item in self.items(scene):
                if item['sourceName'] == LEGACY_OVERLAY:
                    self.req('RemoveSceneItem', {'sceneName': scene, 'sceneItemId': item['sceneItemId']})
            names = {x['sourceName'] for x in self.items(scene)}
            overlay = OVERLAYS[scene[-1]]
            mode = next(mode for mode, pair in SCENES.items() if scene in pair)
            wanted = list(self.scene_sources(scene))
            unexpected = names - set(wanted)
            if unexpected: raise ObsError('Owned scene contains unexpected sources; remove them manually before setup')
            for name in wanted:
                if name not in names:
                    self.req('CreateSceneItem', {'sceneName': scene, 'sourceName': name, 'sceneItemEnabled': name in BASES.values()})
            # Ordering: camera above content; graphics above everything, media under graphics.
            order = [b['name'] for k, b in self.bindings.items() if k == 'content'] + [b['name'] for k, b in self.bindings.items() if k == 'camera'] if '/ Live ' in scene else []
            if mode=='live':
                order.insert(1 if order else 0,PAGES[scene[-1]])
                self.req('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':self.item(scene,PAGES[scene[-1]]),'sceneItemEnabled':False})
            if mode in BASES: order = [BASES[mode]] + order
            order += [MEDIA, overlay]
            # Explicit setup initializes defaults without exposing a stale bank.
            for name in (overlay, *([BASES[mode]] if mode in BASES else [])):
                self.req('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': self.item(scene, name), 'sceneItemEnabled': name != overlay})
            for index, name in enumerate(order):
                self.req('SetSceneItemIndex', {'sceneName': scene, 'sceneItemId': self.item(scene, name), 'sceneItemIndex': index})
        self.req('SetInputVolume', {'inputName': MEDIA, 'inputVolumeMul': 0})
        self.req('TriggerMediaInputAction', {'inputName': MEDIA, 'mediaAction': 'OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP'})
        if self.req('GetSceneList').get('currentProgramSceneName') not in OWNED:
            self.req('SetCurrentProgramScene', {'sceneName': OWNED[0]})
            self.wait_transition(expected_program=OWNED[0])
        self.req('SetCurrentPreviewScene', {'sceneName': OWNED[0]})
        return self.snapshot()

    def verify(self):
        self.guard(); self.source_guard()
        kinds = {x['inputName']: x['inputKind'] for x in self.req('GetInputList').get('inputs', [])}
        for binding in self.bindings.values():
            if kinds.get(binding['name']) != binding['kind']: raise ObsError('Bound input identity changed')
        for scene in OWNED:
            names = {x['sourceName'] for x in self.items(scene)}
            wanted = self.scene_sources(scene)
            if names != wanted: raise ObsError('Owned scene sources changed; disarmed')
        current = self.req('GetSceneList')
        if current.get('currentProgramSceneName') not in OWNED: raise ObsError('Current OBS program is not owned')
        return current

    @staticmethod
    def require_owned_scenes(scenes):
        for role in ('Program', 'Preview'):
            if scenes.get('current'+role+'SceneName') not in OWNED:
                raise ObsError('Current OBS '+role.lower()+' is not owned')

    def snapshot(self):
        self.guard()
        scenes = self.wait_transition()
        self.require_owned_scenes(scenes)
        self.source_guard()
        geometry = {}
        for scene in OWNED:
            geometry[scene] = []
            for item in self.items(scene):
                if item['sourceName'] not in self.scene_sources(scene):
                    raise ObsError('Unexpected owned scene source')
                transform = self.req('GetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item['sceneItemId']})['sceneItemTransform']
                geometry[scene].append({'source': item['sourceName'], 'transform': operative_transform(transform), 'enabled': item['sceneItemEnabled']})
        return {'page_urls':dict(self.page_urls), 'bank_content':dict(self.bank_content), 'program': scenes['currentProgramSceneName'], 'preview': scenes['currentPreviewSceneName'], 'geometry': geometry,
                'profile': self.profile, 'collection': COLLECTION,
                'outputs': self.output_states()}

    def set_box(self, scene, source, box):
        ident = self.item(scene, source)
        enabled = box is not None
        self.req('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': ident, 'sceneItemEnabled': enabled})
        if not enabled: return
        x, y, w, h = box
        transform = {'positionX': x, 'positionY': y, 'alignment': 5, 'rotation': 0,
                     'boundsType': 'OBS_BOUNDS_SCALE_INNER', 'boundsAlignment': 0, 'boundsWidth': w, 'boundsHeight': h,
                     'cropLeft': 0, 'cropTop': 0, 'cropRight': 0, 'cropBottom': 0}
        self.req('SetSceneItemTransform', {'sceneName': scene, 'sceneItemId': ident, 'sceneItemTransform': transform})
        actual = self.req('GetSceneItemTransform', {'sceneName': scene, 'sceneItemId': ident})['sceneItemTransform']
        if any(actual.get(k) != v for k, v in transform.items()): raise ObsError('OBS layout readback mismatch')

    def _arm_prepare_guard(self, context, permit):
        permit()
        self.outputs_off()
        current = self.verify()
        self.require_owned_scenes(current)
        self.wait_transition(invariant_program=context['program'])
        if self.fingerprint(context['program']) != context['signature']:
            raise ObsError('Program geometry changed during arm preparation; outcome uncertain')
        permit()

    def arm_prepare_preview(self, scene, context, permit):
        """Qualified operator preparation only; no program or source-settings writes."""
        self._arm_prepare_guard(context, permit)
        if scene not in OWNED: raise ObsError('Unowned arm preparation preview')
        if self.req('GetSceneList')['currentPreviewSceneName'] != scene:
            permit()
            self.req('SetCurrentPreviewScene', {'sceneName': scene})
        return self.wait_transition(expected_preview=scene, invariant_program=context['program'])

    def arm_prepare_graphics(self, saved, visible, context, permit):
        self._arm_prepare_guard(context, permit)
        scene = saved['scene']
        if scene == context['program']:
            raise ObsError('Arm preparation cannot change the program graphics item')
        if scene[-1] == context['program'][-1] and self.graphics_item(context['program'])['sceneItemEnabled']:
            raise ObsError('Arm preparation cannot expose a shared visible program bank')
        item = self.graphics_item(scene)
        if item['sceneItemId'] != saved['id'] or item['sourceName'] != saved['source']:
            raise ObsError('Arm preparation graphics identity changed')
        if item['sceneItemEnabled'] != visible:
            permit()
            self.req('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item['sceneItemId'], 'sceneItemEnabled': visible})
        actual = self.graphics_item(scene)
        if actual['sceneItemId'] != saved['id'] or actual['sceneItemEnabled'] != visible:
            raise ObsError('Arm preparation visibility not confirmed; outcome uncertain')
        self._arm_prepare_guard(context, permit)

    def _payload_prepare_guard(self, context, permit):
        # Already-armed live operation, distinct from outputs-off cold Arm.
        permit()
        current = self.verify()
        self.require_owned_scenes(current)
        self.wait_transition(invariant_program=context['program'])
        if self.fingerprint(context['program']) != context['signature']:
            raise ObsError('Program geometry changed during payload preparation; outcome uncertain')
        permit()

    def payload_prepare_preview(self, scene, context, permit):
        self._payload_prepare_guard(context, permit)
        if scene not in OWNED: raise ObsError('Unowned payload preparation preview')
        if self.req('GetSceneList')['currentPreviewSceneName'] != scene:
            permit()
            self.req('SetCurrentPreviewScene', {'sceneName': scene})
        self.wait_transition(expected_preview=scene, invariant_program=context['program'])

    def payload_prepare_graphics(self, saved, visible, context, permit):
        self._payload_prepare_guard(context, permit)
        scene = saved['scene']
        if scene == context['program'] or (scene[-1] == context['program'][-1] and self.graphics_item(context['program'])['sceneItemEnabled']):
            raise ObsError('Payload preparation cannot expose a visible program bank')
        item = self.graphics_item(scene)
        if item['sceneItemId'] != saved['id'] or item['sourceName'] != saved['source']:
            raise ObsError('Payload preparation graphics identity changed')
        if item['sceneItemEnabled'] != visible:
            permit()
            self.req('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item['sceneItemId'], 'sceneItemEnabled': visible})
        actual = self.graphics_item(scene)
        if actual['sceneItemId'] != saved['id'] or actual['sceneItemEnabled'] != visible:
            raise ObsError('Payload preparation visibility not confirmed; outcome uncertain')
        self._payload_prepare_guard(context, permit)

    def graphics_item(self, scene):
        if scene not in OWNED: raise ObsError('Unowned graphics scene')
        matches = [item for item in self.items(scene) if item['sourceName'] == OVERLAYS[scene[-1]]]
        if len(matches) != 1: raise ObsError('Owned graphics item missing or duplicated')
        return matches[0]

    def set_graphics_visible(self, scene, visible, program, *, inactive=False):
        """Only exact owned item visibility; never reload or clear a SOURCE texture."""
        self.wait_transition(invariant_program=program)
        current = self.verify()
        if current['currentProgramSceneName'] != program or scene not in OWNED:
            raise ObsError('OBS program changed before graphics visibility; outcome uncertain')
        if inactive and scene[-1] == program[-1]:
            raise ObsError('Graphics preparation must use the inactive bank')
        if not inactive and scene != program:
            raise ObsError('Graphics visibility must target the current owned program')
        item = self.graphics_item(scene)
        if item['sceneItemEnabled'] != visible:
            self.req('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item['sceneItemId'], 'sceneItemEnabled': visible})
        actual = self.graphics_item(scene)
        if actual['sceneItemId'] != item['sceneItemId'] or actual['sceneItemEnabled'] != visible:
            raise ObsError('Owned graphics visibility not confirmed; outcome uncertain')
        self.wait_transition(invariant_program=program)
        return {'scene': scene, 'source': OVERLAYS[scene[-1]], 'scene_item_id': item['sceneItemId'],
                'enabled': visible, 'source_texture_cleared': False, 'pixels_verified': False}

    def reveal_prepared_graphics(self):
        prepared = self.prepared
        if not prepared or not prepared.get('graphics_pending'): return
        self.wait_transition(expected_preview=prepared['target'], invariant_program=prepared['program'])
        if self.fingerprint(prepared['target']) != prepared['geometry']:
            raise ObsError('OBS layout changed before graphics readiness')
        self.set_graphics_visible(prepared['target'], prepared['graphics_visible'], prepared['program'], inactive=True)
        prepared['geometry'] = self.fingerprint(prepared['target'])
        prepared['graphics_pending'] = False

    def preview(self, mode, layout, *, defer_graphics=False, graphics_visible=True, page_url=None):
        self.prepared = None
        self.wait_transition()
        current = self.verify()
        self.require_owned_scenes(current)
        pair = SCENES[mode]
        bank = 'B' if current['currentProgramSceneName'].endswith(' A') else 'A'
        target = pair[0 if bank == 'A' else 1]
        if mode == 'live':
            if page_url is not None:self.set_page_url(bank,page_url,invariant_program=current['currentProgramSceneName'])
            self.bank_content[bank]=page_url is not None
            bindings=self.layout_bindings(target)
            required = {'camera'} if layout == 'camera' else {'content'} if layout == 'content' else {'camera', 'content'}
            if not required <= set(bindings): raise ObsError('Bind camera/content inputs with outputs off before using this layout')
            boxes = {'camera': {'camera': (0, 0, 1920, 1080)},
                     'content': {'content': (0, 0, 1920, 1080)},
                     'pip': {'content': (0, 0, 1920, 1080), 'camera': (1390, 720, 480, 300)},
                     'side-by-side': {'content': (700, 80, 1180, 920), 'camera': (40, 80, 620, 920)}}[layout]
            for key, binding in bindings.items(): self.set_box(target, binding['name'], boxes.get(key))
            if page_url is None:self.set_box(target,PAGES[bank],None)
        # A later hidden payload can stop ACKing even after cold-arm warming.
        # Unapproved PREVIEW may show it; the globally opposite program bank
        # stays untouched. Fresh ACK finalizes the segment's required visibility.
        if defer_graphics: self.set_graphics_visible(target, True, current['currentProgramSceneName'], inactive=True)
        self.req('SetCurrentPreviewScene', {'sceneName': target})
        after = self.wait_transition(expected_preview=target, invariant_program=current['currentProgramSceneName'])
        self.prepared = {'bank': bank, 'target': target, 'program': current['currentProgramSceneName'], 'geometry': self.fingerprint(target), 'graphics_pending': defer_graphics, 'graphics_visible': graphics_visible}
        return after

    def reload_prepared_graphics(self, bank):
        """Explicit recovery only: refresh the exact globally inactive owned bank."""
        prepared = self.prepared
        if bank not in OVERLAYS or not prepared or bank != prepared['bank']:
            raise ObsError('Reload requires the exact prepared graphics bank')
        current = self.wait_transition(expected_preview=prepared['target'], invariant_program=prepared['program'])
        self.guard(); self.source_guard(); self.require_owned_scenes(current)
        if (current['currentProgramSceneName'].endswith(' '+bank)
                or prepared['target'][-1] != bank or self.fingerprint(prepared['target']) != prepared['geometry']):
            raise ObsError('Refuse to reload program graphics or changed preview geometry')
        # Existing OBS browser property calls BrowserSource::Refresh/ReloadIgnoreCache.
        # RPC success is not a frame ACK; Director still waits for a fresh document.
        self.req('PressInputPropertiesButton', {'inputName': OVERLAYS[bank], 'propertyName': 'refreshnocache'})
        self.wait_transition(expected_preview=prepared['target'], invariant_program=prepared['program'])
        if self.fingerprint(prepared['target']) != prepared['geometry']:
            raise ObsError('Preview geometry changed during graphics reload; outcome uncertain')

    def fingerprint(self, scene):
        fields = {'positionX', 'positionY', 'scaleX', 'scaleY', 'rotation', 'alignment', 'boundsType', 'boundsWidth', 'boundsHeight', 'boundsAlignment', 'cropLeft', 'cropRight', 'cropTop', 'cropBottom'}
        result = {}
        for item in self.items(scene):
            actual = self.req('GetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item['sceneItemId']})['sceneItemTransform']
            result[item['sourceName']] = {'enabled': item['sceneItemEnabled'], 'transform': operative_transform({k: v for k, v in actual.items() if k in fields})}
        return result

    def bound_layout(self):
        """Read operative geometry for current owned Live bound inputs, never item IDs."""
        self.wait_transition()
        current = self.verify()
        self.require_owned_scenes(current)
        scene = current['currentProgramSceneName']
        if scene not in SCENES['live']:
            raise ObsError('Undo camera layout requires the current owned Live program')
        bindings=self.layout_bindings(scene)
        if not bindings:
            raise ObsError('No bound camera/content arrangement')
        fingerprint = self.fingerprint(scene)
        return {'scene': scene, 'bindings': bindings,
                'geometry': {b['name']: fingerprint[b['name']] for b in bindings.values()}}

    def undo_bound_layout(self, saved):
        current = self.bound_layout()
        if current != saved['expected']:
            raise ObsError('Camera/content binding or geometry changed; layout undo refused')
        scene = current['scene']
        # Resolve each current-bank item by the bound source name. Never reuse A/B IDs.
        # Each setter occurs once, with exact readback and no rollback/retry on failure.
        for source, previous in saved['before'].items():
            for field, method, key in (('transform', 'SetSceneItemTransform', 'sceneItemTransform'),
                                       ('enabled', 'SetSceneItemEnabled', 'sceneItemEnabled')):
                if self.bound_layout() != current:
                    raise ObsError('Camera/content changed during layout undo; outcome uncertain')
                self.req(method, {'sceneName': scene, 'sceneItemId': self.item(scene, source), key: previous[field]})
                current['geometry'][source][field] = previous[field]
                if self.bound_layout() != current:
                    raise ObsError('Camera layout undo readback mismatch; outcome uncertain')
        return current

    def take(self):
        self.wait_transition()
        current = self.verify()
        if not self.prepared or self.prepared.get('graphics_pending') or current['currentProgramSceneName'] != self.prepared['program'] or current['currentPreviewSceneName'] != self.prepared['target']:
            raise ObsError('OBS scene changed since preview; preview again before take')
        target = self.prepared['target']
        if self.fingerprint(target) != self.prepared['geometry']:
            raise ObsError('OBS layout changed since preview; preview again before take')
        self.req('SetCurrentProgramScene', {'sceneName': target})
        actual = self.wait_transition(expected_program=target)
        self.guard()
        if target in SCENES['live'] and self.bank_content[target[-1]] and self.prepared['geometry'][PAGES[target[-1]]]['enabled']:
            # Caller is the deliberate manual Take or an exactly human-approved agent Take.
            self.page_reviewed[target[-1]]=True
        self.prepared = None
        return actual

    def page_restore_plan(self,snapshot,current=None):
        """Read-only preflight before media, graphics publication or any recovery setter."""
        if current is None:
            self.wait_transition();current=self.verify()
        desired=snapshot.get('page_urls',dict(self.page_urls))
        if set(desired)!=set(PAGES):raise ObsError('Invalid owned page recovery state')
        active=current['currentProgramSceneName'];deferred=[];updates=[]
        if snapshot['program'] in SCENES['live']:
            bank=snapshot['program'][-1]
            visible=next(x['enabled'] for x in snapshot['geometry'][snapshot['program']] if x['source']==PAGES[bank])
            if visible and (desired[bank]!=self.page_urls[bank] or not self.page_reviewed[bank]):
                raise ObsError('Recovery page needs an explicit reviewed take in its saved bank; checkpoint retained')
        for bank,url in desired.items():
            if url!='about:blank':public_url(url)
            if url==self.page_urls[bank]:continue
            visible=active==SCENES['live'][0 if bank=='A' else 1] and any(x['sourceName']==PAGES[bank] and x['sceneItemEnabled'] for x in self.items(active))
            if visible:
                intended=next(x for x in snapshot['geometry'][snapshot['program']] if x['source']==PAGES[bank]) if snapshot['program']==active else None
                if intended and intended['enabled']:
                    raise ObsError('Recovery would reload the on-air page; prepare an opposite-bank reviewed page first')
                deferred.append((bank,url))
            else:updates.append((bank,url))
        return desired,deferred,updates

    def restore(self, snapshot):
        self.wait_transition()
        current = self.verify()
        if snapshot['profile'] != self.profile or snapshot['collection'] != COLLECTION:
            raise ObsError('Restore checkpoint belongs to a different OBS profile/collection')
        if snapshot['program'] not in OWNED or snapshot['preview'] not in OWNED:
            raise ObsError('Restore checkpoint is outside owned scenes')
        desired,deferred,updates=self.page_restore_plan(snapshot,current)
        active=current['currentProgramSceneName']
        for bank,url in updates:self.set_page_url(bank,url)
        allowed = {'positionX', 'positionY', 'scaleX', 'scaleY', 'rotation', 'alignment', 'boundsType', 'boundsAlignment', 'boundsWidth', 'boundsHeight', 'cropLeft', 'cropRight', 'cropTop', 'cropBottom'}
        def apply_geometry(scene):
            for item in snapshot['geometry'][scene]:
                ident=self.item(scene,item['source'])
                transform=operative_transform({k:v for k,v in item['transform'].items() if k in allowed})
                self.req('SetSceneItemTransform',{'sceneName':scene,'sceneItemId':ident,'sceneItemTransform':transform})
                self.req('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':ident,'sceneItemEnabled':item['enabled']})
        for scene in snapshot['geometry']:
            if scene!=active or snapshot['program']==active:apply_geometry(scene)
        if current['currentProgramSceneName'] != snapshot['program']:
            self.req('SetCurrentProgramScene', {'sceneName': snapshot['program']})
        self.wait_transition(expected_program=snapshot['program'])
        if snapshot['program']!=active:apply_geometry(active)
        for bank,url in deferred:self.set_page_url(bank,url)
        self.bank_content=dict(snapshot.get('bank_content',self.bank_content))
        self.guard()
        # Apply preview last: OBS's completed Fade has already swapped it to old program.
        self.req('SetCurrentPreviewScene', {'sceneName': snapshot['preview']})
        self.prepared = None
        actual = self.snapshot()
        if actual['page_urls']!=desired:raise ObsError('Page recovery URL readback mismatch')
        settled = self.wait_transition(expected_program=snapshot['program'], expected_preview=snapshot['preview'])
        actual.update(program=settled['currentProgramSceneName'], preview=settled['currentPreviewSceneName'])
        for scene, items in snapshot['geometry'].items():
            for expected, observed in zip(items, actual['geometry'][scene]):
                if expected['source'] != observed['source'] or expected['enabled'] != observed['enabled']:
                    raise ObsError('Restore item readback mismatch')
                expected_transform = operative_transform(expected['transform'])
                for key in allowed:
                    if key in expected_transform and observed['transform'].get(key) != expected_transform[key]:
                        raise ObsError('Restore geometry readback mismatch')
        return actual

    def media(self, path=None, volume=.25):
        if path is None:
            self.guard()
            if self.req('GetInputSettings', {'inputName': MEDIA}).get('inputKind') != 'ffmpeg_source':
                raise ObsError('Owned media identity changed')
            self.req('TriggerMediaInputAction', {'inputName': MEDIA, 'mediaAction': 'OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP'})
            self.req('SetInputVolume', {'inputName': MEDIA, 'inputVolumeMul': 0})
        else:
            self.verify()
            if not math.isfinite(volume) or not 0 <= volume <= .5: raise ObsError('Volume cap is 50%')
            self.req('SetInputVolume', {'inputName': MEDIA, 'inputVolumeMul': volume})
            self.req('SetInputSettings', {'inputName': MEDIA, 'inputSettings': {'is_local_file': True, 'local_file': str(path), 'looping': False, 'restart_on_activate': False}, 'overlay': True})
            for scene in OWNED:
                self.set_box(scene, MEDIA, (0, 0, 1920, 1080))
            self.req('TriggerMediaInputAction', {'inputName': MEDIA, 'mediaAction': 'OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART'})
        result = {'volume': self.req('GetInputVolume', {'inputName': MEDIA})['inputVolumeMul'],
                  'state': self.req('GetMediaInputStatus', {'inputName': MEDIA}).get('mediaState')}
        if result['volume'] > .5: raise ObsError('Media volume readback exceeded cap')
        if path is None and (result['volume'] != 0 or result['state'] not in ('OBS_MEDIA_STATE_STOPPED', 'OBS_MEDIA_STATE_ENDED', 'OBS_MEDIA_STATE_NONE')):
            raise ObsError('Media stop readback was not confirmed')
        return result
