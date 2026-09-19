/* test_c.c — 测试 C 库 */
#include "pathfinding.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    /* 测试1: A* 寻路 */
    int w = 20, h = 15;
    int grid[300];
    /* 初始化全障碍 */
    for (int i = 0; i < 300; i++) grid[i] = 1;
    /* 开一条水平路径 y=3 */
    for (int x = 0; x < 20; x++) grid[3 * 20 + x] = 0;

    int path[200];
    int n = cr_pathfind(grid, w, h, 0, 3, 19, 3, path, 200);
    printf("[test] A* path nodes: %d\n", n);
    if (n > 0) {
        printf("[test] start=(%d,%d) end=(%d,%d)\n", path[0], path[1], path[(n-1)*2], path[(n-1)*2+1]);
    }

    /* 测试2: 计时 */
    unsigned long long t1 = cr_now_ns();
    for (volatile int i = 0; i < 1000000; i++);
    unsigned long long t2 = cr_now_ns();
    printf("[test] 1M iterations took %llu ns\n", t2 - t1);

    /* 测试3: Lua 关卡加载 */
    printf("[test] loading lua/levels.lua...\n");
    const char *json = cr_load_level("lua/levels.lua");
    if (json) {
        printf("[test] lua JSON length: %zu\n", strlen(json));
        printf("[test] first 200 chars: %.200s\n", json);
        cr_free((void*)json);
        printf("[test] lua load OK\n");
    } else {
        printf("[test] lua load FAILED\n");
    }
    return 0;
}
