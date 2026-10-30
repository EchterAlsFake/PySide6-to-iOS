#!/bin/bash
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: bash scripts/check-ios-runtime.sh /path/Python.xcframework [ios_arm64|ios_arm64_simulator|ios_x86_64_simulator]'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
runtime=${1:-"$PYTHON_XCFRAMEWORK"}
exec "$PYTHON_HOST_BIN" "$GUIDE_ROOT/scripts/inspect-ios.py" runtime "$runtime" --target "${2:-ios_arm64}"
