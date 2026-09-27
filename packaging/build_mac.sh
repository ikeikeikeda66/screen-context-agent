#!/bin/sh
# Build and sign dist/ScreenContext.app. macOS keeps the Screen Recording permission across
# rebuilds only while the signing identity stays the same: use a Developer ID or the self-signed
# identity from `sh packaging/macos/signing_identity.sh`. "-" (ad hoc) lasts one build.
set -eu
: "${SCREEN_CONTEXT_SIGN_IDENTITY:?Set a code-signing identity, or - for an ad hoc signature (see README)}"
cd packaging
../.venv/bin/python setup_mac.py py2app --dist-dir ../dist --bdist-base ../build
APP=../dist/ScreenContext.app
# --deep does not re-sign the loose Python extension modules in Resources. Under the hardened
# runtime, one left with py2app's ad hoc signature is killed at its first page-in (#7), so sign
# every nested binary first, then seal the bundle.
#
# A self-signed identity has no real Team ID, so the hardened runtime's Library Validation
# refuses to dlopen the embedded Python.framework even when every binary shares that identity
# (dyld: "different Team IDs"). entitlements.plist disables Library Validation for this reason;
# a real Developer ID build should not need it.
find "$APP/Contents" -type f \( -name '*.so' -o -name '*.dylib' \) \
    -exec codesign --force --options runtime --entitlements entitlements.plist --timestamp --sign "$SCREEN_CONTEXT_SIGN_IDENTITY" {} +
codesign --force --deep --options runtime --entitlements entitlements.plist --timestamp --sign "$SCREEN_CONTEXT_SIGN_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
