# Agentic OBS

Demo video: a 94-second local candidate is ready; the public YouTube link is pending. No submission is claimed.

Direct a show while staying in the conversation. This prototype connects bounded streamer cues and permitted Twitch chat commands to graphics, with a separate native OBS connector for scenes and saved animations.

The intended product is live editing through a conversation: create a segment, refine its look and motion, let chat participate, then reuse it next stream. The current implementation contains several working experiments; the complete conversational flow is still in progress. Codex was used to build the project. The experimental Codex runtime planner is disabled; the runnable demonstration uses rules.

## Run the account-free rehearsal

Requires Python 3.12 and an available local TCP stack. Dependency installation needs internet access. From a fresh clone, enter the repository directory and run:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest test_twitch_eventsub test_mock_eventsub test_mock_transport test_stream_agent
.venv/bin/python offline_workshop.py demo --out /tmp/agentic-obs-first-rehearsal
```

Use a new output directory; the command refuses an existing one. Port 8881 must be free for its owned rehearsal controller; fake Twitch uses ephemeral ports. It starts and stops only its own services. Read the resulting `proof.json`. Expected: five accepted actions through the real controller and overlay event stream, duplicate and wrong-channel rejection, reconnect handling, and all inputs off at the end. This uses fake Twitch and a synthetic transcript. It does not demonstrate a live channel, microphone recognition or rendered OBS frames.

## See the overlay

```sh
AGENTIC_OBS_PORT=8879 STREAM_CODEX_ENABLED=0 .venv/bin/python stream_agent.py
```

Open `http://127.0.0.1:8879/` for the controller and `http://127.0.0.1:8879/overlay.html` for the graphics. All inputs start disabled. Enable Typed, then try a documented cue such as `Director, show Hello stream.`. Inspect the controller's result; the supported grammar is deliberately bounded. If port 8879 is occupied, stop here and inspect its owner. Do not replace an existing controller.

The overlay can be added as an OBS Browser Source at 1920 by 1080. That step changes your scene setup and is separate from the account-free rehearsal. The standalone stream agent does not itself control OBS.

## Connect a real Twitch channel

Follow [Twitch setup](docs/TWITCH-SETUP.md), then [EventSub transport](TWITCH-EVENTSUB-README.md). The initial test uses the broadcaster's own token, `user:read:chat`, and no rewards. Token values never belong in the repository or terminal history. A real channel requires operator authorization and an existing registered Twitch application. Local replay is not evidence that the real channel test passed.

The adapter maps exact allowed chat commands to fixed cues. It validates token identity and expiry, subscription identity and active WebSocket session; reconnects are bounded. Viewer text never becomes a prompt, overlay text or arbitrary executable action. It cannot post to chat or start a stream.

## Native OBS and voice

[Native program controls](PROGRAM-README.md) use a separate local controller on 8878 and an owned OBS profile/collection. Install `requirements-live.txt` for that optional route. Program control starts disabled and must be enabled deliberately through the local controller. It never starts or stops streaming, recording or the virtual camera. Actual active-stream behavior has not been proven by the historical outputs-off tests.

[Local voice](STREAM-AGENT-README.md) additionally requires `whisper-cli`, a compatible local model configured through `STREAM_WHISPER_MODEL`, and browser microphone permission. The account-free rehearsal does not require these. Local synthetic-audio proof is separate from real-microphone proof.

## Read more

- [Vision](docs/VISION.md) and [requirements](docs/PRD.md)
- [Original show authoring and rehearsal](docs/ORIGINAL-POC.md)
- [Judge routes and evidence boundaries](JUDGE.md)
- [Build history and Codex threads](docs/BUILD-HISTORY.md)

Current limits: fixed cues and separate controllers; no continuous OpenAI voice conversation, generated arbitrary animations, native Twitch polls or verified Channel Points entitlement. Real Twitch chat delivery through the replacement transport and a rendered browser overlay were verified on 29 October. Stranger usability, active OBS output and the final submitted video remain separate evidence.

## Codex build attribution

Codex session: `01a187b1-4ce5-7a93-99a2-c656faae194c`.

Transport rebuilt in this Codex thread on 29 Oct from a written spec; an earlier prototype existed, and the OBS director core was built in other Codex threads.

## What a viewer types

| Twitch chat command | Fixed overlay action |
|---|---|
| `!overlay party` | Emoji burst |
| `!overlay hydrate` | Popup saying `Hydrate!` |
| `!overlay clear` | Clear the current graphics |

Other viewer text is ignored by the transport. Chat forwarding starts off and requires deliberate enabling.

## Project dates and license

The project development commits were created 27–29 October 2026, inside the 23 October–2 November submission window. Both author and committer dates were checked. The source is provided under the [MIT License](LICENSE).
