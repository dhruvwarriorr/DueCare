#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
api_url="${API_URL:-https://duecare-xi.vercel.app}"
if [[ "$api_url" != https://* ]]; then
  echo "API_URL must use HTTPS for a release build." >&2
  exit 1
fi
cd "$repo_root/apps/mobile"
if [[ ! -f android/key.properties ]]; then
  echo "Missing android/key.properties. See apps/mobile/README.md." >&2
  exit 1
fi
defines=("--dart-define=API_URL=$api_url")
if [[ -f firebase.json ]]; then
  defines+=(--dart-define-from-file=firebase.json)
fi
flutter pub get
flutter analyze
flutter build apk --release "${defines[@]}"
version="$(sed -n 's/^version: //p' pubspec.yaml | cut -d+ -f1)"
output="$repo_root/dist/android"
mkdir -p "$output"
cp build/app/outputs/flutter-apk/app-release.apk "$output/DueCare-$version.apk"
cd "$output"
shasum -a 256 "DueCare-$version.apk" > SHA256SUMS.txt
echo "Release APK: $output/DueCare-$version.apk"
