# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  dart,
  gnutar,
  gzip,
  purifier,
  python3,
}:
{
  src,
  lockFile ? src + "/pub-purifier.lock.json",
  pubLock ? src + "/pubspec.lock",
  fetchers ? { },
  browserTargets ? { },
  srcFilter ?
    path: type:
    !(builtins.elem (baseNameOf path) [
      ".git"
      ".dart_tool"
      ".pub-purifier"
      "build"
      "result"
    ]),
  testCommand ? null,
  projectDir ? ".",
  pathSources ? [ ],
}:
let
  lock = purifier.checkLock (
    (import ../../lib-overlays/default/read-lock.nix { inherit lib; }) { inherit src lockFile pubLock; }
  );
  cache =
    (import ./cache.nix {
      inherit
        lib
        runCommand
        fetchurl
        gnutar
        gzip
        purifier
        ;
    })
      { inherit lock fetchers; };
  source =
    if (lock.version or 1) == 2 then
      src
    else
      lib.cleanSourceWith {
        inherit src;
        filter = srcFilter;
      };
  pathMode = (lock.version or 1) == 2;
  verifierPython = python3.withPackages (ps: [ ps.pyyaml ]);
  validRoot =
    value:
    builtins.isString value
    && value != ""
    && !(lib.hasPrefix "/" value)
    && !(lib.hasInfix "\\" value)
    && !(builtins.elem ".." (lib.splitString "/" value));
  sourceReference =
    value:
    builtins.isPath value
    || lib.isDerivation value
    || (builtins.isString value && builtins.hasContext value);
  validSources =
    builtins.isList pathSources
    && builtins.all (
      value:
      builtins.isAttrs value
      && value ? src
      && sourceReference value.src
      && validRoot (value.root or ".")
      && builtins.all (
        key:
        builtins.elem key [
          "src"
          "root"
        ]
      ) (builtins.attrNames value)
    ) pathSources;
  setup =
    if pathMode then
      ''
        export HOME="$TMPDIR/home" PUB_CACHE="$TMPDIR/pub-cache" DART_SUPPRESS_ANALYTICS=true
        mkdir -p "$HOME" "$PUB_CACHE"
        cp -r ${cache}/. "$PUB_CACHE/"
        chmod -R u+w "$PUB_CACHE"
        export PYTHONPATH=${../..}
        ${verifierPython}/bin/python -m pub_purifier.materialize \
          --source-root ${lib.escapeShellArg "${source}"} \
          --project ${lib.escapeShellArg "${source}/${projectDir}"} \
          ${
            lib.concatMapStringsSep " " (
              value: "--path-source-root " + lib.escapeShellArg "${value.src}/${value.root or "."}"
            ) pathSources
          } \
          --destination "$TMPDIR/staged" --native ${pubLock} --capture ${lockFile} \
          --dart ${dart}/bin/dart --result-file "$TMPDIR/project-path" --receipt "$TMPDIR/pub-materialization.json"
        cd "$(cat "$TMPDIR/project-path")"
      ''
    else
      ''
        export HOME="$TMPDIR/home" PUB_CACHE="$TMPDIR/pub-cache" DART_SUPPRESS_ANALYTICS=true
        mkdir -p "$HOME" "$PUB_CACHE" work
        cp -r ${cache}/. "$PUB_CACHE/"
        chmod -R u+w "$PUB_CACHE"
        cp -r ${source}/. work/
        chmod -R u+w work
        cp ${pubLock} work/pubspec.lock
        cd work
        dart pub get --offline --enforce-lockfile --no-example
      '';
  nativePackages = lib.mapAttrs (
    name: spec:
    runCommand "pub-${name}" { nativeBuildInputs = [ dart ]; } ''
      ${setup}
      mkdir -p "$out/bin"
      dart compile exe ${lib.escapeShellArg spec.file} -o "$out/bin/${name}"
    ''
  ) lock.outputs;
  relative =
    path:
    builtins.isString path
    && path != ""
    && !(lib.hasPrefix "/" path)
    && !(lib.hasInfix "\\" path)
    && builtins.all (part: part != "" && part != "." && part != "..") (lib.splitString "/" path);
  coordinate =
    value: builtins.isString value && builtins.match "[A-Za-z0-9_][A-Za-z0-9_.-]*" value != null;
  validTarget =
    target:
    builtins.isAttrs target
    && builtins.all (
      key:
      builtins.elem key [
        "entrypoint"
        "target"
        "assets"
        "webjar"
      ]
    ) (builtins.attrNames target)
    && builtins.elem (target.target or "javascript") [
      "javascript"
      "wasm"
    ]
    && relative (target.entrypoint or null)
    && lib.hasSuffix ".dart" target.entrypoint
    && builtins.isAttrs (target.assets or { })
    && builtins.all (
      path:
      relative path
      && !(builtins.elem path [
        "main.js"
        "main.mjs"
        "main.wasm"
        "main.support.js"
      ])
      && relative target.assets.${path}
    ) (builtins.attrNames (target.assets or { }))
    && (
      (target.webjar or null) == null
      || (
        builtins.isAttrs target.webjar
        && builtins.all (
          key:
          builtins.elem key [
            "artifactId"
            "version"
            "groupId"
          ]
        ) (builtins.attrNames target.webjar)
        && coordinate (target.webjar.artifactId or null)
        && coordinate (target.webjar.version or null)
        && coordinate (target.webjar.groupId or "org.webjars.npm")
      )
    );
  validTargets =
    builtins.isAttrs browserTargets
    && builtins.all (name: coordinate name && validTarget browserTargets.${name}) (
      builtins.attrNames browserTargets
    );
  browserArtifacts = lib.mapAttrs (
    name: target:
    runCommand "pub-browser-${name}"
      {
        outputs = [
          "out"
          "proof"
        ];
        nativeBuildInputs = [
          dart
          python3
        ];
        spec = builtins.toJSON target;
        passAsFile = [ "spec" ];
      }
      ''
            ${setup}
            export SOURCE_DATE_EPOCH=1 TZ=UTC
            mkdir -p "$TMPDIR/compiled" "$out" "$proof"
          python3 ${./browser-output.py} validate "$PWD" "$specPath"
            dart --version > "$proof/compiler-version.txt"
        ${
          if (target.target or "javascript") == "wasm" then
            ''
              dart compile wasm --no-source-maps ${lib.escapeShellArg target.entrypoint} --output="$TMPDIR/compiled/main.wasm"
            ''
          else
            ''
              dart compile js -O2 --no-source-maps ${lib.escapeShellArg target.entrypoint} --output="$TMPDIR/compiled/main.js"
            ''
        }
        python3 ${./browser-output.py} "$PWD" "$TMPDIR/compiled" "$specPath" "$out" "$proof" ${dart}
      ''
  ) browserTargets;
  browser = lib.mapAttrs (
    name: artifact:
    artifact
    // {
      projections =
        (purifier.resourceProjections {
          producer = artifact;
          roots."." = ".";
          inherit runCommand python3;
        })
        // lib.optionalAttrs ((browserTargets.${name}.webjar or null) != null) (
          purifier.webjarProjections (
            browserTargets.${name}.webjar
            // {
              producer = artifact;
              assets = artifact;
              inherit runCommand python3;
            }
          )
        );
    }
  ) browserArtifacts;
  projections = lib.mapAttrs (_: artifact: artifact.projections) browser;
  browserPackages = lib.mapAttrs' (
    name: artifact: lib.nameValuePair "browser-${name}" artifact
  ) browser;
  packages = nativePackages // browserPackages;
  tests = runCommand "pub-project-tests" { nativeBuildInputs = [ dart ]; } ''
    ${setup}
    ${
      if testCommand != null then
        testCommand
      else
        ''
          dart analyze --fatal-infos
          ${
            if pathMode then
              ''
                if [ -f test/check.dart ]; then
                  dart run test/check.dart
                elif ${verifierPython}/bin/python -c 'import yaml; raise SystemExit(0 if "test" in yaml.safe_load(open("pubspec.lock"))["packages"] else 1)'; then
                  dart test
                fi
              ''
            else if builtins.pathExists (src + "/test/check.dart") then
              "dart run test/check.dart"
            else if builtins.hasAttr "test" lock.packages then
              "dart test"
            else
              ""
          }
        ''
    }
    ${if pathMode then ''cp "$TMPDIR/pub-materialization.json" "$out"'' else ''touch "$out"''}
  '';
  release =
    if pathMode then
      runCommand "pub-path-release"
        {
          nativeBuildInputs = [
            dart
            gnutar
            gzip
          ];
        }
        ''
          test -e ${tests}
          ${setup}
          mkdir -p "$out"
          rm -f pub-purifier.lock.json
          cp ${lockFile} pub-purifier.lock.json
          ${verifierPython}/bin/python -c 'import pathlib,shutil; root=pathlib.Path("'"$TMPDIR"'/staged"); [shutil.rmtree(p) for p in root.rglob(".dart_tool") if p.is_dir() and not p.is_symlink()]'
          tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
            -C "$TMPDIR/staged" -cf - . | gzip -n > "$out/source.tar.gz"
          ${lib.concatMapStringsSep "\n" (name: ''
            tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C ${packages.${name}} -cf - . | gzip -n > "$out/${name}.tar.gz"
          '') (builtins.attrNames packages)}
        ''
    else
      runCommand "pub-release"
        {
          nativeBuildInputs = [
            gnutar
            gzip
          ];
        }
        ''
            test -e ${tests}
            mkdir -p "$out"
          mkdir -p "$TMPDIR/source"
          cp -r ${source}/. "$TMPDIR/source/"
          chmod -R u+w "$TMPDIR/source"
          cp ${pubLock} "$TMPDIR/source/pubspec.lock"
          cp ${lockFile} "$TMPDIR/source/pub-purifier.lock.json"
          tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner \
            -C "$TMPDIR/source" -cf - . | gzip -n > "$out/source.tar.gz"
            ${lib.concatMapStringsSep "\n" (
              name:
              ''tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C ${packages.${name}} -cf - . | gzip -n > "$out/${name}.tar.gz"''
            ) (builtins.attrNames packages)}
        '';
in
assert lib.assertMsg (
  validRoot projectDir && validSources && (!pathMode || sourceReference src)
) "pub-purifier: invalid source owner references";
assert lib.assertMsg validTargets
  "pub-purifier: browserTargets requires named Dart entrypoints, relative public assets and optional explicit WebJar coordinates";
assert lib.assertMsg (builtins.all (name: !(builtins.hasAttr name nativePackages)) (
  builtins.attrNames browserPackages
)) "pub-purifier: browser package collides with a native executable";
assert
  pathMode
  || lock.sdkVersion == dart.version
  || throw "pub-purifier: locked Dart SDK ${lock.sdkVersion} differs from ${dart.version}; override the scope's dart or regenerate the lock with the intended SDK";
{
  inherit packages tests release;
  inherit browser projections;
  fetches = lock.entries;
  inherit cache;
}
