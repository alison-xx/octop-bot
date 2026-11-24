#!/usr/bin/env bash
# Copy the shared Bot character data, the Chief mascot and the device tool list into both native apps.
# Run after changing dashboard/src/vendor/ds-bot/characters.json, the mascot art or device_tools.json.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
src_chars="$root/dashboard/src/vendor/ds-bot/characters.json"
src_mascot="$root/dashboard/src/assets/avatars/octop-mascot.webp"
ios="$root/mobile/ios/OctopBot/Resources"
android="$root/mobile/android/app/src/main"
mkdir -p "$ios" "$android/assets" "$android/res/drawable-nodpi"
cp "$src_chars" "$ios/characters.json"
cp "$src_chars" "$android/assets/characters.json"
# Soft characters (dashboard/src/pages/OctopBot/softShapes.ts), when this checkout has them.
src_soft="$root/dashboard/src/pages/OctopBot/softShapes.ts"
if [[ -f "$src_soft" ]]; then
  python3 "$root/mobile/scripts/soft-characters.py" "$src_soft" "$ios/soft-characters.json"
  cp "$ios/soft-characters.json" "$android/assets/soft-characters.json"
fi
# Device connector tools (mobile/PROTOCOL.md §C), shared with the server.
src_device="$root/src/octop/infra/agents/device_tools.json"
cp "$src_device" "$ios/device_tools.json"
cp "$src_device" "$android/assets/device_tools.json"
cp "$src_mascot" "$ios/octop-mascot.webp"
cp "$src_mascot" "$android/res/drawable-nodpi/octop_mascot.webp"
if [[ "${1:-}" == "--check" ]]; then
  git -C "$root" diff --quiet -- mobile/ios/OctopBot/Resources mobile/android/app/src/main/assets mobile/android/app/src/main/res/drawable-nodpi \
    || { echo "mobile assets are stale; run mobile/scripts/sync-assets.sh" >&2; exit 1; }
fi
echo "synced characters.json, octop-mascot and device_tools.json into mobile/ios and mobile/android"
