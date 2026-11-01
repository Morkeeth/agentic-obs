#!/usr/bin/env python3
"""Offline Mach-O bundle closure audit. Never loads/launches an image.

Uses real per-architecture load commands and loader/executable-relative run paths.
Audits the main executable's graph, then every resident Mach-O (plugins/helpers
included). Private images must resolve inside this bundle; ambient SDK/DYLD paths
cannot make a distributable artifact pass. System install names are classified as
dyld-cache/system dependencies, not required to have standalone on-disk files.
Static closure does not prove native startup, signing, ABI or runtime dlopen names.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess

SYSTEM = ('/System/Library/', '/usr/lib/', '/Library/Apple/System/Library/')
MAGIC = {bytes.fromhex(x) for x in ('feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca')}
LOADS = {'LC_LOAD_DYLIB','LC_LOAD_WEAK_DYLIB','LC_REEXPORT_DYLIB','LC_LOAD_UPWARD_DYLIB','LC_LAZY_LOAD_DYLIB'}


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          env={'PATH':'/usr/bin:/bin','LC_ALL':'C'}, timeout=30).stdout


def commands(text):
    """Parse otool -l, retaining weak-vs-required edges and real LC_RPATH order."""
    paths, loads = [], []
    for block in re.split(r'\nLoad command \d+\n', '\n'+text)[1:]:
        command = re.search(r'^\s*cmd (\S+)\s*$',block,re.M)
        if not command: continue
        kind = command[1]
        if kind == 'LC_RPATH':
            match = re.search(r'^\s*path (.+) \(offset \d+\)\s*$',block,re.M)
            if not match: raise ValueError('Malformed LC_RPATH metadata')
            paths.append(match[1])
        elif kind in LOADS:
            match = re.search(r'^\s*name (.+) \(offset \d+\)\s*$',block,re.M)
            if not match: raise ValueError('Malformed dylib load metadata')
            loads.append((match[1], kind == 'LC_LOAD_WEAK_DYLIB'))
    return paths, loads


def expand(name, image, executable):
    if name == '@loader_path' or name.startswith('@loader_path/'):
        return Path(os.path.normpath(str(image.parent)+name[len('@loader_path'):]))
    if name == '@executable_path' or name.startswith('@executable_path/'):
        return Path(os.path.normpath(str(executable.parent)+name[len('@executable_path'):]))
    if name.startswith('/'): return Path(os.path.normpath(name))
    return None


class Audit:
    def __init__(self, bundle):
        self.bundle = Path(bundle).resolve(strict=True)
        if self.bundle.suffix != '.app': raise ValueError('Explicit .app artifact required')
        metadata = plistlib.loads((self.bundle/'Contents/Info.plist').read_bytes())
        name = metadata.get('CFBundleExecutable')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name):
            raise ValueError('Invalid executable metadata')
        self.main = self.bundle/'Contents/MacOS'/name
        if not self.resident(self.main): raise ValueError('Resident main executable required')
        self.identifier = metadata.get('CFBundleIdentifier')
        self.architectures = run('/usr/bin/lipo','-archs',str(self.main)).split()
        self.metadata, self.visited, self.errors, self.weak = {}, set(), {}, set()
        self.images, self.edges, self.system = set(), set(), set()
        self.main_images = set()

    def resident(self, path):
        # Never inspect private files outside the explicitly selected artifact.
        if not path.is_relative_to(self.bundle): return False
        resolved = path.resolve()
        return resolved.is_relative_to(self.bundle) and resolved.is_file()

    def label(self, path):
        return str(path.relative_to(self.bundle)) if path.is_relative_to(self.bundle) else '<external-private>'

    def meta(self, image, arch):
        key = (image,arch)
        if key not in self.metadata:
            available = run('/usr/bin/lipo','-archs',str(image)).split()
            if arch not in available: raise ValueError('Missing required Mach-O architecture: '+arch)
            self.metadata[key] = commands(run('/usr/bin/otool','-m','-arch',arch,'-l',str(image)))
        return self.metadata[key]

    def candidates(self, name, image, executable, rpaths):
        if name.startswith('@rpath/'):
            return [Path(os.path.normpath(str(base)+'/'+name[len('@rpath/'):])) for base in rpaths]
        expanded = expand(name,image,executable)
        return [expanded] if expanded else []

    def visit(self, image, executable, arch, inherited=(), active=()):
        image = image.resolve()
        if image in active: return
        try: own, loads = self.meta(image,arch)
        except (ValueError,subprocess.SubprocessError):
            self.errors[(self.label(image),arch,'metadata')] = {'image':self.label(image),'architecture':arch,'reason':'Unreadable/incompatible Mach-O load metadata'}
            return
        paths = tuple(dict.fromkeys([p for name in own if (p:=expand(name,image,executable)) is not None]+list(inherited)))
        key = (image,executable,arch,paths)
        if key in self.visited: return
        self.visited.add(key); self.images.add((self.label(image),arch))
        for name, weak in loads:
            self.edges.add((self.label(image),arch,name,weak))
            if name.startswith(SYSTEM):
                self.system.add(name);continue
            candidates = self.candidates(name,image,executable,paths)
            target = next((p.resolve() for p in candidates if self.resident(p)),None)
            if target is None:
                if weak: self.weak.add((self.label(image),arch,name));continue
                self.errors[(self.label(image),arch,name)] = {
                    'image':self.label(image),'architecture':arch,'dependency':name,
                    'reason':'Required private dependency does not resolve inside bundle',
                    'searched':[self.label(p) for p in candidates],
                }
            else:
                self.visit(target,executable,arch,paths,active+(image,))

    def all_images(self):
        found = set()
        for path in self.bundle.rglob('*'):
            if not self.resident(path): continue
            image = path.resolve()
            if image in found: continue
            with image.open('rb') as stream: magic = stream.read(4)
            if magic in MAGIC: found.add(image)
        return sorted(found)

    def executable_for(self, image):
        # Helpers are separate loader roots; plugins inherit the owning app's
        # executable run paths. Frameworks' own rpaths retain loader anchoring.
        for directory in image.parents:
            if not directory.is_relative_to(self.bundle): break
            if directory.suffix != '.app': continue
            info = directory/'Contents/Info.plist'
            if not info.is_file(): continue
            metadata = plistlib.loads(info.read_bytes())
            name = metadata.get('CFBundleExecutable')
            if isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_ ()-]{1,128}',name):
                candidate = directory/'Contents/MacOS'/name
                if self.resident(candidate): return candidate.resolve()
        return self.main

    def check(self):
        for arch in self.architectures: self.visit(self.main,self.main,arch)
        self.main_images = set(self.images)
        for image in self.all_images():
            executable = self.executable_for(image)
            for arch in self.architectures:
                try: roots,_ = self.meta(executable,arch)
                except (ValueError,subprocess.SubprocessError): roots = []
                inherited = tuple(p for name in roots if (p:=expand(name,executable,executable)) is not None)
                self.visit(image,executable,arch,inherited)
        return {'status':'FAIL' if self.errors else 'PASS','bundle_identifier':self.identifier,
                'architectures':self.architectures,'main_graph_images':len(self.main_images),
                'resident_images_audited':len(self.images),'dependency_edges':len(self.edges),
                'system_install_names':len(self.system),'missing_optional_weak_edges':len(self.weak),
                'errors':sorted(self.errors.values(),key=lambda e:json.dumps(e,sort_keys=True)),
                'main_sha256':hashlib.sha256(self.main.read_bytes()).hexdigest(),
                'limits':'Static actual load-command closure only; system/dyld-cache install names classified, not loaded. No startup/ABI/runtime-dlopen/signing/voice/render proof. No ambient SDK or DYLD fallback.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles',nargs='+',type=Path)
    args = parser.parse_args()
    failed = False
    for bundle in args.bundles:
        try: result = Audit(bundle).check()
        except (OSError,ValueError,subprocess.SubprocessError):
            result = {'status':'FAIL','reason':'Artifact or Mach-O metadata unavailable; no loader action attempted'}
        print(json.dumps(result,sort_keys=True));failed |= result['status']!='PASS'
    return int(failed)


if __name__ == '__main__': raise SystemExit(main())
