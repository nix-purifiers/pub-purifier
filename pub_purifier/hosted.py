# SPDX-License-Identifier: MIT
"""Closed portable hosted identities and verification of native Pub results."""
import re
from .lock import seal

_KEYS = {'version', 'hosted', 'outputs', 'contentHash'}
_IDENTITY_KEYS = {'version', 'registry', 'sha256', 'archiveUrl'}
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
_VERSION = re.compile(r'[0-9][A-Za-z0-9.+-]*\Z')
_URL = re.compile(r"https?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]+)?(?:[/?][^#]*)?\Z")

def url_ok(value):
    return isinstance(value, str) and _URL.fullmatch(value) is not None

_SHA = re.compile(r'[0-9a-f]{64}\Z')


def validate(data):
    """Validate only portable data; never inspect a producer's output."""
    if not isinstance(data, dict) or set(data) != _KEYS or type(data['version']) is not int or data['version'] != 2:
        raise ValueError('invalid closed version 2 lock')
    if data['contentHash'] != seal(data)['contentHash']:
        raise ValueError('contentHash mismatch')
    if not isinstance(data['hosted'], dict) or not isinstance(data['outputs'], dict):
        raise ValueError('invalid hosted or output map')
    for name, identity in data['hosted'].items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError('invalid hosted package name')
        if not isinstance(identity, dict) or set(identity) != _IDENTITY_KEYS:
            raise ValueError(name + ': invalid closed hosted identity')
        if not isinstance(identity['version'], str) or not _VERSION.fullmatch(identity['version']):
            raise ValueError(name + ': invalid version')
        if not isinstance(identity['sha256'], str) or not _SHA.fullmatch(identity['sha256']):
            raise ValueError(name + ': invalid native sha256')
        if not url_ok(identity['registry']) or not url_ok(identity['archiveUrl']):
            raise ValueError(name + ': invalid hosted URL')
    for name, spec in data['outputs'].items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
            raise ValueError('invalid output name')
        if not isinstance(spec, dict) or set(spec) != {'file'}:
            raise ValueError('invalid output entry')
        file = spec['file']
        if not isinstance(file, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+[.]dart', file) or file.startswith('/') or '..' in file.split('/'):
            raise ValueError('invalid output entry point')
    return data


def verify_active(data, native):
    """Allow unused captures; every active hosted identity must be captured."""
    validate(data)
    packages = native.get('packages') if isinstance(native, dict) else None
    if not isinstance(packages, dict):
        raise ValueError('invalid native package graph')
    for name, package in packages.items():
        if not isinstance(package, dict):
            raise ValueError('invalid native package')
        source = package.get('source')
        if source == 'path':
            continue
        if source != 'hosted':
            raise ValueError(name + ': unsupported native source')
        identity = data['hosted'].get(name)
        description = package.get('description')
        if not isinstance(description, dict) or identity is None:
            raise ValueError(name + ': active hosted package was not captured')
        if description.get('name') != name or (package.get('version'), description.get('url'), description.get('sha256')) != (identity['version'], identity['registry'], identity['sha256']):
            raise ValueError(name + ': active hosted identity differs from capture')
    return native
