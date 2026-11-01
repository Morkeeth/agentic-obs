"""Injected process/controller effects only. NOT a real CEF crash trial."""
import copy
from pathlib import Path
import signal
import plistlib
import tempfile
import unittest
from director_browser_probe import Refused, attest, exercise, graphics_binding

APP=Path(__file__).resolve().parent/'.director-data/fake/OBS.app'

class Probe(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='.director-test-')
        self.addCleanup(self.tmp.cleanup)
        self.app=Path(self.tmp.name)/'OBS.app'
        (self.app/'Contents/MacOS').mkdir(parents=True)
        (self.app/'Contents/MacOS/OBS').write_bytes(b'fictional non-executable test fixture')
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'OBS','CFBundleIdentifier':'com.morkeeth.agentic-streamer'}))
        self.effects=[]; self.now=0
        self.log=Path(self.tmp.name)/'app.log'
        self.log.write_text('18:00:00.000: [director-renderer-binding] app_pid=101 renderer_pid=102 browser_id=7 source=Director / Graphics B\n')
        self.table={101:{'pid':101,'parent':1,'executable':str(self.app/'Contents/MacOS/OBS')},
                    102:{'pid':102,'parent':101,'executable':str(self.app/'Contents/Frameworks/OBS Helper (Renderer).app/Contents/MacOS/OBS Helper (Renderer)')}}
        self.state={'armed':True,'obs':{'connected':True},'destination':'obs', 'rendered_ready':True,
                    'native_review':{'payload_id':123,'bank':'B'},'agent_take_approved':True,'program':{'mode':'live'},'program_bank':'A'}
    def inspect(self,pid): return self.table[pid]
    def send(self,pid,sig): self.effects.append((pid,sig))
    def wait(self,seconds): self.now+=seconds
    def run_probe(self,read=None,**fields):
        return exercise(self.app,101,102,read or (lambda:copy.deepcopy(self.state)),inspect=self.inspect,
                        send=self.send,clock=lambda:self.now,wait=self.wait,binding_log=self.log,**fields)
    def test_missing_malformed_wrong_bundle_and_unsafe_metadata_refuse(self):
        info=self.app/'Contents/Info.plist';valid=info.read_bytes()
        for value in [b'not plist',plistlib.dumps({'CFBundleExecutable':'OBS','CFBundleIdentifier':'wrong'}),
                      *[plistlib.dumps({'CFBundleExecutable':name,'CFBundleIdentifier':'com.morkeeth.agentic-streamer'})
                        for name in ('../OBS','/OBS','bad\\name','','missing','OBS/other')]]:
            info.write_bytes(value)
            with self.assertRaises(Refused):self.run_probe()
        info.unlink()
        with self.assertRaises(Refused):self.run_probe()
        info.write_bytes(valid)
        self.assertEqual(self.effects,[])

    def test_exact_two_owned_identities_only(self):
        info=self.app/'Contents/Info.plist'
        for identity in ('com.morkeeth.agentic-streamer','com.morkeeth.agentic-streamer.browser'):
            info.write_bytes(plistlib.dumps({'CFBundleExecutable':'OBS','CFBundleIdentifier':identity}))
            self.assertFalse(self.run_probe()['signal_sent'])
        for identity in ('com.morkeeth.agentic-streamer.browser.other','com.obsproject.obs-studio','com.morkeeth.agentic-streamer.other'):
            info.write_bytes(plistlib.dumps({'CFBundleExecutable':'OBS','CFBundleIdentifier':identity}))
            with self.assertRaises(Refused): self.run_probe()
        self.assertEqual(self.effects,[])

    def test_source_binding_rejects_content_wrong_bank_pid_and_console_spoof(self):
        safe=self.log.read_text()
        for bad in [safe.replace('Graphics B','Fixture Content'),safe.replace('Graphics B','Graphics A'),
                    safe.replace('renderer_pid=102','renderer_pid=999'),
                    safe.replace('app_pid=101','app_pid=999'),
                    '18:00:00.000: [obs-browser console] '+safe.split(': ',1)[1], '']:
            self.log.write_text(bad)
            with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
            self.assertFalse(self.effects)
        self.log.write_text(safe)

    def test_latest_binding_wins_and_missing_symlink_or_large_log_refuse(self):
        safe=self.log.read_text()
        self.log.write_text(safe+safe.replace('renderer_pid=102','renderer_pid=103'))
        self.assertEqual(graphics_binding(self.log,101,'B')['renderer_pid'],103)
        with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
        self.log.unlink()
        with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
        target=Path(self.tmp.name)/'other.log';target.write_text(safe);self.log.symlink_to(target)
        with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
        self.log.unlink();self.log.write_text('x'*8_000_001)
        with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
        self.assertFalse(self.effects)

    def test_default_only_attests_and_never_signals(self):
        self.assertFalse(self.run_probe()['signal_sent']); self.assertEqual(self.effects,[])
    def test_exact_app_parent_and_renderer_identity_required(self):
        for field,value in [('parent',900),('executable','/unrelated/OBS Helper (Renderer)')]:
            with self.subTest(field=field):
                old=self.table[102][field];self.table[102][field]=value
                with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
                self.table[102][field]=old
        self.assertEqual(self.effects,[])
    def test_requires_confirmation_fresh_render_and_no_external_page(self):
        with self.assertRaises(Refused):self.run_probe(crash=True)
        for key,value in [('rendered_ready',False),('armed',False),('staged_page',{'id':'external'})]:
            old=copy.deepcopy(self.state);self.state[key]=value
            with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
            self.state=old
        self.assertEqual(self.effects,[])
    def test_only_selected_child_signaled_and_expired_review_observed(self):
        def read():
            value=copy.deepcopy(self.state)
            if self.effects: value.update(rendered_ready=False,native_review=None,agent_take_approved=False)
            return value
        result=self.run_probe(read,crash=True,confirmed=True)
        self.assertTrue(result['signal_sent']);self.assertEqual(self.effects,[(102,signal.SIGKILL)])
        self.assertFalse(result['native_pixels_verified'])
    def test_surviving_or_restarted_heartbeat_never_timeout_success(self):
        with self.assertRaises(Refused):self.run_probe(crash=True,confirmed=True)
        self.assertGreaterEqual(self.now,8);self.assertEqual(len(self.effects),1)
    def test_program_change_or_parent_loss_fails_without_recovery_writes(self):
        def read():
            value=copy.deepcopy(self.state)
            if self.effects:value['program']={'mode':'ending'}
            return value
        with self.assertRaises(Refused):self.run_probe(read,crash=True,confirmed=True)
        self.assertEqual(len(self.effects),1)

class ArtifactIdentity(unittest.TestCase):
    def test_built_bundle_metadata_accepts_matching_fake_process_without_signal(self):
        root=Path(__file__).resolve().parent/'fork-src'
        identities=[]
        for build, expected in [('build_macos','com.morkeeth.agentic-streamer'), ('build_director_browser','com.morkeeth.agentic-streamer.browser')]:
            app=(root/build/'frontend/RelWithDebInfo/OBS.app').resolve()
            metadata=plistlib.loads((app/'Contents/Info.plist').read_bytes())
            identities.append(metadata['CFBundleIdentifier'])
            self.assertEqual(metadata['CFBundleIdentifier'],expected)
            self.check_artifact(app)
        self.assertEqual(len(set(identities)),2)

    def check_artifact(self, app):
        self.assertTrue(app.is_dir(), 'browser candidate artifact must exist for this acceptance check')
        metadata=plistlib.loads((app/'Contents/Info.plist').read_bytes())
        executable=app/'Contents/MacOS'/metadata['CFBundleExecutable']
        self.assertTrue(executable.is_file())
        self.assertIn(metadata['CFBundleIdentifier'], ('com.morkeeth.agentic-streamer','com.morkeeth.agentic-streamer.browser'))
        table={201:{'pid':201,'parent':1,'executable':str(executable)},
               202:{'pid':202,'parent':201,'executable':str(app/'Contents/Frameworks/OBS Helper (Renderer).app/Contents/MacOS/OBS Helper (Renderer)')}}
        signals=[]
        state={'armed':True,'obs':{'connected':True},'destination':'obs','rendered_ready':True,
               'native_review':{'payload_id':42}}
        result=exercise(app,201,202,lambda:state,inspect=table.__getitem__,send=lambda *args:signals.append(args))
        self.assertFalse(result['signal_sent']); self.assertEqual(signals,[])
        for pid,field,value in [(201,'executable',str(app/'Contents/MacOS/obs')),
                                 (201,'executable','/wrong/OBS.app/Contents/MacOS/OBS'),
                                 (202,'parent',999), (202,'executable','/wrong/OBS Helper (Renderer)')]:
            old=table[pid][field];table[pid][field]=value
            with self.assertRaises(Refused):attest(app,201,202,table.__getitem__)
            table[pid][field]=old

if __name__=='__main__':unittest.main()
