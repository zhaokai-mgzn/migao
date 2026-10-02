-- V144 — 日报卡片面「proactive 四态」（issue #5955）
--
-- ## 一句话
-- `daily_briefings` 加一列 `proactive_status`（JSONB）：**逐规则**的接线四态
-- （`wired` / `not_wired` / `not_enabled` / `incomplete` + 原因 + 边界），由 ai-agent 侧的
-- **确定性引擎**（`backend/ai-agent-service/app/briefing/proactive.py::proactive_status`）
-- 在 `sanitize_briefing` **之后**算出并原样透传，admin-api 只负责**落库 + 透出**，不做任何改写。
--
-- ## 为什么**要**落库（本单的持久化判断，理由逐条）
-- ① 它是**引擎当次输出的原样**：同一行数据同时冻结了「结论」与「给出这个结论时的规则集/边界」。
--    卡片面只读它，不做任何二次计算 ⇒ 三端不存在第二份口径（引擎重算 = 第二份口径）。
-- ② **不落库就只能靠重算**，而重算有两处硬伤：admin-api 侧重算要在 Java 里复刻引擎四态判据
--    （同一判据两份实现）；ai-agent 侧重算要新开一条内部端点（读面挂在生成链路上）。
--    两者都比「多一列 JSONB」贵，且都会引入新的漂移面。
-- ③ 语义与同表的 `content` / `source_snapshot` 同族：三者都是**那一天的快照事实**
--    （`content` = 当天 LLM 组织结果、`source_snapshot` = 当天确定性输入、
--    `proactive_status` = 当天确定性结论）⇒ 归一张表，不另立第二处存储。
--
-- ## 为什么是**可空**、存量行**不回填**
-- 本列面世之前生成的简报**从未采集过**这个事实 ⇒ 留 NULL（= **未采集**，不是「没问题」）。
-- 回填就是拿今天的规则集去冒充那一天没算过的结论 —— 与 `V142` 的 `created_by` 同口径。
-- 消费方（`GET /api/admin/briefing/today`）对 NULL 的语义 = 「本行没有这个事实」，
-- 前端据此**不渲染**该面板（未知 ≠ 没问题；也不许渲染成空壳冒充「已检查」）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN`（幂等）⇒ 第二遍净效果相同。
--
-- ## 不带 NOT NULL / 不带默认值
-- NOT NULL 会逼出一个编造的值（`{}` 或 `{}`），而「空对象」在卡片面上正是最该被禁止的形态
-- —— 它长得像「已检查、没有问题」。

ALTER TABLE daily_briefings ADD COLUMN IF NOT EXISTS proactive_status JSONB;

COMMENT ON COLUMN daily_briefings.proactive_status IS
    '逐规则接线状态（issue #5955）= ai-agent 引擎 proactive_status(snapshot) 的**原样**输出：{rule_id: {rule_id, rule_name, status, reason, missing, gaps, caveats}}，status ∈ {wired, not_wired, not_enabled, incomplete}；不变式 reason is None ⟺ status=wired。NULL = 未采集（本列面世前的存量行）⇒ 卡片面**不渲染**该面板（未知 ≠ 没问题）。由 admin-api 在生成时从 ai-agent 生成返回体取出后原样落库，**不在 admin-api 侧重算**（重算 = 第二份口径）';
