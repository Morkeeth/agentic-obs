# Product requirements

Vision: Direct a Twitch show through speech and prompts while keeping the streamer in control of the picture.

Personas: A solo streamer is the operator; viewers participate through chat; a judge installs and reproduces a labelled demonstration.

Stack: Python, local HTML/CSS/JavaScript overlays, OBS WebSocket and MCP controls, local whisper.cpp transcription, Twitch EventSub WebSockets and Helix subscription requests. Codex was used for development. Its experimental runtime planner remains disabled pending verified tool isolation; the current live path uses deterministic rules.

## Whole flow

1. The streamer opens a local controller and chooses a segment.
2. They describe or revise its display, preview the result, and deliberately enable the owned OBS workspace.
3. They run the segment and invite viewers to use one discoverable chat cue.
4. Twitch delivers the event; an allowed command maps to a fixed graphic. Ordinary conversation does nothing.
5. The streamer changes or clears the graphic, restores the show and saves a reusable segment.

This is the target flow. The existing authoring, overlay and native-control paths have separate controllers; their consolidation into one user journey is unfinished.

## Current acceptance requirements

- Typed cues produce the documented overlay actions in a browser.
- Local audio transcription reaches the same validation boundary. Synthetic speech evidence and real microphone evidence are labelled separately.
- Native OBS changes are restricted to the owned workspace, scenes and sources; program control starts disabled and is deliberately enabled locally.
- Chat uses `user:read:chat` only for the first real test, with no rewards or native polls required.
- One actual Twitch chat command produces one fixed cue in the overlay, with event identity, trace and visible screenshot evidence.
- Repeated, stale, wrong-channel and wrong-subscription events cannot repeat a cue. Disconnects and revoked authorization are visible and forwarding stops.
- Turning inputs off cancels pending work where implemented; it does not promise to interrupt a native animation already executing.
- A clean clone runs the account-free rehearsal with documented dependencies.

## Trust and limits

Viewer text never becomes a prompt, overlay text, shell input or arbitrary OBS command. Unknown chat commands do nothing. Channel Points, arbitrary asset generation, continuous OpenAI voice, native Twitch polls and full conversational revision are not implemented in the tested live path. They remain product directions rather than advertised completion.

No stream, recording or virtual camera is started or stopped by this product. No public push, upload or submission is automatic. Tokens remain in the operating-system credential store and process memory, never the repository or trace.

## Success evidence

Record the actual Twitch event reaching the permitted overlay action and screenshot. Observe an ordinary message doing nothing, the command creating its cue, and disable preventing another cue. Record command-to-screen timing from the same observation before publishing a latency claim. The public video must show actual Twitch behavior and actual Codex build footage in under three minutes.

Measure stranger setup and the creator's second-session reuse separately. No interviews, external users or demand measurements have been established yet.
