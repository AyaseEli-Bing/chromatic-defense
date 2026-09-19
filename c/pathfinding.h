#ifndef PATHFINDING_H
#define PATHFINDING_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A* 寻路：返回路径节点数（每节点2个int：x,y），失败返回 -1。
 * grid: 网格，0=可走，1=障碍。w/h 为宽高。
 * out_path: 输出缓冲区，max_len 为其容量（int 个数）。
 */
int cr_pathfind(const int *grid, int w, int h,
                int sx, int sy, int ex, int ey,
                int *out_path, int max_len);

/* 高精度计时：返回纳秒时间戳（单调钟） */
unsigned long long cr_now_ns(void);

/* Lua 关卡加载：返回 JSON 字符串（调用方用 cr_free 释放），失败返回 NULL */
const char *cr_load_level(const char *lua_path);

void cr_free(void *ptr);

#ifdef __cplusplus
}
#endif

#endif
