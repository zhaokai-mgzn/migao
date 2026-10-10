-- V151__backfill_order_logistics_shipped_at.sql
--
-- 背景（issue #6276；**口径由用户 2026-10-10 裁定**）：
--   `order_logistics.shipped_at` = **首次发货时刻**。
--   这条裁定**排除了**另一种口径（「最近一次改物流时刻」）⇒ 已有非空值一律不得被覆盖，
--   填补只允许发生在「该行没有首次发货时刻」时。
--
-- ## 为什么会有 `shipped_at IS NULL` 的行（现取读数 + 读码）
--   真库读数（2026-10-03，`ai_customer_service`，与 issue #6276 正文逐字一致）：
--     `order_logistics` 全表 **29** 行、`shipped_at` 非空仅 **16** 行 ⇒ **13 行**为空。
--   根因（`backend/admin-api/src/main/java/com/migao/admin/service/OrderLogisticsWriter.java`）：
--   `shipped_at` **只在新建物流行的分支里写**；走 **update 分支**（已有物流行、再改物流/发货）
--   时**不补写** ⇒ 任何「台账行先存在（含测试/导入/建单期）、之后才发货」的单锚点永远为空。
--   （本迁移只搬**已经存在的事实**，不生成任何新事实。）
--
-- ## 为什么表内就有真值（不需要外部输入、不猜）
--   本表**三条建行路径**（`OrderLogisticsWriter.upsert` 的 insert 分支、
--   `OrderLogisticsService.createLogistics`、`OrderController.updateLogistics` 的建行分支）
--   都在建行那一刻写 `shipped_at = now()`；而 `created_at`（实体 `FieldFill.INSERT` + 列 `DEFAULT NOW()`）
--   就是**同一刻** —— 两者是同一事实的两种记法（现取：`OrderLogisticsMapper.selectByOrderId`
--   用 `ORDER BY created_at DESC` 取「最新物流行」，即 `created_at` 的既有语义就是「这一行何时建立」）。
--   ⇒ 这 13 行的首次发货时刻 = 该行自己的 `created_at`：取值是**列对列**的搬移，可复算、无需人工填。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   `UPDATE ... WHERE shipped_at IS NULL` ⇒ 第二遍匹配 0 行，结果与第一遍逐值相同；
--   只 `UPDATE`，不 `INSERT` / 不 `DELETE` / 不改列 ⇒ 无新增行、无删除行、无结构变更。
--
-- ## 非破坏性
--   不删列、不改既有列、不设 NOT NULL、不带 FK、不建索引。
--   已有非空值**一个字都不动**（谓词 `shipped_at IS NULL` 就是那条不变量）。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   ⚠️ 回滚**必然**抹掉本迁移补出的值，且**分不出**哪些行是它补的 ⇒ 只在确认要放弃
--   「首次发货时刻可查」这件事时执行。可复算的原值就是 `created_at`，重跑本迁移即可恢复：
--     UPDATE order_logistics SET shipped_at = NULL WHERE shipped_at = created_at;
--
-- ## 边界（照实登记）
--   · 软删行（`deleted = 1`）**也在射程内**：本行曾发生的首次发货是历史事实，
--     它不因后来被删而变得不存在；且与 `orders` 的 `deleted = 0` 谓词无耦合。
--   · `created_at` 与 `shipped_at` **同刻**（建行即发货）是既有代码的实装事实；本迁移不引入新语义。
--   · **不动** `orders.shipped_at`（V148）：那里 `IS NULL` 的 6 条是 V148 的**显式裁定**
--     （「不猜一个发货时刻」），动它 = 改变「发货后 N 天自动完成」这条腿的射程 ⇒ 属另一件事，另需裁定。

BEGIN;

UPDATE order_logistics
   SET shipped_at = created_at
 WHERE shipped_at IS NULL
   AND created_at IS NOT NULL;

COMMIT;
