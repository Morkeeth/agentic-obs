# Push-to-talk director — local implementation

Official OpenAI model checked 1 Nov: `gpt-realtime-2.1`. Server-side Realtime WebSocket, PCM16 mono24kHz, `marin` voice, `turn_detection:null`. This is the OpenAI API, billed separately from a ChatGPT subscription; the existing managed-subscription native voice path is not silently reused as API authentication.

## What is implemented

The existing controller Mic button now opens `/voice.html` in the same tab. Hold the button or Space to capture; release stops all tracks before uploading one WAV turn. Cancel, blur, hidden page, Stop and page exit discard capture. A12-second bound also stops capture. Late permission/old-playback completions cannot reopen it. Spoken guidance and its transcript return to the player. New speech during playback retires the prior API conversation so unheard output is not retained as heard context.

The model receives a minimal director-state projection and can stage validated composition/mode/layout changes through the existing optimistic-version check. There is no voice tool for Take, approval, connection, arming, outputs or arbitrary RPC. Existing preview/human Take controls remain responsible for going on air. Viewer text and material catalogs are not exported to this new model session.

## Offline test, no microphone or provider account

```
python3 -m unittest test_realtime_voice -v
node test_realtime_ptt.cjs
```

The checked-in `fixtures/realtime-tone.wav` is a generated200ms tone, not a human recording. The fixture test exercises the actual HTTP route and production event handling against a deterministic protocol peer. It proves WAV/event/output plumbing, origin rejection, bounded staging and capture lifecycle, NOT live model speech understanding or acoustic performance. No OBS/native app or physical device is opened.

## Supervised live configuration — do not run unattended

When Oscar is present and approves the session, provide `OPENAI_API_KEY` to the server process through the existing approved secret mechanism. No credential search, key logging or subscription-token reuse. Then the exact local command is:

```
python3 director_server.py --port 8880 --realtime-voice
```

Check that8880 is unowned before choosing it; never replace an existing controller. For a free alternative port, set `--port` explicitly. Keep stream/recording/camera off. Use the single shared AGENT Chrome window only after its owner grants the slot; open the controller's `/voice.html` in a tab, not a new window. Browser mic permission and a real spoken turn require Oscar's presence. No launch was performed while preparing this branch.

Start with the selected file input to exercise the cloud route without a microphone. A tone is not a semantic voice test; use an approved synthetic speech fixture for speech-understanding acceptance. Then, separately, inspect actual hold/release, Stop, blur and spoken guidance with Oscar before claiming live voice works.

D5 remains a distinct zero-audio synthetic native startup/render/crash/recovery acceptance. It does not itself prove voice. Run it only with fresh GO, exact source/binary pins, encode gate, planted-source RED and real-fixture GREEN, and the existing watchdog. This source branch includes the prior4fdbc7a recovery repair; the previous pinned D5 driver must be updated and reviewed to select this exact controller revision, not silently redirected.

## Current missing proof

No OpenAI API key was available in this lane. No cloud turn, physical microphone, actual speaker playback, native WebKit/CSP compatibility or integrated expanded Twitch flow was tested. Browser rendering was not launched during the Chrome freeze. Public source parity, replacement film and final form remain separate gates.

## Official sources

- https://developers.openai.com/api/docs/models/gpt-realtime-2.1
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://developers.openai.com/api/docs/guides/voice-websockets
