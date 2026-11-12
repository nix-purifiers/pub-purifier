# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/pub-purifier.lock.json",
  pubLock ? src + "/pubspec.lock",
}:
let
  problem =
    message:
    "pub-purifier: ${message}; run pub-purifier lock (use --lockfile and --pub-lock for external locks)";
  exists =
    builtins.pathExists lockFile
    && builtins.pathExists pubLock
    && builtins.pathExists (src + "/pubspec.yaml");
  data =
    if exists then
      builtins.addErrorContext (problem "cannot parse companion lock") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  native = if exists then (import ./native-lock.nix { inherit lib; }) pubLock else { };
  packages = native.packages or { };
  names = builtins.attrNames packages;
  archives = data.archives or { };
  urlOK =
    s:
    let
      match = if builtins.isString s then builtins.match "https?://([^/?#]+)([^#]*)" s else null;
    in
    match != null && !(lib.hasInfix "@" (builtins.head match));
  packageOK =
    name:
    let
      p = packages.${name};
      d = p.description or { };
    in
    builtins.match "[A-Za-z_][A-Za-z0-9_]*" name != null
    && builtins.isAttrs p
    && (p.source or null) == "hosted"
    && builtins.isAttrs d
    && (d.name or null) == name
    && urlOK (d.url or null)
    && builtins.isString (d.sha256 or null)
    && builtins.match "[0-9a-f]{64}" d.sha256 != null
    && builtins.isString (p.version or null)
    && builtins.match "[0-9][A-Za-z0-9.+-]*" p.version != null
    && urlOK (archives.${name} or null);
  outputs = data.outputs or { };
  outputOK =
    name:
    builtins.match "[A-Za-z0-9][A-Za-z0-9_-]*" name != null
    && builtins.isAttrs outputs.${name}
    && builtins.isString (outputs.${name}.file or null)
    && builtins.match "[A-Za-z0-9_./-]+[.]dart" outputs.${name}.file != null
    && !(lib.hasPrefix "/" outputs.${name}.file)
    && !(builtins.elem ".." (lib.splitString "/" outputs.${name}.file))
    && builtins.pathExists (src + "/${outputs.${name}.file}");
  overrides = src + "/pubspec_overrides.yaml";
  problems = map problem (
    if !exists then
      [ "missing manifest or lockfile" ]
    else if !builtins.isAttrs data || (data.version or null) != 1 then
      [ "unsupported lock format" ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if
      (data.inputs.manifest or null) != builtins.hashFile "sha256" (src + "/pubspec.yaml")
      || (data.inputs.native or null) != builtins.hashFile "sha256" pubLock
    then
      [ "manifest or native lock changed after locking" ]
    else if
      (data.inputs.overrides or null)
      != (if builtins.pathExists overrides then builtins.hashFile "sha256" overrides else null)
    then
      [ "overrides changed after locking" ]
    else if !builtins.isString (data.sdkVersion or null) then
      [ "missing SDK version" ]
    else if !builtins.isAttrs packages || !builtins.isAttrs archives then
      [ "invalid package maps" ]
    else if !builtins.all packageOK names then
      [ "invalid or missing hosted package entries; only hosted sources are currently supported" ]
    else if builtins.attrNames archives != names then
      [ "unexpected archive entries" ]
    else if !builtins.isAttrs outputs || !builtins.all outputOK (builtins.attrNames outputs) then
      [ "invalid output entry points" ]
    else
      [ ]
  );
  # Match pub's _urlToDirectory, including decimal character escapes.
  cacheKey =
    url:
    let
      match = builtins.match "(https?://)(127[.]0[.]0[.]1|[[]::1[]]|localhost)?(.*)" url;
      loopback = builtins.elemAt match 1 != null;
      normalized =
        (if builtins.head match == "https://" || loopback then "" else builtins.head match)
        + (if loopback then "localhost" else "")
        + builtins.elemAt match 2;
    in
    lib.replaceStrings
      [
        "<"
        ">"
        ":"
        "\""
        "\\"
        "/"
        "|"
        "?"
        "*"
        "%"
      ]
      [
        "%60"
        "%62"
        "%58"
        "%34"
        "%92"
        "%47"
        "%124"
        "%63"
        "%42"
        "%37"
      ]
      normalized;
  usable = problems == [ ];
in
{
  purifier = "pub-purifier";
  inherit problems;
  inherit outputs;
  sdkVersion = data.sdkVersion or "";
  packages =
    if usable then
      lib.mapAttrs (name: p: p // { cacheKey = cacheKey p.description.url; }) packages
    else
      { };
  entries =
    if !usable then
      [ ]
    else
      map (name: {
        path = "${name}-${packages.${name}.version}.tar.gz";
        url = archives.${name};
        hash = builtins.convertHash {
          hash = packages.${name}.description.sha256;
          hashAlgo = "sha256";
          toHashFormat = "sri";
        };
        mirrors = [ ];
      }) names;
}
