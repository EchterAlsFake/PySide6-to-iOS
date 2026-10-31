# Python 3.10–3.14 / Qt 6.12 iOS 15 matrix

This expansion reuses the three static Qt 6.12.0 iOS 15 kits from the
[original release](https://github.com/EchterAlsFake/PySide6-to-iOS/releases/tag/6.12.0-ios15-cp315).
Qt is independent of the embedded Python ABI, so it does not need to be
compiled again for each Python version. Shiboken and all 52 PySide bindings
are compiled separately for each Python/target combination.

| Python | Pinned BeeWare support build | Targets |
| --- | --- | --- |
| 3.10.20 | 3.10-b14 | Device ARM64, simulator ARM64, simulator x86_64 |
| 3.11.18 | 3.11-b13 | Same three targets |
| 3.12.16 | 3.12-b13 | Same three targets |
| 3.13.18 | 3.13-b18 | Same three targets |
| 3.14.10 | 3.14-b14 | Same three targets |

The runtimes are pinned, upstream-built XCFrameworks from
[Python-Apple-support](https://github.com/beeware/Python-Apple-support/releases).
This is not a fresh CPython build. The preparation manifest records archive
hashes, and the runtime auditor checks every architecture's interpreter,
stdlib layout and native extensions against the iOS 15 maximum minimum.
Python 3.10–3.12 use BeeWare's iOS port/backports; these are embedded iOS
runtimes rather than desktop Python installations copied into an app.

There are **15 combinations and 30 wheels**. iOS wheels use explicit tags
such as `cp310-cp310-ios_arm64`; they are static deployment inputs, not a
single desktop `cp310-abi3` wheel renamed for multiple Python versions.

## Build without rebuilding Qt

Use an Intel macOS host, full Xcode, Python 3.13, CMake, Ninja, zstd, Git and
curl. The host Python runs the build tools; it does not determine the target
interpreter's version.

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export PYTHON_MATRIX_ROOT="$PWD/work-python-matrix"
python3.13 scripts/prepare-python-matrix.py --work-root "$PYTHON_MATRIX_ROOT"
python3.13 scripts/build-python-matrix.py --work-root "$PYTHON_MATRIX_ROOT" --jobs 6
```

The default preparation restores the complete Intel host tool kit as well as
the three target kits. An installed Qt host kit may be supplied through
`--qt-host-path /path/to/Qt/6.12.0/macos`, but it must include the required
Remote Objects and SCXML tools (`repc`, `qscxmlc`) as well as the core/QML
tools. A macOS/Android-only installer selection does not supply an iOS target
kit, and a normal upstream iOS kit does not replace the custom iOS 15 build.

Re-run the same build command to resume. Completed pairs are recorded in
`python-matrix-state.json`, and each successful pair's intermediate object
tree is removed to control disk use. Logs and per-pair inventories are kept.
For a smaller development run, use `--python-versions 3.10 --targets ios_arm64`.

```bash
python3.13 scripts/check-ios-wheels.py \
    "$PYTHON_MATRIX_ROOT/wheels/3.10/ios_arm64" \
    --python-version 3.10 --target ios_arm64 --max-ios 15.0
```

The build requires the same 52 binding modules, two PySide helpers, 105 QML
modules, 314 translations and static support archives as the original matrix.
The existing [module exclusions and source/deployment patches](RELEASE_MATRIX.md)
still apply. All Python versions must pass their own wheel-tag and native-code
audits; an earlier Python 3.15 test does not establish runtime success here.

Use the matching runtime and wheel pair together when generating a test
project with `pyside6-ios-deploy`. Application linking and interpreter import
tests are separate from the build/audit stage. Apple Silicon simulator
execution cannot be tested on an Intel host; simulator screen capture in a
GPU-less VM does not establish actual rendering.

Python 3.10 also needs the deployment bootstrap fix supplied by
`scripts/patch-ios-deploy.py`. Its built-in importer normally refuses package
submodules; iOS statically registers names such as `shiboken6.Shiboken` and
`PySide6.QtCore`. The patched launcher adds a finder for registered built-ins
on Python 3.10 only. Regenerate existing projects after patching the host
deployment environment. The corrected launcher passed all 52 module imports
on the Intel simulator; this does not yet establish a physical Python 3.10 test.
