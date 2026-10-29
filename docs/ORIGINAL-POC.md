# Agentic OBS — exploratory rehearsal prototype

**[Start with the local judge guide](../JUDGE.md).** It distinguishes the original show rehearsal, stream-agent overlay and synthetic Twitch-event experiment, with a no-account verification path. This project has not established a public source or completed Twitch integration.

New local Python/HTML/CSS/JavaScript, authored in Codex session `01a17c79-75a3-7a00-9644-8f6b772245cf` on27October2026. No prior product code, third-party frontend package, external asset, paid API or model call. This is an exploratory interaction proof, not a finished Twitch integration or admitted hackathon submission.

Run `python3 server.py`, then visit `http://127.0.0.1:8873/`.

The running detached process ID is in SERVER.pid; server.log contains its stdout. Bound to127.0.0.1 only. All content and actions remain local. The API rejects cross-origin action requests. Stop only this exact PID when no longer needed.

## Try it

Choose Toast / Forecast / Mission. Create or revise a brief. The local rule parser recognises those3looks, camera left/right, numeric countdown, `Reveal: ...`, quiet/playful motion and `Hold reveal for8seconds`. This is deliberately narrow; it does not understand arbitrary visual requests. The draft changes; the program stays untouched. Rehearse the timed setup/countdown/reveal/return, then Take locally to change the local program. Restore recovers its previous show and clock. Save and load show definitions; saved shows survive server restarts. Restart starts on the normal local program rather than automatically taking an old segment.

Examples:
- Late-night science show. Camera left.12second countdown. Reveal: TOAST ACHIEVED. Keep movement quiet.
- Weather report. Camera right.9second countdown. Reveal:80% CHANCE OF SKILL ISSUE. Make it playful.
- Space mission control. Camera left.15second countdown. Reveal: COFFEE HAS LANDED. Less movement.
- Revision: Camera left. Less movement. Hold reveal for8seconds.

## OBS boundary

`http://127.0.0.1:8873/overlay.html` is the working local Browser Source page. At1920×1080 its animated graphics surround a transparent opening for a separate OBS camera source underneath. It polls the local program state. The controller stage uses an explicit camera placeholder. No webcam was accessed.

OBS29.1.3 is installed. Port4455 had no listener at lane startup. This lane never launched OBS, enabled its websocket, read stream credentials, changed a profile/scene collection, connected Twitch or started a broadcast. OBS Browser Source compatibility follows documented web-source architecture; actual OBS rendering and Twitch output remain unverified. No adapter/control code was shipped pretending otherwise.

## Proof

WORKFLOW-VERIFICATION.json records the real HTTP workflow, independent draft/program states, exact restore, saved-show restart persistence and rejected invalid/cross-origin actions. Actual CUA clickthrough screenshots01–08show the interface and weather revision/payoff/take/restore. The24second MP4 and GIF are step flipbooks built from those screenshots, not continuous screen recordings. They are silent. FLIPBOOK-QA.json pins exact hashes and full decode.

## Remaining product questions

The next product proof is replacing the narrow parser with real Codex-assisted show authoring, measuring time to a usable unseen segment, and demonstrating controlled OBS/Twitch output. Generic prompt overlays and OBS automation already exist; novelty remains UNCLEAR. Whole-segment revision/rehearsal/return is a proposed distinction, not a measured advantage. This prototype does not establish hackathon eligibility or superiority to MeldSpark/aq.chat/OBSShowrunner.
