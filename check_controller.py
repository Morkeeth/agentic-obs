"""Controller behaviour in headless Chromium: inputs start off, typed and chat cues reach the overlay
preview, the chat label appears, no page errors. Behaviour only; no screenshots, no OBS, no mic.
Usage: python3 check_controller.py OUT.json"""
import json, sys, threading
from playwright.sync_api import sync_playwright
import stream_agent as SA

agent = SA.Agent(seed=16)
srv = SA.Server(('127.0.0.1', 0), type('H', (SA.Handler,), {'agent': agent}))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'
res, errors = {}, []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    for label, vp in (('desktop', {'width': 1440, 'height': 1000}), ('phone', {'width': 390, 'height': 844})):
        page = b.new_page(viewport=vp); page.on('pageerror', lambda e: errors.append(str(e)[:200]))
        page.on('console', lambda m: errors.append(m.text[:200]) if m.type == 'error' else None)
        page.goto(base + '/'); page.wait_for_selector('[data-input=typed]')
        r = {'all_off_at_start': page.evaluate("[...document.querySelectorAll('[data-input]')].every(b => b.getAttribute('aria-pressed') === 'false')")}
        page.click('[data-input=typed]'); page.wait_for_selector('[data-input=typed][aria-pressed=true]')
        page.fill('#typed-text', f'popup Hello from {label}'); page.click('#typed button')
        frame = page.frame_locator('#preview')
        frame.locator('#popup:not([hidden])').wait_for(timeout=5000)
        r['typed_popup_text'] = frame.locator('#popup-text').inner_text()
        page.click('[data-input=chat]'); page.wait_for_selector('[data-input=chat][aria-pressed=true]')
        page.fill('#chat-text', 'director, lower third chat says hi'); page.click('#chat button')
        frame.locator('#lower:not([hidden])').wait_for(timeout=5000)
        r['chat_lower_text'] = frame.locator('#lower-text').inner_text(); r['chat_tag'] = frame.locator('#lower-tag').inner_text()
        r['source_label'] = frame.locator('#source').inner_text()
        page.fill('#chat-text', 'director popup <img src=x onerror=alert(1)>'); page.click('#chat button')
        page.wait_for_timeout(800)
        r['markup_rendered_as_text'] = frame.locator('#popup-text').inner_text() == '<img src=x onerror=alert(1)>' and frame.locator('#popup img').count() == 0
        r['twitch_note'] = page.locator('#twitch').inner_text()
        r['overflow'] = page.evaluate('document.documentElement.scrollWidth - innerWidth')
        for s in ('typed', 'chat'):
            page.click(f'[data-input={s}]')  # leave inputs off again for the next viewport
        page.wait_for_timeout(300)
        res[label] = r; page.close()
    b.close()
srv.shutdown()
ok = all(v['all_off_at_start'] and v['typed_popup_text'].startswith('Hello from') and v['chat_tag'] == 'CHAT' and v['source_label'] == 'CHAT SIMULATOR'
         and v['markup_rendered_as_text'] and 'not connected' in v['twitch_note'] and v['overflow'] <= 1 for v in res.values()) and not errors
json.dump({'ok': ok, 'errors': errors, 'results': res}, open(sys.argv[1], 'w'), indent=1, ensure_ascii=False)
print(json.dumps({'ok': ok, 'errors': errors, 'results': res}, indent=1, ensure_ascii=False)[:2500]); sys.exit(0 if ok else 1)
