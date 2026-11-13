# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import tempfile
import unittest
import yaml
from pub_purifier.path_sources import stage_sources


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.owner=self.base/'owner';self.project=self.owner/'app'
        self.project.mkdir(parents=True);self.provider=self.base/'provider';self.provider.mkdir()
        self.original={'name':'app','version':'0.0.1','environment':{'sdk':'>=3.0.0 <4.0.0'},
                       'dependencies':{'provided':{'path':'/unavailable/previous-source','version':'>=0.0.1'}},
                       'description':'original nonlocation data'}
        (self.project/'pubspec.yaml').write_text(yaml.safe_dump(self.original))
        (self.provider/'pubspec.yaml').write_text('name: provided\nversion: 0.0.2\n')
        (self.provider/'code.dart').write_text('const answer=42;\n');(self.provider/'code.dart').chmod(0o755)
        (self.provider/'alias.dart').symlink_to('code.dart')
        (self.provider/'absolute.dart').symlink_to(self.provider/'code.dart')

    def stage(self):
        return stage_sources(self.owner,self.project,[self.provider],self.base/'stage',self.base/'absent.lock')

    def test_current_provider_locations_only(self):
        project=self.stage();staged=yaml.safe_load((project/'pubspec.yaml').read_text())
        selected=(project/staged['dependencies']['provided']['path']).resolve()
        self.assertEqual(selected,self.base/'stage/1')
        staged['dependencies']['provided']['path']=self.original['dependencies']['provided']['path']
        self.assertEqual(staged,self.original)
        self.assertEqual(yaml.safe_load((self.project/'pubspec.yaml').read_text()),self.original)
        self.assertEqual((selected/'code.dart').read_bytes(),(self.provider/'code.dart').read_bytes())
        self.assertEqual((selected/'code.dart').stat().st_mode & 0o777,0o755)
        self.assertTrue((selected/'alias.dart').is_symlink())
        self.assertTrue((selected/'absolute.dart').is_symlink())
        self.assertEqual((selected/'absolute.dart').resolve(),selected/'code.dart')

    def test_hosted_conflict_not_overridden(self):
        self.original['dependencies']['provided']='^0.0.1'
        (self.project/'pubspec.yaml').write_text(yaml.safe_dump(self.original))
        project=self.stage()
        self.assertEqual(yaml.safe_load((project/'pubspec.yaml').read_text()),self.original)
        self.assertFalse((project/'pubspec_overrides.yaml').exists())

    def test_escaping_symlink_rejected(self):
        (self.provider/'escape').symlink_to(self.base)
        with self.assertRaisesRegex(ValueError,'symlink escapes'):self.stage()

    def test_undeclared_path_rejected(self):
        self.original['dependencies']['other']={'path':str(self.base)}
        (self.project/'pubspec.yaml').write_text(yaml.safe_dump(self.original))
        with self.assertRaisesRegex(ValueError,'escapes declared'):self.stage()

    def test_duplicate_provider_native_name_rejected(self):
        other=self.base/'other';other.mkdir();(other/'pubspec.yaml').write_text('name: provided\nversion: 0.0.3\n')
        with self.assertRaisesRegex(ValueError,'duplicate provided'):
            stage_sources(self.owner,self.project,[self.provider,other],self.base/'stage',self.base/'absent.lock')

    def test_existing_cli_state_is_excluded(self):
        state=self.owner/'.pub-purifier/previous/project';state.mkdir(parents=True)
        (state/'pubspec.yaml').write_text('name: previous\ndependencies:\n  missing:\n    path: /outside\n')
        self.stage()
        self.assertFalse((self.base/'stage/0/.pub-purifier').exists())
