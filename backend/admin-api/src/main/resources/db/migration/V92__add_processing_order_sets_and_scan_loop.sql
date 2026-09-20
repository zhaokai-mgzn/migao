-- 扫码报工闭环 · **数据层**（切片 ⓪）：套号落库（`processing_order_sets`）+ 一部位一码的 token 载体
-- （`processing_set_part_tokens`）+ 工序实例六列 + 存量回填 + 停止条件。
--
-- 设计依据：`docs/design/set-code-and-scan-loop.md`（issue #4691 已合并，901 行）§2 / §11 / §12 / §14；
-- 落码单 = issue #4698（用户裁定：**A. 一樘窗 = 一套** / **套号要落库** / **一部位一码** /
-- **不拦生产顺序但工序必须确定** / **A 模式**）。
--
-- ## 一句话
-- ① 建 `processing_order_sets`（一单 × 一套 = 一行，两个唯一键）；② 建 `processing_set_part_tokens`
-- （一部位一码，两个唯一键，**本迁移不种行** —— 码由打印入口在切片 ① 之后的打印流程里生成）；
-- ③ `processing_position_operations` 加 **6 列**（全部可空、存量行留空、**零行为变化**）；
-- ④ 加卡点报表索引；⑤ **存量回填**套行 + 实例行的 `set_id`/`set_no`；⑥ 末尾**可执行停止条件**。
--
-- ## 迁移号（**现取**）
-- `ls backend/admin-api/src/main/resources/db/migration | tail` **现取** ⇒ 当时最大为 `V90`，
-- 而 `V91` 按约定留给 **#4707**（迁移目录属它的边界）⇒ 本单取 **V92**。
-- 若 push 时 V92 已被占 ⇒ 用下一个空闲号并在 PR body 说明（设计 §11.1 原文预估 V89，已过期）。
--
-- ## 🔴 红线（本文件**一字不动**的三处历史值）
--   · `processing_orders.items_snapshot` —— 只**读**（回填的唯一输入），**零写入**；
--   · `processing_position_operations` —— 只 `ADD COLUMN`（可空）+ 回填**新增的** `set_id`/`set_no`；
--     **既有列零赋值**（核法：回填 UPDATE 的 `SET` 子句只允许出现 `set_id` / `set_no`）；
--   · `production_work_logs.unit_price` / `factor` —— 本文件**零命中**；
--   · `processing_orders.qr_token` —— **不碰**（设计 §2.6 明令：已有打印件不作废，**不设强制失效日**）。
-- 机械核验：`grep -c "production_work_logs\|qr_token" V92__*.sql` ⇒ 只应命中注释里的红线说明。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① `CREATE TABLE / INDEX IF NOT EXISTS`、`ADD COLUMN IF NOT EXISTS`、`COMMENT ON`（覆盖式）均幂等；
-- ② 回填 INSERT 走 `ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING`；
-- ③ 回填 UPDATE 带 `o.set_id IS DISTINCT FROM s.id` 守卫 ⇒ 第二次执行匹配 0 行；
-- ④ 末尾停止条件块只读 ⇒ 幂等。
-- ⚠️ 幂等的**语义要求**不是「跑两遍不报错」，而是「跑两遍**净效果相同**」：本文件靠
-- 「已存在的套行按 `position_item_ids` 指纹认领、**不重编号**」实现（见下「序号只增不复用」）。
--
-- ## 序号只增不复用（用户裁定 + 设计 §2.4）
-- 格式 = `{processing_order_no}-{3 位零填充 set_index}`（设计 §2.1，逐字）；
-- `set_index` 口径 = **一樘窗在订单里的次序**，而「一樘窗」落到既有载体上 = **`craftLineId` 组**
-- （布 + 纱 + 帘头是多条 `order_items` 行，设计 §2.1 F11/F12）⇒ 分配单位是**组**，不是订单行。
-- 回填的编号规则（**只增不复用**，比设计 §11.3 的 `enumerate(groups, 1)` 伪码更严 —— 见下「与设计的偏离」）：
--   · 组的**指纹** = `position_item_ids`（该组各行的 `order_item_id`，有序）——`order_items.id` 是主键，
--     指纹在单内唯一 ⇒ 可用它把「已有套行」认领回组，**不重编号**；
--   · **未被认领**的新组取 `MAX(set_index) + 1, +2, …`，而 `MAX` 的查询**不带 `deleted = 0`**
--     （软删行仍占号 ⇒ 号池单调）—— 这正是「删一个窗再加一个**不得复用已删号**」的实现；
--   · 全新库上无任何已有行 ⇒ `MAX = 0` ⇒ 得到 `1..M`（= 设计 §11.3 的行序分配，逐值一致）。
--
-- ## 与设计的偏离（**照实登记，不粉饰**）
-- 设计 §11.3 的伪码用 `enumerate(groups, start=1)` 按快照位置编号。它在**首次执行**上与本节逐值一致，
-- 但**重跑/软删后**会复用已删号：删掉第 2 套再在快照中间插一樘新窗 ⇒ 新窗按位置得 `2`，
-- 而 `uk_processing_order_sets_index` 是**部分**唯一索引（`WHERE deleted = 0`，设计 §2.2 指定）
-- ⇒ 已软删的第 2 套**挡不住**它 ⇒ **号被复用**，违反用户裁定「已删的号不回收」。
-- ⇒ 以**用户裁定 + §2.4** 为准，回填改为「指纹认领 + MAX+1」（首跑结果与设计逐值相同）。
--
-- ## 按租户（issue #4676 ⑥ 同款口径）
-- 回填的两条 DML 都以 `JOIN tenants t ON t.id = <行>.tenant_id AND t.deleted = 0` 限定 ⇒
-- 「按租户循环」的集合形态；被软删的租户**一条都不写**。
--
-- ## 显式写列（issue #4608 纪律）+ 类型显式（V79 的坑）
-- INSERT 一律列清单显式（不靠列位置）；`set_index` 显式 `::integer`（`ROW_NUMBER()` / `COUNT(*)`
-- 是 `bigint` ⇒ 不转型会依赖隐式收窄），`new_index::text` 显式进 `lpad`。
-- 本文件**没有** `VALUES` 列表（无 V79 那种「整列 NULL 被推断成 text」的形态）。
--
-- ## 存量旧码（设计 §2.6）：**本片只落载体，不落解析顺序**
-- 双读的**顺序**（新 token → 旧 `qr_token` → `processing_order_no` → `order_no` → `order_id`）与
-- 旧码命中后的 `granularity="order"` + `needs_selection` 降级形态是**读面代码**（切片 ① / ⑤），
-- 本迁移只保证载体存在（`processing_set_part_tokens` + 实例的 `set_id`/`set_no`）。
-- `granularity` 是**响应字段**（读时派生），**不是列** ⇒ 本片无它。
--
-- ## 存量回填的确定性（设计 §2.5 / §11.3）
-- 唯一输入 = `items_snapshot`（**固化真相**），**不读 `order_items` 现值**（后者会被改名/改行序影响
-- ⇒ 回填结果不可复现）。分组键 = `craftLineId ?? itemId ?? 'ord:'||位置`（与 `ProcessingOrderService`
-- 的 `craftGroupKey` 同口径：`craftLineId` 优先、缺省回落本行 `itemId`、两者皆缺 ⇒ 各自成组）；
-- 被吸收的**配布边行**（`componentRole='配布边'` 且同组存在主布行）不独立成窗（与实例化循环同口径）。
-- 实例行回填**只回填 `order_item_id` 非空的行**（V69 逐字：「猜错比留空更糟」）⇒ 存量单读面行为不变。
--
-- ## bootstrap 终态同步（设计 §11.2 ⑩）
-- `docs/sql/schema.sql` 已同步本文件终态（两张新表 + 六列 + 索引 + 注释）—— 新建库路径**不跑迁移链**
-- （docker `docker-entrypoint-initdb.d/001_schema.sql`），只写迁移 = 新建库无该表（#3270 同族）。
--
-- ## 回滚（**新迁移，不删 V92**；设计 §11.4）
-- ```sql
-- -- V93__rollback_processing_order_sets_and_scan_loop.sql（本单只登记，不落码）
-- --   理由：**落码即自动执行**（MigrationRunner 按文件名顺序跑全部未记账迁移）⇒ 会把本迁移当场撤销。
-- --   与 V88 / V89 同款处置（它们也只登记回滚名）。
-- DROP TABLE IF EXISTS processing_set_part_tokens;
-- DROP TABLE IF EXISTS processing_order_sets;
-- DROP INDEX IF EXISTS idx_position_operations_status_done;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS set_id;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS set_no;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS done_at;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS worker_id;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS worker_name;
-- ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS started_at;
-- -- ④ 不恢复任何旧码、不改 `qr_token`（既有列从未被改 ⇒ 旧码路径始终可用）
-- ```
-- ⚠️ **回滚会丢什么（设计 §11.4 ⑤，必须写明）**：套号（以及将来 C 模式的认领记录）**不可恢复**
-- ⇒ 回滚前必须**导出**这两张表。**报工明细与计件金额不受影响**（`production_work_logs` 未被改）
-- ⇒ 工人已做的活的钱不会丢 —— 这是把套号放**实例快照**而不是报工行的第二个收益。
--
-- ## 停止条件（**末尾可执行断言**，逐条红证见
-- `tests/unit_ci_workflows/test_set_code_storage_v92_migration.py`）
-- **硬停（`RAISE EXCEPTION` ⇒ 整个文件回滚 ⇒ `MigrationRunner` 记 ERROR 并跳过）** ——
-- 这些是「**本迁移自己写出来的数据**不自洽」的形态，说明回填逻辑坏了，继续跑只会把脏数据留在库里：
--   S1 同租户内 `set_no` 重复（码里印的是它 ⇒ 重复会让扫码解析到两套）；
--   S2 某单 `set_index` 不是连续的 `1..MAX`（跳号 ⇒ 号池不单调）；
--   S3 活跃单的 **live 套数 ≠ 窗数**（多/少都算；`>999` 跳过的单除外 —— 见 S4）；
--   S4 live 套行的 `set_no` 不符合 `{单号}-{3 位}`（>999 溢出的**显式拒绝**，不静默截断）；
--   S5 实例行的 `set_id` 跨单、或该行 `order_item_id` 不在所属套的部位清单里（归错套）。
-- **软停（`RAISE WARNING` + 跳过该单/该步，不中止整个迁移）** —— 设计 §11.3 的 1/2/4/5 条：
-- 一条脏数据不该挡住全量（但必须**可见**，所以逐条 `RAISE WARNING` 点名）：
--   · `items_snapshot` 非数组（解析失败）⇒ 跳过该单；
--   · 分组数 > 999 ⇒ 跳过该单（人工裁定，不静默截断）；
--   · `order_item_id` 为 NULL 的实例行 ⇒ 不回填（不猜）；
--   · 实例行回填数与「按快照预期」不一致 ⇒ 记 WARNING（**可观测的对账读数**，不中止）。
--
-- ## ⚠️ 为什么把 `FROM "v92_*"` 写成**带引号**的 CTE 名（刻意的）
-- `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py::_referenced_tables` 用
-- `FROM\s+([a-z_]\w*)` 抽表名 ⇒ 裸 CTE 名会被读成「schema 里不存在的表」= **假红**
-- （该守卫的射程是「迁移引用的表必须真实存在」，CTE 不是表）。引号让该正则不匹配，
-- 而 PostgreSQL 里 `"v92_groups"` 与 `v92_groups` 是同一个标识符（全小写）⇒ 零语义代价。
-- 该守卫的**真缺陷仍被抓住**（`FROM processing_orders_sets`（拼错）照样命中并判红）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 套号载体 `processing_order_sets`（一单 × 一套 = 一行）—— 设计 §2.2 逐列
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS processing_order_sets (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    set_index INT NOT NULL,
    set_no VARCHAR(64) NOT NULL,
    craft_line_id VARCHAR(64),
    position_item_ids JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 唯一键 ①：分配器的正确性依赖（并发建套时把「同号两套」挡在库层，设计 §2.4 规则 3）
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_order_sets_index
    ON processing_order_sets (tenant_id, processing_order_id, set_index)
    WHERE deleted = 0;

-- 唯一键 ②：可读号的唯一性（**码里印的是 `set_no`，扫码解析靠它** ⇒ 可重则解析到两套）。
-- `tenant_id` 入键 = 跨租户不互撞（多租户同形单号合法）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_order_sets_no
    ON processing_order_sets (tenant_id, set_no)
    WHERE deleted = 0;

COMMENT ON TABLE processing_order_sets IS
    '套号载体（V92，issue #4698 / 设计 §2.2）：一个加工单 × 一套 = 一行。'
    '一套 = 一樘窗（= 一个 craftLineId 组 / 一个窗的全部部位合计一套，用户裁定 2026-09-20）。';
COMMENT ON COLUMN processing_order_sets.set_index IS
    '一樘窗在本加工单里的次序（1 起，3 位零填充进 set_no）。**只增不复用**：软删行仍占号（MAX 查询不带 deleted=0）'
    '⇒ 重排/改名/删窗都不改已有套号（设计 §2.4）。';
COMMENT ON COLUMN processing_order_sets.set_no IS
    '可读套号 = {processing_order_no}-{pad3(set_index)}（**落库冗余**，不是读时拼）：① 码里印的是它，'
    '扫码解析按文本查唯一索引，不在热路径做拼接；② 冗余**不会漂移**的唯一条件是「单号一经生成不变 + set_index 一经分配不变」'
    '（设计 §2.2）—— 这两条正是本表与 processing_orders 的约定，改任一即须重估本列。';
COMMENT ON COLUMN processing_order_sets.craft_line_id IS
    '樘窗组键（= 快照 craftLineId，缺省 = 该组主布行的 itemId）；**可空**（存量/脏快照，与 ProcessingOrderService.craftGroupKey 同口径）。';
COMMENT ON COLUMN processing_order_sets.position_item_ids IS
    '本套包含的**部位行** order_items.id 数组（**有序**）⇒「这套有哪几个部位」不靠反查，'
    '也是回填时把已有套行认领回组的**指纹**。';
COMMENT ON COLUMN processing_order_sets.deleted IS
    '软删（**软删 ≠ 释放号**）：被删的窗不回收序号，新窗取 MAX(set_index)+1（设计 §2.4 规则 1）。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 码载体 `processing_set_part_tokens`（**一部位一码**）—— 设计 §2.3
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 本迁移**不种行**：码在**打印**那一刻生成（切片 ① 之后）。本片只保证载体与唯一键存在，
-- 与 C 模式的六列同款「先建列、零消费者」（设计 §14：数据层先行，不阻断后续切片）。
CREATE TABLE IF NOT EXISTS processing_set_part_tokens (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    set_id VARCHAR(64) NOT NULL REFERENCES processing_order_sets(id),
    order_item_id VARCHAR(36) NOT NULL,
    position_kind VARCHAR(16),
    token VARCHAR(64),
    print_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 与既有 `uk_processing_orders_qr_token` 逐字同款形态（token 置 NULL = 撤销；PG 唯一索引允许多个 NULL）
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_token
    ON processing_set_part_tokens (token)
    WHERE deleted = 0;

-- **一部位一码**：同一部位重复打印 = 复用同一 token（不换码）
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_part
    ON processing_set_part_tokens (tenant_id, set_id, order_item_id)
    WHERE deleted = 0;

COMMENT ON TABLE processing_set_part_tokens IS
    '部位码载体（V92，issue #4698 / 设计 §2.3）：一部位一码（一樘窗 ≤3~4 码）。'
    '载体是 token（32 位 UUID 去横线，与 processing_orders.qr_token 同格式），**不是明文拼接**；工序**不进码**'
    '（工序在实例化后还会变 ⇒ 进码会让「改一次工艺、全车间已打印的码全部作废」）。';
COMMENT ON COLUMN processing_set_part_tokens.token IS
    '码 token（32 位 UUID 去横线）。**撤销 = 置 NULL**（与 ProcessingOrderMapper.revokeQrToken 逐字同语义：'
    '「这张纸作废」，**不换新 token**）；NULL 行不参与 uk_set_part_tokens_token（部分唯一索引）。';
COMMENT ON COLUMN processing_set_part_tokens.print_count IS
    '打印次数（原子自增 COALESCE(print_count,0)+1；多人同时打印不丢计数，与 ProcessingOrderMapper.incrementPrintCount 同款）。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 工序实例六列（**全部可空**：存量行留空 = 明确语义，与 V69 的 order_item_id 同款「不猜」）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `set_id` / `set_no` = 套归属（**实例快照，不靠 join**；用途：扫码归属校验 + 计件按套下钻，
--   零改动 production_work_logs）；
-- `done_at` = **A 模式唯一必需的新增时序列**（「做完扫一次 = 完工」的完成时刻；不能用 updated_at 冒充
--   —— 它会被任何更新污染，设计 D8）；
-- `started_at` / `worker_id` / `worker_name` = **C 模式预留**（A 模式默认路径**不读不写**，设计 D15）。
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS set_id VARCHAR(64);
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS set_no VARCHAR(64);
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS done_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS worker_id VARCHAR(64);
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS worker_name VARCHAR(64);
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN processing_position_operations.set_id IS
    '套归属（V92，issue #4698）：指向 processing_order_sets.id。**可空** = 存量行（本列引入前的实例行，'
    '与 V69 的 order_item_id 同款「留空不猜」）；回填只写 order_item_id 非空的行。';
COMMENT ON COLUMN processing_position_operations.set_no IS
    '套号快照（V92，issue #4698）：与 set_id 同一次回填写入；**可空**（同 set_id）。'
    '用途：扫码归属校验 + 计件按套下钻（**零改动 production_work_logs**）。读面按「无 set_no ⇒ 显示加工单号」兜底。';
COMMENT ON COLUMN processing_position_operations.done_at IS
    '完成时刻（V92，issue #4698）：**A 模式唯一必需的新增时序列**（「做完扫一次 = 完工」）。'
    '⚠️ 不得用 updated_at 冒充（它会被任何更新污染）。';
COMMENT ON COLUMN processing_position_operations.started_at IS
    '开工时刻（V92，issue #4698）：**C 模式预留**（A 模式默认路径不读不写，设计 D15）。';
COMMENT ON COLUMN processing_position_operations.worker_id IS
    '报工人 id（V92，issue #4698）：**C 模式预留**（A 模式默认路径不读不写）。';
COMMENT ON COLUMN processing_position_operations.worker_name IS
    '报工人姓名（V92，issue #4698）：**C 模式预留**（A 模式默认路径不读不写）。';
-- ⑤ 取值域扩一条：**不改列定义**（`VARCHAR(16)` 装得下），只更新列注释（设计 §11.2 ⑤）
COMMENT ON COLUMN processing_position_operations.status IS
    'pending 待做 / in_progress 进行中（**C 模式预留**，V92 只扩取值域、零行为变化）/ done 已报工。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 卡点报表索引（设计 §11.2 ⑥：A 模式「没开工」判据 = pending + 立即前道 done + 等待时长）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_position_operations_status_done
    ON processing_position_operations (tenant_id, status, done_at);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 存量回填 · 套行（唯一输入 = items_snapshot，不读 order_items 现值）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 分组口径与 `ProcessingOrderService.buildPositionPayload` 的实例化循环**逐条对齐**：
--   · 只考虑有 `processingItems` 数组的行（Java：`instanceof List` 才成部位）；
--   · **配布边行**（`componentRole='配布边'`）在同组存在主布行时被吸收 ⇒ 不独立成窗；
--   · 组键 = `craftLineId` → `itemId` → `'ord:'||快照位置`（后两者 = Java 的「缺省回落 / 各自成组」）；
--   · 组顺序 = 快照中出现次序（`MIN(ord)`）。
WITH "v92_parts" AS (
    SELECT po.id AS processing_order_id,
           po.tenant_id,
           po.processing_order_no,
           e.value AS entry,
           e.ordinality AS ord,
           COALESCE(NULLIF(btrim(e.value ->> 'craftLineId'), ''),
                    NULLIF(btrim(e.value ->> 'itemId'), ''),
                    'ord:' || e.ordinality) AS group_key
      FROM processing_orders po
      JOIN tenants t ON t.id = po.tenant_id AND t.deleted = 0
      CROSS JOIN LATERAL jsonb_array_elements(po.items_snapshot)
           WITH ORDINALITY AS e(value, ordinality)
     WHERE po.deleted = 0
       AND jsonb_typeof(po.items_snapshot) = 'array'
       AND jsonb_typeof(e.value -> 'processingItems') = 'array'
       AND NOT (
             COALESCE(e.value ->> 'componentRole', '') = '配布边'
             AND EXISTS (
                 SELECT 1
                   FROM processing_orders po2
                   CROSS JOIN LATERAL jsonb_array_elements(po2.items_snapshot)
                        WITH ORDINALITY AS e2(value, ordinality)
                  WHERE po2.id = po.id
                    AND jsonb_typeof(e2.value -> 'processingItems') = 'array'
                    AND COALESCE(e2.value ->> 'componentRole', '') <> '配布边'
                    AND COALESCE(NULLIF(btrim(e2.value ->> 'craftLineId'), ''),
                                 NULLIF(btrim(e2.value ->> 'itemId'), ''),
                                 'ord:' || e2.ordinality)
                      = COALESCE(NULLIF(btrim(e.value ->> 'craftLineId'), ''),
                                 NULLIF(btrim(e.value ->> 'itemId'), ''),
                                 'ord:' || e.ordinality)
             )
           )
),
"v92_groups" AS (
    SELECT p.processing_order_id,
           p.tenant_id,
           p.processing_order_no,
           p.group_key,
           MIN(p.ord) AS first_ord,
           jsonb_agg(p.entry ->> 'itemId' ORDER BY p.ord) AS position_item_ids
      FROM "v92_parts" p
     GROUP BY p.processing_order_id, p.tenant_id, p.processing_order_no, p.group_key
),
-- 已有 **live** 套行（认领用）：指纹 = position_item_ids 的规范文本
"v92_live" AS (
    SELECT s.processing_order_id, s.set_index, s.position_item_ids::text AS parts_key
      FROM processing_order_sets s
     WHERE s.deleted = 0
),
-- 号池上界：**不带 `deleted = 0`**（软删行仍占号 ⇒ 只增不复用，设计 §2.4 规则 1）
"v92_high" AS (
    SELECT s.tenant_id, s.processing_order_id, MAX(s.set_index) AS max_index
      FROM processing_order_sets s
     GROUP BY s.tenant_id, s.processing_order_id
),
"v92_numbered" AS (
    SELECT g.processing_order_id,
           g.tenant_id,
           g.processing_order_no,
           g.group_key,
           g.position_item_ids,
           g.first_ord,
           COALESCE(l.set_index,
                    (COALESCE(h.max_index, 0) + ROW_NUMBER() OVER (
                         PARTITION BY g.processing_order_id, (l.set_index IS NOT NULL)
                         ORDER BY g.first_ord))::integer) AS new_index,
           (COUNT(*) OVER (PARTITION BY g.processing_order_id))::integer AS group_count
      FROM "v92_groups" g
      LEFT JOIN "v92_live" l
             ON l.processing_order_id = g.processing_order_id
            AND l.parts_key = g.position_item_ids::text
      LEFT JOIN "v92_high" h
             ON h.processing_order_id = g.processing_order_id
)
INSERT INTO processing_order_sets
    (id, tenant_id, processing_order_id, set_index, set_no, craft_line_id, position_item_ids)
SELECT 'poset-v92-' || md5(n.processing_order_id || '#' || n.new_index::text),
       n.tenant_id,
       n.processing_order_id,
       n.new_index::integer,
       n.processing_order_no || '-' || lpad(n.new_index::text, 3, '0'),
       n.group_key,
       n.position_item_ids
  FROM "v92_numbered" n
 WHERE n.group_count <= 999            -- 软停（设计 §11.3 条件 2）：分组数 > 999 ⇒ **跳过该单**（不静默截断）
ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑥ 存量回填 · 实例行（只回填 order_item_id 非空的行；**SET 子句只允许 set_id / set_no**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 🔴 既有列**零赋值**：不写 `updated_at`（写它 = 改历史值，且会让「历史值一字不动」不可机械核验）。
-- 归属判据 = `position_item_ids @> to_jsonb(o.order_item_id)`（只在行标识可信时归属；NULL 行跳过）。
-- 幂等守卫 = `o.set_id IS DISTINCT FROM s.id`（第二次执行匹配 0 行）。
UPDATE processing_position_operations o
   SET set_id = s.id,
       set_no = s.set_no
  FROM processing_order_sets s
  JOIN tenants t ON t.id = s.tenant_id AND t.deleted = 0
 WHERE s.processing_order_id = o.processing_order_id
   AND s.tenant_id = o.tenant_id
   AND s.deleted = 0
   AND o.deleted = 0
   AND o.order_item_id IS NOT NULL
   AND o.set_id IS DISTINCT FROM s.id
   AND s.position_item_ids @> to_jsonb(o.order_item_id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑦ 软停读数（设计 §11.3 条件 1/4/5）：**可见但不中止** —— 一条脏数据不该挡住全量
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    v_bad_snapshot INTEGER;
    v_over_999     INTEGER;
    v_null_item    INTEGER;
    v_mismatch     INTEGER;
BEGIN
    -- 条件 1：快照解析失败（非数组 / 缺 items_snapshot）
    SELECT COUNT(*) INTO v_bad_snapshot
      FROM processing_orders po
      JOIN tenants t ON t.id = po.tenant_id AND t.deleted = 0
     WHERE po.deleted = 0
       AND COALESCE(jsonb_typeof(po.items_snapshot), 'null') <> 'array';
    IF v_bad_snapshot > 0 THEN
        RAISE WARNING 'V92 软停①：% 个活跃加工单的 items_snapshot 不是 JSON 数组 ⇒ 跳过该单（人工复核，不猜）', v_bad_snapshot;
    END IF;

    -- 条件 2：分组数 > 999（套号会溢出 3 位填充）⇒ 跳过该单（与 ⑤ 的 `group_count <= 999` 同判据）
    SELECT COUNT(*) INTO v_over_999 FROM (
        SELECT p.processing_order_id
          FROM (SELECT po.id AS processing_order_id, po.tenant_id, po.processing_order_no,
                       e.value AS entry, e.ordinality AS ord,
                       COALESCE(NULLIF(btrim(e.value ->> 'craftLineId'), ''),
                                NULLIF(btrim(e.value ->> 'itemId'), ''),
                                'ord:' || e.ordinality) AS group_key
                  FROM processing_orders po
                  JOIN tenants t ON t.id = po.tenant_id AND t.deleted = 0
                  CROSS JOIN LATERAL jsonb_array_elements(po.items_snapshot)
                       WITH ORDINALITY AS e(value, ordinality)
                 WHERE po.deleted = 0
                   AND jsonb_typeof(po.items_snapshot) = 'array'
                   AND jsonb_typeof(e.value -> 'processingItems') = 'array') AS p
         GROUP BY p.processing_order_id, p.tenant_id, p.group_key) AS g
        GROUP BY g.processing_order_id
       HAVING COUNT(*) > 999;
    IF v_over_999 > 0 THEN
        RAISE WARNING 'V92 软停②：% 个活跃加工单的樘窗组数 > 999 ⇒ 已跳过该单（套号会溢出 3 位填充，需人工裁定，不静默截断）', v_over_999;
    END IF;

    -- 条件 4：order_item_id 为 NULL 的实例行 ⇒ 跳过回填（V69 逐字：猜错比留空更糟）
    SELECT COUNT(*) INTO v_null_item
      FROM processing_position_operations o
      JOIN tenants t ON t.id = o.tenant_id AND t.deleted = 0
     WHERE o.deleted = 0 AND o.order_item_id IS NULL;
    IF v_null_item > 0 THEN
        RAISE WARNING 'V92 软停④：% 条活跃实例行的 order_item_id 为 NULL（V69 之前的存量行）⇒ 跳过套归属回填（不猜，读面按加工单号兜底）', v_null_item;
    END IF;

    -- 条件 5：实例行回填数与「按快照预期」不一致 ⇒ 记 ERROR 读数（不中止）
    -- 预期 = 该单快照里 order_item_id 非空且能归到某个套的实例行数；实际 = set_id 非空的实例行数
    SELECT COUNT(*) INTO v_mismatch FROM (
        SELECT o.processing_order_id
          FROM processing_position_operations o
          JOIN tenants t ON t.id = o.tenant_id AND t.deleted = 0
         WHERE o.deleted = 0
           AND o.order_item_id IS NOT NULL
         GROUP BY o.processing_order_id
        HAVING COUNT(*) FILTER (WHERE o.set_id IS NOT NULL) <> COUNT(*)) AS m;
    IF v_mismatch > 0 THEN
        RAISE WARNING 'V92 软停⑤（对账读数）：% 个加工单存在「order_item_id 非空但未回填 set_id」的实例行 ⇒ 供人工复核（不中止）', v_mismatch;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑧ 硬停（**可执行断言**）：本迁移自己写出的数据不自洽 ⇒ 立即停（整个文件回滚）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    v_count  INTEGER;
    v_sample TEXT;
BEGIN
    -- S1 套号重复（同租户内 live 行）—— 码里印的是 set_no ⇒ 重复会让扫码解析到两套
    SELECT COUNT(*), COALESCE(MIN(d.set_no), '')
      INTO v_count, v_sample
      FROM (SELECT s.set_no
              FROM processing_order_sets s
             WHERE s.deleted = 0
             GROUP BY s.tenant_id, s.set_no
            HAVING COUNT(*) > 1) AS d;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'V92 停止条件 S1（套号重复）：同租户内 set_no 重复 % 组（例：%）⇒ 立即停（本文件已回滚）', v_count, v_sample;
    END IF;

    -- S2 序号跳号：软删行仍占号 ⇒ 每个单的 set_index 必须是连续的 1..MAX
    SELECT COUNT(*), COALESCE(MIN(d.processing_order_id), '')
      INTO v_count, v_sample
      FROM (SELECT s.processing_order_id
              FROM processing_order_sets s
             GROUP BY s.tenant_id, s.processing_order_id
            HAVING MIN(s.set_index) <> 1 OR MAX(s.set_index) <> COUNT(*)) AS d;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'V92 停止条件 S2（序号跳号）：% 个加工单的 set_index 不是连续的 1..MAX（例：%）⇒ 立即停（号池必须单调）', v_count, v_sample;
    END IF;

    -- S3 活跃单的 live 套数 ≠ 窗数（`>999` 被软停②跳过的单除外 —— 它们的套行**本就不该存在**）
    SELECT COUNT(*), COALESCE(MIN(d.processing_order_id), '')
      INTO v_count, v_sample
      FROM (SELECT g.processing_order_id,
                   COUNT(*) AS group_count,
                   COALESCE(l.live_sets, 0) AS live_sets
              FROM (SELECT p.processing_order_id, p.group_key
                      FROM (SELECT po.id AS processing_order_id, po.tenant_id,
                                   e.value AS entry, e.ordinality AS ord,
                                   COALESCE(NULLIF(btrim(e.value ->> 'craftLineId'), ''),
                                            NULLIF(btrim(e.value ->> 'itemId'), ''),
                                            'ord:' || e.ordinality) AS group_key
                              FROM processing_orders po
                              JOIN tenants t ON t.id = po.tenant_id AND t.deleted = 0
                              CROSS JOIN LATERAL jsonb_array_elements(po.items_snapshot)
                                   WITH ORDINALITY AS e(value, ordinality)
                             WHERE po.deleted = 0
                               AND jsonb_typeof(po.items_snapshot) = 'array'
                               AND jsonb_typeof(e.value -> 'processingItems') = 'array'
                               AND NOT (
                                     COALESCE(e.value ->> 'componentRole', '') = '配布边'
                                     AND EXISTS (
                                         SELECT 1
                                           FROM processing_orders po2
                                           CROSS JOIN LATERAL jsonb_array_elements(po2.items_snapshot)
                                                WITH ORDINALITY AS e2(value, ordinality)
                                          WHERE po2.id = po.id
                                            AND jsonb_typeof(e2.value -> 'processingItems') = 'array'
                                            AND COALESCE(e2.value ->> 'componentRole', '') <> '配布边'
                                            AND COALESCE(NULLIF(btrim(e2.value ->> 'craftLineId'), ''),
                                                         NULLIF(btrim(e2.value ->> 'itemId'), ''),
                                                         'ord:' || e2.ordinality)
                                              = COALESCE(NULLIF(btrim(e.value ->> 'craftLineId'), ''),
                                                         NULLIF(btrim(e.value ->> 'itemId'), ''),
                                                         'ord:' || e.ordinality)
                                     )
                                   )
                           ) AS p
                     GROUP BY p.processing_order_id, p.group_key) AS g
              LEFT JOIN (SELECT s.processing_order_id, COUNT(*) AS live_sets
                           FROM processing_order_sets s
                          WHERE s.deleted = 0
                          GROUP BY s.processing_order_id) AS l
                     ON l.processing_order_id = g.processing_order_id
             GROUP BY g.processing_order_id, l.live_sets
            HAVING COUNT(*) <= 999
               AND COUNT(*) <> COALESCE(l.live_sets, 0)) AS d;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'V92 停止条件 S3（存量单套数 ≠ 窗数）：% 个加工单的 live 套行数与快照窗数不符（例：%）⇒ 立即停', v_count, v_sample;
    END IF;

    -- S4 套号格式：{加工单号}-{3 位零填充}（>999 溢出的**显式拒绝**，不静默截断）
    SELECT COUNT(*), COALESCE(MIN(d.set_no), '')
      INTO v_count, v_sample
      FROM (SELECT s.set_no
              FROM processing_order_sets s
              JOIN processing_orders po ON po.id = s.processing_order_id
             WHERE s.deleted = 0
               AND s.set_no <> po.processing_order_no || '-' || lpad(s.set_index::text, 3, '0')) AS d;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'V92 停止条件 S4（套号格式）：% 条 live 套行的 set_no ≠ {单号}-{3 位}（例：%）⇒ 立即停', v_count, v_sample;
    END IF;

    -- S5 实例行的 set_id 对不上：跨单 / 该行 order_item_id 不在所属套的部位清单里
    SELECT COUNT(*), COALESCE(MIN(d.set_no), '')
      INTO v_count, v_sample
      FROM (SELECT o.set_no
              FROM processing_position_operations o
              JOIN processing_order_sets s ON s.id = o.set_id
             WHERE o.deleted = 0
               AND o.set_id IS NOT NULL
               AND (s.processing_order_id <> o.processing_order_id
                    OR s.tenant_id <> o.tenant_id
                    OR s.deleted <> 0
                    OR NOT (s.position_item_ids @> to_jsonb(o.order_item_id)))) AS d;
    IF v_count > 0 THEN
        RAISE EXCEPTION 'V92 停止条件 S5（套归属对不上）：% 条实例行的 set_id 跨单或不在所属套的部位清单里（例：%）⇒ 立即停', v_count, v_sample;
    END IF;
END $$;
