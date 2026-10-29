# Agentic OBS

A solo streamer should be able to direct a show while staying in the conversation. Say what belongs on screen, refine it aloud, let viewers participate, and reuse the result next stream.

The intended product brings the video-editing conversation into a live broadcast: create a graphic, change its position and motion, rehearse it, take it to OBS, then restore the show. Twitch chat becomes a participant in the segment. The streamer decides what viewers can trigger.

The first user is a solo creator doing a talk, science, coding or variety stream without a producer. The recurring moment is a good idea arriving while they are already talking. They should not need to stop the show to configure several tools.

Success on stream means a viewer understands how to participate, their permitted cue visibly lands, and the streamer can revise or clear the output without losing the thread. Next stream, the creator opens the saved segment and runs it again. Outside-user demand remains unmeasured.

The current prototype contains local show authoring, bounded voice-to-overlay cues, native OBS controls and a Twitch EventSub adapter. These paths are not yet a single continuous agent conversation. Live Twitch delivery and live microphone performance must be demonstrated before being claimed.

The distinction to prove is creating and revising an interactive segment during the show. Voice-triggered scene switching already exists. More commands alone do not establish a new product.

Viewer text never becomes a model prompt, executable action or displayed free text. Viewers trigger permitted fixed cues; the streamer owns creative changes. The director never starts a broadcast, recording or virtual camera.
