"""main.py — 塔防游戏主循环（Python）
职责：加载关卡 → 驱动游戏状态机 → 通过 localhost socket 与 Swift/JS 通信。

通信协议：
  - Python 监听 localhost:9876
  - 每帧(30fps)推送: {"type":"state", ...游戏状态...}
  - 接收命令: {"type":"build_tower","x":3,"y":5,"tower":"arrow"}
            {"type":"start_wave"}
            {"type":"submit_score","name":"Alice"}
            {"type":"get_leaderboard"}
            {"type":"restart"}
"""
import ctypes
import json
import math
import os
import select
import socket
import subprocess
import sys
import threading
import time

from bridge import NativeBridge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")


class Tower:
    fire_count = 0  # 诊断：总开火次数
    def __init__(self, x, y, spec):
        self.x = x
        self.y = y
        self.spec = spec
        self.level = 1
        self.cooldown = 0.0
        self.angle = 0.0

    @property
    def range(self):
        return self.spec["range"] * (1 + 0.15 * (self.level - 1))

    @property
    def damage(self):
        return self.spec["damage"] * (1 + 0.3 * (self.level - 1))

    @property
    def fire_rate(self):
        return self.spec["fire_rate"]

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "type": self.spec["id"],
            "name": self.spec["name"], "color": self.spec["color"],
            "level": self.level, "range": self.range, "damage": self.damage, "cooldown": self.cooldown,
            "angle": self.angle,
        }


class Enemy:
    def __init__(self, spec, path):
        self.spec = spec
        self.x = float(path[0][0])
        self.y = float(path[0][1])
        self.hp = spec["hp"]
        self.max_hp = spec["hp"]
        self.speed = spec["speed"]
        self.reward = spec["reward"]
        self.color = spec.get("color", "#ff4444")
        self.size = spec.get("size", 1.0)
        self.path = path
        self.target_idx = 1
        self.slow_timer = 0.0
        self.slow_factor = 1.0
        self.dead = False
        self.reached_goal = False
        # ---- 特性敌人字段 ----
        self.flying = bool(spec.get("flying", False))
        self.shield_threshold = spec.get("shield_threshold", 0)
        self.shield_reduction = spec.get("shield_reduction", 1.0)
        self.heal_interval = spec.get("heal_interval", 0)
        self.heal_amount = spec.get("heal_amount", 0)
        self.heal_radius = spec.get("heal_radius", 0)
        self.heal_timer = self.heal_interval

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "hp": self.hp, "max_hp": self.max_hp,
            "color": self.color, "size": self.size, "dead": self.dead,
            # 特性标记：供 JS 渲染不同外观
            "flying": self.flying,
            "shielded": self.shield_threshold > 0,
            "healer": self.heal_amount > 0,
        }

    def take_damage(self, raw_damage):
        """受击结算：护盾单位为低单发伤害提供减免。返回实际伤害。"""
        dmg = raw_damage
        if self.shield_threshold > 0 and raw_damage < self.shield_threshold:
            dmg = raw_damage * self.shield_reduction
        self.hp -= dmg
        return dmg


class Projectile:
    hit_count = 0  # 诊断：总命中次数
    def __init__(self, x, y, target_enemy, damage, color, splash=0):
        self.x = x
        self.y = y
        self.target = target_enemy
        self.damage = damage
        self.color = color
        self.splash = splash
        self.dead = False

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "color": self.color,
            "tx": self.target.x if self.target and not self.target.dead else self.x,
            "ty": self.target.y if self.target and not self.target.dead else self.y,
        }


class Game:
    def __init__(self, bridge, level, db_path):
        self.bridge = bridge
        self.level = level
        self.W = level["width"]
        self.H = level["height"]
        self.grid = level["grid"]
        self.map_data = level["map"]
        self.tower_specs = {t["id"]: t for t in level["towers"]}
        self.enemy_specs = {e["id"]: e for e in level["enemies"]}
        self.wave_defs = level["wave_defs"]
        self.start = (level["start"]["x"] - 1, level["start"]["y"] - 1)
        self.goal = (level["goal"]["x"] - 1, level["goal"]["y"] - 1)
        self.start_gold = int(os.environ.get("TD_START_GOLD", level["start_gold"]))
        self.start_lives = int(os.environ.get("TD_START_LIVES", level["start_lives"]))

        # A* 计算路径
        grid_flat = []
        for row in self.grid:
            grid_flat.extend(row)
        self.path = bridge.pathfind(grid_flat, self.W, self.H,
                                    self.start[0], self.start[1],
                                    self.goal[0], self.goal[1])
        if not self.path:
            raise RuntimeError("A* pathfinding failed")

        # 排行榜
        self.bridge.lb_init(db_path)

        self.reset()

    def reset(self):
        self.gold = self.start_gold
        self.lives = self.start_lives
        self.wave_idx = 0
        self.score = 0
        self.enemies = []
        self.towers = []
        self.projectiles = []
        self.phase = "waiting"  # waiting | playing | game_over | victory
        self.wave_spawn_queue = []
        self.wave_spawn_timer = 0
        self.wave_active = False
        self.pending_leaderboard = False
        self.leaderboard_data = None
        self.flash_msg = ""
        self.flash_timer = 0

    def build_tower(self, x, y, tower_type):
        if self.phase in ("game_over", "victory"):
            return False, "游戏已结束"
        if tower_type not in self.tower_specs:
            return False, "未知塔类型"
        if x < 0 or x >= self.W or y < 0 or y >= self.H:
            return False, "坐标越界"
        if self.map_data[y][x] != 0:
            return False, "该格不可建塔"
        for t in self.towers:
            if t.x == x and t.y == y:
                return False, "已有塔"
        spec = self.tower_specs[tower_type]
        if self.gold < spec["cost"]:
            return False, "金币不足"
        self.gold -= spec["cost"]
        self.towers.append(Tower(x, y, spec))
        return True, f"建造{spec['name']}成功"

    def upgrade_tower(self, x, y):
        for t in self.towers:
            if t.x == x and t.y == y:
                cost = t.spec["cost"] * t.level
                if self.gold < cost:
                    return False, "金币不足"
                if t.level >= 3:
                    return False, "已满级"
                self.gold -= cost
                t.level += 1
                return True, f"升级到{t.level}级"
        return False, "未找到塔"

    def sell_tower(self, x, y):
        for i, t in enumerate(self.towers):
            if t.x == x and t.y == y:
                refund = int(t.spec["cost"] * t.level * 0.6)
                self.gold += refund
                self.towers.pop(i)
                return True, f"卖出获得{refund}金币"
        return False, "未找到塔"

    def start_wave(self):
        if self.phase != "waiting":
            return False, "当前波次进行中"
        if self.wave_idx >= len(self.wave_defs):
            return False, "所有波次已完成"
        wd = self.wave_defs[self.wave_idx]
        self.wave_spawn_queue = []
        for spawn in wd["spawns"]:
            enemy_spec = self.enemy_specs[spawn["type"]]
            for _ in range(spawn["count"]):
                self.wave_spawn_queue.append((enemy_spec, spawn.get("interval", 0.8)))
        self.wave_spawn_timer = 0
        self.wave_active = True
        self.phase = "playing"
        return True, f"第{self.wave_idx+1}波开始"

    def _spawn_next(self, dt):
        if not self.wave_spawn_queue:
            return
        self.wave_spawn_timer -= dt
        if self.wave_spawn_timer <= 0:
            spec, interval = self.wave_spawn_queue.pop(0)
            self.enemies.append(Enemy(spec, self.path))
            self.wave_spawn_timer = interval

    def update(self, dt):
        if self.flash_timer > 0:
            self.flash_timer -= dt

        if self.phase == "playing":
            self._spawn_next(dt)
            self._update_enemies(dt)
            self._update_towers(dt)
            self._update_projectiles(dt)

            # 波次结束判定
            if not self.wave_spawn_queue and not self.enemies:
                self.wave_idx += 1
                self.wave_active = False
                if self.wave_idx >= len(self.wave_defs):
                    self.phase = "victory"
                    self.flash_msg = "胜利！"
                    self.flash_timer = 999
                else:
                    self.phase = "waiting"
                    self.flash_msg = f"第{self.wave_idx}波完成，准备下一波"
                    self.flash_timer = 3

            if self.lives <= 0:
                self.phase = "game_over"
                self.flash_msg = "游戏结束"
                self.flash_timer = 999

        self._cleanup()

    def _update_enemies(self, dt):
        for e in self.enemies:
            if e.dead or e.reached_goal:
                continue
            if e.slow_timer > 0:
                e.slow_timer -= dt
                if e.slow_timer <= 0:
                    e.slow_factor = 1.0
            if e.target_idx >= len(e.path):
                e.reached_goal = True
                self.lives -= 1
                continue
            tx, ty = e.path[e.target_idx]
            nx, ny, reached = self.bridge.enemy_step(
                e.x, e.y, float(tx), float(ty),
                e.speed, e.slow_factor, dt
            )
            e.x, e.y = nx, ny
            if reached:
                e.target_idx = self.bridge.next_target(e.target_idx, len(e.path))

        # 医疗兵：定期为半径内友军回复 HP（不治疗自己）
        for e in self.enemies:
            if e.dead or e.reached_goal or e.heal_amount <= 0 or e.heal_interval <= 0:
                continue
            e.heal_timer -= dt
            if e.heal_timer <= 0:
                e.heal_timer = e.heal_interval
                r2 = e.heal_radius ** 2
                for ally in self.enemies:
                    if ally is e or ally.dead or ally.reached_goal:
                        continue
                    if ally.hp >= ally.max_hp:
                        continue
                    d2 = (ally.x - e.x) ** 2 + (ally.y - e.y) ** 2
                    if d2 <= r2:
                        ally.hp = min(ally.hp + e.heal_amount, ally.max_hp)

    def _update_towers(self, dt):
        for t in self.towers:
            if t.cooldown > 0:
                t.cooldown -= dt
            # 找最近的在射程内的敌人
            best = None
            best_dist = t.range ** 2
            for e in self.enemies:
                if e.dead or e.reached_goal:
                    continue
                # 飞行单位：只有射程 >= 4 的塔能锁定（箭塔/炮塔打不到空中）
                if e.flying and t.range < 4:
                    continue
                d2 = (e.x - t.x) ** 2 + (e.y - t.y) ** 2
                if d2 <= best_dist:
                    best_dist = d2
                    best = e
            if best and t.cooldown <= 0:
                t.cooldown = t.fire_rate
                t.angle = math.atan2(best.y - t.y, best.x - t.x)
                self.projectiles.append(Projectile(
                    t.x + 0.5, t.y + 0.5, best, t.damage,
                    t.spec["color"], t.spec.get("splash", 0)
                ))
                if t.spec.get("slow"):
                    best.slow_factor = t.spec["slow"]
                    best.slow_timer = 2.0

    def _update_projectiles(self, dt):
        speed = 8.0
        for p in self.projectiles:
            if p.dead or not p.target or p.target.dead or p.target.reached_goal:
                p.dead = True
                continue
            dx = p.target.x - p.x
            dy = p.target.y - p.y
            dist = math.hypot(dx, dy)
            step = speed * dt
            if dist <= step:
                # 命中：击中给即时反馈分数，击杀给大额奖励
                self.score += 1  # 击中 +1（每次打中都有反馈，激励高 DPS）
                p.target.take_damage(p.damage)  # 含护盾减免结算
                if p.target.hp <= 0 and not p.target.dead:
                    p.target.dead = True
                    self.gold += p.target.reward
                    self.score += p.target.reward * 10  # 击杀额外 +reward×10
                # 溅射
                if p.splash > 0:
                    for e in self.enemies:
                        if e is p.target or e.dead:
                            continue
                        d2 = (e.x - p.target.x) ** 2 + (e.y - p.target.y) ** 2
                        if d2 <= p.splash ** 2:
                            e.take_damage(p.damage * 0.5)  # 溅射同样算护盾减免
                            if e.hp <= 0 and not e.dead:
                                e.dead = True
                                self.gold += e.reward
                                self.score += e.reward * 10
                            else:
                                self.score += 1  # 溅射击中 +1
                p.dead = True
            else:
                p.x += dx / dist * step
                p.y += dy / dist * step

    def _cleanup(self):
        # dead 或 reached_goal 的敌人都不再参与游戏，一并清理
        self.enemies = [e for e in self.enemies if not e.dead and not e.reached_goal]
        self.projectiles = [p for p in self.projectiles if not p.dead]

    def submit_score(self, name):
        self.bridge.lb_add_score(name, self.score, self.wave_idx)

    def get_leaderboard(self):
        self.leaderboard_data = self.bridge.lb_top10()

    def state_dict(self):
        return {
            "type": "state",
            "phase": self.phase,
            "gold": self.gold,
            "lives": self.lives,
            "score": self.score,
            "wave": self.wave_idx,
            "total_waves": len(self.wave_defs),
            "wave_active": self.wave_active,
            "W": self.W,
            "H": self.H,
            "map": self.map_data,
            "path": self.path,
            "enemies": [e.to_dict() for e in self.enemies],
            "towers": [t.to_dict() for t in self.towers],
            "projectiles": [p.to_dict() for p in self.projectiles],
            "tower_specs": self.level["towers"],
            "leaderboard": self.leaderboard_data,
            "flash_msg": self.flash_msg if self.flash_timer > 0 else "",
            "start": list(self.start),
            "goal": list(self.goal),
        }


def handle_command(game, msg):
    """处理来自 JS/Swift 的命令，返回响应 dict。"""
    t = msg.get("type")
    if t == "ping":
        return {"type": "resp", "ok": True, "msg": "pong"}
    if t == "build_tower":
        ok, info = game.build_tower(msg["x"], msg["y"], msg["tower"])
        return {"type": "resp", "ok": ok, "msg": info}
    if t == "upgrade_tower":
        ok, info = game.upgrade_tower(msg["x"], msg["y"])
        return {"type": "resp", "ok": ok, "msg": info}
    if t == "sell_tower":
        ok, info = game.sell_tower(msg["x"], msg["y"])
        return {"type": "resp", "ok": ok, "msg": info}
    if t == "start_wave":
        ok, info = game.start_wave()
        return {"type": "resp", "ok": ok, "msg": info}
    if t == "submit_score":
        game.submit_score(msg.get("name", "Anonymous"))
        return {"type": "resp", "ok": True, "msg": "分数已提交"}
    if t == "get_leaderboard":
        game.get_leaderboard()
        return {"type": "resp", "ok": True, "msg": "排行榜已更新"}
    if t == "restart":
        game.reset()
        return {"type": "resp", "ok": True, "msg": "已重新开始"}
    return {"type": "resp", "ok": False, "msg": f"未知命令: {t}"}


def main():
    lua_path = os.path.join(ROOT, "lua", "levels.lua")
    # 数据库路径：Swift 设置的 TD_SCORES_DB 优先，否则开发模式用 build/scores.db
    db_path = os.environ.get("TD_SCORES_DB") or os.path.join(BUILD, "scores.db")

    # 1) 先 bind/listen——让 Swift 能立即连上，避免 connect 撞空端口被 RST
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 9876))
    srv.listen(8)
    srv.setblocking(False)
    print(f"[python] socket listening on 127.0.0.1:9876 (initializing...)", flush=True)

    # 2) 耗时初始化（ctypes 挂载、Lua 关卡、音效预生成）
    t0 = time.monotonic()
    bridge = NativeBridge()
    print(f"[python] native bridge loaded ({time.monotonic()-t0:.2f}s)", flush=True)
    t1 = time.monotonic()
    level = bridge.load_level(lua_path)
    print(f"[python] level loaded ({time.monotonic()-t1:.2f}s)", flush=True)
    t2 = time.monotonic()
    game = Game(bridge, level, db_path)
    print(f"[python] game initialized ({time.monotonic()-t2:.2f}s)", flush=True)
    t3 = time.monotonic()
    # 音效输出到 TD_SFX_DIR（.app 内）或开发模式 build/
    sfx_dir = os.environ.get("TD_SFX_DIR") or BUILD
    os.makedirs(sfx_dir, exist_ok=True)
    for name, freq, dur in [("hit", 880, 80), ("kill", 1320, 120),
                             ("build", 660, 100), ("wave", 440, 200),
                             ("lose", 200, 400), ("win", 880, 300)]:
        bridge.beep(freq, dur, os.path.join(sfx_dir, f"sfx_{name}.wav"))
    print(f"[python] sfx generated ({time.monotonic()-t3:.2f}s)", flush=True)
    print(f"[python] READY, total init {time.monotonic()-t0:.2f}s", flush=True)

    clients = []
    buf = {}

    TARGET_FPS = 20  # 30→20：体感差异不可察觉，但 Swift dispatchToJS 任务数降 33%，避免主线程堆积
    last = time.monotonic()
    acc = 0.0

    while True:
        now = time.monotonic()
        frame_dt = min(now - last, 0.1)
        last = now
        acc += frame_dt

        # select 同时检测可读(新连接/命令)和可写(推送)
        # 超时设为距下一帧的剩余时间：无命令时休眠，避免 busy-loop 空转烧 CPU
        try:
            timeout = max(0.0, 1.0 / TARGET_FPS - acc)
            r_list, w_list, _ = select.select([srv] + clients, clients, [], timeout)
        except (ValueError, OSError):
            r_list, w_list = [], []

        # 接受新连接
        if srv in r_list:
            try:
                conn, _ = srv.accept()
                conn.setblocking(False)  # 防止 sendall 在客户端不读时阻塞整个循环
                clients.append(conn)
                buf[id(conn)] = b""
                print(f"[python] client connected, total={len(clients)}", flush=True)
            except BlockingIOError:
                pass

        # 读取客户端命令（阻塞 socket + select 已确保可读）
        dead = []
        for conn in r_list:
            if conn is srv:
                continue
            if conn not in clients:
                continue
            try:
                data = conn.recv(4096)
                if not data:
                    dead.append(conn)
                    continue
                buf[id(conn)] += data
                while b"\n" in buf[id(conn)]:
                    line, buf[id(conn)] = buf[id(conn)].split(b"\n", 1)
                    if line.strip():
                        try:
                            msg = json.loads(line.decode("utf-8"))
                            resp = handle_command(game, msg)
                            payload = (json.dumps(resp, separators=(",", ":")) + "\n").encode("utf-8")
                        except Exception as ex:
                            payload = (json.dumps({"type": "resp", "ok": False, "msg": str(ex)}, separators=(",", ":")) + "\n").encode("utf-8")
                        try:
                            conn.sendall(payload)
                        except BlockingIOError:
                            pass  # 发送缓冲满，丢弃该响应（下帧状态会刷新 UI）
                        except (ConnectionError, OSError) as ex:
                            dead.append(conn)
                            break
            except BlockingIOError:
                pass  # recv 非阻塞保护（select 已确保可读，理论上不触发）
            except (ConnectionError, OSError):
                dead.append(conn)
        for d in dead:
            if d in clients:
                clients.remove(d)
            buf.pop(id(d), None)

        # 固定步长更新
        steps = 0
        while acc >= 1.0 / TARGET_FPS and steps < 5:
            game.update(1.0 / TARGET_FPS)
            acc -= 1.0 / TARGET_FPS
            steps += 1

        # 状态推送：仅在发生实际更新的帧边界推送一次（30fps），
        # 避免 busy-loop 每轮都推送撑爆 TCP 缓冲导致 sendall 阻塞
        if steps > 0:
            state = json.dumps(game.state_dict(), separators=(",", ":"))
            payload = (state + "\n").encode("utf-8")
            dead2 = []
            for conn in w_list:
                if conn not in clients:
                    continue
                try:
                    conn.sendall(payload)
                except BlockingIOError:
                    pass  # 客户端暂时不读，丢弃本帧状态，绝不阻塞主循环
                except (ConnectionError, OSError):
                    dead2.append(conn)
            for d in dead2:
                if d in clients:
                    clients.remove(d)
                buf.pop(id(d), None)


if __name__ == "__main__":
    main()
