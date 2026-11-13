# SPDX-License-Identifier: MIT
"""Materialize path inputs and verify a native offline Pub resolution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urljoin, urlsplit, unquote
from . import hosted, lock
from .path_sources import stage_sources, within


def source_files(root):
    root=Path(root).resolve()
    result={}
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:]=[name for name in directories if name not in {'.git','.dart_tool','.pub-purifier'}]
        for name in [*directories,*files]:
            path=Path(base)/name
            relative=str(path.relative_to(root))
            if path.is_symlink():result[relative]={'link':os.readlink(path)}
            elif path.is_file():result[relative]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'mode':path.stat().st_mode & 0o777}
    return result


def materialize(source_root, project, providers, destination, native, capture, dart, receipt=None):
    data = hosted.validate(json.loads(Path(capture).read_text()))
    owners=[Path(source_root).resolve(),*[Path(p).resolve() for p in providers]]
    original=[source_files(owner) for owner in owners]
    seed_hash=lock.file_hash(native) if Path(native).exists() else None
    staged = stage_sources(source_root, project, providers, destination, native)
    environment = {**os.environ, 'DART_SUPPRESS_ANALYTICS': 'true'}
    command = [str(dart), 'pub', 'get', '--offline', '--no-example', '--directory', str(staged)]
    # The selected SDK authors any changes to its temporary lock. The original
    # lock and immutable source inputs are never rewritten by this operation.
    subprocess.run(command, env=environment, check=True)
    current = lock.load_native(staged / 'pubspec.lock')
    hosted.verify_active(data, current)
    subprocess.run([*command, '--enforce-lockfile'], env=environment, check=True)
    final = lock.load_native(staged / 'pubspec.lock')
    hosted.verify_active(data, final)
    if current != final:
        raise ValueError('native enforced graph differs from native authored graph')
    config_path = staged / '.dart_tool/package_config.json'
    config = json.loads(config_path.read_text())
    packages = config.get('packages')
    if not isinstance(packages, list):
        raise ValueError('invalid native package configuration')
    seen = set()
    root_name=lock.load_native(staged/'pubspec.yaml')['name']
    provided_roots={lock.load_native(owner/'pubspec.yaml')['name']:(Path(destination)/str(index)).resolve()
                    for index,owner in enumerate(owners) if index>0}
    staged_owners=[(Path(destination)/str(index)).resolve() for index in range(len(owners))]
    for package in packages:
        name = package.get('name')
        if not isinstance(name, str) or name in seen:
            raise ValueError('duplicate or invalid native package configuration')
        seen.add(name)
        uri = urlsplit(urljoin(config_path.as_uri(), package['rootUri']))
        if uri.scheme != 'file' or uri.netloc not in ('', 'localhost'):
            raise ValueError('nonlocal native package configuration')
        root = Path(unquote(uri.path)).resolve(strict=True)
        manifest = lock.load_native(root / 'pubspec.yaml')
        if manifest.get('name') != name:
            raise ValueError('native package source identity differs from configuration')
        entry = final['packages'].get(name)
        if entry is not None:
            if str(manifest.get('version')) != entry['version']:
                raise ValueError('materialized native package version differs from graph')
            if entry['source'] == 'path':
                if not any(within(root, owner) for owner in staged_owners):
                    raise ValueError('native path graph escapes materialized source owners')
                if name in provided_roots and root!=provided_roots[name]:
                    raise ValueError('native path graph bypasses current provided source')
                description = entry['description']
                expected = (staged / description['path']).resolve(strict=True)
                if root != expected:
                    raise ValueError('native path configuration differs from current graph')
            else:
                cache = Path(os.environ['PUB_CACHE']).resolve()
                expected = cache / 'hosted' / lock.cache_key(entry['description']['url']) / (name + '-' + entry['version'])
                if root != expected.resolve(strict=True):
                    raise ValueError('native hosted configuration differs from captured cache')
        elif name!=root_name or root!=staged.resolve():
            raise ValueError('native root configuration differs from selected project')
    if not set(final['packages']).issubset(seen):
        raise ValueError('native package configuration omits graph packages')
    for spec in data['outputs'].values():
        if not (staged / spec['file']).is_file():
            raise ValueError('output entry point is missing after materialization')
    joins=[]
    for index, (owner, files) in enumerate(zip(owners, original)):
        if source_files(owner)!=files:
            raise ValueError('original source input changed during native materialization')
        target=Path(destination)/str(index)
        joined=[]
        for relative, entry in files.items():
            path=target/relative
            if 'link' in entry:
                if not path.is_symlink():raise ValueError('source symlink type changed')
                continue
            if relative=='pubspec.lock' or path.name=='pubspec.lock':continue
            if path.stat().st_mode & 0o777 != entry['mode']:
                raise ValueError('source file mode changed')
            if path.name in ('pubspec.yaml','pubspec_overrides.yaml'):
                before=lock.load_native(owner/relative);after=lock.load_native(path)
                for section in ('dependencies','dev_dependencies','dependency_overrides'):
                    for name,spec in before.get(section,{}).items():
                        if isinstance(spec,dict) and 'path' in spec:
                            after[section][name]['path']=spec['path']
                if before!=after:raise ValueError('nonlocation manifest field changed')
            elif lock.file_hash(path)!=entry['sha256']:
                raise ValueError('source code bytes changed during materialization')
            joined.append({'file':relative,**entry})
        joins.append({'owner':str(owner),'staged':str(target),'files':joined})
    if (lock.file_hash(native) if Path(native).exists() else None)!=seed_hash:
        raise ValueError('original native lock changed during materialization')
    if receipt:
        Path(receipt).write_text(json.dumps({'sourceJoins':joins,'nativeSeedSha256':seed_hash,
            'activeNativeGraph':final,'portableContentHash':data['contentHash'],
            'sdkVersionObservation':subprocess.run([str(dart),'--version'],check=True,capture_output=True,text=True).stdout.strip()},sort_keys=True,indent=2)+'\n')
    return staged


def main():
    parser = argparse.ArgumentParser()
    for name in ('source-root', 'project', 'destination', 'native', 'capture', 'dart'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--result-file')
    parser.add_argument('--receipt')
    parser.add_argument('--path-source-root', action='append', default=[])
    args = parser.parse_args()
    result = materialize(args.source_root, args.project, args.path_source_root, args.destination, args.native, args.capture, args.dart, args.receipt)
    if args.result_file:
        Path(args.result_file).write_text(str(result))
    else:
        print(result)


if __name__ == '__main__':
    main()
