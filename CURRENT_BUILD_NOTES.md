# Qt 6.12 / PySide6 iOS investigation

Reference dates: **28–30 October 2026**. This is the iOS counterpart to the
Android guide's build diary. It records observed results separately from
what a new portable build script promises.

## Required versions and host

- Intel macOS 15.7.2 VM on an Arch Linux host, initially 4 virtual CPUs and
  later 8; 16 GB RAM; no usable VM GPU.
- Xcode 26.3 with iPhoneOS/iPhoneSimulator 26.2 SDKs; full Xcode kept outside
  `/Applications` during the experiment. `DEVELOPER_DIR` selected it per shell.
- Host Python 3.13.16; PySide/Shiboken 6.12.0; embedded official Python 3.15.0rc2.
- Physical target: iPhone 7, `iPhone9,1`, iOS 15.8.8, palera1n rootless.
- Exact Qt source revisions and reference wheel hashes are in
  [`scripts/versions.json`](scripts/versions.json).

## 28 October — simulator to physical device

The Intel simulator used public `ios_x86_64_simulator` wheels. The simulator
could run without a VM GPU using `QT_QUICK_BACKEND=rhi`, `QSG_RHI_BACKEND=opengl`
and `QSG_RENDER_LOOP=basic` passed through `SIMCTL_CHILD_…` at launch.
These are simulator-specific settings; the phone uses default Metal rendering.

Moving to an older phone required a new ARM64 Qt/PySide build for iOS 15;
the official Qt 6.12 minimum is 18. Host and target kits, native packages,
wheels, bundle IDs and data containers were kept separate from the simulator.

### Compiler and source-build findings

- `os_sync_*` locking APIs required 17.4. The patch selects the generic mutex
  path with the older public Mach-semaphore implementation and consistent futex flags.
- Metal 3/HDR and several UIKit/EventKit/accessibility/hover APIs needed runtime guards.
- Availability warnings were errors for all four source languages.
- Host QML tools built with host animation disabled; target Quick remained enabled.
- A normalized include/lib view into Python.framework fixed FindPython.
- The host Shiboken generator wheel already linked Clang statically; another LLVM SDK was unnecessary.
- Build OpenGL bindings before Quick. The opposite order broke generated-header lookup.
- Never silently reuse an unpacked `_wheels` cache after replacing its source wheels.

### Milestones actually verified

| Stage | Evidence/result |
| --- | --- |
| Native UIKit | User saw “Hello World! Apple toolchain works.” |
| Embedded Python | stdlib/platform/computation probe succeeded |
| Qt rendering | Python + Qt text visibly confirmed |
| QML/Material | User confirmed screen/button; counter read back as five taps |
| Graphics | Apple A10 Metal device, exposed window, presented frames |
| Native packages | CFFI, chompjs, selectolax, curl-cffi sync/async and cryptography checks passed |
| Real app | User confirmed interface and smooth operation |
| Media workflow | User downloaded, found the file, later played the remux and confirmed a fresh automatic remux |

### Jailbreak deployment and Metal

The phone was reached over Wi-Fi SSH from the NATed VM; a bridged VM address
was not required in this network. Ping failure alone was not proof that SSH
would fail. No phone IP, password, SSH identity or pairing file is published here.

Rootless installation used `/var/jb/Applications`, a rootless shell, `ldid`,
`uicache` and `uiopen`. The app's separate data container was preserved across
bundle updates. Stop the **actual executable** (`<name>_bin` for the generated
Python launcher), not only the app display name, before replacing a bundle.

Initial Qt tests stayed alive and rendered a correct offscreen image while
the physical screen remained black. Adding `UIApplicationSceneManifest` /
`QIOSWindowSceneDelegate` was necessary but insufficient. The key result was
that both Metal device creation and GLES context creation were denied under
the ad-hoc jailbreak signing setup.

A narrow `com.apple.security.iokit-user-client-class` allowlist for the A10
graphics/IOSurface classes restored graphics access in that **jailbreak**
installation. It did not add no-sandbox/platform-app/JIT privileges or change
global jailbreak settings. This does **not** establish that normal stock
development-signed apps need or may request that private entitlement.

The explicit scene configuration used:

```xml
<key>UIApplicationSceneManifest</key>
<dict>
  <key>UIApplicationSupportsMultipleScenes</key><false/>
  <key>UISceneConfigurations</key>
  <dict>
    <key>UIWindowSceneSessionRoleApplication</key>
    <array><dict>
      <key>UISceneConfigurationName</key><string>Default Configuration</string>
      <key>UISceneDelegateClassName</key><string>QIOSWindowSceneDelegate</string>
    </dict></array>
  </dict>
</dict>
```

### Native dependency and FFmpeg findings

CFFI initially crashed in its closure preparation. Enabling its Apple/libffi
trampoline-table path made both a native call and callback work without JIT.
curl-cffi passed certificate-verified synchronous and asyncio requests.
cryptography passed Ed25519 and AES-GCM probes. The OpenSSL legacy-provider
warning was recorded rather than hidden; legacy algorithms were not tested.

The first phone download was 445,108,800 bytes of MPEG-TS with an `.mp4` name.
Apple reported it unreadable/unplayable. Standard embedded Python could not
launch a desktop FFmpeg subprocess, so a CPython extension linked static FFmpeg
libraries and copied the encoded streams into a faststart MP4.

Remux took 4.893 s; output with metadata and a generic PNG cover was
431,414,546 bytes, duration 1034.733333 s, H.264 1280×720/30fps and stereo AAC.
AVFoundation decoded audio and video. Full independent decoding counted
31,040 video / 44,562 audio frames, zero corrupt packets, zero decoding errors
and zero timestamp regressions. A single cover-art timescale probe warning
was retained in the report. The user confirmed playback with sound and a
fresh app download that remuxed automatically.

## 30 October — stock-iOS IPA preparation

A separate **PornFetch Test** IPA was prepared for iLoader on Arch Linux,
then SideStore. Its ID is `local.asuna.PornFetch.Sideload`; the original
jailbreak installation was left alone. No Apple signing identity was configured
on the Mac, so this is a re-signable ad-hoc package, not a provisioned distribution build.

Packaging found and corrected:

- Original jailbreak signatures were not valid Apple-tool signatures.
- The private GPU entitlement must not be carried into stock provisioning.
- 74 extension frameworks declared `APPL`; the packaged copy normalizes them to `FMWK`.
- Copied `.o`, static/linker/CMake build artifacts do not belong in the runtime bundle.
- `codesign`'s default entitlement display was human-readable `[Dict]`;
  `--xml` produced parseable plist output.

The resulting IPA is **93,709,928 bytes** (89.37 MiB), with 75 embedded
frameworks and 8,300 ZIP entries. Its SHA-256 is
`b45ae5db0a9957d14ec1c364ab36716353fb23dc8722cda100acf970beafc1b3`.
All 76 executable images were ARM64 device iOS: 7 minimum-15 images and
69 minimum-13 images. The app advertises minimum iOS 15. Every nested
signature, `.fwork` path and archive CRC passed; the uploaded digest matched.

**No stock-device installation or runtime result has been received.** This
must remain separate from the jailbreak proof. Background downloads and
memory-pressure behavior also remain unverified.

## Guide repository adaptation

The Android guide was cloned at commit `ec8b41c` and its history/layout retained:
README, current notes, runtime chapter, source-build chapters and `scripts/`.
Android helpers were replaced by iOS equivalents; the historical 6.11 filename
now explains why no 6.11 iOS recipe is claimed. Donation/support links are retained.

Unlike the original lab scripts, the new helpers use configurable work roots,
explicit target selection and a source/hash manifest rather than a personal
username, simulator UUID or phone address. They do not install to a phone,
change global Xcode selection, or run live provider/account tests automatically.

The generalized source-build helpers are adaptations of commands that built
the reference artifacts. Do not interpret syntax/audit checks as a second
clean source build or a completed three-target runtime matrix. Guide-specific
verification details are recorded alongside the scripts and in the publishing commit.

Guide-specific checks on 30 October:

- Python sources and documented shell blocks parse; shell helpers parse under macOS Bash 3.2.
- The device wheel pair passes inspection of 3,573 selected Mach-O objects, all minimum iOS 15.
- The Intel simulator pair passes 8,331 selected objects, maximum minimum iOS 18. Embedded
  FFmpeg XCFrameworks have additional slices; the auditor selects them using metadata.
- Python device, ARM simulator and Intel simulator slices pass metadata/header/platform audits.
- The auditor correctly rejects the official Intel wheels when asked for a maximum iOS 15 minimum.
- The copied legacy Qt patch reverse-applies cleanly to the actual patched source used for the build.
- The generic IPA helper packages the reference device app with 75 normalized frameworks,
  valid relative extension markers, empty entitlements, verified signatures and valid ZIP CRCs.
- The new minimal Hello World generates an Xcode project and **builds successfully for the Intel
  simulator**. This check does not claim a new human runtime/touch test of that example.
- The generic simulator destination initially attempted ARM64 as well as Intel; the quickstart now
  selects `ARCHS=x86_64 ONLY_ACTIVE_ARCH=YES`. With Xcode signing disabled, CPython's own build phase
  also needed explicit `EXPANDED_CODE_SIGN_IDENTITY=-` instead of an empty identity. Both fixes are documented.
- Local Markdown paths/anchors and public checksum endpoints for all three wheel targets were checked.

Machine-readable results: [`scripts/validation.json`](scripts/validation.json).

## 31 October — full matrix and stock-device test

The fresh full-module Qt/PySide 6.12.0 device kit and ARM64 simulator kit
have completed their builds and binary audits. Each contains 52 supported
Qt bindings, the QtQmlFeatures/QtAsyncio helpers, 105 QML modules and 314
translation catalogs. All-module applications link for both ARM64 targets.
The Intel simulator build is still in progress; the complete release is
not published yet.

The fresh device test app was packaged as `PySideMatrixSmoke-ios15.ipa`
for re-signing, with minimum iOS 15, 69 embedded frameworks and empty ad-hoc
entitlements. Its input SHA-256 is
`5e90a1ed23ffd4177327aa2baa1b376db7407e569e7eaabe106dcfdb6369cfa2`.
The user installed it on the non-jailbroken iPhone 7 running iOS 15.8.8
and confirmed all module imports and the working tap counter. This is a
stock-device Python/Qt import, window and touch test; it does not exercise
every module's hardware, media or networking features. It also does not
establish a stock-device result for the separate PornFetch application IPA.

The source and deployment patches now include UiTools' `libuiplugin.a`
and link it and `libpyside6remoteobjects.a` when their modules are used.
The generic IPA helper fills in Qt's missing scene delegate even when the
generated plist already has a scene manifest. Document sharing can be
enabled to retrieve the smoke application's JSON report and log.

See [the full matrix workflow](RELEASE_MATRIX.md) for sources, exclusions,
patches and verification details.

## Artifacts and provenance

The [public application lab source snapshot](https://github.com/EchterAlsFake/Porn_Fetch/tree/ios/iphone7-port-snapshot-2026-10-28/ios-lab)
contains the original scripts/reports. Its large build-state archive and IPA
were placed in a **draft** release visible to the maintainer; public readers
should not rely on access to those assets. This guide supplies public-source
recipes, the actual Qt compatibility patch and a generic FFmpeg bridge instead.

No private SSH keys, GPG keys, Apple credentials, personal runtime databases,
downloaded media or signed media URLs are included in this guide.
