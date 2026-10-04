# 线② · 售后退款闭环 + 并发竞态 sweep（2026-10-04 第四轮 · 租户 25 · **已部署面**）

> 执行者 = 后台验收子代理（线②）。**本报告只产读数 + 判定 + 证据，不下「验收通过 / 交付完成 / 已达标」结论**（不自我验收）。
> 四态：`pass` / `fail(产品)` / `skip(未覆盖 —— 永不记 pass)` / `假红(判据缺陷或无判别力)`。
>
> ## ⚠️ 被测构建点坐标（**集成侧 2026-10-04 09:1x +08 更正，本报告按新口径**）
> - **行为实测构建点 = `de614623d`**（`2026-10-02 10:22:50 UTC`，**落后 `origin/main` 152 个提交**）。
>   三条依据：① 集成侧独立复现同一工单并发状态流转 = `[200,200,200,200]` + 副作用 ×4，而被测台账 SHA 的源码里 #6220 的原子条件更新**本应给出 `[200,409,409,409]`**；
>   ② 部署步远端输出逐字：`PREV_GOOD_TAG=sha-de61462` + `❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建`；
>   ③ 近 80 条 deploy run 里 `deploy=success` **一条都没有**，两条 `success` 出自 reconcile 的「跳过部署」路径（**skip 不判绿 ⇒ 假绿**）。
> - **部署台账声称 `ff655a06c`**（`deploy-admin-api.yml` 最近一个 `success` 的 `headSha`，`2026-10-03T21:47:10Z` = 2026-10-04 05:47 +08），**但部署腿自 2026-10-03 起从未成功**；已开单 **#6294（P0·部署）**。
> - ⇒ **本线全部 `fail` 只能定性为「老构建 `de614623d` 上实测存在的缺陷」**，**不得**归因为「main 上的缺陷」；对 `origin/main` 的结论需环境修复（#6294）后重跑。
> - 本报告引用的**源码符号路径**取自**台账声称构建点** `ff655a06c`；实际运行构建点早于它 ⇒ 同名符号**不保证逐字一致**，需在环境升到 main 后复验。
> - 🔺 **升级后状态（2026-10-04 09:30:44 +08 起）**：环境已切到 **`sha-6838a05`**（= main HEAD `6838a0533`，#6294 已修）⇒ 本线 harness **原样重放**：`pass 51→57 / fail 8→2 / skip 3 / 假红 0`（见 **§9**）。本报告 §0~§7 的读数仍是**升级前（`de614623d`）**的读数，**同时保留**作 before/after 对照。
> - `LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live` HEAD = `43ca70322` 只是**本地旧构建点**，**本报告读数一律不取自它**。
>
> 被测面：`https://api.migaozn.com` · 租户 **25**「米高测试环境」· 管理员 `13800138000` · 万能码 `123456`。
> 采集时刻：**2026-10-04 09:17:10 +08**（最后一次全量跑；11 段全部 `ok`，见 `out/run-all.log` 的 11 对 `▶ 运行 <段>` / `◀ <段> ok`，09:15:19–09:17:10 +08）。

---

## 0. 一句话结论

- **四态读数**（全量 62 条）：**pass 51 / fail(产品) 8 / skip(未覆盖) 3 / 假红 0**；收尾零残留（本线命名域逐表 **0**，含本线新增的探针分类）。
- **8 条 fail 收敛为 4 个独立现象**（3 个在钱与状态机面，1 个是新租户可用性前置缺口）：
  ① **并发完结副作用翻倍**（工单时间线重复 + 退货回补库存重复；4 条判据）；
  ② **涉钱精度静默归零**（`0.001` ⇒ HTTP 200 / `refund_amount=0` / 仍写 `refund_at`；2 条判据）；
  ③ **读面自相矛盾**（`size<0` ⇒ `total=0` 却回整页；1 条）；
  ④ **空租户首个商品走 API 不可达**（本线命名域初始 **0 个商品分类**、`categoryId` 必填；1 条）。
- **正对照全绿**：**并发退款封顶**（8×3 轮 `[200×3, 422×5]`、终值 = 实收）、**订单侧并发改状态恰一个赢家**、**并发派工**（业务成功恰 1、活跃加工单恰 1、工序实例不重复）。
- ⇒ 本线读数支持一个**机器可判**的结论形态：**同一租户、同一装置下，守卫在位的面守住（退款 / 订单状态 / 派工），缺谓词的面翻倍（工单状态机 + 退货回补）**。
- ⚠️ 以上一切只对 **`de614623d`（老构建）** 成立（见页首坐标声明）。
- 🔺 **升级后（`6838a0533`，2026-10-04 09:30:44 +08 起）**：本线 harness 原样重放 ⇒ **pass 57 / fail 2 / skip 3 / 假红 0**；旧构建 8 条 fail 中 **6 条转绿**（C2 / C21 / C22 / C23 / REF-B03 / PREC-02 随 #6220 / #6228 生效而消失），残留 2 条 = **`LB0-01`（期望值过期伪影：判据仍拿 BRIEF 的 `ff655a06c` 比，而台账已是 `6838a0533`）** + **`LB1-SETUP-category-gap`（#6295 在 main 仍开放）**；详见 §9。

---

## 1. 读数汇总（四态分列）

> 真值以 `out/SUMMARY.json` 的 `counts` / `byGroup` 为准。

| 组 | pass | fail(产品) | skip(未覆盖) | 假红 | total |
|---|---|---|---|---|---|
| B0 环境自证（部署面坐标） | 6 | 0 | 0 | 0 | 6 |
| B1 夹具（探针商品/已确认订单 + 分类前置） | 5 | **1** | 0 | 0 | 6 |
| B1 售后退款闭环（串行） | 18 | 0 | 2 | 0 | 20 |
| B2 并发竞态（C1~C4 族） | 4 | 1 | 0 | 0 | 5 |
| B2/B1 补强探针（并发状态机面 / 精度 / 读面） | 6 | **5** | 1 | 0 | 12 |
| B1 涉钱精度（p5） | 2 | 1 | 0 | 0 | 3 |
| B1 退款负例补强（p7） | 3 | 0 | 0 | 0 | 3 |
| B2 正对照（订单侧 CAS + SQL 量化） | 2 | 0 | 0 | 0 | 2 |
| B2 并发派工（C5 + 红证） | 3 | 0 | 0 | 0 | 3 |
| Z 零残留 | 2 | 0 | 0 | 0 | 2 |
| **合计** | **51** | **8** | **3** | **0** | **62** |

**8 条 fail 的归属**：`LB1-SETUP-category-gap`（F4）；`LB-C2-CONCURRENT-RESOLVE` / `LB-C21-CONCURRENT-SAME-TARGET` / `LB-C22-CONCURRENT-CONFLICT` / `LB-C23-CONCURRENT-RESOLVE-TIMELINE`（F1，同一根因）；`LB-REF-B03` + `LB-PREC-02`（F2，同一根因）；`LB-C4-NEGATIVE-SIZE`（F3）。**假红 0 条**。

**3 条 skip（永不记 pass）**：`LB-AS-CREATE-02`（库中已无 tenant≠25 的订单可作跨租户探针）、`LB-AS-CREATE-03`（判据对象错层：admin-api 直连面未接 `ClientRequestIdService`）、`LB-C4-BULK-READ-1000`（本租户最大可读面 < 1000 行）。

**并发族单列**（每项带 `N` / `rounds[3]` / 逐请求结局 / `overlapEvidence`；原始读数见 `out/B2-concurrency.json`、`out/B4-probe-batch.json` 的 `extra.rounds`）：

| id | 形态 | N×轮 | 逐轮结局 | DB 终态 | 重叠证据 | 判定 |
|---|---|---|---|---|---|---|
| `LB-C1-CONCURRENT-REFUND` | 同一订单并发退款（防双花） | 8×3 | `[200×3, 422×5]`×3 | `refund_amount=300.00`（= 实收）；流水合计 300.00 | 真重叠 | **pass** |
| `LB-C1-REDPROOF` | C1 判别力红证（摘/加守卫） | 8 | 无守卫 ⇒ 800；有守卫 ⇒ 300 | — | 8 个独立 psql 进程 | **pass** |
| `LB-C2-CONCURRENT-RESOLVE` | 同工单并发完结（双副作用） | 4×3 | `[200,200,200,200]`×3 | 库存 98→**106**；台账 **4 行**；时间线 **5 行**；退款 300（**未翻倍 = 正对照**） | 365/350/446ms 真重叠 | **fail(产品)** |
| `LB-C21-CONCURRENT-SAME-TARGET` | 并发打**同一目标** | 4×3 | `[200,200,200,200]`×3 | 时间线 **4 行**（应 1） | 166/115/115ms 真重叠 | **fail(产品)** |
| `LB-C22-CONCURRENT-CONFLICT` | 并发**分歧**（processing vs closed） | 2×3 | `[200,200]`×3 | 终态 `[processing, closed, closed]`；**两路都成** | 64/70/73ms 真重叠 | **fail(产品)** |
| `LB-C23-CONCURRENT-RESOLVE-TIMELINE` | 并发 resolved ⇒ 审计重复 | 4×3 | `[200,200,200,200]`×3 | timeline「→resolved」**4 行**（应 1） | 117/109/112ms 真重叠 | **fail(产品)** |
| `LB-C23-ROWCOUNT-REDPROOF` | 「行数」读数的判别力红证 | 4 / 1 | 4 次写 ⇒ 4 行；1 次写 ⇒ 1 行 | — | — | **pass** |
| `LB-C3-CONCURRENT-STOCK` | 同 SKU 并发扣减 / 超卖 / 负数 | 8×3 | 超卖 `[422,…]` | 不出现负数 | 真重叠 | **pass** |
| `LB-C5-DISPATCH-POOLED` | 同一单据并发派工（pooled 两侧） | 4×3 | HTTP `[200×4]`；**业务成功数 [1,1,1]**（其余 `VALIDATION_ERROR`「已有加工单 … 请勿重复生成」） | 活跃加工单 **1**；工序实例不重复 | 真重叠 | **pass** |
| `LB-C5-REDPROOF` | C5 判别力红证（摘/加唯一约束） | 4 | 无约束 ⇒ **4 行**；有约束 ⇒ **1 行** | — | 4 个独立 psql 进程 | **pass** |
| `LB-CTRL-ORDER-STATUS-CAS` | **正对照**：订单侧并发改状态 | 4×3 | 恰 1 个 200 ×3 | 终态 producing | 真重叠 | **pass** |
| `LB-CTRL-CAS-SQL` | 正对照 SQL 层量化 | 4 | 有谓词 w=**1**；无谓词 w=**4** | — | — | **pass** |

> **C5 兜底物**：库级部分唯一索引 `uk_processing_orders_active`（上一轮由主会话独立从 `pg_indexes` 核过）；本轮读数「业务成功恰 1 / 活跃加工单恰 1」与之自洽。

---

## 2. 真缺陷清单（最小复现 + 会红判据 + 根因符号 + 五层归因 + 证据引用）

> **逐条状态（升级后复验，2026-10-04 09:30:44 +08 起，证据见 §9）**：
> `F1`（C2/C21/C22/C23）**已随部署消失** ⇒ pass｜`F2`（PREC-02 / REF-B03）**已随部署消失** ⇒ pass｜`F3`（C4-NEGATIVE-SIZE）**已随部署消失** ⇒ pass｜`F4`（category-gap）**仍开放**（#6295）⇒ 仍 fail。
>
> **统一坐标声明（本节 4 条全部适用）**：以下现象均在 **老构建 `de614623d`** 上实测；根因符号路径取自**台账声称构建点** `ff655a06c` 的源码 ⇒ **该符号属台账声称构建点，实际运行构建点早于它 ⇒ 需在环境升到 main（#6294 修复）后复验**。

### 2.1 F1（**并发 · 涉库存**）售后工单并发完结 ⇒ 审计重复 + 退货回补库存重复生效

- **判据 id**：`LB-C2-CONCURRENT-RESOLVE` / `LB-C21-CONCURRENT-SAME-TARGET` / `LB-C22-CONCURRENT-CONFLICT` / `LB-C23-CONCURRENT-RESOLVE-TIMELINE`（4 条 **fail**）
- **逐字读数**（`out/B2-concurrency.json` 的 `records[LB-C2-CONCURRENT-RESOLVE].extra.rounds[0].dbFinal`，三轮逐字相同）：
  ```
  {"ticketStatus":"resolved","refund_amount":300,"actual":300,
   "skuBefore":98,"skuAfter":106,"ledgerRows":4,"timelineRows":5,"financeRows":1}
  perRequest = [ {200 ok 366ms}, {200 ok 243ms}, {200 ok 269ms}, {200 ok 458ms} ]
  overlapEvidence R1 = 真重叠：最大逐对重叠 365ms（并集 459ms < 各历时之和 1336ms）
  ```
  `out/B4-probe-batch.json`：`LB-C21` 三轮 `成功数=[4,4,4]`、`时间线读数=[4,4,4]`；`LB-C23` 三轮 `时间线读数=[4,4,4]`；`LB-C22` 三轮 `成功数=[2,2,2]`、`DB 终态=["processing","closed","closed"]`。
- **最小复现**（全部在探针自建对象上；`PROBE_PREFIX=线B验收` / id 前缀 `lb`）：
  ```bash
  M="/Users/guangzhen.zk/ai native/migao"; cd "$M"
  API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
  OUT_DIR=acceptance/2026-10-04/aftersales-refund-sweep/out REPO_ROOT="$M" \
  SEGMENTS=p0,p1,p3,p4 node acceptance/2026-10-04/aftersales-refund-sweep/harness/run-all.mjs
  # 手抄版：① 探针商品（allow_return_restock=true, stock=100）② 建单 qty=2 + PUT /api/admin/orders/{id}/payment（实收 300）
  #        ③ POST /api/admin/after-sales {ticketType:return, refundAmount:300} ④ 工单 → processing
  #        ⑤ N=4 同时 PUT /api/admin/after-sales/{tid}/status → resolved（共享 barrier 同一起跑线）
  #        ⑥ 读 SKU 库存 + stock_ledger_entries(ref_no=工单号) + ticket_timeline
  ```
- **会红的判据**（机器可判、**不依赖请求时序**）：
  1. `stock_ledger_entries` 中 `ref_no=<工单号>`、`reason='aftersales'` 的**行数必须 = 1**，且 SKU 终值 = 回补前读数 + 明细数量（**恰一次增量**）；实测 **4 行 / 98→106**；
  2. `ticket_timeline` 中同一工单 `content.to='resolved'` 的**行数必须 = 1**；实测 **4 行**；
  3. 并发打同一目标（pending→processing）**成功响应必须恰好 1 个**（其余 422）；实测 **4/4 全 200、时间线 4 行**。
- **根因（源码符号）**：
  - `…/service/AfterSalesTicketService.java` 的 `updateTicketStatus` —— 状态机校验读 `selectById` 得到的**内存旧值**，落库 `afterSalesTicketMapper.updateById(ticket)` 其 `WHERE` **仅主键 id**（无状态谓词）⇒ 读-判-写在并发下失去互斥；
  - 同文件 `maybeRestockOnReturn` ⇒ `OrderService.restoreStockForReturn` ⇒ `…/mapper/ProductSkuMapper.java` 的 `restoreStock`：`UPDATE product_skus SET stock = COALESCE(stock,0) + #{quantity} WHERE id = #{skuId}` —— **无幂等谓词**；
  - **正对照 1（同一次完结的另一副作用有护栏）**：`AfterSalesTicketService.linkRefundToOrderAndFinance` 的 `setSql(...) + WHERE COALESCE(refund_amount,0) + applied <= actual`，`updated==0` 即跳过 ⇒ 实测退款**未翻倍**（300.00 封顶、`financeRows=1`）；
  - **正对照 2（同仓更近的范式）**：`OrderService.transitionStatusAtomic`（带状态谓词的条件更新 + `rows==0 ⇒ 422`）⇒ 订单侧并发改状态实测**恰 1 个赢家**；SQL 层量化**有谓词 w=1 / 无谓词 w=4**。
- **五层归因**：① **现象层** 并发完结 ⇒ 库存虚增 6 米 + 审计 4 行；② **接口层** `PUT /api/admin/after-sales/{id}/status` 对同工单**无并发互斥**（4/4 全 200）；③ **实现层** `updateById` 的 `WHERE` 缺状态谓词 ⇒ 校验基于陈旧内存值；④ **类级层** 同一服务内已有正确范式（退款封顶谓词）与订单 CAS，本处未复用；⑤ **机制层** `restoreStock` 无幂等键 ⇒ **副作用不可重复的语义没有落到 SQL 上**。
- **边界**：只在工单从 `processing` 并发打 `resolved`（或同目标并发）时出现；`pending→resolved` 本就不合法。影响面 = 客服连点 / 客户端重试 / 网络重放。
- **证据引用**：`out/B2-concurrency.json`（`LB-C2-*` 的 `extra.rounds[*].dbFinal/leaks/overlapEvidence`）、`out/B4-probe-batch.json`（`LB-C21/C22/C23` 的 `extra.rounds[*]`）。

### 2.2 F2（**涉钱精度**）`refund_amount=0.001` ⇒ HTTP 200 但金额**静默归零**且仍写 `refund_at`

- **判据 id**：`LB-PREC-02`（`out/B5-refund-precision.json`）/ `LB-REF-B03`（`out/B4-probe-batch.json`，独立复现）
- **逐字读数**：
  ```
  LB-PREC-01  0.01  （最小可表示）  ⇒ 200；orders.refund_amount=0.01；流水 1 行 0.01     ✅ 两侧相等（正对照）
  LB-PREC-02  0.001 （小于最小可表示）⇒ 200；orders.refund_amount=0；流水 1 行 amount=0；refund_at=set  ❌
  LB-PREC-03  0.004 ⇒ 0/0 ；0.005 ⇒ 0.01/0.01 ；0.009 ⇒ 0.01/0.01（订单侧与流水侧始终相等 —— 口径登记）
  ```
- **最小复现**：
  ```bash
  curl -X PUT "https://api.migaozn.com/api/admin/orders/<探针已确认订单id>/refund" \
    -H 'Content-Type: application/json' -b "access_token=$TOKEN" \
    -d '{"refund_reason":"精度探针","refund_amount":"0.001"}'
  # ⇒ {"success":true}（HTTP 200）；库内 orders.refund_amount=0.00 且 refund_at 非空；finance_transactions 1 行 amount=0.00
  ```
- **会红的判据**：`0 < refund_amount < 0.01`（小于列可表示精度）时必须 **4xx 显式拒绝**，且不得写 `refund_at`、不得写资金流水；不变式：同笔 `orders.refund_amount` 与 `finance_transactions.amount` 必须**逐字相等**。
- **根因（源码符号）**：`…/controller/OrderController.java` 的 `refundOrder` 只做 `new BigDecimal(amount.toString().trim())` ⇒ 任意精度进入；列类型 `orders.refund_amount = numeric(12,2)` / `finance_transactions.amount = numeric(12,2)` ⇒ 库内四舍五入。**同系统既有范式是「显式拒绝、不静默取整」**：`…/service/StockQuantity.java` 的 `requireOneDecimal`、`…/service/InboundOrderService.java` 的 `requireItemNumbers` ⇒ **两套精度口径**。
- **五层归因**：① 现象层 退 0.001 元显示「已退款」而金额为 0；② 接口层 非法精度未被准入拦截；③ 实现层 金额侧无准入校验（数量侧有）；④ 类级层 `StockQuantity` 范式未在金额面复用；⑤ 机制层 **精度责任被交给 DB 的隐式舍入**。
- **证据引用**：`out/B5-refund-precision.json`（`LB-PREC-01/02/03` + 列类型真值）、`out/B4-probe-batch.json`（`LB-REF-B03` 的 `extra.finance`）。

### 2.3 F3（**读面**）列表端点 `size < 0` ⇒ HTTP 200 但 `total=0` 与整页行**自相矛盾**

- **判据 id**：`LB-C4-NEGATIVE-SIZE`（1 条 **fail**）
- **逐字读数**（`out/B4-probe-batch.json`）：
  ```
  [{label:orders,       status:200, total:0, size:500, rows:44},
   {label:stock-ledger, status:200, total:0, size:500, rows:148},
   {label:after-sales,  status:200, total:0, size:500, rows:20}]   不自洽点数 = 3
  对照（自洽）：size=0 ⇒ total=真实总数 / rows=0；page=99999 ⇒ total 真实 / rows=0；size=100000 ⇒ 钳到 500
  ```
- **最小复现**：`curl -b "access_token=$TOKEN" "https://api.migaozn.com/api/admin/orders?page=1&size=-5"` ⇒ `total=0` 而 `items` 非空。
- **会红的判据**：任意 200 的分页响应必须满足 `items.length <= total`；`size<0` 应 **4xx 或归一化（回退默认 20）并保持 `total` 真实**。
- **根因（源码符号）**：`OrderController.getOrders`（`@RequestParam(defaultValue="1") long size`，**无下限校验**）；`…/config/MybatisPlusConfig.java` 的 `PaginationInnerInterceptor(setMaxLimit(500))` **只设上限**。
- **五层归因**：① 现象层 按 `total` 驱动分页器/空态的调用方把有数据的页面当「0 条」；② 接口层 参数无下限校验；③ 实现层 非法入参下 `total` 与列表路径分叉；④ 类级层 分页插件只设上限、缺下限。
- **证据引用**：`out/B4-probe-batch.json` 的 `LB-C4-NEGATIVE-SIZE.detail`（三端点读数 + 源码符号）。

### 2.4 F4（**新租户可用性 · 前置缺口**）本线命名域初始 **0 个商品分类** ⇒ `POST /api/admin/products`（`categoryId` 必填）422 不可达

- **判据 id**：`LB1-SETUP-category-gap`（1 条 **fail**，`out/B1-setup.json`）
- **逐字读数**（`out/B1-category-gap.json`）：
  ```
  本线命名域（前缀「线B验收」）初始 active 分类数 = 0
  POST /api/admin/products ⇒ 422 VALIDATION_ERROR「分类ID不能为空」（原始响应见 out/B1-fixtures.json 的 fixtures[*].resp）
  经真实 API 补建探针分类后 ⇒ 本线命名域 active 分类数 = 1（补建响应见 out/B1-category-gap.json 的 probeCategoryCreate）
  同时段**别线**的分类 = 4 条（`线A验收链分类-*`，本线只登记、不触碰）
  ```
- **最小复现**：
  ```bash
  curl -X POST "https://api.migaozn.com/api/admin/products" -H 'Content-Type: application/json' -b "access_token=$TOKEN" \
    -d '{"name":"x","unit":"米","pricingType":"per_meter","basePrice":100,"price":100,"stock":100,"status":"on_shelf",
         "colors":[{"colorName":"c","mainColorHex":"#AABBCC"}],"doorWidths":["2.8m"]}'
  # ⇒ 422 {"error":{"code":"VALIDATION_ERROR","message":"分类ID不能为空"}}
  ```
- **会红的判据**：新租户（**本线命名域内** `categories` 0 行）在**不手工造分类**的前提下，`POST /api/admin/products` 不得因缺服务端默认分类而 422；或产品侧应在入驻时种一个默认分类 / 在 422 文案里给出可行动出口。
- **根因（源码符号）**：`…/dto/ProductCreateRequest.java` 的 `categoryId` 必填（服务端 `createProduct` 依赖它）；`…/service/RegistrationService.java` 入驻只种**默认角色/权限/岗位**，**不种商品分类**。
- **五层归因**：① 现象层 空租户走 API 建不出第一个商品；② 接口层 422 文案只说「分类ID不能为空」，不指出「去哪里建分类」；③ 实现层 入驻流程无商品分类种子；④ 类级层 **「新租户可用性」缺一条端到端判据**（本轮以空租户首跑才暴露）。
  ⚠️ **归因强度限制**：本线只断言「**本租户本线命名域**初始零分类 ⇒ 走 API 建商品缺前置」。**能否由前端「商品管理」页自助建分类兜住**（即真实新用户是否被卡住）**不在本线射程**（未做 UI 级验证）⇒ 不写更强归因，也不判「用户必被卡死」。
- **证据引用**：`out/B1-setup.json`（`LB1-SETUP-category-gap`）、`out/B1-category-gap.json`、`out/B1-fixtures.json`。

---

## 3. 判据的红证 / 负对照索引（**没有红证 = 空断言**）

| 判据 | 红证 / 负对照（注入方式） | 读数 | 会不会红 |
|---|---|---|---|
| `LB-C1-CONCURRENT-REFUND` | `lb_gp_redproof`：8 个独立 psql 进程并发同一 UPDATE，一轮**摘掉 WHERE 上限**、一轮**加回** | 无守卫 ⇒ **800**（> 上限 300）；有守卫 ⇒ **300** | 会（摘掉必红） |
| `LB-C2/C21/C22/C23` | `lb_gp_timeline`：「N 次到达是否 N 行」的判别力自证 | 4 次写 ⇒ **4 行**；1 次写 ⇒ **1 行** | 会（读数对写入次数敏感） |
| `LB-C3-CONCURRENT-STOCK` | `lb_gp_stock`：初值 3.0，8 进程并发各扣 1.0 | 终值 **0.0**（`GREATEST(...,0)` 夹住） | 会（去掉 GREATEST 必为负） |
| `LB-C4-BULK-READ` | **自曝红证**：上一版取数路径错时 `total=undefined` 仍判 pass ⇒ 已改判「取不到真值 ⇒ fail」 | 见 `out/B4-probe-batch.json` | 会（真值缺失即红） |
| `LB-C5-DISPATCH-*` | `lb_gp_dispatch`：4 进程并发同键 INSERT，一轮**无唯一约束**、一轮**有 partial unique index**（产品同形） | 无约束 ⇒ **4 行**；有约束 ⇒ **1 行** | 会（摘掉约束必红） |
| `LB-PREC-01/02`（**涉钱**） | **负对照**：`0.01`（最小可表示）逐字落 0.01 ✅ ⇄ `0.001` 现状 200 且归零 ❌ | 见 §2.2 | 会（越界必红 + 正对照绿） |
| `LB-REF-02/03/04`（**涉钱负例**） | 超额 400/实收 300 ⇒ 422；负数 −50 ⇒ 422；4×100 vs 实收 300 ⇒ 第 4 次 422 | 见 `out/B1-serial.json` | 会 |
| `LB-REF-C01/C02/C03`（负例） | `null` ⇒ 全额；`"一百元"` ⇒ 422「格式不正确」；空白串 ⇒ 全额 | 见 `out/B7-refund-negative.json`（3/3 pass） | 会 |
| `LB-CTRL-ORDER-STATUS-CAS` + `LB-CTRL-CAS-SQL` | **正对照**：同一装置，谓词列被本次 UPDATE 改写；一轮有谓词、一轮无 | 有谓词 **w=1**（恰 1 个 200）；无谓词 **w=4** | 会（本条本身即「换实现必变号」的证据） |
| `LB-Z-01/Z-02` | 逐表计数 + 段内紧邻前后逐行 diff | 全 0 / 0-0-0 | 会（残留非 0 即红） |

> 注入纪律：临时表一律 `lb_gp_*` 且用后即 `drop`（残留计数的 `tempTables` 项终态 **0**）；**未改任何产品源码 / 测试 / 用例**。

---

## 4. 假红 / 假绿与自身 harness 缺陷（自曝）

> 判据纪律：**判据的缺陷与产品的缺陷必须分开报**。以下每条都是本线（或底座）自己的问题。

| # | 现象（逐字） | 归因 | 处置 |
|---|---|---|---|
| **G1（假绿，本轮最值钱）** | `LB1-SETUP-category-gap` 首版写 `select … from categories where status='active'`（**全租户**），而当时租户 25 里**已有别线留下的 4 条 `线A验收链分类-*`** ⇒ 判据「绿」但**对本线探针毫无判别力**（它测的是「租户里有分类」，不是「新租户能不能建商品」） | **判据未命名空间化**（BRIEF 纪律 8） | 改为**只看本线前缀**（`name like '${PROBE_PREFIX}%'`）并重跑 ⇒ 由 `pass` 翻为 **`fail`**（真读数），同时登记「别线 4 条只读不碰」 |
| H1 | **底座 `p7-refund-negative.mjs` 文件级语法错误**：第 49 行 evidence 模板串嵌套未转义反引号 ⇒ `SyntaxError`，整段 `exit 1`、`B7-refund-negative.json` **不生成** | 底座 harness 缺陷（非产品）。**佐证：2026-10-03 的 REPORT/out 里也没有 B7 产物 ⇒ 那段判据其实从未跑过** | 本线在 overlay 修掉语法（判据逐字不变）⇒ `LB-REF-C01/C02/C03` **3/3 pass**，落 `out/B7-refund-negative.json` |
| H2 | 底座 `p0-env.mjs` 硬编码 `tenant_id=20`（该租户 2026-10-04 08:31 已清空）+ 硬编码本地构建点断言 `43ca7032` + 报告写死旧手机号 | 底座与**新环境 / 新口径**不匹配 | overlay 版：租户基线改 `TENANT_ID` 现取；构建点断言改**部署台账自证**（并据集成侧更正加注「台账声称 ≠ 行为实测」）；手机号取 `ADMIN_PHONE` |
| H3 | 底座 `p1-setup.mjs` / `p2-b1-serial.mjs` 硬编码 `tenant_id=20` | 同上 | overlay 改 `TENANT_ID` |
| H4 | `run-all.mjs` 底座路径写错一层（`resolve(HERE,'..','..',…)` 多拼了 `2026-10-04/`）⇒ p3/p4/p5/p6/p7/p9 全报「缺段」，**静默少了 6 段** | 本线 overlay 的**路径缺陷**（非产品） | 修为 `'..','..','..'`；复跑：11 段全部 `ok`（逐段读数见 `out/run-all.log` 的 11 对 `▶/◀`，09:15:19–09:17:10 +08） |
| H5 | 清理顺序反了：先删「探针分类」再删商品 ⇒ `ERROR: update or delete on table "categories" violates foreign key constraint "products_category_id_fkey"` ⇒ 分类残留 | 本线 overlay 的**顺序缺陷**（FK 拓扑序：子表优先） | 改为「先 `cleanupProbe()`（商品/订单/工单…）后 `cleanup-extra`（分类）」⇒ 复跑 `Z-cleanup-extra.json`：`remaining: []` |
| H8 | `out/SUMMARY.json` 的 `segments` 字段为 `{}` —— 因收尾用 `SKIP_RUN=1` 重生成过一次 SUMMARY（该档**不跑段** ⇒ 段状态表为空），而**段级真相在 `out/run-all.log`**（11 对 `▶/◀` 均 ok，09:15:19–09:17:10 +08） | 产物字段语义易误导（非产品） | 本报告凡引用「段全部 ok」一律引 `out/run-all.log`；`SUMMARY.json` 的 `segments` 字段**不作为段执行证据** |
| H6 | 一次全量跑被**我自己的中途补丁**干扰（边跑边改 p2 源码）⇒ 那次读数只到 15 条 | 操作纪律问题（非产品） | 该次读数**作废**，重跑为最终 62 条 |
| H7 | 首版 `p2` 补丁把反引号吃掉（`PROBE_PREFIX工单-…` + 孤立反引号）⇒ 语法错误 | 本线补丁脚本缺陷 | 从底座重新复制后改用「仅同行内替换」的正则 ⇒ `node --check` 通过 |

**本线 overlay 与底座的关系（底座文件一个字节都没改）**：`acceptance/2026-10-04/aftersales-refund-sweep/harness/` 下 `lib.mjs` 是指向底座 `lib.mjs` 的**软链**（逐字同一份）；overlay 只放「因新环境必须改写」的段：`p0-env.mjs` / `p1-setup.mjs` / `p2-b1-serial.mjs` / `p7-refund-negative.mjs` / `p10-dispatch-concurrency.mjs`（仅把 sku_code 前缀 `LB-DISP-` → `LB-DISP2-` 以避开与其它线同名对象撞）+ `cleanup-extra.mjs` + `run-all.mjs`。

---

## 5. 未覆盖清单（skip 及原因与重启条件）

| 缺口 | 为什么没覆盖 | 重启条件 |
|---|---|---|
| `LB-AS-CREATE-02` 跨租户订单复用（挑 tenant≠25 的真实订单作探针） | **库中已无 tenant 1 的订单**（租户 1 于 2026-10-04 清空） | 出现第二个有订单的租户时（线③ 会建临时对照租户）⇒ 即可重跑该条 |
| `LB-AS-CREATE-03` admin-api 直连面的建单幂等回放（AS-010 口径） | **判据对象错层**：AS-010 判的是 agent 工具面 `aftersale_create`，admin-api 售后建单**未接** `ClientRequestIdService`；实测第 2 次被 dup-guard 拒 422（`replayed=undefined`） | 需 agent 工具面跑法（**受 #4262 约束：不得自动派发真实 LLM 评测**）⇒ 需用户显式要求 |
| `LB-C4-BULK-READ-1000` 「>1000 行真实数据量」的列表读 | 本租户最大可读面 = **148 行**（orders 44 / ledger 148 / finance 73 / tickets 20） | 租户数据量 ≥1000 行时 |
| **对 `origin/main` 的结论** | 被测面实际跑的是 **`de614623d`**（落后 main 152 提交，见页首 #6294）⇒ 本线**不能**对 main 下任何结论 | **环境升到 main（#6294 修复）后重跑本线全套**（最直接的复验判据：`LB-C2-CONCURRENT-RESOLVE` 的状态码分布应由 `[200×4]` 变为 `[200,409,409,409]` 型） |
| **「服务端已落库但客户端超时」的真实故障注入** | 当前环境无故障注入能力 | 具备代理/断连注入时 |
| **UI 级（售后/退款页面）写面验证** | 本线只打 admin-api 已部署面；无头浏览器未在本线登记工具与截图路径 ⇒ **如实登记 skip**，不用「页面能打开」冒充写面验证 | 需登记 Playwright + 截图路径（线①/线③ 若已做可复核） |
| **最坏竞争强度（N≫8、跨实例）** | 单机单实例、N≤8 | 多副本部署时 |

---

## 6. 残留清理读数（清理前 / 清理后，均为**现取**）

- **探针命名域**：名称前缀 **`线B验收`**、id/键前缀 **`lb`**、临时表 `lb_gp_*`、本线新增**探针分类**（注册表登记 + `cleanup-extra.mjs`）。
- **清理器**：底座 `lib.mjs` 的 `cleanupProbe()`（按**注册表 + 命名前缀兜底**）+ 本线 `cleanup-extra.mjs`（探针分类，**晚于**商品删除，避开 FK）+ **凭据清理**（`out/.token` 用后即删，`run-all` 收尾打印 `token 凭据已删=true`）。
- **清理前**（本轮全量跑期间创建的探针对象）：15 组探针「商品 + 已确认订单」、约 30 余张探针工单、以及对应的 `finance_transactions` / `stock_ledger_entries` 行（见 `out/B1-fixtures.json` / `out/probe-registry.json`）。
  另登记**非本线**存留（跨包，只读、不触碰）：租户 25 的 `products` / `orders` / `ledger` / `finance` 若干行 + `categories` **5 条**（其中 **4 条 `线A验收链分类-*` 属线①**，另 1 条 `线B验收分类-*` 为本线建、后由 `cleanup-extra` 清掉）。
- **清理后（终态，现取）**：`out/SUMMARY.json` 的 `residue`（本线命名域逐表）
  ```
  {"products":0,"productSkus":0,"orders":0,"orderItems":0,"tickets":0,"ticketTimeline":0,"ledger":0,
   "finance":0,"clientKeys":0,"tempTables":0,"processingOrders":0,"positionOperations":0,"workLogs":0}  total=0
  ```
  `out/Z-cleanup-extra.json`：`{registryCategoryIds: [], preByPrefix: [], remaining: [], errors: []}`；
  `out/run-all.log` 收尾逐字：`零残留=true（…全 0…）；token 凭据已删=true`；
  `out/Z-residue-recheck.json`（清理后独立复读）：`probeDomain` 七项**全为空数组**（含 `categories_lb: []`）。
- **跨包隔离声明（BRIEF 纪律 8）**：三线并发写同一租户 25 ⇒ 本线**只断言本线前缀对象**及其库存/台账行；`Z-02` 的「存量行零改动」判据取**段内紧邻**前后快照，流水表（`stock_ledger_entries` / `finance_transactions`）**只登记行数、不参与 sha 断言**（线①/线③ 同时在写）。
- **未改删任何非探针行**；`categories` 的 4 条 `线A验收链分类-*` 原样保留。

---

## 7. 被测构建点与 SHA 声明（**读数坐标**；已按集成侧更正）

| 项 | 值 | 取证 |
|---|---|---|
| **行为实测构建点（读数来源）** | **`de614623d`**（2026-10-02 10:22:50 UTC，**落后 origin/main 152 提交**） | ① 集成侧独立复现：同一工单并发状态流转 `[200,200,200,200]` + 副作用 ×4，而台账声称 SHA 的源码里 #6220 的原子条件更新**本应给出 `[200,409,409,409]`**；② 部署步远端输出逐字 `PREV_GOOD_TAG=sha-de61462` + `❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建`；③ 近 80 条 deploy run 里 `deploy=success` 一条都没有，两条 `success` 出自 reconcile 的「跳过部署」路径（**skip 不判绿 ⇒ 假绿**） |
| **部署台账声称构建点** | `ff655a06c`（= `ff655a06cdaf4793902c5fb4b0b5bfaa3e3037f2`） | `out/E0-deploypoint.json`：`gh run list --workflow=deploy-admin-api.yml` 最近一个 `success` 的 `headSha`，`createdAt=2026-10-03T21:47:10Z`（= 2026-10-04 05:47 +08）。⚠️ **该 `success` 不等于「部署成功」**（见上行 ③） |
| 远端部署变量 | `ADMIN_API_DEPLOYED_SHA` **未设**（`gh variable get` 取不到） | `out/E0-deploypoint.json` |
| 被测面 URL | `https://api.migaozn.com`（`LB0-03/04` 未鉴权 401；`LB0-05` 短信登录 200 且登录租户 = 25） | `out/B0-env.json`、`out/B0-auth.json` |
| **本地旧构建点（非被测面）** | `LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live` HEAD = `43ca703221a714e143c468ff0b29c4a46e67a88f` | 仅作坐标登记；**本报告读数一律不取自它** |
| 时钟自检 | JS(+08) 与 SQL(`Asia/Shanghai`) 差 **0s** | `out/B0-clock.json` |

**结论射程（据本坐标）**：本线 8 条 `fail` **只能**定性为「**老构建 `de614623d` 上实测存在的缺陷**」；
**不得**读成「main 上的缺陷」；**且**：`LB-C2-CONCURRENT-RESOLVE` 的实测状态码分布 `[200,200,200,200]` 本身即与「#6220 已在源码里落下原子条件更新」**矛盾** —— 这正是坐标不匹配的**行为级证据**，也是环境升到 main 后**最直接的复验判据**。

---

## 8. 产物与一键重跑

```
acceptance/2026-10-04/aftersales-refund-sweep/
├── REPORT.md                 # 本文件
├── harness/
│   ├── lib.mjs               # → 软链到 2026-10-03 底座 lib.mjs（逐字同一份，**未改**）
│   ├── run-all.mjs           # 段解析：本目录优先 + 底座兜底；OUT_DIR/REPO_ROOT 绝对化；清理顺序即安全顺序
│   ├── p0-env.mjs            # 部署面坐标自证 + 时钟 + 鉴权 + 租户基线（env 化）
│   ├── p1-setup.mjs          # 夹具 + 探针分类前置（**命名空间化**的空租户缺口读数）
│   ├── p2-b1-serial.mjs      # 串行闭环（env 化 tenant）
│   ├── p7-refund-negative.mjs# 负例三连（修掉底座语法错误）
│   ├── p10-dispatch-concurrency.mjs # 并发派工（sku 前缀 LB-DISP2- 避撞）
│   ├── cleanup-extra.mjs     # 探针分类清理（FK 序：晚于商品）
│   └── apply-summary.py      # 收尾后把「四态 counts / 更正的 buildpoint / findings」合并写回 out/SUMMARY.json
│                             #    （run-all 每次会按段 JSON 重生成 SUMMARY；坐标更正与 findings 收敛由本脚本落盘）
└── out/                      # 逐条 JSON + SUMMARY.json + run-all.log + run.log
```

```bash
cd "/Users/guangzhen.zk/ai native/migao"
API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live \
OUT_DIR=acceptance/2026-10-04/aftersales-refund-sweep/out \
REPO_ROOT="/Users/guangzhen.zk/ai native/migao" \
node acceptance/2026-10-04/aftersales-refund-sweep/harness/run-all.mjs
# 只跑某几段：SEGMENTS=p0,p1,p3,p4 node …（别名 p0/p8/p1/p2/p3/p4/p5/p6/p7/p10/p9）
# 收尾若用 SKIP_RUN=1 重生成过 SUMMARY.json，记得再合并写回坐标与 findings：
python3 acceptance/2026-10-04/aftersales-refund-sweep/harness/apply-summary.py \
  acceptance/2026-10-04/aftersales-refund-sweep/out/SUMMARY.json
```

**纪律声明**：本线**未**运行 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁），
**未**做真实 LLM 评测（#4262），**未**改任何产品源码 / 测试 / 用例，**未**提 PR；
**本线**（验收子代理）**未**开 issue —— 本报告提到的 **#6294（部署）由集成侧（主会话）于 2026-10-04 09:16:23 +08 开具**，本线只引用它、不认领；
**未**修改底座 `acceptance/2026-10-03/aftersales-concurrency-sweep/**` 任何文件。
**本报告不下「验收通过 / 交付完成 / 已达标」结论**（不自我验收；判定权在主会话与独立复核）。

## 9. 升级后重放（before / after · 环境切到 main 后）

> **谁跑的**：本线 harness 被集成侧（主会话）**原样重放**（同一 harness、同一落点 `TENANT_ID=25`、同一 `PROBE_PREFIX` 机制；重放侧 `PROBE_PREFIX=ZR`）。
> **证据**：`acceptance/2026-10-04/replay-postdeploy/aftersales/SUMMARY.json` + `acceptance/2026-10-04/replay-postdeploy/20-aftersales-full.log`。
> 环境切换：**2026-10-04 09:30:44 +08** 起为 `sha-6838a05`（= main HEAD `6838a0533`，#6294 已修）。
> ⚠️ 重放是**集成侧**的读数（非本线自跑）；本节只做**对照转录 + 差异归因**，不下「验收通过」结论。

### 9.1 四态对照（同一 harness、同一 62 条判据）

| 四态 | 升级前（`de614623d`，09:17:10 +08） | 升级后（`6838a0533`，09:32:47 +08） | 差 |
|---|---|---|---|
| pass | **51** | **57** | +6 |
| fail(产品) | **8** | **2** | −6 |
| skip(未覆盖) | 3 | 3 | 0 |
| 假红(falseRed) | 0 | 0 | 0 |
| total | 62 | 62 | — |

`replay-postdeploy/20-aftersales-full.log` 收尾逐字：
```
2026-10-04 09:32:47 +08 汇总：counts={"pass":57,"fail":2,"skip":3,"falseRed":0,"total":62}；零残留=true（…全 0…）；token 凭据已删=true
```
分段对照（`byGroup`，升级前 → 升级后）：`B2-并发竞态` 4/1/0/0/5 → **5/0/0/0/5**；`B2/B1-补强探针` 6/5/1/0/12 → **11/0/1/0/12**；`B1-涉钱精度` 2/1/0/0/3 → **3/0/0/0/3**；`B0-环境自证` 6/0/0/0/6 → **5/1/0/0/6**；`B1-夹具` 5/1/0/0/6 → **5/1/0/0/6**（不变，仍是 `category-gap`）；其余组不变。

### 9.2 §2 四现象逐条标注（**已随部署消失 / 仍开放**）

| 现象 | 判据 | 升级后 | 依据 |
|---|---|---|---|
| **F1** 工单并发完结 ⇒ 审计重复 + 回补翻倍 | `LB-C2-CONCURRENT-RESOLVE` / `C21` / `C22` / `C23` | ✅ **已随部署消失**（4 条全转 pass；`B2-并发竞态` fail 0、`补强探针` fail 0） | `replay-postdeploy/aftersales/SUMMARY.json` 的 `byGroup`；`LB-C2` 由「成功数 4 / 台账 4 行 / 库存 98→106」变为 pass |
| **F2** 涉钱精度静默归零（0.001 ⇒ 0） | `LB-PREC-02` / `LB-REF-B03` | ✅ **已随部署消失**（`B1-涉钱精度` 3/0） | 同上；对应 main 侧 #6228 的精度准入 |
| **F3** `size<0` ⇒ `total=0` 却回整页 | `LB-C4-NEGATIVE-SIZE` | ✅ **已随部署消失**（`补强探针` fail 0） | 同上 |
| **F4** 空租户命名域零分类 ⇒ API 建商品 422 | `LB1-SETUP-category-gap` | ❌ **仍开放**（`B1-夹具` 5/1，重放读数：`本线命名域（前缀「ZR」）初始 active 分类数=0；经真实 API 补建探针分类后=1（HTTP 200）`） | `replay-postdeploy/aftersales/B1-category-gap.json` + §5/#6295 |

### 9.3 升级后残留的 2 条 fail（逐条归因，**不夸大**）

1. **`LB0-01`（判据侧伪影，非产品缺陷）**：重放读数逐字 = `远端声明=(ADMIN_API_DEPLOYED_SHA 未设)；最后一个 success 部署=6838a0533 @ 2026-10-04T01:20:10Z（UTC）`。
   本线 `p0-env.mjs` 的判据**写死了 BRIEF 的期望值 `ff655a06c`**（`const EXPECTED = 'ff655a06c'`）⇒ 台账一变即红。
   **归因 = 判据缺陷（期望值过期）**，不是产品缺陷；修法 = 期望值改为**运行时从部署台账取**（或改为「最近 success 部署 == 当前环境声明」的关系式断言）。
   ⚠️ 本线**未**改判据去凑绿（那样就成了「改判据让红灯消失」），只如实登记。
2. **`LB1-SETUP-category-gap`（真读数，仍开放）**：升级后仍复现「本线命名域初始 0 分类 ⇒ 需先建分类才能建商品」，与 **#6295**（main 上仍开放）一致 ⇒ **F4 不是老构建伪影**。

### 9.4 对 §7「结论射程」的更新

- 升级后重放**支持**这样的读数：§2 的 **F1 / F2 / F3 是「老构建 `de614623d` 上的缺陷」**（main 上已消失，与本线当初的坐标声明自洽：本线当时**没有**把它们归因给 main）。
- **F4 两条构建点上都成立**（老构建 + main 均 fail）⇒ 它可上升到「main 现状」层。
- 本线**仍不下「验收通过 / 交付完成」**结论；升级后是否放行由集成侧/独立复核按 `replay-postdeploy` 的读数与 §5 未覆盖清单裁定。

---
