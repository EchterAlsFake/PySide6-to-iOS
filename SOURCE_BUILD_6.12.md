# Source-build Qt 6.12 and PySide6 iOS wheels

This chapter mirrors the Android source-build guide, using the actual iOS
reference: Qt/PySide 6.12.0, embedded CPython 3.15.0rc2 and an Intel macOS host.
It has two paths: upstream iOS 18+ and the experimental iOS 15 patch used for
the iPhone 7. Do not silently mix their installation prefixes.

## Toolchain versions

| Component | Reference | Role |
| --- | --- | --- |
| Qt / PySide / Shiboken | 6.12.0 | Must match |
| Full Xcode | 26.3 | Native tools and signing |
| Device/simulator SDK | 26.2 | SDK is not the deployment minimum |
| Host Python | 3.13.16 | Runs generators/build scripts |
| Embedded Python | 3.15.0rc2 | Official Python.xcframework, CPython ABI 315 |
| Device | iPhone 7, ARM64 | iOS 15.8.8 with palera1n rootless |
| Deployment minimum | 18.0 normally; 15.0 experimentally | Recorded in every native build |

The maintained scripts pin the source revisions and archive hashes in
[`scripts/versions.json`](scripts/versions.json). The lab's exact source revisions were:

| Module | Commit |
| --- | --- |
| qtbase | `025bdad181de241e81bf853c8a2d7bf3d19261a9` |
| qtshadertools | `bccd516b990a6396900051470ac86cc27a7042ea` |
| qtsvg | `883a58532078d003cefef0a549bfe9f885ce41f5` |
| qtdeclarative | `4332fbbb4c340463dc8cee36dda0c85d932122d8` |
| qt5compat | `9c2a1b4c8298c750f8632e2fd19f7a1a539c5f09` |
| pyside-setup | `f50facb83fc3dc5f3240c854668c7a6dd93871b2` |

## Fetch and verify Qt 6.12.0

The helpers shallow-clone upstream `v6.12.0` module repositories and verify
the checked-out commit against the manifest. They refuse a different existing
revision rather than resetting your sources. No personal machine paths or
root access are required.

```bash
export GUIDE_ROOT="$PWD"
export WORK_ROOT="$GUIDE_ROOT/work"
export PYTHON_HOST_BIN=python3.13
export JOBS=4
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcrun --sdk iphoneos --show-sdk-path
```

These are the upstream iOS helper's expected prefix names:

```text
work/qt/6.12.0/macos/                 host tools
work/qt/6.12.0/ios_device/            ARM64 device kit
work/qt/6.12.0/ios_simulator_arm64/   Apple Silicon simulator kit
work/qt/6.12.0/ios_simulator_x86_64/  Intel simulator kit
```

Our adapted source-build driver passes explicit host/target paths, but retains
that useful layout. Upstream `tools/cross_compile_ios/main.py --qt-install-path`
expects the **root containing these directories**, not the device prefix itself.

## Build the host Qt tools

```bash
bash scripts/build-qt-host.sh
```

The order is Qt Base → ShaderTools → Declarative. Host tools provide `moc`,
`rcc`, `qsb` and QML generators. Host and target Qt versions must match; the
desktop PySide pip wheel is not a substitute for a same-version host Qt kit.

The host build disables widgets/SQL/tests/examples and uses
`FEATURE_qml_animation=OFF` for host Declarative. That was sufficient to retain
the QML tools without building host Qt Quick in this experiment. It does not
disable animation or Qt Quick in the target app. This is a minimal Quick stack,
not a promise that every Qt module's host generators are installed.

## Build Qt for the device

Normal supported baseline:

```bash
IOS_DEPLOYMENT_TARGET=18.0 bash scripts/build-qt-ios.sh ios_arm64
```

The script builds static Qt Base and then ShaderTools, Svg, Declarative and
Core5Compat. The latter supplies GraphicalEffects used by the reference app.
It passes iOS availability warnings as errors for C, C++, Objective-C and
Objective-C++. Build output is isolated by target and deployment minimum.
Use a new `WORK_ROOT` when switching minimums; do not install incompatible
builds over an existing kit.

### Experimental iOS 15 path

Qt 6.12's documented minimum is **18**, not 15. The reference could not be
ported simply by changing `MinimumOSVersion`: unavailable APIs were compiled
into both platform and threading code.

```bash
export WORK_ROOT="$GUIDE_ROOT/work-ios15"
export IOS_DEPLOYMENT_TARGET=15.0
export EXPERIMENTAL_IOS15=1
bash scripts/build-qt-host.sh
bash scripts/build-qt-ios.sh ios_arm64
```

The device script verifies and applies
[`qtbase-ios15.patch`](scripts/patches/qtbase-ios15.patch), SHA-256
`1a7a858d30f616d84e0b17c510fe64f88c449c932c0db776ae61ea0e9881ad63`.
It is tied to the exact qtbase revision above. Already applied patches are
recognized; conflicts stop the build.

The changes were required by real compiler/runtime failures:

1. **Mutexes:** current `os_sync_*` futex calls require iOS 17.4. For earlier
   deployment targets, select Qt's generic mutex path and restore the public
   Mach-semaphore implementation from upstream Qt 6.8.3. Update the futex and
   `FutexAlwaysAvailable` decisions together; changing only a CMake minimum is insufficient.
2. **Metal/HDR:** guard Metal 3 detection and newer HDR capabilities behind
   runtime availability checks. Retain SDR and disable unsupported capabilities on older systems.
3. **Platform APIs:** retain compatible calendar permissions, accessibility
   traits, Pencil hover/rotation and HDR behavior when newer APIs are unavailable.

The patch retains upstream notices and uses public Mach APIs. It does not
make iOS 15 an officially supported Qt configuration, and it has not been
validated across every iOS 15 device or Qt module.

## Build the wheels

The convenience driver prepares the pinned official Python runtime, builds
the host/target kits and produces one matching wheel pair per requested target:

```bash
# iOS 18 baseline:
TARGETS=ios_arm64 bash scripts/rebuild-ios-matrix.sh

# iOS 15 experiment, separate work root:
WORK_ROOT="$PWD/work-ios15" IOS_DEPLOYMENT_TARGET=15.0 EXPERIMENTAL_IOS15=1 \
    TARGETS=ios_arm64 bash scripts/rebuild-ios-matrix.sh
```

The host deployment/generator environment and source-build environment are
separate. The latter pins setuptools 78.1.0, packaging 24.2, build 1.2.2.post1
and wheel 0.46.3 as in the working build. The generator is the official
Shiboken 6.12 universal macOS wheel, verified against its pinned SHA-256.
This host generator already links Clang statically; downloading another LLVM
SDK was unnecessary. Its wrapper Qt/Clang search paths point to its bundled host Qt libraries.

The critical target CMake settings are generated explicitly:

```cmake
include("/your/target/Qt/lib/cmake/Qt6/qt.toolchain.cmake")
set(CMAKE_OSX_SYSROOT iphoneos)
set(CMAKE_OSX_ARCHITECTURES arm64)
set(CMAKE_OSX_DEPLOYMENT_TARGET 15.0 CACHE STRING "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(Python_INCLUDE_DIR "/your/runtime/slice/include/python3.15" CACHE PATH "" FORCE)
set(Python_LIBRARY "/your/runtime/slice/lib/libpython3.15.dylib" CACHE FILEPATH "" FORCE)
set(Python_SOABI "cpython-315-iphoneos" CACHE STRING "" FORCE)
```

The runtime helper creates the framework-backed include/library symlinks.
Passing a raw framework filename to FindPython failed in the original build;
the Unix-shaped view worked. Host Python 3.13 and target Python 3.15 are deliberately different.

Build bindings in this order:

```text
Core,Gui,Network,OpenGL,Svg,Qml,Quick,QuickControls2
```

Quick before OpenGL produced missing generated-header includes. The driver
uses the upstream `setup.py bdist_wheel` flags from the working build:
`--standalone`, `--no-qt-tools`, `--disable-pyi`, `--skip-mypy-test`,
`--disable-numpy-support`, explicit host/target/Python paths and `--plat-name`.

Outputs are under `work/wheels/<target>/`; logs under `work/logs/`.
Compilation is not installation or runtime verification.

## Matrix automation and audits

There are **three platform/architecture choices and one pinned Python ABI**,
not Android's 5 × 4 version/ABI matrix:

```bash
TARGETS='ios_arm64 ios_x86_64_simulator' bash scripts/rebuild-ios-matrix.sh
TARGETS='ios_arm64 ios_x86_64_simulator' bash scripts/check-ios-matrix.sh
```

Select only targets you intend to build. Apple Silicon uses
`ios_arm64_simulator`; it was not exercised in the Intel lab. The generalized
simulator source-build branch is provided for reproducibility work, not marked
as a completed source-build matrix. Our working Intel simulator used official wheels.

The Python wheel auditor checks filename/internal tags, ZIP CRCs, CPU,
Mach-O platform and deployment minimum. It reads static archive members and
selects relevant XCFramework slices from their metadata. A universal
XCFramework can legitimately retain unused slices. Runtime auditing selects
the corresponding Python slice. Neither auditor executes target code.

## Known limitations

- No Widgets, WebEngine, multimedia or other complete module matrix is claimed.
- Keep your modules/resources in the generated static registration list.
- A source build can consume many GB of intermediates and run slowly in a VM.
- Do not reuse desktop or simulator native extensions on the device.
- Replacing target wheels may leave `_wheels` unpacked caches; remove only the
  appropriate generated target cache and regenerate before trusting the result.
- Follow [RUNTIME_BUILD.md](RUNTIME_BUILD.md) for third-party dependencies.
- Keep private jailbreak GPU entitlements out of stock-signed IPAs.

Upstream sources: [Qt for iOS](https://doc.qt.io/qt-6/ios.html),
[PySide iOS deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-ios-deploy.html),
[Qt platform support](https://doc.qt.io/qt-6/supported-platforms.html).
