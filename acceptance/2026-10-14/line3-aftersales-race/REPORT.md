# 线③ · 售后退款 / 租户隔离 / 并发竞态 —— 2026-10-14 环境重建轮

> 执行者 = 后台验收子代理（线③）。**本报告只产读数 + 判定 + 证据，不下「验收通过 / 交付完成 / 已达标」结论**（不自我验收，BRIEF §3.1）。
> 四态：`pass` / `fail(产品)` / `skip(未覆盖 —— 永不记 pass)` / `假红(判据缺陷或无判别力)`。时间一律 **Asia/Shanghai（+08）**。

| 项 | 值 | 取证 |
|---|---|---|
| **被测构建点 sha** | **`90192bcac82b1d276d2793986ca9c64f47e47d16`**（= `origin/main`） | `git rev-parse HEAD`（本报告页首采集时刻 2026-10-14 20:29 +08） |
| 被测面 | 本机三件套 `admin-api 127.0.0.1:8080`（PID 54364）/ `ai-agent :8001`（PID 30865）/ `admin-web :3001`（PID 54424） | `bash acceptance/2026-10-14/tools/start-stack.sh status` ⇒ `:8001 HTTP 200` / `:8080 HTTP 401`（鉴权面正常）/ `:3001 HTTP 200` |
| 被测租户 | **tenant 32**「米高测试环境」`shop-ttf1` · 管理员 `13800138000` · 万能码 `123456` | `out/aftersales/B0-auth.json`：`tenantSeen=32`、`via=sms-bypass-code`、token 长度 774（`out/aftersales/B0-env.json::LB0-05`） |
| DB | 云 dev RDS `ai_customer_service`（参数现取 `backend/admin-api/.env`） | `acceptance/2026-10-14/line3-aftersales-race/q.sh`（本线只读查库助手） |
| 本线**未**改产品代码 | `backend/**` / `frontend/**` / 既有 harness **一行未动** | 本线新增物 = `acceptance/2026-10-14/line3-aftersales-race/**` 下 7 个文件：`q.sh` / `probe-w2-repro.mjs` / `run-w2-rounds.sh` / `probe-cross-tenant.mjs` / `probe-independent-math.mjs` / `run-race-probes.sh` / `REPORT.md`（+ `out/**`） |
| **禁真实 LLM** | 本线**未**派发任何评测 workflow、**未**调用真实 LLM。唯一 LLM 触点是入驻接口 `POST /api/auth/register` 的产品 AI 甄别（BRIEF 指定路径，用于建临时对照租户）：2 次，均 `status=approved` | 见 §6.1 逐字响应 |
| 禁重活 | **未**跑 `verify-all.sh gate/full`、`batch-gate`、全量 pytest | — |

---

## 0. 一句话结论

**在 `90192bcac` + 全新租户 32 的被测面上：四态 = pass 83 / fail(产品) 2 / skip 4 / 假红 3。真缺陷 2 条 —— ① `InboundOrderService#cancel` 缺 CAS 谓词 ⇒ 入库单「过账 × 作废」并发交叉竞态下 post 拿到的过账权被 cancel 抹掉，库存 +5 与入库台账行**静默留在库里**（本线独立复现 20 轮命中 3 轮）；② 全新租户 0 个商品分类 ⇒ `POST /api/admin/products` 的 `categoryId` 前置不可达。** 售后退款涉钱链路（精度准入 / 封顶 / 回补开关两侧 / 并发完结）、跨租户隔离、幂等键、盘点幂等在本轮**全部转绿**（2026-10-04 老构建上的 6 条同类 fail 已消失，均为真实修复生效，不是判据放宽）。

- **两条 sweep 结构性未覆盖**：`tenant-isolation-sweep` / `tenant-concurrency-sweep` **完全无 env 注入口**（主体矩阵与租户 id 全 hardcode 到已删除的 20/21/1），在本轮被测面上**登录即失败** ⇒ 判**未覆盖**，由本线自建 `probe-cross-tenant.mjs`（32↔34 真租户对）补测 4/4 pass（§5.1）。
- **收尾零残留**：tenant 32 本线三命名域 + race-sweep 命名域**现取全 0**；临时对照租户 34 已按 FK 拓扑序清空并删 `tenants` 行（清理前 391 子表行 → 清理后 0，`tenants` 只剩 32）。

---

## 1. 四态汇总（逐 sweep · 逐组）

### 1.1 总表

| # | harness | 原始四态（原样落盘） | 判据侧修正后 | 产物 |
|---|---|---|---|---|
| 1 | `2026-10-04/aftersales-refund-sweep/run-all.mjs` | **pass 56 / fail 3 / skip 3 / 假红 0**（62 条） | pass 57 / **fail(产品) 1** / skip 3 / 假红 2 | `out/aftersales/**` |
| 2 | `2026-10-03/tenant-isolation-sweep` | **未产生任何判据**（登录即 401 失败） | **未覆盖**（不计 pass / 不计 skip） | `out/tenant-isolation/run-all.log` |
| 3 | `2026-10-03/tenant-concurrency-sweep` | **未产生任何判据**（登录即 401 失败） | **未覆盖** | `out/tenant-concurrency/run-all.log` |
| 4 | `2026-10-04/race-sweep`（`run-all.sh` 有路径缺陷 ⇒ 改用其 4 个探针逐个跑） | **pass 18 / fail 1 / skip 1**（20 条） | pass 18 / **fail(产品) 1** / skip 1 / 假红 0 | `out/race/**` |
| — | 本线自建补测（§5） | **pass 8 / fail 0** | pass 8 | `out/aftersales/XT-cross-tenant.log` 等 |
| | **合计** | — | **pass 83 / fail(产品) 2 / skip 4 / 假红 3** | `out/SUMMARY.json` |

> 计数配方逐字见 `out/SUMMARY.json::counts_recipe`（`83 = 56 + 1 + 18 + 4 + 4`）。**skip 永不折算 pass**；sweep2/3 既然一条判据都没跑出，就既不进 pass 也不进 skip，单列「未覆盖」。

### 1.2 sweep#1 逐组（`out/aftersales/SUMMARY.json::byGroup`，原样）

| 组 | pass | fail | skip | 假红 | total |
|---|---|---|---|---|---|
| B0-环境自证 | 5 | **1** | 0 | 0 | 6 |
| B1-夹具 | 5 | **1** | 0 | 0 | 6 |
| B1-售后退款闭环(串行) | 18 | 0 | 2 | 0 | 20 |
| B2-并发竞态 | 5 | 0 | 0 | 0 | 5 |
| B2/B1-补强探针 | 11 | 0 | 1 | 0 | 12 |
| B1-涉钱精度 | 3 | 0 | 0 | 0 | 3 |
| B2-正对照 | 2 | 0 | 0 | 0 | 2 |
| B1-退款负例补强 | 3 | 0 | 0 | 0 | 3 |
| B2-并发派工 | 3 | 0 | 0 | 0 | 3 |
| Z-零残留 | 1 | **1** | 0 | 0 | 2 |
| **合计** | **56** | **3** | **3** | **0** | **62** |

11 段全部 `ok`（`out/aftersales/run-all.log` 的 11 对 `▶ 运行 <段>` / `◀ <段> ok`，20:29:54–20:32:31 +08），收尾逐字：
`汇总：counts={"pass":56,"fail":3,"skip":3,"falseRed":0,"total":62}；零残留=true（…全 0…）；token 凭据已删=true`

### 1.3 并发族单列（每项带 N / 轮次 / 逐请求结局 / 重叠证据）

| id | 形态 | N×轮 | 逐轮结局 | 库侧终态 | 重叠证据 | 判定 |
|---|---|---|---|---|---|---|
| `LB-C1-CONCURRENT-REFUND` | 同订单并发退款（防双花） | 8×3 | `[200×3, 422×5]`×3 | `refund_amount=300.00`（= 实收） | 真重叠 | **pass** |
| `LB-C2-CONCURRENT-RESOLVE` | 同工单并发完结（双副作用） | 4×3 | `[200,409,409,409]` 型 | 台账 1 行、时间线 1 行、库存**恰一次**增量 | 真重叠 | **pass**（老构建为 fail） |
| `LB-C21-CONCURRENT-SAME-TARGET` | 并发打同一目标 | 4×3 | 成功数 `[1,1,1]`；状态码 `[409,409,200,409]` 等 | 时间线 `[1,1,1]` 行 | 真重叠 | **pass**（老构建 4/4 全 200） |
| `LB-C22-CONCURRENT-CONFLICT` | 并发分歧（processing vs closed） | 2×3 | 成功数 `[1,1,1]` | 终态合法（至多一个赢家） | 真重叠 | **pass**（老构建两路都成） |
| `LB-C23-CONCURRENT-RESOLVE-TIMELINE` | 并发 resolved ⇒ 审计 | 4×3 | 成功数 `[1,1,1]` | 时间线 `[1,1,1]` 行 | 真重叠 | **pass**（老构建 4 行） |
| `LB-C3-CONCURRENT-STOCK` | 同 SKU 并发扣减 / 超卖 | 8×3 | 超卖 `[422,3]`×3 | 终值 `[0,0,0]`，不为负 | 真重叠 | **pass** |
| `LB-C5-DISPATCH-POOLED` | 同一单据并发派工 | 4×3 | HTTP `[200×4]`；**业务成功数 `[1,1,1]`** | 活跃加工单 `[1,1,1]` | 真重叠 | **pass** |
| `LB-CTRL-ORDER-STATUS-CAS` | **正对照**：订单侧并发改状态 | 4×3 | 恰 1 个 200 ×3 | 终态 `producing` | 真重叠 | **pass** |
| `W1`（race） | 同草稿入库单 8 并发过账 | 8 | 200 响应 **1/8**（`409×7`） | `status=posted`、库存 Δ20、台账 1 行 | 重叠对 28 | **pass** |
| **`W2`（race）** | **过账 × 作废交叉竞态** | 2 | **`[200,200]`** | `status=cancelled` 但库存 30→**35**、台账 **1 行** | **严格同时起跑 issueSpan=0ms** | **fail(产品)** ⇒ §2.1 |
| `W3`/`W3b`（race） | 同 SKU 两草稿并发过账 + 台账链 | 2 | `[200,200]` | 台账 `10.0→20.0` / `20.0→35.0`（**链 0 处不一致**） | 重叠对 1 | **pass**（老构建同基断链） |
| `W4`（race） | 并发确认收款防超卖 | 2 | 200×**1**/2 | 库存 10→2（扣减恰一次） | 重叠对 1 | **pass**（老构建 `[200,200]` 钳 0） |
| `W5`（race） | 同 runId 6 并发盘点 | 6 | **200×6**、5xx **0** | 分录 1 行、Δ-3 正确 | 重叠对 15 | **pass**（老构建 `[500×5,200]`） |
| `W6`（race） | 并发交叉上下架 | 8 | 200×8、5xx 0 | 回执/终态自洽 | 重叠对 28 | **pass** |
| `W7`（race） | 洁净 SKU 并发过账（收敛控） | 2 | `[200,200]` | 台账 `100.0→110.0` / `110.0→125.0`（链 0 处不一致） | 重叠对 1 | **pass**（老构建同基） |
| `I1`–`I4`,`I6`（race） | 幂等键并发/顺序/不同体/发货面 | 2–6 | 见 `out/race/probe-idem.json` | 同键恰 1 副作用、发货面占位 1 + 发货单 1 | 重叠对 1–15 | **pass**（老构建 I6 fail） |
| `C1`–`C5`（race） | 跨租户串号并发读/伪造头/混合读写 | 120/160 并发 | 核对本线探针对象 **360/480** 次 | **跨租户 0 次** | 重叠对 7140/12720 | **pass**（老构建同） |
| `RP1`–`RP4`（race） | 红证 / 判别对照 | — | 见 `out/race/probe-redproof.json` | 合法链 0 处 / 合成同基链 1 处；顺序双击 `[200,409]`；合成跨租户被标记 1 个 | — | **pass** |

> **「莫名转绿」的自我审查**（防止「修好了」是判据变松的假象）：race 侧逐条都有**同环境判别对照**（`RP1` 顺序重放 ⇒ `changed=0,replayed=1`；`RP3` 顺序双击 ⇒ `[200,409]`；`RP2`/`RP4` 注入红证会红），且 sweep#1 的 `LB-C21/C22/C23` 的状态码分布由老构建的 `[200×4]` 变为 `[200,409,409,409]` 型 —— **是被测行为变了，不是判据变了**。本轮**未改**任何既有 harness 文件。

---

## 2. 真缺陷清单

> 每条 = 最小复现 + 会红判据 + 根因符号/文件 + 五层归因。**根因符号取自被测工作树 `90192bcac` 本体**（本轮被测面 = 本机该检出，不是已部署面 ⇒ 符号与读数同源，无坐标漂移）。

### 2.1 F1（**并发 · 涉库存台账**）入库单「过账 × 作废」交叉竞态 ⇒ `post` 拿到的过账权被 `cancel` 抹掉，库存与入库台账行**静默留在库里**

- **判据 id**：`W2-过账×作废交叉竞态`（`out/race/probe-write.json` = **fail**）+ 本线独立复现 `W2-rounds`（20 轮）
- **逐字读数**（`out/race/probe-write-raw.json::cases.W2`）：
  ```
  statuses = [200, 200]            # post 与 cancel 都回 200
  window   = { requests:2, overlappedPairs:1, issueSpanMs:0, wallMs:231,
               spans: [[1791981321861,1791981322154],[1791981321861,1791981322092]] }
  dbStatus = "cancelled"           # 最终却是「已作废」
  stockBefore = "30.0" → stockAfter = "35.0"      # 库存被加了 5 米
  ledgerForRef = 1                 # 作废的单留下 1 行入库台账
  inconsistent = [ {rule:"post 返回 200 但库侧状态不是 posted", dbStatus:"cancelled"},
                   {rule:"库存变化与该单最终状态不符", before:"30.0", after:"35.0", dbStatus:"cancelled"},
                   {rule:"已作废的单却留下了入库台账行",
                    ledger:[{id:4344, sku_id:"2110348703040729089", delta:"5.0", before_qty:"30.0",
                             after_qty:"35.0", reason:"inbound", ref_no:"RK-20261014-0002",
                             note:"入库单过账（缸号 race-sweep-lot）", created_at:"2026-10-14T20:35:23.884786+08:00"}]} ]
  ```
- **本线独立复现（不依赖被测 harness，含逐请求毫秒时间线）**：`out/race/W2-rounds-index.txt`
  ```
  20 轮严格同时起跑（post / cancel 同一个 microtask 门控放行）：
    round-06 / round-09 / round-20 : post=200 cancel=200 db=cancelled delta=5 ledger=1  ⇒ fail(产品) 3 条不一致
    其余 17 轮                      : post=409 cancel=200 db=cancelled delta=0 ledger=0  ⇒ 单赢家，正确
  ⇒ 命中率 3/20 = 15%（竞态窗口真实存在、且**不是每轮都复现** ⇒ 只跑一轮会漏）
  ```
  单轮原始 JSON（例 `out/race/W2-rounds/round-06.json`）含：`overlapEvidence {真实重叠:true, unionMs:231, sumDurMs:287}`、`db {status:cancelled, postedAt:null, cancelledAt:…, cancelledReason:'race-sweep-race'}`、`ledgerForRef:[{delta:5, before_qty:30, after_qty:35, ref_no:'RK-…'}]`。
- **最小复现**（全在本线自建探针对象上）：
  ```bash
  # ① POST /api/admin/inbound-orders 建草稿单（探针 SKU，qty 任意）
  # ② 一个 microtask 门控**同时**发：
  #      PATCH /api/admin/inbound-orders/{id}  body {"action":"post"}
  #      PATCH /api/admin/inbound-orders/{id}  body {"action":"cancel","reason":"…"}
  # ③ 读 inbound_orders.status / posted_at / cancelled_at
  #    读 stock_ledger_entries where ref_no=入库单号
  #    读 product_skus.stock
  # 一键复算：bash acceptance/2026-10-14/line3-aftersales-race/run-w2-rounds.sh   # N=20
  ```
- **会红的判据**（机器可判、不依赖时序叙事）：
  1. `post` 返回 200 ⇒ 库侧 `status` 必须 = `posted`（实测 `cancelled`）；
  2. `cancel` 返回 200 ⇒ 该单**不得**产生任何库存增量（实测 +5.0）；
  3. `status = cancelled` ⇒ `stock_ledger_entries` 中 `ref_no=<入库单号>` 的行数必须 = **0**（实测 **1**）。
- **根因（源码符号，`90192bcac` 本体）**：
  - `backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java#post` —— **有** CAS 抢过账权：
    `if (inboundOrderMapper.markPosted(order.getId(), tenantId, operator, now) == 0) throw …conflict("…只有草稿可以过账"…)`
    （注释逐字：「抢过账权：条件更新（CAS），判断与写入同一条语句 + PG 行锁 ⇒ 并发/双击只有一个能进来」）；
  - 同文件 `#cancel` —— **无 CAS**：
    ```java
    if (!InboundOrder.STATUS_DRAFT.equals(order.getStatus())) { throw …conflict("…只有草稿可以作废"…); }
    order.setStatus(InboundOrder.STATUS_CANCELLED);
    inboundOrderMapper.updateById(order);     // ← WHERE 仅主键，无 status 谓词
    ```
    `resolveOrder()` 的 `status` 判定读的是**内存旧值**，落库走无谓词 `updateById` ⇒ **与 `post` 的 CAS 不互斥**：cancel 在 post 的 CAS 提交前读到 `draft`，之后无条件覆写成 `cancelled`（并覆盖 `updateById` 的其它字段），而 post 已经把库存 + 台账写下去了。
  - **正对照（同文件、同一并发窗口）**：`#post` 的 CAS 实测有效 —— `W1` 8 并发 `200×1 / 409×7`、库存只加一次、台账恰 1 行。
  - **类级同族**：与 2026-10-04 线② 记录的 `AfterSalesTicketService#updateTicketStatus`（`updateById` 无谓词）**同一根因形态**。
  - 微妙之处：`cancel` 的 conflict 文案**自己**说「已过账的入库单库存已进台账，冲销请另开单据（不原地改历史）」—— 即产品已把「不许把过账单改成作废」写成契约，但该契约**没有落到 SQL 谓词上**。
- **五层归因**：① **现象层** 作废的单把库存加了 5 米并留下 1 行入库台账（账实不符、无人发现）；② **接口层** 同一张草稿单的 `action=post` 与 `action=cancel` **都回 200**；③ **实现层** 两条路径的互斥强度不对称 —— post 用条件更新（`markPosted`），cancel 用无谓词 `updateById`；④ **类级层** 同一服务内已有 CAS 范式，`cancel` 未复用；⑤ **机制层** 单据状态机的「状态迁移权」只在 post 一侧落到 SQL 谓词上。
- **证据强度**：**强**。独立复现脚本 + 20 轮频率 + 严格同时起跑的毫秒时间线 + 库侧三读数（状态/库存/台账）+ 同环境判别对照（17/20 轮给出正确 409）+ 源码对照（有谓词 vs 无谓词）。**归因到 `90192bcac` 本体成立**（被测面 = 该检出）。
- **影响面**：客户端重试 / 用户同时点「过账」与「作废」/ 网络重放；后果是**库存虚增且台账留痕**（涉钱涉账）。

### 2.2 F2（**新租户可用性 · 前置缺口**）全新租户 0 个商品分类 ⇒ `POST /api/admin/products`（`categoryId` 必填）不可达

- **判据 id**：`LB1-SETUP-category-gap`（`out/aftersales/B1-setup.json` = **fail**）
- **逐字读数**（`out/aftersales/B1-category-gap.json`）：
  ```
  本线命名域（前缀「线B验收」）初始 active 分类数 = 0
  经真实 API 补建探针分类后 = 1（新建 id=df257ad497918feb7ba1fb37c8061c7e，HTTP 200）
  同时段**其他线**的分类 = 4 条（窗帘成品, smoke测试分类_1791980976716, smoke已更新_1791980977064, smoke待删除_1791980977391，本线只登记不触碰）
  ```
- **最小复现**：`POST /api/admin/products`（body 不带 `categoryId`）⇒ `422 VALIDATION_ERROR`「分类ID不能为空」。
- **会红的判据**：新租户在**本线命名域内 0 分类**的前提下，不手工造分类时 `POST /api/admin/products` 不得 422；或产品侧应在入驻时种一个默认分类 / 在 422 文案里给出可行动出口。
- **根因（源码符号，`90192bcac` 本体）**：`…/dto/ProductCreateRequest.java` 的 `categoryId` 必填（`…/service/ProductService` 建品依赖它）；`…/service/RegistrationService.java` 入驻只种默认角色/权限/岗位，**不种商品分类**。
- **五层归因**：① **现象层** 空租户走 API 建不出第一个商品；② **接口层** 422 文案只说「分类ID不能为空」，不指出「去哪里建分类」；③ **实现层** 入驻流程无商品分类种子；④ **类级层**「新租户可用性」缺一条端到端判据（本轮以空租户首跑才暴露）；⑤ **机制层** 新租户可用性前置不由入驻流程承接。
- ⚠️ **归因强度限制**：本线只断言「**本租户本线命名域**初始零分类 ⇒ 走 API 建商品缺前置」。**能否由前端「商品管理」页自助建分类兜住**（真实新用户是否被卡住）**不在本线射程**（未做 UI 级验证）⇒ 不写更强归因，也不判「用户必被卡死」。
- **跨构建点**：与 2026-10-04 的 **#6295** 同族，本轮在 `90192bcac` 上**仍复现** ⇒ **不是老构建伪影**。

---

## 3. 判据侧问题清单（假红 / 夹具漂移 / 期望过期 / 探针缺陷）

> 纪律：**判据的缺陷与产品的缺陷必须分开报**。以下每条都给「谁判的、判据文件、为什么是判据侧」。

| # | 现象（逐字） | 归因 | 判别证据 | 本轮处置 |
|---|---|---|---|---|
| **G1** | `LB0-01` = fail：「远端声明=(`ADMIN_API_DEPLOYED_SHA` 未设)；最后一个 success 部署=`d0efc4e0c` @ `2026-10-14T09:41:37Z`（UTC）」 | **期望值过期**（任务书点名的同类伪影） | 判据源 `acceptance/2026-10-04/aftersales-refund-sweep/harness/p0-env.mjs:23` **写死** `const EXPECTED = 'ff655a06c'`（那是 2026-10-04 的部署台账）；本轮口径源 = BRIEF §2「`API_BASE` 必须指本机 8080（本轮被测面）」。**判据度量「已部署面构建点」，被测对象是「本机源码树 HEAD=90192bcac」⇒ 判据对象与被测对象不是同一个** | 登记为 **假红**；**不改**判据（改了就是改判据凑绿） |
| **G2** | `LB-Z-02` = fail：「orders: added=2 removed=0 changed=0」，added id = `2d90b9e6…` / `9d27be2d…` | **判据未命名空间化 ⇒ 跨包干扰被读成本线问题** | 本线独立归因现取：这 2 行 `customer_name='工序验收客户077598'`，**不是**本线命名域（本线 sweep#1 夹具客户名规则 = `${PROBE_PREFIX}客户-${tag}-${u}` = `线B验收客户-*`，见 `…/aftersales-concurrency-sweep/harness/lib.mjs:371`），`created_at` = 20:32:22 / 20:32:25 +08（落在本段落窗口内，由**别线**写面探针创建）。该判据自身 evidence 也写明「别线在同租户并发写」并对流水表做了同款豁免 ⇒ **对 `orders` 表漏了同一豁免** | 登记为 **假红**；本线清理后 tenant 32 三命名域全 0（§7） |
| **G3** | sweep#2 `tenant-isolation-sweep` **登录即失败**：`Error: 登录失败 401 {"code":"AUTH_FAILED","message":"该手机号未注册"} @ sweep.mjs:26`；sweep#3 `tenant-concurrency-sweep` 同形 `@ probe.mjs:26` | **探针缺陷（非产品）**：两条 harness **完全无 env 注入口** | grep 全文件 `process.env.TENANT` / `PHONE` ⇒ **0 命中**；主体矩阵 hardcode：`sweep.mjs:22-24` `SUBJ={A:'13870217889',B:'13797101248',P:'13456800919',C:'13800138000'}` + `T={A:20,B:21,P:-1,C:1}`；`resources.mjs:5-7` `A={tenant:20}` / `B={phone:'13797101248',tenant:21}` / `C={tenant:1}`。库现取：`tenants` 只剩 32（+本线临时 34），那 3 个 hardcode 手机号在 `users` 中 **0 行**。⇒ **被测对象（32）无法用 env 注入**；改 harness 源码 = 违反「不要修改它们」 | 判 **未覆盖**；由本线 `probe-cross-tenant.mjs`（32↔34）补 4/4（§5.1） |
| **G4** | `LB-AS-CREATE-02` = skip：「库中无 tenant=1 的订单可作跨租户探针」 | **判据对象写死租户 id ⇒ 结构性 skip** | 判据源 `…/aftersales-refund-sweep/harness/p2-b1-serial.mjs:37` `select … from orders where tenant_id=1 …`（tenant 1 已不存在） | 本线**补测**该覆盖（§5.1 的 `LB3-XT-01`），原条仍保留 skip |
| **G5** | `LB-PREC-02`（涉钱精度）判据 label/evidence 仍写「现状 **200 静默归零**」「⇒ 请求被「成功」接受（HTTP 200 + `refund_at` 落笔）…」，而它**自己**的 pass 断言要求 422、实测 `extra={status:422, silentZero:false}` | **判据文案漂移（不改变 verdict）** | 产品侧已按 #6221 修复：`backend/admin-api/src/main/java/com/migao/admin/service/MoneyScale.java`（2 位小数 fail-closed 准入）+ `OrderService#refundOrder` 调用 `requireTwoDecimalsOrNull(refundAmount,"退款金额")`（源码逐字可见）。判据用**状态码**判定 ⇒ 仍能正确判 pass，**只是证据串是旧文案** | 登记；不影响四态 |
| **G6** | `race/run-all.sh` **三个探针全部 `Cannot find module …/acceptance/acceptance/…`** | **探针缺陷（路径）** | `run-all.sh` 里 `cd "$(dirname "$0")/../../.."`（= 仓库根）后仍以**相对路径** `acceptance/2026-10-04/race-sweep/harness/$p.mjs` 调 `node` ⇒ 路径重复拼接。**同 2026-10-04 报告已自曝的形态** | 本线未改该文件；改用**绝对路径**逐个跑 4 个探针（`out/race/run-all.log` 完整留痕，含原始失败） |
| **G7** | `race/bootstrap.mjs` **第 40 行登录失败**：`登录失败 13800138001 401 …该手机号未注册` | **夹具漂移（探针侧）** | `bootstrap.mjs#ensureTenantB()` 先 `select id,name from tenants where name='米高测试环境-隔离对照'` —— **只按名字认租户，不校验该租户的管理员手机号**；`config.mjs:10 PHONE_B='13800138001'` 写死。本线第一次入驻用的手机号是 13800138002 ⇒ 名字命中但手机号对不上 ⇒ 登录 401 | 本线把临时租户重建为 `phone=13800138001`（**未改 config.mjs**），bootstrap 随即通过；并登记「`tenant_applications` 残留会挡同名再入驻」这一环境事实（§6.1） |

---

## 4. 涉钱 / 库存期望值的**本线独立算式**（任务书要求：不得读被测读面）

| 项 | 本线独立算式 | 实测（现取/响应） | 判据 id | 判定 |
|---|---|---|---|---|
| 退款精度准入 | 列精度 `NUMERIC(·,2)` ⇒ scale 2；`0.01`（有效 2 位）合法、`0.001`/`0.004`/`0.005`/`0.009`（有效 3 位）**必须拒绝** | `0.01` ⇒ 200 + 订单 `refund_amount=0.01` + 流水 1 行 0.01（**两侧逐字相等**）；`0.001`/`0.004`/`0.005`/`0.009` ⇒ **422**、订单 0、流水 0 行、`refund_at=null` | `LB-PREC-01/02/03` | **pass**（老构建上 0.001 是 200 + 静默归零） |
| 退款封顶 | 实收 = `qty × unitPrice` = 2×100 = **¥200.00**（本线算式）；累计退款 ≤ 实收 | 订单 `actual_amount=300.00`（该夹具为 3×100）⇒ 3×100 全成、第 4 次 422；并发场景 `8×3 轮` 恒 `[200×3,422×5]`，终值 `refund_amount=300.00` **= 实收** | `LB-C1-CONCURRENT-REFUND` | **pass** |
| 退款负例 | 超额（实收+0.01）、负数、非法串 ⇒ 一律 4xx 且**零落库** | 300.01 ⇒ 422「退款金额不能超过实收款 300.00」；−50 ⇒ 422「退款金额不能为负数」；`"一百元"` ⇒ 422「退款金额格式不正确」；三者 `refund_amount` 均 0 | `LB-REF-02/03/08`、`LB-REF-C02` | **pass** |
| **退货回补（开关开）** | 自建品 `stock=137.0` → 确认收款扣 `qty=3` ⇒ **134.0** → 退货完结回补 `qty=3` ⇒ **期望 137.0**；台账该工单号下 **恰 1 行 delta=+3** | SKU `137→134→137`；台账 **1 行**（算式 1 行）；订单 `refund_amount=150 = 3×50`（算式 150） | 本线 `LB3-IS-ON-*` | **pass** |
| **退货回补（开关关）** | 同上但 `allow_return_restock=false` ⇒ 完结后**期望仍 134.0**、该工单号下台账 **0 行** | SKU `134→134`；台账 **0 行**；退款仍照记 `150` | 本线 `LB3-IS-OFF-*` | **pass** |
| 入库并发过账库存增量 | 草稿单量 = 20 ⇒ 库存恰 +20、台账恰 1 行、`before/after` 首尾相接 | `W1`：库存 `10.0→30.0`（Δ20）、台账 1 行；`W3/W3b`：两行 `10.0→20.0`/`20.0→35.0`（**链 0 处不一致**） | `W1/W3/W3b` | **pass** |

> 独立算式的基准值由本线**自己建的对象**定义（自定 `stock=137.0`、`qty=3`、`unitPrice=50`），期望值不从被测响应反读；`createProbeProduct`/`createProbeOrder` 只用于造对象，**期望值一律由本脚本算式给出**（见 `probe-independent-math.mjs` 内 `expectStock` / `expectLedger` / `expectLedgerDelta`）。

---

## 5. 本线自建补测（补 sweep#2/#3 的覆盖缺口；不改既有 harness）

### 5.1 跨租户隔离（32 ↔ 34 真租户对）

- **工装**：`acceptance/2026-10-14/line3-aftersales-race/probe-cross-tenant.mjs`（本线新建，**未改**既有 harness）
- **产物**：`out/aftersales/XT-cross-tenant.log`
- **读数（4/4 pass）**：
  ```
  [PASS] LB3-XT-01-跨租户建单   — A(32) token 打 B(34) 订单 20261014639640146 ⇒ HTTP 422
                                  {"code":"VALIDATION_ERROR","message":"关联订单不存在"}；A 侧 order_id=该单的工单落库 0→0 行
  [PASS] LB3-XT-03-正对照-B打自己 — B(34) token 打 B 自己的订单 ⇒ HTTP 200；B 侧落库 1 行
  [PASS] LB3-XT-02-跨租户按-id-读 — A(32) token 按 id 读 B(34) 的 商品/订单/工单 ⇒ 404 / 404 / 404（要求 401/403/404）
  [PASS] LB3-XT-04-正对照-A打自己 — A(32) token 打 A 自己的订单 ⇒ HTTP 200
  ```
- **判据会红**：正对照（B 打自己 / A 打自己）必须 200 —— 若正对照不 200，则反例的 4xx **不可归因于租户边界**（说明端点本身坏了），本条即成「不可判」。本轮正对照两侧均 200 ⇒ 反例的拒绝可归因。
- **与 race-sweep 的 C 组关系**：race 的 `C1–C5`（120/160 并发交错读、伪造 `X-Tenant-Id`、并发混合读写）已在**本机被测面**上 pass（跨租户 0 次）；本组补的是**建单写面**的跨租户复用 + 按 id 读三资源。两者**独立**。

### 5.2 W2 的独立复现 + 频率读数

见 §2.1：`probe-w2-repro.mjs` + `run-w2-rounds.sh`（N=20），产物 `out/race/W2-rounds-index.txt` + `out/race/W2-rounds/round-*.json`。

### 5.3 涉钱/库存的独立算式端到端

见 §4：`probe-independent-math.mjs`，产物 `out/aftersales/INDEP-independent-math.log`。

---

## 6. 临时对照租户（建 → 用 → 清）

### 6.1 建立（走真实入驻流程，非直插）

```
# 第一次（本线建，手机号自选 13800138002）
POST /api/auth/sms/send  {"phone":"13800138002"} ⇒ 200
POST /api/auth/register  {"companyName":"米高测试环境-隔离对照","contactName":"隔离对照管理员",
                          "phone":"13800138002","smsCode":"123456","industry":"布艺纺织",
                          "province":"广东省","city":"深圳市","address":"验收探针地址"}
  ⇒ 200 {"applicationId":2110347709485608961,"status":"approved","message":"AI 甄别通过，欢迎入驻观星台平台"}
  ⇒ tenants: id=33 name=米高测试环境-隔离对照 code=shop-utwl

# 重建（原因见 §3 G7：race-sweep 的 config.mjs 把 PHONE_B 写死 13800138001，
#        而 bootstrap 只按企业名找租户 ⇒ 名字命中但手机号对不上 ⇒ 登录 401）
#   ① wipe 掉 33（本线自建，允许）② 清掉 tenant_applications 里 phone=13800138002 的残留行
#      （**复算命令**：select id,phone,company_name,status from tenant_applications 现取；
#        不清这一行再入驻会 422「该企业已有入驻申请，请勿重复提交」）
POST /api/auth/register  {…,"phone":"13800138001",…}
  ⇒ 200 {"applicationId":2110348657377341442,"status":"approved","message":"AI 甄别通过，欢迎入驻观星台平台"}
  ⇒ tenants: id=34 name=米高测试环境-隔离对照 code=shop-gh42；users: (34, 13800138001, admin)
```
- 两次入驻的 `status=approved` + `review_summary` 均来自**规则层降级放行**（BRIEF §1：本机 ai-agent 无 `PRIMARY_API_KEY`）⇒ 无真实 LLM 参与业务判定。

### 6.2 使用

跨租户补测（§5.1）的 B 侧：登录、建探针商品（race-sweep bootstrap 建 `race-sweep-B1-*` / `race-sweep-X-B-*`）、建探针订单 2 张、建探针工单 2 张。

### 6.3 清理（**清理前 / 清理后均为现取**）

| 读数 | 清理前（2026-10-14 20:39:49 +08） | 清理后（20:40:20 +08 及 wipe 自证） | 证据 |
|---|---|---|---|
| `select count(*) from tenants` | **2**（32 + 34） | **1**（只剩 32） | `q.sh` 现取 + `evidence/wipe-tenants.json` |
| tenant 34 全子表 `tenant_id=34` 行数合计 | **391** | **0** | 现取（`query_to_xml` 全表扫描）+ wipe 自证「点名租户的子表残留行数合计 = 0」 |
| tenant 34 `products` / `orders` / `after_sales_tickets` / `users` | 2 / 2 / 2 / 1 | 0 / 0 / 0 / 0 | 同上 |
| `tenants` 里点名的 34 行 | 存在（`34\|米高测试环境-隔离对照\|shop-gh42`） | **无** | wipe 自证逐字「tenants 里仍存在的点名行 = 无」 |
| 清理命令 | `python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 34 --apply` | dry-run 显示 371 行子表 + 1 行 tenants | `acceptance/2026-10-14/evidence/wipe-tenants.json` |
| **清理失败项** | **无** | — | — |

---

## 7. 残留清理读数（tenant 32 —— **未清空**，只清本线命名域）

- **本线命名域**：`线B验收`（sweep#1）、`race-sweep`（sweep#4）、`线③独立` + `lb3-race`（本线自建探针）。

**⚠️ 清理是两轮的（如实登记，含第二轮的原因）**：

| 轮次 | 触发 | 读数 |
|---|---|---|
| 第 1 轮 | sweep#1 `cleanupProbe()` + `cleanup-extra.mjs`（段内自带）；sweep#4 `cleanup-a.mjs`（删 112 行）；本线 `cleanupProbe()`（`PROBE_PREFIX=线③独立`，33 行 → 0） | 当时三命名域全 0 |
| **第 2 轮（补）** | **第 1 轮之后我又跑了一次 `probe-independent-math.mjs` 去补产 `IND-independent-math.log`，它又建了 2 商品 + 2 订单 + 2 工单**；同时 **W2 复现 20 轮留下 21 张 `lb3-race-supplier` 草稿/作废入库单**（`cleanup-a.mjs` 的谓词只认 `race-sweep%`，**不覆盖 `lb3-race`**） | 见下方「最终读数」 |

> 这两个残留是**我自己的操作顺序造成的**（先清理、后补跑），不是清理器失效；登记在此以便复算者理解时序。

### 7.1 最终读数（**现取 2026-10-14 20:43:45 +08**）

| 读数 | 值 |
|---|---|
| `select count(*) from tenants` | **1**（只剩被试租户 32） |
| `tenants` 点名 | `32|米高测试环境` |
| tenant 32 `products` 命中 `race-sweep%`/`线B验收%`/`线③独立%`/`lb3-race%` | **0** |
| tenant 32 `product_skus` 命中 `LB-%` | **0** |
| tenant 32 `inbound_orders` 命中 `race-sweep%`/`lb3-race%` 供应商 | **0** |
| tenant 32 `after_sales_tickets` 命中 `线B验收%`/`线③独立%` 描述 | **0** |
| tenant 32 `orders` 命中三前缀 remark | **0** |
| tenant 32 `client_request_keys` 命中 `lb%` | **0** |
| tenant 32 `stock_ledger_entries` 命中三前缀 + `lb3-race` note | **0** |
| **全库粗扫**：所有含 `remark` 列的表，`tenant_id=32 and remark like 'race-sweep%\|线③独立%\|线B验收%'` 行数合计 | **0** |

第 2 轮的定向删除（FK 拓扑序、单事务）：
```sql
-- probe-ok 本线自建命名域清理（线③独立 / lb3-race）
begin;
delete from product_skus      where product_id in (select id from products where tenant_id=32 and name like '线③独立%');
delete from product_colors    where product_id in (select id from products where tenant_id=32 and name like '线③独立%');
delete from stock_ledger_entries where tenant_id=32 and product_id in (select id from products where tenant_id=32 and name like '线③独立%');
delete from products          where tenant_id=32 and name like '线③独立%';
delete from inbound_orders    where tenant_id=32 and coalesce(supplier,'') like 'lb3-race%';
delete from ticket_timeline   where ticket_id in (select id from after_sales_tickets where tenant_id=32 and description like '线③独立%');
delete from after_sales_tickets where tenant_id=32 and description like '线③独立%';
delete from finance_transactions where tenant_id=32 and (order_id in (select id from orders where tenant_id=32 and coalesce(remark,'') like '线③独立%') or coalesce(remark,'') like '%线③独立%');
delete from stock_ledger_entries where tenant_id=32 and (ref_no in (select order_no from orders where tenant_id=32 and coalesce(remark,'') like '线③独立%') or coalesce(note,'') like '%线③独立%');
delete from order_items       where order_id in (select id from orders where tenant_id=32 and coalesce(remark,'') like '线③独立%');
delete from orders            where tenant_id=32 and coalesce(remark,'') like '线③独立%';
commit;
```
> 首版顺序把 `products` 放在 `stock_ledger_entries` 之前 ⇒ 触发 `stock_ledger_entries_product_id_fkey` 违例、**整事务回滚**（`EXIT=1`）；按 FK 拓扑序（子表优先）重排后通过 —— 与 2026-10-04 报告自曝的 H5 同族缺陷，登记在此。

### 7.2 逐段清理器自证

| 清理器 | 读数 | 证据 |
|---|---|---|
| sweep#1 `cleanupProbe()` + `cleanup-extra.mjs` | `preCleanupResidue.total=537 → residue=0`（逐表全 0）；`零残留=true`；`token 凭据已删=true` | `out/aftersales/B9-cleanup.json::LB-Z-01`、`out/aftersales/Z-residue.json`、`out/aftersales/run-all.log` 收尾行 |
| sweep#4 `cleanup-a.mjs`（race-sweep 命名域，FK 图级联） | 删 112 行；现取残留 `{"products":0,…,"ledger":0,"consumptions":0}`；阻塞表 Top=`[]`（`--dry` 先跑：`errors=[]`、`blocked=[]`） | `out/race/cleanup-tenantA.json`、`out/race/cleanup-tenantA-dry.json` |
| 本线 `线③独立` 命名域（`cleanupProbe()`，`PROBE_PREFIX=线③独立`） | 33 → 0（逐表全 0） | 本线现取 stdout |
| 本线 W2 复现入库单（`lb3-race`） | 21 张 → 0（第 2 轮定向删除） | §7.1 SQL + 复核读数 |

**未触碰**：别线对象（`窗帘成品` 分类、`工序验收客户*` 订单、`LA-ORD-*`、`smoke*`）**一行未动**；tenant 32 的种子数据（41 工序 / 27 路由规则 / 7 角色 / 权限）未动；**tenant 32 本身未清空**。

## 8. 未覆盖清单（skip 及原因与重启条件）

| # | 缺口 | 为什么没覆盖 | 重启条件 |
|---|---|---|---|
| 1 | **`tenant-isolation-sweep` 全量** | 主体矩阵与租户 id **全 hardcode**（`T={A:20,B:21,P:-1,C:1}` + 3 个手机号），**无任何 env 注入口** ⇒ 在本轮被测面（只剩 tenant 32）**登录即 401 失败**，未产生一条判据（`out/tenant-isolation/run-all.log`） | 把该 harness 的主体/租户 env 化（需改代码）**或**重建 20/21/1 三个租户 |
| 2 | **`tenant-concurrency-sweep` 全量** | 同上（`resources.mjs` hardcode 20/21/1；`probe.mjs:26` 登录 401 失败） | 同上 |
| 3 | `LB-AS-CREATE-02`（跨租户订单复用建单幂等） | 判据源写死 `tenant_id=1` 的真实订单（`p2-b1-serial.mjs:37`）；tenant 1 已不存在 ⇒ 结构性 skip | **已由本线 `LB3-XT-01` 补上等价覆盖**（32↔34，pass）；原条仍记 skip |
| 4 | `LB-AS-CREATE-03`（admin-api 直连面建单幂等回放，AS-010 口径） | **判据对象错层**：AS-010 判的是 agent 工具面 `aftersale_create`，admin-api 售后建单**未接** `ClientRequestIdService`；实测第 2 次被 dup-guard 拒 422（`replayed=undefined`） | 需 agent 工具面跑法（**受 #4262 约束：不得自动派发真实 LLM 评测**）⇒ 需用户显式要求 |
| 5 | `LB-C4-BULK-READ-1000`（>1000 行真实数据量的列表读） | 本租户最大可读面 = **97 行**（orders 49 / ledger 97 / finance 73 / tickets 19）< 1000 | 租户数据量 ≥1000 行时 |
| 6 | race `I5`（商家表单建单面是否消费幂等键） | 如实登记：该端点**不消费**幂等键（3 并发落 3 单、占位 0 行）；幂等覆盖面仅 Agent 面/工人面/发货面 | 产品决定接入该面时 |
| 7 | 跨租户**写**面（`PUT`/`DELETE` 对方对象） | race 的 C 组只覆盖「读 + 各自建品」；本线 `LB3-XT-01` 补了「跨租户建单（写）被拒」，但 `PUT/DELETE` 跨租户未覆盖 | 追加 C6/C7 |
| 8 | UI 层并发（双击提交、同页并发操作） | 本线只打 `:8080` admin-api；无头浏览器未在本线登记工具与截图路径 | 登记 Playwright + 截图路径（线①/主会话若已做可复核） |
| 9 | 最坏竞争强度（N≫8 / 跨实例 / 多副本） | 单机单实例，N≤160 | 多副本部署时 |
| 10 | `race/probe-async.mjs` / `probe-agent.mjs` / `probe-redproof`（线④ 原有全套） | 后三者中 `probe-redproof` 已跑（4/4 pass）；`probe-async` 依赖硬编码旧 `API_LOG` 路径（`acceptance/2026-10-03/out/main-live-1233b8a42-api.log`，该文件不存在）⇒ 未跑 | 提供本机 admin-api 日志路径后 |

---

## 9. 产物与复算命令

```
acceptance/2026-10-14/line3-aftersales-race/
├── REPORT.md                      # 本文件
├── SUMMARY.json → out/SUMMARY.json # 机器可读（计数 + findings + 计数配方）
├── q.sh                            # 本线只读查库助手（新增，非产品代码）
├── probe-w2-repro.mjs              # 新增：W2 独立复现（含逐请求毫秒时间线）
├── run-w2-rounds.sh                # 新增：W2 多轮运行器（N=20）
├── probe-cross-tenant.mjs          # 新增：32↔34 跨租户隔离补测
├── probe-independent-math.mjs      # 新增：涉钱/回补的独立算式端到端
└── out/
    ├── aftersales/                 # sweep#1 原生产物（B*.json / Z-*.json / SUMMARY.json / run-all.log / run.log）
    │   ├── XT-cross-tenant.log     #   本线跨租户补测
    │   └── IND-independent-math.log#   本线独立算式
    ├── tenant-isolation/run-all.log     # sweep#2（登录失败原文）
    ├── tenant-concurrency/run-all.log   # sweep#3（登录失败原文）
    └── race/                       # sweep#4 原生产物 + W2-rounds/ + W2-rounds-index.txt + cleanup-tenantA*.json
```

```bash
cd "/Users/guangzhen.zk/ai native/migao"
# ① 三件套体检
bash acceptance/2026-10-14/tools/start-stack.sh status
# ② sweep#1（售后退款闭环）—— 统一口径
REPO_ROOT="$PWD" LIVE_WORKTREE="$PWD" API_BASE=http://127.0.0.1:8080 AGENT_BASE=http://127.0.0.1:8001 \
TENANT_ID=32 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
OUT_DIR="$PWD/acceptance/2026-10-14/line3-aftersales-race/out/aftersales" \
node acceptance/2026-10-04/aftersales-refund-sweep/harness/run-all.mjs
# ③ sweep#4（race）—— 底座的 run-all.sh 有路径缺陷（§3 G6），逐个跑 4 个探针
OUT_DIR="$PWD/acceptance/2026-10-14/line3-aftersales-race/out/race" \
bash acceptance/2026-10-14/line3-aftersales-race/run-race-probes.sh   # 等价于逐个 node（见 out/race/run-all.log）
# ④ 本线补测
node acceptance/2026-10-14/line3-aftersales-race/probe-independent-math.mjs
node acceptance/2026-10-14/line3-aftersales-race/probe-cross-tenant.mjs
bash acceptance/2026-10-14/line3-aftersales-race/run-w2-rounds.sh
# ⑤ 清理
node acceptance/2026-10-04/race-sweep/harness/cleanup-a.mjs            # race-sweep 命名域
python3 acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 34 --apply
```

**纪律声明**：本线**未**运行 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁）；**未**派发任何评测 workflow / **未**调用真实 LLM；**未**改任何产品源码（`backend/**` / `frontend/**`）、测试、用例、CHANGELOG；**未**修改 `acceptance/2026-10-03/**` 与 `acceptance/2026-10-04/**` 下**任何既有 harness 文件**（本线所有新代码都在 `acceptance/2026-10-14/line3-aftersales-race/`）；**未**开 issue、**未**提 PR。
**本报告不下「验收通过 / 交付完成 / 已达标」结论**（不自我验收；判定权在主会话与独立复核）。
