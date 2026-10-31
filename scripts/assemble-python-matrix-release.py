"""Assemble the completed Python 3.10–3.14 iOS matrix for signing/publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.work_root.resolve(), args.output.resolve()
    guide = Path(__file__).resolve().parent.parent
    state = json.loads((root / "python-matrix-state.json").read_text())
    checks = json.loads((root / "reports/application-checks.json").read_text())
    inputs = json.loads((guide / "scripts/python-matrix-inputs.json").read_text())
    versions = json.loads((guide / "scripts/versions.json").read_text())
    if not state.get("all_requested_builds_passed"):
        raise SystemExit("The binding matrix is incomplete")
    if subprocess.check_output(["git", "-C", str(guide), "status", "--porcelain"], text=True).strip():
        raise SystemExit("Commit the build/validation sources before assembling")
    commit = subprocess.check_output(["git", "-C", str(guide), "rev-parse", "HEAD"], text=True).strip()
    output.mkdir(parents=True, exist_ok=True)
    records = []

    def record(path, kind, **extra):
        assert path.stat().st_size < 2 * 1024**3, f"Oversized GitHub asset: {path}"
        records.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha(path), "kind": kind, **extra})

    def copy(path, kind, expected=None, **extra):
        if expected and sha(path) != expected:
            raise SystemExit(f"Unexpected artifact checksum: {path}")
        destination = output / path.name
        if destination.exists():
            assert sha(destination) == sha(path), f"Different existing asset: {path.name}"
        else:
            try:
                os.link(path, destination)
            except OSError:
                shutil.copy2(path, destination)
        record(destination, kind, **extra)

    for minor in ["3.10", "3.11", "3.12", "3.13", "3.14"]:
        for target in ["ios_arm64", "ios_arm64_simulator", "ios_x86_64_simulator"]:
            label = "cp" + minor.replace(".", "") + "-" + target
            built = state["stages"][label]
            checked = checks[minor][target]
            assert built["status"] == "passed" and checked.get("finished") and not checked.get("error")
            assert checked["xcodebuild_exit"] == 0 and checked["wheel_sha256"] == built["wheel_sha256"]
            if target == "ios_x86_64_simulator":
                assert checked["runtime_tested"] and checked["runtime_binding_count"] == 52
            for package in ["pyside6", "shiboken6"]:
                wheels = list((root / "wheels" / minor / target).glob(package + "-*.whl"))
                assert len(wheels) == 1
                copy(wheels[0], "target-wheel", built["wheel_sha256"][wheels[0].name], python=minor, target=target)
        info = inputs["python"][minor]
        copy(root / "downloads" / info["name"], "upstream-python-runtime", info["sha256"], python=minor)
        ipa = root / "ipas" / ("PySideMatrix-Python" + minor.replace(".", "") + "-ios15.ipa")
        copy(ipa, "resignable-device-test", checks[minor]["ios_arm64"]["ipa_sha256"], python=minor,
             stock_device_runtime_tested=False)
        copy(ipa.with_suffix(".json"), "device-test-packaging-report", python=minor)
        copy(ipa.with_suffix(".ipa.sha256"), "device-test-checksum", python=minor)
    source = root / "pyside-setup"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert revision == versions["source_revisions"]["pyside-setup"]
    for repository, name, prefix in [(source, "pyside-setup-v6.12.0.tar.gz", "pyside-setup-v6.12.0/"),
            (guide, "PySide6-to-iOS-python310-314-scripts.tar.gz", "PySide6-to-iOS/")]:
        destination = output / name
        subprocess.run(["git", "-C", str(repository), "archive", "--format=tar.gz", "--prefix=" + prefix,
                        "--output=" + str(destination), "HEAD"], check=True)
        record(destination, "corresponding-source" if repository == source else "build-scripts-and-patches")
    evidence = output / "python310-314-build-evidence.tar.zst"
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    with evidence.open("wb") as stream:
        tar = subprocess.Popen(["tar", "-cf", "-", "-C", str(root), "logs", "reports", "inputs.json",
                                "python-matrix-state.json", "run-python-matrix.py"], env=env, stdout=subprocess.PIPE)
        compressed = subprocess.run(["zstd", "-q", "-T6", "-8", "-c"], stdin=tar.stdout, stdout=stream)
        tar.stdout.close()
        assert tar.wait() == 0 and compressed.returncode == 0
    subprocess.run(["zstd", "-t", str(evidence)], check=True)
    record(evidence, "build-evidence")
    copy(guide / "scripts/python-matrix-validation.json", "matrix-validation")
    manifest = {"qt": "6.12.0", "minimum_ios": "15.0", "experimental": True, "qt_recompiled": False,
        "guide_commit": commit, "pyside_commit": revision, "python_inputs": inputs["python"],
        "shared_qt_kits": [x for x in inputs["qt_assets"] if x["name"].startswith("qt-")],
        "shared_qt_release": "https://github.com/EchterAlsFake/PySide6-to-iOS/releases/tag/6.12.0-ios15-cp315",
        "qt_corresponding_source": versions["full_matrix_sources"],
        "patches": versions["pyside_patches"], "host_deploy_patches": [versions["ios_deploy_patch"], *versions.get("ios_deploy_additional_patches", [])],
        "build_state": state, "application_checks": checks, "assets": records}
    path = output / "release-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    record(path, "manifest")
    (output / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['name']}\n" for r in sorted(records, key=lambda x: x['name'])))
    print(f"Assembled {len(records)} assets plus SHA256SUMS in {output}")


if __name__ == "__main__":
    main()
