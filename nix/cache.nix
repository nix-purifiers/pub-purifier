# SPDX-License-Identifier: MIT
{
  lib,
  runCommand,
  fetchurl,
  gnutar,
  gzip,
  purifier,
}:
{
  lock,
  fetchers ? { },
}:
let
  checked = purifier.checkLock lock;
  archives = purifier.tree (
    {
      name = "pub-archives";
      entries = checked.entries;
      inherit runCommand fetchurl;
    }
    // fetchers
  );
  install = lib.concatMapStringsSep "\n" (
    name:
    let
      p = checked.packages.${name};
      dir = "${p.cacheKey}/${name}-${p.version}";
    in
    ''
      mkdir -p "$out/hosted/${dir}" "$out/hosted-hashes/${p.cacheKey}"
      tar -xzf ${archives}/${name}-${p.version}.tar.gz -C "$out/hosted/${dir}"
      printf '%s' ${lib.escapeShellArg p.description.sha256} > "$out/hosted-hashes/${dir}.sha256"
      test -f "$out/hosted/${dir}/pubspec.yaml"
    ''
  ) (builtins.attrNames checked.packages);
in
runCommand "purified-pub-cache"
  {
    nativeBuildInputs = [
      gnutar
      gzip
    ];
  }
  ''
    mkdir -p "$out/hosted" "$out/hosted-hashes"
    ${install}
  ''
