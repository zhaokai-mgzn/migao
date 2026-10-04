# 线③ 并发竞态 sweep 报告（租户 25 + 临时对照租户 26）

- **日期**：2026-10-04（本机时区 Asia/Shanghai，UTC+8；观测窗口 `09:04`–`09:24` +08）
- **产物目录**：`acceptance/2026-10-04/race-sweep/`（`REPORT.md` + `harness/` + `out/`）
- **一句话结论**：**跨租户 `TenantContext` 串号（C 组 5 条）与「同一入库单并发过账恰一个赢家」（W1/W2）、状态流转并发终态（W6）、幂等键并发去重（I1–I4）在本轮未发现异常；但同资源并发写面暴露 3 条产品缺陷（台账链断裂、并发确认收款超卖、同 runId 并发盘点 5×500）与 1 条发货面幂等缺失，且**被测面实测构建点 = `de614623d`（非台账声称的 `ff655a06c`）**。**
- **本线是否改产品代码**：**否**。只在 `race-sweep/harness/` 新增/复制探针脚本，未触碰 `backend/**`、`frontend/**`、`.github/cases/**`、`CHANGELOG.md`；未跑 `verify-all.sh gate` / 全量 pytest（重活锁纪律）。
- **LLM 调用**：**未派发任何 LLM 评测**（#4262）。唯一 LLM 触点是 `POST /api/auth/register` 的产品入驻 AI 甄别（BRIEF §4.3 **指定路径**）：实测 1 次，返回 `status=approved`（`out/fixtures.json::register`）。
- **纪律**：写操作只碰探针对象（`race-sweep` 前缀 + 入驻流程建的临时租户 26）；判据只在本线命名空间（探针 SKU / 探针单号）内断言，**未**断言任何租户级全局计数或整表不变。

---

## 0. 被测构建点（先后声明，再看结论）

| 项 | 读数 | 采集方式 |
|---|---|---|
| 台账声称的构建点 | `ff655a06c`（2026-10-04 05:47 +08 部署） | `gh run list --workflow=deploy-admin-api.yml` |
| **行为实测构建点** | **`de614623d`**（2026-10-02 10:22:50 UTC，落后 `origin/main` 152 提交） | `out/buildpoint-shape-sample.json`：**12/12 连续采样** `/api/admin/production/orders/{id}/ship` 均为 legacy 形状（`data={order_id,status}`、`order_shipments` 零行、`client_request_keys` 零行）—— 与 `git show de614623d:.../ProductionController.java` 第 235 行 `Map.of("order_id", orderId, "status", "shipped")` **逐字一致**；而 `git show origin/main:...ProductionController.java` 的 `shipAtomic` 会额外落 `shipment_no`/`shipment_source` |
| 部署腿 | 最近一次 `deploy-admin-api` success = `2026-10-03T21:47:10Z`（= 10-04 **05:47 +08**）；其后 `2026-10-04T00:30:01Z`（= **08:30 +08**）run = `failure` | `gh run view 37165129713` 远端输出逐字：`PREV_GOOD_TAG=sha-de61462`、`❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建`、`部署失败…且自动回滚（tag=sha-de61462）也失败` |
| 归因口径 | **本报告全部 fail 读数取自 `de614623d`，需在环境升到 `origin/main` 后复验** | 与集成侧独立结论一致（已开单 **#6294**，P0·部署） |

> `LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live` 只是启动口径里用于记录**本地**构建点的变量；本报告不含任何本地 :8080 读数，**读数一律取自 `https://api.migaozn.com`**。

**复算命令**（逐字）：

```bash
cd "/Users/guangzhen.zk/ai native/migao"
API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
OUT_DIR=acceptance/2026-10-04/race-sweep/out \
bash acceptance/2026-10-04/race-sweep/harness/run-all.sh     # 逐条跑 probe-write / probe-idem / probe-cross
node acceptance/2026-10-04/race-sweep/harness/probe-redproof.mjs   # 红证与判别对照
node acceptance/2026-10-04/race-sweep/harness/cleanup-a.mjs        # 清理租户 25 探针对象（已执行）
node acceptance/2026-10-04/race-sweep/harness/_final-read.mjs      # 现取残留读数
```

---

## 1. 四态汇总

| 套件 | pass | fail(产品) | skip(未覆盖) | 总计 | 产物 |
|---|---|---|---|---|---|
| `probe-write`（同资源并发写 W） | 4 | **4** | 0 | 8 | `out/probe-write*.json` |
| `probe-idem`（幂等键并发 I） | 4 | **1** | 1 | 6 | `out/probe-idem*.json` |
| `probe-cross`（跨租户串号 C） | 5 | 0 | 0 | 5 | `out/probe-cross*.json` |
| `probe-redproof`（红证/判别对照 RP） | 4 | 0 | 0 | 4 | `out/probe-redproof*.json` |
| **合计** | **17** | **5** | **1** | **23** | — |

**假红（判据缺陷，已修正、不计入产品 fail）= 4 条**：
1. W6 首版：用 `draft` 商品打 `/api/admin/products/batch/on-shelf`（该端点只认 `off_sale→on_sale`，逐条 `addError` 却整体 200）⇒ 已改为「先 `/status` 推到 on_sale，再并发交叉上下架 + 回执/终态自洽」。
2. C4 首版：跨租户 id 取用映射写反（A 实际读了自己的商品）⇒ 已修正并补**正对照**（各自读自己的必须 200，防「一律 403」的假绿）。
3. RP1 首版：回执行字段名取错（`results[0].status` vs 正本 `replayedCount`）⇒ 已修正。
4. W4/W6/W7 首版夹具：建品传 35 字符 `skuCode` ⇒ 500（见 §4 观察项 O1），被我读成「建品失败」⇒ 已改短 `skuCode` 并加退避重试。

**逐条判定**

| ID | 判据 | 结论 | 关键读数 |
|---|---|---|---|
| W1 | 同一草稿入库单 8 并发过账 ⇒ 恰一个赢家 | pass | `200,409×7`；库存 90→110（Δ20）；该单号台账 1 行 |
| W2 | 同一草稿单同时 `post` × `cancel` ⇒ 状态/响应/库存/台账自洽 | pass | `409,200`，库侧 `cancelled`，库存不变、台账 0 行（**仅 1 轮，覆盖强度有限**） |
| W3 | 同 SKU 两草稿并发过账 ⇒ 净增量 = Σdelta | pass | 库存 65→90（Δ25），台账 Σdelta 25 |
| **W3b** | 并发过账的台账行必须**首尾相接** | **fail** | 两行 `65.0→75.0` / `65.0→80.0`（**同基**），链断 1 处 |
| **W4** | 库存 10 米、两单各 8 米并发确认收款 ⇒ 不得超卖 | **fail** | `[200,200]`，库存 10→**0**（只扣 10），台账 delta `-8`/`-10` |
| **W5** | 同 runId 并发盘点 ⇒ 可读回执、分录恰 1 行 | **fail** | `[500×5, 200]`；分录 1 行、库存 Δ-3 正确（防双记有效） |
| W6 | 同一商品并发交叉上下架 ⇒ 终态与回执自洽 | pass | 8/8 = 200、5xx 0、`success=[1,0,1,0…]`、终态合法 |
| **W7** | 洁净 SKU（库存 0）两草稿并发过账 ⇒ 净增量与链同时对 | **fail** | 库存 100→125（Δ25 正确），台账 `100.0→115.0` / `100.0→110.0`（同基） |
| I1 | 同 `X-Client-Request-Id` 6 并发建单 ⇒ 恰一副作用 | pass | 6×200、同一单号、库侧 1 行、`client_request_keys` 1 行 |
| I2 | 无键并发 3 并发同体（对照） | pass | 库侧 3 行（证明 I1 的「恰 1」来自幂等键） |
| I3 | 同键 + **不同请求体**并发 ⇒ 只认首次 | pass | 两体订单行 `1/0`，回放同一单号 |
| I4 | 同键**顺序**两次（判别对照） | pass | 同一单号、库侧 1 行 |
| I5 | 商家表单建单面是否消费幂等键 | **skip（如实登记）** | `/api/admin/orders` **不消费**（3 并发落 3 单、占位 0 行） |
| **I6** | 发货面同键并发 ⇒ 占位 1、发货单 1、状态恰流转一次 | **fail** | `[200,422,422,422]`、占位 0、发货单 0、`orders.status=shipped` |
| C1 | 120 并发交错列表读 ⇒ 响应中本线对象必属本租户 | pass | 核对探针对象 **2160** 次 ⇒ 跨租户 **0**；窗口重叠对 7140 |
| C2 | 并发跨租户按 id 读 ⇒ 一律 403/404 | pass | 9 对全部 404 |
| C3 | 伪造 `X-Tenant-Id`（对方/-1/超大）⇒ 归属仍由 JWT 决定 | pass | 4×200、越租户 0 |
| C4 | A/B 并发混合读写（各建各的 + 各读对方 id + 各读列表） | pass | 跨读 `[404,404]`、正对照 `[200,200]`、各自写入 1 行、串号 0 |
| C5 | 160 并发（> Tomcat 线程）交错读 | pass | 核对 **2880** 次 ⇒ 串号 **0**；重叠对 12720 |
| RP1 | 同 runId **顺序**重复盘点（判别对照） | pass | 第二次 `changed=0,replayed=1`、分录 1 行（**对照 W5 的 5xx**） |
| RP2 | 台账链判据注入（红证） | pass | 合法链报 0 处；合成「同基」链报 1 处 |
| RP3 | 顺序双击过账（判别对照） | pass | `[200,409]`、库存 Δ1、台账 1 行 |
| RP4 | 跨租户判据注入（红证） | pass | 合成「租户 25 列表含租户 26 探针商品」⇒ 被判 1 个 |

---

## 2. 真缺陷清单（每条 = 最小复现 + 会红判据 + 判别性对照 + 根因符号 + 证据引用）

### F1（fail 产品）并发过账同一 SKU ⇒ `stock_ledger_entries` 的 `before_qty` 同基、台账链断裂

- **最小复现**：建两张同 SKU（探针 SKU）草稿入库单（10 米 / 15 米）→ 用同一 microtask 门控**同时** `PATCH /api/admin/inbound-orders/{id}` body `{"action":"post"}` → 查 `stock_ledger_entries`。
- **会红判据**：W3b（`before == 前一行 after` 且首行 `before == 窗口前库存`）；洁净复现 W7 同判据。
- **实测**：两行 `65.0→75.0`、`65.0→80.0`（**同一 before**，链断 1 处；`sameBaseConcurrentRead=true`），但库存净增量正确（65→90，Σdelta=25）。洁净 SKU 复现：`15.0:100.0→115.0`、`10.0:100.0→110.0`（链断 1 处，Δ 正确）。
- **判别性对照**：RP3 顺序双击过账 ⇒ `[200,409]`、库存只加一次、台账恰 1 行；RP2 注入「同基两行」⇒ `chainCheck` 报 1 处（证明判据不是恒绿）。
- **根因符号（de614623d）**：`service/InboundOrderService.java#post` —— `BigDecimal beforeQty = StockQuantity.orZero(sku.getStock())`（事务内一次性**快照读**，无 `FOR UPDATE`）+ `productSkuMapper.receiveStock`（`stock = stock + qty` **原子自增**）+ `stockLedgerService.record(..., beforeQty, afterQty, ...)`（用陈旧快照算 after）⇒ 并发下两行同基，且 `after_qty` 都不是当刻真实库存。
- **五层归因**：① 现象层＝台账「库存为什么从 X 变成 Y」答不出（首尾接不上）；② 数据层＝`before_qty` 取读快照而非 CAS 返回值；③ 代码层＝读-改-写与原子自增混用（写用自增、账用快照）；④ 契约层＝`#4055` 明确的「链条首尾相接」不变式在并发路径失守；⑤ 机制层＝该路径没有「变更前的行锁/`UPDATE ... RETURNING`」把 before/after 与写入绑定。
- **证据引用**：`out/probe-write-raw.json::cases.W3.ledgerMine / sameBaseConcurrentRead / chainBad`；`out/probe-write-raw.json::cases.W7.ledgerMine`；`out/probe-write.json` 的 `W3b`/`W7` 记录；`out/probe-redproof-raw.json::cases.RP2/RP3`。

### F2（fail 产品）并发确认收款超卖：库存钳 0、少扣 6 米、无 4xx；台账 delta 错记 -8/-10

- **最小复现**：建洁净探测 SKU（`stock=10`）→ 建两张各 **8 米**订单 → 同时 `PUT /api/admin/orders/{id}/payment`。
- **会红判据**：W4（恰一单 `200` + 扣减恰一次 + 库存非负 + 台账链一致）。
- **实测**：`statuses=[200,200]`、`rejectedBodies=[]`、库存 `10.0 → 0.0`（**只扣 10 米，缺 6 米**）、台账两行 delta `-8.0`（`10.0→2.0`）与 `-10.0`（`10.0→0.0`）。
- **判别性对照**：同一序列**顺序**执行（`out/control-seq-oversell.json`）：首单 `200`、库存 `10.0→2.0`；第二单 **422** `商品「RCTLZOKI2R-01-28」库存不足：需要 8 米，当前仅剩 2.0 米，请先补货后再确认支付` ⇒ 同一代码在无并发窗口时**会拒**，证明 W4 测的正是并发窗口。
- **根因符号（de614623d）**：`service/OrderService.java#confirmPayment` 的 `validateStockSufficient(order)`（**读-判-写**前置校验，两请求都读到 10）+ `mapper/ProductSkuMapper.java#deductStock` 的 `GREATEST(COALESCE(stock,0) - qty, 0)` **把不足额静默钳 0**（既不报错也不留痕）⇒ 超卖不响亮。
- **五层归因**：① 现象层＝两单各 8 米都确认成功、账面只剩 0；② 数据层＝`product_skus.stock` 被 `GREATEST` 钳 0，订单却已 `confirmed`；③ 代码层＝库存校验与扣减不在同一原子判据内（校验读快照、扣减用钳位 UPDATE）；④ 契约层＝`confirmPayment` javadoc 自述「防止并发重复扣减库存」的原子性只覆盖**同一订单**，不覆盖**跨订单对同一 SKU**；⑤ 机制层＝无「SKU 行锁 / `UPDATE ... WHERE stock >= qty` + 影响行数判定」的准入。
- **证据引用**：`out/probe-write-raw.json::cases.W4`（`statuses`/`stockBefore`/`stockAfter`/`ledgerMine`/`rejectedBodies`）；`out/control-seq-oversell.json::pay2`。

### F3（fail 产品）同 `runId` 并发盘点 ⇒ 1×200 + 5×500；回执应为 `replayed`

- **最小复现**：对同一批次（探针 SKU 的批次）用**同一 `runId`** 并发 `POST /api/admin/batch-stock/stocktake` 6 次。
- **会红判据**：W5（同 runId 重复提交必须给可读回执；分录恰 1 行、库存只调一次）。
- **实测**：`statuses=[500,500,500,500,200,500]`（`INTERNAL_ERROR`）；`consumptionsForRun=1`、库存 Δ 与实盘差异一致（-3）⇒ **防双记有效**，缺陷在**回执形态**（500 而非 `replayed`）。
- **判别性对照**：RP1 同 runId **顺序**两次 ⇒ 第二次 `changed=0, replayed=1`（200）——同一代码在无并发窗口时行为正确。
- **根因符号（de614623d）**：`service/BatchStocktakeService.java#stocktake` 的读半边 `stocktakeRecordedBatchIds`（普通 SELECT，**非原子**）+ 写半边部分唯一索引 `uk_batch_consumption_stocktake (tenant_id, stocktake_run_id, batch_id) WHERE stocktake_run_id IS NOT NULL AND deleted = 0`（`out/db-index-readback.json` 现取）⇒ 两个请求同时通过读判，插入时后到者抛 `DuplicateKeyException`，未映射为业务回执。
- **五层归因**：① 现象层＝同一键的重复提交有时 500；② 数据层＝无双记（唯一索引挡住）；③ 代码层＝「读判 + 依赖唯一索引」代替「`ON CONFLICT DO NOTHING` + 影响行数判首执」；④ 契约层＝类 javadoc 自认「同一 run id 的重复请求由部分唯一索引挡住」，但没规定被挡住时的回执形态（现为 500）；⑤ 机制层＝缺 HTTP 层把该唯一冲突翻译为 `replayed`/409 的映射。
- **证据引用**：`out/probe-write-raw.json::cases.W5`；`out/db-index-readback.json::uk_batch_consumption_stocktake`；`out/probe-redproof-raw.json::cases.RP1`。

### F4（fail 产品）发货面同键并发无幂等：`[200,422,422,422]`、零占位、零发货单，订单却被置 `shipped`

- **最小复现**：建单 → 确认收款 → 同 `X-Client-Request-Id` 4 并发 `POST /api/admin/production/orders/{orderId}/ship`（body 带 `trackingNo`/`logisticsCompany`）。
- **会红判据**：I6（占位 1 行、发货单 1 张、状态恰流转一次）。
- **实测**：`statuses=[200,422,422,422]`、`client_request_keys` **0** 行、`order_shipments` **0** 行、`orders.status=shipped`；12/12 连续采样的响应形状 = `{order_id,status}`（`out/buildpoint-shape-sample.json`）。
- **判别性对照**：I1/I4 在**同一环境** pass ⇒ 判据本身有效（幂等实现存在且有效，只是 `/ship` 未接）；I5 显示商家表单建单面同样不消费幂等键（如实登记，不计缺陷）。
- **根因符号**：**de614623d 的 `controller/ProductionController.java#ship`**：签名无 `@RequestHeader(ClientRequestIdService.HEADER)`、方法体直接 `orderService.shipWithLogistics(...)` 后 `return ApiResponse.success(Map.of("order_id", orderId, "status", "shipped"))`，**不建发货单、不落幂等占位**。`origin/main` 已按 `#6157`（幂等）+ `#6181`（三步写序/事务 owner）改造（`shipAtomic` 落 `shipment_no`/`shipment_source`）。
- **归因强度**：**证据充足**——`de614623d` 源码逐字比对 + 响应形状 12/12 + 库侧三读数（占位/发货单/状态）。
- **⚠️ 必须加的归因边界**：**本读数取自 `de614623d`**；它在 `origin/main` 上**大概率已修**（同名端点已有幂等 + 发货单写入），**需在环境升到 main 后复验**（勿把它当作 main 的缺陷）。
- **证据引用**：`out/probe-idem-raw.json::cases.I6`（含 4 条响应体原文）；`out/buildpoint-shape-sample.json`。

### F5（观察，非并发，线外）`POST /api/admin/products`：`skuCode` 长度 >30 ⇒ 500（应 4xx）

- **最小复现**：`POST /api/admin/products`，`skuCode` 取 `'R'.repeat(n)`：`n=30 → 200`、`n=31 → 500 INTERNAL_ERROR`（连续采样 `8/12/16/20/24/26/28/29/30 → 200`，`31/32/34/36/38/40/44/46/47/48/49 → 500`）。
- **根因**：`products.sku_code` 列宽 `varchar(30)`，入口无长度准入（`ProductCreateRequest` 无 `@Size`），PG 报错被全局处理器翻译成 `INTERNAL_ERROR`。
- **归因边界**：`git show origin/main:.../dto/ProductCreateRequest.java` 仍无长度约束 ⇒ **main 上同样缺**，但本线**不判定其归属**，仅登记（并发射程之外）。
- **证据**：`out/run-all.log`（采样逐行）+ `harness/_trycreate9.mjs`（最小 diff 脚本）。

### F6（环境）被测面 = `de614623d`，与台账声称不一致

见 §0；证据 `out/buildpoint-shape-sample.json` + `gh run view 37165129713`。**影响**：本线所有 fail 读数须按 `de614623d` 归因；跨 152 提交的功能面差异（含发货幂等/发货单、库存台账相关修复）不在读数范围内。

---

## 3. 未覆盖清单（skip 与覆盖不足，均不折算为 pass）

| # | 项 | 原因 | 重启条件 |
|---|---|---|---|
| 1 | W2（`post`×`cancel` 交叉竞态） | **仅 1 轮**（无多轮重复）⇒ 只能证明「本轮自洽」，不能证明「无窗口」 | 环境升 main 后跑 ≥20 轮 |
| 2 | 不同 `runId` 并发盘同一批次 | 未构造（`BatchStocktakeService` javadoc 自认该形态「靠唯一索引防重复，不靠行锁」） | 追加用例 |
| 3 | 加工单生成/派工/批次扣减并发 | 租户 25 无加工单夹具链（需先走 `/api/admin/production/**` 建链） | 夹具链建好后 |
| 4 | 售后工单并发完结/派工 | 属线② 射程（本线不重复） | 线② 出结论 |
| 5 | 工人侧 `Idempotency-Key`（`/api/worker/**`） | 需工人登录会话夹具（本线未建） | 线① 夹具可复用时 |
| 6 | 跨租户**写**面（`PUT`/`DELETE` 对方对象） | C 组只覆盖「读 + 各自建品」 | 追加 C6/C7 |
| 7 | UI 层并发（双击提交、并发操作同一页面） | 本线未接无头浏览器 | 工具登记后 |
| 8 | 多实例/脏部署状态对读数的干扰 | 部署腿自 10-03 起失败（F6），无法确认后端是否单一构建 | 部署恢复后复跑 |

`skip` 条目：**I5**（商家表单建单面不消费幂等键，如实登记；非缺陷）。

---

## 4. 临时对照租户：建立 → 使用 → 清理（BRIEF §4.3）

**建立**（产品入驻流程，非直插）：

```
POST /api/auth/sms/send   {"phone":"13800138001"}                                    → 200
POST /api/auth/register   {"companyName":"米高测试环境-隔离对照","contactName":"隔离对照管理员",
                           "phone":"13800138001","smsCode":"123456","industry":"布艺纺织",…}
  → 200 {"status":"approved","message":"AI 甄别通过，欢迎入驻米高平台"}（applicationId=2106551069144797185）
  → 轮询 tenants：id=26 name=米高测试环境-隔离对照 code=shop-4c53 status=active
```

**使用**：C1–C5（跨租户并发读/伪造头/混合读写，见 §1）与 RP4；两租户各建探针商品（租户 25：`race-sweep-*`；租户 26：`race-sweep-B1-*`）。

**清理（已完成，现取读数）**：

| 读数 | 值 | 证据 |
|---|---|---|
| `select id,name from tenants` | **`[{id:25, name:'米高测试环境', code:'shop-8yn7', status:'active'}]`（只剩 25）** | `out/residue-final.json::tenants` |
| `tenants` 行 id=26 | **0**（`cleanup.json::after.tenantB.tenantsDeleted=1`；`usersDeleted` 字段为 **0** —— 见下行说明） | `out/cleanup.json::after.tenantB` |
| 租户 26 的 `users` 行 | **已不在**（可复算口径：对**含 `users` 表在内**的全 `tenant_id` 表做现取扫描 = `leftovers: []`；`totalDeletedRows=0`/`usersDeleted=0` 表示最后一次运行时表内**已无行可删**——该批行是在**前一轮（进程被 SIGTERM 打断的那轮）**删掉的，`tenants` 行则由本轮删除） | `out/cleanup.json::after.tenantB.leftovers` + `::steps` |
| 租户 26 残余扫描（所有含 `tenant_id` 的表） | **`leftovers: []`** | `out/cleanup.json::after.tenantB.leftovers` |
| 租户 25 探针残留 | products 0 · product_skus 0 · orders 0 · inbound_orders 0 · stock_ledger_entries 0 · stock_batch_consumptions 0 · client_request_keys 0 | `out/residue-final.json::tenant25_probe_residue`、`out/cleanup-tenantA.json::after` |
| 探针手机号 13800138001 的入驻申请 | 0 行 | `out/residue-final.json::tenant_applications_probe_phone` |

> **现取复算（09:55:03 +08，复核修正时刻）**：`select id,name from tenants` = **`[{id:25, name:'米高测试环境', code:'shop-8yn7'}]`（只剩 25）**；id=26 已不存在。父会话升级后重放期间曾短暂出现 id=27「米高测试环境-隔离对照」（09:54:25 +08 读数），到 09:55:03 已不在（重放侧已清）。证据：`out/tenants-now.json`。

> 清理方式：`cleanup.mjs`（临时租户 26：按 `tenant_id` 的全表 FK 容错迭代 + `users`→`tenants` 拓扑序）与 `cleanup-a.mjs`（租户 25：只按 `race-sweep` 标记与探针对象 id 做 FK 图级联，**绝不做整表/整租户删除**）。租户 25 的探针对象合计删除 215 行（`cleanup.mjs` 有效谓词轮 + `cleanup-a` 三轮 127+51+37）。

**清理过程中的失败项（如实登记，原报告此处写错，已按实改写）**：

- `cleanup-a.mjs` 的 `blocked` **共 20 条 = 10 张表 × 2 轮**，**全部是 SQL 列名错误（`kind=sql_error`），不是 FK 阻塞**（`fk_blocked` 计数 **0**）。可复算证据：`out/run-all.log` 的 `阻塞表 Top=[[...],2]` 行（该日志从未被覆盖）+ 重建文件 `out/cleanup-tenantA-historical-blocked.json`（**注明**：原始 `out/cleanup-tenantA.json` 曾被一次 `--dry` 运行覆盖 ⇒ 重建以 durable 日志为准，provenance 写在该文件内）。
- 根因（列名口径全部现取 `information_schema` 核对）：
  1. `inbound_orders` 谓词引用了 **`dye_lot`** —— 该列在 `stock_batches` / `inbound_order_items` 上，`inbound_orders` **没有**；
  2. 该坏谓词经 FK 闭包**传播**到 `inbound_labels`（子查询引用父表谓词）⇒ 同样报 `dye_lot does not exist`；
  3. `finance_transactions` 谓词引用了 **`ref_no`** —— 真实列为 `order_no` / `order_id` / `transaction_no` / `remark`；
  4. `processing_orders` 谓词引用了 **`order_no`** —— 真实列为 `processing_order_no` / `order_id` ⇒ 连带 6 张加工子表（`production_instance_repricing_logs` / `processing_position_operations` / `processing_order_sets` / `production_work_logs` / `processing_set_part_tokens` / `worker_report_audits`）全部失败。
- **归属更正**：`inbound_orders` / `inbound_labels` 是**本线自己的根表/子表**（当时租户 25 本线探针入库单 **24 行**），**不是**「其他线的对象」——原报告此句错误。
- **已修**：`cleanup-a.mjs` 的三处坏谓词按真实列名改写（`inbound_orders` 去掉 `dye_lot`、`finance_transactions` 改 `order_no`/`order_id`、`processing_orders` 改 `processing_order_no`/`order_id`）；失败分类改为 `fk_blocked` vs `sql_error` 两类，**schema 类失败一律进 `errors`**（不再出现「`errors: []` 而 `blocked` 20 条」）；新增 `--dry` 只读谓词校验。**校验读数**：`node cleanup-a.mjs --dry` ⇒ `blockedTop=[]`、`errors=[]`（无 `predicate_unparseable`），见 `out/cleanup-tenantA-dry.json`（含 dry 时**现取**的残留读数）。
- **残留扫描面已扩容**（原扫描集是盲区）：新增 `finance_transactions` / `processing_orders` / `inbound_labels` / `stock_batches` 四项，写入 `cleanup-a.mjs` 的 `ev.after`。
- **追加只读审计（`out/residue-audit.json`）**：本线窗口（≤ 09:24 +08）在上述扩容表内**无残留**——现取 3 条 `finance_transactions`、6 个 `products`、12 张 `orders` 的 `created_at` 全部落在 **09:52–09:53 +08（父会话重放窗口，≥ 09:30:44 切构建点之后）**；`inbound_labels` / `processing_orders` 均为 0。
- **本轮未重跑删除、未改环境**（按复核指令）：`--dry` 只做 `SELECT count`；重放侧收尾时用**已修好谓词**的 `cleanup-a.mjs`（不带 `--dry`）即可把两窗口的探针对象一并删净。

---

## 5. 与三线并发的隔离纪律

租户 25 同时被线①/线② 写入（观测到 `线A验收链布-*`、`线B验收商品-*` 等对象，以及线② 建的 `stock_ledger_entries reason=manual` 行）。本线因此：
- 所有判据按**探针命名空间**过滤（探针 SKU id / 探针单号 / `race-sweep` 标记），**未**断言任何租户级计数或整表不变；
- 清理**只**删本线探针对象（见 §4 表）；
- 受影响读数已显式标注：C1/C5 的「核对对象数」随环境变化（2160/2880 次），但**跨租户计数恒为 0**；
- 另登记一条环境观察：并发高峰期建品偶发 500（`probe-write-raw.json::env.productCreate`，含 10 次 requestId 原文），成因未定（**不归因**，可能与三线并发负载 + 上述 `skuCode` 边界叠加）；判据侧已用退避重试规避。

---

## 6. 交付物

- `out/*.json`：`probe-write{,-raw,-summary}.json`、`probe-idem{,-raw,-summary}.json`、`probe-cross{,-raw,-summary}.json`、`probe-redproof{,-raw,-summary}.json`、`buildpoint-shape-sample.json`、`control-seq-oversell.json`、`db-index-readback.json`、`cleanup.json`、`cleanup-tenantA.json`、`residue-final.json`、`fixtures.json`、`run-all.log`（含全部逐条日志）；
- `out/SUMMARY.json`（机器可读：`line` / `buildpoint` / `counts{pass,fail,skip,false_red}` / `findings[]` / `temp_tenant{id,cleaned,readings}`）；
- `harness/`：`lib.mjs`（**复制**自 `acceptance/2026-10-03/tenant-concurrency-sweep/harness/`，未改底座文件）+ `lib2.mjs`/`config.mjs`/`bootstrap.mjs`/`probe-write.mjs`/`probe-idem.mjs`/`probe-cross.mjs`/`probe-redproof.mjs`/`control-seq-oversell.mjs`/`cleanup.mjs`/`cleanup-a.mjs`/`run-all.sh` + 若干一次性诊断脚本（`_*.mjs`）。
> 注：**底座 `probe.mjs` / `probe2.mjs` 未运行、已从本目录移除** —— 它们硬编码上一轮的租户 20/21（该两租户已于 2026-10-04 清空），直接跑会把「侧面已不存在」读成功能异常；本线读数全部来自自建 `probe-write` / `probe-idem` / `probe-cross` / `probe-redproof`。
> `lib.mjs` 为**复制**（未修改 2026-10-03 底座文件），并在 `lib2.mjs`/`config.mjs` 中做 env 化与工装扩展。
