#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reconstruct pinned public OBS/browser sources; never build or launch them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile


def git(root, *args, data=None):
    env={'PATH':os.defpath,'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_SYSTEM':os.devnull,
         'GIT_TERMINAL_PROMPT':'0'}
    result=subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(root),*args],input=data,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if result.returncode: raise RuntimeError('Git source operation refused: '+args[0])
    return result.stdout


def tree(root, revision):
    result={}
    for record in git(root,'ls-tree','-r','-z',revision).split(b'\0'):
        if not record:continue
        metadata,name=record.split(b'\t',1);mode,kind,oid=metadata.decode().split()
        result[name.decode()]={'mode':mode,'type':kind,'oid':oid}
    return result


def actual_tree(root, expected):
    """Hash actual checkout bytes, symlink targets and executable modes, not mocks."""
    errors=[];normalized=[]
    for name,item in expected.items():
        if item['type']=='commit':continue
        path=root/name
        if path.is_symlink():mode='120000';data=os.readlink(path).encode()
        elif path.is_file():
            mode='100755' if path.stat().st_mode & stat.S_IXUSR else '100644';data=path.read_bytes()
        else:errors.append(name);continue
        oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if mode!=item['mode']:errors.append(name)
        elif oid!=item['oid']:
            # Public upstream .gitattributes intentionally checks out three Windows
            # project files as CRLF. Verify canonical Git content, without changing sources.
            canonical=git(root,'hash-object','--path='+name,name).decode().strip()
            if canonical!=item['oid']:errors.append(name)
            else:normalized.append(name)
    if errors:raise RuntimeError('Reconstructed file content/mode mismatch ('+str(len(errors))+')')
    return normalized


def materialize(destination, source, revision):
    destination.mkdir(parents=True,exist_ok=False)
    git(destination,'init','--quiet')
    git(destination,'fetch','--quiet','--no-tags','--no-recurse-submodules','--depth=1',str(source),revision)
    git(destination,'checkout','--quiet','--detach','FETCH_HEAD')


def reconstruct(package, destination, obs_objects=None, browser_objects=None, fetch_public=False):
    package=Path(package).resolve();destination=Path(destination).absolute()
    manifest=json.loads((package/'packaging/source-manifest.json').read_text())
    if destination.exists():raise ValueError('Destination exists; refusing reuse/reset/clean')
    if not fetch_public and (obs_objects is None or browser_objects is None):
        raise ValueError('Supply explicit local public object stores or --fetch-public; default performs no network')
    for name,expected in manifest['patches'].items():
        if hashlib.sha256((package/name).read_bytes()).hexdigest()!=expected:raise ValueError('Patch checksum mismatch')
    obs=manifest['obs'];browser=manifest['browser']
    materialize(destination,obs_objects or obs['upstream_url'],obs['base'])
    git(destination,'apply','--check',str(package/'packaging/obs-director.patch'))
    git(destination,'apply','--index',str(package/'packaging/obs-director.patch'))
    child=destination/'plugins/obs-browser'
    # Empty gitlink directory from checkout; not an existing unrelated checkout.
    if child.exists():child.rmdir()
    materialize(child,browser_objects or browser['upstream_url'],browser['base'])
    git(child,'apply','--check',str(package/'packaging/obs-browser-director.patch'))
    git(child,'apply','--index',str(package/'packaging/obs-browser-director.patch'))
    root_tree=git(destination,'write-tree').decode().strip();child_tree=git(child,'write-tree').decode().strip()
    if child_tree!=browser['tree']:raise ValueError('Browser tree mismatch')
    obs_normalized=actual_tree(destination,manifest['obs_files'])
    browser_normalized=actual_tree(child,manifest['browser_files'])
    # Only the reproduction index is touched. No custom child fetch is required.
    git(destination,'update-index','--cacheinfo','160000,'+browser['revision']+',plugins/obs-browser')
    intended=git(destination,'write-tree').decode().strip()
    git(destination,'update-index','--cacheinfo','160000,'+browser['base']+',plugins/obs-browser')
    if intended!=obs['tree']:raise ValueError('Frozen superproject tree mismatch')
    return {'git_attribute_normalizations':obs_normalized+browser_normalized,
            'obs_file_count':sum(v['type']=='blob' for v in manifest['obs_files'].values()),
            'browser_file_count':sum(v['type']=='blob' for v in manifest['browser_files'].values()),
            'obs_normalized_tree':root_tree,'obs_tree_with_recorded_gitlink':intended,'browser_tree':child_tree,
            'native_build_run':False,'native_launch_run':False,'public_remote_clone_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--obs-objects',type=Path);parser.add_argument('--browser-objects',type=Path)
    parser.add_argument('--fetch-public',action='store_true',help='Explicitly permit the two pinned public Git fetches')
    parser.add_argument('--cef-archive',type=Path,help='Optional already-downloaded official archive; verify before extraction')
    args=parser.parse_args();package=Path(__file__).resolve().parent.parent
    result=reconstruct(package,args.destination,args.obs_objects,args.browser_objects,args.fetch_public)
    if args.cef_archive:
        metadata=json.loads((package/'packaging/source-manifest.json').read_text())['cef']
        if hashlib.sha256(args.cef_archive.read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('CEF checksum mismatch; not extracted')
        target=args.destination/'.deps'/metadata['directory'];target.mkdir(parents=True,exist_ok=False)
        with tarfile.open(args.cef_archive,'r:xz') as archive:archive.extractall(target,filter='data')
        result['cef_checksum_verified']=True
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
