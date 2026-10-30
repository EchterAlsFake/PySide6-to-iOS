#!/bin/bash
# Add as a build phase after the generated Python copy phases, before final signing.
set -euo pipefail
: "${VENDOR_DIR:?Set VENDOR_DIR to your iOS-target package tree}"
: "${PYTHON_XCFRAMEWORK:?Set PYTHON_XCFRAMEWORK}"
: "${CODESIGNING_FOLDER_PATH:?Run as an Xcode build phase}"
: "${PROJECT_DIR:?Run as an Xcode build phase}"
rsync -a --exclude='__pycache__/' "$VENDOR_DIR/" "$CODESIGNING_FOLDER_PATH/packages/"
relative=$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1],sys.argv[2]))' "$PYTHON_XCFRAMEWORK" "$PROJECT_DIR")
source "$PYTHON_XCFRAMEWORK/build/utils.sh"
export EXPANDED_CODE_SIGN_IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:--}"
export EXPANDED_CODE_SIGN_IDENTITY_NAME="${EXPANDED_CODE_SIGN_IDENTITY_NAME:-ad-hoc}"
process_dylibs "$relative" packages
