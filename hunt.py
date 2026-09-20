"""hunt.py — 精准测试：建塔沿路径，开波次，记录敌人 hp 变化"""
import socket, json, time, sys

HOST = '127.0.0.1'
PORT = 9876


def read_all(sock, buf_ref, dur=0.3):
    sock.setblocking(False)
    states = []
    deadline = time.monotonic() + dur
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65536)
            if not data:
                return None
            buf_ref[0] += data
            while b'\n' in buf_ref[0]:
                line, buf_ref[0] = buf_ref[0].split(b'\n', 1)
                try:
                    msg = json.loads(line.decode())
                    if msg.get('type') == 'state':
                        states.append(msg)
                except Exception:
                    pass
        except BlockingIOError:
            time.sleep(0.02)
    return states


def send_cmd(sock, cmd):
    sock.sendall((json.dumps(cmd) + '\n').encode())


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    buf = [b'']

    states = read_all(sock, buf, 0.5)
    s = states[-1]
    print(f"[init] phase={s['phase']} gold={s['gold']} path_len={len(s['path'])}")
    print(f"[path] start={s['start']} goal={s['goal']}")
    # 找路径旁边的格子（距路径 < 1.5 格）
    near_path_cells = set()
    path_points = set((p[0], p[1]) for p in s['path'])
    for (px, py) in path_points:
        for dx, dy in [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]:
            nx, ny = px+dx, py+dy
            if 0 <= nx < s['W'] and 0 <= ny < s['H'] and s['map'][ny][nx] == 0:
                near_path_cells.add((nx, ny))
    near_path_cells -= path_points
    print(f"[path] {len(near_path_cells)} empty cells adjacent to path")

    # 在路径中段附近建 5 个激光塔（v1.0.0 测试新增塔）
    arrow = next(sp for sp in s['tower_specs'] if sp['id'] == 'laser')
    print(f"[tower] laser: damage={arrow['damage']} range={arrow['range']} fire_rate={arrow['fire_rate']} cost={arrow['cost']}")
    placed = 0
    # 优先选路径中段（idx 5-15）
    mid_cells = sorted(near_path_cells, key=lambda c: abs(sum(c) - 10))
    for (x, y) in mid_cells:
        if s['gold'] >= arrow['cost']:
            send_cmd(sock, {'type': 'build_tower', 'x': x, 'y': y, 'tower': 'laser'})
            time.sleep(0.05)
            placed += 1
            if placed >= 5:
                break
    print(f"[tower] placed {placed} laser towers near mid-path")

    # 确认塔建好
    time.sleep(0.3)
    states = read_all(sock, buf, 0.3)
    s = states[-1]
    print(f"[placed] towers={len(s['towers'])}: " + ", ".join(f"({t['x']},{t['y']})rng={t['range']}lv{t['level']}" for t in s['towers']))

    # 开波
    send_cmd(sock, {'type': 'start_wave'})
    print(f"[wave] start")

    # 追踪 20 秒内每个敌人 hp 变化
    last_seen = {}  # enemy unique id by initial position+spawn order -> (hp_history)
    spawn_order = 0
    hp_changes = []  # (t, eid, hp_before, hp_after)
    start = time.monotonic()
    while time.monotonic() - start < 20:
        states = read_all(sock, buf, 0.2)
        if not states:
            print("[err] socket closed")
            return
        s = states[-1]
        for i, e in enumerate(s['enemies']):
            # 用 (x, y) round 作为粗略 ID
            eid = (round(e['x'], 1), round(e['y'], 1), i)
            hp = e['hp']
            if eid not in last_seen:
                last_seen[eid] = [(time.monotonic()-start, hp, e['color'], e['size'])]
                spawn_order += 1
            else:
                prev_t, prev_hp, _, _ = last_seen[eid][-1]
                if hp != prev_hp:
                    hp_changes.append((time.monotonic()-start, eid, prev_hp, hp))
                last_seen[eid].append((time.monotonic()-start, hp, e['color'], e['size']))

    print(f"\n[stat] {spawn_order} enemies spawned, {len(hp_changes)} hp changes detected")
    if hp_changes:
        print(f"[stat] first 10 changes:")
        for t, eid, h0, h1 in hp_changes[:10]:
            print(f"  t={t:.2f}s pos={eid[:2]} hp: {h0} -> {h1}")
        # 找最大 hp 减少的敌人
        max_decrease = 0
        for eid, hist in last_seen.items():
            for i in range(1, len(hist)):
                if hist[i][1] < hist[i-1][1]:
                    pass
            min_hp = min(h[1] for h in hist)
            max_hp = max(h[1] for h in hist)
            if max_hp - min_hp > max_decrease:
                max_decrease = max_hp - min_hp
                print(f"  max drop: enemy at {eid[:2]} color={hist[-1][2]} hp: {max_hp} -> {min_hp}")
    else:
        print(f"[!!] NO HP CHANGES IN 20s — enemies can't die")

    sock.close()


if __name__ == '__main__':
    main()