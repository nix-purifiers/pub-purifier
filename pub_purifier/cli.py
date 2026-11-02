# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import yaml
from . import lock

def run(args,**kwargs): return subprocess.run(list(map(str,args)),check=True,**kwargs)
def tool(): return os.environ.get('PUB_PURIFIER_DART','dart')
def read(path):
    try:return json.loads(path.read_text())
    except (ValueError,OSError) as error:raise ValueError(f'cannot read {path}: {error}; {lock.ADVICE}') from error
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
def inputs(root,native):
    overrides=root/'pubspec_overrides.yaml'
    return {'manifest':lock.file_hash(root/'pubspec.yaml'),'native':lock.file_hash(native),'overrides':lock.file_hash(overrides) if overrides.exists() else None}
def stage_manifest(root,destination,native):
    declaration=yaml.safe_load((root/'pubspec.yaml').read_text())
    if 'workspace' in declaration or declaration.get('resolution')=='workspace':
        raise ValueError('pub workspaces are not supported yet')
    shutil.copyfile(root/'pubspec.yaml',destination/'pubspec.yaml')
    if (root/'pubspec_overrides.yaml').exists():shutil.copyfile(root/'pubspec_overrides.yaml',destination/'pubspec_overrides.yaml')
    seed = native if native.exists() else root/'pubspec.lock'
    if seed.exists():
        try:
            if isinstance(lock.load_native(seed),dict):shutil.copyfile(seed,destination/'pubspec.lock')
        except yaml.YAMLError:pass

def do_lock(root,native,sidecar,names=(),update=False,entries=()):
    previous=None
    if sidecar.exists():
        try:
            old=read(sidecar)
            if not lock.problems(root,native,old):previous=old
        except ValueError:pass
    if previous and not update and not entries:
        print(f'Existing package resolution retained in {sidecar}');return
    with tempfile.TemporaryDirectory(prefix='pub-lock-') as temp:
        stage=Path(temp);stage_manifest(root,stage,native)
        run([tool(),'pub','upgrade' if update else 'get',*names,'--no-example','--directory',stage],env={**os.environ,'PUB_CACHE':str(stage/'cache'),'DART_SUPPRESS_ANALYTICS':'true'})
        packages=lock.load_native(stage/'pubspec.lock')['packages']
        archives={}
        for name,package in packages.items():
            if package['source']!='hosted':raise ValueError(name+': only hosted packages are supported currently')
            desc=package['description']
            if not lock.url_ok(desc['url']):raise ValueError('invalid hosted URL')
            if previous and lock.load_native(native)['packages'].get(name)==package:
                archives[name]=previous['archives'][name];continue
            url=desc['url'].rstrip('/')+'/api/packages/'+name+'/versions/'+package['version']
            with urllib.request.urlopen(url,timeout=60) as response:metadata=json.load(response)
            if metadata.get('archive_sha256')!=desc['sha256']:raise ValueError(name+': registry hash differs from native lock')
            archive=metadata['archive_url']
            if not lock.url_ok(archive):raise ValueError(name+': invalid archive URL')
            archives[name]=archive
        outputs=(previous or {}).get('outputs',{})
        if not outputs:outputs={p.stem:{'file':str(p.relative_to(root))} for p in sorted((root/'bin').glob('*.dart'))}
        for entry in entries:
            name,separator,file=entry.partition('=')
            if not separator:raise ValueError('--entry expects NAME=FILE.dart')
            outputs[name]={'file':file}
        version=run([tool(),'--version'],text=True,capture_output=True).stdout
        version=re.search(r'Dart SDK version: ([^ ]+)',version).group(1)
        data=lock.seal({'version':1,'inputs':inputs(root,stage/'pubspec.lock'),'sdkVersion':version,'archives':archives,'outputs':outputs})
        if errors:=lock.problems(root,stage/'pubspec.lock',data):raise ValueError('\n'.join(errors))
        native.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(stage/'pubspec.lock',native)
        write(sidecar,data)
    print(f'Locked {len(packages)} Dart packages in {sidecar}')

def prepare(root,native,sidecar,get_args=(),quiet=False):
    data=read(sidecar)
    if errors:=lock.problems(root,native,data):raise ValueError('\n'.join(errors))
    state=sidecar.parent/'.pub-purifier'/lock.digest(str(root))[:12]
    state.mkdir(parents=True,exist_ok=True)
    for target in ['cache','runtime']:
        run(['nix','build','--impure','--file',os.environ['PUB_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','pubLock',native,'--argstr','target',target,'--out-link',state/target])
    cache=state/'working-cache';cache.mkdir(exist_ok=True)
    for directory in ['hosted','hosted-hashes']:
        for server in (state/'cache'/directory).iterdir():
            dest=cache/directory/server.name;dest.mkdir(parents=True,exist_ok=True)
            for package in server.iterdir():
                target=dest/package.name
                if target.is_symlink():target.unlink()
                elif target.exists():raise ValueError(f'expected an owned cache symlink: {target}')
                target.symlink_to(package.resolve())
    # Pub writes its lock into the selected project, so use a staging manifest
    # and copy only native generated package configuration back. External
    # native locks never need to replace the working tree's pubspec.lock.
    with tempfile.TemporaryDirectory(prefix='pub-prepare-') as temp:
        stage=Path(temp);stage_manifest(root,stage,native)
        run([tool(),'pub','get','--offline','--enforce-lockfile','--no-example',*get_args,'--directory',stage],env={**os.environ,'PUB_CACHE':str(cache),'DART_SUPPRESS_ANALYTICS':'true'},stdout=subprocess.DEVNULL if quiet else None)
        if '--dry-run' not in get_args and '-n' not in get_args:
            target=root/'.dart_tool';target.mkdir(exist_ok=True)
            for name in ['package_config.json','package_graph.json']:
                shutil.copyfile(stage/'.dart_tool'/name,target/name)
    return cache

def find_root(arguments):
    root=Path.cwd()
    for index,arg in enumerate(arguments):
        if arg.startswith('--directory='):root=Path(arg.split('=',1)[1]).resolve();break
        if arg in ('--directory','-C') and index+1<len(arguments):root=Path(arguments[index+1]).resolve();break
    for path in [root,*root.parents]:
        if (path/'pubspec.yaml').exists():return path
    return root

def main(argv=None):
    parser=argparse.ArgumentParser(prog='pub-purifier')
    parser.add_argument('--lockfile');parser.add_argument('--pub-lock')
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('lock');create.add_argument('--entry',action='append',default=[])
    update=sub.add_parser('update');update.add_argument('packages',nargs='*')
    sub.add_parser('prefetch')
    native_parser=sub.add_parser('native',help=argparse.SUPPRESS);native_parser.add_argument('args',nargs=argparse.REMAINDER)
    publish=sub.add_parser('publish');publish.add_argument('--repo',required=True);publish.add_argument('--tag',required=True)
    args=parser.parse_args(argv)
    command=getattr(args,'args',[])
    if command[:1]==['--']:command=command[1:]
    root=find_root(command)
    sidecar=Path(args.lockfile or os.environ.get('PUB_PURIFIER_LOCKFILE',root/'pub-purifier.lock.json')).resolve()
    native=Path(args.pub_lock or os.environ.get('PUB_PURIFIER_PUB_LOCK',root/'pubspec.lock')).resolve()
    try:
        if args.command in ('lock','update'):
            do_lock(root,native,sidecar,getattr(args,'packages',()),args.command=='update',getattr(args,'entry',()))
        elif args.command=='prefetch':print(prepare(root,native,sidecar))
        elif args.command=='publish':
            prepare(root,native,sidecar)
            with tempfile.TemporaryDirectory(prefix='pub-publish-') as temp:
                release=Path(temp)/'release'
                run(['nix','build','--impure','--file',os.environ['PUB_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','pubLock',native,'--argstr','target','release','--out-link',release])
                run(['gh','release','create',args.tag,*sorted(release.glob('*.tar.gz')),'--repo',args.repo,'--title',args.tag])
        else:
            if not sidecar.exists() and not sidecar.is_symlink():
                print('pub-purifier: warning: no lockfile; using ordinary, impure Dart package resolution',file=sys.stderr)
                os.execv(tool(),[tool(),*command])
            if '--help' in command or '-h' in command:
                os.execv(tool(),[tool(),*command])
            if command[:2] in (['pub','add'],['pub','remove'],['pub','upgrade'],['pub','downgrade'],['pub','cache']):
                raise ValueError('edit pubspec.yaml and use pub-purifier lock or update to change locked dependencies')
            get_args=[]
            if command[:2]==['pub','get']:
                get_args=command[2:]
                # Directory selection was handled above; it must not override
                # the staging directory passed to the native command.
                filtered=[];iterator=iter(get_args)
                for arg in iterator:
                    if arg in ('--directory','-C'):next(iterator,None)
                    elif arg in ('--no-offline','--offline=false'):
                        raise ValueError('locked pub get requires offline resolution; use pub-purifier update to resolve new versions')
                    elif not arg.startswith('--directory='):filtered.append(arg)
                get_args=filtered
            cache=prepare(root,native,sidecar,get_args,quiet=command[:2]!=['pub','get'])
            if command[:2]==['pub','get']:return 0
            os.environ.update(PUB_CACHE=str(cache),DART_SUPPRESS_ANALYTICS='true')
            os.execv(tool(),[tool(),*command])
    except (ValueError,OSError,KeyError,TypeError,yaml.YAMLError) as error:
        print(f'pub-purifier: {error}',file=sys.stderr);return 1
    except subprocess.CalledProcessError as error:return max(error.returncode,1)
    return 0
if __name__=='__main__':sys.exit(main())
