-- 打印流水（issue #7902）—— 谁、什么时候、打了哪种单据
--
-- ## 一句话
-- 「打印」过去只发生在浏览器里：按钮一点、纸一出一进，服务端什么都不知道。于是同一个问题反复出现：
-- 这张单打没打过？上次打的是加工单还是销售单？发货之后补打过几次？改名/离职的那个人是谁？
-- 本表把「打印」变成**服务端可见的事实**：订单详情页的打印流水读它，订单列表的「是否已打印」是它的聚合投影。
--
-- ## 打印是**外部事实**：只登记「已发起 + 结果」，不假装能确认纸真的出来了
-- 纸出没出来，服务端**不可能知道**（浏览器打印对话框的最终结果不在任何接口里，蓝牙直连也一样）。
-- 所以 `status` 只有两档：`fired` = 已发起到打印（订单页点了、任务交给了浏览器/打印机）、
-- `failed` = 明确的失败（并在 `fail_reason` 里说清为什么）。
-- ⛔ 不新增「已打印」这种第三态 —— 那会把一个不可验证的承诺写成数据库事实。
--
-- ## 不存业务对象副本
-- `order_no` / `order_status` / `doc_title` / `operator_name` / `media_id` 都是**当时的快照**，
-- 真值仍在 `orders` / `processing_orders` / `users` / `print-media.json`。
-- 快照存在的唯一理由是**历史可读**：
--   ① 单被作废/软删之后，「这台打印机当时确实吐过这张单」仍要说得清；
--   ② 人改名/离职之后，流水上写的仍是当时那个人（不是现在的名字）。
-- ⇒ 这几列**只用于显示**；任何业务判断都不许读它们（要真值去读 `orders`）。
--
-- ## 为什么不是「订单上加一个 printed 布尔」
-- 打印是 **N 次事件**：首打、改单后重打、发货后补打、水洗唛按部位一张、一次联合打印 N 条……
-- 一个布尔只能回答「有没有」，回答不了「谁 / 何时 / 哪种单据 / 几张 / 哪台纸型」；
-- 而且布尔一旦被重置（改单后想重新标记），历史就没了。事件表天然带时间轴，
-- 列表页的「最近一次打印」只是它的一个聚合投影（`MAX(created_at)`）。
--
-- ## 批号（`batch_id` / `batch_index` / `batch_size`）
-- 一次「联合打印」= 一次请求里的 N 条，共享一个 `batch_id`；`batch_index` 从 0 起、`batch_size` = 本次条数。
-- 三件缺一就分不清「3 张纸一批」与「三批各 1 张」（重打时要重放的是**那一批**）。
--
-- ## 闭集合（表上有 CHECK 兜底）
-- `doc_type` ∈ {sales, processing, quotation, labels}
-- `channel`   ∈ {browser=系统打印, ble=蓝牙直连}
-- `status`    ∈ {fired=已发起, failed=失败}
-- Java 侧同一份口径在 `entity/PrintLog.java` 的常量与 `isKnown*` 方法里；新增一种单据/通道/结果
-- 必须同时改迁移与判据，不允许字符串随便长。
--
-- ## 索引
-- `(tenant_id, order_id, created_at DESC)` —— 详情页时间轴 + 列表「最近一次打印」的聚合；
-- `(tenant_id, created_at DESC)`         —— 「本租户最近的打印流水」（谁在什么时候打了什么）。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步本表（新建库不跑迁移链）。
-- - 回滚：`DROP TABLE print_logs;` **无数据损失** —— 打印流水是**事实记录**，不是任何业务状态的来源
--   （`orders` / `processing_orders` / `users` 一个字段都不动）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS print_logs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),

    order_id VARCHAR(36),
    order_no VARCHAR(64),                        -- 订单号快照（订单作废/软删后仍可读）

    doc_type VARCHAR(32) NOT NULL,               -- 封闭集合：sales / processing / quotation / labels
    doc_title VARCHAR(32),                       -- 打印当时的纸面名（加工单 / 面料单 / 水洗唛 / 销售单 / 报价单）
    processing_order_id VARCHAR(36),
    processing_order_no VARCHAR(64),             -- 加工单号快照（加工单 / 水洗唛那两张才有）

    media_id VARCHAR(32),                        -- 纸型 id（a4 / continuous-241x140 / label-50x150，登记在 print-media.json）
    sheets INTEGER NOT NULL DEFAULT 1,           -- 这次出纸几张（水洗唛按部位一张）
    channel VARCHAR(16) NOT NULL DEFAULT 'browser',  -- browser=系统打印 / ble=蓝牙直连

    batch_id VARCHAR(36),                        -- 一次「联合打印」的 N 条共享 batch_id
    batch_index INTEGER,                         -- 这一批里的第几条（0 起）
    batch_size INTEGER,                          -- 这一批共几条

    order_status VARCHAR(32),                    -- 打印当时的订单状态快照（分清首打与发货后补打）

    status VARCHAR(16) NOT NULL DEFAULT 'fired', -- fired=已发起到打印 / failed=失败
    fail_reason VARCHAR(255),

    operator_id VARCHAR(36),
    operator_name VARCHAR(64),                   -- 姓名快照（改名/离职后历史仍可读）
    client_ip VARCHAR(64),
    user_agent VARCHAR(255),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_print_logs_doc_type CHECK (doc_type IN ('sales', 'processing', 'quotation', 'labels')),
    CONSTRAINT ck_print_logs_channel CHECK (channel IN ('browser', 'ble')),
    CONSTRAINT ck_print_logs_status CHECK (status IN ('fired', 'failed')),
    CONSTRAINT ck_print_logs_sheets CHECK (sheets BETWEEN 1 AND 999)
);

CREATE INDEX IF NOT EXISTS idx_print_logs_tenant_order_created
    ON print_logs (tenant_id, order_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_print_logs_tenant_created
    ON print_logs (tenant_id, created_at DESC);

COMMENT ON TABLE print_logs IS
    '打印流水（issue #7902）：谁、什么时候、打了哪种单据。🔴 不存业务对象副本（order_no/order_status/doc_title/operator_name 只是快照）；打印是外部事实，只登记「已发起 + 结果」，不假装能确认纸真的印出来了。';
COMMENT ON COLUMN print_logs.doc_type IS
    '封闭集合（CHECK）：sales 销售单 / processing 加工单 / quotation 报价单 / labels 洗水唛等标签类';
COMMENT ON COLUMN print_logs.doc_title IS
    '打印当时的纸面名快照（加工单 / 面料单 / 洗水唛 / 销售单 / 报价单）—— 只用于显示，不参与任何业务判断';
COMMENT ON COLUMN print_logs.channel IS 'browser 系统打印 / ble 蓝牙直连';
COMMENT ON COLUMN print_logs.status IS
    'fired 已发起到打印（纸出没出来服务端不知道）/ failed 明确失败（原因在 fail_reason）';
COMMENT ON COLUMN print_logs.sheets IS '这次出纸几张（洗水唛按部位一张）';
COMMENT ON COLUMN print_logs.batch_id IS '一次联合打印的 N 条共享同一个 batch_id（batch_index 从 0 起、batch_size = 本次条数）';
COMMENT ON COLUMN print_logs.order_status IS '打印当时的订单状态快照（分清首打与发货后补打）';

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_table BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'print_logs' AND table_schema = 'public') INTO has_table;
    IF NOT has_table THEN
        RAISE EXCEPTION 'print_logs 缺表（issue #7902 迁移未生效）';
    END IF;
END $$;

COMMIT;
