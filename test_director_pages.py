"""Owned selected pages in simulated OBS protocol; external loads/pixels unverified."""
import copy
import unittest
from unittest.mock import patch
import test_director as existing
from director_obs import ObsError

PAGES={'A':'Director / Page A','B':'Director / Page B'}


class SelectedPages(unittest.TestCase):
    setUp=existing.NativeIntegration.setUp
    tearDown=existing.NativeIntegration.tearDown
    do=existing.NativeIntegration.do
    preview=existing.NativeIntegration.preview
    def register(self,id,url):
        self.do('page_register',id=id,name=id.title(),url=url)
        self.do('page_select',id=id)
        return self.d.state()['selected_page']
    def stage(self,selection):self.do('stage_selected_page',**selection)
    def test_stage_preview_take_other_page_preserves_on_air_settings_geometry_and_clocks(self):
        one=self.register('one','https://example.com/one')
        before_inputs=copy.deepcopy(self.sim.inputs);before=self.d.native.fingerprint(self.sim.program)
        bank=self.d.program_bank;payload=copy.deepcopy(self.d.banks[bank])
        self.stage(one)
        self.assertEqual(self.sim.inputs,before_inputs)  # Staging is data only.
        self.assertEqual(self.d.destination,'obs')
        with self.assertRaises(ValueError):self.do('preview',target='overlay')
        self.preview()
        self.assertEqual(self.d.native.fingerprint(self.sim.program),before)
        self.assertEqual(self.sim.inputs[PAGES[bank]],before_inputs[PAGES[bank]])
        self.assertEqual(self.sim.inputs['Content'],before_inputs['Content'])
        self.assertEqual(self.d.banks[bank],payload)
        self.do('approve_agent_take');self.d.execute_agent({'action':'take'},self.d.version)
        self.assertEqual(self.d.state()['program_page'],one)
        self.assertTrue(self.d.native.graphics_item(self.sim.program)['sceneItemEnabled']==False)
        current_bank=self.d.program_bank
        self.assertEqual(self.sim.inputs[PAGES[current_bank]]['settings']['url'],'https://example.com/one')
        current=copy.deepcopy(self.d.native.fingerprint(self.sim.program));input_one=copy.deepcopy(self.sim.inputs[PAGES[current_bank]])
        current_payload=copy.deepcopy(self.d.banks[current_bank])
        two=self.register('two','https://example.org/two');self.stage(two);self.preview()
        self.assertEqual(self.sim.inputs[PAGES[current_bank]],input_one)
        self.assertEqual(self.d.native.fingerprint(self.sim.program),current)
        self.assertEqual(self.d.banks[current_bank],current_payload)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        self.do('approve_agent_take');self.d.execute_agent({'action':'take'},self.d.version)
        self.assertNotEqual(self.d.program_bank,current_bank)
        self.assertEqual(self.sim.inputs[PAGES[self.d.program_bank]]['settings']['url'],'https://example.org/two')

    def test_ordinary_bound_content_recovery_and_page_camera_layout_undo(self):
        self.do('stage_patch',fields={'mode':'live','layout':'pip'});self.preview();self.do('take')
        self.do('checkpoint');saved=self.d.native.snapshot()
        page=self.register('one','https://example.com/one');self.stage(page);self.preview();self.do('take')
        self.do('stage_patch',fields={'layout':'side-by-side'});self.preview();self.do('take')
        inputs=copy.deepcopy(self.sim.inputs);scene=self.sim.program
        self.do('undo_camera_layout')
        self.assertEqual(self.sim.inputs,inputs)
        self.assertEqual(self.sim.program,scene)
        self.assertEqual(self.d.state()['program_page'],page)
        fingerprint=self.d.native.fingerprint(scene)
        self.assertEqual(fingerprint['Camera']['transform']['boundsWidth'],480)
        self.assertTrue(fingerprint[PAGES[self.d.program_bank]]['enabled'])
        self.assertFalse(fingerprint['Content']['enabled'])
        self.do('restore');self.assertEqual(self.d.native.snapshot(),saved)
        self.assertIsNone(self.d.state()['program_page'])

    def test_page_graphics_only_revision_preserves_layout_undo_across_banks(self):
        page=self.register('one','https://example.com/one');self.stage(page);self.preview();self.do('take')
        self.do('stage_patch',fields={'layout':'side-by-side'});self.preview();self.do('take')
        self.do('compose',title='Same selected page, new graphic');self.preview();self.do('take')
        self.do('undo_camera_layout')
        self.assertEqual(self.d.native.fingerprint(self.sim.program)['Camera']['transform']['boundsWidth'],480)
        self.assertEqual(self.d.state()['program_page'],page)

    def test_same_bank_recovery_never_reloads_a_different_on_air_page(self):
        page=self.register('one','https://example.com/one');self.stage(page);self.preview();self.do('take');self.do('checkpoint')
        for id in ('two','three'):
            page=self.register(id,'https://example.com/'+id);self.stage(page);self.preview();self.do('take')
        before=copy.deepcopy(self.sim.inputs);geometry=self.d.native.fingerprint(self.sim.program)
        payload=copy.deepcopy(self.d.banks);offset=len(self.sim.requests)
        with self.assertRaises(ObsError):self.do('restore')
        self.assertEqual(self.sim.inputs,before);self.assertEqual(self.d.native.fingerprint(self.sim.program),geometry)
        self.assertEqual(self.d.banks,payload)
        self.assertFalse(any(kind.startswith('Set') or kind.startswith('Trigger') for kind in self.sim.requests[offset:]))
        self.assertTrue(self.d.state()['can_restore'])
        saved=copy.deepcopy(self.d.anchor['native'])
        self.do('arm',enabled=True);self.do('page_select',id='one')
        self.stage(self.d.state()['selected_page']);self.preview();self.do('take')
        self.preview();self.do('take')  # Saved physical bank must receive its own reviewed take.
        self.do('restore');self.assertEqual(self.d.native.snapshot(),saved)

    def test_urls_identity_stale_selection_and_failed_settings_refuse(self):
        for url in ('http://example.com','https://user:secret@example.com','https://example.com/?token=secret','https://example.com/#secret','file:///tmp/test','https://exa mple.com'):
            with self.assertRaises(ValueError):self.do('page_register',id='bad',name='Bad',url=url)
        page=self.register('one','https://example.com/one');self.stage(page);self.preview();self.do('approve_agent_take')
        self.do('page_select',id=None)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        self.do('page_select',id='one');self.stage(self.d.state()['selected_page'])
        self.sim.inputs[PAGES['B']]['kind']='foreign-kind'
        with self.assertRaises(ObsError):self.preview()
        self.assertFalse(self.d.armed)

    def test_external_program_change_before_page_update_stops_all_writes(self):
        page=self.register('one','https://example.com/one');self.stage(page)
        original=self.d.native.set_page_url
        def change_program(bank,url,**kwargs):
            self.sim.program='Director / Live '+bank
            return original(bank,url,**kwargs)
        offset=len(self.sim.requests)
        with patch.object(self.d.native,'set_page_url',side_effect=change_program):
            with self.assertRaises(ObsError):self.preview()
        self.assertFalse(any(kind.startswith('Set') for kind in self.sim.requests[offset:]))
        self.assertFalse(self.d.armed)

    def test_failed_page_update_never_cuts_or_retries(self):
        page=self.register('one','https://example.com/one');self.stage(page)
        before=self.sim.program;offset=len(self.sim.requests)
        self.sim.refuse_on='SetInputSettings'
        with self.assertRaises(ObsError):self.preview()
        self.assertEqual(self.sim.program,before);self.assertFalse(self.d.armed)
        self.assertEqual(self.sim.requests[offset:].count('SetInputSettings'),1)
        self.assertNotIn('SetCurrentProgramScene',self.sim.requests[offset:])

    def test_recovery_cannot_substitute_url_ack_for_reviewed_page_take(self):
        first=self.register('one','https://example.com/one');self.stage(first);self.preview();self.do('take');self.do('checkpoint')
        for id in ('two','three'):
            page=self.register(id,'https://example.com/'+id);self.stage(page);self.preview();self.do('take')
        self.do('page_select',id='one');self.stage(first);self.preview();self.do('take')
        self.preview()  # Reloaded saved bank has a fresh graphics ACK, but no human Take.
        offset=len(self.sim.requests);before=copy.deepcopy(self.sim.inputs)
        with self.assertRaisesRegex(ObsError,'reviewed take'):self.do('restore')
        self.assertEqual(self.sim.inputs,before)
        self.assertFalse(any(kind.startswith('Set') or kind.startswith('Trigger') for kind in self.sim.requests[offset:]))
        self.assertTrue(self.d.state()['can_restore'])

    def test_page_and_bound_layouts_across_both_banks(self):
        page=self.register('one','https://example.com/one')
        for use_page in (True,False):
            if use_page:self.stage(page)
            else:self.do('stage_bound_content')
            for layout in ('camera','content','pip','side-by-side'):
                self.do('stage_patch',fields={'layout':layout})
                before=self.d.native.fingerprint(self.sim.program);inputs=copy.deepcopy(self.sim.inputs)
                current_bank=self.d.program_bank
                self.preview()
                self.assertEqual(self.d.native.fingerprint(self.sim.program),before)
                self.assertEqual(self.sim.inputs[PAGES[current_bank]],inputs[PAGES[current_bank]])
                self.assertEqual(self.sim.inputs['Content'],inputs['Content'])
                self.do('take');fp=self.d.native.fingerprint(self.sim.program)
                self.assertEqual(fp['Camera']['enabled'],layout!='content')
                self.assertEqual(fp[PAGES[self.d.program_bank]]['enabled'],use_page and layout!='camera')
                self.assertEqual(fp['Content']['enabled'],not use_page and layout!='camera')

    def test_catalog_revision_and_source_url_change_invalidate_review(self):
        page=self.register('one','https://example.com/one');self.stage(page);self.preview();self.do('approve_agent_take')
        self.do('page_register',id='one',name='One revised',url='https://example.com/revised')
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'take'},self.d.version)
        with self.assertRaises(ValueError):self.stage(page)
        self.do('page_select',id='one');self.stage(self.d.state()['selected_page']);self.preview();self.do('approve_agent_take')
        bank=self.d.native.prepared['bank'];self.sim.inputs[PAGES[bank]]['settings']['url']='https://example.org/foreign'
        before=self.sim.program;offset=len(self.sim.requests)
        with self.assertRaises(ObsError):self.d.execute_agent({'action':'take'},self.d.version)
        self.assertEqual(self.sim.program,before);self.assertFalse(self.d.armed)
        self.assertNotIn('SetCurrentProgramScene',self.sim.requests[offset:])

    def test_page_url_ack_without_readback_effect_is_not_success(self):
        page=self.register('one','https://example.com/one');self.stage(page)
        original=self.sim.rpc;writes=[]
        def acknowledge_only(kind,data):
            if kind=='SetInputSettings' and data.get('inputName') in PAGES.values():
                writes.append(copy.deepcopy(data));return {}
            return original(kind,data)
        before=copy.deepcopy(self.sim.inputs);program=self.sim.program;offset=len(self.sim.requests)
        with patch.object(self.sim,'rpc',side_effect=acknowledge_only):
            with self.assertRaisesRegex(ObsError,'readback not confirmed'):self.preview()
        self.assertEqual(self.sim.inputs,before);self.assertEqual(self.sim.program,program)
        self.assertEqual(len(writes),1);self.assertFalse(self.d.armed)
        self.assertNotIn('SetCurrentProgramScene',self.sim.requests[offset:])

    def test_agent_viewer_cannot_register_urls_or_select_unapproved_ids(self):
        page=self.register('one','https://example.com/one')
        catalog=copy.deepcopy(self.d.pages.catalog())
        self.do('audience',enabled=True)
        self.d.enqueue_request({'session':'s','event_id':'e','viewer_id':'123','text':'https://viewer.invalid/VIEWER_URL_ONLY','suggested':None})
        self.assertEqual(self.d.pages.catalog(),catalog)
        item=self.d.requests.view()[0]
        with self.assertRaises(ValueError):self.do('request_select',id=item['id'],revision=item['revision'],intent='stage_selected_page')
        self.assertNotIn('VIEWER_URL_ONLY',str(self.d.agent_state()))
        for action in ('page_register','page_select'):
            with self.assertRaises(ValueError):self.d.execute_agent({'action':action,'id':'other','url':'https://example.org'},self.d.version)
        with self.assertRaises(ValueError):self.d.execute_agent({'action':'stage_selected_page','id':'other','revision':'unknown'},self.d.version)
        self.d.execute_agent({'action':'stage_selected_page',**page},self.d.version)
        self.assertNotIn('https://example.com/one',str(self.d.agent_state()))
        self.do('stage_bound_content');self.preview();self.do('take')
        fp=self.d.native.fingerprint(self.sim.program)
        self.assertTrue(fp['Content']['enabled']);self.assertFalse(fp[PAGES[self.d.program_bank]]['enabled'])

if __name__=='__main__':unittest.main()
