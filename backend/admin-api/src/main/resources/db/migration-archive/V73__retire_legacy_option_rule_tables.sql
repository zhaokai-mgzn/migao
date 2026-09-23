-- 旧规则表退场（**软删，表先不 DROP**）—— issue #4459 = 母单 #4423 的 P2b
--
-- ## 一句话
-- 把 `production_option_routings` / `production_option_factors` 的活跃行软删为 0：
-- 自本迁移起，**唯一**的规则真值源是 `production_route_rules`。
--
-- ## 🔴 为什么本段不在 V72（原文见 V72 的 ⑥ 段注释）
-- V72（P2a / #4432）原本把这两条 UPDATE 写在自己里，**主会话复核后移出**：
-- 当时 Java 侧**仍在读**这两张旧表（`ProductionOperationQueryService.optionRoutings` /
-- `optionFactors` → `ProcessingOrderService` 插条件工序 + 算计件系数），而**消费路径切换**
-- 在 P2b。⇒ 若 V72 先把旧行软删、而 Java 还没切过去：**条件工序不会插入、计件系数退回 1.0**
-- ⇒ **少发工人钱**（#4230「静默黑洞」同族形态）。
--
-- ⇒ **软删必须与「消费路径切到新结构」同一 PR 原子发布**（本迁移与 #4459 的 Java 改动同 PR）。
--    两条 SQL 的原文逐字取自 V72 的 ⑥ 段注释（未做任何改写）。
--
-- ## 为什么迁移号是 V73（不是改 V72）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记、已应用的文件**整份跳过**
-- ⇒ 改 V72 只对全新库生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）。
-- ⇒ 一切增量都走新文件。
--
-- ## 幂等（判据 16）
-- `WHERE deleted = 0` ⇒ 重复执行是空操作（第二次匹配 0 行）；`updated_at` 只在真改行时推进。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- UPDATE production_option_routings SET deleted = 0, updated_at = NOW() WHERE id LIKE 'por-%';
-- UPDATE production_option_factors  SET deleted = 0, updated_at = NOW() WHERE id LIKE 'pof-%';
-- ```
-- ⚠️ 回滚**必须与「Java 读面回退到旧两表」同时做**：只把行复活而 Java 已切到新结构 ⇒
-- 旧行无人读（无害但无用）；只把 Java 回退而旧行仍软删 ⇒ **少发工人钱**。
--
-- ## 与 P2a 守卫的关系
-- `tests/unit_ci_workflows/test_routing_model_p2_consumers.py` 的两条判据在这里**同时**成立：
-- · `test_v72_must_not_retire_legacy_rule_tables`（V72 不得软删）—— 继续绿（V72 未动）；
-- · `test_old_rule_tables_soft_deleted`（本单的 C-1，从 xfail 转正）—— 由本文件满足。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 旧规则表退场：活跃行软删为 0（**表本身不 DROP** —— 可回滚，DROP 留待确认零消费者后的独立迁移）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- SQL 原文逐字取自 V72 的 ⑥ 段注释。
UPDATE production_option_routings SET deleted = 1, updated_at = NOW() WHERE deleted = 0;
UPDATE production_option_factors   SET deleted = 1, updated_at = NOW() WHERE deleted = 0;

COMMENT ON TABLE production_option_routings IS
    '特殊选项 → 条件工序（V59 建）。**V73（issue #4459 = 母单 #4423 P2b）起活跃行 = 0**：'
    '规则真值源已收口到 production_route_rules（V71 建表 / V72 扩列），本表**只保留历史行**'
    '（软删、不 DROP ⇒ 可回滚）。DROP 留待确认零消费者后的独立迁移。';
COMMENT ON TABLE production_option_factors IS
    '特殊选项 → 计件系数（V59 建）。**V73（issue #4459 = 母单 #4423 P2b）起活跃行 = 0**：'
    '系数档已搬进 production_route_rules（action=''factor''，V72 搬迁），本表**只保留历史行**'
    '（软删、不 DROP ⇒ 可回滚）。DROP 留待确认零消费者后的独立迁移。';
