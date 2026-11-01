# License and provenance map

- Root [LICENSE](LICENSE): MIT from the existing public project baseline
  `d5033023a4d09e031a188a6cae96463a51bcee83`; applies to the Python project and
  new packaging helpers, subject to retained per-file notices.
- Imported native OBS Python core, supporting web/voice files and regressions
  came from that public baseline and were built in other Codex threads. The
  replacement Twitch transport was independently rebuilt here from a written
  spec on29Oct; an earlier prototype existed. No private thread IDs are needed
  to describe that attribution.
- `packaging/obs-director.patch` and its reconstructed OBS source are GPL-covered,
  **not MIT**. [OBS GPL text](LICENSES/OBS-COPYING.txt) is copied unchanged from
  official OBS33.0.1. All upstream copyrights and per-file licensing exceptions
  remain in the exact reconstructed source. Earlier branding/isolation spike
  commit `b2fb28e4ffe418995bac7e11aae4290b112f21da` is included honestly; expanded
  Director changes build on it rather than relabel it.
- `packaging/obs-browser-director.patch` retains the browser project's copyright
  and [GPL text](LICENSES/BROWSER-COPYING.txt). It reproduces only the helper bundle
  identity/display-name delta against the official pinned browser source.
- CEF/Chromium, Qt and OBS dependencies are not distributed in this candidate.
  Preserve their original notices/licenses from the checksum-pinned upstream
  source/dependency archives when reconstructing or later distributing binaries.
  This map does not relicense vendor source or binaries or grant extra rights.

No built app/framework, cache, private config, authentication, session trace or
raw local evidence is included. Exact source/tree/patch hashes are in the
[manifest](packaging/source-manifest.json). See [build instructions](SOURCE-BUILD.md).
