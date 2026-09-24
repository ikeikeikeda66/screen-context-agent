#!/bin/sh
set -eu
: "${SCREEN_CONTEXT_SIGN_IDENTITY:?Set Developer ID Application identity before building}"
cd packaging
../.venv/bin/python setup_mac.py py2app --dist-dir ../dist --bdist-base ../build
codesign --force --deep --options runtime --timestamp --sign "$SCREEN_CONTEXT_SIGN_IDENTITY" ../dist/ScreenContext.app
codesign --verify --deep --strict --verbose=2 ../dist/ScreenContext.app
