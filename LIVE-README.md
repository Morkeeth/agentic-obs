# Live display connector

This optional local display connector was built on 27 October, separately from the original show-rehearsal prototype. New source is `live_server.py`, `live_mcp.py`, and `live_web/`. Original source remains available and its server still uses8873.

## Run

Install `python3 -m pip install -r requirements-live.txt`, run `python3 live_server.py`, and open http://127.0.0.1:8874/ . The browser display is http://127.0.0.1:8874/overlay.html . Add that URL as an OBS Browser Source at1920×1080 above the camera source. No OBS profile was changed automatically.

To connect an MCP-compatible agent, configure a stdio server with command `python3` and args containing the absolute path to `live_mcp.py`. Start the HTTP server first. For a reproducible isolated Python environment, use `uv run --with mcp==1.29.1 python live_mcp.py` in the MCP configuration. Tools are display_status, set_display, ingest_transcript, pause_display, undo_display, probe_obs. `set_display` supports title/subtitle/cue text, speaker/focus/break layout, lime/pink/white accent and countdown seconds. An agent can interpret general requests and call those validated structured fields. There is no embedded model call, cloud connector registration or automatically running Codex reasoning loop.

## Speaking while showing

The microphone button uses browser SpeechRecognition. It is continuous during the browser's recognition session; if that session ends the button returns to Start microphone. Microphone permission and recognition service availability depend on the browser. Some browsers send audio to their speech service. No microphone audio was captured or tested in this build. A separate speech service can instead call ingest_transcript with text, stable event_id, and final true/false.

Final transcript example: `I’m explaining what happened. Director, show The toast experiment`. Only an explicit director cue changes the output. Supported cue grammar: show/title text, caption/subtitle text, countdown number [seconds], cue/reveal text, focus, back to me, break, clear. Interim speech and ordinary narration remain visible to the controller but do not change the display. Retries with the same final event_id are suppressed (last1000IDs, memory only). Pause stops automatic changes; undo restores the previous display. A restart starts clean, with an empty event history and dedup cache. This is a local single-operator prototype, not a durable or distributed event system.

## OBS and Twitch limits

The optional OBS v5 WebSocket probe performs identification and GetVersion only. If an OBS password is needed, provide it explicitly using OBS_WEBSOCKET_PASSWORD in the HTTP server environment. It is never included in browser state. No broadcast start/stop, scene mutation, profile access, or Twitch authentication exists. Actual4455probe returned ConnectionRefusedError; the controller explicitly shows OBS disconnected. Browser overlay rendering works independently. Actual OBS/Twitch rendering remains unverified. Never present the browser preview as evidence of live Twitch output.

## Actual proof

`python3 verify_live.py` uses the official MCP SDK ClientSession and a headless browser, requiring playwright==1.60.0 plus installed Chromium for verification only. It initialized MCP, listed all six tools, changed display via tool calls, then used the real browser controls to send transcript, countdown, reveal and undo. It checked interim/no-wake speech, duplicate retry, paused updates, invalid tool fields and hostile origins. LIVE-VERIFICATION.json and LIVE-01…04 screenshots record that run. The screenshots were inspected visually; they show actual browser output. These are not microphone or OBS video evidence. The verifier uses a fresh run ID and reuses one final event ID within each run to test duplicate handling.

## Scope

This connector is an optional experiment, distinct from the tested stream-agent Twitch path. It has no embedded model conversation. Existing voice-control and overlay tools are prior art; arbitrary conversational creation and superiority over those tools are not claimed.
