# SPDX-License-Identifier: MIT
{ lib }:
{ data }:
let
  attrs = builtins.isAttrs;
  keys =
    value: expected:
    attrs value && builtins.attrNames value == builtins.sort builtins.lessThan expected;
  matches = pattern: value: builtins.isString value && builtins.match pattern value != null;
  urlOK = value: matches "https?://([A-Za-z0-9.-]+|[[][0-9A-Fa-f:.]+[]])(:[0-9]+)?([/?][^#]*)?" value;
  hosted = data.hosted or { };
  outputs = data.outputs or { };
  identityOK =
    name:
    let
      value = hosted.${name};
    in
    matches "[A-Za-z_][A-Za-z0-9_]*" name
    && keys value [
      "version"
      "registry"
      "sha256"
      "archiveUrl"
    ]
    && matches "[0-9][A-Za-z0-9.+-]*" value.version
    && matches "[0-9a-f]{64}" value.sha256
    && urlOK value.registry
    && urlOK value.archiveUrl;
  outputOK =
    name:
    let
      value = outputs.${name};
    in
    matches "[A-Za-z0-9][A-Za-z0-9_-]*" name
    && keys value [ "file" ]
    && matches "[A-Za-z0-9_./-]+[.]dart" value.file
    && !(lib.hasPrefix "/" value.file)
    && !(builtins.elem ".." (lib.splitString "/" value.file));
  problems =
    if
      !(keys data [
        "version"
        "hosted"
        "outputs"
        "contentHash"
      ])
      || data.version != 2
    then
      [ "invalid closed version 2 lock" ]
    else if
      data.contentHash
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if !(attrs hosted) || !(builtins.all identityOK (builtins.attrNames hosted)) then
      [ "invalid hosted identities" ]
    else if !(attrs outputs) || !(builtins.all outputOK (builtins.attrNames outputs)) then
      [ "invalid output entry points" ]
    else
      [ ];
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
in
{
  purifier = "pub-purifier";
  version = 2;
  inherit outputs;
  problems = map (message: "pub-purifier: ${message}") problems;
  packages =
    if problems != [ ] then
      { }
    else
      lib.mapAttrs (name: value: {
        inherit (value) version;
        source = "hosted";
        description = {
          inherit name;
          url = value.registry;
          inherit (value) sha256;
        };
        cacheKey = cacheKey value.registry;
      }) hosted;
  entries =
    if problems != [ ] then
      [ ]
    else
      lib.mapAttrsToList (name: value: {
        path = "${name}-${value.version}.tar.gz";
        url = value.archiveUrl;
        hash = builtins.convertHash {
          hash = value.sha256;
          hashAlgo = "sha256";
          toHashFormat = "sri";
        };
        mirrors = [ ];
      }) hosted;
}
