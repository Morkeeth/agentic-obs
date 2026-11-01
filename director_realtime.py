"""Explicit opt-in Realtime voice. No devices, credential discovery or OBS launch.

Audio arrives only as one bounded WAV clip. The model can stage visuals, never
approve/Take, arm OBS or start outputs. The API key stays in the server process.
"""
import base64
import io
import json
import threading
import time
import wave

MODEL = 'gpt-realtime-2.1'
RATE = 24000
MAX_SECONDS = 12
MAX_AUDIO = RATE * 2 * 30
INSTRUCTIONS = ('You are the streamer’s live visual director. Give brief, useful spoken guidance, '
    'ask one question when intent is unclear, and say what you plan before staging a visual. '
    'Use only supplied state; never claim you saw native pixels or heard a live stream. '
    'You may stage a composition or layout. You cannot approve, Take, connect, arm, '
    'record, stream, enable a microphone or act on viewer messages. The human must '
    'inspect the preview and use the existing controls to put anything on air.')


def pcm_from_wav(data):
    if not isinstance(data, bytes) or len(data) > RATE * 2 * MAX_SECONDS + 4096:
        raise ValueError('Use a WAV clip of at most 12 seconds')
    try:
        with wave.open(io.BytesIO(data), 'rb') as clip:
            if (clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getcomptype()) != (1, 2, RATE, 'NONE'):
                raise ValueError('Use mono 24 kHz PCM16 WAV')
            count = clip.getnframes()
            if not RATE // 10 <= count <= RATE * MAX_SECONDS:
                raise ValueError('Use 0.1–12 seconds of audio')
            pcm = clip.readframes(count)
            if len(pcm) != count * 2:
                raise ValueError('Incomplete WAV clip')
            return pcm
    except (wave.Error, EOFError):
        raise ValueError('Invalid WAV clip') from None


def wav_from_pcm(pcm):
    out = io.BytesIO()
    with wave.open(out, 'wb') as clip:
        clip.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        clip.writeframes(pcm)
    return out.getvalue()


class RealtimeDirector:
    def __init__(self, director, api_key=None, connect=None):
        self.director, self._key, self._connect = director, api_key, connect
        self._socket = None
        self._lock = threading.Lock()
        self._guard = threading.Lock()
        self._generation = 0
        self._live_verified = False

    def status(self):
        return {'enabled': bool(self._key), 'model': MODEL, 'push_to_talk': True,
                'automatic_capture': False, 'max_seconds': MAX_SECONDS,
                'live_provider_verified': self._live_verified}

    def close(self):
        # Can interrupt a blocked receive; no reconnect/replay after Stop.
        with self._guard:
            self._generation += 1
            sock, self._socket = self._socket, None
        if sock:
            sock.close()

    def _send(self, event):
        if self._socket is None:
            raise ValueError('Voice stopped')
        self._socket.send(json.dumps(event))

    def _state(self):
        state = self.director.agent_state()
        # Do not export catalogs, selected material, raw viewer text or history.
        return {k: state.get(k) for k in ('version', 'armed', 'paused',
                'rendered_ready', 'current_native_layout', 'program_bank')}

    def _stage(self, event):
        if event.get('name') != 'stage_visual':
            return {'error': 'Voice can only stage a visual; use human controls for Take'}
        try:
            args = json.loads(event['arguments'])
            if set(args) != {'expected_version', 'fields'}:
                raise ValueError('Exact stage contract required')
            fields = args['fields']
            if not isinstance(fields, dict) or not fields or set(fields) - {'composition', 'mode', 'layout'}:
                raise ValueError('Only composition, mode and layout may be staged')
            self.director.execute_agent({'action': 'stage_patch', 'fields': fields}, args['expected_version'])
            return {'staged': True, 'state': self._state(), 'on_air_changed': False}
        except Exception:
            return {'error': 'Stage refused; state changed or visual was invalid. Ask the human; do not retry.'}

    def turn(self, data):
        pcm = pcm_from_wav(data)  # Validate before any provider call.
        if not self._key:
            raise ValueError('Realtime is off; explicitly enable it with a server-side OpenAI API key')
        if not self._lock.acquire(blocking=False):
            raise ValueError('Director is answering; wait or press Stop')
        try:
            generation = self._generation
            if self._socket is None:
                connect = self._connect
                if connect is None:
                    from websocket import create_connection
                    connect = create_connection
                socket = connect('wss://api.openai.com/v1/realtime?model=' + MODEL,
                    header=['Authorization: Bearer ' + self._key], timeout=8)
                with self._guard:
                    if generation != self._generation:
                        socket.close()
                        raise ValueError('Voice stopped while connecting')
                    self._socket = socket
                self._send({'type': 'session.update', 'session': {
                    'type': 'realtime', 'model': MODEL, 'output_modalities': ['audio'],
                    'instructions': INSTRUCTIONS,
                    'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': RATE}, 'turn_detection': None},
                              'output': {'format': {'type': 'audio/pcm', 'rate': RATE}, 'voice': 'marin'}},
                    'tools': [{'type': 'function', 'name': 'stage_visual',
                        'description': 'Stage only. Never puts a change on air. Use the supplied current version.',
                        'parameters': {'type': 'object', 'properties': {
                            'expected_version': {'type': 'integer'},
                            'fields': {'type': 'object', 'properties': {
                                'composition': {'type': 'object'}, 'layout': {'type': 'string'}, 'mode': {'type': 'string'}},
                                'additionalProperties': False}},
                            'required': ['expected_version', 'fields'], 'additionalProperties': False}}]}})
            self._send({'type': 'conversation.item.create', 'item': {'type': 'message', 'role': 'system',
                'content': [{'type': 'input_text', 'text': 'Current bounded director state: ' + json.dumps(self._state())}]}})
            self._send({'type': 'input_audio_buffer.clear'})
            for start in range(0, len(pcm), 24000):
                self._send({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm[start:start + 24000]).decode()})
            self._send({'type': 'input_audio_buffer.commit'})
            self._send({'type': 'response.create'})
            chunks, transcript, tools, pending_tools = [], [], 0, False
            deadline = time.monotonic() + 30
            for _ in range(1000):
                if time.monotonic() > deadline:
                    raise ValueError('Director response timed out')
                event = json.loads(self._socket.recv())
                kind = event.get('type')
                if kind == 'error':
                    raise ValueError('Realtime provider refused the turn; no automatic retry')
                if kind == 'response.output_audio.delta':
                    chunks.append(base64.b64decode(event['delta'], validate=True))
                    if sum(map(len, chunks)) > MAX_AUDIO:
                        raise ValueError('Director reply exceeded its audio limit')
                elif kind == 'response.output_audio_transcript.delta':
                    transcript.append(event.get('delta', ''))
                    if sum(map(len, transcript)) > 8000:
                        raise ValueError('Director reply exceeded its text limit')
                elif kind == 'response.function_call_arguments.done':
                    tools += 1
                    if tools > 2:
                        raise ValueError('Director action limit reached')
                    with self._guard:
                        if self._socket is None:
                            raise ValueError('Voice stopped; action discarded')
                        result = self._stage(event)
                    self._send({'type': 'conversation.item.create', 'item': {'type': 'function_call_output',
                        'call_id': event['call_id'], 'output': json.dumps(result)}})
                    pending_tools = True
                elif kind == 'response.done':
                    if event.get('response', {}).get('status') != 'completed':
                        raise ValueError('Director reply did not complete')
                    if pending_tools:
                        pending_tools = False
                        self._send({'type': 'response.create'})
                        continue
                    if not chunks:
                        raise ValueError('No spoken guidance received')
                    self._live_verified = self._connect is None
                    return {'model': MODEL, 'text': ''.join(transcript),
                        'audio_wav': base64.b64encode(wav_from_pcm(b''.join(chunks))).decode(),
                        'state': self._state(), 'input': 'one bounded WAV clip'}
            raise ValueError('Director event limit reached')
        except ValueError:
            self.close()
            raise
        except Exception:
            self.close()
            raise ValueError('Realtime connection failed; no automatic retry') from None
        finally:
            self._lock.release()
