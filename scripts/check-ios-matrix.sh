#!/bin/bash
set -euo pipefail
if [ "${1:-}" = --help ]; then
    echo 'Usage: TARGETS="ios_arm64 ..." bash scripts/check-ios-matrix.sh'
    exit 0
fi
source "$(dirname -- "$0")/common.sh"
for target in ${TARGETS:-ios_arm64}; do
    bash "$GUIDE_ROOT/scripts/check-ios-runtime.sh" "$PYTHON_XCFRAMEWORK" "$target"
    extra=(--target "$target")
    if [ -n "${IOS_DEPLOYMENT_TARGET:-}" ]; then extra+=(--max-ios "$IOS_DEPLOYMENT_TARGET"); fi
    "$PYTHON_HOST_BIN" "$GUIDE_ROOT/scripts/check-ios-wheels.py" "$WORK_ROOT/wheels/$target" "${extra[@]}"
done
