Owned OBS program control, 27 Oct

This branch adds actual program-screen scene selection and source animation,
beyond the prior preview-only prototype. It never starts/stops stream, record,
or virtualcamera. Actual proof is entirely outputsOFF; the active-output branch
is exercised with explicitly fake OBS status replies in test_program_control.py.

Run with AGENTIC_OBS_PORT=8878 only. HTTP binds127.0.0.1. MCP checks8878 and build
native-program-27oct before mutations. OBS identity is the exact dedicated profile
and collection Agentic OBS Program27Oct (actual name has spaces before27Oct).
Each scene has a separate source and pinned loopback URL: scene-speaker.html,
scene-focus.html, scene-break.html. Camera/device capture is not configured.

Program control defaults OFF in each service process. Deliberately enable with
the local controller UI. No enable tool or endpoint is exposed to MCP or voice.
The browser route checks local Origin; this is an interface boundary, not human-only
security against an agent with full OS/browser access. Initial enable requires all
outputsOFF. Enable checks all owned source
kinds, URLs and scene membership and binds to this service session/profile/
collection. It is never persisted. Disable immediately drops authorization.
A profile/collection mismatch disarms program control. Program operations and
active-output transforms require enable; setup/sourcecreation always require
all outputsOFF. No arbitrary OBS methods are accepted.

Commands: program speaker/focus/break; undo program; play program preset toast.
Preview controls and prior save/replay data-only presets remain available.
Voice final cues 'Director, program break.' use localWhisper→officialMCP. Voice
cannot enable program control. Pause blocks future native commands, not current
motion. Durations200–2000ms are requested timing, not walltime guarantees.

Scene and transform mutations recheck exact profile, collection, sourcekind,
URL and sceneitem ID. The narrow capability exposes no Start/Stop outputs,
profile switching, arbitraryfile/network paths or executable animation code.
Program scene switches use SetCurrentProgramScene (cut); no stream initiation.

Restore original Untitled profile/collection, LIVESTREAM preview/program and
Studio ModeON; disable authenticated OBSWebSocket server after proof. During
proof the stock OBS server listens wildcard4455; our client only127.0.0.1.
Private credentials stay in ignored .obs-private.json0600 and original backups.
No embedded LLM or live microphone hardware proof is claimed.
