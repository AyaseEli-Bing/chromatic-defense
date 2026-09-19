"""stress.py — 90秒压测，模拟完整游玩循环"""
import socket, json, time, sys

HOST = '127.0.0.1'
PORT = 9876


def read_all(sock, buf_ref, dur=0.3):
    sock.setblocking(False)
    states = []
    resps = []
    deadline = time.monotonic() + dur
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65536)
            if not data:
                return None, None
            buf_ref[0] += data
            while b'\n' in buf_ref[0]:
                line, buf_ref[0] = buf_ref[0].split(b'\n', 1)
                try:
                    msg = json.loads(line.decode())
                    if msg.get('type') == 'state':
                        states.append(msg)
                    elif msg.get('type') == 'resp':
                        resps.append(msg)
                except Exception:
                    pass
        except BlockingIOError:
            time.sleep(0.02)
    return states, resps


def send_cmd(sock, cmd):
    sock.sendall((json.dumps(cmd) + '\n').encode())


def find_open_cells(map_data, n=5):
    cells = []
    for y, row in enumerate(map_data):
        for x, cell in enumerate(row):
            if cell == 0:
                cells.append((x, y))
                if len(cells) >= n:
                    return cells
    return cells


def run_round(sock, buf, round_no):
    states, _ = read_all(sock, buf, 0.5)
    if not states:
        return False, "no initial state"
    s = states[-1]
    spec = s['tower_specs'][0]
    cells = find_open_cells(s['map'], n=8)
    built = 0
    for (x, y) in cells:
        if s['gold'] >= spec['cost']:
            send_cmd(sock, {'type': 'build_tower', 'x': x, 'y': y, 'tower': spec['id']})
            time.sleep(0.08)
            built += 1
    send_cmd(sock, {'type': 'start_wave'})
    deadline = time.monotonic() + 30
    last_sig = None
    stall = 0
    while time.monotonic() < deadline:
        states, _ = read_all(sock, buf, 0.3)
        if not states:
            return False, "socket closed"
        s = states[-1]
        sig = (s['phase'], s['lives'], len(s['enemies']), len(s['projectiles']))
        if sig != last_sig:
            last_sig = sig
            stall = 0
        else:
            stall += 1
        if s['phase'] in ('game_over', 'victory'):
            send_cmd(sock, {'type': 'submit_score', 'name': f'S{round_no}'})
            time.sleep(0.1)
            send_cmd(sock, {'type': 'restart'})
            time.sleep(0.2)
            return True, f"R{round_no} {s['phase']} score={s['score']} built={built}"
        if stall > 80:
            return False, f"R{round_no} STALL phase={s['phase']} lives={s['lives']} enemies={len(s['enemies'])} proj={len(s['projectiles'])}"
    return False, f"R{round_no} timeout"


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    buf = [b'']
    start = time.monotonic()
    ok, fail = 0, 0
    while time.monotonic() - start < 90:
        r, msg = run_round(sock, buf, ok + fail + 1)
        elapsed = time.monotonic() - start
        prefix = "  " if r else "!!"
        print(f"{prefix}[{elapsed:5.1f}s] {msg}  (ok={ok} fail={fail})", flush=True)
        if r:
            ok += 1
        else:
            fail += 1
            break
    sock.close()
    print(f"\n=== done: {(time.monotonic()-start):.1f}s, ok={ok}, fail={fail} ===")


if __name__ == '__main__':
    main()