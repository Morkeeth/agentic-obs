Native OBS prototype, 27 Oct

This branch adds actual OBS preview scene selection and source transforms to the
previous overlay connector. Native preview is a separate capability from overlay
content. Program output and streaming/recording/virtual camera are never started.
It is an intermediate native-control experiment for real-time show direction.

Run only with explicit AGENTIC_OBS_PORT=8877. MCP checks connector port and build
identity before sending mutations. Native adapter rejects other ports, profiles,
collections, sources, URLs, arbitrary OBS methods and active outputs. Only Studio
Mode preview is changed. Its three own scenes contain dedicated loopback Browser
Sources; the focus scene changes native source scale/position.

Commands: preview speaker/focus/break; save preset NAME with MOTION 500ms;
play preset NAME; pause native; resume native; undo preview.
MOTION is slide left, slide right, lift or pulse; duration200–2000ms.
Presets are validated records, not executable code, persisted atomically in
ignored .native-presets.json mode0600 and reused across fresh processes.
Animation moves/scales the actual OBS source, then returns to its starting point.
Commands are bounded grammar, not general model-generated animation code.

Voice: explicit final 'Director, preview break.' or 'Director, play preset toast.'
uses existing local Whisper→official MCP transcript→native command path.
Ordinary speech/interim/duplicates and paused automation preserve native scenes.
The UI has independent native pause/resume and overlay pause controls.
Live microphone hardware/permission remains untested; proof uses synthetic TTS.

Native profile/collection Agentic OBS Realtime27Oct (actual name has spaces before
27Oct), own scenes Agentic RT Speaker/Focus/Break. Native HTTP service8877 binds
loopback. OBS4455 authentication remains enabled, but OBS's server listens on a
wildcard interface during proof. Disable it after proof and select original
Untitled profile/collection with LIVESTREAM preview/program, StudioModeON.
Original configuration is privately backed up; do not overwrite live configfiles.
No paid services or heavy media render is needed.

Animation positions are clamped to the validated preview bounds. Native pause
blocks future commands; it does not interrupt the current at-most2second animation.
