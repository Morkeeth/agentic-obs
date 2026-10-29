# Local transport rebuild

`twitch_eventsub.py` is new code written in this Codex thread from REBUILD-SPEC.md, README.md and black-box failure output, replacing the absent earlier Claude prototype. No earlier implementation was inspected, copied or relabelled. Acceptance tests, fake server and replay source were neither read nor modified. No files outside this workspace were inspected. Inherited controller/harness components were not authored here. No other agents, live services, credentials, OAuth flows, UI, paid providers or publication were used.

Validation (all commands use `.venv/bin/python`):

- Missing-module baseline: `-m unittest test_twitch_eventsub test_mock_eventsub test_mock_transport test_stream_agent`; failed importing the missing module, 51 tests reported. Saved as `baseline-missing-module.txt` before implementation.
- Final acceptance: same command; 64 tests pass (`acceptance-results.txt`).
- Transport checks: `-m unittest test_twitch_eventsub -v`; 14 tests pass (`transport-results.txt`).
- Independent checks: `-m unittest test_rebuild_independent -v`; six tests pass (`independent-results.txt`). These cover bounded storage, reconnect-query privacy, fixed reward values, controller build refusal, HTTP redirect refusal and cancellation cleanup.
- Offline replay: `offline_workshop.py demo --out proof-rebuild-final`; PASS, four fixed-cue deliveries, five overlay events and zero model calls (`replay-results.txt`, `proof-rebuild-final/proof.json`).
- `-m py_compile twitch_eventsub.py test_rebuild_independent.py` and `git diff --check` pass.

Implementation covers token identity/scope/expiry validation, idle revalidation, subscription registration, bounded deduplication and receipts, fixed cue filtering, default-off forwarding, reconnect transfer, bounded fresh sessions, fatal-close/revocation stops, redirect refusal and cancellation cleanup. The controller gate checks the supported `stream-agent-27oct` build, rules planner and disabled Codex with zero calls.

Known contract discrepancy: the spec names the loopback validation path `/validate`, but the immutable fake server returns HTTP 401 there and accepts `/oauth2/validate`. `offline_endpoints().validate` therefore uses `/oauth2/validate` for compatibility with the required acceptance and replay. Explicit endpoint objects still use their supplied validation URL. No validation bypass or retry with alternate credentials was added.

At the original rebuild checkpoint, the checks were offline only. Subsequent actual Twitch authorization, delivery and browser-overlay rendering are recorded in [the redacted live receipt](evidence/twitch-live-29oct.json). Reward entitlement, active broadcast output, real microphone performance and participant eligibility remain unproved by these checks. The supported controller gate remains bounded to the inspected build.
