# SPDX-License-Identifier: MIT
"""Portable captures admit current native sources, never uncaptured hosted identities."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from pub_purifier import hosted, lock


class PathLockTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'version':'1.2.3','registry':'https://pub.dev',
                         'sha256':'a'*64,'archiveUrl':'https://pub.dev/a.tar.gz'}
        self.data = lock.seal({'version':2,'hosted':{'demo':self.identity},'outputs':{}})

    def test_active_identity_and_unused_capture(self):
        hosted.verify_active(self.data, {'packages':{}})
        hosted.verify_active(self.data, {'packages':{'demo':{'source':'hosted','version':'1.2.3',
            'description':{'name':'demo','url':'https://pub.dev','sha256':'a'*64}},
            'provided':{'source':'path','version':'99.0.0','description':{'path':'/current/source'}}}})

    def test_active_hosted_changes_rejected(self):
        original={'source':'hosted','version':'1.2.3',
                  'description':{'name':'demo','url':'https://pub.dev','sha256':'a'*64}}
        for field, value in [('version','1.2.4'),('url','https://other.example'),('sha256','b'*64),('name','other')]:
            package=copy.deepcopy(original)
            if field=='version':package[field]=value
            else:package['description'][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                hosted.verify_active(self.data,{'packages':{'demo':package}})
        with self.assertRaises(ValueError):
            hosted.verify_active(self.data,{'packages':{'uncaptured':original}})

    def test_closed_schema_python_nix_parity(self):
        source=Path(__file__).resolve().parents[1]
        nixlib=os.environ.get('NIXPKGS_LIB')
        if not nixlib:self.skipTest('NIXPKGS_LIB required for independent Nix reader')
        vectors=[(self.data,True)]
        for mutation in (
            lambda d:d.update(sdkVersion='3.13.0'),
            lambda d:d.update(pathSources={}),
            lambda d:d.update(version=True),
            lambda d:d['hosted']['demo'].update(sourceTreeHash='a'*64),
            lambda d:d['hosted']['demo'].update(archiveUrl='https://user:pass@example.org/a'),
            lambda d:d['hosted']['demo'].update(sha256='bad'),
            lambda d:d.update(outputs={'escape':{'file':'../main.dart'}}),
            lambda d:d.update(outputs={'main':{'file':'bin/main.dart','sdk':'forced'}}),
        ):
            data=copy.deepcopy(self.data);mutation(data);vectors.append((lock.seal(data),False))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock.json'
            for data,expected in vectors:
                try:hosted.validate(data);python_ok=True
                except (ValueError,TypeError):python_ok=False
                path.write_text(json.dumps(data))
                expr=f'''let lib=import {nixlib}; read=import {source}/lib-overlays/default/hosted-lock.nix {{inherit lib;}};
                in (read {{data=builtins.fromJSON (builtins.readFile {path});}}).problems'''
                result=subprocess.run(['nix-instantiate','--eval','--strict','--json','--expr',expr],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((python_ok,json.loads(result.stdout)==[]),(expected,expected),data)

    def test_native_seed_shape_python_nix_parity(self):
        nixlib=os.environ.get('NIXPKGS_LIB')
        if not nixlib:self.skipTest('NIXPKGS_LIB required')
        source=Path(__file__).resolve().parents[1]
        valid={'packages':{'oldprovided':{'version':'0.0.1','source':'path','description':{'path':'/unavailable/previous','relative':False}}}}
        vectors=[(valid,True),(None,False),({},False)]
        for mutation in (
            lambda d:d['packages']['oldprovided'].update(source='git'),
            lambda d:d['packages']['oldprovided']['description'].update(relative='false'),
            lambda d:d['packages']['oldprovided'].update(version=1),
        ):
            value=copy.deepcopy(valid);mutation(value);vectors.append((value,False))
        with tempfile.TemporaryDirectory() as folder:
            data_path=Path(folder)/'capture.json';data_path.write_text(json.dumps(self.data))
            seed=Path(folder)/'seed.json'
            for value,expected in vectors:
                try:hosted.validate_seed(value);python_ok=True
                except (ValueError,TypeError):python_ok=False
                seed.write_text(json.dumps(value))
                expr=f"let lib=import {nixlib}; read=import {source}/lib-overlays/default/hosted-lock.nix {{inherit lib;}}; in (read {{data=builtins.fromJSON (builtins.readFile {data_path}); native=builtins.fromJSON (builtins.readFile {seed});validateNative=true;}}).problems"
                result=subprocess.run(['nix-instantiate','--eval','--strict','--json','--expr',expr],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((python_ok,json.loads(result.stdout)==[]),(expected,expected),value)

    def test_replay_rejects_bad_seed_before_running_sdk(self):
        if not os.environ.get('NIXPKGS_LIB'):self.skipTest('NIXPKGS_LIB required')
        from pub_purifier.materialize import materialize
        from unittest.mock import patch
        import yaml
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);capture=root/'capture.json';capture.write_text(json.dumps(self.data));seed=root/'seed.lock'
            for contents in [None,'{broken',json.dumps({'packages':{'p':{'version':'1.0.0','source':'git','description':{}}}})]:
                if seed.exists():seed.unlink()
                if contents is not None:seed.write_text(contents)
                with patch('pub_purifier.materialize.subprocess.run') as sdk:
                    with self.assertRaises((ValueError,OSError,yaml.YAMLError)):
                        materialize(root,root,[],root/'stage',seed,capture,'/unavailable/sdk')
                    sdk.assert_not_called()
                expr=f"let lib=import {os.environ['NIXPKGS_LIB']}; read=import {Path(__file__).resolve().parents[1]}/lib-overlays/default/read-lock.nix {{inherit lib;}}; in (read {{src={root};lockFile={capture};pubLock={seed};}}).problems"
                result=subprocess.run(['nix-instantiate','--eval','--strict','--json','--expr',expr],capture_output=True,text=True)
                self.assertTrue(result.returncode!=0 or json.loads(result.stdout)!=[],result.stdout)
