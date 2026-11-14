# pub-purifier

Locked, Nix-resolved dependencies for Dart pub.

## Quickstart

In your existing Dart project:

```sh
nix shell 'github:nix-purifiers/pub-purifier'
pub-purifier lock
pub-purifier prefetch
dart run bin/main.dart
```

Commit `pubspec.lock` and `pub-purifier.lock.json`. Prefetch fetches the
locked archives with Nix and generates the native `.dart_tool` package
configuration. The shell supplies a Dart wrapper that activates the
project's locked cache for normal run, analyze, compile and editor commands.

You can install the wrapper through your usual Nix configuration. Without
a purifier lock it warns and runs ordinary, impure Dart. Invalid or stale
locks fail with a repair command.

## Development loop

After editing `pubspec.yaml`:

```sh
nix shell 'github:nix-purifiers/pub-purifier'
pub-purifier lock
pub-purifier prefetch
dart analyze
dart test
```

Use your project's existing test command; `dart test` requires the usual
`test` development dependency. Repeating `lock` retains the resolution and
leaves both lockfiles byte-for-byte identical.

Update everything or name the packages to update:

```sh
pub-purifier update
pub-purifier update collection
pub-purifier prefetch
```

Updates use the native pub solver. Named updates preserve unrelated pins.
In a locked project, dependency-changing `dart pub` commands direct you to
edit the manifest and run `pub-purifier lock` or `update`.

## Working offline

```sh
nix shell 'github:nix-purifiers/pub-purifier'
pub-purifier prefetch
dart pub get
dart analyze
```

Prefetch keeps GC roots for the store cache and the CLI/toolchain beside
the lock. The wrapper's `dart pub get` uses `--offline --enforce-lockfile`.
It generates native package configuration without replacing a selected
external `pubspec.lock`. Other commands reuse that configuration and the
project-local cache; dependency resolution needs no network after prefetch.

## Editor

The wrapper supplies the standard `dart language-server`. Prefetch first,
then start the editor from the same shell so it finds that Dart executable.
The normal `.dart_tool/package_config.json` points at locked packages;
there is no generated Nix development shell. The checks exercise a real
language server against the fixture's dependency imports offline.

## Troubleshooting

- **Manifest or overrides changed:** run `pub-purifier lock`, then `prefetch`.
- **Missing archive URL or damaged companion:** `lock` repairs it using the
  selected native lock and hosted registry metadata.
- **Invalid native lock:** `lock` asks pub to regenerate the resolution.
- **Wrong SDK:** use the wrapper or override the scope's `dart` and regenerate
  the lock using that SDK.
- **Package missing in the editor:** prefetch and restart the language server
  with the wrapper available on its `PATH`.

External native and companion locks are supported:

```sh
pub-purifier \
  --pub-lock ../locks/pubspec.lock \
  --lockfile ../locks/pub.json lock
pub-purifier \
  --pub-lock ../locks/pubspec.lock \
  --lockfile ../locks/pub.json prefetch
```

Set `PUB_PURIFIER_PUB_LOCK` and `PUB_PURIFIER_LOCKFILE` to the same paths
when using the Dart wrapper. The working tree's native lock is left alone.
The wrapper locates `pubspec.yaml` in the current directory or its parents,
or follows pub's `--directory` / `-C` option.

## Supported language repositories

Hosted pub.dev and compatible HTTP(S) pub repositories with modern native
archive SHA-256 hashes are supported. Coordinates and hashes stay in
`pubspec.lock`; the companion adds concrete archive URLs, input fingerprints,
the SDK version and binary entry points. `pubspec_overrides.yaml` is included
in stale-lock detection when present.

Git, path and SDK dependencies, Flutter projects, and pub workspaces are not
yet supported. Unsupported sources fail explicitly rather than falling back
to ordinary dependency resolution. No native pub plugin package is needed;
GitHub Pages hosts this documentation.

## Examples

[`examples/hello`](examples/hello) uses the hosted `collection` package:

```sh
nix shell 'github:nix-purifiers/pub-purifier'
cd examples/hello
pub-purifier prefetch
dart run bin/hello.dart
dart run test/check.dart
```

The checks compile a native executable, analyze and run the fixture, test
editor imports offline, reject malformed/stale/tampered/incomplete locks,
and build with both locks outside the source. Host conformance tests run
native pub resolution and named upgrades against a local versioned registry,
then stop that server before running the application and `dart pub get`.

### Optional Nix build

The overlay adds only the `pub-purifier` scope:

```nix
let
  pkgs = import nixpkgs {
    inherit system;
    overlays = [ purifier.overlays.default ];
  };
  project = pkgs.pub-purifier.buildPubProject {
    src = ./.;
    pubLock = ../locks/pubspec.lock;
    lockFile = ../locks/pub.json;
  };
in {
  packages.default = project.packages.main;
  checks.default = project.tests;
}
```

`lock` discovers `bin/*.dart` entry points. Add another with
`pub-purifier lock --entry NAME=path/to/main.dart`. The builder exposes one
package per entry, `tests`, `release` and `fetches`. It accepts `fetchers`,
`srcFilter` and `testCommand` overrides, and its named `callPackage`
dependencies support scope overrides. Default tests run analysis and the
fixture's `test/check.dart`, or `dart test` when that dependency is present.

`release` contains deterministic source and binary archives. Publish the
Nix-built artifacts to a GitHub release with:

```sh
pub-purifier publish \
  --repo OWNER/PROJECT --tag v1.0.0
```

`lib.pub-purifier.readLock` exposes the shared lock-reader shape without
import-from-derivation. The cache and release are checked with
`nix build --rebuild`; CI runs on x86_64 and ARM Linux.

### Browser applications and WebJars

Select a Dart web entrypoint and its public assets explicitly:

```nix
project = pkgs.pub-purifier.buildPubProject {
  src = ./.;
  browserTargets.site = {
    entrypoint = "web/main.dart";
    target = "javascript"; # or "wasm"
    assets = {
      "index.html" = "web/index.html";
      "style.css" = "web/style.css";
    };
    webjar = {
      groupId = "org.webjars.dart";
      artifactId = "my-site";
      version = "1.0.0";
    };
  };
};
```

`browser.site` and `packages.browser-site` contain the native compiler's
runtime files and selected assets. JavaScript builds retain `main.js` and
any deferred-loading JavaScript parts. Wasm builds retain `main.wasm`, its
native `main.mjs` loader, and generated support files. Wasm uses Dart's
WasmGC browser runtime and JavaScript loader API; this is not a WASI module.
Use the compiler-generated loader's `compileStreaming`, `instantiate` and
`invokeMain` API from your HTML, as shown in the browser test fixtures.

`projections.site.web` provides a static document root and a Java resource
JAR. Optional `webjar` coordinates also expose `projections.site.maven`
and `.ivy` for ordinary JVM resolvers. Publication identities incorporate
the producer, so a changed build gets a distinct coordinate even when its
declared version stays the same. Resource paths and sidecars are preserved.

The browser builds use the same offline, enforced Pub lock and selected
Dart SDK as native builds. Public asset paths must stay inside the source
tree and cannot overwrite compiler output. Compiler metadata lives in the
separate `browser.site.proof` output. Source files, private configuration,
Pub caches and source maps are excluded from the public output.

Checks exercise two real producer revisions with a locked `collection`
dependency and deferred imports. Chromium executes JavaScript and WasmGC
from the native asset tree, HTTP projection, and a Java HTTP server reading
an ordinary Gradle-resolved WebJar. Java consumers check exact JAR resource
origins and hashes. Missing runtime files, native-only FFI entrypoints,
escaping assets, compiler-file collisions and compiled replacements have
separate rejection checks.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).

Path dependencies can use an explicit version 2 hosted capture. Run from the
Dart project directory, declaring its enclosing source tree and each provided
package root:

```sh
pub-purifier --source-root .. --path-source-root /path/to/thrift/lib/dart lock
pub-purifier --source-root .. --path-source-root /path/to/thrift/lib/dart native -- run bin/main.dart
```

The Nix constructor accepts `projectDir` within `src` and
`pathSources = [ { src = selectedThriftSource; root = "lib/dart"; } ];`.
Each provided package takes its name and version from its actual native
`pubspec.yaml`. These are current source inputs, rather than source pins stored
in the hosted download capture. Native path fields are relocated in temporary
copies; other dependency constraints and existing overrides are preserved.
Workspaces require a separate contract and are rejected.

The closed version 2 capture contains only `version`, `hosted`, `outputs`, and
`contentHash`. Each hosted entry contains its native `version`, `registry`,
`sha256`, and `archiveUrl`. Unused captured packages may remain. Every active
hosted identity must match a capture; adding or changing one requires an
explicit capture/update. The selected Dart SDK resolves offline and authors a
temporary lock, which is then checked with `--enforce-lockfile`. The original
native lock is retained as an unchanged seed. SDK version observations and
provided source receipts are derived build evidence, not portable admission
pins. Existing version 1 hosted-only projects retain their existing behavior.
