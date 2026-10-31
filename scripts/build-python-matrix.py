"""Build Python 3.10–3.14 iOS bindings against reused, audited Qt 6.12 SDKs.

The work root supplies pinned Python XCFrameworks, Qt SDKs and a patched
v6.12.0 PySide source checkout. Qt itself is never compiled by this driver.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qt_matrix", HERE / "build-release-matrix.py")
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--python-versions", nargs="+", choices=["3.10", "3.11", "3.12", "3.13", "3.14"],
                        default=["3.10", "3.11", "3.12", "3.13", "3.14"])
    parser.add_argument("--targets", nargs="+", choices=matrix.TARGETS, default=list(matrix.TARGETS))
    parser.add_argument("--qt-host-path", type=Path)
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise SystemExit("Run as your normal macOS login user, not root.")
    root = args.work_root.resolve()
    lock = (root / ".bindings-matrix.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = root / "pyside-setup"
    host = args.qt_host_path.resolve() if args.qt_host_path else root / "qt/6.12.0/macos"
    python = root / "venvs/build/bin/python"
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == "f50facb83fc3dc5f3240c854668c7a6dd93871b2"
    for name in ["moc", "rcc", "qmlcachegen", "qmltyperegistrar", "repc", "qscxmlc"]:
        if not (host / "libexec" / name).is_file():
            raise SystemExit(f"Incomplete Qt host kit: missing {name}: {host}")
    if subprocess.check_output([str(host / "bin/qmake"), "-query", "QT_VERSION"], text=True).strip() != "6.12.0":
        raise SystemExit("Qt host must be 6.12.0")
    generator = subprocess.check_output([str(python), "-c",
        "import importlib.util,pathlib; print(pathlib.Path(importlib.util.find_spec('shiboken6_generator').origin).parent)"], text=True).strip()
    env = os.environ.copy()
    env["PATH"] = str(python.parent) + ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    state_path = root / "python-matrix-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "qt": "6.12.0", "minimum_ios": "15.0", "qt_recompiled": False,
        "started": datetime.now(timezone.utc).isoformat(), "stages": {}}
    state["requested_python_versions"] = args.python_versions
    state["requested_targets"] = args.targets
    state["all_requested_builds_passed"] = False
    state.pop("finished", None)

    def save():
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(state_path)

    def run(name, command, cwd=None, capture=False):
        log = root / "logs" / (name + ".log")
        print("Running", name, flush=True)
        with log.open("a") as stream:
            stream.write("\nCOMMAND " + json.dumps(list(map(str, command))) + "\n")
            stream.flush()
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                stdout=subprocess.PIPE if capture else stream, stderr=stream, text=capture)
            if capture:
                stream.write(result.stdout)
        if result.returncode:
            state["last_failure"] = {"stage": name, "exit": result.returncode, "log": str(log)}
            save()
            raise SystemExit(f"Failed {name}: {log}")
        return result.stdout if capture else None

    for minor in args.python_versions:
        framework = root / "python" / minor / "Python.xcframework"
        assert framework.is_dir()
        for target in args.targets:
            label = "cp" + minor.replace(".", "") + "-" + target
            if state["stages"].get(label, {}).get("status") == "passed":
                print("Already passed", label, flush=True)
                continue
            state["active_stage"] = label
            state["stages"][label] = {"status": "running", "started": datetime.now(timezone.utc).isoformat()}
            state.pop("last_failure", None)
            save()
            arch, sdk, prefix_name, python_slice = matrix.TARGETS[target]
            runtime = json.loads(run(label + "-runtime", [python, HERE / "inspect-ios.py", "runtime", framework,
                "--target", target, "--max-ios", "15.0"], capture=True))
            assert runtime["python_version"] == minor
            (root / "reports" / (label + "-runtime.json")).write_text(json.dumps(runtime, indent=2) + "\n")
            prefix = root / "qt/6.12.0" / prefix_name
            assert (prefix / "lib/cmake/Qt6/qt.toolchain.cmake").is_file()
            toolchain = root / ("toolchain-" + label + ".cmake")
            values = {"CMAKE_SYSTEM_PROCESSOR": arch, "CMAKE_OSX_ARCHITECTURES": arch,
                "CMAKE_OSX_SYSROOT": sdk, "CMAKE_OSX_DEPLOYMENT_TARGET": "15.0", "QT_APPLE_SDK": sdk,
                "QT_HOST_PATH": host, "BUILD_SHARED_LIBS": "OFF", "BUILD_WITH_PCH": "OFF",
                "CMAKE_DISABLE_PRECOMPILE_HEADERS": "ON",
                "Python_INCLUDE_DIR": framework / python_slice / ("include/python" + minor),
                "Python_LIBRARY": framework / python_slice / ("lib/libpython" + minor + ".dylib"),
                "PYTHON_EXECUTABLE": python,
                "Python_SOABI": "cpython-" + minor.replace(".", "") + "-" + sdk,
                "SHIBOKEN_WRAPPER_HOST_QT_LIB_PATH": generator + "/Qt/lib",
                "SHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH": generator + "/Qt/lib"}
            toolchain.write_text('include(' + json.dumps(str(prefix / "lib/cmake/Qt6/qt.toolchain.cmake")) + ')\n'
                + "\n".join(f'set({k} {json.dumps(str(v))} CACHE STRING "Python matrix" FORCE)' for k, v in values.items()) + "\n")
            marker = root / "bindings-current.txt"
            if not marker.exists() or marker.read_text().strip() != label:
                for path in [source / "build", source / "dist"]:
                    if path.exists():
                        shutil.rmtree(path)
                marker.write_text(label + "\n")
            output = root / "wheels" / minor / target
            output.mkdir(parents=True, exist_ok=True)
            run(label + "-build", [python, "setup.py", "bdist_wheel", "--standalone", "--no-qt-tools",
                "--reuse-build", "--limited-api=no", "--disable-pyi", "--skip-mypy-test", "--disable-numpy-support",
                f"--shiboken-host-path={generator}", f"--qt-host-path={host}", f"--qt-target-path={prefix}",
                f"--python-target-path={framework / python_slice}", f"--cmake-toolchain-file={toolchain}",
                f"--plat-name={target}", f"--dist-dir={output}", f"--parallel={args.jobs}"], cwd=source)
            audit = json.loads(run(label + "-audit", [python, HERE / "check-ios-wheels.py", output,
                "--target", target, "--max-ios", "15.0", "--python-version", minor], capture=True))
            inventory = matrix.binding_inventory(output, prefix, target)
            inventory.update(python_version=minor, qt_recompiled=False)
            (root / "reports" / (label + "-modules.json")).write_text(json.dumps(inventory, indent=2) + "\n")
            (root / "reports" / (label + "-wheels.json")).write_text(json.dumps(audit, indent=2) + "\n")
            state["stages"][label].update(status="passed", finished=datetime.now(timezone.utc).isoformat(),
                wheel_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.whl")})
            state.pop("last_failure", None)
            save()
            shutil.rmtree(source / "build", ignore_errors=True)
    state["active_stage"] = None
    state["all_requested_builds_passed"] = True
    state["finished"] = datetime.now(timezone.utc).isoformat()
    save()
    print("All requested Python/target wheel pairs passed.", flush=True)


if __name__ == "__main__":
    main()
