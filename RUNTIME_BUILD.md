# iOS Python runtime and native dependencies

This mirrors the Android guide's runtime chapter, but does not pretend that
an NDK recipe works on iOS. The reference embedded the official CPython
3.15.0rc2 XCFramework and built third-party native modules for the selected
Apple target. No Python executable or `pip` is installed system-wide on a stock phone.

## Prepare and audit Python.xcframework

```bash
bash scripts/build-ios-runtime.sh
bash scripts/check-ios-runtime.sh "$PWD/work/python/3.15.0rc2/Python.xcframework" ios_arm64
```

Despite the mirrored helper name, the first command **downloads and prepares**
the official runtime; it does not recompile CPython. It verifies SHA-256
`2496d92689da625cd349e856e17b3d540787f8d17806e21536e8d394d940adc0`.
Override `PYTHON_XCFRAMEWORK` to reuse an existing extraction. For a different
embedded Python release, update the pins, rebuild matching bindings/extensions
and follow CPython's `Platforms/Apple` instructions rather than renaming wheel tags.

The official runtime supplies common `lib/python3.15` code and target slices:

```text
Python.xcframework/
  lib/python3.15/
  ios-arm64/Python.framework/
  ios-arm64_x86_64-simulator/Python.framework/
```

The helper adds `include/python3.15` and `lib/libpython3.15.dylib` symlinks in
the slices for CMake discovery. Keep the common standard library and matching
architecture-specific stdlib extensions; copying only `Python.framework` is insufficient.

The runtime audit checks the XCFramework metadata, selected CPU/platform,
headers and common standard library. It cannot prove that `_ssl`, `_ctypes`
or any third-party extension will work in an actual installed app.

## Packaging pure Python and native extensions

Keep package resources and `.dist-info`, not only `.py` files. The reference
needed certificate bundles and metadata as well as Python source. Its vendor
overlay was copied into the app's `packages` directory and placed on `sys.path`.

For Xcode, add [`scripts/bundle-vendor.sh`](scripts/bundle-vendor.sh) **after**
the generated Python copy phases and **before** final app signing. Set
`VENDOR_DIR` to your staged iOS packages and `PYTHON_XCFRAMEWORK` to the same
runtime used by PySide. The script copies full package trees and calls the
runtime's `build/utils.sh` function `process_dylibs`.

That converts each `.so` extension into a separately signed framework under
`Frameworks/`, leaves a relative `.fwork` marker on the Python import path,
and records the corresponding `.origin`. Do not invent an absolute path to
your Mac or leave executable `.so` files loose inside package directories.
See [CPython's packaging explanation](https://docs.python.org/3.15/using/ios.html).

Before stock IPA packaging, check that every framework declares
`CFBundlePackageType=FMWK`. The support script in our pinned runtime generated
`APPL` for 74 extension frameworks; the IPA helper corrects these on a copy
before re-signing. Also remove copied object/static build files from runtime
resources. Qt/PySide's static modules are registered by the native launcher;
ordinary third-party extensions use the CPython framework-loader route.

## Native dependency reference

These versions and results belong to the actual iPhone 7 experiment:

| Dependency | Reference | Device result |
| --- | --- | --- |
| libffi / CFFI | 3.8.0 / 2.1.1 | libc call and callback passed |
| chompjs | 1.4.1 | Parsed JavaScript object |
| selectolax | 1.0.2 | Lexbor HTML/CSS query |
| curl-cffi / curl-impersonate | 0.17.0 / 2.3.1 | Certificate-verified HTTPS, sync and asyncio |
| cryptography / OpenSSL | 50.0.2 / 3.5.9 | Ed25519 verification and AES-GCM round trip |
| FFmpeg | 9.0.2 | TS→MP4, metadata, cover art, native playback and full decode |

Use target Python headers, `xcrun --sdk iphoneos`, and
`-target arm64-apple-ios15.0` for the experimental device build. A simulator
requires `iphonesimulator` and a `...-simulator` triple, even when ARM64.
The output suffix was `.cpython-315-iphoneos.so`; CPython's packaging step
later moves the executable code into its framework.

### CFFI and libffi

The first callback crashed in `ffi_prep_closure_loc` because CFFI's allocator
did not match the target libffi's Apple trampoline-table configuration. The
working CFFI build adds:

```text
-DFFI_AVAILABLE_APPLE=1 -DFFI_EXEC_TRAMPOLINE_TABLE=1
```

alongside its existing libffi include/archive, `FFI_BUILDING`, threading and
synchronization definitions. Rebuilding only Python wrapper code is not enough.
This tested configuration did not add a JIT entitlement. It is not a general
instruction to enable executable-memory entitlements in a stock app.

### chompjs and selectolax

chompjs compiles its C module/parser/buffer against target Python. For
selectolax, compile the generated Lexbor wrapper plus the Lexbor source set
with `LEXBOR_STATIC` and the correct include root. Do not mix the simulator's
objects into the device extension. Keep per-target object directories; compiling
one source at a time with bounded parallelism worked within 16 GB RAM.

### curl-cffi

Generate the CFFI wrapper from the matching curl-cffi source and its `shim.h` /
`shim.c`, then link the target curl-impersonate static archive, C++/zlib/iconv/
resolver libraries and required Apple frameworks. Our device archive was
`libcurl-ios-arm64.tar.gz` from curl-impersonate 2.3.1, SHA-256
`16a3095fe0b107af2007be22b87c9f594658a04a22ad694abfd460f9bd70743e`.

Preserve `certifi` data, and test both synchronous requests and `AsyncSession`.
The reference probes used HTTPS to example.com, not a provider/account test.

### cryptography / OpenSSL

Build static OpenSSL for the selected iOS target, then use the matching Rust
target (`aarch64-apple-ios` on the phone), SDKROOT, deployment minimum, target
Python sysconfig data, headers and libpython compatibility view. The host and
target Rust outputs must remain separate.

An existing build-script branch intended for macOS needed narrowing from all
Apple targets to `apple-darwin`; applying macOS runtime-linking assumptions to
iOS broke cross-compilation. The resulting `_rust.abi3.so` still needs iOS
framework packaging. Do not mistake its `abi3` suffix for cross-platform binary compatibility.

The app logged OpenSSL's unavailable legacy provider. Modern HTTPS, Ed25519
and AES-GCM tests passed; legacy cipher/provider behavior was not validated.

The exact application-specific source recipes remain available in the
[public lab source snapshot](https://github.com/EchterAlsFake/Porn_Fetch/tree/ios/iphone7-port-snapshot-2026-10-28/ios-lab).
They are reference recipes, not a universal resolver for arbitrary native packages.

## In-process FFmpeg remuxing

An iOS Python app cannot rely on launching the desktop `ffmpeg` executable
through `subprocess`. The working solution links libavformat/libavcodec/libavutil
into `_ios_ffmpeg`, a small CPython extension. It releases the GIL during local
file I/O and stream-copies audio/video into MP4 with `+faststart`; it does not encode video.

The portable reference bridge and build helper are included:

```bash
python3.13 scripts/ffmpeg/build.py \
    --xcframework /absolute/path/to/Python.xcframework \
    --target ios_arm64 --min-ios 15.0 \
    --work-root "$PWD/work-ios15/ffmpeg" \
    --output "$PWD/work-ios15/vendor" --jobs 4
```

Use `18.0` for the supported baseline. Device output has the matching CPython
3.15 suffix and must go through the vendor/framework packaging phase. The
device bridge was run in the real app; the generalized build wrapper and its
simulator options are adaptations, not a new runtime test matrix.

Python usage after packaging:

```python
import _ios_ffmpeg
packets = _ios_ffmpeg.remux('/writable/input.ts', '/writable/output.mp4',
                            {'title': 'Local video'}, None)
```

The fourth argument optionally names a JPEG/PNG cover file. Input and output
must be different files. For tagging an existing MP4, write a temporary output
and replace the original only after success. Run this blocking operation with
`await asyncio.to_thread(...)` in an asynchronous app; no QThread is required.

FFmpeg's `aac_adtstoasc` filter is included for ADTS AAC, and the MP4 muxer
inserts the required conversion. [FFmpeg documents this behavior](https://ffmpeg.org/ffmpeg-bitstream-filters.html#aac_005fadtstoasc).
The build disables GPL/version3/nonfree/network features and all encoders.
It retains license/configuration files beside the extension; the upstream
source archive and static libraries remain in the work directory.

Do not equate a `.mp4` extension with an MP4 container: our 425 MiB download
was MPEG-TS. The phone remux took 4.893 s. AVFoundation then decoded both video
and audio; an independent full-file check decoded 31,040 video frames and
44,562 audio frames with zero corrupt packets or decoding errors. The user
confirmed playback and a fresh download's automatic remux.

## Runtime limits

- Use app-owned Documents/Application Support/Cache paths. `sys.platform` is
  `ios` on both simulator and device; Darwin alone does not mean macOS.
- Keep desktop services and Android-only APIs out of the iOS composition root.
- No account, licensing or provider test runs automatically in these helpers.
- Background transfers and memory-pressure behavior remain unverified.
- Our IPA packaging/signature checks do not prove stock-iOS native-module behavior.

Primary references: [CPython iOS](https://docs.python.org/3.15/using/ios.html),
[FFmpeg remuxing example](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/doc/examples/remux.c),
[Apple bundle types](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundlepackagetype).
