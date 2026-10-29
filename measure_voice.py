"""Spoken cue to overlay, through real local Whisper, in headless Chromium. No mic, no OBS, no screenshots.

Phrases are spoken by macOS `say` straight to 16 kHz mono WAV and posted to /voice-chunk exactly as
the controller does. Usage: python3 measure_voice.py OUT.json
"""
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

import stream_agent as SA
import stream_voice as SV

PHRASES = [('Director, popup hello viewers.', {'kind': 'popup'}),
           ('Director, lower third building live tonight.', {'kind': 'lower_third'}),
           ('Director, countdown 5 seconds, demo time.', {'kind': 'countdown'}),
           ('Director, fire emoji.', {'kind': 'emoji_burst'}),
           ('Director, clear the screen.', {'kind': 'clear'}),
           ('I think the build is going well today.', None)]

out = sys.argv[1]
ready = SV.readiness()
if not ready['ready']:
    raise SystemExit('local whisper not ready: ' + json.dumps(ready))
agent = SA.Agent(seed=8); agent.set_input('voice', True)
handler = type('H', (SA.Handler,), {'agent': agent})
srv = SA.Server(('127.0.0.1', 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'
rows = []
with tempfile.TemporaryDirectory(prefix='stream-voice-proof-') as tmp, sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto(base + '/overlay.html'); page.wait_for_timeout(500)
    q = agent.subscribe()
    for i, (phrase, expect) in enumerate(PHRASES):
        wav = Path(tmp) / f'{i}.wav'
        subprocess.run(['say', '-o', str(wav), '--file-format=WAVE', '--data-format=LEI16@16000', phrase], check=True)
        data = wav.read_bytes()
        before = page.evaluate('window.__lastShown && window.__lastShown.id')
        sent = time.time()
        r = urllib.request.Request(base + '/voice-chunk', data=data, method='POST', headers={'Content-Type': 'audio/wav', 'Origin': base})
        json.load(urllib.request.urlopen(r))
        transcript, event = None, None
        deadline = time.time() + 30
        while time.time() < deadline and (transcript is None or (expect and event is None)):
            try:
                ev = q.get(timeout=1)
            except Exception:  # noqa: BLE001
                continue
            if ev.get('type') == 'transcript':
                transcript = ev
            elif ev.get('action'):
                event = ev
        if not expect:
            time.sleep(1.0)
        row = {'phrase': phrase, 'heard': transcript and transcript['text'], 'expected': expect and expect['kind'],
               'shown_kind': event and event['action']['kind'], 'audio_s': transcript and transcript['audio_s'], 'whisper_s': transcript and transcript['whisper_s']}
        if event:
            page.wait_for_function('id => window.__lastShown && window.__lastShown.id === id', arg=event['id'], timeout=5000)
            shown = page.evaluate('window.__lastShown')
            row.update(post_to_dom_update_s=round(shown['domUpdatedAt'] - sent, 3), published_to_dom_update_ms=round((shown['domUpdatedAt'] - event['timing']['published']) * 1000, 2))
        else:
            row['overlay_changed'] = page.evaluate('window.__lastShown && window.__lastShown.id') != before
        row['ok'] = (row['shown_kind'] == row['expected']) if expect else (not row.get('overlay_changed') and row['shown_kind'] is None)
        rows.append(row)
        time.sleep(0.3)
    browser.close()
srv.shutdown()
shown = [r for r in rows if r.get('post_to_dom_update_s')]
result = {'whisper': ready, 'all_ok': all(r['ok'] for r in rows), 'rows': rows,
          'summary_s': {'whisper_median': round(statistics.median(r['whisper_s'] for r in rows if r['whisper_s']), 3),
                        'whisper_max': max(r['whisper_s'] for r in rows if r['whisper_s']),
                        'chunk_post_to_dom_update_median': round(statistics.median(r['post_to_dom_update_s'] for r in shown), 3),
                        'chunk_post_to_dom_update_max': max(r['post_to_dom_update_s'] for r in shown)},
          'scope': 'DOM-update latency (not paint, OBS or viewer): synthetic macOS say voice, one chunk per phrase, headless Chromium overlay on this Mac. Live mic chunking adds up to the 3 s chunk length before a chunk is sent.'}
json.dump(result, open(out, 'w'), indent=1, ensure_ascii=False)
print(json.dumps({k: result[k] for k in ('all_ok', 'summary_s')}, indent=1))
for r in rows:
    print(r['ok'], '|', r['phrase'], '| heard:', r['heard'], '| shown:', r['shown_kind'], '| whisper', r['whisper_s'], '| total', r.get('post_to_dom_update_s'))
sys.exit(0 if result['all_ok'] else 1)
