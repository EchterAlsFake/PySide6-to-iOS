#!/bin/bash
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: bash scripts/build-qt-host.sh'
    echo 'Builds pinned Qt 6.12 host tools. Overrides: WORK_ROOT, QT_SOURCE_ROOT, QT_HOST_PREFIX, JOBS, PYTHON_HOST_BIN.'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
require_macos
for module in qtbase qtshadertools qtdeclarative; do
    ensure_source "$module" "https://code.qt.io/qt/$module.git"
done
cmake -S "$QT_SOURCE_ROOT/qtbase" -B "$WORK_ROOT/build/qt-host-base" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$QT_HOST_PREFIX" \
    -DCMAKE_OSX_ARCHITECTURES="$(uname -m)" -DCMAKE_OSX_SYSROOT=macosx \
    -DQT_BUILD_TESTS=OFF -DQT_BUILD_EXAMPLES=OFF -DFEATURE_widgets=OFF \
    -DFEATURE_printsupport=OFF -DFEATURE_sql=OFF -DFEATURE_testlib=OFF -DFEATURE_dbus=OFF
cmake --build "$WORK_ROOT/build/qt-host-base" --parallel "$JOBS"
cmake --install "$WORK_ROOT/build/qt-host-base"
for module in qtshadertools qtdeclarative; do
    extra=(-DQT_BUILD_TESTS=OFF)
    if [ "$module" = qtdeclarative ]; then extra+=(-DFEATURE_qml_animation=OFF); fi
    cmake -S "$QT_SOURCE_ROOT/$module" -B "$WORK_ROOT/build/qt-host-$module" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$QT_HOST_PREFIX" \
        -DCMAKE_PREFIX_PATH="$QT_HOST_PREFIX" -DCMAKE_OSX_SYSROOT=macosx \
        -DCMAKE_OSX_ARCHITECTURES="$(uname -m)" -DQT_BUILD_TESTS=OFF -DQT_BUILD_EXAMPLES=OFF "${extra[@]}"
    cmake --build "$WORK_ROOT/build/qt-host-$module" --parallel "$JOBS"
    cmake --install "$WORK_ROOT/build/qt-host-$module"
done
