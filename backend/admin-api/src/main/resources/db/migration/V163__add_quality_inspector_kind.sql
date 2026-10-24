-- V163__add_quality_inspector_kind.sql
--
-- issue #7162：工人端质检（扫水洗唛 → 报工页 → 录判定 → 生成「质检单」）。
--
-- 背景：质检记录此前**只**来自观星台员工（inspector_id = users.id，登录态 = 员工会话，
-- 权限码 production:inspect）。本轮工人端也能录判定，而工人是**另一套会话/授权路径**
-- （worker session，permissions 恒为 []）⇒ 只靠 inspector_id 分不清「这条是谁录的」。
--
-- 口径（用户 2026-10-17 逐字：「工人不能进入观星台，维持这个设计」）：
--   · employee = 观星台员工（生产管理 ▸ 质检记录页 / 作业单质检区）
--   · worker   = 工人端（H5 扫水洗唛后录判定；工人不需要、也不能进观星台）
--
-- 只加列、不改既有语义：存量行全部来自观星台 ⇒ 一律 employee（列默认值兜底，不回填历史）。
ALTER TABLE quality_inspections
    ADD COLUMN IF NOT EXISTS inspector_kind VARCHAR(16) NOT NULL DEFAULT 'employee';

COMMENT ON COLUMN quality_inspections.inspector_kind IS
    '检验人身份类别（V163 / issue #7162）：employee 观星台员工 / worker 工人端（工人 session）；存量行默认 employee。';
