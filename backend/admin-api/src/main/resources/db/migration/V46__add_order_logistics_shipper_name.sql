-- =====================================================================
-- V46: 发货人落库（issue #3768，设计见 issue 正文「发货单」）
-- =====================================================================
-- ⚠️ 本文件原为 V45，因**版本号撞车**改名（issue #3812）：
--    同目录另有 V45__widen_order_items_quantity_to_decimal.sql（#3671，先合入），
--    两个同号迁移的执行顺序由 classpath 扫描顺序决定（MigrationRunner 按版本号数值排序，
--    javadoc 自述 getResources 曾实测返回逆序）⇒ 潜伏顺序不确定，违反该类硬约束。
--    改名安全：MigrationRunner 仅以文件名判「已执行」（applied.contains(filename)），
--    不校验已记录文件是否仍存在；V46 首跑为 `ADD COLUMN IF NOT EXISTS` 幂等空操作。
--    线上库会保留一条陈旧的 V45__add_order_logistics_shipper_name 记录（历史事实，不改写）。
--
-- 发货单是纸质凭据（拣货/打包/交接），纸面需要「发货人」栏（谁经手发的货）。
-- 此前 order_logistics 只有承运商 + 运单号 + 轨迹，**没有任何操作人留痕**
-- （audit_logs 也不覆盖订单/物流更新：全仓 recordLogAsync 仅 BriefingController 一处调用）。
--
-- 取值规则（两条写入路径共用）：
--   1) B 端发货页显式传入（默认预填当前登录人姓名，允许改成实际发货人）；
--   2) 传空时后端用 SecurityUser.userId 查 users.nickname 兜底
--      （agent 代发路径也带真实用户：order_manage 透传 X-User-Id）。
--
-- ⚠️ 必须 nullable：存量已发货订单历史上从未采集过发货人，加 NOT NULL 会让迁移失败，
--    或被迫回填假值。打印/展示时空值显示「-」。
-- =====================================================================

ALTER TABLE order_logistics ADD COLUMN IF NOT EXISTS shipper_name VARCHAR(64);

COMMENT ON COLUMN order_logistics.shipper_name IS
    '发货人姓名（发货单纸面「经手人」；B 端发货页填写，空则由后端按当前登录用户兜底；存量数据为 NULL）';
