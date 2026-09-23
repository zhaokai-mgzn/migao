-- 生产报工后端（issue #3995，M4-G-2）
-- 工序库 / 工艺路线模板 / 工序实例 / 报工记录 + 加工单二维码 token（扫码报工入口）。
-- 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线 / §4 计件 / §5 扫码报工闭环。
-- 确定性核心（工艺路线/完工判定/计件公式）见 ai-agent-service app/production/routing.py
-- 与 piecework.py（M4-G-1，issue #3993）——本迁移只落 DB 层，语义与之一致。

-- ── 工序库：工序分组（裁剪/车位/后道/其他）+ 按部位分设 + 计件单价 ──
CREATE TABLE IF NOT EXISTS production_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,                       -- 工序名（按部位分设：韩褶-布 / 韩褶-纱）
    group_name VARCHAR(16) NOT NULL DEFAULT '其他',  -- 车间工位分组：裁剪/车位/后道/其他
    position VARCHAR(16),                            -- 部位：布帘/纱帘/帘头/外帘（空=通用）
    unit VARCHAR(16) NOT NULL DEFAULT '米',           -- 计件单位：米/折/幅/孔/套/个
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 计件单价（元/单位）
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,   -- 必完工序：此工序全部完成后才可打包/自动完工
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,  -- 生产开始标记：首工序报工触发订单进入生产中
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- active / disabled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operations_tenant_name
    ON production_operations (tenant_id, name)
    WHERE deleted = 0;
COMMENT ON TABLE production_operations IS '生产工序库：分组（裁剪/车位/后道/其他）+ 按部位分设 + 计件单价（0 元工序也建行，便于报工排线）';
COMMENT ON COLUMN production_operations.is_must_finish IS '必完工序：全绿才可打包；实例上全绿 → 订单自动 completed（issue #3995）';
COMMENT ON COLUMN production_operations.is_start_marker IS '生产开始标记：该工序报工即视为订单进入生产中';

-- ── 工艺路线模板：部位 × 工艺 → 工序名序列（JSONB）──
CREATE TABLE IF NOT EXISTS production_routings (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    curtain_type VARCHAR(16) NOT NULL,               -- 部位/帘种：布帘/纱帘/帘头
    craft VARCHAR(16) NOT NULL,                      -- 工艺：韩褶/打孔/四爪钩/穿杆/平幔
    operations JSONB NOT NULL DEFAULT '[]',          -- 工序名序列（有序数组），与 routing.py ROUTINGS 同构
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_routings_tenant_type_craft
    ON production_routings (tenant_id, curtain_type, craft)
    WHERE deleted = 0;
COMMENT ON TABLE production_routings IS '工艺路线模板：部位×工艺 → 基准工序序列（条件工序/定型开关由实例化时按特殊选项插入）';

-- ── 工序实例：加工单 × 部位 × 工序（应做数量/单价/系数 + 报工进度）──
CREATE TABLE IF NOT EXISTS processing_position_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    position_name VARCHAR(32) NOT NULL,              -- 部位：布帘/纱帘/帘头/外帘
    seq INT NOT NULL DEFAULT 0,                      -- 部位内工序顺序
    operation_name VARCHAR(64) NOT NULL,
    group_name VARCHAR(16),                          -- 与工序库同口径（裁剪/车位/后道/其他）
    unit VARCHAR(16),
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,            -- 应做数量（= 算料引擎输出，报工只确认不心算）
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 实例快照单价（调价不影响历史报工）
    factor NUMERIC(6,2) NOT NULL DEFAULT 1,          -- 特殊选项计件系数（如 一分二 ×1.7）
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,   -- 必完工序（全绿 → 订单自动完工）
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending 待做 / done 已报工
    done_qty NUMERIC(12,2) NOT NULL DEFAULT 0,       -- 合格累计数量（返工/报废不累加）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_position_operations_po
    ON processing_position_operations (processing_order_id, position_name, seq)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_position_operations_tenant
    ON processing_position_operations (tenant_id, status);
COMMENT ON TABLE processing_position_operations IS '工序实例：加工单×部位×工序（应做数量/单价/系数/必完标记/报工进度），扫码报工的推进单元';
COMMENT ON COLUMN processing_position_operations.status IS '报工状态：pending 待做 / done 已报工（合格数量>0 的正常报工即置 done）';
COMMENT ON COLUMN processing_position_operations.done_qty IS '合格累计数量：仅 work_type=normal 且合格数>0 时累加（返工/报废不累加）';

-- ── 报工记录：一次扫码同时推进进度 + 记录个人计件 ──
CREATE TABLE IF NOT EXISTS production_work_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    operation_id VARCHAR(64) NOT NULL,               -- 工序实例 id（processing_position_operations.id）
    operation_name VARCHAR(64) NOT NULL,
    worker_id VARCHAR(64),
    worker_name VARCHAR(64),
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,            -- 报工数量
    qualified_qty NUMERIC(12,2) NOT NULL DEFAULT 0,  -- 合格数量（计件按合格数量）
    work_type VARCHAR(16) NOT NULL DEFAULT 'normal', -- 报工三态：normal 正常 / rework 返工 / scrap 报废
    work_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_work_logs_po
    ON production_work_logs (processing_order_id, operation_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_work_logs_worker_date
    ON production_work_logs (tenant_id, worker_name, work_date)
    WHERE deleted = 0;
COMMENT ON TABLE production_work_logs IS '报工记录（明细不可变）：报工三态 normal/rework/scrap；计件 = Σ(合格数量×单价×系数)，排除返工/报废；单工序一人制';
COMMENT ON COLUMN production_work_logs.work_type IS '报工三态：normal 正常计件 / rework 返工（不计件不累加）/ scrap 报废（不计件不累加）';

-- ── 加工单二维码 token（扫码报工入口；token 化、可撤销）──
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS qr_token VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_qr_token
    ON processing_orders (qr_token)
    WHERE deleted = 0 AND qr_token IS NOT NULL;
COMMENT ON COLUMN processing_orders.qr_token IS '加工单二维码 token（32 位 UUID 去横线）：扫码报工入口，打印在加工单上；软删后 token 释放可复用';
