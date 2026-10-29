# Agentic OBS: offline rehearsal and Grill Me

Use this route to review the whole bounded interaction without a Twitch account, microphone, native OBS, browser automation or model provider.

## Reproduce

Use Python 3.12 with `websockets==15.0.1`. Initial dependency installation needs network access; the rehearsal itself only connects to its three owned loopback ports.

```sh
python3.12 -m pip install 'websockets==15.0.1'
python3.12 offline_workshop.py demo --out /absolute/new/proof-directory
```

Choose a new output directory. The controller binds the dedicated rehearsal port 8881; it must be free. Fake Twitch services choose unused ephemeral ports. All owned services shut down after the run. An occupied controller port fails before any connection to it; existing controllers and live OBS are untouched. The command fails if its observations differ from the expected sequence.

Read `proof.json`: a fixed party cue, a hydration reward, clear after reconnect, hydration after a new session, then a synthetic voice-route caption. The actual stream-agent controller receives HTTP requests, validates actions and publishes them to a real HTTP SSE reader. Inspect duplicate and wrong-channel rejection, reconnect without redundant subscriptions, fresh-session subscriptions and final inputs off. The command also attempts a forbidden non-owned connection and verifies that the local network boundary rejects it before connection.

This proves functional controller/event-feed behavior. It does not show rendered graphics, OBS frames, viewer latency, audio recognition, live Twitch delivery or reward eligibility. Synthetic reward text never becomes an arbitrary tool prompt. The overlay labels this input as CHAT CUE; the fake service remains clearly identified in the rehearsal evidence. Rules planning is used; Codex planning is disabled and no model is called.

## Grill Me

```sh
python3.12 offline_workshop.py grill
```

One question appears at a time. Answer in the terminal, then inspect the follow-up and evidence prompt. Type `stop` to pause. Answers are not saved or sent. `grill --list` prints the questions for the existing review panel; no answers, ratings or user research are invented.

The workshop covers the day-two user, entertaining viewer interaction, prior art, actual Codex contribution, evidence boundaries, failure recovery, judge setup and visual readability. It is a structured discussion, not an automated judge.

## Rules and remaining work

The [official rules](https://twitchcon-codex.devpost.com/rules), read 28 October 2026, require work created during the submission period, an interactive Twitch connection, judging access to code and run instructions, a Codex build-session ID, and a public YouTube demonstration of Twitch functionality and Codex build footage. They permit a private repository shared as specified. Submission closes 2 November at 14:00 PST, or 23:00 Paris. Innovation, impact, implementation and design are equally weighted.

The separate real-channel test verified chat delivery and a rendered browser overlay on 29 October; it does not change the synthetic nature of this rehearsal. Microphone performance, public video access and participant eligibility remain separate checks. Registration is not submission.
