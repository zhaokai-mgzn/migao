# 第三轮深度测试 · 修复包任务书（两包，2026-10-03）

> 承载体（铁律 12(d)）：修复规格不得只活在会话上下文里。两包在两条验收线收口后派发
> （机器负载：同日并发 ≤3，§17.2；**派发时先在批次分支上跑一次 `./scripts/batch-gate.sh`，不逐包跑全量**）。

---

## 包 F-6220（P1·涉钱/库存）· 售后工单并发完结 ⇒ 库存被回补 4 次

**issue**：#6220　**被测构建点**：`main-live` HEAD `43ca70322`

### 根因（已定位，逐字）
`backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::updateTicketStatus`
= **读-判-写**：`selectById` → 应用层比对流转表 → `updateById(ticket)`（**无条件覆盖**，无乐观锁、无 `WHERE status=旧值`）；
随后在应用层分支里执行两个副作用：
- `linkRefundToOrderAndFinance`（**有** DB 原子条件更新 ⇒ 并发安全，本轮实测 `refundOver=false`）
- `maybeRestockOnReturn` → `OrderService.restoreStockForReturn(orderId)`（**零保护** ⇒ 每并发一次跑一遍）

### 判据（修前必红、修后必绿；各配注入式判别力红证）
1. `N=4` 并发对同一 `processing` 工单发 `PUT /api/admin/after-sales/{id}/status {status:"resolved"}`，**重复 3 轮**：
   - 成功数 == **1**（其余返回 409/422「状态已被他人变更」）；
   - `product_skus.stock` 增量 == **单次回补量**（独立算式 = 订单明细数量，**不得**用被测读面当期望）；
   - `stock_ledger_entries` 该 `ref_no` **恰 1 行**；
   - `ticket_timeline` 该工单 `status_change` **恰 2 行**（`pending→processing` + `processing→resolved`）；
   - `orders.refund_amount` == 单次金额（**正对照**：这条现在已绿，证明同事务另一副作用有护栏）。
2. **判别力红证**：摘掉并发保护（或把条件更新换成无条件 `updateById`）⇒ 上述判据必须红；加回 ⇒ 绿。
   ⛔ 注入只在本包的测试装置/临时副本上做，**不得**提交注入代码。
3. **类级固化**（铁律 8）：同一事务内"多个副作用"必须逐个检查并发保护 —— 落一条**元守卫或清单判据**
   （例：`src/main` 内 `updateById(` 后紧跟"多副作用分支"的形态需被审查/登记），并在 PR body 写「固化声明」
   （判据 = 文件::测试名 / CI job / 回归时会怎么红 / 未固化项）。

### 修法建议（不强制，取其一对齐既有范式）
- **首选**：状态流转改原子条件更新 —— `UPDATE after_sales_tickets SET status=?, closed_at=?, close_reason=?, internal_notes=? WHERE id=? AND tenant_id=? AND status=?`；
  `update==0` ⇒ `409`「工单状态已被他人变更，请刷新后重试」；**副作用只在条件更新成功的那一次执行**。
- 备选：给 `after_sales_tickets` 加 `version` 列 + MyBatis-Plus 乐观锁。
- ⚠️ 保持既有语义不变：`pending→closed`（#3541 裁定）、`resolved/rejected/closed` 终态、中文业务文案、
  `closed`/`rejected` 记 `closed_at`、`internal_notes` 追加而非覆盖。

### 边界 / 不得顺手改的
- **不动** `linkRefundToOrderAndFinance` 的既有原子更新口径（它是正对照）；
- **不动** `maybeRestockOnReturn` 的"整单回补 vs 商品开关"业务语义（那是产品裁定：任一商品不允许 ⇒ 整单不回补）；
- 若发现"不同类工单（refund + return）各完结一次 ⇒ 双回补"（主会话假设 H2，**未定论**）⇒ **另开单**，不要在本包改语义。

### 交付物
分支 + PR（body 写 `Closes #6220` + 固化声明）· 实例判据（会红 + 注入红证读数）· 类级守卫 · `# case_ids:`（新增用例 ID 用 `scripts/next_case_id.py` 现取）· CHANGELOG（用户可见行为变更：并发完结由"重复回补"变"一次生效并提示"）。

---

## 包 F-6219（P2·一体机）· 裁高读面 500（不可变空表 `get(null)`）

**issue**：#6219　**被测构建点**：`main-live` HEAD `43ca70322`

### 根因（已定位，逐字）
`backend/admin-api/src/main/java/com/migao/admin/service/WorkerCuttingHeightService.java::positionRow`
第 149 行 `row.put("brand", item == null ? null : brands.get(item.getProductId()));`
而 `brands(...)` 在**没有任何明细带非空 `product_id`** 时 `return Map.of();`（**不可变空表**）。
**JDK 语义**（本机 Java 21 实跑）：`Map.of().get(null)` ⇒ `NullPointerException`；`Map.of("k","v").get(null)` ⇒ NPE；
`new LinkedHashMap<>().get(null)` ⇒ `null`。⇒ `item.getProductId() == null` 时必 500。
（javadoc 的设计意图相反：**「缺 ⇒ `null`，不猜」**。）

### 判据（修前必红、修后必绿）
1. **实例判据**：造 `order_items.product_id IS NULL` 的探针夹具 ⇒ 该端点 **不得 5xx**：
   期望 200 且该行 `brand=null`（或 4xx 明确拒绝）；**5xx 单列 fail**。
2. **回归对照**：`product_id` 非空时行为逐字不变（`brand` 取属性值 / 属性缺失时 `null`）；
   `GET /api/admin/production/scan` 同夹具不受影响（证明修的是这一层）。
3. **判别力红证**：修复前跑一次 ⇒ 判据红；修复后 ⇒ 绿（两次读数都要贴进 PR body）。

### 类级固化（铁律 8）
- **全仓扫描**：`src/main` 内对 `Map.of()` / `Map.of(...)` 的返回值做 `get(<可能为 null 的键>)` 的形态；
  逐处给读数（命中数 / 判定 / 处置），并落一条**会红的守卫**（未登记即红）。
- **主会话给的起点读数**（供包里复核，不是结论）：`backend/admin-api/src/main/java` 内 `Map.of()` 出现 **40 处**，
  其中 `return Map.of();` 的**空集分支**至少 12 处（含 `DailyBriefingService` / `StockBatchConsumptionService` /
  `ProcessingOrderService` / `ProductionScanService` / `WorkerCuttingHeightService` / `OrderShipGuard` / `ProductionService`）；
  形如 `.get(x.getYId())` 的**可能 null 键索引**调用点另有数十处（如 `DailyBriefingService` / `StockBatchConsumptionService`）——
  **逐处判定"键是否可能为 null"才是结论**，不要按出现次数出货。
- 修法建议：`brands` 统一返回 `LinkedHashMap`（空集返回 `new LinkedHashMap<>()` 或 `Collections.emptyMap()`），
  或调用点用 `Objects.requireNonNullElse(item.getProductId(), "")` / 显式判空 —— 取**最少代码**的一条，并注释写明"不可变表的 `get(null)` 抛 NPE"。

### 边界
- 不改 `brands()` 的查询语义（`ProductAttribute` 按 `attr_key=brand` + `tenant_id` 过滤）；
- 不改 `cutting-height` 的只读契约与"不写机器"裁定（用户 2026-09-29）。

### 交付物
同 F-6220 的形态：分支 + PR（`Closes #6219` + 固化声明）· 实例判据 + 红证 · 全仓同族扫描读数 · 类级守卫 · `# case_ids:`。

---

## 包 F-6221（P2·涉钱·精度）· 退款金额 `0.001` 被接受却在写库时静默舍成 `0`

**issue**：#6221

### 根因（已定位）
金额列精度 = `numeric(·,2)`（`orders.refund_amount` `numeric(12,2)`、`finance_transactions.amount` `numeric(12,2)`、
`orders.actual_amount` / `after_sales_tickets.refund_amount` `numeric(10,2)`），而
`PUT /api/admin/orders/{id}/refund` 的入口（`OrderService.refundOrder`）**只校验 `>=0` 与 `<= 实收`**，不校验小数位数 ⇒
`0.001` 被接受（200）后在写库时被舍成 `0.00`（订单与资金流水**两处都静默归零**，`refund_at` 却已写入）。

### 判据（修前必红）
1. `refund_amount = 0.01` ⇒ 200，且 `orders.refund_amount` 与 `finance_transactions.amount` **逐字相等**（正对照）；
2. `refund_amount = 0.001` ⇒ **4xx 显式拒绝**，且**订单与流水都不得新增/改动**（现状 200 ⇒ 红）；
3. 舍入方向登记：`0.004 ⇒ 0`、`0.005 ⇒ 0.01`、`0.009 ⇒ 0.01`（PG 半进位）——写进口径文档，不作缺陷判据。

### 类级固化（铁律 8）
- **全仓金额入口扫描**：凡写入 `numeric(·,2)` 金额列的入口（订单建单/改价、收款、退款、售后联动、结算、发放、调账…）
  逐处给读数（是否有小数位准入），落一条**会红的守卫**（新增入口未登记即红）。
- 口径依据（写进代码注释/文档）：同仓既有范式 = **显式拒绝而非静默取整** —— `StockQuantity.requireOneDecimal`、
  `InboundOrderService.requireItemNumbers`。

### 边界
- 不改金额四舍五入方向（PG 既有语义）；不改退款封顶/状态白名单的既有守卫（那是正对照）；
- 若发现"某入口**本应**允许更多精度"（业务口径）⇒ 交人工裁定，不在本包改。

---

## 包 F-6222（P3·读面）· 分页参数无准入：`size<0` ⇒ `total=0` 而 `items` 返回全部行

**issue**：#6222

### 根因（已定位，主会话独立复现）
`GET /api/admin/orders?size=-5` ⇒ `200 / total=0 / page=1 / size=500 / rows=478`（`size=-1&page=-1` 同形）；
`size=0` ⇒ `total=478 / rows=0`；`page=99999&size=10` ⇒ `rows=0 / total=478`（正常）。
⇒ 分页插件对负 `size` **既不拒绝也不归一**，且**污染了 `total`** —— 同一响应里 `total=0` 与 `rows=478` **自相矛盾**。

### 判据（修前必红）
1. `size < 0`（及非法值）⇒ **4xx 显式拒绝**，或**归一为合法值且 `total` 保持真实**；
2. **不变式**：`total` 必须等于同刻独立 `count(*)`（允许写并发下 ≤ 少量漂移）；
3. `size > 全局上限（`MybatisPlusConfig` 的 `maxLimit=500`）` ⇒ `size` 钳到 500、**`total` 诚实、跨页求和 == total**（现状已绿，正对照）。

### 类级固化
- **分页入参扫描**：逐面（`orders` / `stock-ledger` / `finance` / `after-sales` / `products` / 批量读面…）给读数，
  落一条**会红的守卫**（未登记即红）；判据形状与 `maxLimit=500` 的既有牙齿保持同源，不要另写一份。

### 边界
- 不改 `maxLimit=500` 的既有取值（那是产品口径）；
- 上一轮 D7（导出被截断）已由 #6204 修复 ⇒ 本包**不得**回退其口径（导出走不带 `IPage` 的 `selectList`）。

---

## 包 F-6226（P3·读面）· #6219 同族存量：`Map.of()` 空表 + 空键索引（两处已逐字复核）

**issue**：#6226（由修复包 F-6219 的全仓普查撞见，**主会话已按 `origin/main` 逐字复核**）

### 两处站点（都在 `backend/admin-api/src/main/java/com/migao/admin/service/`）

| # | 站点 | 空集分支 | 调用点 | 触发 |
|---|---|---|---|---|
| A | `ProcessingItemService.getCategoryNameMap` | `:211-213 return Map.of();` | `:72 categoryNameMap.get(item.getCategoryId())`（**键未过同一道 `hasText` 过滤**） | 该页**所有**加工项 `category_id` 为空 ⇒ 空表 + `get(null)` ⇒ NPE ⇒ 500 |
| B | `ProcessingOrderService.loadOrders` | `:3686-3688 return Map.of();` | `:3661 orders.get(po.getOrderId())`（未判空） | 该批加工单 `order_id` 全为空 ⇒ 同形 |

**同族不一致的实证**：`ProductService.java:1823` 的**同名**方法空集返回 `new HashMap<>()` ⇒ 空键索引返 `null` 不抛。
（`ProcessingItemService` 非空分支用 `Collectors.toMap(...)` 无 mergeFunction；键是 PK ⇒ 本次不判缺陷，但要在扫描清单里登记。）

### 判据（修前必红）

1. 造「键全为 NULL」的探针夹具 ⇒ 对应列表端点 **200**（缺值渲染 `null`/空名），**不得 5xx**；
2. **类级元守卫**（**与 F-6219 同源，勿另造一份**）：`src/main` 内凡返回 `Map.of` / `Map.copyOf` 族的方法，
   其调用方若存在**未经判空的空键索引** ⇒ 红（未登记即红、台账只许缩短、条数现取）；
   ⚠️ 口径只裁 `Map.of`/`Map.copyOf` 族 —— `Collections.emptyMap()` / `unmodifiableMap` / `LinkedHashMap` 的 `get(null)` **返 null 不抛**（已实跑，#6219 有对照表）；
3. **修法**（取最少代码，二选一，与 F-6219 口径保持一致）：空集分支改容忍空键的表（`new LinkedHashMap<>()` 或 `Collections.emptyMap()`），**或**调用点显式判空。

### 边界

- **不同文件族** ⇒ 独立包、独立分支（**不进 F-6219 的分支**）；
- 不动 `ProductService` 的同名方法（它已是安全形态）；
- 若扫描又发现第三/第四处 ⇒ 本包内一并修（同族同包更省），但要在 PR body 逐处列读数。

### 交付物

同前两包形态：分支 + PR（`Closes #6226` + 固化声明）· 实例判据 + 修前红/修后绿读数 · 全仓扫描逐处清单 · 类级守卫 · `# case_ids:` · CHANGELOG（用户可见：列表页由 500 变正常渲染）。

---

## 两包共同的纪律
- 一包 = 一个文件族（两包文件不重叠：`AfterSalesTicketService` vs `WorkerCuttingHeightService`；
  **用例面**：两包各改**不同** `.github/cases/*.yml` 域文件，改完必须跑 `render_cases.py` 并提交生成物）；
- **不逐包跑全量**：`./verify-all.sh gate` 只在**批次集中一次**（`./scripts/batch-gate.sh <分支...>`）；
  包内只跑**定点判据**（`-Dtest=<本包测试类>` / `pytest <本包文件>`）；
- 提交前 `./contract-check.sh`（跨模块时）；不改 `cases/**` 生成物以外的共享文件；
- PR body 写「固化声明」四要素；**部分交付不许写 `Closes`**。
