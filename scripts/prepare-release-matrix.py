"""Fetch pinned sources and prepare the host environment for build-release-matrix.py.

Run with Python 3.13 on macOS as your normal login user. Set DEVELOPER_DIR first.
The work directory is dedicated to this run. This does not build Qt or CPython.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def fetch(url, digest, destination):
    if not destination.exists():
        partial = destination.with_suffix(destination.suffix + ".part")
        run("curl", "-fL", "--retry", "3", url, "-o", partial)
        partial.replace(destination)
    with destination.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise SystemExit(f"SHA-256 mismatch: {destination}: {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise SystemExit("Run as your normal macOS login user, not root.")
    if sys.version_info[:2] != (3, 13):
        raise SystemExit("Use Python 3.13 for the pinned host environment.")
    manifest = json.loads(Path(__file__).with_name("versions.json").read_text())
    root = args.work_root.resolve()
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    run("xcrun", "--sdk", "iphoneos", "--show-sdk-path")
    for info in manifest["full_matrix_sources"].values():
        archive = downloads / (info["directory"] + ".tar.xz")
        fetch(info["url"], info["sha256"], archive)
        source = root / info["directory"]
        marker = root / (info["directory"] + ".extracted")
        if not marker.exists():
            if source.exists():
                raise SystemExit(f"Untracked source tree exists: {source}. Use a fresh work root.")
            destination = root if info["enclosing_directory"] else source
            destination.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as bundle:
                bundle.extractall(destination, filter="data")
            marker.write_text(info["sha256"] + "\n")
    pyside = root / "pyside-setup"
    if not pyside.exists():
        run("git", "clone", "--depth", "1", "--branch", "v6.12.0",
            "https://github.com/pyside/pyside-setup.git", pyside)
    revision = subprocess.check_output(["git", "-C", str(pyside), "rev-parse", "HEAD"], text=True).strip()
    if revision != manifest["source_revisions"]["pyside-setup"]:
        raise SystemExit(f"Unexpected PySide source revision: {revision}")
    python = root / "venvs/build/bin/python"
    if not python.exists():
        run(sys.executable, "-m", "venv", python.parent.parent)
    generator = downloads / manifest["host_generator_url"].rsplit("/", 1)[1]
    fetch(manifest["host_generator_url"], manifest["host_generator_sha256"], generator)
    run(python, "-m", "pip", "install", "setuptools==78.1.0", "packaging==24.2",
        "build==1.2.2.post1", "wheel==0.46.3", "jinja2", "certifi", "html5lib==1.1", generator)
    runtime_archive = downloads / f"python-{manifest['python_release']}-iOS-XCframework.tar.gz"
    fetch(manifest["python_xcframework_url"], manifest["python_xcframework_sha256"], runtime_archive)
    runtime_root = root / "python" / manifest["python_release"]
    runtime = runtime_root / "Python.xcframework"
    if not runtime.exists():
        runtime_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(runtime_archive) as bundle:
            bundle.extractall(runtime_root, filter="data")
    for name in ["ios-arm64", "ios-arm64_x86_64-simulator"]:
        for link, target in [(f"include/python{manifest['python_abi']}", "../Python.framework/Headers"),
                             (f"lib/libpython{manifest['python_abi']}.dylib", "../Python.framework/Python")]:
            path = runtime / name / link
            path.parent.mkdir(exist_ok=True)
            if path.is_symlink():
                path.unlink()
            if not path.exists():
                path.symlink_to(target)
    print(f"Prepared {root}\nPython XCFramework: {runtime}")


if __name__ == "__main__":
    main()
