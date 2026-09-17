-- 库存流水/台账（issue #4055）
--
-- 为什么建这张表（裁定，勿再讨论）：超卖/对账是**资金级风险** —— 没有台账就无法回答
-- 「某 SKU 的库存为什么从 X 变成 Y」。同族先例已有：`audit_logs`（操作审计）、
-- `production_work_logs`（报工明细）、`client_request_keys`（幂等键）。
--
-- 粒度 = **SKU 级**（issue #4038 已确立「`product_skus.stock` 为库存权威、`products.stock` 为派生」）。
-- 保留期：不设 TTL，随订单生命周期（软删 `deleted`）。
--
-- 可对账（**不变式**）：同一 SKU 的相邻两行必须首尾相接 ——
--   本行 `before_qty` == 该 SKU 上一行的 `after_qty`，且 `after_qty - before_qty == delta`。
--   `id` 是 IDENTITY 单调递增列，为「同一 SKU 的多行定序」提供**全序**（`created_at` 会撞毫秒）。
--
-- 写入方（挂在**库存变更的既有实现点**，不新造扣减逻辑；每站点写一行流水）：
--   · manual     —— `ProductService.adjustStockForAgent`（Agent 手工调整：增/减按 SKU 分摊）→ 本迁移同批落码
--   · aftersales —— `AfterSalesTicketService.maybeRestockOnReturn`（退货回补，复用
--                   `OrderService.restoreStockForReturn` 的既有路径）→ 本迁移同批落码
--   · order      —— 下单/支付扣减（`OrderService.deductSkuStock`）：**本批未落码**
--                   （该文件被在飞 P15 占用），取值已预留，补写方归后续 issue。
--   ⚠️ 已知未覆盖的第三类变更：建品/改品直接写 SKU 库存（`ProductService.saveColorsAndSkus`
--      的 SKU 新增/更新/删除分支）—— 本批未落码，故该路径造成的库存变化**不会**出现在台账里。
--
-- 与 `orders.stock_deducted` 的关系（该死列本轮不处置，归 issue #4056）：
--   `orders.stock_deducted` 是**订单级的布尔标志**（实测 954/954 恒 false，且全仓无写入方），
--   既答不出「哪个 SKU 变了多少」，也答不出「变之前是多少」—— 它只是「本单是否已扣」的意图位。
--   本表是**SKU 级事实账**：订单扣减对应 `reason='order'` + `ref_no=<订单号>` 的行。
--   ⇒ 两者不是同一个信息：**台账不依赖该布尔列**，也不需要它先被修好；
--     反向地，将来 #4056 若把该列实现为「本单已写台账」的派生标志，其真值应从本表推导
--     （`EXISTS(reason='order' AND ref_no=<orderNo>)`），不再另立第二份真相源。
--
-- 幂等：全部 IF NOT EXISTS。

CREATE TABLE IF NOT EXISTS stock_ledger_entries (
    -- IDENTITY 单调递增：为「同一 SKU 的相邻两行首尾相接」这条不变式提供全序（不靠 created_at 撞运气）
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    -- SKU 主键可能被「删旧行 + 插新行」重建（ProductService.saveColorsAndSkus 会**硬删** SKU），
    -- 故 sku_id 不加 FK（加了会让重建时的历史流水悬空/插入失败），并同时冗余 sku_code 供追溯。
    sku_id BIGINT,
    sku_code VARCHAR(64),
    delta INT NOT NULL,                              -- 变化量（正=入库/回补，负=出库/扣减）
    before_qty INT NOT NULL,                         -- 变更前该 SKU 库存
    after_qty INT NOT NULL,                          -- 变更后该 SKU 库存（= before_qty + delta）
    reason VARCHAR(16) NOT NULL,                     -- order / aftersales / manual（取值集合见 StockLedger 常量）
    ref_no VARCHAR(64),                              -- 业务单据号：订单号（order）或工单号（aftersales）；manual 为空
    note VARCHAR(255),                               -- 人类可读的变更原因（如 Agent 传入的「盘点」「报损」）
    operator VARCHAR(64) NOT NULL,                   -- 操作人（登录用户名；无认证上下文 = system）
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0               -- 软删（不设 TTL）
);

-- 按 SKU 对账（最常用：某 SKU 的库存变化链）
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_sku
    ON stock_ledger_entries (tenant_id, sku_id, id);
-- 按商品查（商品详情/排查）
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_product
    ON stock_ledger_entries (tenant_id, product_id, id);
-- 按单据查（订单/工单溯源：一单改动了哪些 SKU）
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_ref
    ON stock_ledger_entries (tenant_id, ref_no, id);

COMMENT ON TABLE stock_ledger_entries IS
    '库存流水/台账（issue #4055）：SKU 级库存变更事实账，每行 = 一次变更（before/after 首尾相接可对账）。'
    '粒度 SKU 级（#4038：product_skus.stock 为权威）、不设 TTL（软删 deleted）。';
COMMENT ON COLUMN stock_ledger_entries.reason IS
    '变更来源：order 订单扣减 / aftersales 售后回补 / manual 手工调整（本批已落 manual 与 aftersales 两个写入方，order 待补）';
COMMENT ON COLUMN stock_ledger_entries.ref_no IS
    '业务单据号：order → 订单号；aftersales → 工单号；manual → 空';
COMMENT ON COLUMN stock_ledger_entries.operator IS
    '操作人：登录用户名（手机号）；内部服务调用 = internal-service；无认证上下文（定时任务/测试）= system';
COMMENT ON COLUMN stock_ledger_entries.sku_id IS
    'SKU 主键（无 FK：SKU 会被硬删重建）；追溯请优先用 sku_code';