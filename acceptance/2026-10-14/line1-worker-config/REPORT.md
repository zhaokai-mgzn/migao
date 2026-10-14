# 线① 验收包 · 工人端 / 小程序 / 配置写面 — 2026-10-14 环境重建轮

- **执行者**：线① 验收子代理（射程 = `worker-miniapp-writeface-sweep` · `shipments-sweep` · `batch-writeface-sweep` · `config-writeface-sweep`）
- **被测面**：**本机三件套** —— admin-api `http://127.0.0.1:8080`（pid 54364，启动 2026-10-14 20:24:44 +08）· ai-agent `http://127.0.0.1:8001`（pid 30865）· admin-web `http://127.0.0.1:3001`（pid 54424）；DB = 云 dev RDS `ai_customer_service`；租户 = **tenant 32**「米高测试环境」`shop-ttf1`
- **被测构建点**：`git rev-parse HEAD` = **`90192bcac82b1d276d2793986ca9c64f47e47d16`**（`90192bcac`，subject = `chore(deps): bump dompurify to ^3.4.16（按最新 main 重建 commit + npm 10 重生成 lock） (#6655)`，commitTime `2026-10-14T11:52:37Z` = **19:52:37 +08**）；`origin/main` = `03ce170501b4d315f5a744572afbbbe65be67e10`（**读数全部归因到 `90192bcac`**）
- **观测窗口**：`2026-10-14 20:29:10 ~ 20:41 +08`（全部时间均为 **Asia/Shanghai +08**；引用 UTC 处已逐处标注换算）
- **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖)` / `假红(判据缺陷)`；**skip 永不折算成 pass**
- **不自我验收声明**：本包**只产读数 + 判定 + 证据**，**不下**「验收通过 / 评测 OK / 交付完成 / 已达标」类结论

---

## §1 一句话结论

**空租户 tenant 32 的首单端到端链与工人端/小程序/配置的绝大多数写面在本轮构建点上是活的**（冷启动链 7/7、扫码闭环 24/24 + 1 skip、配置写面 68/73、批量写面 57/63、发货写面 69/78），
**但本线实测到 4 条判据会红的真缺陷**（1 条并发删除语义、3 条发货写面边界：`orders.shipped_at` 越界 / 商家发货路不认幂等键）；
**同时 24 条 fail 是判据侧问题**（期望值过期 12 条、夹具漂移 9 条、环境注入 3 条），其中**用户点名的三条（`W0-00b` / `W1-00` / `W6-05`）我都独立复核，结论两条与用户描述一致、一条与我的实测相反**（见 §3）。

---

## §2 四态汇总表（按套件；原始读数）

| 套件 | pass | fail | skip | 假红 | 控制项 | total |
|---|---|---|---|---|---|---|
| P0b 空租户冷启动链（商品→下单→收款→加工单→工序实例） | **7** | 0 | 0 | 0 | 0 | 7 |
| W·P1 工人身份面 | 16 | 0 | 0 | 0 | 0 | 16 |
| W·P2 扫码闭环 | 24 | 0 | **1** | 0 | 0 | 25 |
| W·P2b 裁高读面 | 3 | 2 | 0 | **2** | 0 | 5 |
| W·P3 小程序入库写面 | 9 | 9 | **1** | **9** | 0 | 19 |
| W·P4 小程序其余写面 + C 端上传 | 16 | 4 | 0 | **4** | 0 | 20 |
| W·P5 UI 级（真机驱动） | 1 | 4 | 0 | **4** | 0 | 5 |
| SHIP 发货写面（p1..p7） | 69 | 5 | **4** | 3 | 1（R0） | 78 |
| BATCH 批量/上传/并发（a1,b1,d1,e1,f1） | 57 | 6 | 0 | 4 | 1（F4） | 63 |
| CONFIG 配置写面（p1..p6） | 68 | 1 | **4** | 1 | 0 | 73 |
| **合计** | **270** | **31** | **13** | **24** | **2** | **311** |

> **fail 31 的四态拆分**：真缺陷 **4**（§4）+ 判据侧假红 **24**（§5）+ 故意失效控制项 **2**（`BATCH/F4`、`SHIP/R0-VACUOUS-CONTROL`，逐字自述「本条预期就是 fail」，**不计缺陷**）+ 1 条归并差额（`SHIP/K3-3` 在假红清单按判据侧列示，与真缺陷不重复计）。
> **skip 13 条**不折算 pass（§6）。

**逐段原始读数落盘位置**：`out/bootstrap-chain/P0b-chain.json`、`out/worker-miniapp-writeface-sweep/P{1,2,2b,3,4,5}*.json`、`out/shipments-sweep/p{1..7}-records.json` + `summary.json`、`out/batch-writeface-sweep/*.json` + `SUMMARY.json`、`out/config-writeface-sweep/p*.json` + `run-all-summary.json`；编排日志 = `out/run.log`。

### 前置链：空租户冷启动（**本轮独有价值**，独立判据）

`2026-10-03` 两套 harness 的 P2/P2b/P4/P5 都 `throw 找不到可参照的工序实例（夹具无法搭建）`（`lib.mjs::pickOpTemplate` 依赖已存在的 `processing_position_operations`）——因为 tenant 32 **开箱 0 商品 / 0 订单**。
按 BRIEF §3「缺前置就补跑前置段」，我用**既有** `acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs`（**未修改**）补跑前置链，并把它本身当一条独立判据：

| id | 判据 | 读数（`out/bootstrap-chain/P0b-chain.json`） |
|---|---|---|
| `CH0.category` | `POST /api/admin/categories` 2xx ∧ DB 有行 | HTTP 200，`categoryId=01e509933be1c3e941ae36990dfbb3d7` |
| `CH1.product+sku` | `POST /api/admin/products` 2xx ∧ `product_skus` 恰 1 行 | HTTP 200，`productId=736e8223ba6ed8dca749f499937f4183` |
| `CH2.order-with-product-id` | 下单 2xx ∧ `order_items.product_id == 请求值` | `product_id=736e…4183` 与请求一致 |
| `CH3.prepay-gate` | **负对照**：未确认收款不得出加工单 | HTTP 200 ∧ 未生成（`false`） |
| `CH4.confirm-payment` | `PUT /payment` 200 ∧ `orders.status=confirmed` | 一致 |
| `CH5.generate-processing-order` | 2xx ∧ per-order `success≠false` ∧ 工序实例 ≥1 | `poId=a8a7a684…290b`，工序实例 **2** 行 |
| `CH6.e2e-empty-tenant-first-order` | 四段端点全 2xx + 三段 DB 复读一致 + `set_id` 非空且 `qty>0` | 可扫码工序实例 = **2** ⇒ **空租户首单端到端可用** |

> 补跑后 `p2/p2b/p4/p5` 由「抛错 exit 1」变为「有判定」（见上表）⇒ 前置链本身是本轮缺它不可的一环。
> ⚠️ 该链**不是零残留**：链对象的 id 由**服务端生成 UUID**（`orderId=01cceb1e…`、`poId=a8a7a684…`），**不带** `CHAIN_ID_PREFIX`（`lac`）前缀 ⇒ `lib.mjs::cleanupProbe()` 的 `id like 'lac%'` **命中不了它们**，而 `cascade` 谓词又依赖它。我按 `.chain.json` 的**确切 id** 逐一清理（§7），并把这条口径差登记为判据侧问题（§5-K）。

---

## §3 用户点名的三条「非产品」形态：我的独立判定

| 用户所述 | 我的独立判定 | 判别证据（我自己现取） |
|---|---|---|
| `W0-00b` = 构建点自检 | **同判定：判据侧（构建点自检 / 环境注入）** | `p1-selftest-f8.mjs:32-36`：`bp.hasFix` 来自 `buildPoint()`；`sweep.mjs:199` 的 `worktree` 默认 = `process.env.LIVE_WORKTREE \|\| '/Users/guangzhen.zk/migao-wt/main-live'`。prod 未设该变量 ⇒ 回落**本机不存在**的路径（`ls` ⇒ `No such file or directory`）⇒ `execFileSync('git','-C',…)` 抛错被 `catch { hasFix=false }` 吞掉 ⇒ 判「不含 #6102 修复」。**这是「取不到真值 → 默认 false」的假红**，不是产品 |
| `W1-00` = 新增工序被「部位矩阵」校验拒（夹具用了矩阵里没有的部位名） | **同判定：判据侧（夹具漂移）** | `out/config-writeface-sweep/p1-selftest-f8.json` 的 `W1-00` 逐字：`HTTP 422 … "未知部位「通用」：只接受矩阵里已有的部位（布帘/纱帘/帘头/布料）或基线三部位（布帘/纱帘/帘头）"`。夹具（`p1-selftest-f8.mjs:52`）**故意**用 `positions:['通用']` 去构造「矩阵里没有布帘行」这一 F8 前置 ⇒ 新校验（合法护栏）把它拒了 ⇒ **F8 正对照的锚点建不出来**，`W1-00` 之后的正对照整段失效。**产品行为正确；夹具需改成「基线三部位里取一个而矩阵里没有的」** |
| `W6-05` = 算料公式写面**在 `craft_calc_configs` 增行** | 🔴 **与我的实测相反：本轮 `W6-05` 判定 pass（未增行），但真正的问题在别处 —— 该写面改的那一行 config 值没有被还原** | `out/config-writeface-sweep/p6-other-config.json` 的 `W6-05` 证据逐字 `craft_calc_configs.ccc-32.margin_multi: 0.31 → 0.32 [field]`（**行已存在**，是 UPDATE 不是 INSERT）；`W6-05-restore` 却写 `我的行主面残留=0；还原动作=0`，并把这条 diff 归到「**非我的行**（并行包改动，未触碰）=2」。**现取 DB**：`craft_calc_configs` 全表**只有 1 行** `ccc-32`、`margin_multi=0.320`、`updated_at=2026-10-14 20:34:54.399546+08`（= 我的写入时刻）⇒ 该行**就是本 run 写的、且没被还原**。⇒ 我的判定：**不是「增行」缺陷，而是 `restoreTo()` 的归属判定把「我改的配置行」误判为「别人的行」⇒ 写面残留**（判据侧，§5-E）。产品侧 `PUT /api/admin/craft-calc-config` 是**全量替换**语义，写一行租户级配置是设计行为 |

---

## §4 真缺陷清单（4 条）

### L1-F1【BATCH · 并发语义】并发 5 次 `DELETE /operations/{id}/detach-and-delete` 同一工序 ⇒ **3 次 HTTP 200**（应恰 1 次成功）

- **最小复现**：`POST /api/admin/production/operations`（前缀「线②验收」探针工序）→ 对 `DELETE /api/admin/production/operations/{id}/detach-and-delete` **并发 5 次**（`Promise.all`）→ 读 HTTP 码数组与终态。
- **逐字读数**（`out/batch-writeface-sweep/E4-detach-concurrent.json`）：
  ```json
  { "createHttp": 200, "concurrentHttp": [200,200,200,422,422],
    "after": { "id": "e1f7177549b39c099fc496a6309dd4a8", "deleted": 1 } }
  ```
  `out/batch-writeface-sweep/run.log:80` 的 `E4.1` 判据行逐字：`实测 HTTP=[200,200,200,422,422] 200 次数=3；DB={"id":"e1f7177549b39c099fc496a6309dd4a8","deleted":1}`。
- **会红判据**：`成功(200) 次数 == 1 ∧ 其余 4xx ∧ 终态 deleted==1`（本条**已经红了**，红有效）。
- **根因符号/文件**：`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:739` `detachAndDeleteOperation` → `ProductionOperationCommandService.deleteDetaching`（**check-then-act**：先判「已删/护栏」再摘格+软删，中间无 CAS/行锁）。
- **对照（同套件的正例，证明判据有判别力）**：`E3.1`（终态对象并发写 status）⇒ `HTTP=[404,404,404,404,404]`；`E2.2`（并发写负库存）⇒ `[422×5]` ⇒ **同套件别的并发面都收敛成单赢，只有这一条不收敛**。
- **五层归因**：① 现象 = 同一删除请求并发下 3 次被接受；② 直接因 = 第 2/3 次进入时未观察到「已软删」这一既有终态；③ 服务端因 = `deleteDetaching` 的判定与写入在同一事务但**不在同一行锁**上（默认 READ COMMITTED，双方都先读到未删）；④ 流程因 = 该端点是 #4665 的「一键删」新写面，`E4.1` 是本轮**唯一**覆盖它并发性的判据；⑤ 影响 = **终态正确（`deleted=1`）、无半完成、无脏数据**（实测），风险面限于「重复响应 200 让调用方以为多次生效」与潜在重复摘格/重复写账路径。

### L1-F2【SHIP · 不变量】发货写面在 `orders` 上**多写一列 `orders.shipped_at`**

- **最小复现**：工人 session 对一张 `confirmed` 订单 `POST /api/worker/shipment/orders/{id}/ship`，前后对比 `orders` / `order_items` 字段级 diff。
- **逐字读数**（`out/shipments-sweep/p4-records.json` 的 `W1-2`）：
  `越界明细: ["orders.shipped_at: null → \"2026-10-14T20:32:59.195747+08:00\" [field]"]`；
  全部变化（表.字段去重）= `["order_logistics.*","order_shipment_items.*","order_shipments.*","orders.shipped_at","orders.status"]`。
  `W1-3` 逐字：`diff: ["orders.shipped_at: null → …","orders.status: \"confirmed\" → \"shipped\" [field]"]`。
- **会红判据**：`变化集 ⊆ payload 键 ∪ 显式声明审计列`（`p4-writeface-equivalence.mjs` 的 `AUDIT` 允许集含 `orders.status`/`updated_at`，**不含** `orders.shipped_at`）。
- **根因符号/文件**：工人发货写面（`WorkerShipmentController` → 发货服务）在订单主表写状态**同时写 `shipped_at`**；判据侧锚点 = `acceptance/2026-10-03/shipments-sweep/harness/p4-writeface-equivalence.mjs`。
- **五层归因**：① 现象 = 订单表多一列被改；② 直接因 = 写面比 payload 契约多写 `shipped_at`；③ 服务端因 = 发货成功路径顺手落「发货时间」（是否属**有意的**审计列待裁定 —— 若有意，则应进 `AUDIT` 允许集并在类注释写明）；④ 流程因 = 该断言是「写后等价性」类，**没有**随写面新增列同步维护允许集；⑤ 影响 = **不涉钱、不改数量、不改库存**（`order_items.quantity` 零变化），影响面 = 契约/审计口径。

### L1-F3【SHIP · 幂等语义】商家发货路**不认 `X-Client-Request-Id`**：同键两次调用都不回放

- **最小复现**：`POST /api/admin/production/.../ship` 携带同一个 `X-Client-Request-Id` 调两次（中间换运单号），读 `order_logistics.tracking_no` 与 `client_request_keys` 命中数。
- **逐字读数**（`out/shipments-sweep/p5-records.json` 的 `K3b-1`）：
  `R1(200) tracking=SF-FIRST-7777` / `RA(422) tracking=SF-FIRST-7777` / `RB(422) tracking=SF-FIRST-7777`；
  `client_request_keys 命中: []（空 ⇒ 该端点从未接幂等键）`；
  代码依据逐字：`ProductionController.ship 直接转发 orderService.shipWithLogistics，未走 ClientRequestIdService.claim`。
- **会红判据**：`同键重复写 ⇒ 回放首次结果 ∧ client_request_keys 有该键`。
- **根因符号/文件**：`ProductionController.ship`（商家发货路）**未接** `ClientRequestIdService`（对照：worker 入库草稿/过账路**接了**，见 `P3` 的 `D7`/`D11` 判据）。
- **五层归因**：① 现象 = 同键两次都执行；② 直接因 = 端点不 claim 幂等键；③ 服务端因 = 该路径只做了「重复发货 ⇒ 422 + 可行动文案」的保护（**实测第二次 422 且 tracking 未被覆写 = 本轮的破坏性副作用为零**）；④ 流程因 = 幂等契约（#4037）在端点枚举里被漏接，判据则假设它已接；⑤ 影响 = **本轮实测未观察到数据破坏**（shipments/logistics 仍各 1、tracking 保持不变），风险面 = 「调用方按 200 判成功、按 422 判失败」时的重试语义不可依赖。

### L1-F4【SHIP · 不变量】`W1-3`：`orders` 仅允许 `status/updated_at` 变化 —— 实测改动含 `shipped_at`

- 与 L1-F2 **同源**（同一次写面、同一份 diff），此处单列是因为它是**另一个 id** 的判据（`W1-3` 的命题更窄：`order_items.quantity` 必须零变化 ∧ `orders` 仅 `status/updated_at`）。
- **读数**：`out/shipments-sweep/p4-records.json` 的 `W1-3` 逐字 `实测 ["orders.shipped_at","orders.status"]`（`order_items` 侧**确实零变化** ⇒ 命题的另一半是绿的，缩小了影响面）。
- **会红判据**：`order_items.quantity 无变化 ∧ orders 仅 status/updated_at 变化`。

---

## §5 判据侧问题清单（假红 / 夹具漂移 / 期望过期，各带判别证据）

| # | id | 类别 | 判别证据（为什么不记产品账） |
|---|---|---|---|
| A | `P2b/N1` | **期望值过期伪影** | 判据行逐字期望「product_id 为 NULL ⇒ **HTTP 500**（NPE at positionRow）」，实测 `product_id=NULL ⇒ HTTP 200`；`WorkerCuttingHeightService.java:163-164` 现码已有 `String productId = item == null ? null : item.getItemProductId(); row.put("brand", productId == null ? null : brands.get(productId));`；`git merge-base --is-ancestor 24b7381d1 HEAD` = **YES** ⇒ **修复已在被测构建点内**，判据钉在旧构建（`de614623d`）的行为上 |
| B | `P2b/N5` | **期望值过期伪影** | 单变量三步期望 `200→500→200`，实测 `200→200→200`（同 A 根因）。注：`N5` 的 evidence 里还引用了 `2026-10-03/out/main-live-round3-api-envfix.log:6605` 的旧栈 ⇒ **判据的证据锚也过期** |
| C | `P3/D5,D7,D9,D10,D11,D12,D16,D17,D18`（9 条） | **夹具漂移** | 夹具送 `quantity:'7.5'`（**米数**），而服务端逐字拒绝并给可行动文案：`「商品明细第 1 项的卷数必须是正整数（收到 7.5）：拍照入库按「卷数 × 每卷米数」记账；散米 / 尾料请走商家端手工入库」`；源码锚点：`backend/admin-api/src/main/java/com/migao/admin/dto/WorkerInboundDraftRequest.java:41`（**issue #6812**：工人拍照入库单里该字段 = **卷数（正整数）**）⇒ **产品校验是设计行为**，夹具未随 #6812 更新 |
| D | `P4/E16,E17,E18,E20`（4 条） | **环境注入（JWT 密钥错配）** | 四条全部 `HTTP 401 {"code":"TOKEN_INVALID","message":"Invalid token: Signature verification failed"}`；**我自己现算**：`~/migao-keys/jwt-private.pem` 推导出的公钥 ≠ `backend/ai-agent-service/.env` 的 `JWT_PUBLIC_KEY`（`False`）⇒ harness 用私钥签、被服务的公钥验失败，**不是上传校验缺陷** |
| E | `CONFIG/W6-05-restore`（判定侧） | **归属判定缺陷 + 写面残留** | 见 §3 第三行：`W6-05` 的 diff 明确是 `ccc-32.margin_multi 0.31 → 0.32`（**我的写入**），但 `restore` 把它归到「**非我的行**（并行包改动）=2」并判 `残留=0`；现取 DB `margin_multi=0.320` + `updated_at=20:34:54.399546+08`（= 我的写入时刻）⇒ 归属判反了。**已由我手工还原到 0.31**（§7） |
| F | `P5/U2,U3,U3b,U4a`（4 条） | **夹具漂移（UI 契约变更）** | 实测页面 id 集 = `["wh5-error","wh5-enterprise-code","wh5-worker-no","wh5-pin","wh5-login"]`（**没有** `wh5-code`/`wh5-scan`）；网络面 `POST /api/worker/login ⇒ 422 "无法识别租户：请填写企业编码（向商家索取，例如 migao）"`；源码锚点：`frontend/worker-h5/src/api.mjs:6-7` 逐字「body 送 `enterpriseCode`，**不再**送 `tenantId`」（**issue #6564**，提交 `0478ca5ff`）、`scan-input.mjs:97 enterpriseCodeFromLocation` 读的是 `?tenant_code=`。p5-ui（`2026-10-03`）仍用 `?tenant_id=` + `#wh5-code` ⇒ **装置与页面契约脱节** |
| G | `BATCH/B2.1,B2.3` | **夹具漂移** | `B2.3` 期望逐字「**租户 21** 的商品 undefined 在调用后 deleted=0 且行仍在」⇒ 对照租户写死 `21`，而**租户 21 不复存在** ⇒ 目标为 `null`、断言空转判红 |
| H | `BATCH/F2` | **判据/清理口径缺陷** | 注入行 `l2dup514528d44700dc51a45c` 的删除 SQL 与注入 SQL 都在证据里（逐字），`delete where id='l2dup…'` 只可能删 0 或 1 行，而计数读面 `restored=2` ⇒ **第二次计数/清理口径**缺陷（非产品） |
| I | `BATCH/F3` | **红证注入通道缺陷** | 注入 -5 **走 API**，被**合法护栏**拒绝（`E2.1` 的期望行为逐字：`HTTP 422 … "库存 stock 不能为负…当前值 -5 —— 请改为不小于 0 的值后重试（服务端不做静默归零）"`）⇒ 注入未生效 ⇒ 「判据当场红」不可能成立（**有一条绿的判据反而证明了护栏是活的**） |
| J | `SHIP/K3-3` | **期望值过期** | 期望「幂等重发不报错 ⇒ 2xx」，实测 422 + 服务端逐字可行动文案 `「本次未发生订单发货流转，因此未新增发货单（若只是改运单号，请用物流改单入口）」`，且 `shipments=1 ∧ logistics=1 ∧ tracking=SF-ADMIN-1 未被覆写` ⇒ 现形态是**显式拒绝 + 零副作用**，判据该按「不变量」而非「2xx」写 |
| K | `bootstrap-chain` 的清理口径 | **命名域口径过期** | 其类注释逐字「命名域：链对象 = `lc` 前缀 + …；收尾：`cleanup-chain.mjs` 按 `lc` 前缀删除」，但实测 `orderId=01cceb1e85eef72a085734579c812822` / `poId=a8a7a6849debfd9d7d25bc0461f8290b` = **服务端 UUID**，`id like 'lac%'` 命中 0；且**该脚本在本轮检出里不存在**（`ls` 无 `cleanup-chain.mjs`）⇒ 链残留无法用声明的方式自清（我已按确切 id 清，§7） |
| L | `shipments-sweep/lib.mjs::nowCST` | **装置缺陷（时间口径）** | 该函数显式拼 `+08` 后缀，但取的是 `new Date()`（无 `TZ` 时 = UTC 墙钟）⇒ 实测日志把 `20:32:33 +08` 打印成 `2026-10-15 04:32:33 +08`（**早/晚 8 小时错标**）；对照 `worker-miniapp-writeface-sweep/lib.mjs` 用 `Intl.DateTimeFormat(timeZone:'Asia/Shanghai')`（正确）。**不影响任何判定，但污染证据时间戳** |
| M | `worker-miniapp-writeface-sweep/SUMMARY.json` 的 `buildPoint` | **期望值过期伪影（元数据）** | 该文件的 `buildPoint.how` 逐字写「`git -C /Users/guangzhen.zk/migao-wt/main-live rev-parse HEAD` …；服务地址与健康读自 `acceptance/2026-10-03/env/env-round3.json`」⇒ 指向**已删除**的 worktree 与 **2026-10-03** 的环境文件；实际行为读数（HTTP/DB）取自本轮 `90192bcac`（`out/run.log:2` 逐字 `构建点: worktree=/Users/guangzhen.zk/ai native/migao sha=90192bcac`）。**读 SUMMARY 的人必须以 run.log 为准** |

---

## §6 未覆盖清单（`skip` 及原因与重启条件）

| # | 未覆盖项 | 原因（逐字来自读数） | 重启条件 |
|---|---|---|---|
| 1 | `P2/C17.cross-tenant-object` | `租户 21 无「码 + 待做工序」的夹具（无可用对象），本判定未覆盖` | 存在第二个**带工序夹具**的租户时重跑（**不得**用 tenant 32 自己的对象冒充对照）；本轮 tenant 34「米高测试环境-隔离对照」（线③ 20:35:03 建）无该夹具 |
| 2 | `P3/D21.cross-tenant-label` | `租户 21 无标签短码夹具 ⇒ 未覆盖（不冒充已验）` | 同上 |
| 3–6 | `SHIP/P2-EXPORT`·`K1-2`·`K2-RESTOCK`·`K4-INBOUND` | 逐字「**不存在**（如实登记）」（枚举端点 404/405；发货无出库/回补写面） | 产品新增该写面时 |
| 7–9 | `SHIP/p5` 三条（打印/标签硬件、库存时效读面） | 无硬件 / 读面不可达 | 具备硬件或读面时 |
| 10 | `CONFIG/W6-01` | `加工费组合 POST 422：「加工项「写面横切组合292947」在加工项目录中不存在或已停用」` | 修复夹具「先建加工项再建组合」（本轮 `W6-09` 也因 `本租户没有可用的 processing_categories 行` 跳过 ⇒ **空租户缺 processing_categories 是根因**） |
| 11 | `CONFIG/W6-07` | `读面 /api/admin/worker-page-config 无数据` | 该租户先有一条页面开关配置时 |
| 12 | `CONFIG/W6-09` | `本租户没有可用的 processing_categories 行` | 同上（补 processing_categories 种子） |
| 13 | `CONFIG/W6-14` | `读面无可复用的字符串键（键=tenantId）` | 读面出现字符串键时 |
| — | **UI 级写面旅程（真机）** | 本轮 `P5` 的 4 条判据全部落在**夹具漂移**上（§5-F）⇒ **「登录 → 当前工人 → 扫码 → 开工落库」这条 UI 级写面旅程在本轮实为未覆盖**（`U5.ui-report-writes` 根本没跑到）。**不以「页面能打开」冒充已验** | 按 #6564 契约改夹具（`?tenant_code=shop-ttf1` + 填 `#wh5-enterprise-code`）后重跑 `p5-ui` |

> **skip 永不折算成 pass**（BRIEF §3.2）：上表 13 条 + UI 旅程**均未**产生 `pass` 判定。

---

## §7 残留清理（清理前后**现取**读数）

**清理对象 = 本包命名域**：`la`/`LA`（工人、session、订单、加工单、工序实例、部位码、入库单、幂等键）+ 冷启动链的**确切 id**（`.chain.json`）+ config 写面被改的那一行值。
**未碰**任何非本线行：tenant 32 未清空；`工资验收商品-*`/`漂移验收商品-*`/`设置验收商品-*`/`路线验收商品-*`（**线②**）、tenant 34「隔离对照」（**线③**）一律未触碰。

| 时刻 | 读数（现取） | 来源 |
|---|---|---|
| **清理前**（20:40:06 +08） | `users_la=2 · orders_la=11 · orders_chain=1 · po_la=11 · po_chain=1 · ops_la=13 · ops_chain=2 · product_chain=1 · sku_chain=1 · cat_chain=1 · craft_calc_configs.margin_multi=0.320` | psql 现取 |
| **清理后**（20:40:39 +08） | 上列**全部 0**；`craft_calc_configs.margin_multi=0.310`；`users_t32_total=5`（均为非本线行，见下） | psql 现取 |
| 其它字段 | `worklogs_la=0`、发货面 `ship_orders=0 / ship_shipments=0 / worker_wfs=0` | psql 现取 |
| 各 harness 自证 | `W·SWEEP`：`零残留: total=0 clean=true`（`P0b-chain`/`Z-residue.json`）；`BATCH`：`零残留=true（products/operations/opPositions/… 全 0）`；`SHIP/P7`：`NR-1 total=0（9 张表全 0）` | 各自 `run.log` / `Z-residue.json` |

- **清理异常**：`W·SWEEP` 的 `ledgerUnchanged=false`（存量 sha256 不一致）—— 该口径是**全表指纹**，而本窗口内**线②/线③ 正在同一租户写非探针行** ⇒ 不构成「存量被改」的结论；可用的确定性替代 = 本包命名域逐表归零（上表）+ `SHIP/P7` 的九表全 0。
- **`W·SWEEP` 的 `P5-ui.json` 是 20:37 那次重跑的读数**；`P1/P2/P2b/P3/P4` 同属该次重跑（`rerun.log`）；`P3` 为**首次 run** 的读数（未重跑，因其 9 条 fail 的根因是夹具漂移，重跑不改变判定）。
- **单段重跑的装置摩擦（登记）**：`run-all` 的终态清理会删掉 `la` 探针工人；重跑前 `.store.json` 里若仍存着**已被清理**的 workerId，`p1-auth` 会 `continue` 跳过建号 ⇒ 直接 401（我实测踩到）。正确口径 = **先删 `.store.json` 再按 `p1-auth → 目标段` 顺序跑**（`rerun.log` 即此法的产物）。

---

## §8 纪律声明

- **未改产品代码**：本包读写仅限 `acceptance/2026-10-14/line1-worker-config/**`（以及 `/tmp/line1-clean.sql`、`/tmp/line1-rerun.sh`）；`backend/**`、`frontend/**`、`deploy/**`、任何既有 harness **一行未动**。
- **未跑重活**：**未**运行 `./verify-all.sh`（任何档）、`batch-gate`、全量 pytest；本包全部为轻量 HTTP/SQL 探针 + 一次 Playwright 驱动。
- **未调真实 LLM / 未派 workflow**：入库识别只走「缺图/零命中」的不调模型路径；**未**派发任何 GitHub workflow、**未**开 issue、**未**提 PR。
- **写操作只碰探针对象**：所有写面均带 `-- probe-ok` 标记（`guardedWrite`）或经探针命名域；唯一的非探针写是 §7 的 config **还原**（把 `W6-05` 自己改的值改回它自己的写前值）。
- **装置**：为跑 `p5-ui` 起了**只读**静态服务（`acceptance/2026-10-04/worker-miniapp-sweep/harness/local-jsmime-server.mjs`，`STATIC_ROOT=frontend`、`PORT=3160`，**不改任何产品/部署面**），收尾 kill。
- 时间一律 **Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）时间戳处已标注换算（`11:52:37Z` = `19:52:37 +08`）。

---

## §9 harness 目录树与一键复算

```
acceptance/2026-10-14/line1-worker-config/
├── REPORT.md                                  # 本报告
├── out/
│   ├── run.log                                # 四次 sweep 的串行编排日志（含构建点自证行）
│   ├── SUMMARY.json                           # 交付读数（counts / findings / residue）
│   ├── bootstrap-chain/                       # 前置链（2026-10-04 既有段，未改）：P0b-chain.json + P0b-step0..5 + .chain.json
│   ├── worker-miniapp-writeface-sweep/        # P1/P2/P2b/P3/P4/P5 + P0-env + SUMMARY + Z-residue + run.log + rerun.log + shots/
│   ├── shipments-sweep/                       # p1..p7-records.json + summary.json + run.log
│   ├── batch-writeface-sweep/                 # A/B/D/E/F + SUMMARY.json + Z-residue.json + E4-detach-concurrent.json + run.log
│   └── config-writeface-sweep/                # p1..p6.json + run-all-summary.json + raw-*.log
```

**一键重跑（逐字可复算；从仓库根执行）**：

```bash
cd "/Users/guangzhen.zk/ai native/migao"
# ① 前置：空租户冷启动链（缺它 ⇒ P2/P2b/P4/P5 会 throw）
REPO_ROOT="$PWD" LIVE_WORKTREE="$PWD" API_BASE=http://127.0.0.1:8080 AGENT_BASE=http://127.0.0.1:8001 \
TENANT_ID=32 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
OUT_DIR="$PWD/acceptance/2026-10-14/line1-worker-config/out/bootstrap-chain" \
node acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs

# ② 四个 sweep（逐个换 OUT_DIR）
for s in worker-miniapp-writeface-sweep shipments-sweep batch-writeface-sweep config-writeface-sweep; do
  REPO_ROOT="$PWD" LIVE_WORKTREE="$PWD" API_BASE=http://127.0.0.1:8080 AGENT_BASE=http://127.0.0.1:8001 \
  TENANT_ID=32 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
  OUT_DIR="$PWD/acceptance/2026-10-14/line1-worker-config/out/$s" \
  node "acceptance/2026-10-03/$s/harness/run-all.mjs"
done

# ③ 单段重跑（先删 .store.json，否则 p1-auth 会拿陈旧 workerId 跳过建号 ⇒ 401）
OUT="$PWD/acceptance/2026-10-14/line1-worker-config/out/worker-miniapp-writeface-sweep"
rm -f "$OUT/.store.json"
cp "$PWD/acceptance/2026-10-14/line1-worker-config/out/bootstrap-chain/.chain.json" "$OUT/.chain.json"
for seg in p1-auth p2-scan p2b-cuttingheight-npe p4-ship-upload p5-ui; do
  REPO_ROOT="$PWD" LIVE_WORKTREE="$PWD" API_BASE=http://127.0.0.1:8080 TENANT_ID=32 \
  ADMIN_PHONE=13800138000 SMS_CODE=123456 OUT_DIR="$OUT" WORKER_UI=http://127.0.0.1:3160 API_ORIGIN=http://127.0.0.1:8080 \
  node "acceptance/2026-10-03/worker-miniapp-writeface-sweep/harness/$seg.mjs"
done
# p5-ui 的静态服务（只读，收尾 kill）：
#   STATIC_ROOT="$PWD/frontend" PORT=3160 API_ORIGIN=http://127.0.0.1:8080 \
#   node acceptance/2026-10-04/worker-miniapp-sweep/harness/local-jsmime-server.mjs

# ④ 残留自证（现取）
#   psql … "select count(*) from users where tenant_id=32 and worker_no like 'LA%'"   ⇒ 0
#   psql … "select count(*) from orders where tenant_id=32 and id like 'la%'"          ⇒ 0
#   psql … "select margin_multi from craft_calc_configs where tenant_id=32"            ⇒ 0.310
```

**关键缺陷的最小复算（幂等、只读）**：

```bash
# L1-F3 的静态锚点（端点未接幂等键）
grep -n "shipWithLogistics" backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java
# L1-F1 的静态锚点
sed -n '725,745p' backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java
# §5-D 的密钥错配（现算，读私钥 + 读 .env 公钥比对）
python3 -c "from cryptography.hazmat.primitives import serialization as s;from pathlib import Path;import re;\
k=s.load_pem_private_key((Path.home()/'migao-keys/jwt-private.pem').read_bytes(),None);\
pub=k.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo).decode();\
env=open('backend/ai-agent-service/.env').read();m=re.search(r'JWT_PUBLIC_KEY=\"(.*?)\"',env,re.S).group(1).replace('\\\\n','\n');\
print('PASS' if ''.join(pub.split())==''.join(m.split()) else 'MISMATCH（签名必失败）')"
# §5-A 的过期判据核对（修复是否在构建点内）
git merge-base --is-ancestor 24b7381d1 HEAD && echo "fix #6219 已在 90192bcac 内"
```

---

## §10 交付物清单

- `acceptance/2026-10-14/line1-worker-config/REPORT.md`（本文件）
- `acceptance/2026-10-14/line1-worker-config/out/SUMMARY.json`（机器可读：`{line, buildpoint, counts:{pass,fail,skip,false_red}, findings:[…]}`）
- `acceptance/2026-10-14/line1-worker-config/out/**`（四套 harness 原生产物 + `run.log` + `rerun.log`）
