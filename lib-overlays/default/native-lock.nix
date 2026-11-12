# SPDX-License-Identifier: MIT
# Parse the indentation schema emitted by Dart pub, without running a builder.
{ lib }:
path:
let
  text = builtins.readFile path;
  fail = throw "pub-purifier: unsupported pubspec.lock syntax; run pub-purifier lock";
  scalar =
    raw:
    let
      s = lib.trim raw;
    in
    if
      lib.hasPrefix "\"" s
      || builtins.elem s [
        "true"
        "false"
      ]
    then
      builtins.fromJSON s
    else if lib.hasPrefix "'" s && lib.hasSuffix "'" s then
      lib.replaceStrings [ "''" ] [ "'" ] (builtins.substring 1 (builtins.stringLength s - 2) s)
    else if builtins.match "[A-Za-z0-9_./+@:=<>~-]+" s != null then
      s
    else
      fail;
  set =
    attrs: key: value:
    if builtins.hasAttr key attrs then fail else attrs // { ${key} = value; };
  lines = lib.filter (s: lib.trim s != "" && !(lib.hasPrefix "#" (lib.trim s))) (
    lib.splitString "\n" text
  );
  state =
    builtins.foldl'
      (
        state: line:
        let
          top = builtins.match "(packages|sdks):([ ]*|[ ]+[{][}])" line;
          package = builtins.match "  ([A-Za-z_][A-Za-z0-9_]*):" line;
          field = builtins.match "    ([A-Za-z][A-Za-z0-9_-]*):[ ]*(.*)" line;
          nested = builtins.match "      ([A-Za-z][A-Za-z0-9_-]*):[ ]*(.*)" line;
        in
        if top != null then
          state
          // {
            section = builtins.head top;
            current = null;
          }
        else if state.section == "sdks" then
          if builtins.match "  [A-Za-z][A-Za-z0-9_-]*:[ ]+.*" line == null then fail else state
        else if state.section != "packages" then
          fail
        else if package != null then
          let
            name = builtins.head package;
          in
          state
          // {
            current = name;
            description = false;
            packages = set state.packages name { };
          }
        else if state.current == null then
          fail
        else if field != null then
          let
            key = builtins.head field;
            raw = builtins.elemAt field 1;
          in
          state
          // {
            description = key == "description" && raw == "";
            packages = state.packages // {
              ${state.current} = set state.packages.${state.current} key (if raw == "" then { } else scalar raw);
            };
          }
        else if nested != null && state.description then
          state
          // {
            packages = state.packages // {
              ${state.current} = state.packages.${state.current} // {
                description = set state.packages.${state.current}.description (builtins.head nested) (
                  scalar (builtins.elemAt nested 1)
                );
              };
            };
          }
        else
          fail
      )
      {
        section = null;
        current = null;
        description = false;
        packages = { };
      }
      lines;
in
if lib.hasPrefix "{" (lib.trim text) then builtins.fromJSON text else { inherit (state) packages; }
