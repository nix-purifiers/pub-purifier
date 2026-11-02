# SPDX-License-Identifier: MIT
"""Keep native coordinates and hashes in pubspec.lock; add missing archive URLs."""
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
import yaml

ADVICE='run pub-purifier lock (use --lockfile and --pub-lock for external locks)'
def canonical(value): return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def file_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
    data={k:v for k,v in data.items() if k!='contentHash'}
    return {**data,'contentHash':digest(data)}
def load_native(path):
    with Path(path).open() as stream: return yaml.safe_load(stream)
def url_ok(url):
    if not isinstance(url,str):return False
    parsed=urlsplit(url)
    return parsed.scheme in ('http','https') and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment

def cache_key(url):
    url=re.sub(r'^(https?://)(127\.0\.0\.1|\[::1\]|localhost)?',lambda m: ('' if m[1]=='https://' or m[2] else m[1])+('localhost' if m[2] else ''),url)
    return re.sub(r'[<>:"\\/|?*%]',lambda m:'%'+str(ord(m[0])),url)

def problems(root,native,data):
    try:
        if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('unsupported lock format')
        if data.get('contentHash')!=seal(data)['contentHash']:raise ValueError('contentHash mismatch')
        for key,path in [('manifest',Path(root)/'pubspec.yaml'),('native',Path(native))]:
            if data.get('inputs',{}).get(key)!=file_hash(path):raise ValueError(key+' changed after locking')
        overrides=Path(root)/'pubspec_overrides.yaml'
        if data.get('inputs',{}).get('overrides')!=(file_hash(overrides) if overrides.exists() else None):raise ValueError('overrides changed after locking')
        if not isinstance(data.get('archives'),dict):raise ValueError('missing archive URL map')
        if not isinstance(data.get('sdkVersion'),str):raise ValueError('missing SDK version')
        packages=load_native(native)['packages']
        if not isinstance(packages,dict):raise ValueError('invalid native packages')
        for name,package in packages.items():
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name):raise ValueError('invalid package name')
            if package['source']!='hosted':raise ValueError(name+': only hosted packages are supported currently')
            desc=package['description']
            if desc.get('name')!=name or not url_ok(desc.get('url')):raise ValueError(name+': invalid hosted description')
            if not re.fullmatch('[0-9a-f]{64}',desc.get('sha256','')):raise ValueError(name+': missing native archive sha256')
            if not isinstance(package['version'],str) or not re.fullmatch('[0-9][A-Za-z0-9.+-]*',package['version']):raise ValueError('invalid package version')
            if not url_ok(data['archives'].get(name)):raise ValueError(name+': missing archive URL')
        if set(data['archives'])!=set(packages):raise ValueError('unexpected archive URL entries')
        outputs=data.get('outputs')
        if not isinstance(outputs,dict):raise ValueError('invalid output map')
        for name,spec in outputs.items():
            file=spec.get('file') if isinstance(spec,dict) else None
            if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]*',name) or not isinstance(file,str) or not re.fullmatch('[A-Za-z0-9_./-]+[.]dart',file) or file.startswith('/') or '..' in Path(file).parts or not (Path(root)/file).is_file():raise ValueError('invalid output entry points')
        return []
    except (OSError,ValueError,KeyError,TypeError,AttributeError,yaml.YAMLError) as error:
        return [f'pub-purifier: {error}; {ADVICE}']
