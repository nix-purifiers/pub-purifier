#!/usr/bin/env python3
"""Actual native build rejection controls for selected Dart browser targets."""
from pathlib import Path
import json, os, shutil, subprocess, tempfile
repo=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='pub-browser-negative-') as temporary:
    src=Path(temporary)/'source';shutil.copytree(repo/'tests/fixtures/browser42',src)
    (src/'web/outside.css').symlink_to('/etc/passwd')
    (src/'web/ffi.dart').write_text("import 'dart:ffi';\nvoid main(){print(DynamicLibrary.process());}\n")
    cases=[
        ('missing-entry',dict(entrypoint='web/missing.dart'),'web/missing.dart'),
        ('escaping-asset',dict(entrypoint='web/main.dart',assets={'outside.css':'web/outside.css'}),'browser input escapes project source'),
        ('native-ffi-entry',dict(entrypoint='web/ffi.dart'),'dart:ffi'),
        ('compiled-part-collision',dict(entrypoint='web/main.dart',assets={'main.js_1.part.js':'web/style.css'}),'public asset collides with native browser output'),
    ]
    results=[]
    for name,target,error in cases:
        expression='let f=builtins.getFlake '+json.dumps(str(repo))+'; p=import f.inputs.nixpkgs {system=builtins.currentSystem;overlays=[f.overlays.default];};in (p.pub-purifier.buildPubProject {src=/. + '+json.dumps(str(src))+';browserTargets.site=builtins.fromJSON '+json.dumps(json.dumps(target))+';}).browser.site'
        result=subprocess.run(['nix','build','--impure','--no-link','-L','--expr',expression],capture_output=True,text=True)
        print(result.stderr)
        assert result.returncode and error in result.stderr,(name,result)
        results.append(dict(case=name,rejected=True))
    if os.environ.get('PUB_BROWSER_NEGATIVE_EVIDENCE'):
        Path(os.environ['PUB_BROWSER_NEGATIVE_EVIDENCE']).write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results))
