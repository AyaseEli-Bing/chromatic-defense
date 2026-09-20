#!/bin/bash
# build_app.sh — 编译并打包 ChromaticDefense.app
# 输出: build/ChromaticDefense.app —— 双击即可运行
set -e

PROJ="$(cd "$(dirname "$0")" && pwd)"
BUILD="$PROJ/build"
APP="$BUILD/ChromaticDefense.app"

echo "========== [1/4] 编译所有原生库 + Swift App =========="
bash "$PROJ/build.sh"

echo ""
echo "========== [2/4] 创建 .app bundle 结构 =========="
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Frameworks"
mkdir -p "$APP/Contents/Resources/web"
mkdir -p "$APP/Contents/Resources/python"
mkdir -p "$APP/Contents/Resources/lua"

# 可执行
cp "$BUILD/TowerDefense" "$APP/Contents/MacOS/TowerDefense"
# 动态库
cp "$BUILD/libcr.dylib" "$APP/Contents/Frameworks/"
cp "$BUILD/libtdrust.dylib" "$APP/Contents/Frameworks/"
cp "$BUILD/libtdgo.dylib" "$APP/Contents/Frameworks/"
# 资源
cp -r "$PROJ/web/"* "$APP/Contents/Resources/web/"
cp "$PROJ/python/main.py" "$PROJ/python/bridge.py" "$APP/Contents/Resources/python/"
cp "$PROJ/lua/levels.lua" "$APP/Contents/Resources/lua/"
# 把可执行需要 build 时生成的 sfx 也拷过去（首次启动会重新生成，但预先生成体验更好）
for f in "$BUILD"/sfx_*.wav; do
  [ -f "$f" ] && cp "$f" "$APP/Contents/Resources/"
done
# 初始空数据库（运行时 Python 会自动创建，这个只是占位）
touch "$APP/Contents/Resources/scores.db"
echo "  -> bundle structure ready"

echo ""
echo "========== [3/4] 写 Info.plist =========="
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>ChromaticDefense</string>
  <key>CFBundleDisplayName</key>
  <string>塔防 · Chromatic Defense</string>
  <key>CFBundleExecutable</key>
  <string>TowerDefense</string>
  <key>CFBundleIdentifier</key>
  <string>com.ayaseeli-bing.chromaticdefense</string>
  <key>CFBundleVersion</key>
  <string>0.2.0-rc.1</string>
  <key>CFBundleShortVersionString</key>
  <string>0.2.0-rc.1</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleSignature</key>
  <string>????</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSSupportsAutomaticTermination</key>
  <true/>
  <key>NSSupportsSuddenTermination</key>
  <true/>
  <key>CFBundleDocumentTypes</key>
  <array/>
</dict>
</plist>
EOF
echo "  -> Info.plist written"

echo ""
echo "========== [4/4] ad-hoc 签名 + 去 quarantine =========="
codesign --force --deep --sign - "$APP" 2>&1 | head -5
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "  -> signed"

echo ""
echo "✅ ChromaticDefense.app 已就绪: $APP"
echo "   运行: open \"$APP\"   或  双击"
echo ""
du -sh "$APP"
ls -lh "$APP/Contents/MacOS/TowerDefense"