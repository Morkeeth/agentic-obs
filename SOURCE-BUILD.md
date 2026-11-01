# Exact native source, without a private submodule dependency

The package uses official OBS tag33.0.1, commit
`65c320b46e1af5c7a555161aea6182cdf7a8c524`, and official obs-browser
`d4db73e7e5d5b51d853177c8cddc796715a8ac84`. Public upstream locations are
[obs-studio](https://github.com/obsproject/obs-studio) and
[obs-browser](https://github.com/obsproject/obs-browser).
The final frozen native source is `c6f336ca1e67a2e0521061f772e7d1a1465f2f59`;
browser source is `76993df759ea10ba10616ec4f11db01bc9cc4c5c`.
Those final local commits are provenance pins, **not fetch targets at upstream**.

`packaging/obs-director.patch` contains every fork modification since the genuine
OBS base, including earlier branding/isolation, binary-safe file/mode changes,
Widgets tests and output guards. It excludes only the browser gitlink change.
`packaging/obs-browser-director.patch` reproduces the two helper identity changes
against the public browser pin. No third public repository is required.
Upstream copyright, GPL, dependency notices, entitlements and production hardening
remain. Source pointers in the manifest distinguish this from license/remote proof.

## Explicit reconstruction, no build or launch

By default the bootstrap does not use network. With explicitly supplied available
local upstream object stores:

```sh
python3.12 tools/bootstrap_fork.py --destination fork-src --obs-objects /explicit/obs-object-store --browser-objects /explicit/browser-object-store
```

For a later public-source read, only this explicit option permits the two fixed
public Git fetches. This command was **not** executed against public remotes by
the packager:

```sh
python3.12 tools/bootstrap_fork.py --destination fork-src --fetch-public
```

The destination must be new. No reset/clean of an existing tree is performed.
Both patch checksums are verified before application. The bootstrap compares every
actual source file's Git blob and executable/symlink mode to the frozen trees.
Upstream Git-attribute CRLF normalization is reported separately; those canonical
Git blobs remain identical rather than rewriting Windows project files.
It verifies the exact browser tree and, in the new reconstruction index only,
proves the original superproject tree when its recorded custom gitlink is restored.
It then leaves the browser gitlink at the public upstream pin with the child
patch applied. It never fetches the unreachable custom child at upstream.

Other unchanged OBS submodules retain their exact upstream gitlinks. For a later
native build, fetch only those official public source modules explicitly:

```sh
git -C fork-src submodule update --init -- deps/libdshowcapture/src plugins/obs-websocket
```

Do not run a recursive update that discards the patched browser child. No native
build, CEF launch or device/account action occurred during local packaging.

## CEF and build preparation — not executed here

The pinned OBS dependency contract names official
`https://cdn-fastly.obsproject.com/downloads/cef_binary_7871_macos_arm64.tar.xz`,
SHA256 `0343233fc462384c2f1f58a4222028bc6171f05948a822241f89df2faa7cee8d`.
The archive/frameworks are not included. After deliberately obtaining that exact
public archive, an initial bootstrap can accept `--cef-archive /explicit/archive`:
it refuses a wrong hash before extraction into the new fork's ignored `.deps`.
Preserve the archive's own CEF/Chromium/dependency licenses; do not strip them from
any later binary distribution. OBS/Qt dependency versions/hashes remain pinned
in the reproduced CMakePresets. No dependency download/install is automatic here.

Once the separate public dependency prerequisites already exist, the reproduced
cached presets maintain an OFF baseline and a separate opt-in candidate:

```sh
cd fork-src
nice -n 15 cmake --preset director-cached-off
nice -n 15 cmake --build build_macos --config RelWithDebInfo --target obs-studio director-shell-test --parallel 2 -- CODE_SIGN_IDENTITY=-
nice -n 15 ctest --test-dir build_macos/frontend -C RelWithDebInfo -R '^director-shell$' -V
nice -n 15 cmake --preset director-cached-browser
nice -n 15 cmake --build build_director_browser --config RelWithDebInfo --target obs-studio director-shell-test --parallel 2 -- CODE_SIGN_IDENTITY=-
nice -n 15 ctest --test-dir build_director_browser/frontend -C RelWithDebInfo -R '^director-shell$' -V
```

These are staged instructions, not packaging-task build evidence. Earlier frozen
source passed both cached app/offscreen builds; native pixels/crash acceptance
is still unverified. Browser sources additionally require the exact local launch
flag `--director-browser-sources`, regardless of saved plugin settings. CEF docks
are excluded. Upstream CEF uses `no_sandbox=true`; no stronger OS sandbox or global
Codex isolation is claimed. Frontend start/benchmark refusals are not a universal
libobs/plugin output sandbox. Real native/account/device/renderer trials need a
separate authorization and outputs OFF; no launch is part of bootstrap.

The final source includes the production bundle-closure repair: obsolete PCM and
QtMultimedia are linked only by offline tests, while production managed voice uses
system WebKit. Never hot-copy a missing framework, set DYLD overrides or relax
signing/security to claim a fixed bundle. See [testing](TESTING.md) for the actual
closure tool and NOT RUN artifact checks in a source-only checkout. Both owned
identities remain distinct (`com.morkeeth.agentic-streamer` and its `.browser`
variant). Each exact spoken Take/approve requires a local human manual arm; ASR
is input, not identity. General creative voice remains implemented, but account,
physical mic/ASR, WebKit/native startup/pixels/crash acceptance is unverified.
