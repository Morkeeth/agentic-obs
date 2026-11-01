"""Expanded live director state machine, shared by HTTP, keys and local voice."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import tempfile
import time

import director_schema as schema
from director_queue import RequestQueue, INTENTS
from director_materials import MaterialCatalog
from director_pages import PageCatalog
from director_poll import LocalDirectorPoll
from director_obs import ObsClient, ObsError, OwnedOBS, SCENES, OVERLAYS

ROOT = Path(__file__).resolve().parent
FIXED = {'Director party': 'Celebration', 'Director show Hydrate!': 'Hydrate!', 'Director clear': None}


class Conflict(ValueError): pass


class Director:
    def __init__(self, port=8880, data_dir=None, media_dir=None, obs_factory=ObsClient):
        self.port = port
        self.data_dir = Path(data_dir or ROOT/'.director-data').resolve()
        self.media_dir = Path(media_dir or ROOT/'.director-media').resolve()
        for folder in (self.data_dir, self.media_dir):
            if not folder.is_relative_to(ROOT): raise ValueError('Director storage must stay inside this project')
        self.obs_factory = obs_factory
        self.lock = threading.RLock()
        self.version = 0
        self.staged = schema.default_segment()
        self.stage_id = 1
        self.operator_approval = None
        self.previewed = None
        self.preview_requested = None
        self.preview_target = None
        self.preview_serial = 0
        self.program = schema.segment({**self.staged, 'composition': {'elements': []}})
        self.program['lower'] = None
        self.air_id = 0
        self.air_started = self.clock()
        self.timer_state = None
        self.vote_state = None
        self.chat_poll = LocalDirectorPoll()
        self.voters = {}
        self.audience_enabled = False
        self.requests = RequestQueue()
        self.pages = PageCatalog()
        self.staged_page = None; self.program_page = None; self.page_runtime = None
        self.materials = MaterialCatalog()
        self.materials.register('twitch-story', 'The Twitch project story', 'twitch-story.md')
        self.alert = None
        self.paused = False
        self.paused_at = None
        self.paused_total = 0
        self.reduced_motion = False
        self.native = None
        self.bindings = {}
        self.layout_undo = None
        self.on_air_layout = None
        self.on_air_layout_name = None
        self.armed = False
        self.obs_state = {'connected': False, 'detail': 'Not connected; graphics can be rehearsed locally', 'readback': None}
        self.checkpoint = None
        self.anchor = None
        self.preview_checkpoint = None
        self.events = []
        self.markers = []
        self.seen_voice = {}
        self.error = None
        self.recipes = {}
        self.recipe_name = None
        self.recipe_index = None
        self.media_status = {'state': 'stopped', 'volume': 0}
        self.destination = 'overlay'
        self.preview_started = self.clock()
        self.bank_serial = 0
        self.program_bank = 'A'
        self.program_native = False
        self.bank_ready = {'A': None, 'B': None}
        self.bank_lost = {'A': False, 'B': False}
        self.bank_renderer_instance = {'A': None, 'B': None}
        self.bank_reload = {'A': None, 'B': None}
        self.bank_condition = threading.Condition(self.lock)
        self.in_flight = False
        self._arm_token = None
        self.warm_recovery = None
        self.payload_recovery = None
        self.warming = None
        self.warm_serial = 0
        self.recovering_bank = None
        self.banks = {bank: self._payload(self.program, 0, self.air_started, 'program') for bank in ('A', 'B')}
        self.program_payload = copy.deepcopy(self.banks['A'])
        self._load_recipes()

    def clock(self):
        now = self.paused_at if getattr(self, 'paused', False) else time.time()
        return now - getattr(self, 'paused_total', 0)

    def _load_recipes(self):
        path = self.data_dir/'recipes.json'
        if not path.exists() and not path.is_symlink(): return
        try:
            if path.is_symlink(): raise ValueError()
            if path.stat().st_size > 2_000_000: raise ValueError()
            data = json.loads(path.read_text())
            if not isinstance(data, list) or len(data) > 40: raise ValueError()
            validated = {}
            for item in data:
                item = schema.recipe(item)
                if item['name'] in validated: raise ValueError()
                validated[item['name']] = item
            self.recipes = validated
        except (ValueError, OSError, TypeError):
            self.error = 'Saved recipes failed validation; no stored actions were executed'

    def _save_recipes(self):
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.data_dir/'recipes.json'
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.data_dir, prefix='recipes-', suffix='.tmp', delete=False) as file:
                tmp = Path(file.name)
                json.dump(list(self.recipes.values()), file, ensure_ascii=False, indent=2)
            tmp.chmod(0o600)
            tmp.replace(path)
        finally:
            if tmp is not None and tmp.exists(): tmp.unlink()

    def catalog(self):
        if not self.media_dir.exists(): return []
        return sorted(p.name for p in self.media_dir.iterdir() if p.is_file() and not p.is_symlink()
                      and p.suffix.lower() in ('.wav', '.mp3', '.ogg', '.mp4', '.webm', '.mov')
                      and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_. -]{0,99}', p.name))[:100]

    def media_path(self, name):
        if name not in self.catalog(): raise ValueError('Choose an owned file from the local media catalog')
        path = (self.media_dir/name).resolve()
        if path.parent != self.media_dir: raise ValueError('Media must stay in the owned media directory')
        return path

    def record(self, action, outcome='applied'):
        self.events.append({'at': time.time(), 'action': action, 'outcome': outcome, 'version': self.version})
        self.events[:] = self.events[-80:]

    def state(self):
        with self.lock:
            return copy.deepcopy({'build': 'expanded-director-1', 'port': self.port, 'version': self.version,
                'external_page_load_verified':False if (self.staged_page or self.program_page) else None, 'page_catalog':self.pages.catalog(urls=True), 'selected_page':self.pages.selected, 'staged_page':self.staged_page, 'program_page':self.program_page,
                'poll_tally':self.vote_state, 'local_director_poll':self.poll_context(), 'material_catalog': self.materials.catalog(), 'selected_material': self.materials.selected,
                'stage_id': self.stage_id, 'staged': self.staged, 'controller_reviewed': self.previewed == self.stage_id,
                'rendered_ready': self._review_ready(), 'preview_refresh_required': self._preview_refresh_required(), 'agent_take_approved': self._agent_approved(),
                'operator_approval': self.operator_approval,
                'bank_readiness': {bank: self._bank_is_ready(bank) for bank in ('A','B')}, 'previewed': self._review_ready(), 'destination': self.destination,
                'arm_preparing': self._arm_token is not None, 'warm_recovery_pending': self.warm_recovery is not None, 'payload_recovery_pending': self.payload_recovery is not None,
                'current_native_layout': self.on_air_layout_name if self.on_air_layout else None, 'program_native': self.program_native,
                'program_bank': self.program_bank, 'prepared_bank': self.native.prepared['bank'] if self.native and self.native.prepared else None,
                'preview_target': self.preview_target, 'program': self.program, 'paused': self.paused,
                'reduced_motion': self.reduced_motion, 'obs': self.obs_state, 'armed': self.armed,
                'can_undo_camera_layout': bool(self.layout_undo and self.armed and self.program_native and self.program['mode'] == 'live'),
                'error': self.error, 'can_restore': self.anchor is not None or self.checkpoint is not None or self.preview_checkpoint is not None,
                'chat_requests': self.requests.view(), 'request_intents': list(INTENTS),
                'audience_enabled': self.audience_enabled, 'vote': self.vote_state,
                'media': self.media_status, 'catalog': self.catalog(), 'markers': self.markers,
                'recipes': list(self.recipes.values()), 'recipe_name': self.recipe_name, 'recipe_index': self.recipe_index,
                'events': self.events, 'clock': self.clock(), 'render': self.render('program'),
                'generation': {'mode': 'trusted external Codex MCP authoring or local deterministic templates', 'model_calls': 0,
                               'codex_runtime': 'No automatic model execution; external client privileges are not isolated by this server'},
                'voice': 'Local whisper.cpp only when explicitly configured; microphone not verified'})

    def _payload(self, segment, ident, started, phase):
        return {'mode_look': schema.mode_look(segment['mode']), 'segment': copy.deepcopy(segment),
                'id': ident, 'serial': self.preview_serial, 'started': started, 'phase': phase,
                'timer': {'anchor': started, 'offset': 0, 'running': False} if segment['timer'] else None,
                'vote': {'counts': [0]*len(segment['vote']['options']), 'open': False} if segment['vote'] else None,
                'alert': None}

    def _publish_bank(self, bank, payload):
        self.bank_serial += 1
        self.banks[bank] = copy.deepcopy(payload)
        self.banks[bank]['id'] = self.bank_serial
        self.bank_ready[bank] = None
        self.bank_reload[bank] = None
        self.bank_lost[bank] = False  # Explicit publication creates a fresh review, never a heartbeat.
        return self.bank_serial

    def _lose_bank(self, bank):
        self.bank_ready[bank] = None
        self.bank_lost[bank] = True
        if self.native and self.native.prepared and self.native.prepared['bank'] == bank:
            self.previewed = None
            self.preview_requested = None
            self.operator_approval = None

    def _bank_is_ready(self, bank):
        ready = self.bank_ready[bank]
        payload = self.banks[bank]
        if ready and time.monotonic()-ready['received'] >= 2.5:
            # Latch loss before a late/restarted renderer can revive old approval.
            self._lose_bank(bank)
            return False
        return bool(not self.bank_lost[bank] and ready and ready['id'] == payload['id']
                    and ready['serial'] == payload['serial'])

    def _review_ready(self):
        if self.previewed != self.stage_id or self.preview_requested != self.stage_id or self.preview_target != self.destination: return False
        if self.preview_target != 'obs': return self.preview_target == 'overlay'
        return bool(self.native and self.native.prepared and not self.native.prepared.get('graphics_pending') and self._bank_is_ready(self.native.prepared['bank']))

    def _preview_refresh_required(self):
        return bool(self.preview_target == 'obs' and self.native and self.native.prepared
                    and not self.native.prepared.get('graphics_pending')
                    and not self._bank_is_ready(self.native.prepared['bank']))

    def _approval_context(self):
        if not self._review_ready() or self.paused: return None
        prepared = self.native.prepared if self.preview_target == 'obs' else None
        payload = self.banks[prepared['bank']] if prepared else self.render('preview')
        return {'page':copy.deepcopy(self.staged_page), 'selected_page':copy.deepcopy(self.pages.selected), 'stage_id': self.stage_id, 'preview_serial': self.preview_serial,
                'destination': self.destination, 'bank': prepared['bank'] if prepared else None,
                'target': prepared['target'] if prepared else 'overlay',
                'payload_id': payload['id'], 'payload_serial': payload['serial'],
                'renderer_instance': self.bank_renderer_instance[prepared['bank']] if prepared else None,
                'content_hash': hashlib.sha256(json.dumps(self.staged, sort_keys=True).encode()).hexdigest(),
                'prepared_hash': hashlib.sha256(json.dumps(prepared, sort_keys=True).encode()).hexdigest()}

    def _agent_approved(self):
        return bool(self.operator_approval and self.operator_approval == self._approval_context())

    def bank_ack(self, bank, ident, serial, renderer, warm_epoch=None, renderer_instance=None):
        with self.lock:
            if bank not in ('A', 'B') or renderer != 'obs': raise ValueError('Owned OBS bank renderer acknowledgment required')
            if renderer_instance is not None and (not isinstance(renderer_instance, str) or not re.fullmatch(r'[a-f0-9]{32}', renderer_instance)):
                raise ValueError('Bounded renderer document identity required')
            if self.bank_renderer_instance[bank] is not None and renderer_instance is None:
                raise ValueError('Renderer document identity cannot be omitted')
            if type(ident) is not int or type(serial) is not int or (ident, serial) != (self.banks[bank]['id'], self.banks[bank]['serial']):
                if self.in_flight and type(ident) is int and type(serial) is int:
                    # An ACK already in transit may race recovery publication.
                    # Ignore it without readiness or notification; renderer must
                    # fetch and paint the fresh identity before completion.
                    return {'rendered': None, 'stale': True}
                raise Conflict('Stale bank rendering acknowledgment')
            if warm_epoch is not None and type(warm_epoch) is not int: raise ValueError('Invalid renderer warm epoch')
            expected_warm = self.warming['epoch'] if self.warming and self.warming['bank'] == bank else None
            if warm_epoch != expected_warm:
                return {'rendered': None, 'stale': True}
            self._bank_is_ready(bank)  # Detect a gap even if no state read occurred during it.
            reload = self.bank_reload[bank]
            if reload and expected_warm is None and reload['previous_instance'] is not None and renderer_instance in (None, reload['previous_instance']):
                return {'rendered': None, 'stale': True, 'fresh_document_required': True}

            previous_instance = self.bank_renderer_instance[bank]
            if renderer_instance is not None:
                self.bank_renderer_instance[bank] = renderer_instance
                if previous_instance is not None and previous_instance != renderer_instance:
                    self._lose_bank(bank)
            if expected_warm is not None:
                # Explicit outputs-off re-arming supplied a fresh, exact challenge.
                self.bank_lost[bank] = False
            if self.bank_lost[bank]:
                return {'rendered': None, 'stale': True, 'preview_required': True}
            if (not self.in_flight and self.preview_target == 'obs' and self.native and self.native.prepared
                    and self.native.prepared['bank'] == bank and self.native.prepared.get('graphics_pending')):
                try:
                    self._require_native()
                    self.native.reveal_prepared_graphics()
                except ObsError as exc:
                    self.native.prepared = None  # Never retry a refused visibility mutation on another heartbeat.
                    self._obs_failed(); self.error = str(exc)
                    self.version += 1; self.record('preview_graphics', 'not confirmed')
                    raise
            self.bank_reload[bank] = None  # Only an accepted fresh painted ACK completes reload.
            self.bank_ready[bank] = {'id': ident, 'serial': serial, 'received': time.monotonic()}
            # Native-only surface: the exact OBS bank's real paint heartbeat can
            # complete render review. This is NOT human approval or an invented ACK.
            if (self.preview_target == 'obs' and self.preview_requested == self.stage_id
                    and self.native and self.native.prepared and self.native.prepared['bank'] == bank
                    and not self.native.prepared.get('graphics_pending')):
                self.previewed = self.stage_id
            self.bank_condition.notify_all()
            return {'rendered': bank, 'id': ident, 'serial': serial}

    def _wait_bank(self, bank, operation='Restore', preparation=None):
        deadline = time.monotonic()+(20 if preparation is not None else 5)
        native = self.native
        self.in_flight = True
        try:
            while True:
                # ACK readiness never overrides a genuine loss of human arming
                # or the connection that owns this transaction.
                if preparation is None: self._require_native()
                else: self._arm_permission(preparation)
                if self.native is not native or not native.client.connected:
                    raise ObsError(f'{operation} connection lost; outcome uncertain')
                if self._bank_is_ready(bank): return
                remaining = deadline-time.monotonic()
                if remaining <= 0: raise ObsError(f'{operation} bank did not render; outcome uncertain')
                self.bank_condition.wait(remaining)
        finally:
            self.in_flight = False

    def render(self, channel):
        with self.lock:
            if channel == 'preview':
                payload = self._payload(self.staged, self.stage_id, self.preview_started, 'prepared')
            elif channel == 'program':
                payload = copy.deepcopy(self.banks[self.program_bank] if self.program_native else self.program_payload)
                payload.update(timer=self.timer_state, vote=self.vote_state, alert=self.alert)
            elif channel in ('bank-A', 'bank-B'):
                bank = channel[-1]
                payload = copy.deepcopy(self.banks[bank])
                if self.warming and self.warming['bank'] == bank: payload['warm_epoch'] = self.warming['epoch']
                if self.program_native and bank == self.program_bank and bank != self.recovering_bank:
                    payload.update(timer=self.timer_state, vote=self.vote_state, alert=self.alert)
            else: raise ValueError('Unknown renderer channel')
            payload['poll_epoch']=self.chat_poll.epoch if channel=='program' or (self.program_native and channel=='bank-'+self.program_bank) else None
            payload.update(clock=self.clock(), paused=self.paused, reduced_motion=self.reduced_motion,
                           channel=channel, preview_serial=payload['serial'],
                           review_requested=channel == 'preview' and self.preview_requested == self.stage_id and self.previewed != self.stage_id)
            return payload

    def _take_pose(self, payload):
        c = payload['segment']['composition']
        age = max(0, self.clock()-payload['started'])
        if age >= c['duration']*c['repeat']:
            return min((p['start']+(p['end']-p['start'])*.25 for p in c['elements']), default=0)
        return age

    def _stage(self, value):
        value = schema.segment(value)
        if value['media']: self.media_path(value['media'])
        if value['mode']!='live': self.staged_page=None
        self.staged = value
        self.stage_id += 1
        self.previewed = None
        self.preview_requested = None
        self.preview_target = None
        if self.native: self.native.prepared = None

    def _require_native(self):
        if not self.native or not self.obs_state['connected'] or not self.armed:
            raise ObsError('Connect and explicitly arm owned OBS control first')

    def _arm_permission(self, token):
        if (self._arm_token is not token or self.native is not token['native'] or not self.obs_state['connected']
                or not self.native.client.connected):
            raise ObsError('Arm preparation cancelled or connection lost; outcome uncertain')

    def _prepare_arm(self):
        native = self.native
        self.armed = False
        self.previewed = None; self.preview_requested = None; self.preview_target = None
        native.prepared = None
        native.outputs_off()
        token = {'native': native}
        self._arm_token = token
        permit = lambda: self._arm_permission(token)
        self.obs_state['detail'] = 'Preparing owned bank renderers with outputs off; not armed'
        try:
            # A failed preparation is recoverable without setup or overwriting
            # the show's checkpoint. Only its temporary owned items/preview move.
            for recovery_name in ('payload_recovery','warm_recovery'):
                recovery = getattr(self, recovery_name)
                if recovery:
                    for saved in recovery['items']:
                        native.arm_prepare_graphics(saved, saved['enabled'], recovery, permit)
                    native.arm_prepare_preview(recovery['preview'], recovery, permit)
                    setattr(self, recovery_name, None)
            original = native.snapshot()
            context = {'program': original['program'], 'preview': original['preview'],
                       'signature': native.fingerprint(original['program']), 'items': []}
            self.warm_recovery = context
            for bank in ('A','B'):
                if self._bank_is_ready(bank): continue
                permit()
                # An already visible program bank can simply prove its current
                # heartbeat. A hidden one needs a different owned preview scene.
                active_visible = (context['program'][-1] == bank and native.graphics_item(context['program'])['sceneItemEnabled'])
                saved = None
                if not active_visible:
                    scene = next(pair[0 if bank == 'A' else 1] for pair in SCENES.values()
                                 if pair[0 if bank == 'A' else 1] != context['program'])
                    item = native.graphics_item(scene)
                    saved = {'scene': scene, 'id': item['sceneItemId'], 'source': item['sourceName'], 'enabled': item['sceneItemEnabled']}
                    context['items'].append(saved)
                    native.arm_prepare_preview(scene, context, permit)
                    native.arm_prepare_graphics(saved, True, context, permit)
                # Challenge only bank-render metadata; program payload/identity
                # remains byte-for-byte unchanged. Old in-transit ACKs cannot win.
                self.warm_serial += 1
                self.warming = {'bank': bank, 'epoch': self.warm_serial}
                self.bank_ready[bank] = None
                self._wait_bank(bank, operation='Arm preparation', preparation=token)
                self.warming = None
                if saved: native.arm_prepare_graphics(saved, saved['enabled'], context, permit)
            native.arm_prepare_preview(context['preview'], context, permit)
            permit()
            if native.snapshot() != original:
                raise ObsError('Arm preparation scene/geometry restoration not confirmed')
            self.obs_state['readback'] = native.verify()
            # Final restoration/readback can outlast a heartbeat TTL. Release
            # the lock for hot hidden heartbeats before reporting armed.
            for bank in ('A','B'): self._wait_bank(bank, operation='Arm final readiness', preparation=token)
            permit()
            if not all(self._bank_is_ready(bank) for bank in ('A','B')):
                raise ObsError('Arm renderer readiness was not jointly confirmed')
            self.warm_recovery = None
        finally:
            self._arm_token = None
            self.warming = None

    def _prepaint_bank(self, bank, payload, operation):
        """Prepare a hidden/opposite source in owned preview; never wake via screenshots."""
        self._require_native()
        native = self.native
        def permit():
            self._require_native()
            if self.native is not native or not native.client.connected:
                raise ObsError(operation+' connection lost; outcome uncertain')
        native.wait_transition()
        current = native.verify()
        program = current['currentProgramSceneName']
        if bank == program[-1] and native.graphics_item(program)['sceneItemEnabled']:
            # Existing visible-source in-place restore is the explicit program
            # operation itself, not a hidden-source wake or a new visibility reveal.
            self._publish_bank(bank, payload)
            self._wait_bank(bank, operation=operation)
            return
        current = native.verify()
        native.require_owned_scenes(current)
        scene = next(pair[0 if bank == 'A' else 1] for pair in SCENES.values()
                     if pair[0 if bank == 'A' else 1] != program)
        item = native.graphics_item(scene)
        saved = {'scene':scene, 'id':item['sceneItemId'], 'source':item['sourceName'], 'enabled':item['sceneItemEnabled']}
        geometry = native.fingerprint(scene)
        context = {'program':program, 'preview':current['currentPreviewSceneName'],
                   'signature':native.fingerprint(program), 'items':[saved]}
        self.payload_recovery = context
        native.payload_prepare_preview(scene, context, permit)
        native.payload_prepare_graphics(saved, True, context, permit)
        prepared_geometry = native.fingerprint(scene)
        self._publish_bank(bank, payload)
        self._wait_bank(bank, operation=operation)
        permit()
        if native.fingerprint(scene) != prepared_geometry:
            raise ObsError('Payload preparation geometry changed; outcome uncertain')
        # No finally cleanup: genuine disarm/loss forbids every later setter.
        native.payload_prepare_graphics(saved, saved['enabled'], context, permit)
        native.payload_prepare_preview(context['preview'], context, permit)
        if native.fingerprint(scene) != geometry:
            raise ObsError('Payload preview geometry restoration not confirmed')
        permit()
        if not self._bank_is_ready(bank): raise ObsError(operation+' paint readiness expired; preview again')
        self.payload_recovery = None

    def _checkpoint(self, native=None):
        return copy.deepcopy({'poll_taken':self.chat_poll.taken, 'program_page':self.program_page, 'program': self.program, 'timer': self.timer_state, 'vote': self.vote_state,
            'voters': self.voters, 'air_started': self.air_started, 'native': native, 'alert': self.alert,
            'banks': self.banks, 'program_bank': self.program_bank, 'program_native': self.program_native,
            'program_payload': self.program_payload})

    def _obs_failed(self):
        self.chat_poll.renew(self.program['vote'],taken=False)
        self.requests.clear()
        self.layout_undo = None
        self.on_air_layout = None
        self._arm_token = None
        self.warming = None
        self.bank_ready = {'A': None, 'B': None}
        self.operator_approval = None
        self.armed = False
        self.previewed = None
        self.preview_target = None
        connected = bool(self.native and self.native.client.connected)
        self.obs_state.update(connected=connected, detail='OBS action not confirmed; disarmed. Inspect readback, reconnect if needed, then restore.')
        self.bank_condition.notify_all()

    def execute(self, command, expected):
        with self.lock:
            if self.in_flight and (self._arm_token is not None or self.payload_recovery is not None) and isinstance(command, dict) and command.get('action') == 'arm' and command.get('enabled') is False:
                schema.obj(command, ('action','enabled'), ('enabled',))
                if type(expected) is not int or expected != self.version: raise Conflict('Controller state changed')
                self.requests.clear()
                self.chat_poll.renew(self.program['vote'],taken=False)
                self._arm_token = None; self.warming = None; self.armed = False; self.operator_approval = None
                self.obs_state['detail'] = 'Native preview preparation cancelled; inspect preview, then explicitly re-arm to recover'
                self.bank_condition.notify_all()
                self.version += 1; self.record('arm', 'cancelled preparation')
                return self.state()
            if self.in_flight: raise Conflict('A native action is awaiting its bank renderer')
            if type(expected) is not int or expected != self.version:
                raise Conflict('Controller state changed; refreshed state is required before retrying')
            if not isinstance(command, dict) or not isinstance(command.get('action'), str): raise ValueError('Expected a validated action')
            if command['action'] == 'operator':
                schema.obj(command, ('action', 'text', 'target'), ('text',))
                target = schema.choice(command.get('target', self.destination), ('overlay', 'obs'))
                command = schema.parse_operator(command['text'])
                if command['action'] in ('preview', 'scene'): command.setdefault('target', target)
            action = command['action']
            if self.paused and action not in ('pause', 'clear', 'restore', 'undo_camera_layout', 'requests_clear', 'request_reject', 'local_director_polls', 'poll_control', 'vote_control', 'media_stop', 'disconnect', 'connect', 'refresh', 'marker', 'audience', 'reduced_motion'):
                raise ValueError('Director paused; resume before changing the segment')
            self.error = None
            if action != 'approve_agent_take': self.operator_approval = None
            try:
                self._apply(action, command)
            except ObsError as exc:
                self._obs_failed()
                self.error = str(exc)
                self.version += 1
                self.record(action, 'not confirmed')
                raise
            self.version += 1
            self.record(action)
            return self.state()

    def _apply(self, action, c):
        if action == 'stage_visual_poll':
            schema.obj(c,('action','vote'),('vote',))
            value=schema.vote(c['vote']) if c['vote'] is not None else None
            if value is not None and value['kind']!='vote':raise ValueError('Visual polls use local fixed-choice votes only')
            self._stage({**self.staged,'vote':value})
        elif action == 'local_director_polls':
            schema.obj(c,('action','enabled'),('enabled',))
            self.chat_poll.enabled=schema.boolean(c['enabled'])
            self.chat_poll.renew(self.program['vote'])
        elif action == 'poll_control':
            schema.obj(c,('action','epoch','operation'),('epoch','operation'))
            if not self.chat_poll.taken or self.chat_poll.epoch is None or c['epoch']!=self.chat_poll.epoch:
                raise ValueError('Current taken poll epoch required')
            self._apply('vote_control',{'action':'vote_control','operation':c['operation']})
        elif action == 'page_register':
            schema.obj(c,('action','id','name','url'),('id','name','url'))
            self.pages.register(c['id'],c['name'],c['url'])
            self._stage(self.staged)
        elif action == 'page_remove':
            schema.obj(c,('action','id'),('id',));self.pages.remove(c['id'])
            self._stage(self.staged)
        elif action == 'page_select':
            schema.obj(c,('action','id'),('id',));self.pages.select(c['id'])
            self._stage(self.staged)
        elif action == 'stage_selected_page':
            schema.obj(c,('action','id','revision'),('id','revision'))
            selection={'id':c['id'],'revision':c['revision']};self.pages.resolve(selection)
            self.staged_page=selection
            self.destination='obs'
            self._stage({**self.staged,'mode':'live'})
        elif action == 'stage_bound_content':
            schema.obj(c,('action',));self.staged_page=None
            self._stage({**self.staged,'mode':'live'})
        elif action == 'material_register':
            schema.obj(c,('action','id','name','file'),('id','name','file'))
            self.materials.register(c['id'],c['name'],c['file'])
        elif action == 'material_select':
            schema.obj(c,('action','id'),('id',));self.materials.select(c['id'])
        elif action == 'approve_agent_take':
            schema.obj(c, ('action',))
            context = self._approval_context()
            if context is None: raise ValueError('Render and review this exact preview before operator approval')
            self.operator_approval = context
        elif action == 'destination':
            schema.obj(c, ('action', 'target'), ('target',))
            target = schema.choice(c['target'], ('overlay', 'obs'))
            if target != self.destination:
                self.previewed = None; self.preview_requested = None; self.preview_target = None
                if self.native: self.native.prepared = None
            self.destination = target
        elif action == 'scene':
            schema.obj(c, ('action', 'mode', 'layout', 'target'), ('mode',))
            fields = {'mode': c['mode'], 'composition': {'elements': []}}
            if 'layout' in c: fields['layout'] = c['layout']
            self._apply('stage_patch', {'action': 'stage_patch', 'fields': fields})
            self._apply('preview', {'action': 'preview', 'target': c.get('target', self.destination)})
        elif action == 'stage':
            schema.obj(c, ('action', 'segment'), ('segment',)); self._stage(c['segment'])
        elif action == 'stage_patch':
            schema.obj(c, ('action', 'fields'), ('fields',))
            fields = c['fields']
            if not isinstance(fields, dict) or not fields: raise ValueError('Provide segment fields')
            if 'mode' in fields and fields['mode'] != self.staged['mode'] and 'composition' not in fields:
                fields = {**fields, 'composition': {'elements': []}}
            self._stage({**self.staged, **fields})
        elif action == 'compose':
            schema.obj(c, ('action', 'title', 'subtitle', 'template', 'accent', 'motion', 'duration'), ('title',))
            value = schema.compose(**{k: v for k, v in c.items() if k != 'action'})
            self._stage({**self.staged, 'composition': value})
        elif action == 'revise':
            schema.obj(c, ('action', 'color', 'motion', 'duration', 'title', 'subtitle'), ())
            value = copy.deepcopy(self.staged['composition'])
            old_duration = value['duration']
            for field in ('title', 'subtitle'):
                if field in c:
                    schema.text(c[field])
                    if not any(item['id'] == field and item['kind'] == 'text' for item in value['elements']):
                        raise ValueError('Edit primitives to revise text without a named title/subtitle')
            for item in value['elements']:
                if item['kind'] == 'text' and item['id'] in ('title', 'subtitle') and item['id'] in c:
                    item['text'] = c[item['id']]
                if 'color' in c: item['color'] = schema.color(c['color'])
                if 'motion' in c: item['motion'] = schema.choice(c['motion'], schema.MOTIONS)
                if 'duration' in c:
                    duration = schema.number(c['duration'], .3, 120)
                    item['start'] *= duration / old_duration; item['end'] *= duration / old_duration
            if 'duration' in c: value['duration'] = c['duration']
            self._stage({**self.staged, 'composition': value})
        elif action == 'preview':
            schema.obj(c, ('action', 'target'))
            target = schema.choice(c.get('target', self.destination), ('overlay', 'obs'))
            if self.staged_page and target!='obs':raise ValueError('Selected pages require owned OBS preview; local graphics cannot display them')
            self.preview_serial += 1
            self.preview_started = self.clock()
            self.destination = target
            if target == 'obs':
                self._require_native()
                if self.preview_checkpoint is None:
                    self.preview_checkpoint = self._checkpoint(self.native.snapshot())
                self.obs_state['readback'] = self.native.preview(self.staged['mode'], self.staged['layout'], defer_graphics=True, graphics_visible=schema.needs_graphics(self.staged), page_url=self.pages.resolve(self.staged_page) if self.staged_page else None)
                self.program_bank = self.native.prepared['program'][-1]
                bank = self.native.prepared['bank']
                self._bank_is_ready(bank)  # Observe a missed heartbeat even without a prior UI poll.
                reload = self.bank_lost[bank] or self.bank_reload[bank] is not None
                previous_instance = (self.bank_reload[bank]['previous_instance'] if self.bank_reload[bank]
                                     else self.bank_renderer_instance[bank])
                self._publish_bank(bank, self._payload(self.staged, self.stage_id, self.preview_started, 'prepared'))
                if reload:
                    # One deliberate inactive-bank reload, never heartbeat-driven or automatic take.
                    self.bank_reload[bank] = {'previous_instance': previous_instance}
                    self.bank_renderer_instance[bank] = None
                    self.native.reload_prepared_graphics(bank)

            self.preview_target = target
            self.preview_requested = self.stage_id
            self.previewed = None
        elif action == 'take':
            schema.obj(c, ('action',))
            if not self._review_ready():
                raise ValueError('Preview this revision and wait for its owned OBS bank renderer before take')
            # Resolve catalog changes before any native cut. Never expose a path in errors.
            media_path = None
            if self.staged['media']:
                self._require_native()
                media_path = self.media_path(self.staged['media'])
            if self.staged_page: self.pages.resolve(self.staged_page)
            previous_layout = None
            if self.preview_target == 'obs' and self.program_native and self.program['mode'] == 'live' and self.staged['mode'] == 'live' and self.program_page==self.staged_page:
                self._require_native()
                previous_layout = self.native.bound_layout()
            checkpoint = self.preview_checkpoint or self._checkpoint()
            self.checkpoint = checkpoint
            if self.preview_target == 'obs':
                self._require_native()
                bank = self.native.prepared['bank']
                prepared_payload = self.banks[bank]
                current_layout = None
                if self.staged['mode'] == 'live':
                    prepared = self.native.prepared
                    current_layout = {'scene': prepared['target'], 'bindings': self.native.layout_bindings(prepared['target']),
                        'geometry': {b['name']: copy.deepcopy(prepared['geometry'][b['name']]) for b in self.native.layout_bindings(prepared['target']).values()}}
                self.obs_state['readback'] = self.native.take()
                if previous_layout is not None and previous_layout == self.on_air_layout:
                    remapped={b['name']:previous_layout['geometry'][previous_layout['bindings'][role]['name']] for role,b in current_layout['bindings'].items()}
                    changed=any(old['enabled']!=current_layout['geometry'][name]['enabled'] or ((old['enabled'] or current_layout['geometry'][name]['enabled']) and old['transform']!=current_layout['geometry'][name]['transform']) for name,old in remapped.items())
                    if changed:
                        self.layout_undo = {'before': remapped, 'before_name': self.on_air_layout_name, 'expected': current_layout}
                    elif self.layout_undo and self.layout_undo['expected'] == previous_layout:
                        prior=self.layout_undo['expected']['bindings']
                        self.layout_undo['before']={b['name']:self.layout_undo['before'][prior[role]['name']] for role,b in current_layout['bindings'].items()}
                        self.layout_undo['expected'] = current_layout
                    else:
                        self.layout_undo = None
                else:
                    self.layout_undo = None
                self.on_air_layout = current_layout
                self.on_air_layout_name = self.staged['layout'] if current_layout else None
                pose = self._take_pose(prepared_payload)
                # Identity/text/geometry were already rendered. Only release the prepared clock.
                self.program_bank = bank
                self.program_native = True
                prepared_payload.update(phase='program', started=self.clock()-pose)
            elif self.preview_target != 'overlay': raise ValueError('Choose a preview target first')
            else:
                self.layout_undo = None; self.on_air_layout = None
            self.program_page=copy.deepcopy(self.staged_page) if self.preview_target=='obs' else None
            self.program = copy.deepcopy(self.staged)
            self.air_id += 1; self.air_started = self.clock()
            if self.preview_target == 'obs':
                self.air_started = self.banks[self.program_bank]['started']
            else:
                self.program_native = False
                self.program_payload = self._payload(self.program, self.air_id, self.air_started, 'program')
            self.timer_state = {'anchor': self.clock(), 'offset': 0, 'running': True} if self.program['timer'] else None
            self.vote_state = {'counts': [0]*len(self.program['vote']['options']), 'open': True} if self.program['vote'] else None
            self.voters = {}; self.alert = None
            self.chat_poll.renew(self.program['vote'],taken=bool(self.program['vote']))
            self.previewed = None; self.preview_requested = None
            self.preview_checkpoint = None
            # The cut is confirmed: publish its truth before fallible follow-up effects.
            # Preserve the pre-cut checkpoint; never silently roll back or retry a cut.
            try:
                if media_path is not None:
                    self._require_native()
                    self.media_status = self.native.media(media_path, self.program['volume'])
                elif self.native and self.armed and self.media_status['state'] != 'stopped':
                    self.media_status = self.native.media()
            except ObsError:
                self.media_status = {'state': 'unknown', 'volume': None}
                raise ObsError('Program committed; media effect not confirmed. Inspect owned media before recovery.') from None
        elif action in ('request_select','request_accept','request_reject','requests_clear'):
            if action == 'requests_clear':
                schema.obj(c, ('action',)); self.requests.clear()
            else:
                fields=('action','id','revision','intent') if action in ('request_select','request_accept') else ('action','id','revision')
                schema.obj(c,fields,fields[1:])
                if self.paused or not self.audience_enabled: raise ValueError('Audience requests are off or paused')
                if action == 'request_select': self.requests.select(c['id'],c['revision'],c['intent'])
                elif action == 'request_reject':
                    self.requests.item(c['id'],c['revision']); del self.requests.items[c['id']]
                else:
                    self._require_native()
                    if not self.program_native or self.program['mode']!='live': raise ValueError('Fixed requests require the owned Live program')
                    cue=self.requests.consume(c['id'],c['revision'],c['intent'])
                    result=self._fixed_alert(FIXED[cue])
                    if result['result']!='fixed cue accepted': raise ObsError('Fixed request effect refused; inspect owned graphics before recovery')
        elif action == 'undo_camera_layout':
            schema.obj(c, ('action',))
            self._require_native()
            if not self.program_native or self.program['mode'] != 'live' or self.layout_undo is None:
                raise ValueError('No saved camera layout for the current owned Live program')
            self.on_air_layout = self.native.undo_bound_layout(self.layout_undo)
            self.on_air_layout_name = self.layout_undo['before_name']
            # A new graphic defaults to the recovered known arrangement, never the stale cue.
            self._stage({**self.staged, 'layout': self.on_air_layout_name})
            self.layout_undo = None
            self.previewed = None; self.preview_requested = None; self.preview_target = None
            self.native.prepared = None
        elif action == 'clear':
            schema.obj(c, ('action',))
            if self.program_native: self._require_native()
            # Snapshot observes completed transitions before publishing anything.
            native = self.native.snapshot() if self.native and self.armed else None
            if self.program_native and native['program'] != SCENES[self.program['mode']][0 if self.program_bank == 'A' else 1]:
                raise ObsError('OBS program changed before clear; outcome uncertain')
            self.checkpoint = self._checkpoint(native)
            if self.native and self.armed: self.media_status = self.native.media()
            self.program = schema.segment({**self.program, 'composition': {'elements': []}, 'lower': None, 'timer': None, 'vote': None, 'media': None})
            self.timer_state = None; self.vote_state = None; self.voters = {}; self.alert = None
            self.chat_poll.renew(None,taken=False)
            self.air_id += 1
            self.program_payload = self._payload(self.program, self.air_id, self.clock(), 'program')
            if self.program_native:
                self._require_native()
                self.obs_state['graphics_visibility'] = self.native.set_graphics_visible(native['program'], False, native['program'])
                self._publish_bank(self.program_bank, self.program_payload)
                self.obs_state['readback'] = self.native.wait_transition(invariant_program=native['program'])
                self.native.prepared = None
                self.previewed = None; self.preview_requested = None; self.preview_target = None
        elif action == 'checkpoint':
            schema.obj(c, ('action',))
            self.anchor = self._checkpoint(self.native.snapshot() if self.native and self.armed else None)
        elif action == 'restore':
            self.layout_undo = None; self.on_air_layout = None
            schema.obj(c, ('action',))
            checkpoint = self.anchor or self.checkpoint or self.preview_checkpoint
            if checkpoint is None: raise ValueError('No restore checkpoint')
            if checkpoint.get('program_page'):self.pages.resolve(checkpoint['program_page'])
            if checkpoint.get('native'):
                approved={item['url'] for item in self.pages.entries.values()}|{'about:blank'}
                if any(url not in approved for url in checkpoint['native'].get('page_urls',{}).values()):
                    raise ValueError('Recovery page URL is no longer in the operator-approved catalog')
            if checkpoint['native'] is not None:
                self._require_native()
                # The old bank may still be visible in an in-flight Fade. Do not
                # republish either bank until that transition has completed.
                self.native.wait_transition()
                self.native.page_restore_plan(checkpoint['native'])
                self.media_status = self.native.media()
                bank = checkpoint['native']['program'][-1]
                # Every recovery is a new render, even when four takes have
                # returned to the checkpoint bank. Never resurrect its old ID.
                restore_payload = copy.deepcopy(checkpoint['banks'][bank])
                restore_payload.update(timer=checkpoint['timer'], vote=checkpoint['vote'], alert=checkpoint['alert'])
                self.recovering_bank = bank
                try:
                    restored_item = next(item for item in checkpoint['native']['geometry'][checkpoint['native']['program']] if item['source'] == OVERLAYS[bank])
                    if restored_item['enabled']:
                        self._prepaint_bank(bank, restore_payload, 'Restore')
                        self._require_native()
                        self.obs_state['readback'] = self.native.restore(checkpoint['native'])
                    else:
                        # Confirm hidden native geometry/scene before publishing
                        # invisible data; its texture need not ACK or be erased.
                        self.obs_state['readback'] = self.native.restore(checkpoint['native'])
                        self._publish_bank(bank, restore_payload)
                finally:
                    self.recovering_bank = None
                # Keep the fresh resident identity and the other bank's picture.
                # A hidden checkpoint is content, never a claimed paint receipt.
            self.program_bank = checkpoint['program_bank']; self.program_native = checkpoint['program_native']
            self.program_payload = checkpoint['program_payload']
            self.program_page=copy.deepcopy(checkpoint.get('program_page'))
            self.program = checkpoint['program']; self.timer_state = checkpoint['timer']; self.vote_state = checkpoint['vote']
            self.voters = checkpoint['voters']; self.air_started = checkpoint['air_started']; self.alert = checkpoint['alert']
            self.chat_poll.renew(self.program['vote'],taken=checkpoint.get('poll_taken',False))
            self.air_id += 1
            self.anchor = None; self.checkpoint = None; self.preview_checkpoint = None
            self.previewed = None; self.preview_requested = None; self.preview_target = None
        elif action == 'pause':
            self.requests.clear()
            schema.obj(c, ('action', 'paused'), ('paused',)); paused = schema.boolean(c['paused'])
            if paused != self.paused:
                if paused:
                    self.paused_at = time.time()
                    if self.native and self.armed: self.media_status = self.native.media()
                else:
                    self.paused_total += time.time() - self.paused_at
                    self.paused_at = None
                self.paused = paused
            self.chat_poll.renew(self.program['vote'])
        elif action == 'reduced_motion':
            schema.obj(c, ('action', 'enabled'), ('enabled',)); self.reduced_motion = schema.boolean(c['enabled'])
        elif action == 'timer_control':
            schema.obj(c, ('action', 'operation'), ('operation',))
            operation = schema.choice(c['operation'], ('pause', 'resume', 'reset'))
            if self.timer_state is None: raise ValueError('Take a timer segment first')
            timer = self.timer_state
            if operation == 'pause' and timer['running']:
                timer['offset'] += self.clock()-timer['anchor']; timer['running'] = False
            elif operation == 'resume' and not timer['running']:
                timer['anchor'] = self.clock(); timer['running'] = True
            elif operation == 'reset': timer.update(anchor=self.clock(), offset=0)
        elif action == 'vote_control':
            schema.obj(c, ('action', 'operation'), ('operation',))
            operation = schema.choice(c['operation'], ('open', 'close', 'reset'))
            if self.vote_state is None: raise ValueError('Take a local vote segment first')
            if operation == 'reset':
                self.vote_state['counts'] = [0]*len(self.vote_state['counts']); self.voters = {}
            else: self.vote_state['open'] = operation == 'open'
            self.chat_poll.renew(self.program['vote'])
        elif action == 'audience':
            self.requests.clear()
            schema.obj(c, ('action', 'enabled'), ('enabled',)); self.audience_enabled = schema.boolean(c['enabled'])
            self.chat_poll.renew(self.program['vote'])
        elif action == 'marker':
            schema.obj(c, ('action', 'label'), ('label',))
            label = schema.text(c['label'], 120, False)
            if len(self.markers) >= 500: raise ValueError('Export markers; session limit is 500')
            self.markers.append({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'elapsed': round(self.clock()-self.air_started, 3), 'label': label})
        elif action in ('recipe_save', 'recipe_load', 'recipe_delete'):
            self._recipe(action, c)
        elif action == 'connect':
            self.chat_poll.renew(self.program['vote'],taken=False)
            self.requests.clear()
            self.layout_undo = None; self.on_air_layout = None
            schema.obj(c, ('action', 'password', 'port'), ('password',))
            schema.text(c['password'], 512, False)
            port = c.get('port', 4455)
            if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('Invalid local OBS port')
            if self.native:
                self.page_runtime=(dict(self.native.page_urls),dict(self.native.bank_content))
                self.native.client.close()
            self.armed = False; self.native = None
            self.bank_ready = {'A': None, 'B': None}
            self.obs_state = {'connected': False, 'detail': 'Connecting', 'readback': None}
            client = self.obs_factory(c['password'], port=c.get('port', 4455))
            self.native = OwnedOBS(client, self.port, self.media_dir)
            self.native.bindings = copy.deepcopy(self.bindings)
            if self.page_runtime:self.native.page_urls,self.native.bank_content=copy.deepcopy(self.page_runtime)
            self.native.guard()
            self.obs_state = {'connected': True, 'detail': 'Authenticated, not armed; select inputs and set up owned scenes', 'readback': self.native.req('GetSceneList')}
        elif action == 'disconnect':
            self.chat_poll.renew(self.program['vote'],taken=False)
            self.requests.clear()
            self.layout_undo = None; self.on_air_layout = None
            schema.obj(c, ('action',))
            if self.native:
                self.page_runtime=(dict(self.native.page_urls),dict(self.native.bank_content))
                self.native.client.close()
            self.armed = False; self.native = None
            self.bank_ready = {'A': None, 'B': None}
            self.previewed = None; self.preview_target = None
            self.obs_state.update(connected=False, detail='Disconnected; no automatic retry')
        elif action == 'setup':
            self.chat_poll.renew(self.program['vote'],taken=False)
            self.requests.clear()
            self.layout_undo = None; self.on_air_layout = None
            schema.obj(c, ('action', 'camera', 'content', 'fixtures'))
            fixtures = schema.boolean(c.get('fixtures', False))
            if not self.native: raise ObsError('Connect OBS first')
            self.obs_state['readback'] = self.native.setup(schema.text(c.get('camera', ''), 200), schema.text(c.get('content', ''), 200), fixtures=fixtures)
            self.bindings = copy.deepcopy(self.native.bindings)
            scene = self.obs_state['readback']['program']
            mode = next(mode for mode, scenes in SCENES.items() if scene in scenes)
            self.program = schema.segment({**self.program, 'mode': mode, 'composition': {'elements': []}})
            self.staged_page=None;self.program_page=None
            self.program_bank = scene[-1]; self.program_native = True
            for bank in ('A', 'B'): self._publish_bank(bank, self._payload(self.program, 0, self.clock(), 'program'))
            self.armed = False; self.preview_checkpoint = None; self.checkpoint = None; self.anchor = None
            self.obs_state['detail'] = 'Owned scenes set up; explicitly arm before preview/take'
        elif action == 'arm':
            schema.obj(c, ('action', 'enabled'), ('enabled',))
            enabled = schema.boolean(c['enabled'])
            if enabled:
                if not self.native: raise ObsError('Connect OBS first')
                self._prepare_arm()
            if not enabled: self.requests.clear()
            self.chat_poll.renew(self.program['vote'],taken=False if not enabled else None)
            self.armed = enabled
            self.previewed = None; self.preview_target = None
            self.obs_state['detail'] = 'Owned OBS control armed; bank renderers ready, real frame validation still required' if enabled else 'OBS control disarmed'
        elif action == 'refresh':
            schema.obj(c, ('action',))
            if not self.native: raise ObsError('Connect OBS first')
            self.native.guard()
            self.obs_state['readback'] = self.native.req('GetSceneList')
            self.obs_state['connected'] = self.native.client.connected
        elif action == 'media_play':
            schema.obj(c, ('action', 'name', 'volume'), ('name',))
            path = self.media_path(c['name']); volume = schema.number(c.get('volume', .25), 0, .5)
            self._require_native(); self.media_status = self.native.media(path, volume)
        elif action == 'media_stop':
            schema.obj(c, ('action',))
            self._require_native(); self.media_status = self.native.media()
        else: raise ValueError('Unknown director action')

    def _recipe(self, action, c):
        schema.obj(c, ('action', 'name', 'append', 'index'), ('name',))
        name = schema.text(c['name'], 60, False)
        if action == 'recipe_save':
            append = schema.boolean(c.get('append', False))
            if name not in self.recipes and len(self.recipes) >= 40: raise ValueError('Recipe limit is 40')
            steps = copy.deepcopy(self.recipes[name]['steps']) if append and name in self.recipes else []
            value = schema.recipe({'name': name, 'steps': steps+[self.staged]})
            previous = copy.deepcopy(self.recipes)
            self.recipes[name] = value
            try: self._save_recipes()
            except OSError:
                self.recipes = previous; raise ValueError('Recipe save failed; disk state was not confirmed') from None
        elif action == 'recipe_delete':
            previous = copy.deepcopy(self.recipes)
            self.recipes.pop(name, None)
            try: self._save_recipes()
            except OSError:
                self.recipes = previous; raise ValueError('Recipe delete failed') from None
        else:
            if name not in self.recipes: raise ValueError('Recipe not found')
            value = schema.recipe(self.recipes[name])
            index = c.get('index', 0)
            if type(index) is not int or not 0 <= index < len(value['steps']): raise ValueError('Choose a recipe step')
            self._stage(value['steps'][index]); self.recipe_name = name; self.recipe_index = index

    def preview_ack(self, stage_id):
        with self.lock:
            if type(stage_id) is not int or stage_id != self.stage_id or self.preview_requested != stage_id:
                raise Conflict('Preview revision is stale or was not requested')
            self.previewed = stage_id
            return {'previewed': stage_id}

    def _fixed_alert(self, title):
        if self.program_native:
            if not self.native or not self.armed or not self.obs_state['connected']: return {'result': 'input off'}
            scene = SCENES[self.program['mode']][0 if self.program_bank == 'A' else 1]
            self.native.wait_transition(invariant_program=scene)
            self.native.verify()
            hidden = not self.native.graphics_item(scene)['sceneItemEnabled']
        else: hidden = False
        self.alert = {'title': title, 'start': self.clock(), 'until': self.clock()+5} if title else None
        if hidden and title:
            # Reveal only a cleared Live payload plus this fixed allowlisted cue,
            # never a staged draft or an operator-hidden authored composition.
            if self.program['mode'] != 'live' or self.program['composition']['elements'] or any(self.program[k] for k in ('lower','timer','vote','media')):
                self.alert = None
                return {'result': 'input off'}
            self.operator_approval = None
            bank = self.program_bank
            payload = copy.deepcopy(self.banks[bank])
            payload.update(alert=self.alert, phase='prepared')
            self._prepaint_bank(bank, payload, 'Fixed alert')
            self._require_native()
            self.alert.update(start=self.clock(), until=self.clock()+5)
            self.banks[bank]['phase'] = 'program'
            self.obs_state['graphics_visibility'] = self.native.set_graphics_visible(scene, True, scene)
            self.version += 1; self.record('fixed_alert_visibility')
        return {'result': 'fixed cue accepted'}

    def poll_context(self):
        with self.lock:
            permitted=bool(self.audience_enabled and self.armed and self.obs_state['connected'] and self.native
                and self.native.client.connected and self.program_native and not self.paused and not self.in_flight)
            return self.chat_poll.context(self.program['vote'],self.vote_state,permitted)

    def ingest_vote(self,data):
        with self.lock:
            def check_native():
                self._require_native()
                expected=SCENES[self.program['mode']][0 if self.program_bank=='A' else 1]
                self.native.wait_transition(invariant_program=expected)
                if self.native.verify()['currentProgramSceneName']!=expected:
                    raise ObsError('Program changed during numeric poll input; disarmed')
            try:return self.chat_poll.cast(data,self.poll_context(),self.vote_state,self.voters,check_native)
            except ObsError:
                self._obs_failed();self.version+=1;self.record('numeric_poll','not confirmed')
                raise

    def enqueue_request(self, data):
        """Local validated-transport ingress, never an effect or agent authoring path."""
        with self.lock:
            if not isinstance(data,dict) or set(data)!={'session','event_id','viewer_id','text','suggested'}:
                raise ValueError('Validated request contract required')
            if not self.audience_enabled or self.paused or self.in_flight: return {'result':'input off'}
            admitted=self.requests.admit(**data)
            # Waiting input is operator-only inbox state, not a creative/show mutation.
            # Request IDs/revisions/TTL remain authoritative; native review stays exact.
            return {'result':'queued' if admitted else 'queue refused'}

    def audience(self, voter, message=None, cue=None):
        with self.lock:
            if not self.audience_enabled or self.paused or self.in_flight: return {'result': 'input off'}
            if cue is not None:
                if not isinstance(cue, str) or cue not in FIXED: return {'result': 'rejected'}
                title = FIXED[cue]
                try: return self._fixed_alert(title)
                except ObsError as exc:
                    self._obs_failed(); self.error = str(exc)
                    self.version += 1; self.record('fixed_alert_visibility', 'not confirmed')
                    raise
            if not isinstance(message, str) or not re.fullmatch(r'!vote [1-6]', message): return {'result': 'ignored'}
            schema.text(voter, 120, False)
            if self.vote_state is None or not self.vote_state['open']: return {'result': 'vote closed'}
            index = int(message[-1])-1
            if index >= len(self.vote_state['counts']): return {'result': 'rejected'}
            ident = hashlib.sha256(voter.encode()).hexdigest()
            if ident in self.voters: return {'result': 'duplicate'}
            if len(self.voters) >= 10000: return {'result': 'capacity reached'}
            self.voters[ident] = index
            self.vote_state['counts'][index] += 1
            return {'result': 'vote accepted'}

    def transcript(self, value, event_id, final):
        with self.lock:
            schema.text(value, 800); schema.text(event_id, 100, False); schema.boolean(final)
            if not final: return {'result': 'interim ignored'}
            if event_id in self.seen_voice: return {'result': 'duplicate'}
            self.seen_voice[event_id] = True
            while len(self.seen_voice) > 1000: self.seen_voice.pop(next(iter(self.seen_voice)))
            match = re.fullmatch(r'\s*director[, :]+(.+)', value, re.I)
            if not match: return {'result': 'no director cue'}
            command = schema.parse_operator(match[1])
            # Voice cannot take a different target or bypass the same preview gate.
            result = self.execute(command, self.version)
            return {'result': 'applied', 'state': result}

    def read_selected_material(self, id, revision):
        with self.lock:
            return {'build':'expanded-director-1',**self.materials.read_selected(id,revision)}

    def operator_setup_state(self):
        """Separate human setup projection: never credentials, request text or material content."""
        with self.lock:
            inputs=[];inputs_ready=False
            if self.native and self.obs_state['connected']:
                try: inputs=self.native.inputs();inputs_ready=True
                except ObsError:
                    if self.error!='Operator connection readback not confirmed':
                        self._obs_failed();self.error='Operator connection readback not confirmed'
                        self.version+=1
            return copy.deepcopy({'build':'expanded-director-1','version':self.version,
                'obs_connected':self.obs_state['connected'],'armed':self.armed,
                'preparing':self._arm_token is not None,'paused':self.paused,
                'inputs':inputs,'inputs_ready':inputs_ready,'bindings':self.bindings,
                'material_catalog':self.materials.catalog(),'selected_material':self.materials.selected,
                'page_catalog':self.pages.catalog(urls=True),'selected_page':self.pages.selected})

    def operator_setup_action(self, command, expected):
        """Human-only fixed setup actions delegated to the existing validated engine."""
        with self.lock:
            allowed=('connect','disconnect','setup','arm','material_register','material_select',
                     'page_register','page_select','page_remove')
            if not isinstance(command,dict) or command.get('action') not in allowed:
                raise ValueError('Outside operator setup controls')
            try:self.execute(command,expected)
            except (ValueError,ObsError):
                if command['action']=='connect':self.error='Operator connection not confirmed'
                raise
            return self.operator_setup_state()

    def participation_state(self):
        """Operator-only ephemeral inbox projection. Never used by bounded model API."""
        with self.lock:
            return copy.deepcopy({'build':'expanded-director-1','version':self.version,
                'requests':self.requests.view(),'request_intents':list(INTENTS),
                'audience_enabled':self.audience_enabled,'armed':self.armed,
                'obs_connected':self.obs_state['connected'],'paused':self.paused,
                'program_native':self.program_native,'mode':self.program['mode'],
                'program_vote':self.program['vote'],'poll_tally':self.vote_state,
                'local_director_poll':self.poll_context()})

    def participation_action(self, command, expected):
        with self.lock:
            if type(expected) is not int or expected != self.version:
                raise Conflict('Participation state changed; refresh before acting')
            allowed=('request_select','request_accept','request_reject','requests_clear',
                     'audience','local_director_polls','poll_control')
            if not isinstance(command,dict) or command.get('action') not in allowed:
                raise ValueError('Outside operator participation controls')
            command=copy.deepcopy(command)
            if command['action']=='poll_control':
                if command.pop('revision',None)!=self.poll_context()['revision']:
                    raise ValueError('Exact current poll revision required')
            self.execute(command,expected)  # Existing validation, consume-once and native guards.
            return self.participation_state()

    def operator_review(self, review, expected, operation):
        """Native human controls only; bind the inspected frame before any approval/take."""
        with self.lock:
            if type(expected) is not int or expected != self.version:
                raise Conflict('Controller changed; inspect the refreshed preview')
            if operation not in ('approve', 'take'):
                raise ValueError('Native review permits only approve or take')
            current = self._approval_context()
            if (not isinstance(review, dict) or current is None or review != current
                    or self.destination != 'obs' or not self.armed or not self.obs_state['connected']):
                raise Conflict('Exact native preview review expired or changed')
            # This trusted operator endpoint is deliberately absent from MCP.
            # Manual Take remains one deliberate action, no prior approval needed.
            self.execute({'action':'approve_agent_take' if operation == 'approve' else 'take'}, expected)
            return self.agent_state()

    def agent_state(self):
        """No credentials, arbitrary paths, marker history or raw OBS RPC data."""
        with self.lock:
            return copy.deepcopy({'build': 'expanded-director-1', 'version': self.version,
                'external_page_load_verified':False if (self.staged_page or self.program_page) else None, 'page_catalog':self.pages.catalog(), 'selected_page':self.pages.selected, 'staged_page':self.staged_page, 'program_page':self.program_page,
                'poll_tally':self.vote_state, 'local_director_poll':self.poll_context(), 'material_catalog': self.materials.catalog(), 'selected_material': self.materials.selected,
                'native_review': self._approval_context() if self.destination == 'obs' and self.armed and self.obs_state['connected'] else None,
                'stage_id': self.stage_id, 'staged': self.staged, 'program': self.program,
                'destination': self.destination, 'previewed': self._review_ready(),
                'rendered_ready': self._review_ready(), 'preview_refresh_required': self._preview_refresh_required(), 'agent_take_approved': self._agent_approved(),
                'operator_approval': self.operator_approval,
                'prepared_bank': self.native.prepared['bank'] if self.native and self.native.prepared else None,
                'bank_readiness': {bank: self._bank_is_ready(bank) for bank in ('A','B')},
                'arm_preparing': self._arm_token is not None, 'warm_recovery_pending': self.warm_recovery is not None, 'payload_recovery_pending': self.payload_recovery is not None,
                'can_undo_camera_layout': bool(self.layout_undo and self.armed and self.program_native and self.program['mode'] == 'live'),
                'armed': self.armed, 'paused': self.paused, 'can_restore': bool(self.anchor or self.checkpoint or self.preview_checkpoint),
                'obs': {'connected': self.obs_state['connected'], 'detail': self.obs_state['detail']},
                'current_native_layout': self.on_air_layout_name if self.on_air_layout else None, 'program_native': self.program_native,
                'program_bank': self.program_bank, 'error': self.error,
                'schema': {'canvas': [1920, 1080], 'max_elements': 32, 'kinds': ['text','rect','circle'],
                    'motions': list(schema.MOTIONS), 'duration_seconds': [.3,120], 'repeat': [1,20],
                    'element_fields': ['id','kind','text','x','y','w','h','color','size','opacity','motion','start','end','radius']},
                'privilege_boundary': 'Bounded server only; trusted external client retains its own tools. No automatic model execution.'})

    def execute_agent(self, command, expected):
        if not isinstance(command, dict) or command.get('action') not in ('stage_patch','stage_visual_poll','poll_control','stage_selected_page','stage_bound_content','preview','take','restore','undo_camera_layout','scene','clear','checkpoint','pause','reduced_motion'):
            raise ValueError('Outside bounded authoring capability; human connection/setup/arm required')
        if command['action'] == 'stage_patch' and (not isinstance(command.get('fields'), dict) or set(command['fields']) - {'composition','mode','layout'}):
            raise ValueError('Agent drafts accept only composition, mode and layout')
        with self.lock:
            if type(expected) is not int or expected != self.version:
                raise Conflict('Controller state changed; refreshed state is required before retrying')
            if command['action'] == 'take' and not self._agent_approved():
                raise ValueError('Explicit operator approval required for agent take of this exact preview')
            self.execute(command, expected)
            return self.agent_state()

    def probe(self):
        """Read an already authenticated connection; never reconnect or replay."""
        with self.lock:
            if self.native is None or not self.obs_state['connected']:
                return self.state()
            try:
                self.native.guard()
                actual = self.native.verify() if self.armed else self.native.req('GetSceneList')
                prepared = self.native.prepared
                if self.armed and prepared and not self.in_flight and (actual['currentProgramSceneName'] != prepared['program'] or actual['currentPreviewSceneName'] != prepared['target']):
                    raise ObsError('OBS scene changed since preview; review and re-arm')
                if self.on_air_layout and not self.in_flight:
                    if actual['currentProgramSceneName'] != self.on_air_layout['scene'] or self.native.bound_layout() != self.on_air_layout:
                        self.on_air_layout = None; self.on_air_layout_name = None
                self.obs_state['readback'] = actual
            except ObsError as exc:
                self._obs_failed(); self.error = str(exc)
                self.version += 1; self.record('obs_probe', 'not confirmed')
            return self.state()

    def markers_csv(self):
        with self.lock:
            out = io.StringIO(); writer = csv.writer(out); writer.writerow(('utc', 'segment_elapsed_seconds', 'label'))
            for marker in self.markers:
                label = marker['label']
                if label.startswith(('=', '+', '-', '@', '\t')): label = "'"+label
                writer.writerow((marker['utc'], marker['elapsed'], label))
            return out.getvalue()

    def close(self):
        with self.lock:
            self.requests.clear()
            if self.native: self.native.client.close()
            self.armed = False
            self.operator_approval = None
            self._arm_token = None; self.warming = None
            self.bank_condition.notify_all()
