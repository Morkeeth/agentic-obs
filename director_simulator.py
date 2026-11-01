"""Independent OBS-v5 simulator for expanded-director integration only.

Not OBS and not visual evidence. Uses a synthetic password and ephemeral loopback
port. Context manager closes all sockets and joins its server thread.
"""
import base64
import copy
import hashlib
import json
import threading
import time

from websockets.sync.server import serve

from director_obs import COLLECTION, ObsError

DEFAULT_TRANSFORM = dict(positionX=0, positionY=0, scaleX=1, scaleY=1, rotation=0,
                         alignment=5, boundsType='OBS_BOUNDS_NONE', boundsAlignment=0,
                         boundsWidth=0, boundsHeight=0, cropLeft=0, cropRight=0, cropTop=0, cropBottom=0)


class SimulatedFieldError(ValueError):
    """Recorded OBS setter validation (request status 402)."""


class SimulatedOBS:
    simulated = True
    password = 'synthetic-director-test-only'
    def __init__(self, transition_seconds=.03, clock=time.monotonic):
        self.lock = threading.RLock()
        self.collection = COLLECTION
        self.profile = 'Simulated Director Profile'
        self.studio = True
        self.active = False
        self.program = 'Scene'
        self.preview = 'Scene'
        self.scenes = {'Scene': []}
        self.inputs = {'Camera': {'kind': 'test_camera', 'settings': {}}, 'Content': {'kind': 'test_content', 'settings': {}}}
        self.input_kinds = ['browser_source', 'ffmpeg_source', 'test_camera', 'test_content']
        self.volume = 0
        self.media_state = 'OBS_MEDIA_STATE_STOPPED'
        self.requests = []
        self.connections = set()
        self.drop_on = None
        self.refuse_on = None
        self.stale_before_reply = False
        self.wrong_type = False
        self.server = None
        self.worker = None
        self.sequence = 0
        # Time-scaled Fade model: ACK/program report precede the late Studio preview swap.
        self.clock = clock
        self.transition_seconds = transition_seconds
        self.transition = None
        self.transition_stuck = False
        self.effects = []
        self.transform_writes = []

    def __enter__(self):
        self.server = serve(self.handler, '127.0.0.1', 0, compression=None, close_timeout=.2)
        self.port = self.server.socket.getsockname()[1]
        self.worker = threading.Thread(target=self.server.serve_forever, name='simulated-obs')
        self.worker.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        for ws in list(self.connections): ws.close()
        self.worker.join(timeout=5)
        if self.worker.is_alive(): raise RuntimeError('Simulator did not stop')

    def handler(self, ws):
        self.connections.add(ws)
        try:
            salt, challenge = 'synthetic-salt', 'synthetic-challenge'
            ws.send(json.dumps({'op': 0, 'd': {'rpcVersion': 1, 'authentication': {'salt': salt, 'challenge': challenge}}}))
            identify = json.loads(ws.recv())
            enc = lambda value: base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()
            if identify.get('op') != 1 or identify.get('d', {}).get('authentication') != enc(enc(self.password+salt)+challenge):
                ws.close(4009, 'Synthetic authentication refused'); return
            ws.send(json.dumps({'op': 2, 'd': {'negotiatedRpcVersion': 1}}))
            for raw in ws:
                msg = json.loads(raw)
                data = msg['d']; kind = data['requestType']
                with self.lock:
                    self.requests.append(kind)
                    if self.drop_on == kind:
                        self.drop_on = None
                        ws.close(1011, 'Simulated disconnect'); return
                    try:
                        if self.refuse_on == kind:
                            self.refuse_on = None
                            raise ValueError('Injected refusal')
                        result = self.rpc(kind, data.get('requestData', {})); ok = True; code = 100
                    except (ValueError, KeyError) as exc:
                        result = {}; ok = False
                        code = 402 if isinstance(exc, SimulatedFieldError) else 600
                    response = {'op': 7, 'd': {'requestType': 'WrongType' if self.wrong_type else kind,
                        'requestId': data['requestId'], 'requestStatus': {'result': ok, 'code': code}, 'responseData': result}}
                    self.wrong_type = False
                    if self.stale_before_reply:
                        stale = copy.deepcopy(response); stale['d']['requestId'] = 'stale-response-id'
                        ws.send(json.dumps(stale))
                    ws.send(json.dumps(response))
        except Exception:
            pass
        finally:
            self.connections.discard(ws)

    def item(self, data):
        return next(x for x in self.scenes[data['sceneName']] if x['sceneItemId'] == data['sceneItemId'])

    def add_item(self, scene, source, enabled):
        self.sequence += 1
        self.scenes[scene].append({'sceneItemId': self.sequence, 'sourceName': source,
            'sceneItemEnabled': enabled, 'transform': dict(DEFAULT_TRANSFORM)})
        return {'sceneItemId': self.sequence}

    def advance_transition(self):
        if self.transition and not self.transition_stuck and self.clock() >= self.transition['end']:
            self.preview = self.transition['old_program']
            self.effects.append({'effect': 'transition_complete', 'program': self.program, 'preview': self.preview})
            self.transition = None

    def rpc(self, kind, data):
        self.advance_transition()
        if kind == 'GetCurrentSceneTransitionCursor':
            if not self.transition: return {'transitionCursor': 1.0}
            elapsed = self.clock()-self.transition['start']
            return {'transitionCursor': min(.999, max(0.0, elapsed/self.transition_seconds))}
        if kind == 'GetProfileList': return {'currentProfileName': self.profile}
        if kind == 'GetVersion': return {'obsVersion': 'SIMULATED', 'rpcVersion': 1}
        if kind == 'GetSceneCollectionList': return {'currentSceneCollectionName': self.collection}
        if kind == 'GetStudioModeEnabled': return {'studioModeEnabled': self.studio}
        if kind == 'GetVideoSettings': return {'baseWidth': 1920, 'baseHeight': 1080}
        if kind in ('GetStreamStatus', 'GetRecordStatus', 'GetVirtualCamStatus'): return {'outputActive': self.active}
        if kind == 'GetSceneList': return {'currentProgramSceneName': self.program, 'currentPreviewSceneName': self.preview,
                                           'scenes': [{'sceneName': name} for name in self.scenes]}
        if kind == 'GetInputKindList': return {'inputKinds': list(self.input_kinds)}
        if kind == 'GetInputList': return {'inputs': [{'inputName': name, 'inputKind': v['kind']} for name, v in self.inputs.items()]}
        if kind == 'GetInputSettings':
            value = self.inputs[data['inputName']]
            return {'inputKind': value['kind'], 'inputSettings': copy.deepcopy(value['settings'])}
        if kind == 'CreateScene':
            if data['sceneName'] in self.scenes: raise ValueError()
            self.scenes[data['sceneName']] = []; return {}
        if kind == 'CreateInput':
            if data['inputName'] in self.inputs: raise ValueError()
            self.inputs[data['inputName']] = {'kind': data['inputKind'], 'settings': copy.deepcopy(data['inputSettings'])}
            return self.add_item(data['sceneName'], data['inputName'], data['sceneItemEnabled'])
        if kind == 'CreateSceneItem': return self.add_item(data['sceneName'], data['sourceName'], data.get('sceneItemEnabled', True))
        if kind == 'GetSceneItemList': return {'sceneItems': [{k: v for k, v in item.items() if k != 'transform'} for item in self.scenes[data['sceneName']]]}
        if kind == 'RemoveSceneItem': self.scenes[data['sceneName']].remove(self.item(data)); return {}
        if kind == 'GetSceneItemTransform': return {'sceneItemTransform': copy.deepcopy(self.item(data)['transform'])}
        if kind == 'SetSceneItemTransform':
            transform = data['sceneItemTransform']
            # Actual OBS 29.1.3/WS 5.2.3 rejects these even under OBS_BOUNDS_NONE,
            # although its getter reports inactive dimensions as zero.
            if any(key in transform and transform[key] < 1 for key in ('boundsWidth', 'boundsHeight')):
                raise SimulatedFieldError('Bounds dimensions must be at least 1 when supplied')
            self.transform_writes.append(copy.deepcopy(data))
            self.effects.append({'effect': 'transform_set', 'scene': data['sceneName'], 'during_transition': self.transition is not None})
            self.item(data)['transform'].update(data['sceneItemTransform']); return {}
        if kind == 'SetSceneItemEnabled': self.item(data)['sceneItemEnabled'] = data['sceneItemEnabled']; return {}
        if kind == 'SetSceneItemIndex':
            items = self.scenes[data['sceneName']]; item = self.item(data); items.remove(item); items.insert(data['sceneItemIndex'], item); return {}
        if kind in ('SetCurrentPreviewScene', 'SetCurrentProgramScene'):
            if data['sceneName'] not in self.scenes: raise ValueError()
            if kind == 'SetCurrentPreviewScene':
                self.preview = data['sceneName']
                self.effects.append({'effect': 'preview_set', 'scene': self.preview, 'during_transition': self.transition is not None})
            elif data['sceneName'] != self.program:
                old = self.program
                self.program = data['sceneName']  # Immediate ACK/new reported program, not completion.
                self.transition = {'old_program': old, 'start': self.clock(), 'end': self.clock()+self.transition_seconds}
                self.effects.append({'effect': 'program_ack', 'program': self.program, 'preview': self.preview})
            return {}
        if kind == 'PressInputPropertiesButton':
            if data.get('inputName') not in ('Director / Graphics A','Director / Graphics B') or data.get('propertyName') != 'refreshnocache': raise ValueError('Unowned simulated refresh')
            self.effects.append({'effect':'browser_refresh','input':data['inputName']});return {}
        if kind == 'SetInputSettings': self.inputs[data['inputName']]['settings'].update(data['inputSettings']); return {}
        if kind == 'SetInputVolume': self.volume = data['inputVolumeMul']; return {}
        if kind == 'GetInputVolume': return {'inputVolumeMul': self.volume}
        if kind == 'GetMediaInputStatus': return {'mediaState': self.media_state}
        if kind == 'TriggerMediaInputAction':
            self.media_state = 'OBS_MEDIA_STATE_STOPPED' if data['mediaAction'].endswith('_STOP') else 'OBS_MEDIA_STATE_PLAYING'; return {}
        raise ValueError('Unsupported simulated request')
