# The Twitch project story

This project is intended to let a streamer direct a live explanation while
retaining the decision about what reaches the program.

The authored visual flow is:
streamer direction -> Codex composition -> native preview -> operator approval -> OBS program.
The trusted external Codex client can turn selected reference data into a new
validated composition made of text, rectangles and circles, explain a brief plan,
and revise the draft. The native preview and the program are separate. Renderer
acknowledgments and OBS readbacks do not prove that the intended pixels appeared.
The operator reviews the exact revision before approving an agent take.

The audience flow is:
Twitch chat -> validated request -> streamer decision -> fixed visual.
The receiver inherits the original transport's session, channel, subscription,
reader, timestamp and duplicate checks. Chat goes into a bounded temporary human
inbox. The streamer selects a fixed intent and accepts one exact request.
Viewer text does not author graphics or become a model prompt. A fixed request
approval does not grant permission for an arbitrary authored take.

Camera-layout undo is separate from whole-show recovery. Live source ownership,
explicit arming, fresh graphics-bank readiness and fail-closed recovery remain
part of the intended workflow. Local voice grammar and a trusted external client
are different interfaces; neither is proof of physical microphone performance.

Implementation tests use simulated OBS protocol, simulated DOM behavior and
local tool integration. Actual external page loading, physical camera capture,
voice recognition, model-authored explanations and rendered pixels require
independent operator acceptance. This story reports no usage counts, audience
metrics, participant details, external research or API entitlements.
