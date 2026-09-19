/* lua_loader.c — 通过 Lua C API 加载关卡脚本，遍历 table 输出 JSON
 * 体现 C ↔ Lua 互操作：lua_getfield / lua_geti / lua_next 遍历。
 */
#include "pathfinding.h"
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>

typedef struct {
    char *buf;
    size_t len, cap;
} sbuf_t;

static void sb_init(sbuf_t *s) { s->cap = 256; s->len = 0; s->buf = malloc(s->cap); s->buf[0] = 0; }

static void sb_put(sbuf_t *s, const char *str, size_t n) {
    if (s->len + n + 1 > s->cap) {
        while (s->len + n + 1 > s->cap) s->cap *= 2;
        s->buf = realloc(s->buf, s->cap);
    }
    memcpy(s->buf + s->len, str, n);
    s->len += n;
    s->buf[s->len] = 0;
}

static void sb_printf(sbuf_t *s, const char *fmt, ...) {
    char tmp[512];
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n > 0) sb_put(s, tmp, (size_t)n);
}

/* 递归序列化栈顶 table 为 JSON。数组部分用 [..]，哈希部分用 {..}。
 * 简化：仅处理 string/number/boolean/table，键为字符串或整数。
 */
static void serialize(lua_State *L, sbuf_t *s, int depth);

static void serialize_value(lua_State *L, sbuf_t *s, int depth) {
    int t = lua_type(L, -1);
    switch (t) {
        case LUA_TNIL:      sb_put(s, "null", 4); break;
        case LUA_TBOOLEAN:  sb_put(s, lua_toboolean(L, -1) ? "true" : "false", lua_toboolean(L, -1) ? 4 : 5); break;
        case LUA_TNUMBER:
            if (lua_isinteger(L, -1)) sb_printf(s, "%lld", (long long)lua_tointeger(L, -1));
            else sb_printf(s, "%.17g", lua_tonumber(L, -1));
            break;
        case LUA_TSTRING: {
            size_t ln; const char *str = lua_tolstring(L, -1, &ln);
            sb_put(s, "\"", 1);
            for (size_t i = 0; i < ln; i++) {
                char c = str[i];
                if (c == '"' || c == '\\') { sb_put(s, "\\", 1); sb_put(s, &c, 1); }
                else if (c == '\n') sb_put(s, "\\n", 2);
                else if (c == '\r') sb_put(s, "\\r", 2);
                else if (c == '\t') sb_put(s, "\\t", 2);
                else if ((unsigned char)c < 0x20) sb_printf(s, "\\u%04x", c);
                else sb_put(s, &c, 1);
            }
            sb_put(s, "\"", 1);
            break;
        }
        case LUA_TTABLE:
            serialize(L, s, depth + 1);
            break;
        default:
            sb_put(s, "null", 4);
            break;
    }
}

static void serialize(lua_State *L, sbuf_t *s, int depth) {
    /* table 在栈顶。用 luaL_len 判断是否为数组（连续整数键 1..n） */
    lua_Integer n = luaL_len(L, -1);
    int is_array = (n > 0);
    if (is_array) {
        /* 验证 1..n 都非 nil */
        for (lua_Integer i = 1; i <= n; i++) {
            lua_geti(L, -1, i);
            if (lua_isnil(L, -1)) { is_array = 0; lua_pop(L, 1); break; }
            lua_pop(L, 1);
        }
    }
    if (is_array) {
        sb_put(s, "[", 1);
        for (lua_Integer i = 1; i <= n; i++) {
            if (i > 1) sb_put(s, ",", 1);
            lua_geti(L, -1, i);
            serialize_value(L, s, depth);
            lua_pop(L, 1);
        }
        sb_put(s, "]", 1);
        return;
    }
    /* map：lua_next 标准遍历，栈: ..., table, key, value */
    sb_put(s, "{", 1);
    int first = 1;
    lua_pushnil(L);
    while (lua_next(L, -2)) {
        if (!first) sb_put(s, ",", 1);
        first = 0;
        /* 输出键：字符串直接用，数字转字符串 */
        if (lua_type(L, -2) == LUA_TSTRING) {
            size_t kl; const char *k = lua_tolstring(L, -2, &kl);
            sb_put(s, "\"", 1);
            sb_put(s, k, kl);
            sb_put(s, "\":", 2);
        } else {
            lua_pushvalue(L, -2);            /* 复制 key 到栈顶 */
            size_t kl; const char *k = lua_tolstring(L, -1, &kl);
            sb_put(s, "\"", 1);
            sb_put(s, k, kl);
            sb_put(s, "\":", 2);
            lua_pop(L, 1);                    /* 弹出 key 副本 */
        }
        serialize_value(L, s, depth);         /* 处理 value（栈顶） */
        lua_pop(L, 1);                        /* 弹出 value，保留 key 给下次 lua_next */
    }
    sb_put(s, "}", 1);
}

const char *cr_load_level(const char *lua_path) {
    lua_State *L = luaL_newstate();
    if (!L) return NULL;
    luaL_openlibs(L);

    if (luaL_loadfile(L, lua_path) != LUA_OK) {
        fprintf(stderr, "[C] load lua error: %s\n", lua_tostring(L, -1));
        lua_close(L);
        return NULL;
    }
    if (lua_pcall(L, 0, 1, 0) != LUA_OK) {
        fprintf(stderr, "[C] run lua error: %s\n", lua_tostring(L, -1));
        lua_close(L);
        return NULL;
    }
    if (lua_type(L, -1) != LUA_TTABLE) {
        fprintf(stderr, "[C] level script must return a table\n");
        lua_close(L);
        return NULL;
    }

    sbuf_t s; sb_init(&s);
    serialize(L, &s, 0);
    lua_close(L);
    return s.buf;  /* 调用方用 cr_free 释放 */
}
