#!/bin/bash
# One Python ABI and one target per build. This is not Android's 5x4 matrix.
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: bash scripts/rebuild-ios-matrix.sh'
    echo 'TARGETS defaults to ios_arm64. See SOURCE_BUILD_6.12.md before requesting simulator targets.'
    echo 'Overrides: WORK_ROOT, TARGETS, IOS_DEPLOYMENT_TARGET, EXPERIMENTAL_IOS15, JOBS, PYTHON_HOST_BIN.'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
require_macos
ensure_source pyside-setup https://code.qt.io/pyside/pyside-setup.git
mkdir -p "$WORK_ROOT/downloads" "$WORK_ROOT/logs"
if [ ! -x "$HOST_VENV/bin/python" ]; then
    "$PYTHON_HOST_BIN" -m venv "$HOST_VENV"
    "$HOST_VENV/bin/python" -m pip install 'PySide6-Essentials==6.12.0' certifi ninja jinja2
    wheel="$WORK_ROOT/downloads/shiboken6_generator-6.12.0-cp310-abi3-macosx_14_0_universal2.whl"
    curl -fL --retry 3 "https://download.qt.io/official_releases/QtForPython/shiboken6_generator/$(basename "$wheel")" -o "$wheel"
    echo "d93fb47e8f071855f9b92edea24c331d88461c5b94c0ef656eb5efe157bf0abf  $wheel" | shasum -a 256 -c -
    "$HOST_VENV/bin/python" -m pip install "$wheel"
fi
if [ ! -x "$BUILD_VENV/bin/python" ]; then
    "$PYTHON_HOST_BIN" -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/python" -m pip install 'setuptools==78.1.0' 'packaging==24.2' 'build==1.2.2.post1' 'wheel==0.46.3' jinja2
fi
export PATH="$BUILD_VENV/bin:$HOST_VENV/bin:$PATH"
bash "$GUIDE_ROOT/scripts/build-ios-runtime.sh"
bash "$GUIDE_ROOT/scripts/build-qt-host.sh"
generator=$("$HOST_VENV/bin/python" -c 'import importlib.util,pathlib; print(pathlib.Path(importlib.util.find_spec("shiboken6_generator").origin).parent)')
for target in ${TARGETS:-ios_arm64}; do
    select_target "$target"
    bash "$GUIDE_ROOT/scripts/build-qt-ios.sh" "$target"
    minimum=${IOS_DEPLOYMENT_TARGET:-18.0}
    toolchain="$WORK_ROOT/build/$target-min$minimum/pyside-toolchain.cmake"
    "$BUILD_VENV/bin/python" - "$toolchain" "$QT_TARGET_PREFIX" "$ARCH" "$SDK" "$minimum" "$PYTHON_XCFRAMEWORK/$PYTHON_SLICE" "$BUILD_VENV/bin/python" "$generator" <<'PY'
from pathlib import Path
import json,sys
out,qt,arch,sdk,minimum,slice,python,generator=sys.argv[1:]
q=lambda value:json.dumps(value)
lines=[f'include({q(qt+"/lib/cmake/Qt6/qt.toolchain.cmake")})']
values={'CMAKE_SYSTEM_PROCESSOR':arch,'CMAKE_OSX_ARCHITECTURES':arch,'CMAKE_OSX_SYSROOT':sdk,
 'CMAKE_OSX_DEPLOYMENT_TARGET':minimum,'BUILD_SHARED_LIBS':'OFF',
 'Python_INCLUDE_DIR':slice+'/include/python3.15','Python_LIBRARY':slice+'/lib/libpython3.15.dylib',
 'PYTHON_EXECUTABLE':python,'Python_SOABI':'cpython-315-'+('iphoneos' if sdk=='iphoneos' else 'iphonesimulator'),
 'SHIBOKEN_WRAPPER_HOST_QT_LIB_PATH':generator+'/Qt/lib',
 'SHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH':generator+'/Qt/lib'}
lines += [f'set({key} {q(value)} CACHE STRING "guide" FORCE)' for key,value in values.items()]
Path(out).write_text('\n'.join(lines)+'\n')
PY
    (cd "$PYSIDE_SOURCE" && "$BUILD_VENV/bin/python" setup.py bdist_wheel \
        --standalone --no-qt-tools --disable-pyi --skip-mypy-test --disable-numpy-support \
        --module-subset="${PYSIDE_MODULES:-Core,Gui,Network,OpenGL,Svg,Qml,Quick,QuickControls2}" \
        --shiboken-host-path="$generator" --qt-host-path="$QT_HOST_PREFIX" --qt-target-path="$QT_TARGET_PREFIX" \
        --python-target-path="$PYTHON_XCFRAMEWORK/$PYTHON_SLICE" --cmake-toolchain-file="$toolchain" \
        --plat-name="$target" --dist-dir="$WORK_ROOT/wheels/$target" --parallel="$JOBS") \
        2>&1 | tee "$WORK_ROOT/logs/pyside-$target.log"
    "$PYTHON_HOST_BIN" "$GUIDE_ROOT/scripts/check-ios-wheels.py" "$WORK_ROOT/wheels/$target" --target "$target" --max-ios "$minimum"
done
