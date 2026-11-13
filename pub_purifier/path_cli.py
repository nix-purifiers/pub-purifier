# SPDX-License-Identifier: MIT
"""Explicit native path-source capture, using the caller's selected Dart."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
from . import hosted, lock
from .path_sources import stage_sources


def capture(root, source_root, providers, native, sidecar, dart, entries=(), names=(), update=False):
    previous = None
    if sidecar.exists():
        previous = json.loads(sidecar.read_text())
        if previous.get('version') == 2:
            hosted.validate(previous)
        elif previous.get('version') != 1 or previous.get('contentHash') != lock.seal(previous)['contentHash']:
            raise ValueError('invalid previous capture')
    with tempfile.TemporaryDirectory(prefix='pub-path-capture-') as folder:
        staged = stage_sources(source_root, root, providers, Path(folder)/'sources', native)
        subprocess.run([str(dart), 'pub', 'upgrade' if update else 'get', *names,
                        '--no-example', '--directory', str(staged)], check=True,
                       env={**os.environ, 'PUB_CACHE':str(Path(folder)/'cache'), 'DART_SUPPRESS_ANALYTICS':'true'})
        resolved = lock.load_native(staged/'pubspec.lock')
        identities = {}
        for name, package in resolved['packages'].items():
            if package['source'] == 'path':
                continue
            if package['source'] != 'hosted':
                raise ValueError(name + ': unsupported native source')
            desc = package['description']
            if not lock.url_ok(desc['url']):
                raise ValueError('invalid native hosted URL')
            request = desc['url'].rstrip('/') + '/api/packages/' + name + '/versions/' + package['version']
            with urllib.request.urlopen(request, timeout=60) as response:
                metadata = json.load(response)
            if metadata.get('archive_sha256') != desc['sha256']:
                raise ValueError(name + ': registry hash differs from native lock')
            identities[name] = {'version':package['version'], 'registry':desc['url'],
                                'sha256':desc['sha256'], 'archiveUrl':metadata['archive_url']}
        outputs = dict(previous['outputs']) if previous else {}
        if not previous:
            outputs = {p.stem:{'file':str(p.relative_to(root))} for p in sorted((root/'bin').glob('*.dart'))}
        for entry in entries:
            name, separator, file = entry.partition('=')
            if not separator:
                raise ValueError('--entry expects NAME=FILE.dart')
            outputs[name] = {'file':file}
        data = hosted.validate(lock.seal({'version':2, 'hosted':identities, 'outputs':outputs}))
        hosted.verify_active(data, resolved)
        # Existing authored locks remain seeds. Newly captured source locations
        # belong to the temporary stage, so never publish that lock as input.
        return data
