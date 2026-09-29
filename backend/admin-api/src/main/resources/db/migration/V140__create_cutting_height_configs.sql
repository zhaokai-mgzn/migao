-- 裁高（定高）**租户级配置**（母单 #5161；设计单 `docs/design/cutting-height-config-and-terminal.md`）
--
-- ## 一句话
-- 商家「裁高配置」的持久化载体：**单行**租户配置（`items` / `rounding` 两个 JSONB）。
-- 口径：`裁剪高度(部位) = 成品高 + Σ(命中的增量项)`；命中**复用** `production_route_rules` 的
-- `trigger_kind` / `trigger_value` / `position` 触发口径（不新造第二套匹配实现）。
--
-- ## 为什么是 JSONB 而不是子表
-- 两列都是**整份替换**的配置（PUT 全量替换），没有「按项查询 / 按项外键 / 逐项并发改」的需求
-- ⇒ 子表只带来 join 与「半份配置」的中间态。项数是个位数到几十，JSONB 足够。
--
-- ## 缺行 = 用默认值（**不做开租播种**）
-- 默认种子（壁达现场弹窗那 7 项：包布折 0.08 / 包布孔 0.1 / 包纱折 0.08 / 包纱孔 0.1 /
-- 画线（**有项无值**）/ 布贴 0.015 / 纱贴 0.01）只在 Java **一处**
-- （`CuttingHeightConfigService` 的默认种子）；库里再种一份 = 第二份会漂的默认值。
--
-- ## 为什么没有 formulas 列（与设计单 §2.2 的差异，如实登记）
-- 设计单的 `formulas[]`（部位级可配表达式）需要**表达式求值器**，本版不做
-- ⇒ **不建死列**（建了但没人读 = 假承诺）。部位级的差异本版由 `items[].hit.position` 承载；
-- 表达式层登记为下一期（设计单 §5）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` ⇒ 第二遍净效果相同。
CREATE TABLE IF NOT EXISTS cutting_height_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    rounding JSONB NOT NULL DEFAULT '{"mode": "half_up", "digits": 3}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_cutting_height_configs_tenant
    ON cutting_height_configs (tenant_id)
    WHERE deleted = 0;
