#!/bin/sh
# Create a self-signed code-signing identity in the login keychain, once per Mac.
# Signing every build with the same identity keeps the Screen Recording permission
# across rebuilds (#7). It does not make the app open on other Macs: that needs
# Apple notarization. Run from the repository root: sh packaging/macos/signing_identity.sh
set -eu

NAME="${1:-ScreenContext Local Signing}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-certificate -c "$NAME" "$KEYCHAIN" >/dev/null 2>&1; then
    echo "Identity \"$NAME\" already exists."; exit 0
fi
tmp=$(mktemp -d); pass=$(/usr/bin/openssl rand -hex 16)
trap 'rm -rf "$tmp"' EXIT
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
security find-identity -v -p codesigning | grep "$NAME"
