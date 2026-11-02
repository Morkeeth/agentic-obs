"""Repeat five scoped demo behaviours without microphone, model, OBS or Twitch.

This exercises the real HTTP server. Only ASR and the native engine are synthetic.
A rendered browser was exercised separately; this script does not prove real devices.
"""
import base64
import json
import threading
import urllib.request
from server import make_server
from streamer import Show
from obs import RehearsalNative

UTTERANCE = 'Director, give me a be-right-back screen in preview. Keep my camera scene safe.'

def run():
    show = Show(RehearsalNative())
    def transcribe(audio):
        if audio != b'labelled synthetic audio fixture': raise ValueError('Unexpected fixture')
        return UTTERANCE
    server = make_server(show,port=0,transcribe=transcribe)
    worker = threading.Thread(target=server.serve_forever); worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    def call(path,data=None):
        req=urllib.request.Request(origin+path, data=json.dumps(data).encode() if data is not None else None,
                                   headers={'Origin':origin,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as r: return json.load(r)
    def emit(shot, **data): print(json.dumps({'shot':shot, **data},ensure_ascii=False))
    try:
        print(json.dumps({'proof':'HTTP integration rehearsal', 'native':'synthetic camera/OBS fixture',
                          'speech':'synthetic bytes → fixture ASR transcript', 'director':'rehearsal rules, no model',
                          'audible_reply':'browser speech implementation; audibility unverified',
                          'physical_camera_microphone':False}))
        call('/api/enable',{})
        first=call('/api/stage',{'title':'Tiny break. Enormous drama.'})
        assert first['native']['program']=='Camera' and first['native']['graphics']['visible']
        emit('1 HOOK', preview=first['native']['graphics'], program='Camera', outputs=first['native']['outputs'])
        token=call('/api/voice/start',{})['token']
        voice=call('/api/voice/finish',{'token':token,'audio':base64.b64encode(b'labelled synthetic audio fixture').decode()})
        before=voice['state']['native']
        assert voice['staged'] and before['graphics']['title']=='Be right back' and before['program']=='Camera'
        emit('2 VOICE', transcript=voice['transcript'], answer=voice['answer'], preview=before['graphics'],
             program=before['program'], latency_ms=voice['latency_ms'], latency_scope=voice['latency_scope'], take=False)
        clear=call('/api/clear',{})
        restore=call('/api/restore',{})
        assert not clear['native']['graphics']['visible'] and restore['native']==before
        emit('3 CONTROL', clear_visible=clear['native']['graphics']['visible'], restored=restore['native']['graphics'],
             exact_native_state_restored=restore['native']==before, program=restore['native']['program'])
        title='Demo the demo · The director gets a director'
        presentation=call('/api/stage',{'title':title})
        assert presentation['native']['graphics']['title']==title and presentation['native']['program']=='Camera'
        emit('4 DEMO THE DEMO', preview=presentation['native']['graphics'], program='Camera', program_unchanged=True)
        end=call('/api/state')
        assert end['native']==presentation['native'] and not any(end['native']['outputs'].values())
        emit('5 END', preview=end['native']['graphics'], program='Camera', retained_preview=True,
             outputs=end['native']['outputs'], native_and_human_acceptance='pending supervised recording session')
        call('/api/disable',{})
        assert not call('/api/state')['enabled']
    finally:
        server.shutdown(); worker.join(); server.server_close()

if __name__=='__main__': run()
