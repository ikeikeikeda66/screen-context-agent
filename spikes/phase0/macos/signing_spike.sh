#!/bin/sh
# Spike #7: does a fixed self-signed identity keep the Screen Recording grant across rebuilds?
# Run from the repository root. Results go to spike-results/ (ignored by git).
set -eu

NAME="${SCREEN_CONTEXT_SPIKE_IDENTITY:-ScreenContext Local Signing}"
OUT="${SCREEN_CONTEXT_SPIKE_OUT:-spike-results}"
APP="dist/ScreenContext.app"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
MARKER="screen_context/_spike_marker.py"

usage() {
    cat <<EOF
usage: sh spikes/phase0/macos/signing_spike.sh COMMAND

  identity        create the self-signed code-signing identity "$NAME" in the login keychain
  build LABEL     build and sign $APP; a unique marker makes each build's code hash differ
  compare A B     compare the designated requirement and code hash of two builds
  check           print capture health (active = the grant survived, permission_error = it did not)
  dmg LABEL       package the current build as a quarantined DMG for the Gatekeeper test
EOF
    exit 2
}

identity() {
    if security find-certificate -c "$NAME" "$KEYCHAIN" >/dev/null 2>&1; then
        echo "Identity \"$NAME\" already exists."; return
    fi
    tmp=$(mktemp -d); pass=$(/usr/bin/openssl rand -hex 16)
    # /usr/bin/openssl is LibreSSL, whose PKCS#12 defaults are readable by `security import`.
    /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$NAME" \
        -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
        -addext "basicConstraints=critical,CA:false" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=critical,codeSigning"
    /usr/bin/openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -out "$tmp/id.p12" -passout "pass:$pass"
    security import "$tmp/id.p12" -k "$KEYCHAIN" -P "$pass" -T /usr/bin/codesign
    echo "Trusting the certificate for code signing (macOS asks for your password)."
    security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$tmp/cert.pem"
    rm -rf "$tmp"
    security find-identity -v -p codesigning | grep "$NAME"
}

record() {
    mkdir -p "$OUT"
    {
        echo "label: $1"
        echo "built: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        codesign -dvvv "$APP" 2>&1 | grep -E '^(CDHash|Authority|TeamIdentifier|Identifier)='
        echo "designated requirement:"
        codesign -d -r- "$APP" 2>&1 | grep -v '^Executable='
    } >"$OUT/signing-$1.txt"
    cat "$OUT/signing-$1.txt"
}

build() {
    [ $# -eq 1 ] || usage
    echo "SPIKE_BUILD = \"$1 $(date -u +%s)\"" >"$MARKER"
    trap 'rm -f "$MARKER"' EXIT
    SCREEN_CONTEXT_SIGN_IDENTITY="$NAME" sh packaging/build_mac.sh
    record "$1"
}

compare() {
    [ $# -eq 2 ] || usage
    a="$OUT/signing-$1.txt"; b="$OUT/signing-$2.txt"
    req() { sed -n '/^designated requirement:/,$p' "$1"; }
    hash() { grep '^CDHash=' "$1"; }
    echo "### Signing comparison (#7): $1 vs $2"
    if [ "$(req "$a")" = "$(req "$b")" ]; then echo "- Designated requirement: identical"; else echo "- Designated requirement: DIFFERENT"; fi
    if [ "$(hash "$a")" = "$(hash "$b")" ]; then echo "- CDHash: identical (the marker did not change the build)"; else echo "- CDHash: different (expected)"; fi
    echo; echo '```'; req "$b"; echo '```'
}

check() {
    # permission_error means macOS dropped the grant; the indexer may be stopped, which is fine here.
    .venv/bin/screen-context health | .venv/bin/python -c 'import json,sys; h=json.load(sys.stdin); c=h["capture"]; print("state:", h["state"], "| permission:", h["permission"], "| capture:", c["last_status"], c["error_type"] or "")'
}

dmg() {
    [ $# -eq 1 ] || usage
    mkdir -p "$OUT"
    file="$OUT/ScreenContext-$1.dmg"
    rm -f "$file"
    hdiutil create -volname ScreenContext -srcfolder "$APP" -ov -format UDZO "$file"
    # Mark the DMG as downloaded by a browser so Gatekeeper treats it like a real download.
    xattr -w com.apple.quarantine "0081;$(printf %x "$(date +%s)");Safari;" "$file"
    echo "Created $file. Open it, drag the app to /Applications, launch it, and note what Gatekeeper shows."
}

[ $# -ge 1 ] || usage
command=$1; shift
case "$command" in
    identity) identity ;;
    build) build "$@" ;;
    compare) compare "$@" ;;
    check) check ;;
    dmg) dmg "$@" ;;
    *) usage ;;
esac
