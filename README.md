# Agentic Streamer

Direct the next moment of your show while staying in the conversation. Start listening or hold push-to-talk, ask for a title, slide or layout correction, and inspect the prepared preview. Spoken replies are optional. Your camera stays in program. Clear hides the graphic; Restore brings back the previous safe preview.

This is a local directing studio for OBS, built with Codex. Preview is the default. The optional live composition mode accepts an exact spoken “take it” or “go live” to change local Program; recording and virtual camera outputs must remain off. Preview staging can continue during an operator-started Twitch stream; local Take remains blocked while streaming. It has no broadcast controls.

## Try it in 60 seconds

Requires Python 3.12. From the repository directory, run:

```sh
python3 -m pip install -r requirements.txt
python3 server.py --port 60212
```

Open **http://127.0.0.1:60212/** in Chrome. The typed rehearsal needs no accounts or devices.

1. Click **Enable preview control**.
2. Type **Give me a be-right-back screen in preview** and click **Ask director**.
3. Inspect the reply, then click **Stage in preview**. The preview says **Be right back**, while program remains **Camera**.
4. Click **Clear graphic**, then **Restore preview**.
5. Change the title to **Demo the demo**, then stage it.

The default camera and OBS state are visibly labelled synthetic. The default director uses deterministic rehearsal rules. The typed route proposes a title for inspection; the held voice route stages its returned title when preview control is enabled. A successful typed rehearsal does not prove microphone recognition, model execution or native OBS rendering.

## The five demo shots

| Shot | Action | What to check |
| --- | --- | --- |
| 1 · Hook | Stage a playful title, such as “Tiny break. Enormous drama.” | Preview changes; camera program stays unchanged |
| 2 · Voice | Hold PTT, say “Director, give me a be-right-back screen in preview. Keep my camera scene safe.”, then release | Transcript, spoken answer, BRB preview and measured latency; no Take |
| 3 · Control | Clear, then Restore | Graphic hides, prior preview returns, camera stays intact |
| 4 · Demo the demo | Stage a fun title for the presentation | Title visible in preview; camera program unchanged |
| 5 · End | Inspect the camera and retained preview | Both pictures visible; outputs remain off |

Run the complete account-free HTTP rehearsal with `python3 demo_shots.py`. It uses a labelled synthetic native adapter and an explicit ASR fixture. The printed latency is fixture latency, not real voice/model performance.

## Voice and an optional Codex director

Install local `whisper-cli` and `ffmpeg`, then configure an already installed Whisper model:

```sh
export STREAM_WHISPER_MODEL="$HOME/Models/whisper/ggml-large-v3-turbo.bin"
python3 server.py --port 60212
```

Click **Start listening** for continuous capture: pause between directions while the microphone stays on during processing. **Stop listening**, Cancel and page hiding stop it. A microphone picker and level meter help verify the selected input. Alternatively hold **Hold to talk**; release sends one complete clip, and focus loss cancels held capture. Clips are bounded to 15 seconds / 2 MB and temporary audio/transcription files are removed after processing. Replies are written by default. Enable **Speak director replies**, select an installed voice and hear its sample if desired; speech quality depends on installed system voices.

Add `--director codex` to use an installed, signed-in Codex CLI. It returns a structured answer and title from an ephemeral read-only working directory, with user configuration and the shell tool disabled. The model receives no OBS tools. Runtime model use consumes account quota; the default rehearsal consumes none. A failed model call is reported rather than silently replaced with a rules answer. The transport follows the [official structured-output example](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex).

## Connect an existing OBS instance

Requires authenticated OBS WebSocket v5 and Studio Mode. Recording and virtual camera outputs must be off; an operator-started stream can remain active while preview is edited. This app never launches OBS or creates camera devices. The default mode uses your prepared scenes; `--live` creates two owned composition scenes. Prepare a **Camera** program scene and a separate **Staging** scene containing one native text source named **graphics**. The owned text source and visual sources `preview-image` and `preview-page` must not appear anywhere in program, including nested scenes or groups. The app creates those image/browser inputs inside Staging as needed. Keep program and preview separate. Change the staging/source names with `--staging` and `--graphics` if needed.

```sh
python3 -m pip install -r requirements.txt
# Supply OBS_PASSWORD privately in the process environment.
python3 server.py --port 60212 --obs --obs-port 4455 --staging Staging --graphics graphics
```

Enable preview control in the workspace. Native program and preview screenshots refresh continuously with one request at a time; inspect the actual picture in OBS too. Before every native write the app checks the camera scene, owned title and output state. Uncertain operations disarm control without replay. Inspect OBS before re-enabling.

## Checks and honest limits

```sh
python3 -m unittest discover -s tests -v
node tests/ptt.test.cjs
node tests/continuous.test.cjs
node tests/monitor.test.cjs
node tests/speech.test.cjs
node tests/music.test.cjs
python3 demo_shots.py
```

Native checks have exercised continuous directions through real local Whisper and authenticated OBS: framing, slides, picture-in-picture, borders, lower thirds, video clips, animated overlays, LUT filters, clear and restore. The continuous proofs inject a labelled synthetic voice file through the real browser audio pipeline; they do not establish physical microphone or human speech acceptance. Known cues use a fast local parser; other directions use the selected Codex CLI. A real Codex direction was checked separately. Typical measured fast-cue latency was about 2–2.5 seconds after the phrase; model calls take longer.

## Live composition and populated library

With the OBS setup above, start the independent composition mode:

```sh
python3 server.py --port 60212 --obs --director codex --live
```

Say “zoom in on me”, “close up”, “switch to the wide shot”, “put the slides left”, “add a border”, “go picture in picture”, or “lower third Welcome”. The included camera assets are silent, looping **pre-recorded camera** footage, clearly labelled in the picture. They are not a live webcam. Actual camera scene names can be explicitly allowlisted using repeated `--camera-scene` options.

The library panel shows copied, indexed assets with thumbnails. Try “show the folders clip”, “play the notification burst”, “show the split”, “cinematic look”, “make it warmer”, then “normal”. Clear removes staged graphics and Restore brings back the preceding composition. LUTs apply to owned camera inputs. The native adapter checks decoded media playback and mute state before accepting the composition. Asset provenance and licence notes are in `assets/library/index.json`; these permissions do not grant a general licence to third-party marks or source material.

A local, separately licensed music bed can be configured in `.runtime/licensed-media/index.json`. “Play music” and “stop music” control it; the browser ducks the bed under detected speech and director replies. The development recording uses a licensed track that is deliberately excluded from the public source export. A fresh account-free checkout has no music track configured.

Owned scenes **Director A** and **Director B** alternate when one is in Program. Every native edit checks that its target bank and owned inputs are absent from Program, including nested scenes. With all outputs off, local Take requires the exact operator voice phrase “take it” or “go live”; typed requests, chat and model proposals cannot invoke it. Local Take is covered by adapter tests but has not yet been accepted in a supervised human recording. No output-start operation exists.

## Public browsing and Twitch

In live composition mode, “open our GitHub repo”, “find the TwitchCon logo”, “search for …”, “open https://example.org”, and “scroll down” drive a separate empty-profile headless Chrome. Public page URL, title and scroll position are read back through CDP; OBS renders the same URL and scroll position in an owned browser source. These are separate browser engines, so exact dynamic page state is not mirrored. The logo cue opens an image search; it does not claim to identify or license a logo. The PayPal cue opens the public project README because no hosted demo is configured. There are no account, posting, form or arbitrary desktop actions.

The Twitch panel can join a public channel through a read-only anonymous connection and stage its overlay with “show chat”. Real guest connection, channel room metadata and receipt of an operator’s `!brb` message have been verified. Authenticated EventSub is not implemented. The first live command was safely refused by the earlier outputs-off guard; after the stream-only preview policy was corrected, an operator's `!brb` sent during a live Twitch stream was received and staged in preview, with Program unchanged. The overlay labels its waiting state and never invents messages. Viewer text has no operator authority. The operator can explicitly enable only `!brb`, `!title <text>` and `!zoom` as fixed preview commands. Titles are bounded to 180 printable characters; commands are deduplicated and rate-limited to one every two seconds. The app and overlay show the real triggering message and whether staging succeeded or was refused. Chat cannot Take, browse, invoke arbitrary model prompts, or start outputs.

The **Prepare Twitch bandwidth test** button only modifies an already configured Twitch OBS service. It validates the existing destination and stream key privately, adds the documented `?bandwidthtest=true` suffix, reads it back, and leaves every output off. It never returns credentials or starts a stream. The operator alone clicks Start Streaming in OBS. Twitch documents this parameter as disabling live viewing: [Twitch video broadcast documentation](https://dev.twitch.tv/docs/video-broadcast/). Actual bandwidth-test ingest has not been exercised. The operator instead started an approved public Twitch stream for the live test. Preview edits remain permitted when streaming is the only active output. Every edit checks that Program has not changed and that owned staging inputs remain absent from Program. A detected Program change refuses the operation and marks it uncertain. Recording and virtual camera still block edits; Take is always blocked during a stream.

Native monitors show refreshed screenshots rather than full-rate video. Development clips use sampled frames, preserve wall-clock timing and label synthetic command audio. Actual OBS rendering was measured at 30 fps; this does not make the app monitor or sampled proof a 30 fps capture. Spoken replies use selected installed browser voices; voice quality depends on the system and awaits operator acceptance.

OBS has no atomic conditional scene write, so checks cannot guarantee isolation from a simultaneous manual scene cut. Avoid concurrent Program changes during staging. Uncertain native operations disarm control. Clear confirms hidden native items rather than texture erasure. The server binds loopback only; no personal browser or account is used.

## Built with Codex

This independent implementation, its tests and local rehearsal were built in Codex session **01a19bd8-b912-7441-956c-110adb84d9d6** from written requirements. An earlier prototype existed; its application files were not copied into this build. The attribution covers this preview studio, not the earlier prototype's broader capabilities.
