#!/bin/sh
# Build and sign dist/ScreenContext.app. macOS keeps the Screen Recording permission across
# rebuilds only while the signing identity stays the same: use a Developer ID or the self-signed
# identity from `sh spikes/phase0/macos/signing_spike.sh identity`. "-" (ad hoc) lasts one build.
set -eu
: "${SCREEN_CONTEXT_SIGN_IDENTITY:?Set a code-signing identity, or - for an ad hoc signature (see README)}"
cd packaging
../.venv/bin/python setup_mac.py py2app --dist-dir ../dist --bdist-base ../build
APP=../dist/ScreenContext.app
# --deep does not re-sign the loose Python extension modules in Resources. Under the hardened
# runtime, one left with py2app's ad hoc signature is killed at its first page-in (#7), so sign
# every nested binary first, then seal the bundle.
find "$APP/Contents" -type f \( -name '*.so' -o -name '*.dylib' \) \
    -exec codesign --force --options runtime --timestamp --sign "$SCREEN_CONTEXT_SIGN_IDENTITY" {} +
codesign --force --deep --options runtime --timestamp --sign "$SCREEN_CONTEXT_SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
