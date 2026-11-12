{
  pkgs,
  target ? "javascript",
}:
let
  make =
    src:
    pkgs.pub-purifier.buildPubProject {
      inherit src;
      browserTargets.site = {
        inherit target;
        entrypoint = "web/main.dart";
        assets = {
          "index.html" = if target == "wasm" then "web/index-wasm.html" else "web/index.html";
          "style.css" = "web/style.css";
        };
        webjar = {
          groupId = "org.webjars.dart";
          artifactId = "answer-${target}";
          version = "1.0.0";
        };
      };
    };
  first = make ./fixtures/browser42;
  second = make ./fixtures/browser43;
  record = built: value: {
    inherit value;
    artifact = toString built.browser.site;
    proof = toString built.browser.site.proof;
    web = toString built.projections.site.web;
    maven = toString built.projections.site.maven;
  };
  rejects =
    target:
    !(builtins.tryEval
      (pkgs.pub-purifier.buildPubProject {
        src = ./fixtures/browser42;
        browserTargets.site = target;
      }).browser.site.drvPath
    ).success;
in
assert (pkgs.pub-purifier.buildPubProject { src = ./fixtures/browser42; }).projections == { };
assert rejects { entrypoint = "../outside.dart"; };
assert rejects { entrypoint = "/outside.dart"; };
assert rejects {
  entrypoint = "web/main.dart";
  target = "wasi";
};
assert rejects {
  entrypoint = "web/main.dart";
  assets."main.js" = "web/index.html";
};
assert rejects {
  entrypoint = "web/main.dart";
  assets."../private" = "web/index.html";
};
assert rejects {
  entrypoint = "web/main.dart";
  webjar = {
    artifactId = "../bad";
    version = "1";
  };
};
pkgs.runCommand "pub-browser-consumers"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.jdk
      pkgs.gradle
      pkgs.chromium
    ];
    spec = builtins.toJSON {
      versions = [
        (record first 42)
        (record second 43)
      ];
      chromium = "${pkgs.chromium}/bin/chromium";
    };
    passAsFile = [ "spec" ];
  }
  ''
    export HOME="$TMPDIR/home" GRADLE_USER_HOME="$TMPDIR/gradle-home"
    mkdir -p "$HOME"
    python3 ${./browser}/proof.py "$specPath" "$out"
  ''
