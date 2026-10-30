#!/bin/bash
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: bash scripts/build-qt-ios.sh [ios_arm64|ios_arm64_simulator|ios_x86_64_simulator]'
    echo 'Defaults to iOS 18. Set IOS_DEPLOYMENT_TARGET=15.0 EXPERIMENTAL_IOS15=1 for the experimental patch.'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
require_macos
select_target "${1:-ios_arm64}"
minimum=${IOS_DEPLOYMENT_TARGET:-18.0}
if [ -f "$QT_TARGET_PREFIX/.guide-ios-minimum" ]; then
    [ "$(cat "$QT_TARGET_PREFIX/.guide-ios-minimum")" = "$minimum" ] || die 'Target prefix uses another deployment target; choose a separate WORK_ROOT.'
fi
[ -f "$QT_HOST_PREFIX/lib/cmake/Qt6/Qt6Config.cmake" ] || die 'Build the matching host Qt first.'
for module in qtbase qtshadertools qtsvg qtdeclarative qt5compat; do
    ensure_source "$module" "https://code.qt.io/qt/$module.git"
done
if "$PYTHON_HOST_BIN" -c 'import sys; sys.exit(0 if tuple(map(int,sys.argv[1].split("."))) < (18,0) else 1)' "$minimum"; then
    [ "${EXPERIMENTAL_IOS15:-0}" = 1 ] || die 'Below iOS 18 requires EXPERIMENTAL_IOS15=1; see SOURCE_BUILD_6.12.md.'
    patch="$GUIDE_ROOT/scripts/patches/qtbase-ios15.patch"
    echo "1a7a858d30f616d84e0b17c510fe64f88c449c932c0db776ae61ea0e9881ad63  $patch" | shasum -a 256 -c -
    if git -C "$QT_SOURCE_ROOT/qtbase" apply --reverse --check "$patch" 2>/dev/null; then
        echo 'iOS 15 compatibility patch is already applied.'
    else
        git -C "$QT_SOURCE_ROOT/qtbase" apply --check "$patch"
        git -C "$QT_SOURCE_ROOT/qtbase" apply "$patch"
    fi
fi
build="$WORK_ROOT/build/$TARGET-min$minimum"
availability='-Werror=unguarded-availability -Werror=unguarded-availability-new'
cmake -S "$QT_SOURCE_ROOT/qtbase" -B "$build/qtbase" -G Ninja \
    -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_SYSTEM_PROCESSOR="$ARCH" \
    -DCMAKE_OSX_ARCHITECTURES="$ARCH" -DCMAKE_OSX_SYSROOT="$SDK" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET="$minimum" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$QT_TARGET_PREFIX" -DQT_HOST_PATH="$QT_HOST_PREFIX" \
    -DBUILD_SHARED_LIBS=OFF -DQT_BUILD_TESTS=OFF -DQT_BUILD_EXAMPLES=OFF \
    -DFEATURE_sql=OFF -DFEATURE_testlib=OFF -DFEATURE_dbus=OFF \
    -DCMAKE_C_FLAGS="$availability" -DCMAKE_CXX_FLAGS="$availability" \
    -DCMAKE_OBJC_FLAGS="$availability" -DCMAKE_OBJCXX_FLAGS="$availability"
cmake --build "$build/qtbase" --parallel "$JOBS"
cmake --install "$build/qtbase"
for module in qtshadertools qtsvg qtdeclarative qt5compat; do
    cmake -S "$QT_SOURCE_ROOT/$module" -B "$build/$module" -G Ninja \
        -DCMAKE_TOOLCHAIN_FILE="$QT_TARGET_PREFIX/lib/cmake/Qt6/qt.toolchain.cmake" \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$QT_TARGET_PREFIX" \
        -DQT_HOST_PATH="$QT_HOST_PREFIX" -DCMAKE_OSX_ARCHITECTURES="$ARCH" \
        -DCMAKE_OSX_SYSROOT="$SDK" -DCMAKE_OSX_DEPLOYMENT_TARGET="$minimum" \
        -DQT_BUILD_TESTS=OFF -DQT_BUILD_EXAMPLES=OFF \
        -DCMAKE_C_FLAGS="$availability" -DCMAKE_CXX_FLAGS="$availability" \
        -DCMAKE_OBJC_FLAGS="$availability" -DCMAKE_OBJCXX_FLAGS="$availability"
    cmake --build "$build/$module" --parallel "$JOBS"
    cmake --install "$build/$module"
done
printf '%s\n' "$minimum" > "$QT_TARGET_PREFIX/.guide-ios-minimum"
