-- =====================================================================
-- V45: 发货人落库（issue #3768，设计见 issue 正文「发货单」）
-- =====================================================================
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
