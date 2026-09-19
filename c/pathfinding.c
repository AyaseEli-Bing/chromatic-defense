/* pathfinding.c — A* 寻路 + 高精度计时 + Lua 关卡加载
 * 编译见 build.sh
 */
#include "pathfinding.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdio.h>

/* ===== A* 寻路 ===== */
typedef struct {
    int x, y;
    int g, f;
    int parent;
} node_t;

static int heuristic(int x1, int y1, int x2, int y2) {
    int dx = abs(x1 - x2), dy = abs(y1 - y2);
    return (dx > dy) ? (14 * dy + 10 * (dx - dy)) : (14 * dx + 10 * (dy - dx));
}

int cr_pathfind(const int *grid, int w, int h,
                int sx, int sy, int ex, int ey,
                int *out_path, int max_len) {
    if (w <= 0 || h <= 0) return -1;
    if (sx < 0 || sx >= w || sy < 0 || sy >= h) return -1;
    if (ex < 0 || ex >= w || ey < 0 || ey >= h) return -1;
    if (grid[sy * w + sx] != 0 || grid[ey * w + ex] != 0) return -1;
    if (max_len < 2) return -1;

    int total = w * h;
    node_t *nodes = malloc(sizeof(node_t) * total);
    if (!nodes) return -1;
    int *open = malloc(sizeof(int) * total);
    if (!open) { free(nodes); return -1; }
    char *closed = calloc(total, 1);
    char *in_open = calloc(total, 1);
    if (!closed || !in_open) { free(nodes); free(open); free(closed); free(in_open); return -1; }

    for (int i = 0; i < total; i++) {
        nodes[i].x = i % w; nodes[i].y = i / w;
        nodes[i].g = nodes[i].f = 0x3fffffff; nodes[i].parent = -1;
    }

    int start = sy * w + sx, goal = ey * w + ex;
    nodes[start].g = 0;
    nodes[start].f = heuristic(sx, sy, ex, ey);
    int open_cnt = 0;
    open[open_cnt++] = start;
    in_open[start] = 1;

    static const int dx8[8] = {1, -1, 0, 0, 1, 1, -1, -1};
    static const int dy8[8] = {0, 0, 1, -1, 1, -1, 1, -1};
    static const int cost8[8] = {10, 10, 10, 10, 14, 14, 14, 14};

    int found = 0;
    while (open_cnt > 0) {
        /* 取 f 最小的节点（小规模网格直接线性扫描即可） */
        int best = 0;
        for (int i = 1; i < open_cnt; i++)
            if (nodes[open[i]].f < nodes[open[best]].f) best = i;
        int cur = open[best];
        if (cur == goal) { found = 1; break; }

        /* 从 open 移除 */
        open[best] = open[--open_cnt];
        in_open[cur] = 0;
        closed[cur] = 1;

        int cx = nodes[cur].x, cy = nodes[cur].y;
        for (int k = 0; k < 8; k++) {
            int nx = cx + dx8[k], ny = cy + dy8[k];
            if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
            int ni = ny * w + nx;
            if (grid[ni] != 0 || closed[ni]) continue;
            /* 对角线移动时禁止穿墙角 */
            if (k >= 4) {
                if (grid[cy * w + nx] != 0 || grid[ny * w + cx] != 0) continue;
            }
            int ng = nodes[cur].g + cost8[k];
            if (!in_open[ni] || ng < nodes[ni].g) {
                nodes[ni].g = ng;
                nodes[ni].f = ng + heuristic(nx, ny, ex, ey);
                nodes[ni].parent = cur;
                if (!in_open[ni]) { open[open_cnt++] = ni; in_open[ni] = 1; }
            }
        }
    }

    int result = -1;
    if (found) {
        /* 回溯路径 */
        int path[1024], pc = 0;
        int cur = goal;
        while (cur != -1 && pc < 1024) { path[pc++] = cur; cur = nodes[cur].parent; }
        /* 反转 + 写入 out_path（每节点占2个int） */
        if (pc * 2 <= max_len) {
            for (int i = pc - 1, j = 0; i >= 0; i--, j += 2) {
                out_path[j] = nodes[path[i]].x;
                out_path[j + 1] = nodes[path[i]].y;
            }
            result = pc;
        }
    }

    free(nodes); free(open); free(closed); free(in_open);
    return result;
}

/* ===== 高精度计时 ===== */
unsigned long long cr_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long long)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

void cr_free(void *ptr) { free(ptr); }
