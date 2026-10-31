# Full iOS 15 source-build matrix

This is the full Qt-for-Python module build, separate from the older minimal
Quick build in `rebuild-ios-matrix.sh`. It builds a new host Qt toolchain,
three static target Qt kits and three matching PySide6/shiboken6 wheel pairs.
It uses Qt/PySide 6.12.0 and the official CPython 3.15.0rc2 XCFramework.
CPython and the host Shiboken generator are pinned upstream binaries; Qt and
the target bindings are compiled from fresh source.

The host Qt kit is **x86_64, macOS 15+**. ARM64 simulator output is a target
kit; it does not include native ARM64 macOS host tools. Apple Silicon hosts
need suitable same-version host tools or a Rosetta environment; execution of
the Intel host kit under Rosetta is not established by this build.

| Wheel platform | CPU | Destination | Deployment minimum |
| --- | --- | --- | --- |
| `ios_arm64` | ARM64 | iPhone/iPad | iOS 15.0 |
| `ios_arm64_simulator` | ARM64 | Apple Silicon simulator | iOS 15.0 |
| `ios_x86_64_simulator` | x86_64 | Intel simulator | iOS 15.0 |

These are experimental legacy-target builds. Qt 6.12 officially targets
iOS 18+. Build success, binary audits, app linking and runtime testing are
different checks; the release manifest records which were performed.
Apple Silicon simulator binaries can be cross-compiled on Intel macOS,
but cannot be executed there.

## Build from a fresh work directory

Use an Intel macOS host with full Xcode 26.3 / SDK 26.2, Python 3.13,
CMake, Ninja, Git and curl. Release packaging also uses `zstd`; the download
and signature examples use GitHub CLI and GPG. The recorded VM has 16 GB RAM. Keep several
tens of GB free; the driver deletes each module's object tree after a
successful installation to limit peak disk use.

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export MATRIX_ROOT="$PWD/work-ios15-full"
python3.13 scripts/prepare-release-matrix.py --work-root "$MATRIX_ROOT"
python3.13 scripts/build-release-matrix.py \
    --work-root "$MATRIX_ROOT" \
    --python-xcframework "$MATRIX_ROOT/python/3.15.0rc2/Python.xcframework" \
    --jobs 12 --binding-jobs 6
```

Run as your normal macOS login user. The preparation step verifies source
archive and generator hashes from [`scripts/versions.json`](scripts/versions.json).
It extracts the Qt source bundle and the separately released Qt PDF source,
clones the matching PySide tag and creates an isolated build environment.
The driver checks the QtBase and PySide revisions before compiling.
It pins both `CMAKE_OSX_SYSROOT` and `QT_APPLE_SDK` for each target. Setting
only the former leaves Qt's combined device/simulator mode enabled and can
make configuration tests use the device SDK when compiling for Intel.

Re-run the same command to resume a failed stage within this fresh run.
Completed stages are recorded in `matrix-state.json`; existing lab builds
are never used as target artifacts. Use a new directory for a new release
build. `--targets` can select fewer targets for development, and
`--keep-build-trees` retains intermediates at a substantial disk cost.
The recorded run used 12 Qt compile jobs and six binding compile jobs on
16 logical CPUs. Lower `--jobs` on smaller hosts; binding compilation has
a separate limit because generated wrappers can use more memory.

## Module scope

The full build includes all available iOS PySide binding modules, with an
explicit required-module check, plus their Qt libraries, static plugins,
headers, CMake metadata and QML dependencies. It covers Widgets, Qt Quick,
Quick 3D, Qt 3D, Charts, Graphs, Data Visualization, Multimedia, PDF, networking,
Bluetooth/NFC, positioning, sensors, speech, state machines, Remote Objects,
SVG and UiTools. Qt Virtual Keyboard, Quick Timeline, Lottie, Quick 3D Physics,
image format plugins and Core5Compat are also built for QML applications.
The per-target module inventories are the authoritative list of artifacts.
The wheels also include PySide's `QtQmlFeatures` native helper and `QtAsyncio`.

Platform exclusions are explicit:

- Qt SerialPort and SerialBus return early for `UIKIT` in upstream CMake.
- Qt WebEngine's browser modules do not support iOS. Native Qt WebView is
  included; Qt PDF is built independently with the browser disabled.
- D-Bus is disabled in this Apple-native kit; ActiveX is Windows-only.
- Qt Designer requires process support, which upstream disables on iOS;
  Qt UiTools is included for loading `.ui` files.
- Bindingless products such as Qt MQTT, CoAP, OPC UA and gRPC are outside
  this Qt-for-Python matrix.

Qt 6.12 no longer includes Qt PDF in the main source archive. This build
uses the Qt WebEngine/PDF **6.140.0** source package provided for Qt 6.12,
with `FEATURE_qtwebengine_build=OFF` and `FEATURE_qtpdf_build=ON`.
That separate version is intentional. See Qt's
[separate-release announcement](https://www.qt.io/blog/qt-webengine-will-release-separate).
The driver builds a matching native GN tool before cross-compiling PDF,
disables bitcode and optional IDE source indexing, and applies a small CMake
fix so disabling documentation does not reference a nonexistent docs target.
The PDF source patch also makes availability warnings errors in GN's Apple
target compiler configuration; that toolchain does not inherit Qt's CMake
warning flags. This covers the bundled PDFium and ICU code as well as Qt's
PDF wrappers.

Multimedia uses Apple's AVFoundation/CoreAudio backend. It does not link a
prebuilt FFmpeg SDK with a higher deployment minimum. The application's
custom FFmpeg remux extension described in [RUNTIME_BUILD.md](RUNTIME_BUILD.md)
is a separate native dependency.

The Multimedia compatibility patch retains the built-in microphone type on
iOS 15–16 and uses the newer microphone, external-camera and Continuity-camera
types only from iOS 17. Patch hashes and the exact source revision are pinned
in the manifest; a patch conflict stops the build.

## Audit and use the output

Wheels are written to `wheels/<target>/`. Installed Qt kits are under
`qt/6.12.0/{macos,ios_device,ios_simulator_arm64,ios_simulator_x86_64}`.
Build logs and CMake feature reports are retained in `logs/` and `reports/`.

Every wheel pair must pass the ZIP CRC, internal tag, CPU, Mach-O platform
and deployment-minimum audit. The inventory check compares declared bindings
against actual static binding archives and rejects missing required modules.
Availability warnings are errors in the target Qt C/C++/Objective-C builds.
These checks do not execute every Qt feature or establish stock-device signing.

```bash
python3.13 scripts/check-ios-wheels.py "$MATRIX_ROOT/wheels/ios_arm64" \
    --target ios_arm64 --max-ios 15.0
```

Feed a matching wheel pair to `pyside6-ios-deploy` as described in
[README.md](README.md#build-the-app--ipa). Target wheels are static deployment
inputs, not host `pip install` packages. Regenerate the project's extracted
wheel cache after replacing wheels. Select required modules and QML plugins
in the generated static registration list.

Before generating projects that use UiTools or Remote Objects, apply the
matching host deployment-tool fix:

```bash
python3.13 scripts/patch-ios-deploy.py --python "$WORK_ROOT/venvs/deploy/bin/python"
```

The source-build patch installs and packages `libuiplugin.a`; the deployment
patch links it for UiTools and links `libpyside6remoteobjects.a` for Remote
Objects. Static support archives do not get merged into the binding archives
automatically. Regenerate existing Xcode projects after applying the patch.

[`scripts/examples/matrix-smoke`](scripts/examples/matrix-smoke) imports the
52 Qt bindings plus the two PySide helpers. Its `MatrixDependencies.qml`
declares the Quick, Controls and Graphs imports required by mixed Quick/Widgets
and GraphsWidgets dependencies, so the deployment tool collects their static
QML plugin paths even though the test interface itself uses Widgets.

For a device app built from that example, create a re-signable test IPA with:

```bash
python3.13 scripts/package-ipa.py \
    --app /path/to/PySideMatrixSmoke.app \
    --output "$MATRIX_ROOT/ipas/PySideMatrixSmoke-ios15.ipa" \
    --bundle-id org.example.PySideMatrixSmoke.Sideload \
    --display-name 'PySide Matrix Test' --share-documents
```

The helper copies the app, supplies Qt's scene delegate when missing, removes
build-only archives and applies empty-entitlement ad-hoc signatures. iLoader
or SideStore must re-sign/provision it before installation. The test should
show “52 binding modules imported” and a working tap counter. With document
sharing enabled, `matrix-smoke.json` and `matrix-smoke.log` are accessible in
Files under the app's folder; the report distinguishes imports from feature tests.

For the Widgets test on a VM without Metal, select OpenGL at simulator launch
with `SIMCTL_CHILD_QT_WIDGETS_RHI=1` and
`SIMCTL_CHILD_QT_WIDGETS_RHI_BACKEND=opengl`. The older QML-specific
`QSG_RHI_BACKEND` setting alone does not select Widgets' backing-store API.
Keep the physical device on its normal Metal path.

## Assemble release assets

After all three targets pass, commit the scripts and final validation notes so
the corresponding-source snapshot identifies a clean Git commit. Then run:

```bash
python3.13 scripts/assemble-matrix-release.py \
    --work-root "$MATRIX_ROOT" \
    --python-archive "$MATRIX_ROOT/downloads/python-3.15.0rc2-iOS-XCframework.tar.gz" \
    --output "$MATRIX_ROOT/release"
python3.13 scripts/verify-release-assets.py "$MATRIX_ROOT/release" --all
gpg --armor --detach-sign "$MATRIX_ROOT/release/SHA256SUMS"
```

The assembler requires a completed three-target build. It includes six wheels,
three static Qt SDKs, the Intel host kit, the pinned Python runtime, Qt/PDF and
PySide source archives, this guide's scripts/patches, and compressed build
evidence. A packaged matrix-test IPA is included when present. Each GitHub
asset must be below 2 GiB. `release-manifest.json` records build inventories,
available application checks and source hashes; `SHA256SUMS` covers the assets.
The PySide source archive is the pinned upstream tree, with changes supplied
as patches in the guide source archive and applied by the build driver.

Availability checks and minimum-version audits do not prove that every API
works on iOS 15. Keep this matrix marked experimental, and describe simulator
execution, physical execution and stock-device installation separately when
publishing the release.

Qt and bundled dependencies have different LGPL/GPL/commercial and third-party
licenses. Preserve the source references, patches, license files and generated
SBOMs supplied with the release. Linking a particular set of modules determines
the applicable terms for your application.
