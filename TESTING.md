# Testing the source candidate

Use Node 22+; the runner checks its actual version and structuredClone capability.
Follow [README setup](README.md#account-free-setup-and-rehearsal) in a new clone
and isolated `.venv`, installing its public requirements. No development `.pth`,
PYTHONPATH loan, global install or account is part of the supported cold proof.
Reconstruct `fork-src` before running the tests. The README publishes the UTF-8
locale; the runner also normalizes a missing LANG in the test process only.
`--locale-check` exercises a real child with the repaired locale and no services. New destination/output paths
refuse reuse; existing user trees/listeners are never reset, killed or replaced.

`tools/check_package.py --history` verifies the manifest inventory/hashes/modes,
all eleven protected original hashes, local documentation links, required local
imports, heuristic privacy/secret patterns and reachable public candidate history.
The history must contain exactly one clean curated root commit. The existing
public baseline is a provenance input, not inherited history; no build/fork or
earlier session history is imported. Heuristics are not a guarantee
that arbitrary future changes contain no secrets. Only selected public files and
objects are inspected, not ignored operator data.

`tools/rehearse.py` verifies actual reconstructed fork/browser source blobs/modes,
runs every `test*.py` module (including original70/native15 and bundle-closure
boundary tests), then all `test_director*.mjs`. Required source tests are not
skipped. The only compiled-artifact exclusion is the exact full test ID
`test_director_browser_probe.ArtifactIdentity.test_built_bundle_metadata_accepts_matching_fake_process_without_signal`,
reported **NOT RUN** until both native app variants have been built. Its two exact
owned bundle ID assertions and all process/path/review rules remain intact.
The location-only director test adjustment replaces that test's absolute fork
root with `Path(__file__).resolve().parent/'fork-src'`. Frozen blob/hash and staged
hash plus reason are recorded in the manifest. The NON-protected `test_director_bank_renderer.mjs` is repaired in the frozen
source itself, not transformed during export. It verifies actual owned immutable
base URLs/static titles/settings/item identity and enabled states, unchanged
program/geometry during preview, disabled empty active Graphics, distinct mutable
bank payloads, correct revealed graphics on Take, title DOM identity, exact ACK and
warm epoch. A hidden source's retained DOM/texture is not program pixel proof.
Its previous and current source hashes are retained as test provenance. All
other director source/assets, including every protected transport/harness file,
are byte-for-byte frozen; the only export-time source change is the artifact root
locator described above.

The fixed-page Node test takes a required source argument. Do not use a no-argument
loop for every Node test. The rehearsal supplies exactly:

```sh
node test_director_managed_media.mjs fork-src/frontend/widgets/DirectorMediaPage.inc
```

Other `test_director*.mjs` receive no extra argument. These tests inject DOM,
WebRTC, ICE, device/permission and renderer effects; no WebKit/browser/native audio
process is created. They prove script/state rules, not GPU, ASR or physical audio.

The rehearsal also runs `director_exercise.py --simulate` for 30 scene/geometry
cycles, 10 composition journeys and three persistent-mode checks, plus
`offline_workshop.py demo` for legacy local HTTP/SSE behavior. This is simulated
OBS and synthetic text, not a native trial or microphone test. Fixture HTTP/MCP
services use owned loopback ports and stop in teardown; legacy rehearsal uses
8881. Generated results go to ignored `.source-package-evidence/`; never publish
operator logs, profile/auth files or screenshots with private content.

After a separately authorized native build, run the unchanged actual artifact
assertions and static production closure checker explicitly:

```sh
.venv/bin/python -m unittest test_director_browser_probe.ArtifactIdentity -v
.venv/bin/python director_bundle_closure.py fork-src/build_macos/frontend/RelWithDebInfo/OBS.app fork-src/build_director_browser/frontend/RelWithDebInfo/OBS.app
```

The checker audits actual Mach-O load commands, per-image rpaths and resident
private dependencies without loading the app or using ambient DYLD/SDK fallbacks.
Its three boundary tests run in the account-free suite. Actual artifact closure
and Qt offscreen tests are **NOT RUN in the source-only cold clone**. Earlier
frozen-source cached builds/offscreen suites and closure scans passed; that does
not prove native startup, account/microphone/ASR/WebKit behavior, physical teardown,
painted pixels or renderer crash containment. Expanded live Twitch delivery also
remains unverified. No model, Twitch, native build or device trial belongs to the
cold rehearsal. Fully hands-free privileged approval is OPEN; each exact spoken
Take requires a fresh local human arm.
