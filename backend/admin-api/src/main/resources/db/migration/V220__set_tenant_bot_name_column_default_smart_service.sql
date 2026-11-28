-- V220__set_tenant_bot_name_column_default_smart_service.sql
--
-- 背景（issue #9328 = issue #9308 登记的第 ① 条边界；产品改名「米宝」→「智能客服」的最后一块）：
--   · #9304（main f9103e365）改**代码侧**兜底身份：`DEFAULT_BOT_NAME = "智能客服"`；
--   · #9311（V219）回填**存量行**（`UPDATE … WHERE bot_name = '米宝'`）；
--   · 本迁移改**列默认值**：'米宝' → '智能客服'（堵「新建配置行未显式给 botName」这个洞）。
--
-- ## 为什么必须有这一条（现取依据）
--   · 建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 里该列是最初的
--     `DEFAULT '小布'`，而 **V213** 把列默认值改成了 '米宝'
--     ⇒ 迁移链跑完之后，新建的 `tenant_ai_configs` 行若**没显式给** `botName`，落库仍是 '米宝'；
--   · 读取侧是「租户配置优先」：`backend/ai-agent-service/app/agents/agents/xiaobu.py` 的
--     `bot_name = data.get("botName") or DEFAULT_BOT_NAME` ⇒ 行里非空就照用，代码默认值压不过它
--     ⇒ 新租户的顾客照旧被退役品牌名问候。V219 只动**行值**，动不到**将来插入**的行。
--
-- ## 为什么只改 DEFAULT、不动任何数据
--   存量行（逐字 '米宝' 的那些）**已由 V219 处理**（带旧值谓词，第二遍 `UPDATE 0`）；
--   本迁移**一条 UPDATE 都没有** —— 再写一遍回填既冗余，又会把「谁在何时改的数据」搅成一团。
--   判据：`tests/unit_ci_workflows/test_v220_bot_name_column_default.py`（真库 INSERT 读数 + 链尾守卫）。
--
-- ## 与 V213 的关系（明确口径，防「回改」）
--   **本迁移覆盖 V213 的列默认值设置，不要回改 V213，也不要把这个默认值改回去。**
--   V213 是已注册的不可变历史迁移（`tests/unit_ci_workflows/migration_fingerprints.json` 按 sha256 冻结）
--   ⇒ 不许改它本体重写历史；要再改默认值，**新增一条更晚的迁移**。
--   静态判据盯的是「迁移链里**最后**一条设置该列默认值的迁移必须设成 '智能客服'」——
--   后人若加一条更晚的把默认值设回旧名，判据现取变红（不是注释里的君子协定）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   `ALTER COLUMN … SET DEFAULT` 幂等（第二遍把同一个默认值再设一遍，结果逐值相同）；
--   本迁移不 INSERT / 不 DELETE / 不 UPDATE ⇒ 无新增行、无删除行、无数据变化。
--
-- ## 全新库（initdb 后首次启动）也走到这里
--   建库脚本 `schema.sql` 的 `DEFAULT '小布'` 属**已发布内容**（同一份 sha256 账本冻结）⇒ 不回改；
--   `MigrationRunner` 先应用基线、再跑迁移链 ⇒ 全新库的列默认值同样由本迁移推到 '智能客服'。
--
-- ## 停止条件（fail-closed）
--   `information_schema.columns.column_default` 读到 `'智能客服'::character varying`，
--   且 `INSERT INTO tenant_ai_configs (tenant_id) VALUES (…) RETURNING bot_name` 落 '智能客服'。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '米宝';

BEGIN;

ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '智能客服';

COMMIT;
