#!/bin/bash
# run.sh — 塔防游戏启动器（Shell，第8种语言）
# 职责：依赖检测 → 环境装配 → 拉起 Swift App
set -e

PROJ="$(cd "$(dirname "$0")" && pwd)"
BUILD="$PROJ/build"
BIN="$BUILD/TowerDefense"

# 颜色
R='\033[0;31m' G='\033[0;32m' Y='\033[0;33m' N='\033[0m'

echo "╔══════════════════════════════════════════╗"
echo "║   塔防 · Chromatic Defense (8语言混搭)   ║"
echo "║   Swift·Python·C·Rust·Go·JS·Lua·Shell    ║"
echo "╚══════════════════════════════════════════╝"

# ---- 依赖检测 ----
echo ""
echo "[1/3] 依赖检测"
missing=0
check() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "  ${G}✓${N} $1"
    else
        echo "  ${R}✗${N} $1 — 未安装"
        missing=1
    fi
}
check swift
check python3
check clang
check cargo
check rustc
check go
check lua
# 检测 lua 头文件
if [ -f /opt/homebrew/include/lua/lua.h ]; then
    echo "  ${G}✓${N} lua.h"
else
    echo "  ${R}✗${N} lua.h — 缺失（brew install lua）"
    missing=1
fi
if [ $missing -eq 1 ]; then
    echo ""
    echo "${R}依赖缺失，请安装后重试。${N}"
    exit 1
fi

# ---- 编译 ----
echo ""
echo "[2/3] 编译检查"
if [ ! -f "$BIN" ] || [ ! -f "$BUILD/libcr.dylib" ] || [ ! -f "$BUILD/libtdrust.dylib" ] || [ ! -f "$BUILD/libtdgo.dylib" ]; then
    echo "  产物缺失，执行全量编译..."
    bash "$PROJ/build.sh"
else
    # 检查源码是否比产物新
    newest_src=$(find "$PROJ/c" "$PROJ/rust/src" "$PROJ/go" "$PROJ/swift" "$PROJ/lua" "$PROJ/python" "$PROJ/web" -type f -newer "$BIN" 2>/dev/null | head -1)
    if [ -n "$newest_src" ]; then
        echo "  检测到源码更新（$newest_src），重新编译..."
        bash "$PROJ/build.sh"
    else
        echo "  ${G}✓${N} 产物已是最新"
    fi
fi

# ---- 启动 ----
echo ""
echo "[3/3] 启动游戏"
echo "  Swift App: $BIN"
echo "  Python:    $PROJ/python/main.py"
echo "  Web UI:    $PROJ/web/index.html"
echo ""

# 去除 quarantine（本地构建无需签名）
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true

# 设置环境变量，启动 Swift App
export TD_ROOT="$PROJ"
export DYLD_LIBRARY_PATH="/opt/homebrew/lib"
exec "$BIN"
