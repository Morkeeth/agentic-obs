#!/usr/bin/env python3
"""Repeatable owned-OBS exercise. --simulate is protocol evidence, never pixels.

--real prompts for a password in memory and requires a browser controller open
for genuine renderer preview acknowledgments. No stream/record/output control.
"""
import argparse
import base64
import copy
from contextlib import ExitStack
import getpass
import hashlib
import subprocess
import json
import os
from pathlib import Path
import statistics
import tempfile
import threading
import time
import urllib.error
import urllib.request

from director import Director, ROOT
import director_schema as schema
from director_obs import ObsClient, OwnedOBS, OWNED, OVERLAYS
from director_server import make_server
from director_simulator import SimulatedOBS


class Exercise:
    def __init__(self, port, simulated, dwell=0, capture_dir=None):
        self.url = f'http://127.0.0.1:{port}'
        self.simulated = simulated
        self.dwell = dwell
        self.capture_dir = capture_dir
        self.captures = []
        self.clear_checks = []
        self.capture_details = []
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.receipts = []
        self.latencies = []
        self.observer = None

    def http(self, path, body=None):
        request = urllib.request.Request(self.url+path, data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Origin': self.url})
        with self.opener.open(request, timeout=30) as response: return json.load(response)

    def action(self, action, **kwargs):
        state = self.http('/api/state'); started = time.monotonic()
        result = self.http('/api/action', {'expected': state['version'], 'command': {'action': action, **kwargs}})
        elapsed = (time.monotonic()-started)*1000
        self.latencies.append(elapsed)
        self.receipts.append({'action': action, 'version': result['version'], 'ms': round(elapsed, 3)})
        return result

    def preview(self):
        old_scene = self.observer.req('GetSceneList')['currentProgramSceneName']
        old_bank = old_scene[-1]
        before = self.http('/api/render?channel=bank-'+old_bank)
        before.pop('clock', None)
        geometry = self.observer.fingerprint(old_scene)
        self.action('preview', target='obs')
        if self.simulated:
            # Explicitly simulated controller and OBS document acknowledgments.
            state = self.http('/api/render?channel=preview')
            self.http('/api/previewed', {'stage_id': state['id']})
            self.ack_banks()
        deadline = time.monotonic()+15
        while not self.http('/api/state')['previewed']:
            if time.monotonic() > deadline: raise RuntimeError('Controller and owned OBS bank renderers must acknowledge; no cut attempted')
            time.sleep(.05)
        after = self.http('/api/render?channel=bank-'+old_bank)
        after.pop('clock', None)
        if before != after or self.observer.fingerprint(old_scene) != geometry:
            raise RuntimeError('Preview changed the on-air bank payload or geometry')
        if self.observer.req('GetSceneList')['currentProgramSceneName'] != old_scene:
            raise RuntimeError('Preview changed actual program')
        if self.dwell: time.sleep(self.dwell)

    def ack_banks(self):
        for bank in ('A', 'B'):
            value=self.http('/api/render?channel=bank-'+bank)
            self.http('/api/rendered', {'bank':bank,'id':value['id'],'serial':value['serial'],'renderer':'obs','renderer_instance':('a' if bank=='A' else 'b')*32,**({'warm_epoch':value['warm_epoch']} if 'warm_epoch' in value else {})})

    def take(self, observer):
        observer.outputs_off()
        result = self.action('take')
        # A second independently authenticated connection reads actual OBS state.
        actual = observer.req('GetSceneList')
        expected = result['obs']['readback']['currentProgramSceneName']
        if actual['currentProgramSceneName'] != expected: raise RuntimeError('Independent program readback mismatch')
        self.receipts[-1]['independent_program'] = actual['currentProgramSceneName']
        if observer.graphics_item(expected)['sceneItemEnabled'] != schema.needs_graphics(result['program']):
            raise RuntimeError('Taken owned graphics visibility does not match authored/default segment')
        self.capture(expected, 'taken-program-scene')
        return result

    def capture(self, source, label):
        if not self.capture_dir: return
        if source not in OWNED and source not in OVERLAYS.values(): raise RuntimeError('Unowned screenshot refused')
        self.observer.source_guard()
        image = self.observer.req('GetSourceScreenshot', {'sourceName': source, 'imageFormat': 'png', 'imageWidth': 1920, 'imageHeight': 1080})['imageData']
        prefix = 'data:image/png;base64,'
        if not image.startswith(prefix) or len(image) > 20_000_000: raise RuntimeError('Unexpected OBS screenshot response')
        data = base64.b64decode(image[len(prefix):], validate=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'): raise RuntimeError('Invalid OBS PNG screenshot')
        self.capture_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.capture_dir/f'owned-{len(self.captures)+1:03d}-{label}.png'
        path.write_bytes(data); path.chmod(0o600)
        relative = str(path.relative_to(ROOT)); self.captures.append(relative)
        self.capture_details.append({'file': relative, 'source': source, 'scope': label, 'pixels_verified': False})

    def clear(self, observer):
        before = observer.snapshot(); scene = before['program']
        self.capture(scene, 'before-clear-program-scene')
        result = self.action('clear')
        after = observer.snapshot(); expected = copy.deepcopy(before)
        enabled = False
        item = next(item for item in expected['geometry'][scene] if item['source'] == OVERLAYS[scene[-1]])
        if not enabled: item['enabled'] = False
        if after != expected: raise RuntimeError('Clear changed unrelated scene/content geometry or failed owned visibility')
        actual = observer.graphics_item(scene)
        if actual['sceneItemEnabled'] != enabled: raise RuntimeError('Clear graphics visibility mismatch')
        self.clear_checks.append({'scene': scene, 'source': OVERLAYS[scene[-1]],
            'scene_item_id': actual['sceneItemId'], 'enabled': actual['sceneItemEnabled'],
            'unrelated_geometry_unchanged': True, 'source_texture_cleared': False, 'program_pixels_verified': False})
        self.capture(scene, 'after-clear-program-scene')
        self.capture(OVERLAYS[scene[-1]], 'after-clear-raw-browser-source')
        return result


def run_exercise(exercise, observer, *, backend=None, manual_recovery=False):
    exercise.observer = observer
    reads = []
    journeys = []
    for i in range(30):
        before = observer.snapshot()
        exercise.action('checkpoint')
        transitions = []
        for mode in ('starting', 'live', 'brb', 'ending'):
            exercise.action('stage_patch', fields={'mode': mode, 'layout': ('camera','content','pip','side-by-side')[i%4]})
            exercise.preview(); exercise.take(observer)
            scene = observer.req('GetSceneList')['currentProgramSceneName']
            transitions.append({'mode': mode, 'actual_program': scene, 'geometry': observer.fingerprint(scene)})
        exercise.action('restore')
        after = observer.snapshot()
        if after != before: raise RuntimeError(f'Full scene/geometry restore mismatch on cycle {i+1}')
        reads.append({'cycle': i+1, 'before': before, 'transitions': transitions, 'after': after})
    for i in range(10):
        composition = schema.compose(f'Chapter {i+1}', 'Expanded director exercise', duration=5+i/2)
        for j in range(3):
            composition['elements'].append({'id': f'originalOrbit{j}', 'kind': 'circle', 'x': 350+j*410, 'y': 200+j*40, 'w': 32+i*3, 'h': 32+i*3, 'color': '#0047ff', 'motion': 'orbit', 'start': j*.1, 'end': composition['duration']})
        exercise.action('stage_patch', fields={'mode': 'live', 'layout': 'pip', 'composition': composition})
        exercise.preview(); created = exercise.take(observer)
        exercise.action('revise', title=f'Chapter {i+1} / revised', color='#0047ff', motion='slide', duration=4+i/3)
        exercise.preview(); revised = exercise.take(observer)
        journeys.append({'journey': i+1, 'created': created['program'], 'revised': revised['program']})
        exercise.clear(observer); exercise.action('restore')
    persistent_checks = []
    for mode in ('starting','brb','ending'):
        exercise.action('stage_patch',fields={'mode':mode,'composition':{'elements':[]}})
        exercise.preview()
        exercise.take(observer)
        exercise.capture(observer.req('GetSceneList')['currentProgramSceneName'],'default-mode-reference')
        exercise.action('compose',title='Transientcheck',duration=30)
        exercise.preview();exercise.take(observer)
        exercise.clear(observer)
        persistent_checks.append({'mode':mode,'mutable_graphics_enabled':False,'program_pixels_verified':False})
    before = observer.req('GetSceneList')
    exercise.action('pause', paused=True)
    try:
        exercise.action('compose', title='Paused action must refuse')
        raise RuntimeError('Paused mutation unexpectedly succeeded')
    except urllib.error.HTTPError as exc:
        if exc.code != 400: raise
    exercise.action('pause', paused=False)
    for command in ({'action':'stage_patch','fields':{'layout':'not-a-layout'}}, {'action':'StartStream'}):
        state=exercise.http('/api/state')
        try:
            exercise.http('/api/action',{'expected':state['version'],'command':command})
            raise RuntimeError('Invalid action unexpectedly succeeded')
        except urllib.error.HTTPError as exc:
            if exc.code != 400: raise
    if observer.req('GetSceneList') != before: raise RuntimeError('Pause/invalid action changed scene')
    recovery = 'not exercised; use --manual-recovery for actual OBS disconnect'
    if backend is not None or manual_recovery:
        exercise.preview()
        if backend is not None: backend.drop_on='SetCurrentProgramScene'
        else: input('Disable the OBS WebSocket server now, then press Return. ')
        try:
            exercise.action('take')
            raise RuntimeError('Disconnected OBS take unexpectedly succeeded')
        except urllib.error.HTTPError as exc:
            if exc.code != 503: raise
        if exercise.http('/api/state')['armed']: raise RuntimeError('Disconnect failed to disarm')
        recovery='simulated socket loss, explicit reconnect, arm and restore' if backend else 'operator-induced actual OBS socket loss; reconnect required'
    result = {'status':'PASS', 'simulated':exercise.simulated, 'pixels_verified':False,
              'scene_restore_cycles':30, 'create_preview_take_revise_clear_journeys':10,
              'persistent_mode_clear_checks':persistent_checks,
              'model_calls':0, 'physical_microphone_verified':False,
              'preview_ack':'simulated HTTP acknowledgment' if exercise.simulated else 'browser renderer acknowledgment; pixels still require operator review',
              'recovery':recovery, 'readback_cycles': reads, 'composition_journeys': journeys, 'failures': [],
              'source_types': observer.bindings, 'independent_profile_collection_outputs': observer.snapshot(),
              'expected_refusals': ['paused mutation', 'invalid layout', 'forbidden output request'], 'action_receipts':exercise.receipts}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--simulate',action='store_true');mode.add_argument('--real',action='store_true')
    parser.add_argument('--port',type=int,default=8880);parser.add_argument('--obs-port',type=int,default=4455)
    parser.add_argument('--camera',default='Camera');parser.add_argument('--content',default='Content')
    parser.add_argument('--setup',action='store_true',help='Create/reconcile owned scenes with outputs off')
    parser.add_argument('--dwell',type=float,default=None);parser.add_argument('--manual-recovery',action='store_true')
    parser.add_argument('--capture',action='store_true',help='Real OBS only: save owned program source PNGs for human review; not a flicker proof')
    parser.add_argument('--out',type=Path,default=Path('.director-data/exercise.json'))
    args=parser.parse_args()
    if args.simulate and args.capture: parser.error('Simulated pixels are not evidence; --capture requires --real')
    output=args.out.resolve()
    if not output.is_relative_to(ROOT): parser.error('Evidence must stay inside this project')
    with ExitStack() as stack:
        backend=None; server=None; worker=None
        if args.simulate:
            backend=stack.enter_context(SimulatedOBS())
            tmp=stack.enter_context(tempfile.TemporaryDirectory(dir=ROOT,prefix='.director-exercise-'))
            server=make_server(0,Director(data_dir=tmp))
            worker=threading.Thread(target=server.serve_forever,name='exercise-http');worker.start()
            def cleanup():
                server.director.close();server.shutdown();server.server_close();worker.join(timeout=5)
            stack.callback(cleanup)
            port=server.server_port;obs_port=backend.port;password=backend.password
        else:
            port=args.port;obs_port=args.obs_port
            password=getpass.getpass('Authenticated local OBS password (memory only): ')
        exercise=Exercise(port,args.simulate,args.dwell if args.dwell is not None else 0 if args.simulate else .4, output.parent/'real-frames' if args.capture else None)
        if args.simulate:
            render_stop=threading.Event()
            def simulated_renderers():
                while not render_stop.wait(.03):
                    try: exercise.ack_banks()
                    except Exception: pass  # Expected during publication races; next poll uses current IDs.
            render_worker=threading.Thread(target=simulated_renderers,name='simulated-bank-renderers');render_worker.start()
            def stop_renderers():
                render_stop.set();render_worker.join(timeout=3)
            stack.callback(stop_renderers)
        health=exercise.http('/api/health')
        print(f'Verified director HTTP PID {health["pid"]} on loopback port {health["port"]}; '+('temporary simulator services stop on exit' if args.simulate else 'existing operator service'),flush=True)
        exercise.action('connect',password=password,port=obs_port)
        if args.simulate or args.setup:exercise.action('setup',camera=args.camera,content=args.content)
        exercise.action('arm',enabled=True)
        observer_client=ObsClient(password,port=obs_port);stack.callback(observer_client.close)
        observer=OwnedOBS(observer_client,port)
        observer.outputs_off()
        available={x['name']:x['kind'] for x in observer.inputs()}
        observer.bindings={k:{'name':name,'kind':available[name]} for k,name in (('camera',args.camera),('content',args.content)) if name}
        try:
            result=run_exercise(exercise,observer,backend=backend,manual_recovery=args.manual_recovery)
        except Exception as exc:
            failure={'status':'FAIL','simulated':args.simulate,'pixels_verified':False,'failure_type':type(exc).__name__,
                     'last_completed_action':exercise.receipts[-1] if exercise.receipts else None, 'action_receipts':exercise.receipts,
                     'detail':'Exercise stopped on an unexpected failure; inspect local terminal and actual OBS before retrying. No automatic replay.'}
            output.parent.mkdir(parents=True,exist_ok=True,mode=0o700);output.write_text(json.dumps(failure,indent=2));output.chmod(0o600)
            raise
        if backend or args.manual_recovery:
            if not backend:input('Re-enable the OBS WebSocket server, then press Return to reconnect. ')
            exercise.action('connect',password=password,port=obs_port);exercise.action('arm',enabled=True);exercise.action('restore')
            result['recovery']+='; explicit reconnect, re-arm and restore passed'
        if backend:
            backend.stale_before_reply=True
            exercise.action('refresh');backend.stale_before_reply=False
            result['stale_response_test']='simulated unrelated response ignored; matching response accepted'
        exercise.action('audience',enabled=False);exercise.clear(observer);exercise.action('arm',enabled=False)
        password=None
        samples=exercise.latencies
        result['action_latency_ms']={'samples':len(samples),'median':round(statistics.median(samples),3),
            'p95':round(sorted(samples)[max(0,int(len(samples)*.95)-1)],3),'max':round(max(samples),3)}
        result['timestamp_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        revision = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,timeout=3)
        result['source_revision'] = revision.stdout.strip() if revision.returncode == 0 else 'unavailable'
        source_files = ['director.py','director_schema.py','director_obs.py','director_server.py','director_voice.py','director_exercise.py','director_web/app.js','director_web/render.js']
        result['source_sha256'] = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_files}
        result['captured_owned_source_frames'] = exercise.captures
        result['capture_details'] = exercise.capture_details
        result['clear_visibility_checks'] = exercise.clear_checks
        result['obs_request_acks']=observer_client.audit
        result['limits']='No painted frames, real microphone, model generation, native Twitch polls or Twitch markers verified. Media state readback does not prove audible output.'
        output.parent.mkdir(parents=True,exist_ok=True,mode=0o700);output.write_text(json.dumps(result,indent=2));output.chmod(0o600)
        print(json.dumps({k:v for k,v in result.items() if k not in ('readback_cycles','composition_journeys','independent_profile_collection_outputs','source_sha256','action_receipts','obs_request_acks')}),flush=True)
        print(f'Local evidence: {output.relative_to(ROOT)}',flush=True)

if __name__=='__main__':main()
