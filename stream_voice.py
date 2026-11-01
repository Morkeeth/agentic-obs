"""Continuous voice for the stream agent: short WAV chunks -> local whisper-cli -> the same planner.

The browser records 16 kHz mono 16-bit PCM and posts fixed chunks as WAV. Nothing leaves this Mac:
whisper.cpp runs locally, the chunk is written to a private temporary file and deleted after use.
One transcription runs at a time. While it runs, the newest waiting chunk replaces any older one and
the replaced chunk is counted as dropped, so the agent follows what the streamer is saying now.
No ffmpeg: the server only accepts WAV that is already 16 kHz mono 16-bit.
"""
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

MODEL = Path(os.environ.get('STREAM_WHISPER_MODEL', str(Path.home() / 'CODE/recall/.cache/models/ggml-small.bin')))
MAX_BYTES = 400_000          # about 12 s of 16 kHz mono 16-bit audio
MAX_SECONDS = 8.0
TIMEOUT = 30
CHUNKS_PER_MINUTE = 30       # admission limit, checked before any transcription work


class VoiceRejected(ValueError):
    pass


def readiness():
    binary = shutil.which('whisper-cli')
    return {'ready': bool(binary) and MODEL.is_file(), 'whisper_cli': binary, 'model': str(MODEL),
            'model_bytes': MODEL.stat().st_size if MODEL.is_file() else None, 'local_only': True}


def check_wav(data):
    """Accept only the format whisper.cpp reads directly; returns the duration in seconds."""
    if len(data) > MAX_BYTES:
        raise VoiceRejected('audio chunk is too large')
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (1, 16000, 2):
                raise VoiceRejected('audio must be 16 kHz mono 16-bit WAV')
            seconds = w.getnframes() / 16000
    except (wave.Error, EOFError) as e:
        raise VoiceRejected('not a WAV file') from e
    if not 0.2 <= seconds <= MAX_SECONDS:
        raise VoiceRejected('audio chunk must be 0.2 to 8 seconds')
    return seconds


def transcribe(data, model=None, binary=None):
    """Run whisper-cli on one chunk. Returns (text, wall seconds)."""
    model, binary = Path(model or MODEL), binary or shutil.which('whisper-cli')
    if not binary or not model.is_file():
        raise VoiceRejected('local transcription is not installed')
    with tempfile.TemporaryDirectory(prefix='stream-voice-') as tmp:
        path = Path(tmp) / 'chunk.wav'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        start = time.time()
        # Greedy decoding (beam 1) keeps the wait short; English only, no timestamps, text on stdout.
        run = subprocess.run([binary, '-m', str(model), '-f', str(path), '-l', 'en', '-nt', '-np', '-bs', '1', '-bo', '1', '-t', '4'],
                             capture_output=True, text=True, timeout=TIMEOUT)
        took = time.time() - start
    if run.returncode:
        raise VoiceRejected('transcription failed')
    text = ' '.join(line.strip() for line in run.stdout.splitlines() if line.strip())
    # whisper marks silence and noise with bracketed tags; those are not speech.
    if text.startswith('[') and text.endswith(']') or text.lower() in ('(silence)', '[blank_audio]'):
        text = ''
    return text, took


class VoiceWorker:
    """One whisper run at a time; the newest pending chunk wins."""

    def __init__(self, agent, transcriber=transcribe):
        self.agent, self.transcriber = agent, transcriber
        self.cond = threading.Condition()
        self.pending = None
        self.stats = {'chunks_received': 0, 'chunks_dropped': 0, 'rate_refused': 0, 'cancelled': 0, 'transcribed': 0, 'empty': 0,
                      'errors': 0, 'last_whisper_s': None}
        self.admitted = []
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def offer(self, data):
        seconds = check_wav(data)
        received = time.time()
        with self.cond:
            self.admitted = [t for t in self.admitted if received - t < 60]
            if len(self.admitted) >= CHUNKS_PER_MINUTE:
                self.stats['rate_refused'] += 1
                raise VoiceRejected(f'more than {CHUNKS_PER_MINUTE} voice chunks a minute')
            self.admitted.append(received)
            self.stats['chunks_received'] += 1
            if self.pending is not None:
                self.stats['chunks_dropped'] += 1
            self.pending = (data, received, seconds, self.agent.epoch['voice'])
            self.cond.notify()
        return {'queued': True, 'seconds': round(seconds, 2)}

    def cancel(self):
        """Voice was turned off: forget the waiting chunk. The one being transcribed is dropped when it returns."""
        with self.cond:
            if self.pending is not None:
                self.pending = None
                self.stats['cancelled'] += 1

    def _current(self, epoch):
        with self.agent.lock:
            return self.agent.inputs['voice'] and self.agent.epoch['voice'] == epoch

    def _run(self):
        while self.running:
            with self.cond:
                while self.pending is None:
                    self.cond.wait()
                data, received, seconds, epoch = self.pending
                self.pending = None
            if not self._current(epoch):
                with self.cond:
                    self.stats['cancelled'] += 1
                continue
            try:
                text, took = self.transcriber(data)
            except Exception:  # noqa: BLE001 - one bad chunk never stops listening
                with self.cond:
                    self.stats['errors'] += 1
                continue
            with self.cond:
                self.stats['last_whisper_s'] = round(took, 3)
                self.stats['transcribed' if text else 'empty'] += 1
            if not text:
                continue
            with self.agent.lock:  # recheck and publish together: nothing heard after OFF reaches any page
                if not self._current(epoch):
                    with self.cond:
                        self.stats['cancelled'] += 1
                    continue
                self.agent.publish({'type': 'transcript', 'text': text, 'whisper_s': round(took, 3), 'audio_s': round(seconds, 2)})
            self.agent.submit('voice', text=text, received_at=received, epoch=epoch,
                              extra_timing={'whisper_s': round(took, 3), 'audio_s': round(seconds, 2)})
