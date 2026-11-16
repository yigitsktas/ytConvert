#!/bin/bash
# ytConvert.app'i derler ve /Applications'a kurar.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/desktop/build"
APP="$BUILD/ytConvert.app"
DEST="/Applications/ytConvert.app"

rm -rf "$BUILD" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "→ Derleniyor"
xcrun swiftc -O -swift-version 5 -target arm64-apple-macos13.0 \
    -o "$APP/Contents/MacOS/ytConvert" "$ROOT/desktop/main.swift"

echo "→ İkon"
ICONSET="$BUILD/AppIcon.iconset"; mkdir -p "$ICONSET"
xcrun swift "$ROOT/desktop/make_icon.swift" "$BUILD/icon.png"
for s in 16 32 128 256 512; do
    sips -z $s $s "$BUILD/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$BUILD/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>com.yigitsktas.ytconvert.app</string>
    <key>CFBundleName</key><string>ytConvert</string>
    <key>CFBundleDisplayName</key><string>ytConvert</string>
    <key>CFBundleExecutable</key><string>ytConvert</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>2.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSAppTransportSecurity</key>
    <dict><key>NSAllowsLocalNetworking</key><true/></dict>
    <key>YTCProjectRoot</key><string>$ROOT</string>
</dict>
</plist>
EOF

codesign --force --sign - "$APP" >/dev/null 2>&1

echo "→ /Applications'a kuruluyor"
rm -rf "$DEST" && cp -R "$APP" "$DEST"
touch "$DEST"  # Dock/Finder ikon önbelleği yenilensin
echo "✓ $DEST"
