# SPDX-License-Identifier: MIT
{
  project,
  lockFile,
  pubLock,
  target,
}:
let
  pkgs = import (builtins.toPath "@nixpkgs@") { };
  purifier = import (builtins.toPath "@purifier@/nix/lib") { inherit (pkgs) lib; };
  args = {
    src = /. + project;
    lockFile = /. + lockFile;
    pubLock = /. + pubLock;
  };
  result = pkgs.callPackage ./build-project.nix { inherit purifier; } args;
in
if target == "cache" then
  result.cache
else if target == "runtime" then
  pkgs.runCommand "pub-runtime" { } ''ln -s @runtime@ "$out"''
else if target == "release" then
  result.release
else
  throw "pub-purifier: unknown realization target ${target}"
