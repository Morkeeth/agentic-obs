"""Latency from a typed cue to text on the overlay page, in headless Chromium. No screenshots, no OBS.

Usage: python3 measure_latency.py OUT.json [N]
Stages, all on this machine's clock: client send -> server received -> planned -> published ->
overlay drew it (the page's own Date.now when it updated the DOM).
"""
import json
import statistics
import sys
import threading
import time
import urllib.request

from playwright.sync_api import sync_playwright

import stream_agent as SA

out, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20
agent = SA.Agent(seed=3)
handler = type('H', (SA.Handler,), {'agent': agent})
srv = SA.Server(('127.0.0.1', 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'
agent.set_input('typed', True)
SA.RATE['typed'] = max(SA.RATE['typed'], n + 5)


def post(path, body):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode(), method='POST',
                               headers={'Content-Type': 'application/json', 'Origin': base})
    return json.load(urllib.request.urlopen(r))


rows = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto(base + '/overlay.html'); page.wait_for_timeout(500)
    for i in range(n):
        sent = time.time()
        r = post('/cue', {'source': 'typed', 'text': f'popup Cue {i}'})
        eid = r['event']['id']
        page.wait_for_function('id => window.__lastShown && window.__lastShown.id === id', arg=eid, timeout=5000)
        shown = page.evaluate('window.__lastShown')
        text = page.evaluate("document.getElementById('popup-text').textContent")
        t = r['event']['timing']
        rows.append({'cue': i, 'text_on_overlay': text, 'send_to_received_ms': (t['received'] - sent) * 1000,
                     'received_to_published_ms': (t['published'] - t['received']) * 1000,
                     'published_to_dom_update_ms': (shown['domUpdatedAt'] - t['published']) * 1000,
                     'send_to_dom_update_ms': (shown['domUpdatedAt'] - sent) * 1000})
        page.wait_for_timeout(150)
    browser.close()
srv.shutdown()
ok = all(r['text_on_overlay'] == f'Cue {r["cue"]}' for r in rows)
summary = {k: {'median': round(statistics.median(r[k] for r in rows), 2), 'max': round(max(r[k] for r in rows), 2)}
           for k in ('send_to_received_ms', 'received_to_published_ms', 'published_to_dom_update_ms', 'send_to_dom_update_ms')}
result = {'cues': n, 'all_text_matched': ok, 'planner': 'rules', 'summary_ms': summary, 'rows': rows,
          'scope': 'DOM-update latency in a headless Chromium page on this Mac: when the overlay script changed the page, not when a frame was painted, not OBS rendering, not stream or viewer delay'}
json.dump(result, open(out, 'w'), indent=1, ensure_ascii=False)
print(json.dumps({'all_text_matched': ok, 'summary_ms': summary}, indent=1))
sys.exit(0 if ok else 1)
