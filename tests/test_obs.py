import unittest
from obs import ObsAdapter
from streamer import Refused, Show

class Socket:
    def __init__(self):
        self.calls = []
        self.visible = False
        self.title = ''
        self.preview = 'Staging'
        self.program = 'Camera'
    def request(self, method, data=None):
        data = data or {}; self.calls.append(method)
        if method == 'GetSourceScreenshot': return {'imageData':'data:image/png;base64,aW1hZ2U='}
        if method == 'GetStudioModeEnabled': return {'studioModeEnabled': True}
        if method in ('GetStreamStatus','GetRecordStatus','GetVirtualCamStatus'): return {'outputActive': False}
        if method == 'GetCurrentProgramScene': return {'currentProgramSceneName': self.program}
        if method == 'GetCurrentPreviewScene': return {'currentPreviewSceneName': self.preview}
        if method == 'GetSceneList': return {'scenes':[{'sceneName':'Camera'},{'sceneName':'Staging'}]}
        if method == 'GetSceneItemList':
            return {'sceneItems': [{'sourceName': 'camera' if data['sceneName'] == 'Camera' else 'graphics',
                    'sceneItemId': 7, 'sceneItemEnabled': self.visible, 'isGroup':False, 'sourceType':'OBS_SOURCE_TYPE_INPUT'}]}
        if method == 'GetInputSettings': return {'inputKind':'text_ft2_source_v2', 'inputSettings':{'text': self.title}}
        if method == 'SetInputSettings': self.title = data['inputSettings']['text']; return {}
        if method == 'SetSceneItemEnabled': self.visible = data['sceneItemEnabled']; return {}
        if method == 'SetCurrentPreviewScene': self.preview = data['sceneName']; return {}
        raise AssertionError(method)

class ObsTests(unittest.TestCase):
    def test_actual_protocol_readback_and_only_preview_mutations(self):
        wire = Socket(); show = Show(ObsAdapter(wire))
        show.enable(); show.stage('Demo the demo'); show.clear(); show.restore()
        writes = [x for x in wire.calls if x.startswith('Set')]
        self.assertEqual(set(writes), {'SetInputSettings','SetSceneItemEnabled','SetCurrentPreviewScene'})
        self.assertTrue(wire.visible)
        self.assertEqual(wire.program, 'Camera')
    def test_program_changes_between_title_and_enable_stops_next_write(self):
        wire = Socket(); original = wire.request
        def request(method, data=None):
            result = original(method, data)
            if method == 'SetInputSettings': wire.program = 'Staging'
            return result
        wire.request = request
        show = Show(ObsAdapter(wire)); show.enable()
        with self.assertRaises(Refused): show.stage('Never reveal')
        self.assertNotIn('SetSceneItemEnabled', wire.calls)
        self.assertNotIn('SetCurrentPreviewScene', wire.calls)
        self.assertFalse(show.enabled)

    def test_monitor_frames_use_only_actual_program_and_preview_source_names(self):
        wire = Socket(); adapter = ObsAdapter(wire)
        frames = adapter.frames()
        self.assertEqual(set(frames), {'program','preview'})
        self.assertTrue(frames['program'].startswith('data:image/png;base64,'))
        self.assertFalse(any(x.startswith('Set') for x in wire.calls))

    def test_unexpected_input_kind_refuses_writes(self):
        wire = Socket(); original = wire.request
        def request(method, data=None):
            if method == 'GetInputSettings': return {'inputKind':'browser_source','inputSettings':{}}
            return original(method, data)
        wire.request = request
        with self.assertRaises(Refused): Show(ObsAdapter(wire)).enable()
        self.assertFalse(any(x.startswith('Set') for x in wire.calls))
    def test_arbitrary_native_method_is_unavailable(self):
        from obs import ObsSocket
        socket = ObsSocket.__new__(ObsSocket)
        with self.assertRaises(Refused): socket.request('StartStream')

if __name__ == '__main__': unittest.main()

class VisualSocket(Socket):
    def __init__(self):super().__init__();self.inputs={};self.items={};self.next_id=20
    def request(self,method,data=None):
        data=data or {}
        if method=='GetVideoSettings':return {'baseWidth':1920,'baseHeight':1080}
        if method=='GetInputList':return {'inputs':[{'inputName':name,'inputKind':value['kind']} for name,value in self.inputs.items()]}
        if method=='CreateInput':
            self.calls.append(method);name=data['inputName'];self.inputs[name]={'kind':data['inputKind'],'settings':data['inputSettings']};self.next_id+=1
            self.items[name]={'sourceName':name,'sceneItemId':self.next_id,'sceneItemEnabled':False,'transform':{}}
            return {'sceneItemId':self.next_id}
        if method=='GetSceneItemList':
            result=super().request(method,data)
            if data['sceneName']=='Staging':result['sceneItems']+=list(self.items.values())
            return result
        name=data.get('inputName')
        if name in self.inputs and method=='GetInputSettings':return {'inputKind':self.inputs[name]['kind'],'inputSettings':dict(self.inputs[name]['settings'])}
        if name in self.inputs and method=='SetInputSettings':self.calls.append(method);self.inputs[name]['settings'].update(data['inputSettings']);return {}
        item=next((v for v in self.items.values() if v['sceneItemId']==data.get('sceneItemId')),None)
        if item and method=='SetSceneItemEnabled':self.calls.append(method);item['sceneItemEnabled']=data['sceneItemEnabled'];return {}
        if item and method=='SetSceneItemTransform':self.calls.append(method);item['transform'].update(data['sceneItemTransform']);return {}
        if item and method=='GetSceneItemTransform':return {'sceneItemTransform':dict(item['transform'])}
        return super().request(method,data)

class NativeVisualTests(unittest.TestCase):
    def test_visual_source_created_in_staging_and_position_read_back(self):
        wire=VisualSocket();adapter=ObsAdapter(wire);show=Show(adapter);show.enable()
        adapter.visual_write('image','/owned/selected.png',{'x':.1,'y':.2,'width':.6,'height':.5})
        item=wire.items['preview-image']
        self.assertEqual(item['transform']['positionX'],192)
        self.assertEqual(item['transform']['positionY'],216)
        self.assertTrue(item['sceneItemEnabled']);self.assertEqual(wire.program,'Camera')
        adapter.visual_hide();self.assertFalse(item['sceneItemEnabled'])
    def test_visual_source_shared_with_camera_is_refused(self):
        wire=VisualSocket();original=wire.request
        def request(method,data=None):
            result=original(method,data)
            if method=='GetSceneItemList' and data['sceneName']=='Camera':result['sceneItems'].append({'sourceName':'preview-image','sceneItemId':99})
            return result
        wire.request=request;show=Show(ObsAdapter(wire))
        with self.assertRaises(Refused):show.enable()
        self.assertNotIn('CreateInput',wire.calls)
