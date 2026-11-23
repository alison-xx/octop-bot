#!/usr/bin/env bash
# Package Octop Bot for Apple silicon: signed with Developer ID, notarized, stapled.
# Needs the built portable tree (make build-frontend, then desktop/portable/bootstrap-runtime.sh
# and package.sh darwin-arm64), the Developer ID certificate in the login keychain and a
# notarytool keychain profile (NOTARY_PROFILE, default lynxce-notary).
set -euo pipefail
SHELL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$SHELL_DIR/../.." && pwd)"
VERSION="$(sed -nE 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$REPO/pyproject.toml" | head -1)"
TREE="$REPO/desktop/portable/release/Octop-darwin-arm64"
STAGE="$SHELL_DIR/release/octop-bot-mac-stage"
OUT="$REPO/dist/$VERSION"

[[ -x "$TREE/runtime/bin/python3" && -f "$TREE/launch.py" ]] || { echo "Build $TREE first." >&2; exit 1; }
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -a "$TREE" "$STAGE/portable"
rm -f "$STAGE/portable/start.bat"
printf '{"version": "%s"}' "$VERSION" > "$STAGE/portable/version.json"

# Icon: bot-icon.png → .icns
ICONSET="$STAGE/bot-icon.iconset"; mkdir -p "$ICONSET"
cp "$SHELL_DIR/resources/bot-icon.png" "$STAGE/bot-icon.png"
for size in 16 32 128 256 512; do
  sips -z $size $size "$STAGE/bot-icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) "$STAGE/bot-icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$STAGE/bot-icon.icns"

cd "$SHELL_DIR"
./node_modules/.bin/electron-vite build
# electron-builder wants SemVer: 1.0.4b1 → 1.0.4-beta.1
SEMVER="$(echo "$VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+)b([0-9]+)$/\1-beta.\2/; s/^([0-9]+\.[0-9]+\.[0-9]+)a([0-9]+)$/\1-alpha.\2/; s/^([0-9]+\.[0-9]+\.[0-9]+)rc([0-9]+)$/\1-rc.\2/')"
rm -rf release/octop-bot-mac
OCTOP_BOT_STAGING="$STAGE" OCTOP_BOT_PACKAGE_VERSION="$SEMVER" \
  APPLE_KEYCHAIN_PROFILE="${NOTARY_PROFILE:-lynxce-notary}" \
  ./node_modules/.bin/electron-builder --config electron-builder.bot.mac.cjs --mac --arm64 --publish never

DMG="release/octop-bot-mac/Octop-Bot-$SEMVER-mac-arm64.dmg"
xcrun notarytool submit "$DMG" --keychain-profile "${NOTARY_PROFILE:-lynxce-notary}" --wait
xcrun stapler staple "$DMG"
mkdir -p "$OUT"
cp "$DMG" "release/octop-bot-mac/Octop-Bot-$SEMVER-mac-arm64.zip" "$OUT/"
(cd "$OUT" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
echo "Done: $OUT"
