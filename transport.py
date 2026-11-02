"""Bounded director and local audio transports; no model receives OBS tools."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
from streamer import Refused

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'

def scratch():
    RUNTIME.mkdir(exist_ok=True, mode=0o700)
    return tempfile.TemporaryDirectory(dir=RUNTIME)

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['answer', 'proposal'], 'properties': {
              'answer': {'type': 'string'}, 'proposal': {
                  'type': 'object', 'additionalProperties': False,
                  'required': ['title'], 'properties': {'title': {'type': 'string'}}}}}

SCHEMA['properties']['proposal']={'anyOf':[SCHEMA['properties']['proposal'],{
 'type':'object','additionalProperties':False,
 'required':['title','action','asset_id','x','y','width','height'],
 'properties':{'title':{'type':'string'},'action':{'type':'string','enum':['title','show','slideshow','next','previous','move','clear','restore','none','live_zoom','live_wide','live_slides_left','live_pip','live_border','live_no_border','live_pan_left','live_pan_right']},
 'asset_id':{'type':'string'},**{key:{'type':['number','null']} for key in ('x','y','width','height')}}}]}

class CodexDirector:
    name = 'Codex CLI structured director'
    def __init__(self, executable='codex', timeout=45):
        self.executable, self.timeout = executable, timeout
    def ask(self, text, context):
        # Separate scratch working directory, no inherited plugin/tool configuration.
        with scratch() as folder:
            schema, output = Path(folder)/'schema.json', Path(folder)/'answer.json'
            schema.write_text(json.dumps(SCHEMA))
            command = [self.executable, 'exec', '--ignore-user-config', '--ephemeral',
                       '--skip-git-repo-check', '--sandbox', 'read-only',
                       '--disable', 'shell_tool', '--color', 'never',
                       '--output-schema', str(schema), '--output-last-message', str(output), '-']
            prompt = ('You are the operator\'s streaming director. Give a short spoken answer and a title proposal. '
                      'For demo-the-demo requests use title Demo the demo. You can propose title, slideshow, next, previous, show, move, clear, restore, or none. '
                      'For show use only a selected_assets id; never invent an asset or URL. Layout x/y/width/height are fractions inside 0..1, each visual must fit the canvas. '
                      'Use conversation and current visual to fix the last direction. Null layout fields mean unchanged. Preview only; never take or broadcast. '
                      'If live_composition is present, use live_zoom/live_wide/live_slides_left/live_pip/live_border/live_no_border/live_pan_left/live_pan_right for camera and layout requests. These change preview only. You have no Take action. '
                      'Do not use tools or inspect files. Reply only with the requested JSON.\n' +
                      json.dumps({'operator': text, 'show': context}))
            env = {k:v for k,v in os.environ.items() if k in ('PATH','HOME','CODEX_HOME','TMPDIR','SYSTEMROOT')}
            try:
                result = subprocess.run(command, input=prompt, text=True, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, cwd=folder, env=env, timeout=self.timeout)
                if result.returncode != 0 or not output.exists() or output.stat().st_size > 10000:
                    raise Refused('Director failed; no action was staged')
                return json.loads(output.read_text())
            except (OSError, TimeoutError, subprocess.TimeoutExpired, ValueError) as exc:
                raise Refused('Director unavailable; no action was staged') from exc

def voiced_pcm(data):
    import io,wave,array,math
    with wave.open(io.BytesIO(data),'rb') as w:
        if w.getsampwidth()!=2 or w.getnchannels()!=1:raise Refused('Expected decoded mono PCM')
        samples=array.array('h',w.readframes(w.getnframes()))
    return bool(samples) and math.sqrt(sum(x*x for x in samples)/len(samples))/32768>.003

def infer_wav(data,port):
    import urllib.request
    boundary='streamer-'+secrets.token_hex(12)
    fields=[('response_format','json'),('language','en'),('temperature','0')]
    body=b''
    for name,value in fields:
        body+=f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body+=f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode()
    request=urllib.request.Request(f'http://127.0.0.1:{int(port)}/inference',body,{'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
    text=result.get('text','').strip()
    if not text or len(text)>2000:raise Refused('No bounded speech recognized')
    return text

class Whisper:
    def __init__(self, model, executable='whisper-cli', ffmpeg='ffmpeg', port=None):
        self.model, self.executable, self.ffmpeg = Path(model), executable, ffmpeg
        self.port=port
    def __call__(self, audio):
        if not self.model.is_file(): raise Refused('Configure an installed local Whisper model')
        if not 1 <= len(audio) <= 2_000_000: raise Refused('Audio must be at most 2 MB')
        with scratch() as folder:
            source, wav, result = Path(folder)/'clip', Path(folder)/'clip.wav', Path(folder)/'words'
            source.write_bytes(audio)
            try:
                subprocess.run([self.ffmpeg, '-nostdin', '-v', 'error', '-threads', '1',
                                '-protocol_whitelist', 'file,pipe', '-i', str(source), '-t', '15',
                                '-ar', '16000', '-ac', '1', str(wav)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                decoded=wav.read_bytes()
                if not voiced_pcm(decoded):raise Refused('No speech detected')
                if self.port:return infer_wav(decoded,self.port)
                subprocess.run([self.executable, '-m', str(self.model), '-f', str(wav),
                                '-otxt', '-of', str(result), '-nt', '-t', '2'], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
                transcript = result.with_suffix('.txt').read_text().strip()
                if not transcript or len(transcript) > 2000: raise Refused('No bounded speech recognized')
                return transcript
            except (OSError, subprocess.SubprocessError) as exc:
                raise Refused('Local speech recognition failed') from exc

class VoiceSession:
    def __init__(self, show, transcribe):
        self.show, self.transcribe = show, transcribe
        self.lock = threading.RLock()
        self.token = None
        self.processing = False
        self.started = 0
    def start(self):
        with self.lock:
            if self.processing or self.token: raise Refused('Voice capture is already active')
            self.token, self.started = secrets.token_urlsafe(24), time.monotonic()
            return self.token
    def cancel(self):
        with self.lock: self.token = None
        return {'cancelled': True}
    def _check(self, token):
        if not self.token or not secrets.compare_digest(self.token, token):
            raise Refused('Voice capture cancelled or expired')
    def finish(self, audio, token, apply=False):
        with self.lock:
            self._check(token)
            if self.processing: raise Refused('Voice processing is already active')
            if time.monotonic() - self.started > 30 or not 1 <= len(audio) <= 2_000_000:
                self.token = None
                raise Refused('Voice clip is too long or too large')
            self.processing = True
        try:
            transcript = self.transcribe(audio)
            with self.lock: self._check(token)
            reply = self.show.plan_direction(transcript, source='voice')
            with self.lock: self._check(token)
            if apply:
                with self.show.lock:
                    def check():
                        with self.lock:self._check(token)
                    self.show.cancellation_check=check
                    try:reply=self.show.apply_plan(reply)
                    finally:self.show.cancellation_check=None
            return dict(reply, transcript=transcript)
        finally:
            with self.lock:
                self.token, self.processing = None, False
