# SPDX-License-Identifier: MIT
{ lib }:
args@{
  src,
  lockFile ? src + "/pub-purifier.lock.json",
  pubLock ? src + "/pubspec.lock",
}:
let
  generatedSeed = builtins.any (value: value ? outputs || value ? allOutputs) (
    builtins.attrValues (builtins.getContext (toString pubLock))
  );
  portable =
    if builtins.pathExists lockFile then
      builtins.addErrorContext "pub-purifier: cannot parse companion lock; run pub-purifier lock" (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
in
if builtins.isAttrs portable && (portable.version or null) == 2 then
  (import ./hosted-lock.nix { inherit lib; }) {
    data = portable;
    validateNative = !generatedSeed;
    native =
      if !generatedSeed && builtins.pathExists pubLock then
        (import ./native-lock.nix { inherit lib; }) pubLock
      else
        null;
  }
else
  (import ./read-lock-v1.nix { inherit lib; }) args
