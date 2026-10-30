"""Build the tested local-file remux extension for one iOS target; no subprocess on iOS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

here = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--xcframework", type=Path, required=True)
parser.add_argument("--target", choices=["ios_arm64", "ios_arm64_simulator", "ios_x86_64_simulator"], default="ios_arm64")
parser.add_argument("--min-ios", default="18.0")
parser.add_argument("--work-root", type=Path, default=here.parent.parent / "work/ffmpeg")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--jobs", type=int, default=4)
args = parser.parse_args()
root = args.work_root.resolve()
root.mkdir(parents=True, exist_ok=True)
args.output.mkdir(parents=True, exist_ok=True)
archive = root / "ffmpeg-9.0.2.tar.xz"
if not archive.exists():
    subprocess.run(["curl", "-fL", "--retry", "3", "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz", "-o", str(archive)], check=True)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
source = root / "ffmpeg-9.0.2"
if not source.exists():
    with tarfile.open(archive) as bundle:
        bundle.extractall(root, filter="data")
simulator = args.target.endswith("_simulator")
arch = "x86_64" if "x86_64" in args.target else "arm64"
sdk_name = "iphonesimulator" if simulator else "iphoneos"
sdk = subprocess.check_output(["xcrun", "--sdk", sdk_name, "--show-sdk-path"], text=True).strip()
clang = subprocess.check_output(["xcrun", "--find", "clang"], text=True).strip()
triple = f"{arch}-apple-ios{args.min_ios}" + ("-simulator" if simulator else "")
slice_name = "ios-arm64_x86_64-simulator" if simulator else "ios-arm64"
headers = args.xcframework / slice_name / "Python.framework/Headers"
assert (headers / "Python.h").is_file()
build = root / f"{args.target}-min{args.min_ios}"
build.mkdir(exist_ok=True)
flags = (here / "configure_flags.txt").read_text().splitlines()
flags += ["--enable-cross-compile", "--target-os=darwin", f"--arch={'aarch64' if arch == 'arm64' else arch}",
          f"--cc={clang}", f"--sysroot={sdk}", f"--extra-cflags=-target {triple} -fPIC",
          f"--extra-ldflags=-target {triple}"]
if not (build / "config.h").exists():
    subprocess.run([str(source / "configure"), *flags], cwd=build, check=True)
subprocess.run(["make", f"-j{args.jobs}"], cwd=build, check=True)
configuration = (build / "config.h").read_text()
assert all(f"#define CONFIG_{name} 0" in configuration for name in ["GPL", "VERSION3", "NONFREE", "NETWORK"])
assert not re.search(r"^#define CONFIG_\w+_ENCODER 1$", (build / "config_components.h").read_text(), re.M)
suffix = "iphonesimulator" if simulator else "iphoneos"
output = args.output / f"_ios_ffmpeg.cpython-315-{suffix}.so"
command = [clang, "-target", triple, "-isysroot", sdk, "-O2", "-dynamiclib", "-undefined", "dynamic_lookup",
           "-I", str(headers), "-I", str(source), "-I", str(build), str(here / "bridge.c"), str(here / "apple-probe.m")]
command += [str(build / f"{lib}/{lib}.a") for lib in ["libavformat", "libavcodec", "libavutil"]]
command += ["-lz", "-liconv"]
for framework in ["CoreFoundation", "Security", "AVFoundation", "CoreMedia", "Foundation", "CoreVideo", "AudioToolbox"]:
    command += ["-framework", framework]
command += ["-Wl,-exported_symbol,_PyInit__ios_ffmpeg", "-o", str(output)]
subprocess.run(command, check=True)
legal = args.output / "ffmpeg-legal"
legal.mkdir(exist_ok=True)
for name in ["COPYING.LGPLv2.1", "LICENSE.md"]:
    shutil.copy2(source / name, legal / name)
for name in ["config.h", "config_components.h"]:
    shutil.copy2(build / name, legal / name)
(legal / "configuration.txt").write_text("\n".join(flags) + "\n")
(legal / "build.json").write_text(json.dumps({"version": "9.0.2", "target": args.target,
    "minimum_ios": args.min_ios, "extension_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, indent=2) + "\n")
print(output)
