"""bridge.py — ctypes 挂载三个原生库（C/Rust/Go），提供 Python 友好的封装。"""
import ctypes
import json
import os
import time

# dylib 路径：优先 TD_LIB_PATH 环境变量（Swift 启动时设置），
# 否则开发模式默认 ../build（python/main.py 所在目录的回溯）。
_BUILD = os.environ.get("TD_LIB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "build"
)
# 排行榜数据库：优先 TD_SCORES_DB，否则开发模式默认 ../build/scores.db
_DB_PATH = os.environ.get("TD_SCORES_DB") or os.path.join(_BUILD, "scores.db")
# 音效输出目录
_SFX_DIR = os.environ.get("TD_SFX_DIR") or _BUILD


class NativeBridge:
    """封装 C/Rust/Go 三个 dylib 的调用。"""

    def __init__(self):
        self._cr = ctypes.CDLL(os.path.join(_BUILD, "libcr.dylib"))
        self._rr = ctypes.CDLL(os.path.join(_BUILD, "libtdrust.dylib"))
        self._gr = ctypes.CDLL(os.path.join(_BUILD, "libtdgo.dylib"))
        self._setup_signatures()

    def _setup_signatures(self):
        # C: cr_pathfind
        self._cr.cr_pathfind.restype = ctypes.c_int
        self._cr.cr_pathfind.argtypes = [
            ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.c_int,
        ]
        # C: cr_now_ns
        self._cr.cr_now_ns.restype = ctypes.c_ulonglong
        # C: cr_load_level
        self._cr.cr_load_level.restype = ctypes.c_void_p
        self._cr.cr_load_level.argtypes = [ctypes.c_char_p]
        self._cr.cr_free.argtypes = [ctypes.c_void_p]

        # Rust: rr_enemy_step
        self._rr.rr_enemy_step.restype = None
        self._rr.rr_enemy_step.argtypes = [ctypes.c_float] * 7 + [ctypes.POINTER(ctypes.c_float)]
        # Rust: rr_next_target
        self._rr.rr_next_target.restype = ctypes.c_int
        self._rr.rr_next_target.argtypes = [ctypes.c_int, ctypes.c_int]
        # Rust: rr_beep_to_wav
        self._rr.rr_beep_to_wav.restype = ctypes.c_int
        self._rr.rr_beep_to_wav.argtypes = [ctypes.c_float, ctypes.c_int, ctypes.c_char_p]

        # Go: gr_init / gr_add_score / gr_top10 / gr_free / gr_close
        self._gr.gr_init.restype = ctypes.c_int
        self._gr.gr_init.argtypes = [ctypes.c_char_p]
        self._gr.gr_add_score.restype = ctypes.c_int
        self._gr.gr_add_score.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        self._gr.gr_top10.restype = ctypes.c_void_p
        self._gr.gr_free.argtypes = [ctypes.c_void_p]
        self._gr.gr_close.restype = None

    # ---- C 层 ----
    def load_level(self, lua_path):
        """加载 Lua 关卡，返回 dict。"""
        ptr = self._cr.cr_load_level(lua_path.encode("utf-8"))
        if not ptr:
            raise RuntimeError(f"cr_load_level failed: {lua_path}")
        s = ctypes.string_at(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_char)))
        self._cr.cr_free(ptr)
        return json.loads(s.decode("utf-8"))

    def pathfind(self, grid_flat, w, h, sx, sy, ex, ey):
        """A* 寻路，返回 [(x,y),...] 列表。grid_flat: 0=可走,1=障碍。"""
        arr = (ctypes.c_int * len(grid_flat))(*grid_flat)
        out = (ctypes.c_int * 400)()
        n = self._cr.cr_pathfind(arr, w, h, sx, sy, ex, ey, out, 400)
        if n < 0:
            return []
        return [(out[i * 2], out[i * 2 + 1]) for i in range(n)]

    def now_ns(self):
        return self._cr.cr_now_ns()

    # ---- Rust 层 ----
    def enemy_step(self, ex, ey, tx, ty, base_spd, slow_factor, dt):
        """敌人步进，返回 (new_x, new_y, reached)。"""
        out = (ctypes.c_float * 3)()
        self._rr.rr_enemy_step(ex, ey, tx, ty, base_spd, slow_factor, dt, out)
        return out[0], out[1], int(out[2])

    def next_target(self, cur_idx, path_len):
        return self._rr.rr_next_target(cur_idx, path_len)

    def beep(self, freq, dur_ms, wav_path):
        """合成方波 beep 到 WAV 文件。"""
        return self._rr.rr_beep_to_wav(ctypes.c_float(freq), dur_ms, wav_path.encode("utf-8"))

    # ---- Go 层 ----
    def lb_init(self, db_path=None):
        if db_path is None:
            db_path = _DB_PATH
        if self._gr.gr_init(db_path.encode("utf-8")) != 0:
            raise RuntimeError("gr_init failed")

    def lb_add_score(self, name, score, wave):
        return self._gr.gr_add_score(name.encode("utf-8"), score, wave)

    def lb_top10(self):
        ptr = self._gr.gr_top10()
        if not ptr:
            return []
        s = ctypes.string_at(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_char)))
        self._gr.gr_free(ptr)
        return json.loads(s.decode("utf-8"))

    def lb_close(self):
        self._gr.gr_close()
