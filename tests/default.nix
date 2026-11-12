# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  python = pkgs.python3.withPackages (p: [ p.pyyaml ]);
  fixture = ../examples/hello;
  project = pkgs.pub-purifier.buildPubProject { src = fixture; };
  externalSource = builtins.path {
    path = fixture;
    name = "pub-external-source";
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        "pubspec.lock"
        "pub-purifier.lock.json"
        ".dart_tool"
        ".pub-purifier"
      ]);
  };
  external = pkgs.pub-purifier.buildPubProject {
    src = externalSource;
    pubLock = fixture + "/pubspec.lock";
    lockFile = fixture + "/pub-purifier.lock.json";
  };
  errorCheck =
    case:
    pkgs.runCommand "pub-${case}"
      {
        nativeBuildInputs = [
          python
          pkgs.nix
        ];
        SOURCE = self;
        NIXPKGS_LIB = "${pkgs.path}/lib";
        PURIFIER = self.inputs.purifier;
        PYTHONPATH = self;
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        python ${./eval-errors.py} ${case}
        touch "$out"
      '';
in
{
  browser = import ./browser.nix { inherit pkgs; };
  browser-wasm = import ./browser.nix {
    inherit pkgs;
    target = "wasm";
  };
  environment = project.cache;
  package = project.packages.hello;
  offline = project.tests;
  release = project.release;
  unit = pkgs.runCommand "pub-unit" { nativeBuildInputs = [ python ]; } ''
    cp -r ${self} source
    chmod -R u+w source
    cd source
    python -m unittest discover -s tests -v
    touch "$out"
  '';
  conformance-external = pkgs.runCommand "pub-external-locks" { } ''
    test ! -e ${externalSource}/pubspec.lock
    test ! -e ${externalSource}/pub-purifier.lock.json
    cmp ${external.packages.hello}/bin/hello ${project.packages.hello}/bin/hello
    touch "$out"
  '';
  editor =
    pkgs.runCommand "pub-editor-offline"
      {
        nativeBuildInputs = [
          pkgs.dart
          python
        ];
      }
      ''
        export HOME="$TMPDIR/home" PUB_CACHE="$TMPDIR/cache" DART_SUPPRESS_ANALYTICS=true
        mkdir -p "$HOME" "$PUB_CACHE"
        cp -r ${project.cache}/. "$PUB_CACHE/"
        chmod -R u+w "$PUB_CACHE"
        cp -r ${fixture} project
        chmod -R u+w project
        cd project
        dart pub get --offline --enforce-lockfile --no-example
        python ${./editor.py}
        touch "$out"
      '';
}
// pkgs.lib.genAttrs [
  "conformance-stale"
  "conformance-tampered"
  "conformance-missing"
  "conformance-malformed"
] (name: errorCheck (pkgs.lib.removePrefix "conformance-" name))
