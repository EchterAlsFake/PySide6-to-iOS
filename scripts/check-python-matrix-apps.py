"""Link every completed Python-matrix pair; run imports on the native simulator.

Polls the build driver's state, saves per-pair application checks, and packages
device test IPAs. It never treats Qt window visibility as a visual rendering test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--deploy-venv", type=Path, required=True)
    parser.add_argument("--simulator", required=True, help="Available simulator device UUID")
    args = parser.parse_args()
    root = args.work_root.resolve()
    guide = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PATH"] = str(args.deploy_venv / "bin") + ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    output = root / "reports/application-checks.json"
    checks = json.loads(output.read_text()) if output.exists() else {}

    def save():
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(checks, indent=2) + "\n")
        temporary.replace(output)

    def command(label, argv, cwd=None, launch_env=None, capture=False):
        with (root / "logs" / (label + ".log")).open("a") as stream:
            stream.write("\nCOMMAND " + json.dumps(list(map(str, argv))) + "\n")
            stream.flush()
            result = subprocess.run(list(map(str, argv)), cwd=cwd, env=launch_env or env,
                stdout=subprocess.PIPE if capture else stream, stderr=stream, text=capture)
            if capture:
                stream.write(result.stdout)
        if result.returncode:
            raise RuntimeError(f"{label} failed with exit {result.returncode}")
        return result.stdout if capture else None

    targets = {"ios_arm64": ("arm64", False), "ios_arm64_simulator": ("arm64", True),
               "ios_x86_64_simulator": ("x86_64", True)}
    pending = {(v, t) for v in ["3.10", "3.11", "3.12", "3.13", "3.14"] for t in targets}
    deadline = time.monotonic() + 18 * 3600
    while pending:
        assert time.monotonic() < deadline, "Timed out waiting for matrix app checks"
        state = json.loads((root / "python-matrix-state.json").read_text())
        progress = False
        for minor, target in sorted(pending, key=lambda pair: (pair[0],
                0 if targets[pair[1]][1] and targets[pair[1]][0] == platform.machine() else 1, pair[1])):
            label = "cp" + minor.replace(".", "") + "-" + target
            built = state["stages"].get(label, {})
            if built.get("status") != "passed":
                continue
            previous = checks.get(minor, {}).get(target, {})
            arch, simulator = targets[target]
            needs_runtime = simulator and arch == platform.machine()
            if (previous.get("finished") and not previous.get("error") and previous.get("xcodebuild_exit") == 0
                    and previous.get("wheel_sha256") == built["wheel_sha256"]
                    and (not needs_runtime or previous.get("runtime_tested"))):
                pending.remove((minor, target))
                continue
            result = {"started": datetime.now(timezone.utc).isoformat(), "wheel_sha256": built["wheel_sha256"],
                      "runtime_tested": False, "visual_rendering_verified": False, "module_features_exercised": False}
            checks.setdefault(minor, {})[target] = result
            save()
            print("Checking", label, flush=True)
            try:
                folder = root / "smoke" / minor / target
                folder.mkdir(parents=True, exist_ok=True)
                for name in ["main.py", "MatrixDependencies.qml"]:
                    shutil.copy2(guide / "scripts/examples/matrix-smoke" / name, folder / name)
                name = "PySidePython" + minor.replace(".", "")
                bundle = "org.echteralsfake.PySidePythonMatrix"
                wheels = root / "wheels" / minor / target
                framework = root / "python" / minor / "Python.xcframework"
                command(label + "-app-generate", [args.deploy_venv / "bin/pyside6-ios-deploy", "main.py",
                    "--name", name, "--bundle-id", bundle, "--wheel-pyside", next(wheels.glob("pyside6-*.whl")),
                    "--wheel-shiboken", next(wheels.glob("shiboken6-*.whl")), "--xcframework-path", framework], cwd=folder)
                result["generation_exit"] = 0
                generated = folder / "deployment" / target
                plist = generated / "Info.plist"
                info = plistlib.loads(plist.read_bytes())
                scene = info.setdefault("UIApplicationSceneManifest", {})
                scene.setdefault("UIApplicationSupportsMultipleScenes", False)
                configs = scene.setdefault("UISceneConfigurations", {}).setdefault("UIWindowSceneSessionRoleApplication", [{"UISceneConfigurationName": "Default Configuration"}])
                for config in configs:
                    config.setdefault("UISceneDelegateClassName", "QIOSWindowSceneDelegate")
                info["UIFileSharingEnabled"] = True
                info["LSSupportsOpeningDocumentsInPlace"] = True
                plist.write_bytes(plistlib.dumps(info))
                arch, simulator = targets[target]
                derived = root / "smoke/derived" / label
                command(label + "-app-xcodebuild", ["xcodebuild", "-project", generated / (name + ".xcodeproj"),
                    "-scheme", name, "-configuration", "Release", "-sdk", "iphonesimulator" if simulator else "iphoneos",
                    "-destination", "generic/platform=iOS Simulator" if simulator else "generic/platform=iOS",
                    "-derivedDataPath", derived, "-jobs", "2", "ARCHS=" + arch, "ONLY_ACTIVE_ARCH=YES",
                    "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO", "CODE_SIGN_IDENTITY=-",
                    "EXPANDED_CODE_SIGN_IDENTITY=-", "EXPANDED_CODE_SIGN_IDENTITY_NAME=ad-hoc", "build"])
                result["xcodebuild_exit"] = 0
                products = derived / "Build/Products" / ("Release-iphonesimulator" if simulator else "Release-iphoneos")
                app = products / (name + ".app")
                if not simulator:
                    ipa = root / "ipas" / ("PySideMatrix-Python" + minor.replace(".", "") + "-ios15.ipa")
                    command(label + "-app-ipa", ["/usr/local/bin/python3", guide / "scripts/package-ipa.py", "--app", app,
                        "--output", ipa, "--bundle-id", "org.echteralsfake.PySideMatrixSmoke.Sideload",
                        "--display-name", "PySide Python " + minor, "--share-documents"])
                    packaging = json.loads(ipa.with_suffix(".json").read_text())
                    result.update(ipa=str(ipa), ipa_sha256=packaging["sha256"])
                    shutil.rmtree(ipa.parent / (ipa.stem + "-staging"))
                elif arch == platform.machine():
                    for sign in [*sorted((app / "Frameworks").glob("*.framework")), app]:
                        command(label + "-app-sign", ["codesign", "--force", "--sign", "-", "--timestamp=none", sign])
                    booted = command(label + "-simulator", ["xcrun", "simctl", "list", "devices", "booted", "--json"], capture=True)
                    if args.simulator not in booted:
                        command(label + "-simulator", ["xcrun", "simctl", "boot", args.simulator])
                    command(label + "-simulator", ["xcrun", "simctl", "bootstatus", args.simulator, "-b"])
                    command(label + "-simulator", ["xcrun", "simctl", "install", args.simulator, app])
                    container = Path(command(label + "-simulator", ["xcrun", "simctl", "get_app_container", args.simulator, bundle, "data"], capture=True).strip())
                    runtime = container / "Documents/matrix-smoke.json"
                    runtime.unlink(missing_ok=True)
                    child_env = env.copy()
                    child_env.update(SIMCTL_CHILD_QT_WIDGETS_RHI="1", SIMCTL_CHILD_QT_WIDGETS_RHI_BACKEND="opengl",
                        SIMCTL_CHILD_QSG_RHI_BACKEND="opengl", SIMCTL_CHILD_QSG_RENDER_LOOP="basic")
                    command(label + "-simulator", ["xcrun", "simctl", "launch", "--terminate-running-process", args.simulator, bundle], launch_env=child_env)
                    for _ in range(180):
                        if runtime.exists():
                            break
                        time.sleep(1)
                    else:
                        if (container / "Documents/matrix-smoke.log").exists():
                            shutil.copy2(container / "Documents/matrix-smoke.log", root / "logs" / (label + "-app-runtime.log"))
                        raise RuntimeError("No application import report; inspect the simulator app's Documents log")
                    data = json.loads(runtime.read_text())
                    assert data["all_imports_succeeded"] and data["binding_count"] == 52 and data["window_visible"]
                    assert data["python"].startswith(minor + ".") and data["cpu"] == arch
                    shutil.copy2(runtime, root / "reports" / (label + "-app-runtime.json"))
                    shutil.copy2(container / "Documents/matrix-smoke.log", root / "logs" / (label + "-app-runtime.log"))
                    result.update(runtime_tested=True, runtime_python=data["python"], runtime_os=data["os_version"], runtime_binding_count=52)
                    command(label + "-simulator", ["xcrun", "simctl", "terminate", args.simulator, bundle])
                result["finished"] = datetime.now(timezone.utc).isoformat()
                save()
                pending.remove((minor, target))
                progress = True
                shutil.rmtree(derived)
                shutil.rmtree(generated / "_wheels")
            except BaseException as error:
                result["error"] = repr(error)
                save()
                traceback.print_exc()
                raise
        if not progress:
            time.sleep(15)
    print("All 15 app links and native-simulator imports completed.", flush=True)


if __name__ == "__main__":
    main()
