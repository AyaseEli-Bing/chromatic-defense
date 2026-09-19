#!/bin/bash
# build.sh — 一键编译塔防全部原生库 + Swift App
set -e

PROJ="$(cd "$(dirname "$0")" && pwd)"
BUILD="$PROJ/build"
mkdir -p "$BUILD"

echo "========== [1/5] C 库 (A*寻路 + Lua加载器) =========="
LUA_CFLAGS="$(PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig pkg-config --cflags lua 2>/dev/null || echo '-I/opt/homebrew/include/lua')"
LUA_LIBS="$(PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig pkg-config --libs lua 2>/dev/null || echo '-L/opt/homebrew/lib -llua -lm')"
clang -shared -O2 -fPIC -o "$BUILD/libcr.dylib" \
  "$PROJ/c/pathfinding.c" "$PROJ/c/lua_loader.c" \
  $LUA_CFLAGS $LUA_LIBS
# 加 rpath 让 libcr 能自动找到 liblua，不依赖 DYLD_LIBRARY_PATH
install_name_tool -add_rpath /opt/homebrew/lib "$BUILD/libcr.dylib" 2>/dev/null || true
echo "  -> libcr.dylib OK"

echo "========== [2/5] Rust 库 (敌人AI + 音效合成) =========="
(cd "$PROJ/rust" && cargo build --release 2>&1 | tail -2)
cp "$PROJ/rust/target/release/libtdrust.dylib" "$BUILD/libtdrust.dylib"
echo "  -> libtdrust.dylib OK"

echo "========== [3/5] Go 库 (SQLite排行榜) =========="
(cd "$PROJ/go" && export GOPROXY=https://goproxy.cn,direct && CGO_ENABLED=1 go build -buildmode=c-shared -o "$BUILD/libtdgo.dylib" . 2>&1 | tail -2)
echo "  -> libtdgo.dylib OK"

echo "========== [4/5] Swift App (NSWindow + WKWebView) =========="
(cd "$PROJ/swift" && swiftc -O -framework Cocoa -framework WebKit App.swift -o "$BUILD/TowerDefense")
echo "  -> TowerDefense OK"

echo "========== [5/5] 清理测试文件 =========="
rm -f "$BUILD/test_c" "$BUILD/test_scores.db" "$BUILD/beep_test.wav"
echo "  -> cleaned"

echo ""
echo "✅ 全部编译完成！产物在: $BUILD"
echo "   运行: $PROJ/run.sh"
ls -lh "$BUILD"/*.dylib "$BUILD/TowerDefense" 2>/dev/null
