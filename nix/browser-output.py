"""Select compiler-owned JavaScript and explicitly declared public assets."""
import hashlib, json, pathlib, shutil, sys
Path = pathlib.Path
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def relative(value):
    path=Path(value)
    if path.is_absolute() or '\\' in value or any(p in ('','.','..') for p in value.split('/')):
        raise ValueError('public asset path must be relative and normalized: '+value)
    return path
def validate(root,spec):
    selected=[spec['entrypoint'],*spec.get('assets',{}).values()]
    for name in selected:
        path=(root/relative(name)).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('browser input escapes project source: '+name)
    for destination in spec.get('assets',{}):
        relative(destination)
        if destination in {'main.js','main.wasm','main.mjs','main.support.js'}:raise ValueError('public asset collides with native browser output')
if sys.argv[1]=='validate':
    validate(Path(sys.argv[2]).resolve(),json.loads(Path(sys.argv[3]).read_text()));sys.exit(0)
root, compiled, spec_file, out, proof, sdk = map(Path, sys.argv[1:])
root=root.resolve();spec=json.loads(spec_file.read_text());validate(root,spec)
entry=(root/relative(spec['entrypoint'])).resolve(strict=True)
if not entry.is_relative_to(root) or not entry.is_file():raise ValueError('Dart entrypoint escapes project source')
mode=spec.get('target','javascript')
required={'main.wasm','main.mjs'} if mode=='wasm' else {'main.js'}
generated={p.name:p for p in compiled.iterdir() if p.is_file() and p.suffix in {'.js','.mjs','.wasm'}}
if not required<=set(generated):raise ValueError('native Dart compiler did not produce its declared browser target')
files={}
for name,src in generated.items():
    if src.suffix=='.wasm' and src.read_bytes()[:8]!=b'\0asm\x01\0\0\0':raise ValueError('native Dart output is not a WebAssembly module')
    shutil.copyfile(src,out/name);files[name]={'sha256':sha(src),'owner':'native dart compile '+mode}
for destination, source in spec.get('assets',{}).items():
    dest=relative(destination);src=(root/relative(source)).resolve(strict=True)
    if not src.is_relative_to(root) or not src.is_file():raise ValueError('public asset escapes project source: '+source)
    if destination in files:raise ValueError('public asset collides with native browser output')
    target=out/dest;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    files[destination]={'sha256':sha(src),'source':source}
(proof/'model.json').write_text(json.dumps({'kind':'native-dart-browser','target':mode,'runtime':'wasm-gc-with-javascript-loader' if mode=='wasm' else 'javascript','sdk':str(sdk),'entrypoint':spec['entrypoint'],'compilerVersion':(proof/'compiler-version.txt').read_text().strip(),'files':files},sort_keys=True,indent=2)+'\n')
