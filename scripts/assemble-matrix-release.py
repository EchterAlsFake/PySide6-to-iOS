"""Assemble completed iOS 15 matrix artifacts; does not sign or publish them."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

TARGET_NAMES = {"ios_arm64": "ios_device", "ios_arm64_simulator": "ios_simulator_arm64",
                "ios_x86_64_simulator": "ios_simulator_x86_64"}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--python-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.work_root.resolve(), args.output.resolve()
    state = json.loads((root / "matrix-state.json").read_text())
    application_report = root / "reports" / "smoke-link-results.json"
    application_checks = json.loads(application_report.read_text()) if application_report.exists() else {}
    if not state.get("all_requested_builds_passed") or set(state["targets"]) != set(TARGET_NAMES):
        raise SystemExit("A completed, audited three-target build is required.")
    for target in TARGET_NAMES:
        if state["stages"][target + "-bindings"]["status"] != "passed":
            raise SystemExit(f"Incomplete binding build: {target}")
    versions = json.loads(Path(__file__).with_name("versions.json").read_text())
    guide = Path(__file__).resolve().parent.parent
    if subprocess.check_output(["git", "-C", str(guide), "status", "--porcelain"], text=True).strip():
        raise SystemExit("Commit the release scripts/docs first; the source snapshot must match a clean commit.")
    guide_revision = subprocess.check_output(["git", "-C", str(guide), "rev-parse", "HEAD"], text=True).strip()
    if sha256(args.python_archive) != versions["python_xcframework_sha256"]:
        raise SystemExit("Unexpected CPython archive checksum")
    output.mkdir(parents=True, exist_ok=True)
    records = []

    def record(path, kind, **details):
        if path.stat().st_size >= 2 * 1024**3:
            raise SystemExit(f"GitHub asset exceeds 2 GiB: {path}")
        records.append({"name": path.name, "kind": kind, "bytes": path.stat().st_size,
                        "sha256": sha256(path), **details})

    def copy(path, kind, **details):
        destination = output / path.name
        if destination.exists():
            if sha256(destination) != sha256(path):
                raise SystemExit(f"Different existing release asset: {destination}")
        else:
            try:
                os.link(path, destination)
            except OSError:
                shutil.copy2(path, destination)
        record(destination, kind, **details)

    def compress(name, paths):
        destination = output / name
        temporary = destination.with_suffix(destination.suffix + ".part")
        env = os.environ.copy()
        env["COPYFILE_DISABLE"] = "1"
        with temporary.open("wb") as stream:
            tar = subprocess.Popen(["tar", "-cf", "-", "-C", str(root), *paths],
                                   stdout=subprocess.PIPE, env=env)
            zstd = subprocess.run(["zstd", "-T6", "-8", "-c"], stdin=tar.stdout,
                                  stdout=stream, env=env)
            tar.stdout.close()
            tar_status = tar.wait()
        if tar_status or zstd.returncode:
            raise SystemExit(f"Archive creation failed: {name}")
        subprocess.run(["zstd", "-t", str(temporary)], check=True)
        temporary.replace(destination)
        return destination

    for target, name in TARGET_NAMES.items():
        for package in ["pyside6", "shiboken6"]:
            wheels = list((root / "wheels" / target).glob(package + "-*.whl"))
            if len(wheels) != 1:
                raise SystemExit(f"Expected one {package} wheel for {target}")
            copy(wheels[0], "target-wheel", target=target)
        record(compress(f"qt-sdk-6.12.0-ios15-{target}.tar.zst", [f"qt/6.12.0/{name}"]),
               "static-qt-sdk", target=target)
    record(compress("qt-host-6.12.0-macos-x86_64.tar.zst", ["qt/6.12.0/macos"]), "host-qt-kit")
    copy(args.python_archive, "upstream-python-runtime")
    test_ipa = root / "ipas" / "PySideMatrixSmoke-ios15.ipa"
    if test_ipa.exists():
        ipa_report = json.loads(test_ipa.with_suffix(".json").read_text())
        if sha256(test_ipa) != ipa_report["sha256"]:
            raise SystemExit("Test IPA does not match its packaging report")
        copy(test_ipa, "resignable-device-smoke-app", target="ios_arm64",
             stock_device_runtime_tested=application_checks.get("ios_arm64", {}).get("stock_device_runtime_tested", False))
        copy(test_ipa.with_suffix(".json"), "device-smoke-app-packaging-report")
    for info in versions["full_matrix_sources"].values():
        path = root / "downloads" / (info["directory"] + ".tar.xz")
        if sha256(path) != info["sha256"]:
            raise SystemExit(f"Unexpected source checksum: {path}")
        copy(path, "corresponding-source")
    pyside_source = output / "pyside-setup-v6.12.0.tar.gz"
    subprocess.run(["git", "-C", str(root / "pyside-setup"), "archive", "--format=tar.gz",
                    "--prefix=pyside-setup-v6.12.0/", f"--output={pyside_source}", "HEAD"], check=True)
    record(pyside_source, "corresponding-source")
    guide_source = output / "PySide6-to-iOS-build-scripts.tar.gz"
    subprocess.run(["git", "-C", str(guide), "archive", "--format=tar.gz",
                    "--prefix=PySide6-to-iOS/", f"--output={guide_source}", "HEAD"], check=True)
    record(guide_source, "build-scripts-and-patches", git_commit=guide_revision)
    evidence = ["logs", "reports", "matrix-state.json", "run-provenance.json"]
    record(compress("ios15-matrix-build-evidence.tar.zst", evidence), "build-evidence")
    inventories = {target: json.loads((root / "reports" / f"{target}-modules.json").read_text())
                   for target in TARGET_NAMES}
    manifest = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "qt": "6.12.0", "pyside": "6.12.0", "qt_pdf_source": "6.140.0",
                "python": "3.15.0rc2", "minimum_ios": "15.0", "experimental": True,
                "host_kit": {"architecture": "x86_64", "minimum_macos": "15.0",
                             "native_apple_silicon_host_tools": False},
                "guide_source_commit": guide_revision,
                "build_state": state, "inventories": inventories,
                "application_checks": application_checks, "assets": records,
                "sources_and_patches": versions}
    path = output / "release-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    record(path, "manifest")
    checksums = output / "SHA256SUMS"
    checksums.write_text("".join(f"{r['sha256']}  {r['name']}\n" for r in sorted(records, key=lambda x: x['name'])))
    print(f"Prepared {len(records)} assets and SHA256SUMS in {output}")


if __name__ == "__main__":
    main()
