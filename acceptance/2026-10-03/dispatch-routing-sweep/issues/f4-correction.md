
---

## ⚠️ 前提更正（2026-10-03 08:10 +08，由 F4 修复包读源证伪后回填）

**原文写的「改 `db/init/schema.sql` 的逐租户种子块」是错的**（照字面做会：既修不到新租户、又当场弄红既有判据）。读源实证：

1. `schema.sql` 的逐租户种子块（`rr-v72-*` / `opp-v72-*` / `rt-v72-*`）**只在 DB 首次 bootstrap 时生效一次** —— `MigrationRunner` 按**文件名**记账（`schema_migrations.version='schema.sql'`，`applied.contains` 即 `continue`）⇒ 它只覆盖**建库那一刻已存在的租户**，**今天新开的租户走不到它**。
2. 今天新开租户真正被应用的是 Java：`RegistrationService.applyProductionSeedTemplate` → `ProductionSeedTemplateService.applyTemplate`（`planRouteRules`），其中特殊选项条件工序来自模板 **`production-templates/curtain/seed.json` 的 16 条 `option_routings`**，而该方法给它们**写死 `position = null`**。
3. 这些规则引用的工序**只有布帘变体** ⇒ `variantNameOf(逻辑名,'纱帘',catalog)==null` ⇒ `missing_operations` ⇒ 就是本单的 fail-closed 报错。
4. **反证**（已实测）：给规则补 `position='布帘'` ⇒ 纱帘单上 `rulePositionMatches` 走 `continue`（不插）⇒ 恢复正常；布帘单仍插 `花边-布`。

**因此修法改判为**：修**今天新租户真正走的那条种子路径**（`seed.json` 的 `option_routings` 或 `planRuleRules` 带位），**schema.sql 镜像只在校验强制要求时同步**，**归档迁移 V71/V72 保持逐字节冻结**；**不做**存量租户迁移（用户明示排除 ⇒ 存量卡单是有意接受的缺口）。

**教训（本仓同族）**：issue / 指令是**路标不是判据** —— 派活前先核「我要改的那块，真的是被应用的那块吗」。
