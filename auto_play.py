"""auto_play.py — 自动游玩 8 波（严格同步游戏波次）
只在 phase=waiting 时开波；塔沿路径分散布置；记录特性敌人出现情况。
"""
import socket, json, time

HOST, PORT = '127.0.0.1', 9876


class Client:
    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((HOST, PORT))
        self.s.setblocking(False)
        self.buf = b''
        self.state = None
        self.resps = []

    def send(self, cmd):
        self.s.sendall((json.dumps(cmd) + '\n').encode())

    def pump(self, seconds=0.3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                d = self.s.recv(65536)
                if not d:
                    return False
                self.buf += d
            except BlockingIOError:
                time.sleep(0.02)
        while b'\n' in self.buf:
            line, self.buf = self.buf.split(b'\n', 1)
            if not line.strip():
                continue
            try:
                m = json.loads(line)
                if m.get('type') == 'state':
                    self.state = m
                elif m.get('type') == 'resp':
                    self.resps.append(m)
            except Exception:
                pass
        return True

    def close(self):
        self.s.close()


def spiral_cells(s, n):
    """沿路径均匀取 n 个建塔点（分散布置，避免全部堆在末端）"""
    path = s['path']
    built = set((t['x'], t['y']) for t in s['towers'])
    out = []
    step = max(1, len(path) // (n * 2))
    for i in range(0, len(path), step):
        px, py = path[i]
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
            nx, ny = px + dx, py + dy
            if (0 <= nx < s['W'] and 0 <= ny < s['H']
                    and s['map'][ny][nx] == 0
                    and (nx, ny) not in built
                    and (nx, ny) not in [(c[0], c[1]) for c in out]):
                out.append((nx, ny))
                break
        if len(out) >= n:
            break
    return out


def main():
    c = Client()
    c.pump(0.8)
    if not c.state:
        print("FAIL: no state")
        return
    specs = {t['id']: t for t in c.state['tower_specs']}
    print("塔配置: " + ", ".join(f"{k}(dmg{v['damage']},rng{v['range']},cost{v['cost']})" for k, v in specs.items()))

    c.send({'type': 'restart'})
    c.pump(0.5)
    s = c.state
    print(f"总波次: {s['total_waves']}  初始金币: {s['gold']}  生命: {s['lives']}\n")

    # 建塔优先级：先便宜塔起步，攒钱后补魔法塔（防空）+ 激光塔（破盾）+ 炮塔（溅射）
    plan = ['arrow', 'arrow', 'arrow', 'magic', 'cannon', 'laser', 'magic', 'laser', 'laser', 'cannon', 'laser', 'laser']
    plan_idx = 0
    seen = set()
    kills_events = 0

    for wave_no in range(1, 9):
        # 等到 waiting 状态
        waited = 0.0
        while c.state['phase'] == 'playing' and waited < 90:
            c.pump(0.3)
            waited += 0.3
        s = c.state
        if s['phase'] in ('game_over', 'victory'):
            print(f"  游戏在波{wave_no}前结束: {s['phase']}")
            break

        # 补塔：按优先级建"当前金币负担得起"的塔（贵的优先，避免卡在买不起的塔上）
        priority = ['laser', 'cannon', 'magic', 'arrow']
        while True:
            s = c.state
            built = False
            for tid in priority:
                if s['gold'] >= specs[tid]['cost']:
                    cells = spiral_cells(s, 1)
                    if cells:
                        cx, cy = cells[0]
                        c.send({'type': 'build_tower', 'x': cx, 'y': cy, 'tower': tid})
                        c.pump(0.15)
                        built = True
                        break
            if not built:
                break

        # 开波
        c.send({'type': 'start_wave'})
        c.pump(0.3)
        wave_start_lives = c.state['lives']
        max_enemies = 0
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if not c.pump(0.3):
                print("  socket closed")
                return
            s = c.state
            for e in s['enemies']:
                if e.get('flying'):
                    seen.add('flyer')
                if e.get('shielded'):
                    seen.add('shielded')
                if e.get('healer'):
                    seen.add('healer')
            max_enemies = max(max_enemies, len(s['enemies']))
            if s['phase'] != 'playing':
                break
        print(f"  波{wave_no}: {s['phase']:9s} lives={s['lives']:2d}(-{wave_start_lives - s['lives']}) "
              f"gold={s['gold']:4d} score={s['score']:5d} towers={len(s['towers'])} 峰值敌人={max_enemies}")

        if s['phase'] in ('game_over', 'victory'):
            break

    s = c.state
    print()
    print(f"最终: phase={s['phase']} wave={s['wave']}/{s['total_waves']} lives={s['lives']} "
          f"score={s['score']} towers={len(s['towers'])}")
    print(f"观察到的特性敌人: {sorted(seen) if seen else '（无）'}")
    missing = {'flyer', 'shielded', 'healer'} - seen
    print(f"3 种特性敌人全部出现: {'YES ✅' if not missing else f'NO ❌ 缺少 {sorted(missing)}'}")
    c.close()


if __name__ == '__main__':
    main()