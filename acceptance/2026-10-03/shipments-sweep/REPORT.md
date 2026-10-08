# 发货单 / 仓储链 —— 功能级验收报告

- **包名**：`shipments-sweep`（产线 ①：发货单 / 仓储，**新功能首次功能级验证**）
- **租户**：`20`（米高POC演示布艺）
- **日期 / 时区**：2026-10-03，**本机时区 Asia/Shanghai（UTC+8）**；原始读数若为 UTC 均标注换算
- **产物**：`acceptance/2026-10-03/shipments-sweep/{REPORT.md, harness/, out/}`
- **本包不改任何 MIGAO 业务代码**（只新增验证工装）

## 0. 结论（一句话）

发货链的**双发防护在工人侧成立**（串行/并发/同幂等键三种打法下都只产生 1 张有效发货单，红证两侧夹住），
**但「少发/错发可核」这条链在"多发"方向是敞开的**：系统**从不校验「累计已发 ≤ 订单量」**，
且**商家发货路完全不产生发货单**。共 **6 条缺陷**（3×P1 / 3×P2）+ 1 条观察项（P3-F7）。

| 读数 | 值 |
|---|---|
| 判据总数 | **79**（pass **68** / fail **7** / skip **4**） |
| 其中 fail 的构成 | **6 条为缺陷登记**（判据报红 = 缺陷成立）+ **1 条为自检控制项**（`R0-VACUOUS-CONTROL`，**故意**为假，证明 `judge()` 的 FAIL 侧可达） |
| 真实缺陷数 | **6** |
| 探针存活残留 | **0**（直连 RDS 逐表计数，见 §6） |
| 墙钟 | 40.3s（79 条判据） |

> 🔴 **归因纪律**：本报告只对**有 RDS 原始读数或 HTTP 原始响应作证据**的条目下结论；
> 证据不足的一律写「未覆盖 / 待归因」（§7），不编归因。

## 1. 环境与构建点（含「已合并未必已部署」披露）

| 项 | 读数 | 来源 |
|---|---|---|
| admin-api | `http://localhost:8080`（在跑） | 活环境实测 |
| **构建点（部署来源 commit）** | **`1233b8a42`**（full `1233b8a426036d77d93b928bfbcee5b644686bf1`） | `git -C /Users/guangzhen.zk/migao-wt/main-live rev-parse --short HEAD` |
| 构建点 commit 时间 | `2026-10-03T09:58:07+08` | 同上 |
| 构建点 subject | `fix(production): #6126 工序设置写面不再凭空新建价目行（连空 payload {} 也建、只增不减） (#6129)` | 同上 |
| **admin-api 进程启动时刻** | `2026-10-03 09:58:44 +08`（读数时已运行 46 分 34 秒） | `lsof -nP -iTCP:8080 -sTCP:LISTEN -t` → `ps -o lstart=` |
| 测量窗口 | `2026-10-03 18:47:21 +08` ~ `18:50:13 +08` | `out/summary.json` |
| 部署窗口核查（migao-acceptance v1.9） | 进程启动 **09:58:44** 早于测量窗口 **08h49m**，窗口内**无重启** ⇒ 测量落在稳定运行期，红/绿均有效 | 进程启动时刻 vs 逐条判据时间戳 |
| 被测 DB | 云 dev RDS（凭据取自 `backend/admin-api/.env`） | `psql` 直连 |
| admin-web | `http://localhost:3001` 返回 200（**未做 UI 面驱动**，见 §7） | HTTP 读数 |

> **「已合并未必已部署」披露**：本报告的全部结论只对**上表这个部署点**成立。
> 工作树 `main-live` 的 HEAD 在本次测量期间**未移动**（`1233b8a42` 在测量前后两次读数一致）；
> 但仓库 `main` 在同日已被其他包推进（`d2965ea35`）⇒ **本报告的读数不能当作 `main` 的健康度证据**。

### 1.1 并行包干扰核查（无干扰）

并行包（跨租户隔离 + 权限）在同一租户上作业 ⇒ 按任务书口径做**只读观测**：

| 项 | 读 1 | 读 2 | 判定 |
|---|---|---|---|
| 租户 20 非探针订单数 | 359（`18:47:5x +08`） | 359（`18:50:1x +08`） | 无变化 |
| 非探针订单 `max(updated_at)` | `2026-10-03T08:49:49.194304+08` | 同左（**早于本包测量窗口 2 小时**） | 本包运行期**无他人写** |
| 全租户发货单数 | 1（本包运行前既有的一张，非本包对象） | 1（本包清理后） | 无变化 |

⇒ **未观测到并发干扰**。本包全部写操作只命中自建对象（id 前缀 `fa`/`fb`/`fc`、客户名统一带 `发货验收` 前缀），
`assertProbe` / `guardedWrite(-- probe-ok)` 两道守卫在代码层禁止触碰他人行（`out/run.log` 可核）。

## 2. 链路枚举（先枚举，别猜）

完整 JSON：`out/surface.json`（含逐端点 / 逐表列 / 逐唯一约束 / 状态机 / 前端文件）。
枚举来源三路交叉：**OpenAPI `GET /v3/api-docs`（244 条路径）** ⊕ **Java 源码 grep** ⊕ **`psql` DDL**。

### 2.1 端点（25 条含发货/仓储/库存关键词；发货链实际一跳不落如下）

| 跳 | 端点 | 角色面 | 作用 |
|---|---|---|---|
| ① 打包 | `POST /api/worker/shipment/orders/{orderId}/pack` | 工人（`X-Worker-Session-Id`） | `confirmed\|producing → packed`，落 `packed_at/by` |
| ② **发货（记实发）** | `POST /api/worker/shipment/orders/{orderId}/ship` | 工人 | 记 `order_shipment_items` 逐行实发 + 物流 + 原子流转 `shipped` |
| ③ 撤销打包 | `POST /api/worker/shipment/orders/{orderId}/unpack` | 工人 | `packed → producing`，**必带理由** + 留痕 |
| ④ 工人读面 | `GET /api/worker/shipment/orders/{orderId}` | 工人 | 发货单 + 逐行实发 + `shipped_totals` |
| ⑤ 按单读面 | `GET /api/admin/orders/{id}/shipments` | 商家 | 「这一单发了多少」 |
| ⑥ **发货单列表** | `GET /api/admin/shipments?keyword=` | 商家（`order:list`） | 流水读面（issue #5939，新增） |
| ⑦ 拍照识别 | `POST /api/worker/shipment/recognize` | 工人 | 图 → 候选文字，**不落库** |
| ⑧ **商家 / 生产发货** | `POST /api/admin/production/orders/{orderId}/ship` | 商家（`production:execute`） | **只**记物流 + 流转 `shipped`（**不写发货单**，见 F4） |
| ⑨ 打印计数 | `POST /api/admin/production/orders/{orderId}/print` | 商家 | `processing_orders.print_count` +1（按 `order_id` 找加工单） |
| ⑩ 状态流转 | `PUT /api/admin/orders/{id}/status`（路由正则 `[0-9a-fA-F-]+`） | 商家 | 裸状态接口（回退**不在此表**） |
| ⑪ 补打前端路径 | `GET /api/admin/orders/{id}`（订单）+ `GET /api/admin/orders/{id}/shipments` | 商家 | `ShipmentDoc` 的**数据源**（见 §7 观察项 O1） |

### 2.2 表 / 字段 / 状态取值

| 表 | 关键列 | 唯一约束 |
|---|---|---|
| `order_shipments` | `shipment_no, source, photo_refs, recognition, packed_at/by_*, shipped_at/by_*, tracking_no, logistics_company, unpacked_at/by_*/unpack_reason` | `pkey(id)` · `uk_order_shipments_idem(tenant_id, client_request_id) WHERE client_request_id IS NOT NULL AND deleted=0` |
| `order_shipment_items` | `shipment_id, order_id, order_item_id, product_name, shipped_quantity **numeric(10,2)**, unit, set_count, roll_count` | **只有 `pkey(id)`（无 (shipment_id, order_item_id) 唯一）** |
| `orders` | `status` | — |
| `order_items` | `quantity numeric, processing_info jsonb` | — |
| `order_logistics` | `tracking_no, logistics_company, shipper_name` | — |
| `client_request_keys` | `(tenant_id, client_request_id, endpoint), response_payload jsonb` | 幂等占位表 |

**状态机（`OrderStatusTransitions.java` 逐字取）**：

```
pending    → {confirmed, cancelled}
confirmed  → {producing, packed, shipped, cancelled}
producing  → {packed, shipped, cancelled}
packed     → {shipped}          ← 撤销打包**有意不在表内**（具名动作 + 必带理由）
shipped    → {completed}
completed  → {}
cancelled  → {}
可发货起始态 SHIPPABLE_FROM = {confirmed, producing, packed}
```

## 3. 判据矩阵（期望来源 / 实测 / 结论）

> 「期望来源」列一律写清期望是**怎么独立算出来的**；凡取系统自身读面者已显式标注并只作**交叉核对**。
> 逐条完整证据（HTTP 原始响应 + SQL 原文 + 时间戳）：`out/p{1..7}-records.json`。

### P1 双发防护（20/20 pass）

| id | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| S1-FIX | 夹具自证：订单行数量落库 == 我们给的量 | 夹具给定（非系统读面） | 10.000 == 10.000 | pass |
| S1-1 | 串行双发：只 1 张有效发货单 | 本包判据 + RDS `order_shipments` | 1 | pass |
| S1-2 | 串行双发：Σ已发 ≤ 订单量 | 独立算式（订单量 10） | 10.000 | pass |
| S1-3 | 第二次被拒（422）且状态未回退 | `shipped ∉ SHIPPABLE_FROM` | 422 + `status=shipped` | pass |
| S1-4 | 未发量 == 订单量 − Σ已发 | 独立算式 | 0.000 == 0.000 | pass |
| S1-5 | 读面 `by_unit` 与 RDS 原始列一致 | **RDS 原始列**（读面只被核对） | 10.000 == 10.000 | pass |
| S1-6 | 发货单留痕 `shipped_at`/`shipped_by` 非空 | 责任凭证（`WorkerShipmentController` 头注） | 均非空 | pass |
| S2-DISC | 判别性证据：两路**真的同刻打出** | `Promise.all` + 墙钟 | HTTP `[422,200]`，墙钟 299ms | pass |
| S2-1 | 并发双发（**不带幂等键**）：只 1 张 | 本包判据 + RDS | 1 | pass |
| S2-2 | 恰一路 2xx、另一路 4xx | 状态机原子流转（影响行数 0 ⇒ 422 ⇒ 回滚） | `[200,422]` | pass |
| S2-3 | 明细不重复记账 | 独立算式（订单量 8） | 8.000（1 行） | pass |
| S2-4 | 无残留半成品（无孤儿明细） | RDS join | shipments=1 items=1 orphan=0 | pass |
| S3-1 | 同幂等键并发：只 1 张 / 1 行 / 不超发 | 幂等占位原子 claim | 1/1/6.000 | pass |
| S3-2 | 第二路为回放/在飞（无第二个 `shipment_no`） | `ClientRequestIdService` 语义 | 两路同号 `SH…142035` | pass |
| S3-3 | 同键串行重放：不新建、不改量 | 同键 = 回放首次快照 | shipments=1，Σ 不变 | pass |
| S4-1 | 正对照：正常发货被接受 | `confirmed ∈ SHIPPABLE_FROM` | HTTP 200 | pass |
| S4-2 | Σ已发 == 我们给的实发合计 | 独立算式 12.5+3=15.500 | 15.500 | pass |
| S4-3 | 逐件等价（含 `null` 不被写成 0） | 「缺值不猜」 | 逐件一致，`roll_count=null` 保持 | pass |
| S4-4 | 一步到底补记 `packed_at` | `doShip` 同事务补记 | 非空 | pass |
| S4-5 | 待发量 == 0 | 独立算式 | 0.000 | pass |

### P2 状态机（15/16 pass；1 fail = F3）

| id | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| T1-1 | `confirmed → packed` 被接受且落 `packed_at/by` | `STATUS_TRANSITIONS` | 200 / packed / 均非空 | pass |
| T1-2 | `packed → shipped` **同一张**单延续 | `activeShipment()` 复用 | 200 / shipped / 1 张 | pass |
| T2-ROUTE | 判别性前置：请求**真进状态机**（非路由 404 空断言） | `@PutMapping("/{id:[0-9a-fA-F-]+}/status")` | 422 `VALIDATION_ERROR` | pass |
| T2-1 | `confirmed → delivered` 被拒 | `isKnownStatus(to)==false ⇒ 422` | 422 | pass |
| T2-2 | 非法流转**不改库** | RDS 前后逐字段 diff | diff = **0 处** | pass |
| T3-1 | `packed → producing` 走裸状态接口被拒 | `packed → {shipped}` | 422 | pass |
| T3-2 | 非法流转不改库 | 逐字段 diff | 0 处 | pass |
| T4-1 | 撤销打包空理由被拒 | `doUnpack` 必带理由 | 422 / 仍 packed | pass |
| T4-2 | 撤销打包留痕三项非空 | 涉责任动作不留白 | 200 / producing / 三项非空 | pass |
| T4-3 | 撤销不影响已发数量 | 独立算式 | items=0，无 `shipped_at` | pass |
| **T4-4** | **撤销后 `packed_*` 被清空** | `setPackedAt(null)` 的**意图** | **`packed_at` 仍为原值** | **FAIL → F3** |
| T5-1 | 已发货单不可撤销打包 | 仅 `packed` 可撤销 | 422，无 `unpacked_*` | pass |
| T5-2 | 已发货订单不可直接取消 | `shipped → {completed}` | 422 | pass |
| T5-3 | 两次非法回退后单据/数量不变 | 逐字段 diff | 0 处，Σ=4.000，1 张 | pass |
| T6-cancelled | `cancelled` 不可发货且零写 | `SHIPPABLE_FROM` | 422 / diff 0 / 0 张 | pass |
| T6-pending | `pending` 不可发货且零写 | `SHIPPABLE_FROM` | 422 / diff 0 / 0 张 | pass |

### P3 独立算式（8/12 pass；4 fail = F1/F2/F5/F6）

| id | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| **M1-OVER** | 实发 999 > 订单 10 ⇒ 必须被拒 | 独立算式（上限 = 10） | **200，Σ=999.000** | **FAIL → F1** |
| M2-EXACT | 实发 == 订单量 ⇒ 接受且逐分一致 | 独立算式（= 12.5） | 200，12.500 | pass |
| M3-M3a | 0 件 ⇒ 422 且不落明细 | `qty<=0` 拒绝 | 422，Σ=0，0 行 | pass |
| M3-M3b | 负数量 −3 ⇒ 422 | 同上 | 422 | pass |
| M3-M3c | 缺 `shipped_quantity` ⇒ 422 | 同上 | 422 | pass |
| M3-M3d | 0.001（正）⇒ 接受，落库 = 列精度 0.00 | 独立算式按 `numeric(10,2)` | 200，Σ=0.000 | pass |
| **M3d2-ZERO-ROW** | 接受发货后 Σ 必须 > 0 | 独立算式（最小可表示 0.01） | **200 / shipped / Σ=0.000 / 1 行** | **FAIL → F6** |
| **M4-DUP-LINE** | 同一 `order_item` 写两行 6+6（=12 > 10）⇒ 不得超量 | 独立算式（上限 10） | **200，Σ=12.000，2 行** | **FAIL → F2** |
| M5-CONC-OVER | 并发两路各发满量 ⇒ 不双记 | 独立算式 + 状态机 | Σ=10.000，1 张，`[422,200]` | pass |
| M6-REMAIN | 多行部分发货：逐行未发量 | 独立算式（逐行） | A=6.000 B=0.000 | pass |
| M7-DECIMAL | decimal 语义按列精度解析 | 原文经 `numeric(10,2)` | 12.500 / 0.000 | pass |

### P4 写后等价性 + 补打/导出/打印（8/9 pass，1 skip）

| id | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| W1-1 | 发货写面 HTTP 成功（前置） | — | 200 | pass |
| W1-2 | 🔴 变化集 ⊆ payload 键 ∪ 显式声明审计列 | 本包声明的允许集 | **越界 0 处** / 总变化 4 处 | pass |
| W1-3 | `orders`/`order_items` 业务列零变化 | 发货只记事实 | 仅 `orders.status` | pass |
| W2-1 | 同幂等键 + **不同 payload** ⇒ 回放首次快照 | 幂等契约（#4037） | `tracking_no` 与 Σ 均不变，diff=0 | pass |
| P1-1 | 补打数据源连读两次逐字段一致 | 前端补打路径 = 订单 + 单据读面 | hash 两侧相同 | pass |
| P1-2 | 打印端点连打两次：不新建单据、不改数量 | `recordPrint` 只写计数 | shipments=1，变化列 `[]` | pass |
| P1-3 | 补打不改已发数量 | 独立算式（9） | 9.000 | pass |
| P1-4 | `print_count` 每次 +1（证明该面**真被调用**） | RDS `processing_orders.print_count` | 0 → 1 → 2 | pass |
| P2-EXPORT | 发货单**导出**面 | — | 三条候选路径 404/404/（200 但为普通列表 JSON） | **SKIP：不存在（如实登记）** |

### P5 库存 / 出库回补 / 打印邻面（4/8 pass，1 fail = F4，3 skip）

| id | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| K1-1 | 发货**不写**库存台账 | 代码事实 + `reason` 枚举 | 本单台账 0 行（全租户 385 → 385） | pass |
| K1-2 | 发货扣减库存面 | — | 枚举无该面 | **SKIP：不存在** |
| K2-RESTOCK | 退回 / 回补 / 回补幂等面 | — | OpenAPI 无发货单回补语义 | **SKIP：不存在** |
| K3-1 | 商家发货路：`confirmed → shipped` + 记物流 | `shipWithLogistics` | 200 / shipped / 1 行 | pass |
| K3-2 | **商家发货路不产生发货单** | 代码事实（不写 `order_shipments`） | shipments=**0** / logistics=1 | pass（并作为 F4 证据） |
| K3-3 | 重复调用不产生第二张单（物流被覆写） | `upsertLogistics` | 200 / 0 张 / 1 行 / `tracking=SF-ADMIN-2` | pass |
| **K3b-1** | **同 `X-Client-Request-Id` 两次调用应回放** | 幂等契约（#4037） | `7777 → 8888 → 9999`，`client_request_keys` **0 行** | **FAIL → F5** |
| K4-INBOUND | 入库标签补打（`/worker/inbound/labels/{shortCode}/print`） | — | 不在本包射程（另半边） | **SKIP：未覆盖** |

### P6 红证（11/12 pass；1 fail = 控制项）

| id | 判据 | 实测 | 结论 |
|---|---|---|---|
| R0-VACUOUS-CONTROL | 故意写一条必然为假的期望 ⇒ 必须 FAIL | status=`fail` | **故意红**（证明 `judge()` FAIL 侧可达） |
| R0-VACUOUS-PROOF | 上面那条确实落了 FAIL（不是空跑） | records 可见 | pass |
| R1-POS-CTRL | 正对照（干净世界）⇒ ①恰 1 张 ②不超发 **都绿** | ①true(n=1) ②true | pass |
| R2-INJECT-APPLIED | 注入**真的生效**（内容指纹 `0e71c9d6…→7f9ccbdf…`） | `["999"]` | pass |
| R2-REDPROOF | 🔴 已发量被改大 ⇒ 判据**当场红**并报出超发量 | `over=989.000` | pass |
| R2-CROSSFACE | 交叉面：被改大量在系统读面亦可见 | `by_unit.米 = 999` | pass |
| R2-RESTORED | 还原**真的生效** ⇒ 判据回绿（两侧夹住） | pass=true，读数 6 | pass |
| R3-INJECT-APPLIED | 注入第二张有效发货单**真的生效** | 1 → 2 行 | pass |
| R3-REDPROOF | 🔴 出现第二张有效单 ⇒ 「恰一张」**当场红** | pass true→false，actual=2 | pass |
| R3-LISTFACE | 交叉面：列表读面命中 2 行 | 2 | pass |
| R4-REDPROOF | 世界改成 `shipped` 后再发货 ⇒ 4xx 且**零写** | 422 / 0 张 / 0 行 | pass |
| R5-1 | 注入「含加工项 + 无完成加工单」⇒ 发货被拒且零写 | 422 / 0 张 / 0 行 | pass |

### P7 零残留（2/2 pass）

| id | 判据 | 实测 | 结论 |
|---|---|---|---|
| NR-1 | 探针存活残留 = 0 | total=**0**（11 张表全 0） | pass |
| NR-2 | 探针边界自证：租户 20 存量订单未被触碰 | 非探针订单 359 | pass |

## 4. 发现清单

> 每条：级别 + 最小复现 + 影响面 + **一句话判据**。全部为**本包判据报红**，红证两侧夹住（§5）。

### 🔴 P1-F1 超发无任何上限校验（发货链头号风险的反面）

- **级别**：P1
- **判据**：`M1-OVER` / `M1-OVER-DEFECT`
- **最小复现**：建订单（`order_items.quantity = 10`，`status = confirmed`）→
  `POST /api/worker/shipment/orders/{id}/ship`，`body.items[0].shipped_quantity = 999`
  → **HTTP 200**，`order_shipment_items.shipped_quantity = 999`，订单流转 `shipped`。
- **证据**：`out/p3-records.json` → `M1-OVER`；`POST body` / `resp(200)` / `SQL` 三段原文。
- **改写点（代码级）**：`OrderShipmentService.parseDetails` 只校验
  `qty > 0` 与「`order_item_id` 属于该订单」，**从不与 `order_items.quantity` 比较**；
  DB 侧 `order_shipment_items` 也无任何上限约束。
- **影响面**：`#5648` 的唯一目标（「少发/错发**可核**」）在**多发方向失效** ——
  实发量、`shipped_totals`、纸面补打、下游对账全部读到超量数字，且订单已 `shipped`（不可撤销、不可再发）。
- **一句话判据**：`Σ order_shipment_items.shipped_quantity ≤ order_items.quantity` 必须恒成立，实测被打破（999 > 10）。

### 🔴 P1-F2 同一订单行可在同一请求里写多行 ⇒ 绕过"合计"语义

- **级别**：P1
- **判据**：`M4-DUP-LINE`
- **最小复现**：`items = [{order_item_id: X, 6}, {order_item_id: X, 6}]`（订单量 10）→
  **HTTP 200**，落 **2 行**，Σ = 12.000 > 10。
- **证据**：`out/p3-records.json` → `M4-DUP-LINE`（含 `resp(200)` 与两行 SQL 原文）。
- **DDL 依据**：`order_shipment_items` 唯一约束**只有主键** `order_shipment_items_pkey`（`pg_indexes` 实读），
  没有 `(shipment_id, order_item_id)` 唯一。
- **影响面**：与 F1 同族、但更隐蔽 —— 单看每行都"不超"（6 ≤ 10），合计才超；
  任何按行校验的修法都会被这个形态绕过。
- **一句话判据**：同一 `shipment` 对同一 `order_item_id` 的**合计**实发 ≤ 订单量，实测 6+6=12 > 10 被放行。

### 🔴 P1-F3 商家发货路**完全没有幂等保护**

- **级别**：P1
- **判据**：`K3b-1`（此前 `K3-3` 已观测到覆写，本次加判据钉死）
- **最小复现**：`POST /api/admin/production/orders/{id}/ship` 带**同一个** `X-Client-Request-Id` 连打两次
  → 两次都 **200** 且都生效：`tracking_no` `SF-FIRST-7777 → SF-SECOND-8888 → SF-THIRD-9999`；
  查 `client_request_keys`（按该键）→ **0 行**（该端点从未接幂等键）。
- **代码依据**：`ProductionController.ship` 直接转发 `OrderService.shipWithLogistics`，
  **未走** `ClientRequestIdService.claim`（worker 侧的 `pack`/`ship`/`unpack` 三个写面都走了）。
- **影响面**：发货是**涉物流凭证**的写动作 —— 客户端超时重试（HTTP 客户端 25s / 工具 30s 窗口客观存在，
  正是 #4037 的立项理由）会把运单号**静默改写**成第二次的值，纸面/物流/客户三方对不上；
  且该路**不产生发货单**（F4），连"发了几次"都无处可查。
- **一句话判据**：同 `X-Client-Request-Id` 的第二次发货请求必须回放首次结果（`tracking_no` 不变），实测被第二次 payload 覆写。

### 🟠 P2-F4 商家发货路不产生发货单 ⇒ 「已发货」在发货单链上是不可见的

- **级别**：P2
- **判据**：`K3-1` / `K3-2`（判据本身 pass，红的是**业务后果**，故按发现登记）
- **证据**：商家发货后 `order_shipments` = **0 行**、`order_logistics` = 1 行、`orders.status = shipped`；
  而 `GET /api/admin/shipments`（发货单列表）与 `GET /api/admin/orders/{id}/shipments` 都以
  `order_shipments` 为唯一来源 ⇒ **该订单在发货单链上查不到，也没有任何实发数量**。
- **影响面**：同一"已发货"事实有**两个真值面**（`order_logistics`/`orders.status` vs `order_shipments`），
  只有其中一面能被「发货单」消费；`#5939` 新做的列表页对这类订单**永远显示不出来**（用户报障的原始形态）。
  另外：`ShipmentDoc`（纸面）数据源是订单本身（联 `order_logistics`），**不读实发明细** ⇒
  少发场景下纸面印的是**订单量**而不是**实发量**（见 §7 O1）。
- **一句话判据**：任何把订单置为 `shipped` 的写面都必须留下 `order_shipments` 行（否则发货单列表漏单），实测商家路违反。

### 🟠 P2-F5 「撤销打包」声称清空 `packed_*`，实际没清 ⇒ 状态与留痕不一致

- **级别**：P2
- **判据**：`T4-4`
- **最小复现**：`pack`（落 `packed_at`/`packed_by_worker_name`）→ `unpack`（HTTP 200，订单回到 `producing`）
  → 查 `order_shipments`：`packed_at = 2026-10-03T10:49:33.006658+08`、`packed_by_worker_name = 发货验收工人`
  **仍为原值**；`unpacked_at`/`unpack_reason` 正常落库。
- **代码依据**：`OrderShipmentService.doUnpack` 显式 `setPackedAt(null)` / `setPackedByWorker*(null)` 后调
  `orderShipmentMapper.updateById(shipment)`；MyBatis-Plus 默认更新策略**跳过 null 字段**
  （`application.yml` 未声明 `update-strategy`）⇒ 三处置空**静默无效**。
- **证据**：`out/p2-records.json` → `T4-4`（含 `at`/`by` 原始读数）。
- **影响面**：「已撤销打包却仍标着已打包」—— `readShipment` 的 `packed_at`/`packed_by` 字段会给出**过期事实**，
  车间/对账据此判断"这单已经打包了"；同一形态会命中**所有**"置 null 清字段"的意图（类级风险）。
- **一句话判据**：`unpack` 成功后 `order_shipments.packed_at` 与 `packed_by_worker_*` 必须为 NULL，实测仍为撤销前的值。

### 🟠 P2-F6 极小正数量被列精度吃成 0 ⇒ 产生"已发货但实发 0"的单据

- **级别**：P2
- **判据**：`M3d2-ZERO-ROW`（配套 `M3-M3d` / `M7-DECIMAL` 记录列精度）
- **最小复现**：`shipped_quantity = 0.001`（订单量 10）→ **HTTP 200**，订单流转 `shipped`，
  而 `order_shipment_items.shipped_quantity` 落 **0.00**（`information_schema`：`numeric(10,2)`）。
- **影响面**：`totals()` 按单位汇总得 0 ⇒ 「实发 = 0 却已发货」这一自相矛盾形态可入库；
  订单随即进入终态（不可再发、不可撤销/回退），只能作废重开；
  下游（纸面 / 对账 / 计件口径）读到 0 会与工人的实际动作不一致。
- **一句话判据**：`/ship` 接受 `shipped_quantity > 0` 后，落库实发合计必须 > 0（或直接 422），实测落 0.00。

### 🟡 P3-F7（观察/建议，非缺陷）并发同幂等键「在飞窗口」偶发 422 而非回放

- **判据**：`S3-2`（判据 pass —— 两种结局都合法，但语义强弱不同）
- **读数**：两次独立运行分别观测到
  ① 第二路 200 + `replayed=true`（回放）；
  ② 第二路 **422**「订单状态已并发变更，请刷新后重试」（撞上状态机原子流转，**未**走到幂等回放）。
- **判定**：**不是缺陷** —— 两路都只产生 1 张单、1 行明细、不超发（`S3-1` 两轮均 pass）。
  但"幂等"在产品语义上应当是"同键必回放"；实测在**在飞窗口**会退化为一个**非回放**的 422。
- **一句话判据**：同 `X-Client-Request-Id` 的并发第二路，期望**恒为回放**（200/409 `REQUEST_IN_PROGRESS`），实测偶为 422 状态机冲突。

## 5. 红证（逐字）

> 纪律：每条关键断言都要有红证；红证本身要**自证注入/还原真的生效**（**内容指纹**，禁用 mtime/size）。
> 逐字原文在 `out/p6-redproof-records.json`。

**① 判据不空自证（先证明判据的"红"侧可达）**

```
R0-VACUOUS-CONTROL  status=fail  detail=期望 99（故意错） ≠ 实测 1
R0-VACUOUS-PROOF    status=pass  detail=records 里可见 R0-VACUOUS-CONTROL.status=fail
```

**② 独立算式判据的红证（注入：把已发量改大）**

```
R2-INJECT-APPLIED   期望 注入前后 shipped_quantity 指纹不同 ∧ 读数 999
                    实测 0e71c9d61a801b86 → 7f9ccbdf4907f11e ∧ ["999"]
R2-REDPROOF         期望 注入前 pass=true，注入后 pass=false 且 over=989.000
                    实测 注入前 pass=true；注入后 pass=false
                        violations=[{"orderItemId":"fsitem…","sum":"999.000","limit":"10.000","over":"989.000"}]
R2-CROSSFACE        实测 {"set_count":0,"roll_count":0,"by_unit":{"米":999}}
R2-RESTORED         期望 还原后 pass=true ∧ 读数 6 —— 实测 pass=true 读数=["6"]
```

**③ 双发防护判据的红证（注入：造第二张有效发货单）**

```
R3-INJECT-APPLIED   期望 注入后 rowCount=2 ∧ valid=2 —— 实测 注入前 rowCount=1 → 注入后 rowCount=2（valid=2）
R3-REDPROOF         期望 注入前 pass=true，注入后 pass=false（actual=2）
                    实测 注入前 pass=true；注入后 pass=false actual=2
R3-LISTFACE         期望 2 == 实测 2（发货单列表读面同样看得见第二张 ⇒ 注入落在被测真值上）
```

**④ 状态机判据的红证（注入：手工把订单置为 `shipped`）**

```
R4-REDPROOF  期望 注入前 status=packed，注入后 4xx ∧ shipments 仍 0 ∧ items 仍 0
             实测 注入后 status=shipped ∧ HTTP 422 ∧ shipments=0 ∧ items=0
```

**⑤ 加工单守卫的红证（注入：含加工项 + 无完成加工单）**

```
R5-1  期望 4xx ∧ shipments=0 ∧ items=0 —— 实测 HTTP 422 ∧ shipments=0 ∧ items=0
      （⚠️ 本条第一次尝试**夹具形状写错**（processing_info 写成裸数组而非
        {"processingItems":[…]}）导致"假绿证"：判据报红、看起来像守卫被绕过。
        按 extractProcessingItems 的真实入参形状修正夹具后为真红证 —— 见 §6 假绿自查第 7 条。）
```

**⑥ 正对照（两侧夹住）**

```
R1-POS-CTRL  期望 ①pass ∧ ②pass ∧ HTTP 2xx —— 实测 ①true(n=1) ②true HTTP 200
```

## 6. 假绿自查（逐条）

1. **期望有没有取自被测系统自身读面？—— 没有。**
   全部期望来自：① 夹具**我们给定的**数量/单位/payload（`S4-2` 明确标注 `NOT 系统读面`）；
   ② 直连 RDS 的**原始列**（`order_items.quantity`、`order_shipment_items.shipped_quantity`）做独立算式。
   系统读面（`GET /worker/shipment/orders/{id}`、`GET /admin/shipments`、`GET /admin/orders/{id}/shipments`）
   只在**两处**被引用，且都在判据里显式去掉期望来源：`S1-5`（标注「交叉核对，非期望来源」）、
   `R2-CROSSFACE`/`R3-LISTFACE`（标注「只证明注入落在被测真值上」）。
2. **判据会不会恒真？—— 不会。** 6 条关键判据各有注入式红证（§5 ②③④⑤），且**还原后回绿**（`R2-RESTORED`）。
3. **判据会不会恒红（假红）？—— 已修 4 处自己造出来的假红**（全部是**判据实现窄于判据声明**）：
   ① `qtyEq(10.000, 10n)` 因把 milli 表示二次换算成 `null` ⇒ 恒 false（`S1-5`）；
   ② 排序后 `codes[0]/codes[1]` 的极性写反（`S2-2`）；
   ③ `toISOString()` 是 UTC 却按本地墙钟再叠加偏移（`S1-6` 显示 −8h）；
   ④ `M7` 期望误按"原文"而非"列精度 `numeric(10,2)`"。
   —— **四条都是判据侧缺陷，不是产品缺陷**，已逐一改正并复跑（改正前后读数都在 `out/run.log`）。
4. **有没有空断言（静默跳过 / 声明了不存在的东西）？—— 抓到 1 处并已加固**：
   `T2/T3/T5` 原本用**非十六进制** id 打 `PUT /api/admin/orders/{id}/status`，
   而路由带 `@PutMapping("/{id:[0-9a-fA-F-]+}/status")` ⇒ 在**路由层**就 404，
   **根本进不到状态机** —— 三条"非法流转被拒"实际测的是路由匹配器。
   修法：探针 id 全部改成十六进制（前缀 `fa`/`fb`/`fc`），并新增判别性前置判据 **`T2-ROUTE`**
   （要求 `code=VALIDATION_ERROR` 而非 `NOT_FOUND`）。修正后三条均为 **422 + 状态机文案**，判据才真正成立。
5. **"绿"是不是空跑？—— 核过三条**：
   ① 步骤级：无 `skipped` 静默（4 条 skip 都是**显式登记"面不存在/未覆盖"**，不是抑制）；
   ② 产物级：每次运行落 `out/p*-records.json` + `out/summary.json`，逐条可读；
   ③ 新鲜度：构建点 `1233b8a42`，测量窗口内进程未重启（§1）。
6. **基线是否取晚？—— 已按纪律处理。** 所有"前后 diff / 连读两次一致"的判据基线都在**触发动作之前**取
   （`tableSnap` 在 `wship` 之前；`P1-1` 的两读之间无写动作）；补打类判据另用 `print_count 0→1→2` 证明面无空跑。
7. **红证本身有没有骗人？—— 抓到 1 处"假绿证"并改正（值得单列）**：
   `R5` 首次尝试时我把 `processing_info` 注入成**裸数组** `[{…}]`，
   而 `OrderShipGuard.extractProcessingItems` 的真实入参形状是
   `{"processingItems": [{id,name,quantity}]}`（`if (!(raw instanceof List)) return emptyList()`）。
   ⇒ 注入"生效了"（列里确实有值）但**守卫读不懂** ⇒ 判据报红，看起来像"守卫被绕过"。
   这是一个典型的**假绿/假红同源形态**：**注入自证只证明了"字节写进去了"，没证明"被测代码会读它"**。
   修法：夹具按真实入参形状重写（并保留两条读数），改正后 `R5-1` 为 **422 + 零写**（真红证）。
8. **并发测试是不是真并发？—— 是。** `Promise.all` 同刻发出，两路都在**无前置 4xx**的情况下到达服务端
   （`S2-DISC` 记录 `HTTP=[422,200]` 与墙钟 299ms；失败那一路的文案是
   「订单状态已并发变更，请刷新后重试」= **状态机在写后**发现冲突，即两路确实都进入了写路径）。
9. **探针是否可能改到别人的行？—— 代码层禁止 + 实测自证。** `assertProbe`（须含 `发货验收`）+
   `guardedWrite`（SQL 须含 `-- probe-ok`）+ 全部 WHERE 走探针 id 前缀；
   `NR-2` 实测跑完后租户 20 非探针订单 359 行仍在。
10. **时间口径**：全部时间戳在报告内以 **+08** 表达；RDS/psql 原文即带 `+08:00` 偏移（未再换算），
    API JSON 若为 `Z` 则标注换算（`lib.mjs` 的 `tsBoth` 对两者分别处理 —— 第一版在这里犯过 −8h 的错，已修）。

## 7. 未覆盖面 / 存疑（不写成通过）

| 项 | 说明 |
|---|---|
| **UI 面（admin-web `:3001`）** | 本包只核到**补打数据源**（`GET /orders/{id}` + 发货单读面两次一致，`P1-1`）。**没有**驱动真实浏览器做「登录 → 发货单列表 → 点补打 → 打印预览」的页面级验收（`ShipmentDoc` 的 `@media print` / portal 隔离 / 同页多单据约束）。⇒ 页面级结论**未覆盖**。 |
| **`O1` 纸面口径差异（观察项）** | `ShipmentDoc` 文件头第 5 条明写「数据全部取自订单本身（明细不可变）」⇒ 补打纸面**不含 `order_shipment_items` 的实发明细**。与 F1/F6 叠加时，"少发/错发可核"在**纸面**这一环拿不到实发数字。**未做 UI 截图取证**，故只登记为观察项（判据：纸面 `<ShipmentDoc>` 的 props 来源 = `order` + `logistics`，不读 `/orders/{id}/shipments` 的 `items`）。 |
| **入库半边（仓储）** | `WorkerInboundLabelController` / 入库单 / 库存台账的**入库**写面属「仓储」的另一半，本包未覆盖（`K4-INBOUND` 显式登记）。 |
| **发货出库扣减库存 / 退回回补** | 两面经枚举与实测确认**不存在**（`K1-2`/`K2-RESTOCK`），已如实登记（**不是**"通过"）。 |
| **发货单导出** | **不存在**（`P2-EXPORT`；三条候选路径 404）。 |
| **并发同幂等键在飞窗口** | 复现为**间歇性**（两轮分别观测到回放 / 422 两种结局）⇒ 语义强弱结论**证据强度只到"存在性级"**（§4 P3-F7）。要进一步定论需在服务端加人工延迟或提高并发轮次。 |
| **识别面（`/worker/shipment/recognize`）** | 未测（需真实图片 + vision 链路；且按纪律**不派发真实 LLM 评测**）。⇒ `recognize` 的「不确定 ⇒ 不预填」判据本包**未覆盖**。 |
| **`main` 健康度** | 本报告只对部署点 `1233b8a42` 有效（工作树 HEAD 当日已被 `main` 推进到 `d2965ea35`）⇒ **不得**用本报告推断 `main` 的健康。 |

## 8. 下一步建议（按性价比排序，不含修复实现）

1. **F1/F2 合并成一个类级修法**：把「累计已发 ≤ 订单量」做成**唯一实现点**
   （服务层一条判据 + DB 侧 `CHECK`/唯一语义兜底），并同时覆盖"同一 `order_item` 多行"的**合计**语义 ——
   只修行级校验会被 F2 的形态绕过。
2. **F3 接幂等键**：把 `ProductionController.ship` 接到既有的 `ClientRequestIdService.claim`（worker 侧已有现成用法）。
3. **F4 决策先行**：商家发货路要么落 `order_shipments`（真值单点），要么在发货单列表里显式标注"无实发明细的单"；
   在决策前，`#5939` 列表页对商家发货订单**永远漏单**是确定性的。
4. **F5 用类级判据钉住**：MyBatis-Plus 的 null 跳过是**全仓**风险 ⇒ 建议加"实体明确置 null 的字段必须落 NULL"的元判据
   （否则每修一处都会漏下 N 处）。
5. **F6/F7**：F6 建议在服务端按列精度对 `shipped_quantity` 归一化/校验；F7 建议把「同键在飞」统一到回放语义。
6. **复现成本**：本包工装可直接复用 ——
   `node acceptance/2026-10-03/shipments-sweep/harness/run-all.mjs`（40s，79 条判据，自建自清）；
   单场景调试用 `p0-enumerate.mjs`（枚举）/ `p6-redproof.mjs`（红证）。

---

### 附：产物清单

| 文件 | 说明 |
|---|---|
| `harness/lib.mjs` | 共享库（HTTP / psql / decimal 千分语义 / 字段级 diff / 探针建清 / 时间口径 / 构建点自证） |
| `harness/p0-enumerate.mjs` → `out/surface.json` | 链路枚举（25 端点 / 11 表列 / 唯一约束 / 状态机 / 前端文件） |
| `harness/p1-ship-protection.mjs` | 双发防护（串行 / 并发 / 同幂等键）+ 独立算式 |
| `harness/p2-state-machine.mjs` | 状态机（合法/非法跳转、回退留痕、非法零写 + 路由判别性前置） |
| `harness/p3-independent-math.mjs` | 独立算式（超发 / 边界 / decimal / 并发超发） |
| `harness/p4-writeface-equivalence.mjs` | 写后字段级等价性 + 补打/导出/打印 |
| `harness/p5-stock-and-print.mjs` | 库存台账 / 回补面 / 商家发货路（含幂等） |
| `harness/p6-redproof.mjs` | 红证（注入式 + 正对照 + 判据非空自证） |
| `harness/p7-noresidue.mjs` | 零残留机器读数 |
| `harness/run-all.mjs` | 一键复跑（setup → p1..p7 → summary.json） |
| `out/p*-records.json`、`out/summary.json`、`out/run.log` | 逐条判据证据（HTTP 原文 + SQL 原文）与汇总读数 |
