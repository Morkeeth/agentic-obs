"""Local-only voice adapter, adapted from the attributed voice_pipeline flow.

No MCP/model tools: transcript enters the same closed operator action grammar.
Only an explicitly selected project-local whisper.cpp model is considered.
"""
import audioop
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

ROOT = Path(__file__).resolve().parent


class LocalVoice:
    def __init__(self, model=None):
        self.model = Path(model).resolve() if model else None
        if self.model and not self.model.is_relative_to(ROOT):
            raise ValueError('Choose a model explicitly inside this project; no home-directory discovery')
        self.lock = threading.Lock()

    def status(self):
        ready = bool(self.model and self.model.is_file() and shutil.which('whisper-cli') and shutil.which('ffmpeg'))
        return {'ready': ready, 'local_only': True, 'physical_microphone_verified': False,
                'detail': 'Configured local whisper.cpp' if ready else 'Voice unavailable: select a local model and install whisper.cpp + ffmpeg',
                'max_seconds': 15, 'generation': 'No model composition; transcription only'}

    def transcribe(self, data):
        if not self.status()['ready']: raise ValueError(self.status()['detail'])
        if not isinstance(data, bytes) or not 44 <= len(data) <= 3_000_000: raise ValueError('Audio clip size invalid')
        if data[:4] == b'RIFF' and data[8:12] == b'WAVE': fmt = 'wav'
        elif data[:4] == b'\x1aE\xdf\xa3': fmt = 'matroska'
        elif data[:4] == b'OggS': fmt = 'ogg'
        else: raise ValueError('Use WAV, WebM or Ogg audio; playlists and remote media are refused')
        if not self.lock.acquire(False): raise ValueError('Local transcriber busy')
        folder = ROOT/'.director-data'/'audio-tmp'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=folder) as tmp:
                tmp = Path(tmp); raw = tmp/'input.audio'; wav = tmp/'voice.wav'; output = tmp/'words'
                raw.write_bytes(data)
                canonical = False
                if fmt == 'wav':
                    try:
                        with wave.open(io.BytesIO(data)) as original:
                            canonical = (original.getnchannels(), original.getframerate(), original.getsampwidth(), original.getcomptype()) == (1, 16000, 2, 'NONE')
                    except wave.Error: raise ValueError('Invalid WAV audio') from None
                if canonical:
                    wav.write_bytes(data)
                else:
                    converted = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe',
                        '-f', fmt, '-i', str(raw), '-t', '15.1', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)],
                        capture_output=True, timeout=30)
                    if converted.returncode: raise ValueError('Local audio decode failed')
                with wave.open(str(wav)) as audio:
                    duration = audio.getnframes()/audio.getframerate()
                    if duration > 15: raise ValueError('Audio must be 15 seconds or shorter')
                    if audioop.rms(audio.readframes(audio.getnframes()), 2) < 40:
                        return {'text': '', 'silence': True, 'local_only': True}
                recognized = subprocess.run([shutil.which('whisper-cli'), '-m', str(self.model), '-f', str(wav), '-t', '1', '-p', '1',
                    '-l', 'en', '-nt', '-otxt', '-of', str(output), '-bo', '1', '-bs', '1'], capture_output=True, timeout=120)
                if recognized.returncode or not output.with_suffix('.txt').is_file(): raise ValueError('Local transcription failed')
                value = ' '.join(output.with_suffix('.txt').read_text()[:1600].split())
                return {'text': value, 'silence': False, 'local_only': True}
        except subprocess.TimeoutExpired:
            raise ValueError('Local transcription timed out') from None
        finally:
            self.lock.release()
