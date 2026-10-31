# iOS 15 full-matrix release results

Qt/PySide 6.12.0, Qt PDF source 6.140.0 and official CPython 3.15.0rc2.
All three Qt kits and target binding pairs were built from fresh source for
minimum iOS 15.0. The Python XCFramework and host Shiboken generator are
pinned upstream binaries. The host Qt kit is Intel x86_64 / macOS 15+.

| Target | Qt bindings | QML modules | Translation catalogs | Application validation |
| --- | --- | --- | --- | --- |
| `ios_arm64` | 52 | 105 | 314 | Stock iPhone 7 / iOS 15.8.8, imports + touch (user confirmed) |
| `ios_arm64_simulator` | 52 | 105 | 314 | Cross-linked; execution not tested on this Intel host |
| `ios_x86_64_simulator` | 52 | 105 | 314 | Intel simulator / iOS 26.3.1, imports + Qt-reported window visibility; rendering unverified |

Every target passed wheel CRC, architecture, Mach-O platform and native
deployment-minimum audits and a full-module application link. QtQmlFeatures
and QtAsyncio are supplied in addition to the 52 bindings. Required UiTools
and Remote Objects support archives are included; apply the host deployment
patch before generating applications that use them.

The Intel simulator imports all modules and Qt reports a visible window, but
its captured screen is black in this GPU-less VM. Actual simulator rendering
is not established by that programmatic visibility flag.

The stock-device result applies to the generic matrix test app, not the
separate PornFetch IPA. Imports and a working UI do not exercise every module
feature. ARM64 simulator execution and Rosetta use of the Intel host kit were
not tested. This is an experimental backport below Qt's official iOS baseline.

The earlier investigation diary includes progress reports from before the
matrix completed. These final results supersede those progress statuses.

See [machine-readable validation](scripts/matrix-validation.json),
[sources/build/patch instructions](RELEASE_MATRIX.md) and the
[release assets](https://github.com/EchterAlsFake/PySide6-to-iOS/releases/tag/6.12.0-ios15-cp315).
The release includes signed checksums, source archives, build evidence and
the re-signable device test IPA. Its packaging report records the pre-test
state; later application checks record the successful stock-device test.
