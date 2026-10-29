# Prior art and the distinction to prove

Read 29 October 2026 from the products' own documentation or sites. These are documented or advertised capabilities, not independently tested product behavior.

| Product | Existing job | Consequence for our pitch |
|---|---|---|
| [Streamer.bot](https://docs.streamer.bot/guide/core/voice-control) | Configured speech commands trigger actions; documented matching and recognition settings | Voice-triggered actions alone are established prior art |
| [StreamPal](https://getstreampal.com/) | Advertises voice control for OBS and other apps, configured/fuzzy command matching and event automation | Broad control coverage alone does not distinguish Agentic OBS |
| [strAImer](https://straimer.com/catalog/voice-control) | Advertises natural-language OBS scene switches, Twitch polls and other bounded actions | Adding natural wording or polls is not enough to claim a new category |

The proposed difference is live authoring and revision of the segment itself: create a graphic or voting display, refine its layout and motion in context, preview it, put it on air and reuse it. The current narrow parser and preset controls do not yet prove arbitrary conversational creation. No superiority or market demand is claimed.

The first compelling proof should be a coherent creative moment, not a catalogue of connectors. One possible future interaction: the streamer starts an impromptu prediction board, chat votes through permitted commands, the streamer says “move that above me, make the winning side celebrate, keep this for next week,” and the actual picture changes. A chat-vote overlay is a proposed implementation; it must not be labelled as a native Twitch poll. Native polls require Partner/Affiliate eligibility and `channel:manage:polls` according to [Twitch's API docs](https://dev.twitch.tv/docs/api/polls).

The OpenAI API documents a voice conversation with a separately chosen backend through [GPT-Live](https://developers.openai.com/api/docs/guides/live). That is a possible future implementation architecture, distinct from the current local Whisper/rules pipeline and from Codex being the development tool. No API access or model call has been established in this project.
