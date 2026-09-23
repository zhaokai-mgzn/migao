-- 订单级「加急」与「客户要求到货日」（issue #5177 = 阶段 2b-2）—— **独立落在 orders 上**
--
-- ## 一句话
--   `orders` 追加两列：`is_urgent`（加急标记，**缺省 false**）/ `required_delivery_date`
--   （客户要求到货日，**可空 = 未指定，不猜**）。两列是**订单自己的事实**，
--   与售后工单的 `priority` **不共享来源、不联动、不派生**。
--
-- ## 为什么必须与消费者同批（本单的存在理由，别把两列读成「可配却无效果的参数」）
--   字段与消费者分两批交付，就会造出本仓明令禁止的形态 —— **可配却无效果的参数**
--   （V112 正是为删掉这样一个参数而存在）。本单的两列**各有真实消费者**，同一批落地：
--     ① `is_urgent` 的消费者 = **加急插队**：加急单**不进池**（不是成批候选），
--        立刻走既有**单订单**路径派工（`pooled=false`）；且把它混进 `pooled=true` 的成批批次
--        ⇒ **整批显式拒绝**（`ProcessingOrderService.assertNoUrgentInPooledBatch`，fail-closed）。
--     ② `required_delivery_date` 的消费者 = **池看板的排序与筛选**：
--        排序键 = 到货日升序（NULL 排最后）→ 等待时长降序 → 进池时刻升序 → 单号升序
--        （`ProcessingOrderService.POOL_LINE_ORDER`），看板按到货日临期优先提示。
--   ⇒ 两列**都不是记录用的空字段**；删掉任一消费者，本迁移的列就应立即失去存在理由。
--
-- ## 为什么**不**复用售后工单的 `priority`（用户裁定，逐字）
--   「**加急不能跟售后工单绑定，得在订单上直接做**」⇒ 订单加急与售后 priority 是**两个事实**：
--   售后 priority 描述「工单处理的紧急度」，订单 `is_urgent` 描述「这张单要不要插队派工」。
--   绑定会同时坏掉两边：给订单标加急会改掉售后的排班序，改售后优先级又会插队生产。
--   ⇒ 售后 `priority` 只作**命名/文案风格**的先例（`is_urgent` 是布尔标记而不是优先级枚举），
--   **不是**数据来源。本迁移因此**不新增外键、不新增触发器、不做任何跨表同步**。
--   （机械判据：`OrderUrgencyRealDbTest` 的零联动断言 —— 改订单加急 ⇒ `after_sales_tickets.priority`
--   逐值不变，反之亦然。）
--
-- ## 为什么 `is_urgent` 是 `NOT NULL DEFAULT FALSE`（而不是可空布尔）
--   「缺省值不变 ⇒ 行为与今天逐字相同」要的是**没有第三态**：可空布尔会给出
--   true / false / NULL 三种读法，而 NULL 与 false 在下游（是否入池、是否拒绝成批）
--   必然被当成同一件事 ⇒ 一个「谁也说不清是不是加急」的单可以静默走任一条路径。
--   NOT NULL DEFAULT FALSE 让「未标加急」与「明确不加急」**同值**，且存量行自动获得
--   `false`（= 今天的行为：所有单都不加急、都进池）⇒ **记录期零污染**。
--
-- ## 为什么 `required_delivery_date` 可空、且**不回填**
--   它记的是**客户要求到货日**这个外部事实。存量单**从来没有**采集过它
--   ⇒ 任何回填都是**编一个日期**（拿 created_at 或承诺交期冒充客户要求 = 伪造事实）。
--   NULL 的语义逐字是「**未指定**」，读面（看板）必须把 NULL 排在**最后**而不是当成
--   「最紧急」（把未知当最紧急会让看板排序变成噪声）。
--
-- ## 精度/类型选择（与既有列同族，不新造口径）
--   · `required_delivery_date` 用 `DATE`（**不是** `TIMESTAMP`）：它语义上是「哪一天」，
--     用带时区的 TIMESTAMP 会让「10 月 1 日」在不同时区读成 9 月 30 日 —— 一个只有日期
--     精度的事实不该带时刻。
--   · `is_urgent` 用 `BOOLEAN`，与既有 `orders.stock_deducted`（V8 家族）/`order_items.is_shaped`
--     同型，不引入 CHECK 词表。
--
-- ## 变更影响面（如实登记）
--   · **不改任何既有列**：`status` / `total_amount` / `actual_amount` / `discount_amount` /
--     `refund_amount` 一字未动 ⇒ 对客金额、售价、成品口径**逐值不变**（判据 6）。
--   · **不新增幂等键、不新增来源枚举、不新增精度助手**（最少代码：两列 + 两段注释 + 终态对账）。
--   · **不新增查询索引**：池的判定谓词是 `tenant_id × deleted × status`（已有索引面），
--     加急/到货日只改**内存里的排序与候选集**，不进任何 `WHERE` 谓词
--     ⇒ 加一个没人用的索引只是噪音（YAGNI；若日后看板改成库侧排序再按 EXPLAIN 加）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V121__rollback_order_urgency.sql（本单只登记，不落码）
-- -- ALTER TABLE orders DROP COLUMN IF EXISTS required_delivery_date;
-- -- ALTER TABLE orders DROP COLUMN IF EXISTS is_urgent;
-- ```
-- **回滚是有损的**：商家标过的「加急」与「客户要求到货日」**回不来**（列被丢弃），
-- 且回滚后正在插队的单不再插队。属**有意**（回滚一个已登记的业务事实就不该静默复原）。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V115/V116/V117/V118/V119 纪律）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `orders` 表不存在 ⇒ 迁移失败并停下（不 CREATE TABLE 兜底 —— 会造出无外键/无租户列
--      的影子表，而 `orders` 是全系统最核心的表之一）；
--   ② 终态对账报「列缺失」/「列类型不符」/「is_urgent 仍可空」/「列默认值不是 false」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V115/V116/V117/V118/V119 的实测口径）
--   `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒
--   留下**半完成态**。两条执行路径（`MigrationRunner` 的 `jdbc.execute(整份文件)` 与 `psql -f`）
--   必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'orders') THEN
        RAISE EXCEPTION 'V120 前置表缺失：orders —— 迁移停下（不兜底建表）';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 追加两列（`is_urgent` 一步到位 NOT NULL DEFAULT FALSE ⇒ 存量行自动 false = 今天的行为）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS required_delivery_date DATE;

-- 幂等加固：若该列先前以可空形态存在（半完成态 / 手工改过），这里补上 NOT NULL 与默认值。
-- `SET DEFAULT` / `SET NOT NULL` 本身幂等（重复设置不报错）；回填只对 NULL 行生效（第二遍 0 行）。
UPDATE orders SET is_urgent = FALSE WHERE is_urgent IS NULL;
ALTER TABLE orders ALTER COLUMN is_urgent SET DEFAULT FALSE;
ALTER TABLE orders ALTER COLUMN is_urgent SET NOT NULL;

COMMENT ON COLUMN orders.is_urgent IS
    '订单级**加急标记**（issue #5177）：true = 该单插队、**不进池**、立刻走单订单路径派工'
    '（pooled=false）；混进 pooled=true 的成批批次 ⇒ 整批显式拒绝。'
    'NOT NULL DEFAULT FALSE ⇒ 存量单与未传值的建单都自动 false = 今天的行为（记录期零污染）。'
    '与售后工单 priority **不共享来源、不联动、不派生**（用户裁定：加急不能跟售后工单绑定）。';
COMMENT ON COLUMN orders.required_delivery_date IS
    '**客户要求到货日**（issue #5177；DATE，非 TIMESTAMP —— 一个只有日期精度的事实不该带时刻）。'
    'NULL = **未指定**（不猜、不回填：存量单从未采集过这个外部事实，回填 = 编一个日期）。'
    '消费者 = 池看板排序/筛选：到货日升序（NULL 排最后，**不得**当成最紧急）→ 等待时长降序。'
    '不影响对客价格、成品、交期承诺（判据 6）。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing      TEXT;
    urg_type     TEXT;
    urg_nullable TEXT;
    urg_default  TEXT;
    date_type    TEXT;
    null_rows    INTEGER;
BEGIN
    -- ① 两列必须在
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('is_urgent'), ('required_delivery_date')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'orders'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V120 终态对账失败：缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ② 类型必须逐字正确（改错类型 = 读面把日期当字符串 / 布尔当整数，静默错）
    SELECT data_type, is_nullable, column_default INTO urg_type, urg_nullable, urg_default
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'is_urgent';
    IF urg_type <> 'boolean' THEN
        RAISE EXCEPTION 'V120 终态对账失败：orders.is_urgent 类型 = %（期望 boolean）—— 回滚本迁移', urg_type;
    END IF;
    SELECT data_type INTO date_type
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'required_delivery_date';
    IF date_type <> 'date' THEN
        RAISE EXCEPTION 'V120 终态对账失败：orders.required_delivery_date 类型 = %（期望 date）'
            ' —— 回滚本迁移', date_type;
    END IF;

    -- ③ is_urgent 必须 NOT NULL DEFAULT FALSE（第三态 = 「谁也说不清是不是加急」的单能走任一条路径）
    IF urg_nullable <> 'NO' THEN
        RAISE EXCEPTION 'V120 终态对账失败：orders.is_urgent 仍可空（is_nullable=%）'
            ' —— 「未标加急」与「明确不加急」必须同值 —— 回滚本迁移', urg_nullable;
    END IF;
    IF urg_default IS NULL OR lower(urg_default) NOT LIKE '%false%' THEN
        RAISE EXCEPTION 'V120 终态对账失败：orders.is_urgent 默认值 = %（期望 false）'
            ' —— 缺省变了 ⇒ 行为与今天不再逐值相同 —— 回滚本迁移', coalesce(urg_default, '(null)');
    END IF;

    -- ④ 存量行必须全部有值（回填谓词写错 ⇒ 可空列上留 NULL，读面把「未指定」读成「不加急」）
    SELECT count(*) INTO null_rows FROM orders WHERE is_urgent IS NULL;
    IF null_rows <> 0 THEN
        RAISE EXCEPTION 'V120 终态对账失败：仍有 % 行 is_urgent 为 NULL —— 回滚本迁移', null_rows;
    END IF;
END $$;

COMMIT;
