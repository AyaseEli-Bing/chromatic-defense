# 🏰 Chromatic Defense · 塔防游戏

> 8 种语言混搭的 macOS 原生塔防游戏。不是"为了混而混"——每种语言都承担了它最擅长的职责，通过明确的接口契约协作，最终编译成一个可运行的 App。

![languages](https://img.shields.io/badge/languages-8-orange) ![platform](https://img.shields.io/badge/platform-macOS-blue) ![version](https://img.shields.io/badge/version-0.0.1-green)

## 🎮 玩法

经典塔防：在路径旁建塔阻止敌人到达终点。

- **3 种塔**：箭塔（单体高频）、炮塔（溅射）、魔法塔（减速）
- **3 种敌人**：小兵（快弱）、重甲（慢强）、飞龙（高速）
- **8 波递进难度**，每波敌人组合不同
- 塔可升级（3 级）可卖出（返还 60%）
- 本地 SQLite 排行榜

## 🏗️ 架构：8 种语言各司其职

```
Shell 启动器 (run.sh)
    ↓ 检测依赖 + 增量编译 + 设置环境
Swift App (swift/App.swift)
    ├─ NSWindow + WKWebView ←→ JavaScript (web/game.js)   渲染 + 交互
    └─ Process 启动 → Python 子进程 (python/main.py)       游戏主循环
                          ├─ ctypes → C dylib (c/)          A*寻路 + Lua加载
                          │            └─ Lua C API → Lua (lua/)  关卡配置
                          ├─ ctypes → Rust dylib (rust/)     音效合成
                          └─ ctypes → Go dylib (go/)         SQLite排行榜
```

| 语言 | 职责 | 为什么是它 |
|------|------|-----------|
| **Swift** | App 壳（NSWindow + WKWebView + 子进程管理） | macOS 原生 UI 的官方语言 |
| **Python** | 游戏主循环（状态机、事件分发、30fps 固定步长） | 快速逻辑开发，ctypes 生态成熟 |
| **C** | A* 寻路 + Lua 脚本加载器 | 寻路是性能热点；C 是 Lua C API 的原生宿主 |
| **Rust** | 音效合成（方波 beep，6 种音效） | 内存安全 + 高性能数值计算 |
| **Go** | SQLite 排行榜（建表/插入/Top10 查询） | cgo 导出 dylib 简洁，database/sql 成熟 |
| **JavaScript** | Canvas 渲染 + 鼠标交互 + Web Audio 即时音效 | 浏览器渲染的标准方案，WKWebView 原生支持 |
| **Lua** | 关卡配置（地图、塔/敌人 spec、波次定义） | 游戏配置的标准 DSL，可热重载 |
| **Shell** | 启动器（依赖检测、增量编译、环境装配） | 系统胶水语言，macOS 原生 zsh |

### 通信架构

```
用户操作 → JS → Swift(WKScriptMessageHandler) → Python(socket) → 游戏逻辑
                                                                    ↓
游戏状态(30fps) → Python(socket) → Swift(readLoop) → JS(handleState) → Canvas
```

- **JS ↔ Swift**：`WKScriptMessageHandler`（JS 调原生）+ `evaluateJavaScript`（原生调 JS）
- **Swift ↔ Python**：localhost TCP socket（127.0.0.1:9876），JSON over newline-delimited 协议
- **Python ↔ C/Rust/Go**：ctypes 加载 dylib，直接函数调用

## 🚀 运行

```bash
git clone <repo-url>
cd tower-defense
bash run.sh
```

`run.sh` 会自动：检测依赖 → 增量编译 → 去除 quarantine → 启动 App。

### 依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| Swift | App 壳 | macOS 自带（Xcode Command Line Tools） |
| Python 3.13+ | 游戏主循环 | `brew install python` |
| clang | C 库编译 | `xcode-select --install` |
| Rust + cargo | Rust 库编译 | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Go 1.21+ | Go 库编译 | `brew install go` |
| Lua 5.x + lua.h | 关卡脚本加载 | `brew install lua` |

> macOS Apple Silicon 已验证。Intel 理论可用但未测。

## 📁 项目结构

```
tower-defense/
├── run.sh              # Shell 启动器（第 8 种语言）
├── build.sh            # 一键编译全部原生库 + Swift App
├── swift/
│   └── App.swift       # macOS App 壳：NSWindow + WKWebView + socket 桥接
├── python/
│   ├── main.py         # 游戏主循环：状态机 + socket 服务
│   └── bridge.py       # ctypes 桥接 3 个 dylib
├── c/
│   ├── pathfinding.c   # A* 寻路算法
│   ├── pathfinding.h
│   ├── lua_loader.c    # Lua C API 加载关卡配置
│   └── test_c.c        # C 库单元测试
├── rust/
│   ├── Cargo.toml
│   └── src/lib.rs      # 音效合成（WAV 方波生成）
├── go/
│   ├── go.mod
│   └── leaderboard.go  # SQLite 排行榜（cgo 导出 dylib）
├── lua/
│   └── levels.lua      # 关卡配置：地图/塔/敌人/波次
├── web/
│   ├── index.html
│   ├── game.js         # Canvas 渲染 + 鼠标交互
│   └── style.css
└── test_socket.py      # socket 通信冒烟测试
```

## 🔧 开发

### 修改关卡

编辑 `lua/levels.lua`，保存后 `bash run.sh` 即生效（Lua 脚本运行时加载）。

### 重新编译

```bash
bash build.sh    # 全量编译所有 dylib + Swift App
```

### 通信协议

Python 监听 `127.0.0.1:9876`，newline-delimited JSON：

```jsonc
// JS → Python（命令）
{"type":"build_tower","x":3,"y":5,"tower":"arrow"}
{"type":"start_wave"}
{"type":"upgrade_tower","x":3,"y":5}
{"type":"sell_tower","x":3,"y":5}
{"type":"submit_score","name":"Alice"}
{"type":"get_leaderboard"}
{"type":"restart"}

// Python → JS（状态推送，30fps）
{"type":"state","phase":"waiting","gold":200,"lives":20,...}

// Python → JS（命令响应）
{"type":"resp","ok":true,"msg":"建造箭塔成功"}
```

## 📝 设计决策

### 为什么用 8 种语言而不是 1 种？

不是为了炫技。每种语言的选择都有工程理由：
- 渲染用 JS/Canvas 比Swift/AppKit 快速原型更快
- 寻路用 C 比 Python 快 100 倍，是真正的性能瓶颈
- 音效用 Rust 合成比依赖音频文件更轻量（6 个 wav 总共 < 50KB）
- 排行榜用 Go/SQLite 比 Python/sqlite3 更稳（cgo 导出 dylib 无 GIL 问题）
- 关卡用 Lua 比 JSON 更灵活（可写逻辑，不只数据）

### 为什么用 socket 而不是嵌入 Python？

子进程 + socket 的隔离边界清晰：Python 崩溃不影响 App 壳，调试时可以单独跑 Python + test_socket.py 验证逻辑。

## 📄 License

MIT
