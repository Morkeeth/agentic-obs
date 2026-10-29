# Twitch setup for the first channel test

Checked against Twitch documentation on 29 October 2026. Use the streamer's own account as reader and broadcaster. Request only `user:read:chat`; configure no rewards. No broadcast or chat post is needed to authorize and read chat, but the final submission video must show the project functioning on Twitch.

Register the application in the Twitch developer console after email verification and two-factor authentication. A Client ID is public; client secrets and tokens are not. For a Public client use Twitch's device authorization flow. Twitch's documented Public-client restrictions do not permit the implicit grant link from the earlier setup draft. An implicit grant requires a compatible app client configuration instead.


The local `twitch.json` contains Client ID, numeric broadcaster/reader IDs and an empty rewards object. It contains no token and is ignored by git. Resolve IDs from Twitch after receiving the actual username; do not invent them.

Live-test sequence: confirm no existing controller will be replaced; start the owned stream agent with rules and Codex disabled; enable its chat input; start `twitch_eventsub.py --config twitch.json --live --enable-events` with the authorized token supplied through the process environment; have the operator enter an allowed command in their own Twitch chat; inspect the trace, controller event and rendered overlay. Then disable the input and stop only owned processes. Save token-free trace and screenshot. The existing CLI prints only its final trace entries on normal exit; capture full trace from the adapter rather than claiming those entries show the entire test.

Sources: [registration](https://dev.twitch.tv/docs/authentication/register-app/), [device flow](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#device-code-grant-flow), [EventSub WebSockets](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).
