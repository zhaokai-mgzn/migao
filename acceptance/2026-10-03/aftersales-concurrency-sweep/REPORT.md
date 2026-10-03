# 线B · 售后退款闭环 + 并发竞态 sweep（2026-10-03 第三轮）

> 执行者 = 后台验收子代理（线B）。**本报告只产读数 + 判定 + 证据，不下「验收通过 / 交付完成」结论**（不自我验收）。
> 四态：`pass` / `fail(产品)` / `假红(判据缺陷或无判别力)` / `skip(未覆盖 —— 永不记 pass)`。
> 构建点：`main-live` 工作树 **`43ca703221a714e143c468ff0b29c4a46e67a88f`**（= 准备时刻 origin/main）。
> 源码一律 `git -C /Users/guangzhen.zk/migao-wt/main-live show HEAD:<path>`（**未读主检出工作树**、**未改任何产品源码**）。

---

## 0. 一句话结论

B1 串行闭环（建单 / 状态机 / 退款金额 / 回补开关两侧 / 三方自洽）**逐条有红证、读数干净**；
B2 并发族跑出 **1 条真缺陷（并发双跑副作用 ⇒ 库存重复回补 + 审计重复）**、**1 条涉钱精度缺陷（0.001 静默归零）**、
**1 条读面自相矛盾缺陷（size<0 ⇒ total=0 而返回整页）**；订单侧并发（CAS 谓词在位）作为**正对照全绿**，
证明「并发到得了、判据会红也会绿」。

---

## 1. 读数汇总（四态分列）

> 真值以 `out/SUMMARY.json` 为准（一键重跑会刷新）。下表为最后一次全量跑的分组汇总。

| 组 | pass | fail | skip | 假红(falseRed) | total |
|---|---|---|---|---|---|
| B0 环境自证 | 6 | 0 | 0 | 0 | 6 |
| B1 夹具 | 4 | 0 | 0 | 0 | 4 |
| B1 售后退款闭环（串行） | 17 | 0 | 0 | 0 | 17 |
| B2 并发竞态（C1~C4 族） | — | — | — | — | — |
| B1/B2 补强探针（精度/边界/正对照） | — | — | — | — | — |
| Z 零残留 | — | — | — | — | — |
| **合计** | 见 `out/SUMMARY.json` 的 `counts` | | | | |

并发族单列（每项都带 `N` / `rounds[3]` / `overlapEvidence`，见 `out/SUMMARY.json` 的 `items[].concurrency`）：

| id | 形态 | N×轮 | 逐轮结局（状态码序列） | DB 终态 | 重叠证据 | 判定 |
|---|---|---|---|---|---|---|
| `LB-C1-CONCURRENT-REFUND` | 同一订单并发退款（防双花） | 8×3 | `[200×3, 422×5]`×3 | `refund_amount=300.00`（= 实收）/ 流水 3 行合计 300.00 | 三轮均真重叠 | **pass** |
| `LB-C1-REDPROOF` | C1 判别力红证（摘守卫 vs 加守卫） | 8 | 无守卫 ⇒ 终值 800（泄漏）；有守卫 ⇒ 300（守住） | — | 真并发（8 独立 psql 进程） | **pass** |
| `LB-C2-CONCURRENT-RESOLVE` | 同工单并发完结（双重副作用） | 4×3 | `[200,200,200,200]`×3 | 库存 98→**106**；台账 **4 行**；时间线 5 行；退款 300（封顶未破） | 三轮均真重叠（最大逐对重叠 987ms） | **fail(产品)** |
| `LB-C21-CONCURRENT-SAME-TARGET` | 并发打**同一目标**（pending→processing） | 4×3 | `[200,200,200,200]`×3 | 时间线 **4 行**（应 1） | 三轮均真重叠 | **fail(产品)** |
| `LB-C22-CONCURRENT-CONFLICT` | 并发**分歧**（processing vs closed） | 2×3 | `[200,200]`×3 | 终态 ∈ {processing, closed}（合法） | 三轮均真重叠 | **fail(产品)**（两个都成 ⇒ 无赢家语义） |
| `LB-C23-CONCURRENT-RESOLVE-TIMELINE` | 并发 resolved ⇒ 审计重复 | 4×3 | `[200,200,200,200]`×3 | timeline「→resolved」**4 行**（应 1） | 三轮均真重叠 | **fail(产品)** |
| `LB-C23-ROWCOUNT-REDPROOF` | 行数读数的判别力红证 | 4 / 1 | 4 次写 ⇒ 4 行；1 次写 ⇒ 1 行 | — | — | **pass** |
| `LB-C3-CONCURRENT-STOCK` | 同 SKU 并发扣减 / 超卖 / 负数 | 8×3 | 并发扣减终值 `[0,0,0]`；超卖请求 `[422,422,422]` | SKU 保持 3.0（超卖未扣）；并发收款后 98.0（恰一次） | 三轮均真重叠 | **pass** |
| `LB-CTRL-ORDER-STATUS-CAS` | **正对照**：订单侧并发改状态 | 4×3 | `[422,422,422,200]` 型（恰 1 个 200） | 终态 producing | 三轮均真重叠 | **pass** |
| `LB-CTRL-CAS-SQL` | 正对照 SQL 层量化 | 4 | 有谓词 w=1；无谓词 w=4 | — | — | **pass** |
| `LB-C4-BULK-READ` | 大批量读（size 钳制 / 跨页求和） | — | ledger `size=5000 ⇒ size=500 total=652 rows=500`，`page2 ⇒ 152`，**跨页求和 652 == total 652** | 无 5xx | — | **pass** |
| `LB-C4-NEGATIVE-SIZE` | `size<0` ⇒ 总数与行数不自洽 | — | 三端点 `size=-5 ⇒ 200 / total=0 / rows=整页` | — | — | **fail(产品)** |
| `LB-C4-BULK-READ-1000` | 「>1000 行」档 | — | 本租户最大面 652 行 < 1000 | — | — | **skip(未覆盖)** |

---

## 2. 真缺陷清单（逐条：级别 / 逐字读数 / 最小复现 / 会红的判据）

### D1（**P1**（主会话裁定，issue #6220）/ 包内初判 P2 · 并发）售后工单并发完结 ⇒ **退货回补库存重复生效 + 审计重复**（`LB-C2` / `LB-C21` / `LB-C23`）

**逐字读数**（`out/B2-concurrency.json`、`out/B4-probe-batch.json`，三轮完全一致）：

```
LB-C2  R1/R2/R3：逐请求状态码 [200,200,200,200]（N=4）
       DB：SKU 98 → 106（回补 4 次 × +2.0）
       stock_ledger_entries（ref_no=AS-20261003-0023）：
         [{"delta":2,"before_qty":98, "after_qty":100,"reason":"aftersales"},
          {"delta":2,"before_qty":100,"after_qty":102,"reason":"aftersales"},
          {"delta":2,"before_qty":102,"after_qty":104,"reason":"aftersales"},
          {"delta":2,"before_qty":104,"after_qty":106,"reason":"aftersales"}]
       ticket_timeline（action=status_change）：
         [{"from":"pending","to":"processing"},
          {"from":"processing","to":"resolved"},   ← 同一张工单同一次「完结」被记 4 遍
          {"from":"processing","to":"resolved"},
          {"from":"processing","to":"resolved"},
          {"from":"processing","to":"resolved"}]
       订单 refund_amount=300.00（= 实收）⇒ **退款侧被守卫挡住，未翻倍**
LB-C21 三轮：N=4 并发打 pending→processing，4/4 全 200，时间线 4 行（应 1 行）
LB-C22 三轮：N=2 并发（processing vs closed），2/2 全 200 ⇒ 不存在「一个赢家」
LB-C23 三轮：N=4 并发打 processing→resolved，4/4 全 200，timeline「→resolved」4 行（应 1 行）
```

**最小复现**（可复制，全部在探针自建对象上）：

```bash
cd "acceptance/2026-10-03/aftersales-concurrency-sweep/harness"
SEGMENTS=p0,p8,p1,p3 API_BASE=http://127.0.0.1:8080 node run-all.mjs   # 只跑手表+夹具+C1~C4 并发族
# 手抄版：① 建探针商品（allow_return_restock=true, stock=100）
#         ② 建单 qty=2 → PUT /api/admin/orders/{id}/payment（实收 300）
#         ③ POST /api/admin/after-sales {ticketType:return, refundAmount:300}
#         ④ PUT /api/admin/after-sales/{tid}/status → processing
#         ⑤ 同时并发 4 个 PUT /api/admin/after-sales/{tid}/status → resolved（同一起跑线）
#         ⑥ 读 SKU 库存与 stock_ledger_entries(ref_no=工单号)：应 98→100 + 1 行；实测 98→106 + 4 行
```

**会红的判据**（机器可判、不依赖请求时序）：
- `stock_ledger_entries` 中 `ref_no=<工单号>`、`reason='aftersales'` 的**行数必须 = 1**；且 SKU 终值必须 = 回补前读数 + 明细数量（**恰一次增量**）；
- `ticket_timeline` 中同一工单 `content.to='resolved'` 的**行数必须 = 1**；
- 同一工单的并发 `resolved` 中**成功响应（200）必须恰好 1 个**，其余 422。

**根因（源码符号，不写行号）**：
- `backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java` 的 `updateTicketStatus` —— 状态机校验读的是 `selectById` 得到的**内存旧值**，落库走 `afterSalesTicketMapper.updateById(ticket)`，其 `WHERE` **仅主键 id**（无状态谓词）⇒ 读-判-写在并发下失去互斥；
- 同文件 `maybeRestockOnReturn` ⇒ `orderService.restoreStockForReturn(...)` ⇒ `backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java` 的 `adjustStockAndSales(false, null)` ⇒ `restoreSkuStock` ⇒ `backend/admin-api/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java` 的 `restoreStock`：`UPDATE product_skus SET stock = COALESCE(stock,0) + #{quantity} WHERE id = #{skuId}` —— **无上限、无幂等谓词**；
- 同一次完结里的**另一条副作用有护栏**（**正对照**）：`AfterSalesTicketService.linkRefundToOrderAndFinance` 用 `setSql("refund_amount = COALESCE(refund_amount,0) + …")` + `WHERE COALESCE(refund_amount,0) + applied <= actual`，`updated==0` ⇒ 跳过 ⇒ 实测退款侧**未翻倍**（300.00 封顶）；
- **同仓更近的对照**：`OrderService.transitionStatusAtomic` 就是「带状态谓词的条件更新 + `rows==0` ⇒ 422」，订单侧并发改状态实测**恰 1 个赢家**（见 D-对照）。

**级别依据（两张纸对齐）**：主会话按 **P1** 开单（issue #6220），理由 = ① 库存/台账**不可逆虚增**（回补 4 次 = 凭空多出 6 米可售库存）；② 与「同一事务里另一副作用有护栏」形成对照（退款侧被挡住、回补侧全裸）；③ 触发门槛极低（双击/双人/客户端重试即可）。
本包初判 P2（依据 = 单机单实例、需并发窗口），**以主会话 P1 为准**。

**边界**：只在工单从 `processing` 并发打 `resolved` 时出现（`pending→resolved` 本就不合法）；
影响面 = 任何「同一张退货/退款工单被重复提交完结」的路径（客服连点、客户端重试、网络重放）。

### D2（P2 · 涉钱精度）`refund_amount=0.001` ⇒ **HTTP 200 但退款金额静默归零**（`LB-PREC-02`、`LB-REF-B03`）

**逐字读数**（`out/B5-refund-precision.json`、`out/B5-col-types.json`）：

```
列类型（现查 information_schema）：
  orders.refund_amount                = numeric(12,2)
  orders.actual_amount                = numeric(10,2)
  finance_transactions.amount         = numeric(12,2)
  after_sales_tickets.refund_amount   = numeric(10,2)

① 0.01  （最小可表示）  ⇒ 200；orders.refund_amount=0.01；流水 1 行 amount=0.01；两侧相等 ✅
② 0.001 （小于最小可表示）⇒ 200；orders.refund_amount=0；流水 1 行 amount=0；refund_at=set  ❌
③ 舍入方向（口径登记）：0.004 ⇒ 0 / 0 ；0.005 ⇒ 0.01 / 0.01 ；0.009 ⇒ 0.01 / 0.01
   （订单侧与流水侧**始终相等** ⇒ 无「一侧 0 一侧非 0」的更重证据）
```

**最小复现**：

```bash
# 建探针已确认订单（实收 300），然后：
curl -X PUT "http://127.0.0.1:8080/api/admin/orders/<probeOrderId>/refund" \
  -H 'Content-Type: application/json' -b "access_token=$TOKEN" \
  -d '{"refund_reason":"精度探针","refund_amount":"0.001"}'
# ⇒ {"success":true,...}（HTTP 200）
# 读库：select refund_amount, refund_at from orders where id='<probeOrderId>';  ⇒ 0.00 | 非空时间戳
#       select amount from finance_transactions where order_id='<probeOrderId>' and type='refund';  ⇒ 0.00
```

**会红的判据**：`refund_amount` 小于列可表示精度（2 位小数，即 `< 0.01` 且 `> 0`）时，必须 **4xx 显式拒绝**，且不得写 `refund_at`、不得写资金流水；
不变式：`orders.refund_amount` 与 `finance_transactions.amount`（同笔）必须**逐字相等**（当前相等，故本条判据落在「该不该接受」上）。

**类级口径依据（同系统内的既有范式是「显式拒绝、不静默取整」）**：
- `backend/admin-api/src/main/java/com/migao/admin/service/StockQuantity.java` 的 `requireOneDecimal`（库存数量超 1 位小数 ⇒ 拒绝）；
- `backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java` 的 `requireItemNumbers`（逐字「超 1 位小数**显式拒绝**、不静默取整」）；
- **金额侧没有对应准入**：`backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java` 的 `refundOrder` 只做 `new BigDecimal(amount.toString().trim())` ⇒ 任意精度进入；而列是 `numeric(…,2)` ⇒ 库内四舍五入。
⇒ 同一系统内**两套精度口径**（数量面拒绝、金额面静默取整）。

### D3（P3 · 读面）列表端点 `size < 0` ⇒ HTTP 200 但 **`total=0` 与返回的整页行自相矛盾**（`LB-C4-NEGATIVE-SIZE`）

**逐字读数**（`out/B4-negative-size.json`；同类读数另见主会话独立复现）：

```
GET /api/admin/orders?page=1&size=-5        ⇒ 200 / total=0 / page=1 / size=500 / rows=492
GET /api/admin/stock-ledger?page=1&size=-5  ⇒ 200 / total=0 / page=1 / size=500 / rows=500
GET /api/admin/after-sales?page=1&size=-5   ⇒ 200 / total=0 / page=1 / size=500 / rows=60
对照（自洽）：size=0      ⇒ 200 / total=真实总数 / rows=0
对照（自洽）：page=99999&size=10 ⇒ 200 / total=真实总数 / rows=0
对照（自洽）：size=100000 ⇒ size 被钳到 500（全局上限）
```

**最小复现**：`curl -b "access_token=$TOKEN" "http://127.0.0.1:8080/api/admin/orders?page=1&size=-5"` ⇒ `total=0` 而 `items` 非空。

**会红的判据**：任意 200 的分页响应必须满足 `items.length <= total`；`total` 必须等于同刻独立 `count(*)`（允许并发写造成的 ≤2 行漂移）。
`size<0` 应 **4xx 或归一化（回退默认 20）并保持 `total` 真实**，不得给出 `total=0` 而返回整页数据。

**根因（源码符号）**：`backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java` 的 `getOrders`（`@RequestParam(defaultValue = "1") long size`，**无下限校验**）；
`backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java` 的 `PaginationInnerInterceptor(setMaxLimit(500))` **只设上限**。
影响：按 `total` 驱动分页器/空态判定的调用方会**把有数据的页面当成「0 条」**。

### 观察项（判据判红不了 ⇒ 只登记，不算缺陷）

| id | 读数 | 说明 |
|---|---|---|
| `LB-REF-B01` | `refund_amount:"1e2"` ⇒ 200 且 `refund_amount=100.00` | `new BigDecimal` 语法上接受科学计数法；口径自洽（接受=100 或拒绝都算自洽），仅登记 |
| `LB-REF-B02` / `LB-REF-C03` | `""` / `"   "` ⇒ 全额退款 | 「空白 = 未传 = 全额」的既有口径，登记 |
| `LB-PREC-03` | 0.004→0 / 0.005→0.01 / 0.009→0.01，两侧一致 | 舍入方向登记（PG `numeric` 四舍五入），不判缺陷 |
| 回补关侧 | 工单带 `refund_amount=200.00` 且开关关 ⇒ 库存零变化，但退款仍照记 200.00 | 语义正确（开关只管库存） |
| 工单 `refund_method` | 全程 `null` | **已转 issue #6224（P3·售后）**：主会话做生产者扫描 ⇒ 后端 **0 个写点**（仅 2 处「实体→响应」的读），而前端 `types/index.ts` 声明为三值枚举 ⇒ 判为**零生产者字段（能力恒为空）**；按铁律 12(b) 把「接线 vs 下线」交人工，不裁时安全默认 = **下线该字段**。（本包 `LB-REF-B05` 给了逐字读数） |

---

## 3. 假红与自身 harness 缺陷（自曝）

> 判据纪律要求：**判据的缺陷与产品的缺陷必须分开报**。以下每条都是本包**自己**的错，已修并重跑（修完的真读数即上文）。

| # | 现象（逐字） | 归因 | 处置 |
|---|---|---|---|
| H1 | `psql()` 单列表子查询报 `function row_to_json(text) does not exist` | 共享 lib 的读器用 `from (…) t`，PG **子查询展平**把单列表拉成标量（加列 / `LIMIT 0` / `OFFSET 0` / `WHERE true` **都拦不住**） | 改用 `with src as materialized (…)`（PG 12+ 不可展平保证）⇒ 读器修好 |
| H2 | 建商品 422「分类ID不能为空」 | harness 少传 `categoryId` | 复用租户既有分类（**不新建**分类，少一类待清理对象） |
| H3 | 建单 422「小计不能为空」 | harness 少传 `items[].subtotal` | 按 `单价 × 数量` 由本包独立算出并传入 |
| H4 | 建单 422「无法定位到 SKU（下单）：已声明 skuCode=…, colorId=…」 | **JS Number 在 >2^53 时静默舍入**：`id`/`color_id` 是 `bigint`，真值 `…3873796` 被读成 `…3873800`，把舍入值回传 ⇒ 订单侧按 `color_id` **精确等值**查 SKU ⇒ 命中 0 行 | 读回时一律 `id::text` / `color_id::text`（真值是**读器**的精度，不是产品的） |
| H5 | 订单停留 `pending`、库存不扣、台账 0 行 | 我调了 `POST /api/admin/orders/{id}/confirm-payment`（**该端点不存在**） | 正确端点是 `PUT /api/admin/orders/{id}/payment` |
| H6 | `LB-AS-RESTOCK-ON/OFF` 422「工单状态不允许从 [待处理] 变更为 [已解决]」 | 我让工单 `pending` 直跳 `resolved`；`STATUS_TRANSITIONS` 里 `pending` 的允许目标是 `{processing, rejected, closed}` | 改走 `pending → processing → resolved` 两步（⇒ 两条判据由假红转 **pass**） |
| H7 | `LB-REF-07` 404「/api/admin/orders/**undefined**/refund」 | 建单请求同样 422（缺 subtotal）⇒ `orderId` 未取到 | 补 subtotal（⇒ 转 **pass**） |
| H8 | `LB-C4` 曾判 **pass**，读数却是 `total=undefined rows=null 2ms` | 响应路径取错（本仓是 `data.items`/`data.total`，不是 `records`/`list`/`content`）⇒ **取不到真值仍判绿 = 假绿** | 改判：取不到真值 ⇒ **fail**；并新增 `typeof total === 'number'` 真值断言（同类假绿见复盘教训） |
| H9 | `LB-AS-RESTOCK-ON/OFF` 曾把期望写死成 `98 → 100` | 夹具被上一轮回补过 ⇒ 基线漂移 ⇒ 假红 | 期望改为**运行时取基线 + 独立算式增量**（不写死数字） |
| H10 | `LB-CTRL-CAS-SQL` 第一版：有谓词组的终值也是 4（"守卫失效"） | **我的 SQL 没改写谓词列**：`SET w=w+1 WHERE … AND status='confirmed'` —— `status` 一直没变 ⇒ 谓词恒真（PG 只在等锁后**重算**谓词，谓词列不变就每次都通过） | 改为 `SET w=w+1, status='producing' WHERE … AND status='confirmed'`（与产品 `set(status,newStatus)` 同形）⇒ 有谓词 w=1 / 无谓词 w=4 |
| H11 | `LB0-02` 时钟自检打印「差 **NaNs**」 | `Date` 解析裸 `YYYY-MM-DD HH:MM:SS` 串（无偏移）不可靠 | 两侧统一按 `+08:00` 显式解析后取毫秒（修后差 0s） |
| H12 | `size=-5` 的读数曾同时拉红 `LB-C4-BULK-READ` 与 `LB-C4-NEGATIVE-SIZE` | 同一现象落在两条判据的域内（判据重叠） | 把负 size 移出主判据域，独立成条（**判据分离 ⇒ 证据不混**） |
| H13 | 16:15 那版 `:8080` **未加载** `SMS_BYPASS_CODE` ⇒ 万能码 401 | 主会话环境失误（已由其带 `.env` 重启修复） | 本包 `LB0-05` 重跑为 **pass**（via=sms-bypass-code）；期间用「`POST /api/auth/sms/send` + 只读 Redis 读回码」的用户等价路径过渡（未绕过鉴权） |

---

## 4. 未覆盖清单（照实登记）

| 缺口 | 为什么没覆盖 | 边界读数 |
|---|---|---|
| **「>1000 行真实数据量」的列表/看板读**（截断、响应时间） | 本租户**没有任何面 ≥1000 行**；自灌 1000+ 探针行会污染活库计数（跨包隔离铁律）⇒ 如实记 `skip` | 现查 `count(*)`：`orders=~500` / `stock_ledger_entries=~650` / `finance_transactions=~570` / `after_sales_tickets=~70`（最大 ~650） |
| **>500 行面的「跨页总计」只覆盖 ledger**（真跨页） | orders/after-sales 的总数 ≤500 ⇒ 单页即可取全，跨页求和未在该两面构成真实考验 | ledger：`size=5000 ⇒ size=500 total=652 rows=500`；`page2 ⇒ 152`；**跨页求和 652 == total** |
| **并发下单导致超卖**（真实 API 面） | 下单流程**不扣库存**（扣减发生在确认收款）⇒ 真实面的并发扣减考验在 `PUT /orders/{id}/payment`；本包以「并发确认收款（真 API）+ 扣减守卫同形 SQL 真并发」两路覆盖，**未覆盖**「并发下单 + 并发确认」的混合形态 | `LB-C3` 三轮：并发扣减终值 0.0；超卖请求 422 且库存保持 3.0；并发收款后 SKU 恰 98.0 |
| **并发派工 / 并发分配同一工序** | 属线A 已占的 `/api/worker/**` 与派工写面（任务书 §2.B3 明确分工）⇒ 本线不重复；本线以「订单/工单并发改状态」近似形态覆盖（`LB-C22`、`LB-CTRL-ORDER-STATUS-CAS`） | 见并发族表 |
| **「服务端已落库但客户端超时」的真实故障注入** | 需要故障注入能力（当前环境无） | 与 `AS-010`/`OR-049` 同族的形态缺口，如实登记 |
| **agent 工具面（米宝）的售后写路径** | 本轮 B1 以 admin-api 直连面为准；AI-TDD 纪律禁止真实 LLM 评测（#4262） | `ai-agent-service:8001` 探活 = 405（内部工具入口需 POST），未做工具级判据 |
| **最坏竞争强度（N ≫ 8、跨进程/跨实例）** | 单机单实例、N≤8；跨实例竞争需多副本部署 | 本包已给「摘守卫 ⇒ 必红」的判别力红证，量化了守卫的作用而非竞争强度的上界 |

---

## 5. 并发判据范式（本轮方法学产出：三条可复用结论）

> 以下三条是本轮**方法学**的产出，写成可复用的「怎么写才算数」；每条都附本轮的自证读数。

### 结论一：**判据的四件套 = N + 逐请求结局 + DB 终态 + 独立算式期望**；DB 终态必须是**不依赖时序**的那一件

- 每轮并发必须记录：**并发度 N**、**逐请求结局（状态码 + 业务码 + 响应摘录）**、**DB 终态（库内最终值）**、**独立算式算出的期望**。
- 判据要挑**库内事实**当主判据，**不要**挑「成功次数」当唯一判据 —— 成功次数对时序敏感，库内终值才是事实。
  本轮实证：`LB-C2` 三轮的响应序列都是 `[200,200,200,200]`，但真正钉死缺陷的是
  **`stock_ledger_entries` 4 行（98→100→102→104→106）** 与 **`ticket_timeline`「→resolved」4 行** ——
  即使某轮没重叠、成功数退化成 1，只要出现「台账 2 行」或「时间线 2 行」，泄漏就成立。
- 独立算式的期望必须**本包算出**，不读被测系统的读面（本轮 C4 的假绿 H8 就是「读面字段名猜错」导致真值取不到）。

### 结论二：**「没真重叠」的判定 = 逐对时间区间求交 + 并集宽度 vs 各历时之和，而不是「用了 Promise.all」**

- 本包的判据（`lib.mjs` 的 `overlapEvidence`）：
  `maxPairOverlapMs > 0` ⇒ 真重叠；同时给出 `unionMs < sumMs` 的对照（串行时两者相等）。
- 本轮实证：`LB-C2` R1 = **最大逐对重叠 987ms（并集 1319ms < 各历时之和 3389ms）**；`LB-C1/C3/CTRL` 三轮均报真重叠。
- **反例规则（写进判据）**：若某轮未观察到重叠 ⇒ 该轮的绿**不算通过**，整条记 `假红(falseRed/无判别力)`，并在 `detail` 里写明
  「并集 ≈ 和」的读数 —— 这样「假绿」在数据上无处藏身。
- 另有一条**独立于重叠**的判别点（比重叠证据更硬）：**同一并发装置下换一条实现必然变号**。
  本轮用 `LB-CTRL-*` 与 `LB-CTRL-CAS-SQL` 做到了：**同一时刻同一装置**，订单侧（有状态谓词）**恰 1 个赢家**、
  售后侧（无谓词）**4/4 全成**；SQL 层量化 **有谓词 w=1 / 无谓词 w=4**。

### 结论三：**判别力红证 = 「摘掉守卫必红」+「同一装置加回守卫必绿」的双向对照**；注入的 UPDATE 必须**同时改写谓词列**

- 只给「必红」的半边不够（可能装置本身就是恒红）；必须**同一装置、同一 N** 给出**双向**读数：
  本轮 `LB-C1-REDPROOF`：`N=8` 独立 psql 进程，**无守卫 ⇒ 终值 800（> 上限 300，泄漏）**；**有守卫 ⇒ 终值 300（守住）**。
- 注入只允许在**本包自建临时表 / 副本**上做（`lb_gp_redproof` / `lb_gp_stock` / `lb_gp_timeline` / `lb_gp_orderstatus`，用后即 `drop`）——
  **未改任何产品源码、未提交任何东西**。
- ⚠️ 踩过的坑（H10）：注入的 `UPDATE` 如果**不改写谓词列**，谓词在并发下恒真 ⇒ 双向对照会**双双变成 4**
  （看起来像「守卫无效」）。**谓词列必须被本次 UPDATE 同时改写**，否则该红证**无判别力**。
- 附带形态：**「读数对被测行为敏感」也可单独自证** —— `LB-C23-ROWCOUNT-REDPROOF` 证明「时间线行数」不是空断言
  （4 次写 ⇒ 4 行；1 次写 ⇒ 1 行）。

---

## 6. 零残留终态

- 探针命名域：名称前缀 **`线B验收`**、id/键前缀 **`lb`**、工单号前缀 `LB-AS-`（本包自建）。
- 清理器：`harness/lib.mjs` 的 `cleanupProbe()`（只按本包前缀匹配：订单 `remark`、工单 `description`、商品 `name`/`sku_code`、
  台账按探针 product/sku 关联、`finance_transactions` 按探针订单关联、`client_request_keys` 的 `lb-` 前缀、临时表 `lb_gp_*`）。
- 终态读数：`out/SUMMARY.json` 的 `residue` + `out/Z-residue.json` + `out/B9-residue.json`（逐表计数全 0）。
- 存量行零改动：`out/B9-stock-before.json`（前）vs `out/B9-residue.json`（后）的 sha256 对照。
  ⚠️ 台账/流水两表参与对照，而同租户**线A 并发包**也在写 ⇒ 若 sha 不一致，先**按行内容归因**（本包行已删；外来行 ⇒ 记 `skip` 并说明）。
- **涉钱面处置**：全程只用**本包自建探针订单**；对存量订单只做过**一次只读退款探针**（`cancelled` 态被拒），前后行 sha 对照零改动（`LB-REF-06` 早期版本），后续版本改为自建 cancelled 单，**不再触碰存量订单**。

---

## 7. 产物与一键重跑

```
acceptance/2026-10-03/aftersales-concurrency-sweep/
├── REPORT.md                       # 本文件
├── BRIEF.md                        # 任务书（主会话下发）
├── harness/
│   ├── lib.mjs                     # 本包共享库（psql 读器 / raceStart / overlapEvidence / 探针建清 / 红证注入）
│   ├── p0-env.mjs                  # 手表：构建点自证 + 时钟自检 + 端点鉴权面 + 存量基线
│   ├── p1-setup.mjs                # 夹具：探针商品（回补开关两侧）+ 已确认探针订单 + 扣减台账自证
│   ├── p2-b1-serial.mjs            # B1 串行闭环：建单/状态机/退款金额/回补开关两侧/三方自洽
│   ├── p3-b2-concurrency.mjs       # B2 并发族 C1~C4（每类 3 轮 + 重叠证据 + 判别力红证）
│   ├── p4-probe-batch.mjs          # 金额边界 + 状态机并发面(C21/C22/C23) + 行数红证 + C4 重做
│   ├── p5-refund-precision.mjs     # 涉钱精度三连（0.01 / 0.001 / 舍入方向）+ 列类型真值
│   ├── p6-order-status-control.mjs # 正对照：订单侧 CAS 守卫 + SQL 层量化
│   ├── p7-refund-negative.mjs      # 退款负例补强（null / 非法串 / 空白串）
│   ├── p8-stock-before.mjs         # 存量行基线快照（sha256）
│   ├── p9-cleanup.mjs              # 零残留自证（逐表计数 + sha256 前后对照）
│   └── run-all.mjs                 # 一键重跑（顺序即安全顺序）
└── out/                            # 逐条 JSON + SUMMARY.json + run.log + run-all.log
```

**一键重跑**（约 3~5 分钟；顺序即安全顺序：手表 → 基线 → 夹具 → 判据 → 清理 → 汇总）：

```bash
cd "/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/aftersales-concurrency-sweep/harness"
API_BASE=http://127.0.0.1:8080 node run-all.mjs
# 只跑某几段（S 别名见 run-all.mjs 的 ALIAS）：
SEGMENTS=p0,p8,p1,p3 API_BASE=http://127.0.0.1:8080 node run-all.mjs
# 只做清理 + 汇总（不重跑判据）：
SKIP_RUN=1 API_BASE=http://127.0.0.1:8080 node run-all.mjs
```

**纪律声明**：本轮**未**运行 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁），
**未**做真实 LLM 评测（#4262），**未**改任何产品源码 / 测试 / 用例，**未**提 PR、**未**开 issue。
