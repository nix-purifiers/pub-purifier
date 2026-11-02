# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  dart,
  gnutar,
  gzip,
  purifier,
}:
{
  src,
  lockFile ? src + "/pub-purifier.lock.json",
  pubLock ? src + "/pubspec.lock",
  fetchers ? { },
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
}:
let
  lock = purifier.checkLock (
    (import ./read-lock.nix { inherit lib; }) { inherit src lockFile pubLock; }
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
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  setup = ''
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
  packages = lib.mapAttrs (
    name: spec:
    runCommand "pub-${name}" { nativeBuildInputs = [ dart ]; } ''
      ${setup}
      mkdir -p "$out/bin"
      dart compile exe ${lib.escapeShellArg spec.file} -o "$out/bin/${name}"
    ''
  ) lock.outputs;
  tests = runCommand "pub-project-tests" { nativeBuildInputs = [ dart ]; } ''
    ${setup}
    ${
      if testCommand != null then
        testCommand
      else
        ''
          dart analyze --fatal-infos
          ${
            if builtins.pathExists (src + "/test/check.dart") then
              "dart run test/check.dart"
            else if builtins.hasAttr "test" lock.packages then
              "dart test"
            else
              ""
          }
        ''
    }
    touch "$out"
  '';
  release =
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
assert
  lock.sdkVersion == dart.version
  || throw "pub-purifier: locked Dart SDK ${lock.sdkVersion} differs from ${dart.version}; override the scope's dart or regenerate the lock with the intended SDK";
{
  inherit packages tests release;
  fetches = lock.entries;
  inherit cache;
}
