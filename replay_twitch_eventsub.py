"""Offline replay: the real transport code against the local fake Twitch, writing proof.json to a new directory.
Usage: python3 replay_twitch_eventsub.py /absolute/new/proof-dir. No Twitch, OAuth, stream, OBS or provider."""
import asyncio
import json
from pathlib import Path
import sys
from websockets.asyncio.server import serve

import fake_twitch as ft
from twitch_eventsub import Config, offline_endpoints, run


async def main(out):
    cfg = Config(client_id=ft.CLIENT_ID, broadcaster_user_id=ft.BROADCASTER, reader_user_id=ft.BROADCASTER,
                 rewards={'rw-hydrate': 'Director show Hydrate!'}, keepalive_seconds=10)
    cues = []
    with ft.FakeHTTP() as http:
        handler, seen = await ft.scenario(http)
        async with serve(handler, '127.0.0.1', 8883):
            adapter = await asyncio.wait_for(run(cfg, offline_endpoints(), lambda: ft.TOKEN, cues.append, enabled=True), 40)
    proof = {'cues': cues, 'trace': adapter.trace, 'server_connections': seen['connections'],
             'server_sent': seen['sent'], 'client_inbound_frames': seen['inbound_frames'],
             'http_requests': http.requests, 'input_enabled_at_end': adapter.enabled,
             'token_in_trace': ft.TOKEN in json.dumps(adapter.trace),
             'limits': 'local fake Twitch only; not evidence of real Twitch delivery, OAuth, affiliate rewards or a stream'}
    (out / 'proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps({'cues': cues, 'connections': seen['connections'], 'posts': len([r for r in http.requests if r['method'] == 'POST']),
                      'inbound_frames': seen['inbound_frames'], 'token_in_trace': proof['token_in_trace'], 'proof': str(out / 'proof.json')}))


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=False)
    asyncio.run(main(out))
