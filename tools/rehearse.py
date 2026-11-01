#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Account-free cold source rehearsal. Never native OBS, accounts or paid APIs."""
import argparse
import json
import locale
import os
from pathlib import Path
import subprocess
import shutil
import sys
import unittest
from check_package import verify
from bootstrap_fork import actual_tree

ARTIFACT_ONLY='test_director_browser_probe.ArtifactIdentity.test_built_bundle_metadata_accepts_matching_fake_process_without_signal'


def node_commands(root, fork):
    page=fork/'frontend/widgets/DirectorMediaPage.inc'
    if not page.is_file():raise ValueError('Reconstruct the pinned fork before source-contract tests')
    return [['node',str(path),*([str(page)] if path.name=='test_director_managed_media.mjs' else [])]
            for path in sorted([*root.glob('test_director*.mjs'), *root.glob('test_realtime_ptt.cjs')])]


def normalize_locale():
    # Packaging/test process only: never broaden application ENV_KEEP or inspect
    # credentials. Remove Python's missing-LANG startup coercion before children.
    value='en_US.UTF-8' if sys.platform=='darwin' else 'C.UTF-8'
    os.environ['LANG']=value
    os.environ.pop('LC_CTYPE',None);os.environ.pop('LC_ALL',None)
    try:locale.setlocale(locale.LC_CTYPE,value)
    except locale.Error:raise ValueError('Required UTF-8 locale unavailable: '+value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-only',action='store_true',help='Run all source tests including Node, without simulated exercise')
    parser.add_argument('--node',help='Explicit installed Node 22+ executable; otherwise use PATH')
    parser.add_argument('--locale-check',action='store_true',help='Offline missing-LANG boundary probe only; no tests/services')
    args=parser.parse_args();lang=normalize_locale()
    if args.locale_check:
        env={'PATH':os.defpath,'LANG':lang}
        child=json.loads(subprocess.check_output([sys.executable,'-c',"import os,json;print(json.dumps({'LANG':os.environ.get('LANG'),'LC_CTYPE_present':'LC_CTYPE' in os.environ}))"],env=env,text=True))
        if child['LC_CTYPE_present']:raise ValueError('Child locale coercion escaped normalization')
        print(json.dumps(child));return 0
    node=args.node or shutil.which('node')
    if not node:raise ValueError('Node 22+ is required; no automatic installation')
    version=json.loads(subprocess.check_output([node,'-p',"JSON.stringify({version:process.versions.node,clone:typeof structuredClone})"],env={'PATH':os.defpath,'LANG':lang},text=True,timeout=5))
    if int(version['version'].split('.')[0])<22 or version['clone']!='function':raise ValueError('Node 22+ with structuredClone is required; select --node explicitly')
    root=Path(__file__).resolve().parent.parent
    if sys.prefix==sys.base_prefix:raise ValueError('Use the isolated project .venv with installed requirements')
    sys.path.insert(0,str(root));os.chdir(root)
    verify(root)
    manifest=json.loads((root/'packaging/source-manifest.json').read_text())
    fork=root/'fork-src'
    # Source-contract checks are REQUIRED even though compiled-artifact checks cannot run.
    actual_tree(fork,manifest['obs_files'])
    actual_tree(fork/'plugins/obs-browser',manifest['browser_files'])
    modules=[p.stem for p in sorted(root.glob('test*.py'))]
    suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
    excluded=[]
    def select(suite):
        result=unittest.TestSuite()
        for item in suite:
            if isinstance(item,unittest.TestSuite):result.addTests(select(item))
            elif item.id()==ARTIFACT_ONLY:excluded.append(item.id())
            else:result.addTest(item)
        return result
    selected=select(suite)
    if excluded!=[ARTIFACT_ONLY]:raise ValueError('Reviewed compiled-artifact-only inventory changed')
    result=unittest.TextTestRunner(verbosity=1).run(selected)
    summary={'python_tests':result.testsRun,'python_failures':len(result.failures),'python_errors':len(result.errors),
             'python_skipped':len(result.skipped), 'python_skip_reasons':[reason for _,reason in result.skipped],
             'native_artifact_checks_NOT_RUN':excluded,
             'native_offscreen_and_bundle_closure_NOT_RUN':'No compiled native artifacts in this source-only cold clone',
             'native_or_model_or_device_run':False,'locale':lang,'node_version':version['version'],'dependencies':'isolated pip-installed requirements; no development dependency loan'}
    print(f'{result.testsRun} run, {len(result.skipped)} skipped'+(' (native prerequisites absent)' if result.skipped and all('native prerequisites absent' in reason for _,reason in result.skipped) else ''), flush=True)
    print(json.dumps(summary),flush=True)
    if not result.wasSuccessful():return 1
    # Deliberately minimal subprocess environment, never a developer PYTHONPATH/.pth loan.
    env={'PATH':os.defpath+':/opt/homebrew/bin','PYTHON':sys.executable,'PYTHONDONTWRITEBYTECODE':'1','LANG':lang}
    commands=node_commands(root,fork)
    for command in commands:
        command[0]=node
        if subprocess.run(command,cwd=root,env=env).returncode:return 1
    summary['node_source_checks']=len(commands)
    output=root/'.source-package-evidence'
    output.mkdir(exist_ok=True)
    if not args.tests_only:
        for command in ([sys.executable,'director_exercise.py','--simulate','--out',str(output/'director.json')],
                        [sys.executable,'offline_workshop.py','demo','--out',str(output/'legacy-rehearsal')]):
            if subprocess.run(command,cwd=root,env=env).returncode:return 1
        summary['simulated_exercise']='30 scene cycles / 10 composition journeys / 3 persistent modes; no pixels'
        summary['legacy_rehearsal']='local account-free HTTP/SSE; no browser/audio'
    (output/'rehearsal-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
