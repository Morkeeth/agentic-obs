#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local candidate integrity/privacy/relative-link checks. No remote reads."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit
from bootstrap_fork import git

PATTERNS=[rb'/Users/[A-Za-z0-9][A-Za-z0-9._-]*/',rb'/Volumes/[A-Za-z0-9]',rb'/\.local/state/fleet/',b'clean'+b'-codex-home',
          rb'[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}',
          rb'(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']

def verify(root):
    root=Path(root).resolve();manifest=json.loads((root/'packaging/source-manifest.json').read_text())
    errors=[];checked=0
    required={'README.md','TESTING.md','SOURCE-BUILD.md','LICENSE-MAP.md','LICENSE',
              'LICENSES/OBS-COPYING.txt','LICENSES/BROWSER-COPYING.txt','requirements.txt','requirements-live.txt',
              'director.py','director_server.py','director_mcp.py','director_bundle_closure.py','test_bundle_closure.py',
              'director_web/index.html','director_web/render.js','test_director_managed_media.mjs',
              'tools/bootstrap_fork.py','tools/check_package.py','tools/rehearse.py',
              'packaging/obs-director.patch','packaging/obs-browser-director.patch'}
    # Only manifest-owned public content, not local evidence/venvs/reconstructed repositories.
    names=set(manifest['director_files'])|set(manifest['package_files'])|{'packaging/source-manifest.json'}
    if not required<=names:errors.append("required source inventory incomplete")
    for name in sorted(names):
        path=root/name
        if not path.is_file() or path.is_symlink():errors.append('missing/invalid file: '+name);continue
        data=path.read_bytes();checked+=1
        mode='100755' if path.stat().st_mode & 0o100 else '100644'
        entry=manifest['director_files'].get(name)
        if entry and mode!=entry['mode']:errors.append('mode: '+name)
        # Only package/runtime imports are checked; protected harness remains opaque.
        if path.suffix=='.py' and name not in manifest['protected_sha256']:
            for node in ast.walk(ast.parse(data)):
                modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
                for module in modules:
                    local=module.split('.')[0]
                    if local.startswith(('director','stream_','live_','test_')) and not (root/(local+'.py')).is_file():
                        errors.append('missing local import '+local+' in '+name)
        digest=entry['staged_sha256'] if entry else manifest['package_files'].get(name)
        if digest and hashlib.sha256(data).hexdigest()!=digest:errors.append('hash: '+name)
        for pattern in PATTERNS:
            if re.search(pattern,data,re.I):errors.append('privacy pattern in '+name);break
        if path.suffix=='.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',data.decode()):
                target=target.strip('<>').split('#',1)[0]
                if not target or urlsplit(target).scheme:continue
                if not (path.parent/unquote(target)).is_file():errors.append('relative link in '+name)
    for name,digest in manifest['protected_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:errors.append('protected hash: '+name)
    if errors:raise ValueError('; '.join(errors))
    return {'checked_public_files':checked,'protected_files':len(manifest['protected_sha256']),
            'privacy_patterns':'pass (heuristic, not a secret audit guarantee)','relative_links':'pass',
            'public_remote_verified':False}


def history(root):
    root=Path(root).resolve()
    manifest=json.loads((root/'packaging/source-manifest.json').read_text())
    commits=git(root,'rev-list','HEAD').decode().splitlines()
    if manifest.get('history_policy')!='curated-root-no-imported-history':raise ValueError('Unreviewed history policy')
    if len(commits)!=1 or len(git(root,'rev-list','--parents','-n','1','HEAD').split())!=1:
        raise ValueError('Expected one curated root; no imported public-baseline or development history')
    checked=0;issues=[]
    for record in git(root,'rev-list','--objects','HEAD').splitlines():
        oid=record.split(b' ',1)[0].decode()
        kind=git(root,'cat-file','-t',oid).strip()
        if kind not in (b'blob',b'commit'):continue
        data=git(root,'cat-file',kind.decode(),oid);checked+=1
        if any(re.search(pattern,data,re.I) for pattern in PATTERNS):issues.append(oid)
    if issues:raise ValueError('Privacy pattern in reachable public candidate history objects: '+','.join(issues))
    return {'reachable_commits':len(commits),'new_curated_commits':len(commits),
            'scanned_blob_and_commit_objects':checked,'history_privacy':'pass (heuristic, not a guarantee)'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',nargs='?',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--history',action='store_true',help='Also scan reachable selected public history and enforce one clean curated root')
    args=parser.parse_args();result=verify(args.root)
    if args.history:result.update(history(args.root))
    print(json.dumps(result,sort_keys=True))
