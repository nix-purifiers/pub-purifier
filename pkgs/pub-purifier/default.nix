# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  git,
  nix,
  dart,
  gh,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "pub-purifier";
  version = "0.1.0";
  src = ../..;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/pub-purifier"
    cp -r pub_purifier nix lib-overlays pkgs "$out/lib/pub-purifier/"
    install -m755 bin/pub-purifier "$out/bin/pub-purifier"
    substituteInPlace "$out/lib/pub-purifier/nix/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/pub-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          (python3.withPackages (p: [ p.pyyaml ]))
          git
          nix
          dart
          gh
        ]
      } \
      --prefix PYTHONPATH : "$out/lib/pub-purifier" \
      --set PUB_PURIFIER_DART ${dart}/bin/dart \
      --set PUB_PURIFIER_REALIZE "$out/lib/pub-purifier/nix/realize.nix" \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    makeWrapper "$out/bin/pub-purifier" "$out/bin/dart" --add-flags "native --"
  '';
  meta = {
    description = "Locked, Nix-resolved Dart packages";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "pub-purifier";
    homepage = "https://nix-purifiers.github.io/";
  };
}
