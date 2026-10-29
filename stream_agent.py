"""Stream agent: voice, chat, random or typed cues become bounded on-screen actions for viewers.

One local service on 127.0.0.1:8879. The overlay page is an OBS Browser Source; the controller is
the operator's page. A planner turns an input into one action from a fixed preset list; the server
validates every action the same way whatever produced it (rules, a model, chat). Nothing reaches the
overlay except validated text in known slots. No code, URLs or OBS calls come from any input.

Every input starts off. Nothing fires until the operator turns an input on in the controller.
"""
import json
import os
import queue
import random
import re
import threading
import time
import unicodedata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import stream_models
import stream_voice

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'stream_web'
BUILD_TAG = 'stream-agent-27oct'
PORT = 8879

KINDS = {
    'popup': 'Big text in the middle of the screen',
    'lower_third': 'Name or caption bar along the bottom',
    'emoji_burst': 'A burst of one emoji',
    'countdown': 'A short countdown with a label',
    'clear': 'Remove whatever is showing',
}
EMOJI = ['🔥', '🎉', '👏', '😂', '🚀', '💡', '❤️', '👀']
MAX_TEXT = 80
DURATION = (1500, 10000)
COUNTDOWN = (3, 30)
SOURCES = ('voice', 'chat', 'random', 'typed')
# Events per source per minute. Chat and random sit lower than the streamer's own voice.
RATE = {'voice': 30, 'typed': 60, 'chat': 6, 'random': 4}
# Anything domain-shaped is refused, whatever the ending: word.word where the last part has 2+ letters
# (or is an internationalised xn-- label). Decimals like 3.5 and abbreviations like e.g. still pass.
URLISH = re.compile(r'(https?://|www\.|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:[a-z]{2,}|xn--[a-z0-9-]+)\b)', re.I)
MAX_SUBSCRIBERS = 8      # overlay and controller pages open at once
MAX_CONNECTIONS = 16     # HTTP connections handled at once; more get 503 straight away


class Rejected(ValueError):
    pass


class Overloaded(RuntimeError):
    pass


def clean_text(value):
    """Plain visible text only: no control or format characters, no links, at most MAX_TEXT characters."""
    if not isinstance(value, str):
        raise Rejected('text must be a string')
    text = ''.join(ch for ch in unicodedata.normalize('NFC', value) if unicodedata.category(ch)[0] != 'C')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        raise Rejected('text is empty')
    if len(text) > MAX_TEXT:
        raise Rejected(f'text is longer than {MAX_TEXT} characters')
    if URLISH.search(text):
        raise Rejected('links are not shown on stream')
    return text


def validate(action):
    """The only gate to the overlay. Returns a new dict with known keys and clamped values."""
    if not isinstance(action, dict):
        raise Rejected('action must be an object')
    kind = action.get('kind')
    if kind not in KINDS:
        raise Rejected('unknown action kind')
    allowed = {'kind', 'text', 'emoji', 'seconds', 'duration_ms'}
    extra = set(action) - allowed
    if extra:
        raise Rejected('unexpected fields: ' + ', '.join(sorted(map(str, extra))))
    for key, value in action.items():
        if isinstance(value, (dict, list)):
            raise Rejected(f'{key} must not be nested')
    out = {'kind': kind}
    if kind in ('popup', 'lower_third', 'countdown'):
        out['text'] = clean_text(action.get('text', ''))
    if kind == 'emoji_burst':
        emoji = action.get('emoji')
        if emoji not in EMOJI:
            raise Rejected('emoji must be one of the preset set')
        out['emoji'] = emoji
    if kind == 'countdown':
        try:
            seconds = int(action.get('seconds', 5))
        except (TypeError, ValueError):
            raise Rejected('seconds must be a whole number') from None
        out['seconds'] = max(COUNTDOWN[0], min(COUNTDOWN[1], seconds))
    if kind != 'clear':
        try:
            ms = int(action.get('duration_ms', 4000))
        except (TypeError, ValueError):
            raise Rejected('duration_ms must be a whole number') from None
        out['duration_ms'] = max(DURATION[0], min(DURATION[1], ms))
    return out


# ---------- rule planner: the offline default ----------
# Whisper often writes the pause after the wake word as a full stop: 'Director. Pop up ...'
WAKE = re.compile(r'^\s*(hey[,\s]+)?(director|stream|agent)[,.:;!?\s]+', re.I)


def rule_plan(text, source):
    """Recognise a few spoken or typed forms. Voice and chat need the wake word; typed does not."""
    raw = str(text or '').strip()
    body = WAKE.sub('', raw, count=1)
    if source in ('voice', 'chat') and body == raw:
        return None  # no wake word: ordinary speech or chat stays off screen
    low = body.lower().strip(' .!?')
    if low in ('clear', 'clear screen', 'clear the screen', 'hide', 'stop'):
        return {'kind': 'clear'}
    m = re.match(r'(?:countdown|count down)(?: from)? (\d{1,2})(?: (?:seconds?|secs?))?[,:]?\s*(.*)$', body.strip(' .!?'), re.I)
    if m:
        return {'kind': 'countdown', 'seconds': int(m.group(1)), 'text': m.group(2).strip(' .') or 'Starting'}
    m = re.match(r'(?:lower third|caption|name)[,:\s]+(.+)$', body, re.I)
    if m:
        return {'kind': 'lower_third', 'text': m.group(1).strip(' .')}
    for word, emoji in (('fire', '🔥'), ('party', '🎉'), ('clap', '👏'), ('applause', '👏'), ('laugh', '😂'),
                        ('rocket', '🚀'), ('idea', '💡'), ('love', '❤️'), ('eyes', '👀')):
        if re.search(rf'\b{word}\b', low) and ('emoji' in low or 'burst' in low or low == word):
            return {'kind': 'emoji_burst', 'emoji': emoji}
    m = re.match(r'(?:popup|pop up|show|say|put up)[,:\s]+(.+)$', body, re.I)
    if m:
        return {'kind': 'popup', 'text': m.group(1).strip(' .')}
    return None


RANDOM_TEXTS = ['Hydrate!', 'Hello chat', 'Still building', 'Big moment coming', 'Thanks for watching']


def random_action(rng):
    kind = rng.choice(['popup', 'emoji_burst', 'lower_third'])
    if kind == 'emoji_burst':
        return {'kind': kind, 'emoji': rng.choice(EMOJI)}
    return {'kind': kind, 'text': rng.choice(RANDOM_TEXTS)}


# ---------- state, rate limits and delivery ----------
class Agent:
    def __init__(self, seed=None):
        self.lock = threading.RLock()
        self.inputs = {s: False for s in SOURCES}
        # Bumped whenever an input changes. A cue planned under an older epoch is dropped, so turning an
        # input off also stops anything from it that is still being transcribed or planned.
        self.epoch = {s: 0 for s in SOURCES}
        self.planner = 'rules'
        self.recent = {s: [] for s in SOURCES}
        self.counters = {'accepted': 0, 'rejected': 0, 'ignored': 0, 'rate_limited': 0, 'cancelled': 0, 'planner_busy': 0,
                         'dropped_subscriber': 0, 'subscribers_refused': 0, 'connections_refused': 0}
        # One model call at a time. A second cue while one is planning is refused and counted, not queued.
        self.plan_gate = threading.BoundedSemaphore(1)
        self.log = []
        self.subscribers = []
        self.rng = random.Random(seed)
        self.random_interval = 20.0
        self.planners = {'rules': rule_plan, 'codex': stream_models.CodexPlanner(), 'openai': stream_models.OpenAIPlanner()}
        self.voice = None  # stream_voice.VoiceWorker, started on the first chunk

    def status(self):
        with self.lock:
            return {'connector_port': PORT, 'build_tag': BUILD_TAG, 'inputs': dict(self.inputs), 'planner': self.planner,
                    'planners': sorted(self.planners), 'counters': dict(self.counters), 'kinds': KINDS, 'emoji': EMOJI,
                    'rate_per_minute': RATE, 'chat': 'SIMULATOR: no streaming platform is connected', 'log': self.log[-20:],
                    'voice': {**stream_voice.readiness(), 'stats': dict(self.voice.stats) if self.voice else None},
                    'models': self._models(), 'random_interval_s': self.random_interval,
                    'twitch': {'connected': False, 'state': 'not connected: needs the operator to authorise a Twitch account (OAuth); chat here is a simulator'}}

    def _models(self):
        c, o = self.planners.get('codex'), self.planners.get('openai')
        out = {}
        if c is not None and hasattr(c, 'calls'):
            out['codex'] = {'available': c.available(), 'enabled': c.enabled, 'model': c.model or 'codex default (unverified)', 'calls': c.calls,
                            'cap': c.max_calls, 'recent': c.log[-5:], 'billing': "Oscar's Codex CLI subscription"}
        if o is not None and hasattr(o, 'available'):
            out['openai'] = {'available': False, 'model': o.model, 'state': 'disabled: needs API key, root budget and a verified request shape'}
        return out

    def set_input(self, source, on):
        if source not in SOURCES:
            raise Rejected('unknown input')
        if not isinstance(on, bool):  # "false" is a string, not off; only JSON true or false is accepted
            raise Rejected('on must be true or false')
        with self.lock:
            if self.inputs[source] != on:
                self.epoch[source] += 1
            self.inputs[source] = on
            voice = self.voice
        if source == 'voice' and not on and voice is not None:
            voice.cancel()

    def set_planner(self, name, model=None):
        if name not in self.planners:
            raise Rejected('unknown planner')
        if model is not None and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{0,64}', model)):
            raise Rejected('model id must be letters, digits, dot, dash, colon or underscore')
        with self.lock:
            self.planner = name
            if model is not None and hasattr(self.planners[name], 'model'):
                self.planners[name].model = model or None

    def _rate_ok(self, source, now):
        window = [t for t in self.recent[source] if now - t < 60]
        self.recent[source] = window
        if len(window) >= RATE[source]:
            return False
        window.append(now)
        return True

    def _note(self, entry):
        self.log.append(entry)
        del self.log[:-200]

    def submit(self, source, text=None, action=None, received_at=None, extra_timing=None, epoch=None):
        """Route one input. Returns the delivered event, or a dict saying why nothing was shown."""
        t0 = received_at or time.time()
        if source not in SOURCES:
            raise Rejected('unknown input')
        with self.lock:
            if not self.inputs[source]:
                self.counters['ignored'] += 1
                return {'shown': False, 'reason': f'{source} input is off'}
            if not self._rate_ok(source, t0):
                self.counters['rate_limited'] += 1
                self._note({'source': source, 'result': 'rate limited', 'at': t0})
                return {'shown': False, 'reason': f'{source} rate limit'}
            planner, planner_name = self.planners[self.planner], self.planner
            if epoch is not None and epoch != self.epoch[source]:
                self.counters['cancelled'] += 1
                return {'shown': False, 'reason': f'{source} input changed since this cue arrived'}
            epoch = self.epoch[source]
        planned_by = 'direct' if action is not None else self.planner
        if action is None:
            gated = planner_name != 'rules'  # rules are a pure function; only model planners hold the gate
            if gated and not self.plan_gate.acquire(blocking=False):
                with self.lock:
                    self.counters['planner_busy'] += 1
                return {'shown': False, 'reason': 'planner busy with another cue'}
            try:
                action = planner(text, source)
            except Exception as e:  # noqa: BLE001 - a broken planner falls back, never crashes the service
                action, planned_by = rule_plan(text, source), f'rules (fallback: {type(e).__name__})'
            finally:
                if gated:
                    self.plan_gate.release()
            if action is None and self.planner != 'rules':
                action, planned_by = rule_plan(text, source), 'rules (fallback: no action from model)'
        t1 = time.time()
        if action is None:
            with self.lock:
                self.counters['ignored'] += 1
                self._note({'source': source, 'result': 'no action', 'at': t0})
            return {'shown': False, 'reason': 'no matching action'}
        try:
            clean = validate(action)
        except Rejected as e:
            with self.lock:
                self.counters['rejected'] += 1
                self._note({'source': source, 'result': 'rejected', 'why': str(e), 'at': t0})
            return {'shown': False, 'reason': 'rejected: ' + str(e)}
        with self.lock:
            # Checked and published under one lock: an input turned off mid-plan never reaches the screen.
            if not self.inputs[source] or self.epoch[source] != epoch:
                self.counters['cancelled'] += 1
                self._note({'source': source, 'result': 'cancelled: input turned off while planning', 'at': t0})
                return {'shown': False, 'reason': f'{source} input turned off while planning'}
            event = {'id': f'{int(t0 * 1000)}-{self.rng.randrange(1 << 30):x}', 'source': source, 'planned_by': planned_by,
                     'action': clean, 'timing': {'received': t0, 'planned': t1, **(extra_timing or {}), 'published': time.time()}}
            self.publish(event)
            self.counters['accepted'] += 1
            self._note({'source': source, 'result': 'shown', 'kind': clean['kind'], 'planned_by': planned_by, 'at': t0})
        return {'shown': True, 'event': event}

    def subscribe(self):
        q = queue.Queue(maxsize=50)
        with self.lock:
            if len(self.subscribers) >= MAX_SUBSCRIBERS:
                self.counters['subscribers_refused'] += 1
                raise Overloaded('too many open pages')
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self, event):
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:  # a stalled page loses old events, counted, never blocks the stream
                with self.lock:
                    self.counters['dropped_subscriber'] += 1

    def random_tick(self):
        if self.inputs['random']:
            return self.submit('random', action=random_action(self.rng))
        return None

    def set_random_interval(self, seconds):
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            raise Rejected('seconds must be a number') from None
        with self.lock:
            self.random_interval = max(5.0, min(300.0, seconds))

    def random_loop(self, stop):
        while not stop.wait(self.random_interval):
            self.random_tick()


AGENT = Agent()


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer with a hard cap on connections handled at once; extra ones get 503 at once."""
    daemon_threads = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            agent = getattr(self.RequestHandlerClass, 'agent', None)
            if agent is not None:
                with agent.lock:
                    agent.counters['connections_refused'] += 1
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(SimpleHTTPRequestHandler):
    agent = AGENT
    timeout = 10  # a client that never finishes sending its request is dropped after 10 s

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, *a):
        pass

    def _port(self):
        return self.server.server_address[1]

    def local(self):
        port = self._port()
        hosts = [f'127.0.0.1:{port}', f'localhost:{port}']
        origins = [None, f'http://127.0.0.1:{port}', f'http://localhost:{port}']
        return self.headers.get('Host') in hosts and self.headers.get('Origin') in origins

    def reply(self, value, code=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Pages may load only their own scripts and styles; no inline script, no third party.
        if not self.path.startswith('/events'):
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
            self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def do_GET(self):
        if not self.local():
            return self.reply({'error': 'local only'}, 403)
        path = self.path.split('?', 1)[0]
        if path == '/status':
            return self.reply(self.agent.status())
        if path == '/events':
            return self.events()
        if path in ('/', '/control'):
            self.path = '/control.html'
        return super().do_GET()

    def events(self):
        try:
            q = self.agent.subscribe()
        except Overloaded:
            return self.reply({'error': 'too many open pages'}, 503)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        try:
            self.wfile.write(b': connected\n\n'); self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    self.wfile.write(b'data: ' + json.dumps(event, ensure_ascii=False).encode() + b'\n\n')
                except queue.Empty:
                    self.wfile.write(b': keepalive\n\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.agent.unsubscribe(q)

    def do_POST(self):
        port = self._port()
        if not self.local() or self.headers.get('Origin') not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            return self.reply({'error': 'local controller only'}, 403)
        if self.path.split('?', 1)[0] == '/voice-chunk':
            return self.voice_chunk()
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n > 20_000:
                return self.reply({'error': 'too large'}, 413)
            req = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(req, dict):
                raise ValueError
        except ValueError:
            return self.reply({'error': 'bad json'}, 400)
        path = self.path.split('?', 1)[0]
        try:
            if path == '/input':
                self.agent.set_input(req.get('source'), req.get('on'))
                return self.reply(self.agent.status())
            if path == '/random':
                self.agent.set_random_interval(req.get('seconds'))
                return self.reply(self.agent.status())
            if path == '/planner':
                self.agent.set_planner(req.get('planner'), req.get('model'))
                return self.reply(self.agent.status())
            if path == '/cue':
                text = req.get('text')
                if not isinstance(text, str) or len(text) > 500:
                    return self.reply({'error': 'text must be a string up to 500 characters'}, 400)
                return self.reply(self.agent.submit(req.get('source', 'typed'), text=text))
            if path == '/chat-sim':
                text = req.get('text')
                if not isinstance(text, str) or len(text) > 500:
                    return self.reply({'error': 'text must be a string up to 500 characters'}, 400)
                return self.reply(self.agent.submit('chat', text=text))
        except Rejected as e:
            return self.reply({'error': str(e)}, 400)
        return self.reply({'error': 'not found'}, 404)


def _voice_chunk(self):
    # Audio is read only while the operator has voice on; otherwise it is refused unread.
    if not self.agent.inputs.get('voice'):
        return self.reply({'error': 'voice input is off'}, 409)
    if self.headers.get('Content-Type', '').split(';')[0] != 'audio/wav':
        return self.reply({'error': 'send audio/wav'}, 415)
    n = int(self.headers.get('Content-Length') or 0)
    if n > stream_voice.MAX_BYTES:
        return self.reply({'error': 'audio chunk is too large'}, 413)
    data = self.rfile.read(n)
    with self.agent.lock:
        if self.agent.voice is None:
            self.agent.voice = stream_voice.VoiceWorker(self.agent)
    try:
        return self.reply(self.agent.voice.offer(data))
    except stream_voice.VoiceRejected as e:
        return self.reply({'error': str(e)}, 400)


Handler.voice_chunk = _voice_chunk


def main():
    if os.environ.get('AGENTIC_OBS_PORT') != str(PORT):
        raise SystemExit(f'Set AGENTIC_OBS_PORT={PORT} explicitly; this service never takes another port')
    stop = threading.Event()
    threading.Thread(target=AGENT.random_loop, args=(stop,), daemon=True).start()
    print(f'Stream agent http://127.0.0.1:{PORT}/  overlay http://127.0.0.1:{PORT}/overlay.html', flush=True)
    Server(('127.0.0.1', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
