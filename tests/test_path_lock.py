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
