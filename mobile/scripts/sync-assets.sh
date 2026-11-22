#!/usr/bin/env bash
# Copy the shared Bot character data and the Chief mascot into both native apps.
# Run after changing dashboard/src/vendor/ds-bot/characters.json or the mascot art.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
src_chars="$root/dashboard/src/vendor/ds-bot/characters.json"
src_mascot="$root/dashboard/src/assets/avatars/octop-mascot.webp"
ios="$root/mobile/ios/OctopBot/Resources"
android="$root/mobile/android/app/src/main"
mkdir -p "$ios" "$android/assets" "$android/res/drawable-nodpi"
cp "$src_chars" "$ios/characters.json"
cp "$src_chars" "$android/assets/characters.json"
cp "$src_mascot" "$ios/octop-mascot.webp"
cp "$src_mascot" "$android/res/drawable-nodpi/octop_mascot.webp"
if [[ "${1:-}" == "--check" ]]; then
  git -C "$root" diff --quiet -- mobile/ios/OctopBot/Resources mobile/android/app/src/main/assets mobile/android/app/src/main/res/drawable-nodpi \
    || { echo "mobile assets are stale; run mobile/scripts/sync-assets.sh" >&2; exit 1; }
fi
echo "synced characters.json and octop-mascot into mobile/ios and mobile/android"
