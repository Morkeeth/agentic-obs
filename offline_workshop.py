"""No-account workshop: real transport -> local controller HTTP -> overlay event stream.

python3 offline_workshop.py demo --out /absolute/new/proof-directory
python3 offline_workshop.py grill                 # one question at a time
python3 offline_workshop.py grill --list          # questions and evidence, no answers
"""
import argparse
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import threading
import urllib.request
from unittest.mock import patch

from websockets.asyncio.server import serve
import fake_twitch as ft
import stream_agent as sa
from twitch_eventsub import Config, StreamAgentSink, offline_endpoints, run


@contextmanager
def local_connections_only(ports, observed):
    """Exercise the network boundary, including libraries used by the real transport."""
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex
    def check(address):
        if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] not in ports:
            raise RuntimeError('Offline workshop refuses non-owned network destinations')
        observed.append(list(address))
    def connect(sock, address):
        check(address)
        return original(sock, address)
    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)
    with patch.object(socket.socket, 'connect', connect), patch.object(socket.socket, 'connect_ex', connect_ex):
        yield


async def demo():
    agent = sa.Agent(seed=7)
    agent.planners['codex'].enabled = False
    agent.set_planner('rules')
    handler = type('WorkshopHandler', (sa.Handler,), {'agent':agent})
    # The production sink permits this dedicated rehearsal port, not arbitrary URLs.
    # Binding fails before any service is started if another controller owns it.
    controller = sa.Server(('127.0.0.1', 8881), handler)
    thread = threading.Thread(target=controller.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(controller.server_port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    events, errors, network = [], [], []
    ready = threading.Event()
    def request(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Origin':base, 'Content-Type':'application/json'})
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    def listen():
        try:
            with opener.open(base+'/events', timeout=12) as response:
                ready.set()
                for line in response:
                    if line.startswith(b'data: '):
                        events.append(json.loads(line[6:]))
                        if len(events) == 5:
                            return
        except Exception as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
            ready.set()
    reader = None
    try:
        with ft.FakeHTTP(port=0) as fake_http:
            dispatch = {}
            async def ws_handler(ws):
                await dispatch['handler'](ws)
            async with serve(ws_handler, '127.0.0.1', 0) as ws:
                ws_port = ws.sockets[0].getsockname()[1]
                http_port = fake_http.server.server_port
                dispatch['handler'], seen = await ft.scenario(fake_http, ws_port=ws_port)
                ports = {controller.server_port, http_port, ws_port}
                with local_connections_only(ports, network):
                    # This negative control must fire before anything is delivered.
                    refused = False
                    with socket.socket() as sock:
                        try:
                            sock.connect(('203.0.113.1', 443))
                        except RuntimeError:
                            refused = True
                    assert refused, 'network guard did not reject a non-owned address'
                    reader = threading.Thread(target=listen, daemon=True)
                    reader.start()
                    assert await asyncio.to_thread(ready.wait, 3), 'overlay event reader not ready'
                    request('/input', {'source':'chat','on':True})
                    cfg = Config(client_id=ft.CLIENT_ID, broadcaster_user_id=ft.BROADCASTER,
                                 reader_user_id=ft.BROADCASTER, rewards={'rw-hydrate':'Director show Hydrate!'})
                    sink = StreamAgentSink(base)
                    deliveries = []
                    def deliver(cue):
                        deliveries.append(dict(cue=cue, result=sink(cue)))
                    adapter = await asyncio.wait_for(run(cfg, offline_endpoints(ws_port, http_port), lambda:ft.TOKEN, deliver, enabled=True), 40)
                    request('/input', {'source':'chat','on':False})
                    # Synthetic text on the voice route; never microphone audio or ASR.
                    request('/input', {'source':'voice','on':True})
                    transcript = request('/cue', {'source':'voice','text':'Director lower third Offline rehearsal'})
                    request('/input', {'source':'voice','on':False})
                    await asyncio.to_thread(reader.join, 3)
                    state = request('/status')
                    assert not errors, errors
                    assert len(deliveries) == 4 and all(d['result']['shown'] for d in deliveries), deliveries
                    assert [e['action']['kind'] for e in events] == ['emoji_burst','popup','clear','popup','lower_third'], events
                    assert not any(state['inputs'].values()) and not adapter.enabled
                    assert state['models']['codex']['calls'] == 0 and not state['models']['codex']['enabled']
                    assert seen['inbound_frames'] == 0
                    assert any(r['result'] == 'duplicate' for r in adapter.trace)
                    assert any(r.get('reason') == 'wrong channel' for r in adapter.trace)
                    assert ft.TOKEN not in json.dumps(adapter.trace)
                    proof = dict(status='PASS', mode='OFFLINE_FAKE_TWITCH_SYNTHETIC_TRANSCRIPT',
                                 deliveries=deliveries, overlay_sse_events=events, transcript_result=transcript,
                                 transport_trace=adapter.trace, fake_http_requests=fake_http.requests,
                                 server_connections=seen['connections'], client_frames=seen['inbound_frames'],
                                 owned_ports=sorted(ports), observed_connections=network, network_negative_control=refused,
                                 final_inputs=state['inputs'], final_adapter_enabled=adapter.enabled, model_calls=0,
                                 limits=['HTTP/SSE functional evidence; no rendered browser or OBS-frame claim',
                                         'Synthetic transcript only; no microphone, ASR, OAuth, live Twitch or provider calls',
                                         'No stream, recording, native OBS, account, publication or submission action'])
        return proof
    finally:
        for source in sa.SOURCES:
            agent.set_input(source, False)
        controller.shutdown()
        controller.server_close()
        thread.join()


def questions():
    return json.loads((Path(__file__).parent/'grill-me.json').read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('demo')
    d.add_argument('--out', type=Path, required=True)
    g = sub.add_parser('grill')
    g.add_argument('--list', action='store_true')
    args = p.parse_args()
    if args.command == 'demo':
        args.out.mkdir(parents=True, exist_ok=False)
        proof = asyncio.run(demo())
        (args.out/'proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        print(json.dumps(dict(status=proof['status'], overlay_events=len(proof['overlay_sse_events']), model_calls=0, proof=str(args.out/'proof.json'))))
    elif args.list:
        print(json.dumps(questions(), indent=2))
    else:
        print('Grill Me: one question at a time. Answers stay in this terminal; no account or service is contacted. Type stop to pause.')
        for q in questions()['questions']:
            print('\n'+q['question'])
            try:
                answer = input('> ')
            except EOFError:
                break
            if answer.strip().lower() == 'stop':
                break
            print('Check against: '+q['evidence']+'\nFollow-up: '+q['follow_up'])


if __name__ == '__main__':
    main()
