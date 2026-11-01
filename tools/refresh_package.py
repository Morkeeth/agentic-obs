#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Refresh reviewed public source inventory; preserve fork and protected pins.

Uses the existing package manifest schema and verifier. Run on a clean tracked
commit. Does not change runtime source, fork patches, history policy or checks.
New inventory is explicit: unknown tracked files are never silently admitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from check_package import verify

ADDITIONS = (
 'AGENTS.md', 'docs/images/director-workspace.png',
 'REALTIME-VOICE.md', 'director_realtime.py', 'director_web/voice-ptt.js',
 'director_web/voice.html', 'fixtures/realtime-tone.wav',
 'obs-websocket-loopback.patch', 'test_director_cold_budget.py',
 'test_director_dead_renderer.py', 'test_director_output_availability.py',
 'test_director_renderer_expiry.py', 'test_obs_fixture_ini.py',
 'test_obs_loopback.py', 'test_realtime_ptt.cjs', 'test_realtime_voice.py',
 'tools/check_obs_ini.c', 'tools/obs_fixture_ini.py', 'tools/refresh_package.py',
)

def git(root, *args):
 return subprocess.check_output(['git', *args], cwd=root)

def digest(data):
 return hashlib.sha256(data).hexdigest()

def refresh(root):
 root=Path(root).resolve()
 if git(root,'status','--porcelain','--untracked-files=no').strip():
  raise ValueError('Commit tracked source changes before refreshing')
 revision=git(root,'rev-parse','HEAD').decode().strip()
 path=root/'packaging/source-manifest.json'
 manifest=json.loads(path.read_text())
 baseline_digest=digest(path.read_bytes())
 if manifest['history_policy']!='curated-root-no-imported-history':
  raise ValueError('Single curated-root policy required')
 # Protected eleven-file checks compare immutable prior pins, not new hashes.
 for name, expected in manifest['protected_sha256'].items():
  if digest(git(root,'show',revision+':'+name))!=expected:
   raise ValueError('Protected source changed: '+name)
 for name, expected in manifest['patches'].items():
  if digest(git(root,'show',revision+':'+name))!=expected:
   raise ValueError('Fork patch changed: '+name)
 prior={k:manifest[k] for k in ('obs','browser','obs_files','browser_files','patches','protected_sha256','history_policy')}
 names=set(manifest['director_files'])|set(manifest['package_files'])|set(ADDITIONS)
 names.discard('packaging/source-manifest.json')
 source_names=set(manifest['director_files'])
 source_names.update(n for n in ADDITIONS if n.startswith('director_web/') or ('/' not in n and n.endswith(('.py','.mjs','.cjs'))))
 for name in sorted(names):
  record=git(root,'ls-tree',revision,'--',name).decode().strip()
  if not record:raise ValueError('Required public file not tracked: '+name)
  info=record.split('\t',1)[0].split();mode,kind,oid=info
  if kind!='blob' or mode not in ('100644','100755'):
   raise ValueError('Invalid public source type: '+name)
  data=git(root,'show',revision+':'+name)
  if (root/name).is_symlink() or (root/name).read_bytes()!=data:
   raise ValueError('Source differs from committed pin: '+name)
  if name in source_names:
   old=manifest['director_files'].get(name)
   entry={'frozen_blob':oid,'mode':mode,'frozen_sha256':digest(data),'staged_sha256':digest(data)}
   if old and old.get('packaging_only_adjustment'):
    entry['prior_packaging_only_adjustment']=old['packaging_only_adjustment']
   manifest['director_files'][name]=entry
  else:manifest['package_files'][name]=digest(data)
 manifest['refresh_provenance']={'previous_director_revision':manifest['director_revision'],'previous_manifest_sha256':baseline_digest,'source_revision':revision,'public_inventory':'prior inventory plus explicit ADDITIONS in tools/refresh_package.py; internal packet/repair notes excluded'}
 manifest['director_revision']=revision
 manifest['director_tree']=git(root,'rev-parse',revision+'^{tree}').decode().strip()
 assert prior=={k:manifest[k] for k in prior}
 path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
 return verify(root)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('root',nargs='?',type=Path,default=Path(__file__).resolve().parent.parent)
 args=parser.parse_args()
 print(json.dumps(refresh(args.root),sort_keys=True))
