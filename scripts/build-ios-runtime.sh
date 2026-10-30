#!/bin/bash
# Retains the Android guide's helper role; prepares the official runtime, not a new CPython build.
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: bash scripts/build-ios-runtime.sh [--help]'
    echo 'Prepares pinned CPython 3.15.0rc2. Overrides: PYTHON_XCFRAMEWORK, WORK_ROOT, PYTHON_HOST_BIN.'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
require_macos
if [ ! -d "$PYTHON_XCFRAMEWORK" ]; then
    mkdir -p "$WORK_ROOT/downloads" "$(dirname -- "$PYTHON_XCFRAMEWORK")"
    archive="$WORK_ROOT/downloads/python-$PYTHON_RELEASE-iOS-XCframework.tar.gz"
    if [ ! -f "$archive" ]; then
        curl -fL --retry 3 "https://www.python.org/ftp/python/3.15.0/python-$PYTHON_RELEASE-iOS-XCframework.tar.gz" -o "$archive.part"
        mv "$archive.part" "$archive"
    fi
    echo "2496d92689da625cd349e856e17b3d540787f8d17806e21536e8d394d940adc0  $archive" | shasum -a 256 -c -
    "$PYTHON_HOST_BIN" - "$archive" "$(dirname -- "$PYTHON_XCFRAMEWORK")" <<'PY'
import sys,tarfile
with tarfile.open(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2], filter='data')
PY
fi
# CMake FindPython accepts this Unix-shaped view more reliably than a framework filename.
for slice in ios-arm64 ios-arm64_x86_64-simulator; do
    directory="$PYTHON_XCFRAMEWORK/$slice"
    [ -d "$directory" ] || continue
    mkdir -p "$directory/include" "$directory/lib"
    ln -sfn ../Python.framework/Headers "$directory/include/python$PYTHON_ABI"
    ln -sfn ../Python.framework/Python "$directory/lib/libpython$PYTHON_ABI.dylib"
done
bash "$GUIDE_ROOT/scripts/check-ios-runtime.sh" "$PYTHON_XCFRAMEWORK" ios_arm64
echo "Runtime prepared at $PYTHON_XCFRAMEWORK"
