# Coding-agent instructions

## Start with the public package

Read README.md, TESTING.md, SOURCE-BUILD.md and packaging/source-manifest.json. Work in an isolated branch/worktree. Keep source-only judge rehearsal separate from optional native/device work. The public package has a deliberately curated root; do not push private consolidated history or raw Codex transcripts.

## Exact account-free setup and checks

Python 3.12, Git and Node 22+ are required. Start from a fresh checkout and use its own .venv. Run these README commands in order:

```sh
python3.12 --version && node -e 'require("node:assert")(Number(process.versions.node.split(".")[0]) >= 22, "Node 22+ required; fix PATH"); console.log("Node", process.version, process.execPath)'

python3.12 -m venv .venv
. .venv/bin/activate
python3 -c 'import sys; assert sys.prefix != sys.base_prefix and sys.version_info[:2] == (3, 12), "Activate the Python 3.12 venv first"; print("Venv Python:", sys.executable)'
env -i PATH=/usr/bin:/bin:/opt/homebrew/bin PIP_CONFIG_FILE=/dev/null .venv/bin/python -m pip --disable-pip-version-check --no-input --keyring-provider disabled install --index-url https://pypi.org/simple --only-binary=:all: --no-cache-dir -r requirements.txt -r requirements-live.txt
.venv/bin/python tools/check_package.py --history
.venv/bin/python tools/bootstrap_fork.py --destination fork-src --fetch-public
LANG=en_US.UTF-8 .venv/bin/python tools/rehearse.py --node "$(node -p 'process.execPath')"
```

The bootstrap destination must be new. If fork-src already exists, use a fresh isolated checkout; do not delete another task's working directory. The package check precedes upstream reconstruction and the rehearsal. Preserve original test rules, protected hashes and upstream pins. Never weaken a check or convert an actual rejection into a skip to make a run pass. A present native checker that rejects must still fail. Missing native prerequisites are explicit skips, not native passes.

For local operator inspection only, the README starts the controller with:

```sh
.venv/bin/python director_server.py --port 8880
```

Check port ownership first. Do not stop, replace or connect to another process. The operator explicitly connects, sets up and arms owned OBS; an agent must not do that merely to run tests.

## Extending the director

Use the existing validated composition and fixed-intent boundaries. Test malformed data, duplicate/replayed events, wrong identity/session, stale revisions, expiry and failed rendering as relevant to the change. Add a regression that fails on the old behavior, then run the complete account-free rehearsal. Distinguish simulated source checks from actual native pixels, audio and live Twitch acceptance in the result.

Preview is not program output. Manual Take remains deliberate. Agent Take needs exact human approval bound to the inspected revision. A model, viewer message or recognized voice is never authority to arm controls. Preserve the fresh human-click and short-lived, one-use approval checks for privileged spoken actions; never replay approval after a failure.

## Never do these automatically

- Start or stop a stream, recording or virtual camera; enable capture, microphone or audio devices; change a real show, OBS profile or scene collection.
- Enable audience forwarding, counters, API voice or managed-account voice; make provider calls, spend money, sign in or create accounts without separate authorization.
- Turn viewer text/URLs into prompts, source code, arbitrary overlays, material catalogs or executable actions. Keep audience content ephemeral and operator-only.
- Discover credentials automatically, print tokens, commit local config, private sessions, raw evidence or built binaries.
- Reset patched upstream source or recursively reset its browser submodule. Follow SOURCE-BUILD.md in a separate native checkout for optional checks.
- Push, deploy, upload or submit without explicit authorization. A green source-only rehearsal does not establish real voice, device teardown, renderer recovery or outside-user usability.

## Handoff

Report the changed files, the exact source revision and commands run, failures/skips, and what remains unverified. Preserve MIT/GPL attribution through LICENSE-MAP.md; Python MIT does not relicense OBS/browser code. If packaged source changes, have the package owner update its manifest through the reviewed refresh process before publication; do not bypass integrity checks.
