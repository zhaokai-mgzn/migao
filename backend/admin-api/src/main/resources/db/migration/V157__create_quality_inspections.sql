-- 质检记录（**成品帘级**）—— issue #5652 的第一刀
--
-- ## 一句话
--   新建**质检记录**载体：一行 = **一件成品帘**（`order_item_id`）× 检验人 × 检验时刻 ×
--   **判定**（合格 / 返工 / 报废）× **不合格原因**（判定 ≠ 合格 时必填）。
--
-- ## 🔴 口径（用户 2026-10-16 逐字裁定，本表**不得**偏离）
--   · **质检颗粒度 =「是按成品帘来检查的」**：一条记录 = 一件成品帘（`order_item_id` 级），
--     **不**逐工序、**不**逐工序完工检 ⇒ 本表**没有** `operation_id` 列（有意不加）。
--   · **录入者 =「B 独立质检员」**：判定由**质检员**录入；`inspector_id` / `inspector_name`
--     是**检验人**，由服务端从 `SecurityContext` 解（body 伪造不了）。
--   · **两套口径并存、互不覆盖**：报工（`production_work_logs`）是**数量事实**
--     （`qty` / `qualified_qty` / `work_type`），本表是**质检判定**。本表**不重算**报工数量、
--     **不**改写任何报工行；报工侧也**不**读本表。质检**不参与计件**
--     （返工/报废不计件是 `production_work_logs.work_type` 的既有口径，本表一个字都没碰）。
--
-- ## 为什么建新表（而不是给 production_work_logs 加列）
--   `production_work_logs` 是**冻结契约**（表注逐字「报工记录（明细不可变）」）：
--   一行 = 一次**数量**报工，粒度是**工序实例**；而质检的粒度是**成品帘**、且**不是**数量记录
--   ⇒ 往冻结契约上塞一个不同粒度的判定，会让两个口径在一张表里互相污染（本单的红线）。
--
-- ## 判定取值域（三态，与报工三态**同名不同物**）
--   `pass` 合格 / `rework` 返工 / `scrap` 报废。取值形态**复用**报工侧既有习惯（小写 ASCII 单词）
--   ⇒ 两端的枚举习惯一致，但语义面**各自独立**（报工 `work_type` = 这一笔报的是什么货；
--   质检 `inspection_result` = 这一件成品帘判了什么）。
--   **DB 不设 CHECK 约束**（与 `production_work_logs.work_type` 同款：约束在服务层
--   `QualityCheckService.RESULTS`，错误码 `VALIDATION_ERROR` + 逐值文案）——
--   保持与既有列同构，避免同一件事两处实现。
--   `reason`：判定 = `pass` 时可为 NULL；判定 ≠ `pass` 时**服务层必填**（缺 ⇒ 422，不静默存）。
--
-- ## 幂等 / 可重复执行
--   `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` ⇒ 第二遍是 no-op。
--   本迁移**不写数据**、不改任何既有表 ⇒ 无可回滚的数据面
--   （回滚 = 手工 `DROP TABLE quality_inspections;`，本项目无 rollback 文件约定，同 V155）。
--
-- ## 无唯一约束（**有意**）
--   同一件成品帘**允许多条**质检记录：返工后重检是**正常业务**（一条 = 一次检验事实）。
--   「当前判定」由读面**按 `inspected_at` 最新一条**给出，不由唯一索引表达
--   （加唯一约束会把「重检」变成写失败，并让历史判定被覆盖 —— 与「记录」语义相反）。
CREATE TABLE IF NOT EXISTS quality_inspections (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    order_item_id VARCHAR(64) NOT NULL,                -- 一件成品帘（order_items.id）
    position_name VARCHAR(128),                        -- 成品帘展示名（快照，读时从工序实例解；解不到为 NULL）
    inspector_id VARCHAR(64) NOT NULL,                 -- 检验人（独立质检员，服务端从 SecurityContext 解）
    inspector_name VARCHAR(64),
    inspection_result VARCHAR(16) NOT NULL,            -- 三态：pass/rework/scrap
    reason VARCHAR(500),                               -- 不合格原因：判定 ≠ pass 时**服务层必填**
    inspected_at TIMESTAMP WITH TIME ZONE NOT NULL,    -- 检验时刻（业务时钟单点 BusinessClock，+08）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 读面主路径 = 「这件成品帘的质检记录」（按时间倒序取最新一条为当前判定）
CREATE INDEX IF NOT EXISTS idx_quality_inspections_item
    ON quality_inspections (tenant_id, order_item_id, inspected_at)
    WHERE deleted = 0;
-- 读面辅路径 = 「这张加工单的质检记录」
CREATE INDEX IF NOT EXISTS idx_quality_inspections_po
    ON quality_inspections (tenant_id, processing_order_id)
    WHERE deleted = 0;

COMMENT ON TABLE quality_inspections IS
    '质检记录（成品帘级，issue #5652）：一行 = 一件成品帘（order_item_id）× 检验人 × 检验时刻 × 判定（pass/rework/scrap）× 不合格原因（判定≠pass 时必填）。'
    '颗粒度 = **成品帘**（用户 2026-10-16 裁定「是按成品帘来检查的」）⇒ 本表**没有** operation_id 列（不逐工序）。'
    '**两套口径并存**：报工表是数量事实、本表是质检判定 —— 互不覆盖、互不重算，质检不参与计件。';
COMMENT ON COLUMN quality_inspections.order_item_id IS '一件成品帘（order_items.id）：质检的**唯一颗粒度**（用户裁定「是按成品帘来检查的」）';
COMMENT ON COLUMN quality_inspections.inspection_result IS '质检三态：pass 合格 / rework 返工 / scrap 报废；取值域由服务层 QualityCheckService.RESULTS 裁（与 production_work_logs.work_type 同名不同物）';
COMMENT ON COLUMN quality_inspections.reason IS '不合格原因：判定 ≠ pass 时**必填**（缺 ⇒ 422 具名报错，绝不静默存）；pass 时可为 NULL';
COMMENT ON COLUMN quality_inspections.inspector_id IS '检验人（独立质检员）：服务端从 SecurityContext 解，body 里的同名字段无效（与报工身份同款纪律）';
COMMENT ON COLUMN quality_inspections.inspected_at IS '检验时刻：取业务时钟单点 BusinessClock（Asia/Shanghai）—— 不使用无参 now()（issue #3802 / BusinessClockSourceGuardTest）';
