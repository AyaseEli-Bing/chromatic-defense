"""test_socket.py — socket 通信冒烟测试"""
import socket, json, time, sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('127.0.0.1', 9876))
sock.setblocking(False)
buf = b''
resps = []
states = []

def read_all():
    global buf
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            buf += data
    except BlockingIOError:
        pass
    while b'\n' in buf:
        line, buf = buf.split(b'\n', 1)
        try:
            msg = json.loads(line.decode())
            if msg.get('type') == 'resp':
                resps.append(msg)
            elif msg.get('type') == 'state':
                states.append(msg)
        except Exception:
            pass

def send_cmd(cmd):
    sock.sendall((json.dumps(cmd) + '\n').encode())

# 等连接 + 首个 state
for _ in range(30):
    read_all()
    if states:
        break
    time.sleep(0.1)

s = states[-1] if states else {}
print('[1] 初始: phase=%s gold=%d towers=%d' % (s.get('phase'), s.get('gold'), len(s.get('towers', []))))

# 建塔
send_cmd({'type': 'build_tower', 'x': 3, 'y': 1, 'tower': 'arrow'})
time.sleep(0.5)
read_all()
print('[2] resp:', resps)
s = states[-1] if states else {}
print('    state: towers=%d gold=%d' % (len(s.get('towers', [])), s.get('gold')))

# 开始波次
send_cmd({'type': 'start_wave'})
time.sleep(1)
read_all()
print('[3] resp:', resps[-1:])
s = states[-1] if states else {}
print('    state: phase=%s enemies=%d' % (s.get('phase'), len(s.get('enemies', []))))

# 等 3 秒看敌人移动
time.sleep(3)
read_all()
s = states[-1] if states else {}
enemies = s.get('enemies', [])
if enemies:
    e = enemies[0]
    print('[4] 敌人0: pos=(%.2f,%.2f) hp=%d/%d' % (e['x'], e['y'], e['hp'], e['max_hp']))
print('    总敌人=%d 金币=%d 分数=%d' % (len(enemies), s.get('gold'), s.get('score')))

# 排行榜
send_cmd({'type': 'get_leaderboard'})
time.sleep(0.3)
read_all()
s = states[-1] if states else {}
print('[5] 排行榜:', s.get('leaderboard'))

sock.close()
print('[done] OK')
