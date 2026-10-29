# Real Twitch EventSub transport

`twitch_eventsub.py` connects the stream agent to real Twitch chat and channel-point rewards over EventSub WebSockets. Viewer messages can only trigger the fixed overlay cues already in the stream agent; their text never becomes a prompt, overlay text, tool or command.

## What it does

1. Validates the user token at `https://id.twitch.tv/oauth2/validate` before connecting and again every hour. It stops if the client ID, user or scopes do not match (`user:read:chat`; plus `channel:read:redemptions` or `channel:manage:redemptions` when rewards are configured, which also needs the broadcaster's own token).
2. Connects to `wss://eventsub.wss.twitch.tv/ws` and, on the welcome message, creates `channel.chat.message` (and, if configured, `channel.channel_points_custom_reward_redemption.add`) subscriptions through Helix, inside Twitch's 10-second window.
3. Never sends application data on the socket (Twitch closes such connections with 4001).
4. On `session_reconnect`, opens the new URL (Twitch host only) and closes the old socket after the new welcome. Subscriptions carry over, so it does not subscribe again.
5. If keepalives stop or the connection drops, it opens a fresh session and subscribes again, up to three sessions with backoff. Events sent while disconnected are lost, as Twitch documents. Close codes 4001, 4002, 4003, 4004 and 4007, a revoked subscription or a failed revalidation stop it.
6. Sends a fixed cue to the local stream agent (`http://127.0.0.1:8879/chat-sim`) only after checking that the agent runs the rules planner with Codex off. The transport forwarding gate ends off whenever it stops. The controller chat toggle is independent and remains operator-owned.

## Run it

- Offline proof, no account: `python3 -m unittest test_twitch_eventsub -v`, then `python3 replay_twitch_eventsub.py /new/proof-dir`. Uses a local fake Twitch on 127.0.0.1:8883 (WebSocket) and 8884 (validate and Helix).
- Plan only: `python3 twitch_eventsub.py --config twitch.json` prints what it would subscribe to and connects to nothing.
- Live: `python3 twitch_eventsub.py --config twitch.json --live --enable-events` (provide `TWITCH_USER_TOKEN` through a private environment, never a checked-in file or command-history literal), with the stream agent already running and its chat input switched on. `twitch.json` holds `client_id`, `broadcaster_user_id`, `reader_user_id` and `rewards` (reward ID to one of the fixed cues).

## Verified live scope and remaining limits

- Real user authorization, a chat-only EventSub subscription, fixed-cue delivery and a rendered browser overlay were verified on 29 October. See the [redacted live receipt](docs/evidence/twitch-live-29oct.json). New users still authorize their own Twitch account.
- Channel-point rewards need an Affiliate or Partner channel.
- The current source labels a permitted input as `CHAT CUE`, because either the separate real receiver or a local test can feed it. Historical video footage retains the older label and explains it.
- Tests cover the shapes the code reads, not every optional field in Twitch's schema.

## Additional local checks, 29 October

Transport forwarding defaults off even after connecting; `--enable-events` is separate from `--live`.
Notifications must match the actual created subscription ID, type/version, reader, broadcaster, and active
WebSocket session. A replacement socket must welcome before it can deliver cues. HTTP and WebSocket
redirects are refused; reconnect URLs retain the expected host, scheme and port. Opaque reconnect queries
are not written to traces. Token revalidation also runs on idle sockets and honors earlier token expiry.

`python3 replay_twitch_owned_overlay.py /new/unused/proof-dir` runs the production adapter over actual
loopback HTTP/WebSockets into the owned rules-only overlay controller. Ports8881,8883,8884 must be free.
It verifies accepted overlay actions through the controller event log, then turns its input off and stops
its owned service. No browser/GUI, capture, native OBS call, account or live Twitch connection is used.
This is backend action evidence, not evidence of painted frames, Twitch delivery or judging eligibility.
