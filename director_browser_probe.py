#!/usr/bin/env python3
"""Source-bound owned-child local-only failure probe for a supervised window.

No native launch, RPC, credentials, model tools or output actions. Default is
read-only preflight. A destructive signal requires all explicit confirmations.
Only a caller-selected exact renderer child of a caller-selected fork app is
eligible. This is a developer exercise CLI, deliberately absent from MCP/UI.
"""
import argparse
import json
import os
import plistlib
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request


class Refused(ValueError): pass


def process(pid):
    if type(pid) is not int or pid < 2: raise Refused('Explicit owned process ID required')
    result = subprocess.run(['/bin/ps','-p',str(pid),'-o','pid=,ppid=,comm='],
                            capture_output=True, timeout=2, check=True)
    match = re.fullmatch(r'\s*(\d+)\s+(\d+)\s+(.+?)\s*', result.stdout.decode())
    if not match or int(match[1]) != pid: raise Refused('Owned process unavailable')
    return {'pid':pid, 'parent':int(match[2]), 'executable':match[3]}


def attest(app, parent_pid, renderer_pid, inspect=process):
    app = Path(app).resolve()
    parent = inspect(parent_pid); child = inspect(renderer_pid)
    try:
        info = app/'Contents/Info.plist'
        if info.is_symlink() or info.stat().st_size > 65536: raise Refused('Invalid own-bundle metadata')
        metadata = plistlib.loads(info.read_bytes())
        name = metadata.get('CFBundleExecutable')
        if (metadata.get('CFBundleIdentifier') not in ('com.morkeeth.agentic-streamer', 'com.morkeeth.agentic-streamer.browser')
                or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',name)):
            raise Refused('Invalid own-bundle metadata')
        expected_parent = app/'Contents/MacOS'/name
        if not expected_parent.is_file() or expected_parent.resolve() != expected_parent:
            raise Refused('Own-bundle executable missing or escaped')
    except (OSError, ValueError, TypeError, AttributeError):
        raise Refused('Invalid own-bundle metadata') from None
    expected_child = app/'Contents/Frameworks/OBS Helper (Renderer).app/Contents/MacOS/OBS Helper (Renderer)'
    if (app.suffix != '.app' or Path(parent['executable']).resolve() != expected_parent
            or Path(child['executable']).resolve() != expected_child
            or child['parent'] != parent_pid or parent_pid == renderer_pid):
        raise Refused('Only the exact selected fork renderer child is eligible')
    return parent, child


def graphics_binding(log, parent_pid, bank):
    """Read native CEF IPC attestation from THIS run's own app log, not page text."""
    if bank not in ('A','B') or type(parent_pid) is not int or parent_pid < 2:
        raise Refused('Exact owned graphics bank and parent required')
    path = Path(log)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
            raise Refused('Bounded own app log required')
        text = path.read_text(encoding='utf8')
    except (OSError, UnicodeError, TypeError):
        raise Refused('Own app log unavailable') from None
    pattern = re.compile(r'^\d{2}:\d{2}:\d{2}\.\d{3}: \[director-renderer-binding\] app_pid=(\d+) renderer_pid=(\d+) browser_id=(\d+) source=Director / Graphics ([AB])$')
    binding = None
    for number, line in enumerate(text.splitlines(), 1):
        match = pattern.fullmatch(line)
        if match and int(match[1]) == parent_pid and match[4] == bank:
            binding = {'app_pid':parent_pid, 'renderer_pid':int(match[2]),
                       'browser_id':int(match[3]), 'bank':bank,
                       'source':'Director / Graphics '+bank, 'log':str(path), 'line':number}
    if not binding or binding['renderer_pid'] < 2:
        raise Refused('No native app-log binding for the reviewed graphics bank')
    return binding


def fetch_state(port):
    if type(port) is not int or port in (4455,8877,8878,8879) or not 1024 <= port <= 65535:
        raise Refused('Use the owned loopback director HTTP port')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(f'http://127.0.0.1:{port}/api/agent-state',timeout=2) as response:
        value = response.read(65537)
    if len(value)>65536: raise Refused('Bounded state required')
    value = json.loads(value)
    if value.get('build') != 'expanded-director-1': raise Refused('Wrong controller')
    return value


def local_review(state):
    if (not state.get('armed') or not state.get('obs',{}).get('connected') or state.get('paused')
            or state.get('destination') != 'obs' or not state.get('rendered_ready')
            or not state.get('native_review') or state.get('staged_page') or state.get('program_page')):
        raise Refused('Fresh native local-only fixture preview required; external pages must be absent')
    return state['native_review']


def exercise(app, parent_pid, renderer_pid, read, *, crash=False, confirmed=False,
             inspect=process, send=os.kill, clock=time.monotonic, wait=time.sleep, binding_log=None):
    attest(app,parent_pid,renderer_pid,inspect)
    initial = read(); identity = local_review(initial)
    if not crash:
        return {'probe':'preflight only', 'signal_sent':False, 'native_pixels_verified':False}
    if not confirmed: raise Refused('Explicit outputs-off and exclusively local owned fixture confirmation required')
    if binding_log is None: raise Refused('Native graphics-source/PID app-log binding required')
    binding = graphics_binding(binding_log, parent_pid, identity.get('bank'))
    if binding['renderer_pid'] != renderer_pid:
        raise Refused('Selected renderer is not the reviewed graphics bank renderer')
    # Re-read the mapping immediately before signaling; no first-child fallback.
    if graphics_binding(binding_log, parent_pid, identity.get('bank')) != binding:
        raise Refused('Graphics renderer binding changed before signal')
    # Re-attest immediately before signaling; never discover/kill arbitrary helpers.
    attest(app,parent_pid,renderer_pid,inspect)
    send(renderer_pid,signal.SIGKILL)
    deadline = clock()+8
    while clock() < deadline:
        inspect(parent_pid)  # A missing/crashed parent is failure, not successful containment.
        state = read()
        if (state.get('program') != initial.get('program') or state.get('program_bank') != initial.get('program_bank')):
            raise Refused('Program changed during read-only failure observation')
        if not state.get('rendered_ready') and not state.get('agent_take_approved') and state.get('native_review') is None:
            return {'probe':'renderer readiness lost; parent observed alive', 'signal_sent':True,
                    'review_identity_was_present':bool(identity), 'native_pixels_verified':False, 'source_binding':binding,
                    'recovery':'Explicit operator recovery/re-preview and exact review required; no mutation attempted'}
        wait(.1)  # Bounded observation cadence; no timeout can authorize success.
    raise Refused('Renderer readiness did not expire: real crash containment NOT established')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',required=True)
    parser.add_argument('--parent-pid',type=int,required=True)
    parser.add_argument('--renderer-pid',type=int,required=True)
    parser.add_argument('--port',type=int,default=8880)
    parser.add_argument('--app-log',help='Fresh own run app log containing native Graphics source/PID binding')
    parser.add_argument('--crash-owned-renderer',action='store_true')
    parser.add_argument('--confirm-outputs-off-owned-local-fixtures-only',action='store_true')
    args = parser.parse_args()
    try:
        result = exercise(args.app,args.parent_pid,args.renderer_pid,lambda:fetch_state(args.port),
                          crash=args.crash_owned_renderer,confirmed=args.confirm_outputs_off_owned_local_fixtures_only,binding_log=args.app_log)
    except Exception:
        # Never echo process commands, paths, response bodies or provider errors.
        print('REFUSED / NOT PROVEN: inspect the owned trial manually; no automatic action retry')
        return 1
    print(json.dumps(result,sort_keys=True)); return 0


if __name__ == '__main__': raise SystemExit(main())
