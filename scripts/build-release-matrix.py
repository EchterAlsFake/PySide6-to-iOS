"""Build the complete Qt-for-Python iOS 15 release matrix in an isolated run root.

Fresh source archives/checkout are prepared before running this driver. A failed
stage may be resumed inside the same fresh run; previous lab builds are never
used as target artifacts. Installed prefixes survive per-module object cleanup.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
HOST_MODULES = ["qtshadertools", "qtsvg", "qtlanguageserver", "qtdeclarative", "qttools",
                "qtquicktimeline", "qtquick3d", "qtscxml", "qtremoteobjects", "qtcanvaspainter", "qtlottie", "qtwebengine-gn"]
TARGET_MODULES = ["qtshadertools", "qtsvg", "qtimageformats", "qtlanguageserver", "qtdeclarative",
                  "qttools", "qt5compat", "qtquicktimeline", "qtquick3d", "qtquick3dphysics",
                  "qtcanvaspainter", "qtlottie", "qtconnectivity", "qtpositioning", "qtlocation",
                  "qtsensors", "qtwebsockets", "qtwebchannel",
                  "qtwebview", "qtnetworkauth", "qthttpserver", "qtremoteobjects", "qtscxml",
                  "qtmultimedia", "qtspeech", "qtcharts", "qtdatavis3d", "qtgraphs", "qt3d",
                  "qtvirtualkeyboard", "qttranslations", "qtwebengine-pdf"]
TARGETS = {"ios_arm64": ("arm64", "iphoneos", "ios_device", "ios-arm64"),
           "ios_arm64_simulator": ("arm64", "iphonesimulator", "ios_simulator_arm64", "ios-arm64_x86_64-simulator"),
           "ios_x86_64_simulator": ("x86_64", "iphonesimulator", "ios_simulator_x86_64", "ios-arm64_x86_64-simulator")}
EXCLUSIONS = {
    "QtSerialPort": "Upstream qtserialport/CMakeLists.txt explicitly returns for UIKIT.",
    "QtSerialBus": "Upstream qtserialbus/CMakeLists.txt explicitly returns for UIKIT.",
    "QtDBus": "D-Bus is not an iOS system service; disabled in this Apple-native kit.",
    "QtWebEngineCore/Quick/Widgets": "Qt WebEngine browser is unsupported on iOS; QtPdf is built separately.",
    "QtAxContainer": "Windows-only ActiveX bindings.",
    "QtDesigner": "Upstream Designer library requires QT_FEATURE_process, unavailable on iOS; QtUiTools is included.",
}
EXPECTED_BINDINGS = set("""Core Gui Widgets PrintSupport Sql Network Test Concurrent
    Xml Help Multimedia MultimediaWidgets OpenGL OpenGLWidgets Pdf PdfWidgets
    Positioning Location NetworkAuth Nfc Qml Quick Quick3D QuickControls2
    CanvasPainter QuickTest QuickWidgets LabsStyleKit RemoteObjects Scxml Sensors
    StateMachine TextToSpeech Charts SpatialAudio Svg SvgWidgets DataVisualization
    Graphs GraphsWidgets Bluetooth UiTools WebChannel WebSockets HttpServer WebView
    3DCore 3DRender 3DInput 3DLogic 3DAnimation 3DExtras""".split())
EXPECTED_QML = {"QtQuick", "QtQuick.Controls", "QtQuick3D", "QtQuick3D.Physics",
                "QtQuick.Timeline", "QtQuick.VectorImage", "Qt.labs.lottieqt",
                "Qt5Compat.GraphicalEffects", "QtQuick.VirtualKeyboard", "QtCanvas2D"}


def binding_inventory(directory, prefix, target):
    wheel = next(directory.glob("pyside6-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        config = ast.parse(archive.read("PySide6/_config.py").decode())
        assignment = next(n for n in config.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "built_modules" for t in n.targets))
        # _config.py uses list(name for name in "Core;Gui;...".split(";")).
        names = [n.value for n in ast.walk(assignment.value)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and ";" in n.value and n.value != ";"]
        if len(names) != 1:
            raise ValueError("Cannot identify the binding module list in _config.py")
        declared = set(names[0].split(";"))
        present = {n.removeprefix("PySide6/libQt").removesuffix(".a") for n in archive.namelist()
                   if n.startswith("PySide6/libQt") and n.endswith(".a") and n.count("/") == 1}
        # Upstream explicitly separates CPython_MODULES from Qt binding modules.
        python_helpers = {"QmlFeatures"}
        if not python_helpers <= present or "PySide6/QtAsyncio/__init__.py" not in archive.namelist():
            raise ValueError(f"{target}: required PySide-only helper module missing")
        support_archives = ["libpyside6.a", "libpyside6qml.a", "libpyside6remoteobjects.a", "libuiplugin.a"]
        for support in support_archives:
            if "PySide6/" + support not in archive.namelist():
                raise ValueError(f"{target}: required static support archive missing: {support}")
        bindings = present - python_helpers
        if declared != bindings:
            raise ValueError(f"{target}: metadata/archive mismatch: declared-only={declared-bindings}; archive-only={bindings-declared}")
        if missing := EXPECTED_BINDINGS - bindings:
            raise ValueError(f"{target}: missing requested supported bindings: {sorted(missing)}")
        qml = set()
        for name in archive.namelist():
            if name.startswith("PySide6/Qt/qml/") and name.endswith("/qmldir"):
                for line in archive.read(name).decode("utf-8").splitlines():
                    if line.startswith("module "):
                        qml.add(line.split()[1])
        if missing := EXPECTED_QML - qml:
            raise ValueError(f"{target}: missing requested QML modules: {sorted(missing)}")
        translations = [n for n in archive.namelist() if n.startswith("PySide6/Qt/translations/") and n.endswith(".qm")]
        if not translations:
            raise ValueError(f"{target}: Qt translation catalogs missing")
        return {"target": target, "wheel": wheel.name, "binding_count": len(bindings),
                "bindings": sorted(bindings), "platform_exclusions": EXCLUSIONS,
                "python_helper_modules": ["QtQmlFeatures"], "pure_python_modules": ["QtAsyncio"],
                "static_support_archives": support_archives,
                "qml_module_count": len(qml), "qml_modules": sorted(qml),
                "translation_catalog_count": len(translations),
                "static_plugins": sorted(n.removeprefix("PySide6/Qt/") for n in archive.namelist()
                                         if n.startswith("PySide6/Qt/plugins/") and n.endswith(".a")),
                "qt_cmake_packages": sorted(p.name for p in (prefix / "lib/cmake").glob("Qt6*")),
                "runtime_execution_tested": False}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--python-xcframework", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--binding-jobs", type=int, default=6,
                        help="Limit memory-heavy generated binding compilation separately.")
    parser.add_argument("--targets", nargs="+", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--keep-build-trees", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise SystemExit("Run as the normal macOS login user, not root.")
    root = args.work_root.resolve()
    lock = (root / ".matrix-driver.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another matrix driver is already using this work root.")
    qt = root / "qt-everywhere-src-6.12.0"
    pdf = root / "qtwebengine-everywhere-src-6.140.0"
    pyside = root / "pyside-setup"
    host = root / "qt/6.12.0/macos"
    python = root / "venvs/build/bin/python"
    framework = args.python_xcframework.resolve()
    assert (qt / "qtbase/.tag").read_text().strip() == "025bdad181de241e81bf853c8a2d7bf3d19261a9"
    assert subprocess.check_output(["git", "-C", str(pyside), "rev-parse", "HEAD"], text=True).strip() == "f50facb83fc3dc5f3240c854668c7a6dd93871b2"
    assert python.is_file() and (pdf / "CMakeLists.txt").is_file()
    logdir = root / "logs"
    logdir.mkdir(exist_ok=True)
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    versions = json.loads((HERE / "versions.json").read_text())
    components = {p.parent.name: p.read_text().strip() for p in sorted(qt.glob("qt*/.tag"))}
    (reports / "source-components.json").write_text(json.dumps({
        "qt_6_12_source_components": components,
        "pyside_commit": versions["source_revisions"]["pyside-setup"],
        "qt_pdf_source_revision": (pdf / ".tag").read_text().strip()}, indent=2) + "\n")
    provenance = {"qt_version": "6.12.0", "python_release": "3.15.0rc2", "minimum_ios": "15.0",
                  "fresh_work_root": str(root), "prior_lab_target_outputs_reused": False,
                  "sources": versions["full_matrix_sources"],
                  "host_generator": {"url": versions["host_generator_url"], "sha256": versions["host_generator_sha256"]},
                  "python_runtime": {"url": versions["python_xcframework_url"], "sha256": versions["python_xcframework_sha256"]},
                  "pyside_commit": versions["source_revisions"]["pyside-setup"],
                  "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
                  "target_qt_parallel_jobs": args.jobs, "binding_parallel_jobs": args.binding_jobs,
                  "module_scope": "all available iOS Qt-for-Python modules and QML dependencies",
                  "multimedia_backend": "native AVFoundation/CoreAudio; prebuilt FFmpeg disabled"}
    (root / "run-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    state_path = root / "matrix-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "started": now(), "qt": "6.12.0", "qt_pdf_source": "6.140.0", "python": "3.15.0rc2",
        "minimum_ios": "15.0", "targets": args.targets, "stages": {}, "runtime_tested": False,
        "scope": "all available iOS Qt-for-Python modules and their QML dependencies"}
    state["platform_exclusions"] = EXCLUSIONS
    env = os.environ.copy()
    env["PATH"] = str(python.parent) + ":/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env["PYTHON3_PATH"] = str(python.parent.parent)
    env["NINJAFLAGS"] = f"-j{args.jobs}"
    env["QTWEBENGINE_GN_THREADS"] = str(args.jobs)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)

    def save():
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(state_path)

    def run(label, command, cwd=None):
        print(f"[{now()}] {label}: {' '.join(map(str, command))}", flush=True)
        log = logdir / f"{label}.log"
        with log.open("a") as stream:
            stream.write(f"\n[{now()}] COMMAND {json.dumps(list(map(str, command)))}\n")
            stream.flush()
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            state["active_stage"] = label
            state["last_failure"] = {"time": now(), "label": label, "returncode": result.returncode}
            save()
            print(log.read_text()[-12000:], flush=True)
            raise SystemExit(f"Stage {label} failed. Log: {log}")

    def stage(label, action):
        if state["stages"].get(label, {}).get("status") == "passed":
            print(f"[{now()}] Previously completed in this run: {label}", flush=True)
            return
        state["active_stage"] = label
        state["stages"][label] = {"status": "running", "started": now()}
        save()
        action()
        state["stages"][label].update(status="passed", finished=now())
        state.pop("last_failure", None)
        save()

    base_options = ["-DCMAKE_BUILD_TYPE=Release", "-DQT_BUILD_TESTS=OFF", "-DQT_BUILD_EXAMPLES=OFF",
                    "-DQT_BUILD_DOCS=OFF", "-DBUILD_WITH_PCH=OFF", "-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON"]

    def qt_module(module, prefix, build, target=None, host_base=False):
        source = pdf if module in {"qtwebengine-pdf", "qtwebengine-gn"} else qt / module
        command = ["cmake", "-S", source, "-B", build, "-G", "Ninja", *base_options,
                   f"-DCMAKE_INSTALL_PREFIX={prefix}", f"-DCMAKE_PREFIX_PATH={prefix}"]
        if target is None:
            command += ["-DCMAKE_OSX_ARCHITECTURES=x86_64", "-DCMAKE_OSX_SYSROOT=macosx",
                        "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0"]
            # Precompile the host Base headers; later module builds limit disk use by omitting PCH.
            if host_base:
                command = [x for x in command if not str(x).startswith(("-DBUILD_WITH_PCH=", "-DCMAKE_DISABLE_PRECOMPILE_HEADERS="))]
                command += ["-DBUILD_WITH_PCH=ON", "-DCMAKE_DISABLE_PRECOMPILE_HEADERS=OFF", "-DFEATURE_dbus=OFF"]
        else:
            arch, sdk, name, python_slice = TARGETS[target]
            command += [f"-DQT_HOST_PATH={host}", f"-DCMAKE_OSX_ARCHITECTURES={arch}",
                        f"-DCMAKE_OSX_SYSROOT={sdk}", f"-DQT_APPLE_SDK={sdk}",
                        "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0",
                        "-DBUILD_SHARED_LIBS=OFF"]
            if module == "qtbase":
                command += ["-DCMAKE_SYSTEM_NAME=iOS", f"-DCMAKE_SYSTEM_PROCESSOR={arch}",
                            "-DFEATURE_dbus=OFF", "-DFEATURE_openssl=OFF"]
            else:
                command += [f"-DCMAKE_TOOLCHAIN_FILE={prefix}/lib/cmake/Qt6/qt.toolchain.cmake"]
            for language in ["C", "CXX", "OBJC", "OBJCXX"]:
                command += [f"-DCMAKE_{language}_FLAGS=-Werror=unguarded-availability -Werror=unguarded-availability-new"]
        if module == "qttools":
            command += ["-DFEATURE_clang=OFF", "-DFEATURE_qdoc=OFF"]
        if module == "qtmultimedia":
            # Avoid linking newer prebuilt FFmpeg or host-only codec dependencies into iOS 15.
            command += ["-DFEATURE_ffmpeg=OFF", "-DFEATURE_avfoundation=ON"]
        if module == "qtwebengine-pdf":
            command += ["-DFEATURE_qtwebengine_build=OFF", "-DFEATURE_qtpdf_build=ON",
                        "-DFEATURE_webengine_build_gn=OFF", "-DQT_SHOW_EXTRA_IDE_SOURCES=OFF",
                        "-DFEATURE_pdf_bitcode=OFF",
                        "-DQT_FEATURE_webengine_pass_extra_cmake_flags=ON",
                        f"-DPython3_EXECUTABLE={python}"]
        if module == "qtwebengine-gn":
            command += ["-DBUILD_ONLY_GN=ON", f"-DPython3_EXECUTABLE={python}"]
        label = (target or "host") + "-" + module
        run(label, command)
        if module == "qtwebengine-pdf":
            run(label, ["cmake", "--build", build, "--target", "run_pdf_GnDone", "--parallel", str(args.jobs)])
            arch, sdk, _, _ = TARGETS[target]
            gn_build = build / "src/pdf/Release" / arch
            ninja = shutil.which("ninja", path=env["PATH"])
            commands = subprocess.check_output([ninja, "-C", str(gn_build), "-t", "commands", "QtPdf"], text=True, env=env)
            checked = 0
            example = None
            for line in commands.splitlines():
                argv = shlex.split(line)
                if "-c" not in argv or "-target" not in argv:
                    continue
                source_file = argv[argv.index("-c") + 1]
                if Path(source_file).suffix not in {".c", ".cc", ".cpp", ".cxx", ".m", ".mm", ".C"}:
                    continue
                triple = argv[argv.index("-target") + 1]
                if "-apple-ios" not in triple:
                    continue
                expected = f"{arch}-apple-ios15.0"
                if not triple.startswith(expected) or triple.endswith("-simulator") != (sdk == "iphonesimulator"):
                    raise SystemExit(f"Unexpected PDFium compiler target: {triple}")
                for warning in ["unguarded-availability", "unguarded-availability-new"]:
                    if f"-Werror={warning}" not in argv or f"-Wno-error={warning}" in argv or f"-Wno-{warning}" in argv:
                        raise SystemExit(f"PDFium availability check missing: {source_file}: {warning}")
                checked += 1
                example = example or line
            if not checked:
                raise SystemExit("No iOS PDFium C/C++/Objective-C compiler commands were audited")
            (reports / f"{target}-pdfium-compiler-audit.json").write_text(json.dumps({
                "target": target, "ios_deployment_target": "15.0", "target_compile_commands_checked": checked,
                "availability_errors_enforced": True, "example_command": example}, indent=2) + "\n")
        run(label, ["cmake", "--build", build, "--parallel", str(args.jobs)])
        run(label, ["cmake", "--install", build])
        for filename in ["CMakeCache.txt", "config.summary", "config.opt"]:
            path = build / filename
            if path.exists():
                shutil.copy2(path, reports / f"{label}-{filename}")
        if not args.keep_build_trees:
            # Only this run's object trees; installed kits, sources and logs are retained.
            assert root / "build" in build.parents
            shutil.rmtree(build)

    stage("host-qtbase", lambda: qt_module("qtbase", host, root / "build/host-qtbase", host_base=True))
    for module in HOST_MODULES:
        stage("host-" + module, lambda module=module: qt_module(module, host, root / "build" / ("host-" + module)))

    def verify_host_tools():
        required = ["moc", "rcc", "qsb", "qmlcachegen", "qmltyperegistrar", "qmlimportscanner",
                    "svgtoqml", "lottietoqml", "qcshadergen", "balsam", "qscxmlc", "repc", "lrelease", "gn"]
        tools = {}
        for tool in required:
            matches = [host / directory / tool for directory in ["bin", "libexec"]
                       if (host / directory / tool).is_file()]
            if len(matches) != 1:
                raise SystemExit(f"Expected one fresh host tool {tool}, found {matches}")
            path = matches[0]
            tools[tool] = {"path": str(path.relative_to(host)),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (reports / "host-tools.json").write_text(json.dumps(tools, indent=2) + "\n")
        for tool in ["moc", "rcc", "qsb", "qmlcachegen", "qmltyperegistrar", "lrelease", "gn"]:
            run("host-tool-" + tool, [host / tools[tool]["path"], "-version" if tool == "lrelease" else "--version"])
    stage("host-tools-inventory", verify_host_tools)

    patch = HERE / "patches/qtbase-ios15.patch"
    def apply_patch():
        if hashlib.sha256(patch.read_bytes()).hexdigest() != versions["qtbase_ios15_patch_sha256"]:
            raise SystemExit("Unexpected QtBase iOS 15 patch checksum")
        already_applied = subprocess.run(["patch", "-p1", "--dry-run", "--reverse", "--force", "--silent", "-i", str(patch)],
                                         cwd=qt / "qtbase", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if already_applied.returncode == 0:
            return
        with patch.open("rb") as stream:
            result = subprocess.run(["patch", "-p1", "--forward", "--force"], cwd=qt / "qtbase", stdin=stream,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (logdir / "ios15-patch.log").write_bytes(result.stdout)
        if result.returncode:
            raise SystemExit("iOS15 QtBase patch failed; see ios15-patch.log")
    stage("apply-ios15-patch", apply_patch)

    def apply_module_patch(module, info):
        source = pyside if module == "pyside-setup" else (pdf if module == "qtwebengine-pdf" else qt / module)
        patch = HERE / "patches" / info["file"]
        if hashlib.sha256(patch.read_bytes()).hexdigest() != info["sha256"]:
            raise SystemExit(f"Unexpected patch checksum: {patch}")
        revision = (subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
                    if module == "pyside-setup" else (source / ".tag").read_text().strip())
        if revision != info["source_revision"]:
            raise SystemExit(f"Unexpected source revision for {module}")
        check = subprocess.run(["patch", "-p1", "--dry-run", "--reverse", "--force", "--silent", "-i", str(patch)],
                               cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if check.returncode == 0:
            return
        run("patch-" + module, ["patch", "-p1", "--forward", "--force", "-i", patch], cwd=source)

    for module, info in versions.get("ios15_module_patches", {}).items():
        stage("apply-ios15-" + module + "-patch-" + info["sha256"][:12],
              lambda module=module, info=info: apply_module_patch(module, info))
    for info in versions.get("pyside_patches", []):
        stage("apply-pyside-patch-" + info["sha256"][:12],
              lambda info=info: apply_module_patch("pyside-setup", info))

    generator = subprocess.check_output([str(python), "-c", "import importlib.util,pathlib; print(pathlib.Path(importlib.util.find_spec('shiboken6_generator').origin).parent)"], text=True).strip()
    for target in args.targets:
        arch, sdk, name, python_slice = TARGETS[target]
        stage(target + "-python-runtime", lambda target=target: run(target + "-python-runtime",
              [python, HERE / "inspect-ios.py", "runtime", framework, "--target", target, "--max-ios", "15.0"]))
        prefix = root / "qt/6.12.0" / name
        stage(target + "-qtbase", lambda: qt_module("qtbase", prefix, root / "build" / (target + "-qtbase"), target))
        for module in TARGET_MODULES:
            stage(target + "-" + module, lambda module=module: qt_module(module, prefix, root / "build" / (target + "-" + module), target))

        def build_bindings():
            toolchain = root / f"toolchain-{target}.cmake"
            q = lambda x: json.dumps(str(x))
            values = {"CMAKE_SYSTEM_PROCESSOR": arch, "CMAKE_OSX_ARCHITECTURES": arch,
                      "CMAKE_OSX_SYSROOT": sdk, "CMAKE_OSX_DEPLOYMENT_TARGET": "15.0",
                      "BUILD_SHARED_LIBS": "OFF", "BUILD_WITH_PCH": "OFF", "CMAKE_DISABLE_PRECOMPILE_HEADERS": "ON",
                      "Python_INCLUDE_DIR": framework / python_slice / "include/python3.15",
                      "Python_LIBRARY": framework / python_slice / "lib/libpython3.15.dylib",
                      "PYTHON_EXECUTABLE": python,
                      "Python_SOABI": "cpython-315-" + ("iphoneos" if sdk == "iphoneos" else "iphonesimulator"),
                      "SHIBOKEN_WRAPPER_HOST_QT_LIB_PATH": generator + "/Qt/lib",
                      "SHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH": generator + "/Qt/lib"}
            toolchain.write_text(f'include({q(prefix / "lib/cmake/Qt6/qt.toolchain.cmake")})\n' +
                "\n".join(f'set({k} {q(v)} CACHE STRING "matrix" FORCE)' for k, v in values.items()) + "\n")
            # New architectures start clean; failed stages can retain their own objects.
            marker = root / "bindings-current-target.txt"
            previous = marker.read_text().strip() if marker.exists() else None
            if previous != target:
                for directory in [pyside / "build", pyside / "dist"]:
                    if directory.exists():
                        shutil.rmtree(directory)
                marker.write_text(target + "\n")
            output = root / "wheels" / target
            output.mkdir(parents=True, exist_ok=True)
            run(target + "-pyside", [python, "setup.py", "bdist_wheel", "--standalone", "--no-qt-tools", "--reuse-build",
                "--disable-pyi", "--skip-mypy-test", "--disable-numpy-support",
                f"--shiboken-host-path={generator}", f"--qt-host-path={host}", f"--qt-target-path={prefix}",
                f"--python-target-path={framework / python_slice}", f"--cmake-toolchain-file={toolchain}",
                f"--plat-name={target}", f"--dist-dir={output}", f"--parallel={args.binding_jobs}"], cwd=pyside)
            run(target + "-audit", [python, HERE / "check-ios-wheels.py", output, "--target", target, "--max-ios", "15.0"])
            inventory = binding_inventory(output, prefix, target)
            (reports / f"{target}-modules.json").write_text(json.dumps(inventory, indent=2) + "\n")
            if not args.keep_build_trees and (pyside / "build").exists():
                shutil.rmtree(pyside / "build")
        stage(target + "-bindings", build_bindings)
    state["finished"] = now()
    state["all_requested_builds_passed"] = True
    state["active_stage"] = None
    save()
    print(f"[{now()}] All requested builds and target audits passed.", flush=True)


if __name__ == "__main__":
    main()
