# SPDX-License-Identifier: MIT
"""Exercise native Dart pub resolution against a real versioned hosted API."""
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading

SOURCE=Path(__file__).resolve().parents[1]
case=sys.argv[1]
def run(args,**kwargs):
    result=subprocess.run(list(map(str,args)),text=True,**kwargs)
    if result.returncode:
        if result.stderr:print(result.stderr,file=sys.stderr)
        result.check_returncode()
    return result
with tempfile.TemporaryDirectory(prefix='pub-conformance-') as temp:
    temp=Path(temp);run(['nix','build',SOURCE,'--out-link',temp/'cli'])
    cli=temp/'cli/bin/pub-purifier';dart=temp/'cli/bin/dart'
    versions={name:[] for name in ['demo','other']};archives={}
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data=None;kind='application/json'
            if self.path.startswith('/archives/'):
                data=archives.get(self.path);kind='application/octet-stream'
            else:
                pieces=self.path.strip('/').split('/')
                if len(pieces)>=3 and pieces[:2]==['api','packages'] and pieces[2] in versions:
                    name=pieces[2]
                    if len(pieces)==3:data=json.dumps({'name':name,'latest':versions[name][-1],'versions':versions[name]}).encode()
                    elif len(pieces)==5 and pieces[3]=='versions':
                        matches=[p for p in versions[name] if p['version']==pieces[4]]
                        if matches:data=json.dumps(matches[0]).encode()
            self.send_response(200 if data is not None else 404);self.send_header('Content-Type',kind);self.end_headers()
            if data is not None:self.wfile.write(data)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def publish(version):
        for name in versions:
            spec={'name':name,'version':version,'environment':{'sdk':'>=3.0.0 <4.0.0'}}
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
                for path,contents in [('pubspec.yaml',json.dumps(spec)),(f'lib/{name}.dart',f"const version = '{version}';\n")]:
                    info=tarfile.TarInfo(path);payload=contents.encode();info.size=len(payload);info.mtime=1;tar.addfile(info,io.BytesIO(payload))
            data=buffer.getvalue();path=f'/archives/{name}-{version}.tar.gz';archives[path]=data
            versions[name].append({'version':version,'pubspec':spec,'archive_url':base+path,'archive_sha256':hashlib.sha256(data).hexdigest(),'published':'2026-01-01T00:00:00Z'})
    root=temp/'project';root.mkdir();(root/'bin').mkdir()
    manifest=root/'pubspec.yaml'
    manifest.write_text(json.dumps({'name':'purifier_example','version':'0.1.0','environment':{'sdk':'>=3.0.0 <4.0.0'},'dependencies':{name:{'hosted':base,'version':'>=1.0.0 <3.0.0'} for name in versions}}))
    (root/'bin/main.dart').write_text("import 'package:demo/demo.dart' as demo; import 'package:other/other.dart' as other; void main() {print('${demo.version},${other.version}');}\n")
    native=temp/'locks/pubspec.lock' if case=='external' else root/'pubspec.lock'
    companion=temp/'locks/pub.json' if case=='external' else root/'pub-purifier.lock.json'
    def purifier(*args):return run([cli,'--lockfile',companion,'--pub-lock',native,*args],cwd=root)
    try:
        publish('1.0.0');purifier('lock');old=native.read_bytes();original=companion.read_bytes()
        if case=='relock':
            purifier('lock');assert companion.read_bytes()==original and native.read_bytes()==old
            companion.write_text('{broken');purifier('lock');assert companion.read_bytes()==original and native.read_bytes()==old
            native.write_text('bad: [');purifier('lock');assert companion.read_bytes()==original and native.read_bytes()==old
        elif case=='update':
            publish('2.0.0');purifier('lock');assert companion.read_bytes()==original
            purifier('update','demo');assert native.read_bytes()!=old
            text=native.read_text();assert 'version: "2.0.0"' in text and 'version: "1.0.0"' in text,text
            purifier('update');assert native.read_text().count('version: "2.0.0"')==2
        elif case!='external':raise ValueError(case)
        purifier('prefetch');server.shutdown();server.server_close();thread.join()
        env={**os.environ,'PUB_PURIFIER_LOCKFILE':str(companion),'PUB_PURIFIER_PUB_LOCK':str(native)}
        result=run([dart,'run','bin/main.dart'],cwd=root,env=env,capture_output=True)
        assert result.stdout.strip()==('2.0.0,2.0.0' if case=='update' else '1.0.0,1.0.0'),result.stdout
        run([dart,'pub','get'],cwd=root,env=env)
        assert not list(root.glob('*.nix'))
        if case=='external':
            assert not (root/'pubspec.lock').exists() and not (root/'pub-purifier.lock.json').exists()
            assert companion.read_bytes()==original and native.read_bytes()==old
        print(case+': native pub solver, cache, locks and offline run passed')
    finally:
        if thread.is_alive():server.shutdown();server.server_close();thread.join()
