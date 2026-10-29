# Local voice connector

This isolated checkout adds local audio ingestion to the existing live director. It does not replace the currently running service on8874.

Run with an explicit target:

    AGENTIC_OBS_PORT=8875 python3 live_server.py

Then open http://127.0.0.1:8875/. For a standalone MCP client, set the same AGENTIC_OBS_PORT=8875 in its environment when launching live_mcp.py. Missing target configuration fails closed; there is no implicit fallback to the existing demo.

Audio remains on this Mac. The existing whisper.cpp CLI and local ~/Models/whisper/ggml-large-v3-turbo.bin transcribe short chunks. Set OBS_WHISPER_MODEL to use another already installed compatible model. Raw clips and generated intermediate transcripts are removed after processing. No cloud speech service is called.

The microphone implementation requests ordinary browser microphone access and records self-contained4.5second chunks, then passes final local transcripts through the official MCP client to ingest_transcript. There is a bounded two-chunk queue; if the transcriber falls behind, the UI says a chunk was skipped rather than silently claiming continuous coverage. Say a complete director cue within a chunk and pause between cues. This is a phrase-based prototype, not uninterrupted low-latency dictation. Stopping the microphone clears queued chunks; a chunk already processing still obeys the automation pause setting. Pause automation to block pending cues.

The file input accepts up to15seconds /2MB. The server converts it with local ffmpeg (one decoder thread, file/pipe protocols only), suppresses silence, transcribes it and verifies the target connector port before a tool can change the display.

Verified: actual synthetic Samantha TTS audio -> local whisper.cpp -> official MCP ingest_transcript -> visible browser output; existing recorded speech without a cue caused no change; silence, interim transcripts, duplicate event IDs, pause, undo and cross-origin rejection were exercised. Nine real checks are recorded. The synthetic fixture is test data, not a user voice clone or a live microphone recording.

Not verified: live microphone speech. The tested browser reached 'Waiting for microphone permission'; no microphone permission was granted and no live microphone audio was captured. OBS29.1.3 was opened read-only; streaming and recording were both off. Port4455 still refused connections. No OBS source/profile/WebSocket settings or broadcast state were changed. Twitch is not connected.

During an initial boundary test, a missing MCP subprocess environment defaulted to the original8874 service. It briefly changed the topic to RETRY, then undo restored the exact preceding Toast display. Two history entries remain. The isolated MCP now requires an explicit port and refuses missing configuration; that failure was exercised while8874's full current state remained byte-equivalent before/after. The actual positive audio test used explicit8875 throughout.

Speech cue boundaries (native-preview candidate): a cue must start a transcript or a sentence with
`Director,` (or `Director:`). Ordinary mentions are ignored. Terminal sentence
punctuation is accepted for fixed commands, including `countdown20 seconds.`.
Unquoted text commands end at their first `.`, `!`, or `?` sentence boundary;
following ordinary speech is not displayed. To keep internal sentence punctuation,
use a quoted title, e.g. `Director, show "Toast. A new day".`. Terminal punctuation
is normalized. Unsupported director commands return an unchanged outcome.
Audio transport requires explicit AGENTIC_OBS_PORT; infrastructure errors return
bounded JSON HTTP 502 rather than dropping the connection.

Native OBS preview (separate branch): `obs_preview.py` sets up only the fixed
Agentic OBS Preview 27Oct profile/collection and its owned scene/source. The
Browser Source URL is exactly http://127.0.0.1:8876/overlay.html. A read-only
`owned_obs_preview_status` MCP tool verifies that source, collection, and outputs.
No stream, recording, program transition, or arbitrary OBS request is exposed.

Credentials are held in ignored `.obs-private.json` mode0600, copied from OBS's
existing generated authenticated config; never commit or display that file.
OBS29.1.3 WebSocket5.2.3 listens on a wildcard interface; authentication is ON,
and our client connects only to127.0.0.1. The HTTP connector binds loopback only.
Restore original UI: select Profile→Untitled and Scene Collection→Untitled;
prior current preview/program were LIVESTREAM and Studio Mode enabled. Original
WebSocket server was disabled; disable it in Tools→WebSocket Server Settings
when no longer needed. No stream/record was started. Keep the private original
configuration backup outside this repository; don't overwrite OBS's live files.
