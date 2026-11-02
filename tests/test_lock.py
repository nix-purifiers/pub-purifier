# SPDX-License-Identifier: MIT
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pub_purifier import lock
SOURCE=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.root.joinpath('pubspec.yaml').write_text('name: example\n')
        self.native=self.root/'pubspec.lock'
        self.native.write_text('packages:\n  demo:\n    source: hosted\n    version: "1.0.0"\n    description:\n      name: demo\n      sha256: "'+'a'*64+'"\n      url: "https://pub.dev"\n')
        self.data=lock.seal({'version':1,'inputs':{'manifest':lock.file_hash(self.root/'pubspec.yaml'),'native':lock.file_hash(self.native),'overrides':None},'sdkVersion':'3.13.0','archives':{'demo':'https://pub.dev/api/archives/demo-1.0.0.tar.gz'},'outputs':{}})
    def test_valid(self):self.assertEqual(lock.problems(self.root,self.native,self.data),[])
    def test_stale(self):
        self.root.joinpath('pubspec.yaml').write_text('name: changed\n');self.assertTrue(lock.problems(self.root,self.native,self.data))
    def test_overrides_stale(self):
        self.root.joinpath('pubspec_overrides.yaml').write_text('dependency_overrides: {}\n');self.assertTrue(lock.problems(self.root,self.native,self.data))
    def test_tampered(self):
        self.data['archives']={};self.assertTrue(lock.problems(self.root,self.native,self.data))
    def test_missing(self):
        self.data['archives']={};self.assertTrue(lock.problems(self.root,self.native,lock.seal(self.data)))
    def test_unexpected_entries(self):
        self.data['archives']['other']='https://example.com/x';self.assertTrue(lock.problems(self.root,self.native,lock.seal(self.data)))
    def test_credentials_rejected(self):
        self.data['archives']['demo']='https://user:password@example.com/a';self.assertTrue(lock.problems(self.root,self.native,lock.seal(self.data)))
    def test_output_traversal(self):
        self.data['outputs']={'escape':{'file':'../outside.dart'}};self.assertTrue(lock.problems(self.root,self.native,lock.seal(self.data)))
    def test_cache_encoding(self):
        for url,key in [('https://pub.dev','pub.dev'),('http://127.0.0.1:1234','localhost%581234'),('http://example.com/path','http%58%47%47example.com%47path')]:self.assertEqual(lock.cache_key(url),key)
    def test_no_lock_fallback(self):
        tool=self.root/'tool';tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nprintf "native stderr\\n" >&2\nexit 23\n');tool.chmod(0o755)
        result=subprocess.run([sys.executable,'-m','pub_purifier.cli','native','--','run','a b.dart'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'PUB_PURIFIER_DART':str(tool)},capture_output=True,text=True)
        self.assertEqual(result.returncode,23);self.assertEqual(result.stdout,'run\na b.dart\n');self.assertIn('warning: no lockfile',result.stderr);self.assertIn('native stderr',result.stderr)
    def test_invalid_lock_fails_without_exec(self):
        self.root.joinpath('pub-purifier.lock.json').write_text('{}')
        result=subprocess.run([sys.executable,'-m','pub_purifier.cli','native','--','run','hello.dart'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'PUB_PURIFIER_DART':'/does/not/exist'},capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('unsupported lock format',result.stderr);self.assertNotIn('warning: no lockfile',result.stderr)
