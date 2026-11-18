#!/bin/bash
# Builds Arnheim's Mac app (docs/mac.md): mac/build/Arnheim.app, a menu bar app that carries this copy of
# Arnheim and runs it, and mac/build/Arnheim.zip to hand out. Needs Xcode or Apple's command line tools
# (swiftc), in a git clone of Arnheim. Ad hoc signed: no Apple developer account is used.
#
#   mac/build.sh
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=mac/build
APP="$OUT/Arnheim.app"
WORK="$OUT/work"
MIN_MACOS=13.0

for tool in swiftc codesign ditto iconutil lipo xcrun git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "mac/build.sh needs $tool, which comes with Xcode or Apple's command line tools (xcode-select --install)." >&2
    exit 1
  fi
done
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "mac/build.sh runs in a git clone of Arnheim: it bundles the files git tracks." >&2
  exit 1
fi

rm -rf "$APP" "$OUT/Arnheim.zip" "$WORK"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/arnheim" "$WORK"
trap 'rm -rf "$WORK"' EXIT
SDK=$(xcrun --sdk macosx --show-sdk-path)

echo "Compiling the app, for Apple silicon and Intel..."
for arch in arm64 x86_64; do
  swiftc -O -swift-version 5 -sdk "$SDK" -target "$arch-apple-macos$MIN_MACOS" \
    -o "$WORK/Arnheim-$arch" mac/Sources/*.swift
done
lipo -create -output "$APP/Contents/MacOS/Arnheim" "$WORK/Arnheim-arm64" "$WORK/Arnheim-x86_64"

echo "Drawing the icon..."
swiftc -O -swift-version 5 -sdk "$SDK" -o "$WORK/make-icon" mac/icon.swift
"$WORK/make-icon" "$WORK/Arnheim.iconset"
iconutil -c icns -o "$APP/Contents/Resources/Arnheim.icns" "$WORK/Arnheim.iconset"

echo "Copying Arnheim's files..."
DEST="$APP/Contents/Resources/arnheim"
# Only what git tracks, and of that only what running Arnheim needs: not the tests, the studio that bakes the
# pictures, this app's own source or the README's pictures. Never data/, baked/ or .voice/, which git ignores.
git ls-files -z | while IFS= read -r -d '' file; do
  case "$file" in
    tests/*|studio/*|mac/*|.claude/*|.gitignore|CLAUDE.md|docs/*.gif|docs/*.jpg|data/*|baked/*|.voice/*) continue ;;
  esac
  [ -f "$file" ] || continue  # tracked, but deleted in this copy
  mkdir -p "$DEST/$(dirname "$file")"
  cp -X "$file" "$DEST/$file"
done

# Which Arnheim this is: the commit, and a fingerprint of the files, which the app compares with the copy in
# ~/Library/Application Support/Arnheim/app to know when to update it.
COMMIT=$(git rev-parse --short=12 HEAD)
if [ -n "$(git status --porcelain --untracked-files=no -- . ':(exclude)mac')" ]; then
  COMMIT="$COMMIT+changes"
fi
VERSION=$(cd "$DEST" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -c1-16)
TOP=$(cd "$DEST" && ls -A | LC_ALL=C sort | sed 's/.*/"&"/' | paste -sd, -)
printf '{"version": "%s", "commit": "%s", "top": [%s]}\n' "$VERSION" "$COMMIT" "$TOP" > "$APP/Contents/Resources/arnheim.json"

cp mac/Info.plist "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $(git rev-list --count HEAD)" "$APP/Contents/Info.plist"
plutil -lint -s "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

echo "Signing it, ad hoc..."
xattr -cr "$APP"
codesign --force --sign - --timestamp=none "$APP"
codesign --verify --strict "$APP"

ditto -c -k --keepParent "$APP" "$OUT/Arnheim.zip"
echo "Built $APP ($(du -sh "$APP" | cut -f1)) and $OUT/Arnheim.zip ($(du -h "$OUT/Arnheim.zip" | cut -f1)), with Arnheim $COMMIT."
