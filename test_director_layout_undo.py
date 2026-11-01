"""One-level bound-layout recovery against simulated OBS; no physical camera proof."""
import copy
import unittest
from unittest.mock import patch
import test_director as existing
from director_obs import ObsError
import director_schema as schema


class LayoutUndo(unittest.TestCase):
    setUp = existing.NativeIntegration.setUp
    tearDown = existing.NativeIntegration.tearDown
    do = existing.NativeIntegration.do
    preview = existing.NativeIntegration.preview

    def take_layout(self, layout):
        self.do('stage_patch', fields={'mode': 'live', 'layout': layout})
        self.preview(); self.do('take')
    def bound(self):
        return {k:v for k,v in self.d.native.fingerprint(self.sim.program).items() if k in ('Camera','Content')}
    def prepare(self):
        self.take_layout('pip'); before = copy.deepcopy(self.bound())
        self.do('checkpoint')
        self.take_layout('side-by-side')
        return before

    def test_undo_restores_only_bound_geometry_and_consumes_record(self):
        expected = self.prepare()
        # Unrelated operator state and recovery point must survive this local operation.
        self.d.timer_state = {'anchor': 1, 'offset': 8, 'running': False}
        self.d.vote_state = {'counts': [3, 4], 'open': True}
        self.d.media_status = {'state': 'playing', 'volume': .2}
        self.d.alert = {'title':'Hydrate!'}
        self.preview(); self.do('approve_agent_take')
        saved = copy.deepcopy((self.d.program,self.d.timer_state,self.d.vote_state,self.d.media_status,self.d.alert,self.d.banks,self.d.anchor,self.d.checkpoint,self.d.preview_checkpoint))
        scene, preview = self.sim.program, self.sim.preview
        others = {k:v for k,v in self.d.native.fingerprint(scene).items() if k not in ('Camera','Content')}
        offset = len(self.sim.requests)
        self.do('undo_camera_layout')
        self.assertEqual(self.bound(), expected)
        self.assertEqual((self.sim.program,self.sim.preview), (scene,preview))
        self.assertEqual({k:v for k,v in self.d.native.fingerprint(scene).items() if k not in ('Camera','Content')},others)
        self.assertEqual((self.d.program,self.d.timer_state,self.d.vote_state,self.d.media_status,self.d.alert,self.d.banks,self.d.anchor,self.d.checkpoint,self.d.preview_checkpoint),saved)
        self.assertFalse(self.d._review_ready()); self.assertFalse(self.d._agent_approved())
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        self.assertNotIn('SetCurrentProgramScene',self.sim.requests[offset:])
        self.assertNotIn('SetCurrentPreviewScene',self.sim.requests[offset:])
        with self.assertRaises(ValueError): self.do('undo_camera_layout')

    def test_status_and_new_graphic_preserve_undone_layout(self):
        expected=self.prepare()
        frozen=copy.deepcopy((self.d.banks,self.d.anchor,self.d.checkpoint,self.d.air_started))
        self.do('undo_camera_layout')
        self.assertEqual(self.d.state()['current_native_layout'],'pip')
        self.assertEqual(self.d.agent_state()['current_native_layout'],'pip')
        self.assertEqual((self.d.banks,self.d.anchor,self.d.checkpoint,self.d.air_started),frozen)
        self.do('compose',title='Preserve camera arrangement')
        self.preview();self.do('take')
        self.assertEqual(self.bound(),expected)
        self.do('stage_patch',fields={'layout':'side-by-side'})
        self.preview();self.do('take')
        self.assertEqual(self.d.state()['current_native_layout'],'side-by-side')

    def test_external_arbitrary_geometry_is_reported_unknown(self):
        self.prepare()
        item=next(x for x in self.sim.scenes[self.sim.program] if x['sourceName']=='Camera')
        item['transform']['positionX']+=17
        self.d.probe()
        self.assertIsNone(self.d.state()['current_native_layout'])
        self.assertIsNone(self.d.agent_state()['current_native_layout'])

    def test_graphics_only_take_preserves_previous_arrangement_across_banks(self):
        expected = self.prepare()
        self.do('compose',title='New graphics only'); self.preview(); self.do('take')
        self.do('undo_camera_layout'); self.assertEqual(self.bound(),expected)

    def test_missing_unarmed_and_nonlive_refuse_without_writes(self):
        with self.assertRaises(ValueError): self.do('undo_camera_layout')
        self.prepare(); self.do('arm',enabled=False)
        offset=len(self.sim.requests)
        with self.assertRaises(ObsError): self.do('undo_camera_layout')
        self.assertFalse(any(x.startswith('Set') for x in self.sim.requests[offset:]))
        self.do('arm',enabled=True)
        self.do('stage_patch',fields={'mode':'brb'}); self.preview();self.do('take')
        offset=len(self.sim.requests)
        with self.assertRaises(ValueError): self.do('undo_camera_layout')
        self.assertFalse(any(x.startswith('Set') for x in self.sim.requests[offset:]))

    def test_external_geometry_and_binding_changes_refused(self):
        for change in ('geometry','binding'):
            with self.subTest(change=change):
                self.do('arm',enabled=True);self.prepare()
                if change=='geometry':
                    item=next(x for x in self.sim.scenes[self.sim.program] if x['sourceName']=='Camera')
                    item['transform']['positionX']+=19
                else: self.d.native.bindings['camera']['kind']='foreign-kind'
                offset=len(self.sim.requests)
                with self.assertRaises(ObsError):self.do('undo_camera_layout')
                self.assertFalse(self.d.armed)
                self.assertFalse(any(x.startswith('Set') for x in self.sim.requests[offset:]))
                if change=='binding': self.d.native.bindings=copy.deepcopy(self.d.bindings)

    def test_partial_write_failure_disarms_without_retry_or_rollback(self):
        self.prepare()
        original=self.sim.rpc; setters=[]
        def fail(kind,data):
            if kind in ('SetSceneItemTransform','SetSceneItemEnabled'):
                setters.append((kind,copy.deepcopy(data)))
                if len(setters)==2: raise ValueError('simulated partial setter failure')
            return original(kind,data)
        with patch.object(self.sim,'rpc',side_effect=fail):
            with self.assertRaises(ObsError):self.do('undo_camera_layout')
        self.assertEqual(len(setters),2);self.assertFalse(self.d.armed)
        self.assertTrue(self.d.state()['can_restore'])

    def test_first_live_take_does_not_invent_history(self):
        self.take_layout('pip')
        self.assertFalse(self.d.state()['can_undo_camera_layout'])
        with self.assertRaises(ValueError): self.do('undo_camera_layout')

    def test_enabled_state_operative_bounds_and_current_bank_item_ids(self):
        self.take_layout('camera'); expected=copy.deepcopy(self.bound())
        self.assertFalse(expected['Content']['enabled'])
        self.take_layout('content')
        scene=self.sim.program
        ids={x['sourceName']:x['sceneItemId'] for x in self.sim.scenes[scene]}
        offset=len(self.sim.transform_writes)
        self.do('undo_camera_layout')
        self.assertEqual(self.bound(),expected)
        self.assertEqual(self.bound()['Camera']['transform']['boundsWidth'],1920)
        for write in self.sim.transform_writes[offset:]:
            self.assertEqual(write['sceneName'],scene)
            self.assertIn(write['sceneItemId'],[ids['Camera'],ids['Content']])

    def test_unapproved_external_previous_geometry_is_not_saved_as_history(self):
        self.take_layout('pip')
        item=next(x for x in self.sim.scenes[self.sim.program] if x['sourceName']=='Camera')
        item['transform']['positionX']+=23
        self.take_layout('side-by-side')
        self.assertFalse(self.d.state()['can_undo_camera_layout'])
        with self.assertRaises(ValueError):self.do('undo_camera_layout')

    def test_voice_undo_and_viewer_refusal(self):
        expected=self.prepare()
        self.do('audience',enabled=True)
        self.assertEqual(self.d.audience('viewer',message='Director, undo that')['result'],'ignored')
        self.d.transcript('Director, undo that','undo-voice',True)
        self.assertEqual(self.bound(),expected)
        self.assertEqual(self.d.transcript('Director, undo that','undo-voice',True)['result'],'duplicate')

    def test_readback_mismatch_disarms_without_followup_setters(self):
        self.prepare(); original=self.sim.rpc; setters=[]
        def ignore(kind,data):
            if kind.startswith('Set'):
                setters.append(kind)
                if kind=='SetSceneItemTransform': return {}  # ACK without effect.
            return original(kind,data)
        with patch.object(self.sim,'rpc',side_effect=ignore):
            with self.assertRaisesRegex(ObsError,'readback mismatch'):self.do('undo_camera_layout')
        self.assertEqual(setters,['SetSceneItemTransform']);self.assertFalse(self.d.armed)

    def test_collection_change_refuses_before_any_write(self):
        self.prepare();self.sim.collection='Foreign collection'
        offset=len(self.sim.requests)
        with self.assertRaises(ObsError):self.do('undo_camera_layout')
        self.assertFalse(self.d.armed)
        self.assertFalse(any(x.startswith('Set') for x in self.sim.requests[offset:]))

    def test_reconnect_invalidates_saved_layout(self):
        self.prepare()
        self.do('connect',password=self.sim.password,port=self.sim.port);self.do('arm',enabled=True)
        with self.assertRaises(ValueError):self.do('undo_camera_layout')

    def test_grammar_and_bounded_agent_action(self):
        self.assertEqual(schema.parse_operator('Director, undo that'),{'action':'undo_camera_layout'})
        self.assertEqual(schema.parse_operator('undo camera layout'),{'action':'undo_camera_layout'})
        self.assertEqual(schema.parse_operator('restore segment/show'),{'action':'restore'})
        self.prepare()
        self.d.execute_agent({'action':'undo_camera_layout'},self.d.version)
        with self.assertRaises(ValueError): self.d.execute_agent({'action':'arm','enabled':True},self.d.version)

if __name__=='__main__':unittest.main()
