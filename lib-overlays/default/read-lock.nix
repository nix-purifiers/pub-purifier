# SPDX-License-Identifier: MIT
{ lib }:
args@{
  src,
  lockFile ? src + "/pub-purifier.lock.json",
  pubLock ? src + "/pubspec.lock",
}:
let
  portable =
    if builtins.pathExists lockFile then
      builtins.addErrorContext "pub-purifier: cannot parse companion lock; run pub-purifier lock" (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
in
if builtins.isAttrs portable && (portable.version or null) == 2 then
  (import ./hosted-lock.nix { inherit lib; }) { data = portable; }
else
  (import ./read-lock-v1.nix { inherit lib; }) args
