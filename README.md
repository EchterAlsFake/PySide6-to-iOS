# PySide6 on iOS — Practical Guide

> [!CAUTION]
> This guide uses AI-assisted maintenance. Phone milestones marked verified were checked by a human.
> Newly adapted automation is identified separately in [current build notes](CURRENT_BUILD_NOTES.md).
> A successful compile or IPA signature check is **not** a successful stock-iOS runtime test.

> [!NOTE]
> This guide is **unofficial** and not affiliated with Qt. It mirrors the structure of
> [PySide6-to-Android](https://github.com/EchterAlsFake/PySide6-to-Android), adapted from our iOS build work.
> Authoritative references:
> - [Qt's iOS deployment tool](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-ios-deploy.html)
> - [Qt for iOS](https://doc.qt.io/qt-6/ios.html)
> - [CPython on iOS](https://docs.python.org/3.15/using/ios.html)

> [!IMPORTANT]
> Read the guide end-to-end. iOS is not Android with a different filename: device and simulator
> binaries differ, Qt/PySide are linked statically, native Python extensions need framework packaging,
> and a stock phone requires Apple signing/provisioning.

---

## Supported Versions

| Component | Reference build | Meaning |
| --- | --- | --- |
| Qt / PySide6 / shiboken6 | **6.12.0**, matching versions | Reference iOS deployment toolchain |
| Host | Intel macOS 15.7.2 VM | Apple Silicon needs a different simulator target |
| Xcode | **26.3**, iPhoneOS/Simulator **26.2** SDKs | Full Xcode, not just Command Line Tools |
| Host Python | **3.13.16** | Runs tools; does not become the embedded interpreter |
| Embedded Python | **3.15.0rc2**, `cp315-cp315` | Pinned reference; not Android's `cp310-abi3` wheels |
| Official Qt baseline | **iOS 18+** | [Supported platforms](https://doc.qt.io/qt-6/supported-platforms.html) |
| Experimental legacy target | **iOS 15.0**, ARM64 | Custom source build/patch; iPhone 7, iOS 15.8.8, palera1n rootless |

Python 3.15.0rc2 is the exact embedded release used here, not advice to replace a newer host Python.
Changing it requires matching wheels and native extensions.

**Verified:** Intel simulator launch; physical Python + Qt; Material/QML rendering and touch;
CFFI callbacks; chompjs; selectolax; curl-cffi sync/async HTTPS; cryptography; a real application's
download → in-process FFmpeg remux → video/audio playback workflow on the jailbroken iPhone 7.

**Prepared, not runtime-verified:** a stock-iOS IPA for iLoader/SideStore. Its layout, nested
signatures and archive integrity pass checks. Stock installation, rendering and downloads still
need testing. Apple Silicon simulator and clean rebuilds of all generalized helpers are not claimed verified.

---

## Table of Contents

- [Overview](#overview)
- [Get Prebuilt iOS Wheels](#get-prebuilt-ios-wheels)
- [Environment Setup (Xcode/SDK)](#environment-setup-xcodesdk)
- [Build the App / IPA](#build-the-app--ipa)
  - [Configure `pysidedeploy.spec`](#configure-pysidedeployspec)
  - [Optional: Generate config before the project](#optional-generate-config-before-the-project)
  - [Run the final build](#run-the-final-build)
  - [Install & Debug on Device](#install--debug-on-device)
- [Common Errors & Fixes](#common-errors--fixes)
- [Debugging Strategy (Highly Recommended)](#debugging-strategy-highly-recommended)
- [Building Qt and the Wheels Yourself](#building-qt-and-the-wheels-yourself)
- [Contributing](#contributing)
- [Support](#support)

---

## Overview

An iOS app embeds Python. `pyside6-ios-deploy` generates an **Xcode project**, not a finished IPA.
Xcode builds a native launcher, links the selected Qt/PySide/plugins, and bundles the runtime and code.

| Wheel platform | CPU | Destination | Reference status |
| --- | --- | --- | --- |
| `ios_arm64` | ARM64 | Physical iPhone/iPad | Custom iOS 15 build verified on jailbroken phone |
| `ios_arm64_simulator` | ARM64 | Apple Silicon simulator | Documented, not exercised on this Intel host |
| `ios_x86_64_simulator` | x86_64 | Intel simulator | Prebuilt-wheel path verified |

An ARM64 simulator wheel is **not** an ARM64 device wheel. The CPU matches; the platform/ABI does not.
Keep target Qt prefixes, unpacked wheel caches and build directories separate.

---

## Get Prebuilt iOS Wheels

Get matching **iOS** PySide6/shiboken6 wheels. Desktop wheels installed with `pip` supply host tools.
Do not install target wheels into the host environment.

Public archive: `https://download.qt.io/official_releases/QtForPython/`.
The 6.12.0 / Python 3.15 pair uses:

```text
pyside6-6.12.0-6.12.0-cp315-cp315-ios_arm64.whl
shiboken6-6.12.0-6.12.0-cp315-cp315-ios_arm64.whl

pyside6-6.12.0-6.12.0-cp315-cp315-ios_arm64_simulator.whl
shiboken6-6.12.0-6.12.0-cp315-cp315-ios_arm64_simulator.whl

pyside6-6.12.0-6.12.0-cp315-cp315-ios_x86_64_simulator.whl
shiboken6-6.12.0-6.12.0-cp315-cp315-ios_x86_64_simulator.whl
```

Download a pair and verify its published checksums:

```bash
export GUIDE_ROOT="$PWD"  # run from this repository
export WORK_ROOT="$GUIDE_ROOT/work"
export TARGET=ios_x86_64_simulator  # Intel; select the appropriate row above
mkdir -p "$WORK_ROOT/wheels/$TARGET"
cd "$WORK_ROOT/wheels/$TARGET"
for package in pyside6 shiboken6; do
    wheel="$package-6.12.0-6.12.0-cp315-cp315-$TARGET.whl"
    url="https://download.qt.io/official_releases/QtForPython/$package/$wheel"
    curl -fL --retry 3 "$url" -o "$wheel"
    curl -fL --retry 3 "$url.sha256" -o "$wheel.sha256"
    shasum -a 256 -c "$wheel.sha256"
done
cd "$GUIDE_ROOT"
python3.13 scripts/check-ios-wheels.py "$WORK_ROOT/wheels/$TARGET" --target "$TARGET"
```

The upstream `qtpip download PySide6 --ios --arch arm64 --platform device` route is another option.
Here, qtpip 0.2.0 requested commercial credentials and direct public files worked. That observation
does not establish access to every Qt package or future download.

Prebuilt wheels keep Qt's newer iOS baseline. For iPhone 7/iOS 15, follow the
[custom source-build path](SOURCE_BUILD_6.12.md#experimental-ios-15-path), not a plist edit alone.

---

## Environment Setup (Xcode/SDK)

### Install base dependencies (macOS)

Install full Xcode and open it once to finish initial setup. With Homebrew already available:

```bash
brew install cmake ninja git python@3.13 pkgconf autoconf automake libtool
```

Select Xcode **for this terminal**, without changing the whole machine:

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
# If kept in Downloads:
# export DEVELOPER_DIR="$HOME/Downloads/Xcode.app/Contents/Developer"
xcodebuild -version
xcrun --sdk iphoneos --show-sdk-path
xcrun --sdk iphonesimulator --show-sdk-path
```

Keep the deployment virtualenv outside the app's own folder:

```bash
python3.13 -m venv "$WORK_ROOT/venvs/deploy"
source "$WORK_ROOT/venvs/deploy/bin/activate"
python -m pip install 'PySide6-Essentials==6.12.0'
requirements=$(python -c 'import pathlib,PySide6; print(pathlib.Path(PySide6.__file__).parent / "scripts/requirements-ios.txt")')
python -m pip install -r "$requirements"
pyside6-ios-deploy --help
```

On Intel, install an Intel-capable simulator runtime. This can be a large download:

```bash
xcodebuild -downloadPlatform iOS -architectureVariant universal
xcrun simctl list runtimes
xcrun simctl list devices available
```

The reference used 16 GB RAM and later 8 virtual CPUs. Extra RAM was unnecessary; disk space mattered
more. Keep tens of GB free for SDKs, Qt objects and intermediates. The retained lab was about 21 GB,
excluding Xcode and simulator data. Build as your normal graphical-login user, not root.

---

## Build the App / IPA

### Configure `pysidedeploy.spec`

There is no `buildozer.spec` for this route. Useful `[ios]` options in `pysidedeploy.spec` are:

- `wheel_pyside`, `wheel_shiboken`: matching files; their platform tags choose the destination.
- `xcframework_path`: official Python runtime or the tool's automatically populated cache.
- `bundle_id`: your unique reverse-DNS identifier.
- `team_id`, `signing_style`: your Apple team and signing configuration.
- `deployment_target`: normally leave empty for Qt's baseline; lower only with a compatible rebuilt kit.
- `entitlements`: optional plist; stock provisioning must authorize requested entitlements.

`[qt] modules` and `qml_files` control which bindings/resources are linked and registered. Inspect
generated `main.mm` when an import or QML plugin is missing: static registration happens before Python starts.

### Optional: Generate config before the project

Use upstream `--init`; an interactive pause patched into the deployment script is unnecessary:

```bash
mkdir -p "$WORK_ROOT/apps/hello"
cp "$GUIDE_ROOT/scripts/examples/hello/"* "$WORK_ROOT/apps/hello/"
cd "$WORK_ROOT/apps/hello"
pyside6-ios-deploy main.py --init --name HelloIOS \
    --bundle-id com.example.HelloIOS \
    --wheel-pyside "$WORK_ROOT/wheels/$TARGET/pyside6-6.12.0-6.12.0-cp315-cp315-$TARGET.whl" \
    --wheel-shiboken "$WORK_ROOT/wheels/$TARGET/shiboken6-6.12.0-6.12.0-cp315-cp315-$TARGET.whl"
# Review pysidedeploy.spec; add your own [ios] team_id for device signing.
pyside6-ios-deploy -c pysidedeploy.spec
```

`--init` still validates/unpacks wheels and may download Python. Later, pass `-c` explicitly to
reuse config without repeating wheel arguments. It is not an offline no-op.

### Run the final build

Open `deployment/$TARGET/HelloIOS.xcodeproj` in Xcode. Choose a destination matching your wheels.
For an Intel simulator, a command-line build is:

```bash
xcodebuild -project "deployment/$TARGET/HelloIOS.xcodeproj" \
    -scheme HelloIOS -configuration Debug -sdk iphonesimulator \
    -destination 'generic/platform=iOS Simulator' -derivedDataPath "$WORK_ROOT/derived/hello-$TARGET" \
    ARCHS=x86_64 ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO \
    CODE_SIGN_IDENTITY=- EXPANDED_CODE_SIGN_IDENTITY=- \
    EXPANDED_CODE_SIGN_IDENTITY_NAME=ad-hoc build
```

For a stock device, configure **Signing & Capabilities** with your own team and unique ID. Use
Xcode's archive/export workflow for a provisioned distribution IPA. No Apple signing identity was
available in this VM; its experimental stock IPA instead needs iLoader/SideStore to re-sign it.
GPG signing a Git commit does **not** sign an iOS app.

The simulator command supplies `-` explicitly because CPython's build phase signs extension
frameworks itself even when Xcode's own signing is disabled. An empty expanded identity caused
“The specified item could not be found in the keychain.” These ad-hoc overrides are for the
unsigned simulator/re-signing workflow, not a replacement for your stock-device identity.

To package a built **device** `.app` for that re-signing workflow:

```bash
python3.13 "$GUIDE_ROOT/scripts/package-ipa.py" \
    --app /absolute/path/to/HelloIOS.app \
    --output "$WORK_ROOT/HelloIOS-sideload.ipa" \
    --bundle-id com.example.HelloIOS.Sideload --display-name 'Hello iOS Test'
```

The helper copies the app, normalizes framework metadata, removes build-only objects, signs
frameworks before the main app, and verifies the ZIP. Its **empty entitlements and ad-hoc signatures**
still require Apple Account re-signing/provisioning. It cannot turn simulator code into device code.
It removes the copied Qt build-kit `packages/PySide6/Qt/lib` tree while retaining QML resources;
runtime dylibs must already be embedded in the app's `Frameworks` directory. Additional module
stacks such as Qt Multimedia need their own dependency collection and are not a verified matrix here.

### Install & Debug on Device

**Simulator:**

```bash
xcrun simctl list devices available
export SIMULATOR_ID=YOUR_SIMULATOR_UUID
xcrun simctl boot "$SIMULATOR_ID"  # omit if already booted
open "$DEVELOPER_DIR/Applications/Simulator.app"
xcrun simctl bootstatus "$SIMULATOR_ID" -b
xcrun simctl install "$SIMULATOR_ID" /absolute/path/to/HelloIOS.app
xcrun simctl launch --console "$SIMULATOR_ID" com.example.HelloIOS
```

Use the ID in built `Info.plist`, not the process/display name. These overrides made Qt Quick render
through OpenGL in the no-GPU Intel VM:

```bash
SIMCTL_CHILD_QT_QUICK_BACKEND=rhi SIMCTL_CHILD_QSG_RHI_BACKEND=opengl \
SIMCTL_CHILD_QSG_RENDER_LOOP=basic \
xcrun simctl launch --console "$SIMULATOR_ID" com.example.HelloIOS
```

Those are **VM simulator overrides**. Do not force them onto the phone; the verified phone uses Metal.

**Stock phone:** use Xcode, or import the device IPA into [iLoader](https://github.com/nab138/iloader)
or [SideStore](https://docs.sidestore.io/docs/installation/install) and let it re-sign with your account.
Connect/trust the host, then trust the developer under Settings → General → VPN & Device Management
if asked. iOS 15 has no iOS 16 Developer Mode switch. Stock installation does not use SSH.

**Jailbreak experiment:** we used palera1n rootless, an SSH key, `ldid`, `/var/jb/Applications`,
`uicache` and `uiopen`. This is separate from normal iOS deployment, not a PySide6 requirement.
Rootless may provide `/var/jb/usr/bin/sh` instead of `/bin/sh`.
See [current build notes](CURRENT_BUILD_NOTES.md#jailbreak-deployment-and-metal).

---

## Common Errors & Fixes

| Symptom | What to check |
| --- | --- |
| iOS SDK not found | Full Xcode and `DEVELOPER_DIR`, not only CommandLineTools |
| `pip` rejects the target wheel | Expected; feed it to `pyside6-ios-deploy` |
| ARM64 code cannot run on device | Device vs simulator platform: inspect `LC_BUILD_VERSION`, not only CPU |
| Generic simulator build tries ARM64 with Intel wheels | Pass `ARCHS=x86_64 ONLY_ACTIVE_ARCH=YES`; Apple Silicon uses `ARCHS=arm64` |
| Minimum iOS rejected | Rebuild compatible Qt/PySide or use supported iOS; plist edits do not replace new APIs |
| CMake cannot find target Python | Supply the `include/python3.15` and `lib/libpython3.15.dylib` compatibility view |
| Quick wrappers cannot find OpenGL headers | Build `Core,Gui,Network,OpenGL,Svg,Qml,Quick,QuickControls2` in that order |
| CFFI callback crashes in `ffi_prep_closure_loc` | Match CFFI Apple trampoline-table defines to target libffi |
| Missing PySide/QML module | Check static registration/plugins; regenerate after changing module selection |
| Missing certifi/data/`.dist-info` | Preserve package trees and metadata; `.py`-only copying is insufficient |
| Read-only bundle writes | Use Documents/Application Support/Cache in the data container |
| `subprocess` unavailable | Expected iOS restriction; use an in-process library such as the FFmpeg bridge |
| `.mp4` will not play | Check container format; MPEG-TS renamed `.mp4` still needs remuxing |
| Black screen with live process | Check scene/window exposure and Metal; offscreen painting is not screen presentation |
| IPA entitlement/signature error | Re-sign/provision, remove private jailbreak entitlements and verify every framework |
| Python copy phase reports a missing keychain item | Supply the explicit ad-hoc expanded identity in the simulator command above |
| Framework labeled `APPL` | Normalize to `FMWK` before signing |
| `codesign` prints `[Dict]` | Add `--xml` when parsing its entitlement output with `plistlib` |

---

## Debugging Strategy (Highly Recommended)

Prove one layer at a time: UIKit → embedded Python → Qt window → QML/touch → native dependencies → full app.
Write a local startup log before depending on external networking:

```python
from pathlib import Path
import os, sys, traceback

working = Path.home() / 'Documents' / 'MyApp'
working.mkdir(parents=True, exist_ok=True)
os.chdir(working)
sys.stdout = (working / 'ios-runtime.log').open('w', buffering=1)
sys.stderr = sys.stdout

from PySide6.QtCore import qInstallMessageHandler
qInstallMessageHandler(lambda kind, context, message: print(message, flush=True))
print('Python entry reached', sys.version, sys.platform, flush=True)
```

Wrap your own entry function in exception handling and log `traceback.print_exc()` before re-raising.
For failures before Python starts, use Xcode's device console/crash organizer or macOS Console.
On stock iOS, do not assume SSH exists.

Our black-screen failure survived successful offscreen painting. Useful checks were
`MTLCreateSystemDefaultDevice()`, window/scene attachment, exposure and actual frame presentation.
The final touch counter was read back from the phone, not inferred from compilation.

---

## Building Qt and the Wheels Yourself

See [SOURCE_BUILD_6.12.md](SOURCE_BUILD_6.12.md): matching host tools, static device Qt, iOS 15
compatibility changes, Python discovery, host Shiboken generator and binding order.
[RUNTIME_BUILD.md](RUNTIME_BUILD.md) covers `.fwork` packaging, CFFI/libffi, selectolax/chompjs,
curl-cffi, cryptography/OpenSSL and the FFmpeg extension.
[SOURCE_BUILD_6.11.md](SOURCE_BUILD_6.11.md) retains the Android guide's historical chapter location
while explicitly recording that no PySide6 6.11 iOS build is claimed.

```bash
# Supported baseline; the first source build can take a long time.
TARGETS=ios_arm64 bash scripts/rebuild-ios-matrix.sh

# Experimental iPhone 7 path; use a different work root from an iOS 18 build.
WORK_ROOT="$PWD/work-ios15" IOS_DEPLOYMENT_TARGET=15.0 EXPERIMENTAL_IOS15=1 \
    TARGETS=ios_arm64 bash scripts/rebuild-ios-matrix.sh
```

Audits check formats, platforms and deployment targets; they do not execute the app. Three iOS
targets are not Android's multi-Python, four-ABI matrix.

---

## Contributing

Open an issue/PR with your host architecture, Xcode/SDK, Qt/PySide, embedded Python ABI, wheel
platform, deployment target and signing route. Say whether the device is jailbroken and report
build, installation and runtime success separately. Stock-device and Apple Silicon results are welcome.

## Support

A ⭐ helps others discover the guide. Detailed, dated evidence is in
[CURRENT_BUILD_NOTES.md](CURRENT_BUILD_NOTES.md).

## Donations

If this saved you time, you can support the work through:

- [PayPal](https://paypal.me/EchterAlsFake)
- [Ko-Fi](https://ko-fi.com/echteralsfake)

**Thank you very much <3**
