-- levels.lua — 塔防关卡配置
-- 被 C 的 cr_load_level 加载，返回一个 table，由 C 侧序列化为 JSON
-- 支持热重载：修改本文件后，游戏运行时调用 cr_load_level 即可重新加载

local M = {}

-- 地图：20x15 网格。0=空地(可建塔),1=路径,2=障碍
-- 手工设计一条 S 形路径
local function make_map()
    local w, h = 20, 15
    local map = {}
    for y = 1, h do
        map[y] = {}
        for x = 1, w do map[y][x] = 0 end
    end
    -- S形路径：入口(1,3) → 右到(16,3) → 下到(16,7) → 左到(4,7) → 下到(4,11) → 右到(20,11)出口
    local segments = {
        {{1,3},{16,3}},
        {{16,3},{16,7}},
        {{16,7},{4,7}},
        {{4,7},{4,11}},
        {{4,11},{20,11}},
    }
    for _, seg in ipairs(segments) do
        local p1, p2 = seg[1], seg[2]
        local x1,y1,x2,y2 = p1[1],p1[2],p2[1],p2[2]
        if x1 == x2 then
            for y = math.min(y1,y2), math.max(y1,y2) do map[y][x1] = 1 end
        else
            for x = math.min(x1,x2), math.max(x1,x2) do map[y1][x] = 1 end
        end
    end
    return map, w, h
end

local map, w, h = make_map()

-- 塔类型定义
-- 设计平衡：damage 越高 → fire_rate 越慢、cost 越高
M.towers = {
    {id="arrow",  name="箭塔",  cost=50,  range=3,   damage=8,  fire_rate=0.6, color="#4a9eff"},
    {id="cannon", name="炮塔",  cost=100, range=2.5, damage=25, fire_rate=1.2, color="#ff6b4a", splash=1.2},
    {id="magic",  name="魔法塔", cost=150, range=4,   damage=15, fire_rate=0.8, color="#b04aff", slow=0.5},
    -- 激光塔：所有塔中伤害最高、射程最远、攻击最慢、价格最贵
    -- 纯单体 DPS（无溅射/无减速），与炮塔、魔法塔形成清晰的角色分工
    -- 数值 rationale：damage 30 > cannon 25 > magic 15 > arrow 8
    --                  range 5 > magic 4 > arrow 3 > cannon 2.5
    --                  fire_rate 1.5（最慢，作为高伤的 trade-off）
    --                  cost 200（最贵，无金币上限后才能稳定使用）
    {id="laser",  name="激光塔", cost=200, range=5,   damage=30, fire_rate=1.5, color="#00ffff"},
}

-- 敌人类型
M.enemies = {
    {id="grunt",  name="小兵",   hp=30,  speed=1.0, reward=8,  color="#ff4444"},
    {id="runner", name="跑者",   hp=20,  speed=2.0, reward=12, color="#ffaa00"},
    {id="tank",   name="坦克",   hp=120, speed=0.5, reward=25, color="#8800ff"},
    {id="boss",   name="BOSS",   hp=500, speed=0.4, reward=200, color="#ff00ff", size=1.5},
}

-- 波次配置：每波指定敌人类型和数量
M.waves = {}
local wave_defs = {
    {delay=3,  spawns={ {type="grunt", count=8,  interval=0.8} }},
    {delay=5,  spawns={ {type="grunt", count=10, interval=0.6}, {type="runner", count=3, interval=1.0} }},
    {delay=5,  spawns={ {type="grunt", count=12, interval=0.5}, {type="runner", count=5, interval=0.7} }},
    {delay=8,  spawns={ {type="tank",  count=4,  interval=2.0}, {type="grunt", count=10, interval=0.4} }},
    {delay=8,  spawns={ {type="runner",count=10, interval=0.4}, {type="tank",  count=5, interval=1.5} }},
    {delay=10, spawns={ {type="grunt", count=20, interval=0.3}, {type="tank", count=6, interval=1.2}, {type="runner", count=8, interval=0.5} }},
    {delay=12, spawns={ {type="boss",  count=1,  interval=0}, {type="grunt", count=15, interval=0.4}, {type="tank", count=4, interval=1.5} }},
}

-- 把 map 转成 grid 数组(1=障碍,0=可建塔) + 路径坐标列表
-- 注意：C 侧 A* 需要 grid 中 0=可走,1=障碍。
-- 对塔防而言：敌人走"路径"(1)，塔建在"空地"(0)。
-- 所以 A* 的 grid 应该是：路径=0(可走)，空地+障碍=1(不可走)。
-- 即 grid[y][x] = (map[y][x]==1) ? 0 : 1
local grid = {}
for y = 1, h do
    grid[y] = {}
    for x = 1, w do
        grid[y][x] = (map[y][x] == 1) and 0 or 1
    end
end

M.width = w
M.height = h
M.start = {x=1, y=3}
M.goal  = {x=20, y=11}
M.grid  = grid          -- A* 用：0=路径(可走),1=不可走
M.map   = map           -- 渲染用：0=空地,1=路径,2=障碍
M.start_gold = 200
M.start_lives = 20
M.wave_defs = wave_defs

return M
