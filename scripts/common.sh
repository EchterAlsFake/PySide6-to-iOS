#!/bin/bash
# Shared defaults; scripts never change system-wide xcode-select or run as root.
set -euo pipefail
GUIDE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK_ROOT=${WORK_ROOT:-"$GUIDE_ROOT/work"}
QT_VERSION=6.12.0
PYTHON_RELEASE=3.15.0rc2
PYTHON_ABI=3.15
PYTHON_HOST_BIN=${PYTHON_HOST_BIN:-python3.13}
JOBS=${JOBS:-4}
QT_HOST_PREFIX=${QT_HOST_PREFIX:-"$WORK_ROOT/qt/$QT_VERSION/macos"}
QT_SOURCE_ROOT=${QT_SOURCE_ROOT:-"$WORK_ROOT/sources"}
PYSIDE_SOURCE=${PYSIDE_SOURCE:-"$QT_SOURCE_ROOT/pyside-setup"}
PYTHON_XCFRAMEWORK=${PYTHON_XCFRAMEWORK:-"$WORK_ROOT/python/$PYTHON_RELEASE/Python.xcframework"}
HOST_VENV=${HOST_VENV:-"$WORK_ROOT/venvs/host"}
BUILD_VENV=${BUILD_VENV:-"$WORK_ROOT/venvs/build"}
export WORK_ROOT QT_HOST_PREFIX QT_SOURCE_ROOT PYSIDE_SOURCE PYTHON_XCFRAMEWORK

die() { echo "Error: $*" >&2; exit 1; }
require_macos() {
    [ "$(uname -s)" = Darwin ] || die 'Builds require macOS and full Xcode.'
    [ "$(id -u)" != 0 ] || die 'Run as your normal macOS user, without sudo.'
    if [ -z "${DEVELOPER_DIR:-}" ]; then
        if [ -d /Applications/Xcode.app/Contents/Developer ]; then
            export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
        elif [ -d "$HOME/Downloads/Xcode.app/Contents/Developer" ]; then
            export DEVELOPER_DIR="$HOME/Downloads/Xcode.app/Contents/Developer"
        fi
    fi
    xcrun --sdk iphoneos --show-sdk-path >/dev/null || die 'Set DEVELOPER_DIR to your full Xcode installation.'
}
select_target() {
    TARGET=${1:-ios_arm64}
    case "$TARGET" in
        ios_arm64) ARCH=arm64; SDK=iphoneos; QT_TARGET_NAME=ios_device; PYTHON_SLICE=ios-arm64 ;;
        ios_arm64_simulator) ARCH=arm64; SDK=iphonesimulator; QT_TARGET_NAME=ios_simulator_arm64; PYTHON_SLICE=ios-arm64_x86_64-simulator ;;
        ios_x86_64_simulator) ARCH=x86_64; SDK=iphonesimulator; QT_TARGET_NAME=ios_simulator_x86_64; PYTHON_SLICE=ios-arm64_x86_64-simulator ;;
        *) die 'Target must be ios_arm64, ios_arm64_simulator or ios_x86_64_simulator.' ;;
    esac
    QT_TARGET_PREFIX="$WORK_ROOT/qt/$QT_VERSION/$QT_TARGET_NAME"
    export TARGET ARCH SDK QT_TARGET_PREFIX PYTHON_SLICE
}
ensure_source() {
    local module=$1 url=$2 expected current
    expected=$("$PYTHON_HOST_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_revisions"][sys.argv[2]])' "$GUIDE_ROOT/scripts/versions.json" "$module")
    if [ ! -d "$QT_SOURCE_ROOT/$module" ]; then
        mkdir -p "$QT_SOURCE_ROOT"
        git clone --depth 1 --branch v6.12.0 "$url" "$QT_SOURCE_ROOT/$module"
    fi
    current=$(git -C "$QT_SOURCE_ROOT/$module" rev-parse HEAD)
    [ "$current" = "$expected" ] || die "$module is at $current, expected $expected. Use a separate work root; existing sources were not reset."
}
