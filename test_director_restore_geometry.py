"""Recorded getter/setter asymmetry; simulated protocol, not actual OBS pixels."""
import json
import unittest
import copy
from unittest.mock import patch
from director_obs import ObsClient, OwnedOBS, SCENES, MEDIA, OVERLAYS, ObsError
from director_simulator import SimulatedOBS

WRITABLE = {'positionX','positionY','scaleX','scaleY','rotation','alignment','boundsType',
            'boundsAlignment','boundsWidth','boundsHeight','cropLeft','cropRight','cropTop','cropBottom'}


class RestoreGeometry(unittest.TestCase):
    def setUp(self):
        self.sim = SimulatedOBS().__enter__()
        self.client = ObsClient(self.sim.password, port=self.sim.port)
        self.native = OwnedOBS(self.client)
        self.native.setup('Camera', 'Content')
    def tearDown(self): self.client.close(); self.sim.__exit__()
    def item_data(self, scene, source):
        return {'sceneName':scene, 'sceneItemId':self.native.item(scene, source)}
    def get(self, scene, source):
        return self.client.req('GetSceneItemTransform', self.item_data(scene, source))['sceneItemTransform']
    def set(self, scene, source, transform):
        return self.client.req('SetSceneItemTransform', {**self.item_data(scene, source),'sceneItemTransform':transform})

    def test_recorded_zero_bounds_getter_payload_is_refused_with_402_even_when_inactive(self):
        for source in (MEDIA, OVERLAYS['A']):
            scene = SCENES['starting'][0]
            actual = self.get(scene, source)
            self.assertEqual(actual['boundsType'], 'OBS_BOUNDS_NONE')
            self.assertEqual((actual['boundsWidth'],actual['boundsHeight']), (0,0))
            # Inspect only this synthetic wire reply to verify the external setter rule.
            ident = 'synthetic-zero-bounds'
            self.client.ws.send(json.dumps({'op':6,'d':{'requestType':'SetSceneItemTransform','requestId':ident,
                'requestData':{**self.item_data(scene,source),'sceneItemTransform':{k:v for k,v in actual.items() if k in WRITABLE}}}}))
            reply = json.loads(self.client.ws.recv())['d']
            self.assertEqual(reply['requestId'],ident)
            self.assertFalse(reply['requestStatus']['result'])
            self.assertEqual(reply['requestStatus']['code'],402)

    def test_getter_snapshot_restores_without_invalid_inactive_bounds_or_source_recreation(self):
        saved = self.native.snapshot()
        identities = {scene:[(item['sourceName'],item['sceneItemId']) for item in items] for scene,items in self.sim.scenes.items()}
        offset = len(self.sim.requests)
        self.native.restore(saved)
        self.assertEqual(self.native.snapshot(), saved)
        self.assertEqual({scene:[(item['sourceName'],item['sceneItemId']) for item in items] for scene,items in self.sim.scenes.items()}, identities)
        self.assertFalse(set(self.sim.requests[offset:]) & {'CreateInput','CreateSceneItem','RemoveSceneItem'})
        for write in self.sim.transform_writes:
            transform = write['sceneItemTransform']
            if transform.get('boundsType') == 'OBS_BOUNDS_NONE':
                self.assertNotIn('boundsWidth',transform)
                self.assertNotIn('boundsHeight',transform)

    def test_active_layout_returns_to_unbounded_geometry_without_invented_sizes(self):
        saved = self.native.snapshot()
        scene = SCENES['live'][1]
        self.native.preview('live','pip');self.native.take()
        active = self.get(scene,'Camera')
        self.assertEqual(active['boundsType'],'OBS_BOUNDS_SCALE_INNER')
        self.native.restore(saved)
        restored = self.get(scene,'Camera')
        self.assertEqual(restored['boundsType'],'OBS_BOUNDS_NONE')
        # The inactive stored dimensions remain; visible geometry returns through mode/scale/position.
        self.assertEqual((restored['boundsWidth'],restored['boundsHeight']), (active['boundsWidth'],active['boundsHeight']))
        self.assertEqual(self.native.snapshot(), saved)

    def test_active_bounds_position_scale_crop_rotation_and_enabled_state_are_restored(self):
        scene = SCENES['live'][1]
        camera = {'positionX':111.5,'positionY':37.25,'scaleX':-.75,'scaleY':.9,'rotation':12,
                  'alignment':5,'boundsType':'OBS_BOUNDS_SCALE_INNER','boundsAlignment':0,
                  'boundsWidth':780,'boundsHeight':430,'cropLeft':2,'cropRight':3,'cropTop':4,'cropBottom':5}
        self.set(scene,'Camera',camera)
        self.client.req('SetSceneItemEnabled',{**self.item_data(scene,'Camera'),'sceneItemEnabled':True})
        self.client.req('SetSceneItemEnabled',{**self.item_data(scene,'Content'),'sceneItemEnabled':False})
        saved = self.native.snapshot()
        original_items = [(item['sourceName'],item['sceneItemId']) for item in self.sim.scenes[scene]]
        self.native.preview('live','pip');self.native.take()
        self.assertNotEqual(self.get(scene,'Camera')['boundsWidth'],camera['boundsWidth'])
        self.native.restore(saved)
        self.assertEqual(self.get(scene,'Camera'),camera)
        self.assertEqual(self.native.snapshot(),saved)
        self.assertEqual([(item['sourceName'],item['sceneItemId']) for item in self.sim.scenes[scene]],original_items)
        self.assertTrue(next(item for item in self.sim.scenes[scene] if item['sourceName']=='Camera')['sceneItemEnabled'])
        self.assertFalse(next(item for item in self.sim.scenes[scene] if item['sourceName']=='Content')['sceneItemEnabled'])
        camera_writes = [write['sceneItemTransform'] for write in self.sim.transform_writes
                         if write['sceneName']==scene and write['sceneItemId']==self.native.item(scene,'Camera')]
        self.assertEqual(camera_writes[-1],camera)

    def test_inactive_dimensions_only_are_ignored_in_snapshots_and_prepared_fingerprints(self):
        self.native.preview('starting','pip')
        scene = self.native.prepared['target']
        before = self.native.snapshot();fingerprint = self.native.fingerprint(scene)
        self.set(scene,OVERLAYS['B'],{'boundsWidth':987,'boundsHeight':654})
        self.assertEqual(self.native.snapshot(),before)
        self.assertEqual(self.native.fingerprint(scene),fingerprint)
        self.native.take()  # The two non-operative stored dimensions do not invalidate visible geometry.

    def test_each_active_bounds_dimension_change_still_invalidates_take(self):
        for dimension in ('boundsWidth','boundsHeight'):
            with self.subTest(dimension=dimension):
                self.native.preview('live','pip')
                scene = self.native.prepared['target']
                actual = self.get(scene,'Camera')
                self.set(scene,'Camera',{dimension:actual[dimension]+1})
                count = self.sim.requests.count('SetCurrentProgramScene')
                with self.assertRaisesRegex(ObsError,'layout changed'):self.native.take()
                self.assertEqual(self.sim.requests.count('SetCurrentProgramScene'),count)

    def test_active_bounds_restore_readback_mismatch_is_not_normalized_away(self):
        scene = SCENES['live'][1]
        self.set(scene,'Camera',{'boundsType':'OBS_BOUNDS_SCALE_INNER','boundsWidth':800,'boundsHeight':450})
        saved = self.native.snapshot()
        self.set(scene,'Camera',{'boundsWidth':900})
        ident = self.native.item(scene,'Camera')
        original = self.sim.rpc
        def mismatched(kind,data):
            result = original(kind,data)
            if kind=='GetSceneItemTransform' and data.get('sceneName')==scene and data.get('sceneItemId')==ident:
                result['sceneItemTransform']['boundsHeight'] += 1
            return result
        with patch.object(self.sim,'rpc',side_effect=mismatched):
            with self.assertRaisesRegex(ObsError,'geometry readback mismatch'):self.native.restore(saved)

    def test_raw_legacy_checkpoint_zero_bounds_can_restore_without_clamping(self):
        saved = self.native.snapshot();raw = copy.deepcopy(saved)
        for items in raw['geometry'].values():
            for item in items:
                if item['transform']['boundsType']=='OBS_BOUNDS_NONE':
                    item['transform'].update(boundsWidth=0,boundsHeight=0)
        self.native.preview('live','pip');self.native.take()
        self.native.restore(raw)
        self.assertEqual(self.native.snapshot(),saved)
        for write in self.sim.transform_writes:
            values = write['sceneItemTransform']
            if values.get('boundsType')=='OBS_BOUNDS_NONE':
                self.assertFalse({'boundsWidth','boundsHeight'} & values.keys())

if __name__ == '__main__': unittest.main()
