Stream agent, 27 Oct

A streamer's voice, chat, a random timer or typed text becomes one bounded on-screen action for
viewers: popup, lower third, emoji burst, countdown or clear. Run with AGENTIC_OBS_PORT=8879 only:

  AGENTIC_OBS_PORT=8879 python3 stream_agent.py

Controller: http://127.0.0.1:8879/   Overlay for an OBS Browser Source: http://127.0.0.1:8879/overlay.html at 1920x1080.

Every input starts off. The server validates every action the same way whatever produced it: kind
from the preset list, text at most 80 characters, control characters stripped, links and any domain-shaped text refused, no extra
or nested fields. The overlay writes text with textContent only. Chat is a labelled SIMULATOR; no
streaming platform is connected. Chat and random have lower rate limits than voice and typed; drops are counted.

This service never starts a stream or recording and never calls OBS. Adding the overlay as a
Browser Source in OBS is an operator step. Tests: python3 -m unittest test_stream_agent.
Latency: python3 measure_latency.py OUT.json 20. It measures DOM-update latency in a headless Chromium page:
when the overlay script changed the page, not when a frame was painted, not OBS rendering, not viewer delay.

Voice (slice 2). Turn Voice on in the controller, then Start listening. The page records 16 kHz mono
audio and posts 3 s chunks as WAV (silent chunks are skipped). The server reads audio only while Voice
is on, runs local whisper-cli (default model ~/CODE/recall/.cache/models/ggml-small.bin, override with
STREAM_WHISPER_MODEL), one chunk at a time; the newest waiting chunk replaces older ones and drops are
counted. No ffmpeg and no cloud speech service. Proof without a mic: python3 measure_voice.py OUT.json
(macOS `say` phrases through real Whisper to the overlay page).

Planners (slice 3). Pick in the controller. rules: offline, instant, needs the wake word; the only
live-safe planner. codex: the operator’s Codex CLI subscription, OFF unless STREAM_CODEX_ENABLED=1, and it
must stay off until real tool isolation is verified. The invocation requests limits (--ignore-user-config,
--ignore-rules, feature switches off, a minimal environment, a read-only sandbox, an empty scratch folder,
ephemeral, schema-shaped reply, hard cap STREAM_CODEX_MAX_CALLS, default 5, clamped to 20), but effective
tool and MCP isolation is UNVERIFIED: codex debug prompt-input still lists exec, apply_patch and
exec_command, and the effect of --ignore-user-config on MCP servers was not observed. Validating its reply
protects the overlay only, not what the agent does with tools before replying. Measured 13 to 15 s per cue
on 27 Oct. openai: listed as unavailable until an API key, a root budget and a request shape checked
against current OpenAI docs exist; it makes no network call.
Proof: python3 measure_codex.py OUT.json (4 capped calls, synthetic cues).

Random and platforms (slice 4). Random draws one preset graphic every 5 to 300 s (default 20) while
Random is on. Twitch is not connected: connecting needs the operator to authorise an account (OAuth);
until then chat is a labelled simulator in the controller and on the overlay.
Controller behaviour check: python3 check_controller.py OUT.json (headless, no screenshots).

Inputs: /input accepts only JSON true or false. Turning an input off also cancels its cues still being
transcribed or planned (counted as cancelled).

Limits: one model planner call at a time (a second cue while one plans is refused, counted planner_busy);
at most 16 HTTP connections handled at once (more get 503, counted) and 8 open pages on the event stream;
requests that stall are dropped after 10 s; voice chunks over 30 a minute are refused before transcription;
STREAM_CODEX_MAX_CALLS is clamped to 20. Turning Voice off drops the waiting chunk and anything heard after.
