# Judge guide

Start with the single setup path in [README.md](README.md#run-the-account-free-rehearsal). It installs one pinned dependency, runs the acceptance tests and starts an owned account-free rehearsal. No Twitch account, microphone or OBS installation is needed for that rehearsal.

Public source: https://github.com/Morkeeth/agentic-obs

## Evidence boundaries

- Real Twitch chat authorization, EventSub delivery and a rendered browser-overlay cue were verified on 29 October. The [redacted live receipt](docs/evidence/twitch-live-29oct.json) contains no credentials or numeric account identifiers.
- The no-account rehearsal uses fake Twitch and synthetic transcript input. It verifies controller and event-feed behavior, separately from that real-channel test.
- A separate native OBS connector has historical outputs-off evidence. The real-channel browser-overlay capture does not establish an active OBS broadcast or real microphone recognition.
- Full conversational creation, native Twitch polls and reward entitlement are not claimed by the tested path.

For real chat setup, use [Twitch setup](docs/TWITCH-SETUP.md) and [the transport guide](TWITCH-EVENTSUB-README.md). Start the stream-agent controller on port 8879 only when that port is free. All inputs start off; enable chat deliberately. Native OBS control is an optional separate route in [PROGRAM-README.md](PROGRAM-README.md).

## Build dates and attribution

Project development commits were created 27–29 October 2026, within the 23 October–2 November submission window. Both author and committer dates were inspected. This is a source-history check, not an assertion of participant eligibility or completed submission. See [build history](docs/BUILD-HISTORY.md).
