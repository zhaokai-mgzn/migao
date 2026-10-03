# 线B 任务书 · 售后退款闭环 + 并发竞态 sweep（2026-10-03 第三轮）

> 本文件是**执行规格的承载体**（铁律 12(d)）。执行者 = 后台验收子代理（本包）。主会话只做集成与独立复核。

## 0. 为什么是这一块

① **售后退款闭环**：涉钱、不可逆、跨域最多（订单 × 售后 × 库存 × 财务），前两轮只碰到"建单/查询/工具存在"这一层，
**退款金额封顶、退货回补库存开关的两侧、状态机非法流转**都没验；
② **并发/竞态是全新的方法学维度**：至今全部测试都是**串行单用户**；并发只在跨租户串号上碰过边角。
本轮要把"并发判据怎么写才算数"落成**可复用范式**（含"注入放大使其必现"的红证写法）。

## 1. 被测对象与环境（**先钉事实**）

| 项 | 值 |
|---|---|
| 被测构建点 | `main-live` 工作树检出 **`43ca70322`**（= 准备时刻的 `origin/main`）；源码引用一律 `git -C /Users/guangzhen.zk/migao-wt/main-live show HEAD:<path>`，**禁读主检出工作树** |
| admin-api | `http://127.0.0.1:8080`（重启于 2026-10-03 16:15 +08，见 `acceptance/2026-10-03/env/env-round3.json`） |
| ai-agent-service | `http://127.0.0.1:8001`（内部工具入口 `/api/internal/tools/execute`，上轮线④ 用过） |
| DB | 云 dev RDS（参数从 `backend/admin-api/.env` 读，见共享 lib `psql()`） |
| 被测租户 | `tenant_id=20`；管理员手机 `13870217889`，短信万能码 `123456` |
| 探针命名域 | 名称前缀 **`线B验收`**；自建行 id 前缀 **`lb`** |

## 2. 射程

### B1 售后退款闭环（串行正确性）

端点（源码 = `backend/admin-api/src/main/java/com/migao/admin/controller/AfterSalesController.java` /
`OrderController.java` 的 `PUT /api/admin/orders/{id}/refund`）：
- `GET /api/admin/after-sales`、`GET /{id}`、`POST /api/admin/after-sales`、`PUT /{id}/status`
- `PUT /api/admin/orders/{id}/refund`（body: `refund_reason`、`refund_amount`）
- 退货回补库存的开关（`allow_return_restock` 语义，见用例 **AS-006**）

必测（每条 L1 + 红证）：
1. **建单**：`order_id` 跨域复用是否被校验（不存在的单 / 他人租户的单）；重复建单幂等（用例 **AS-010**：同会话同键 ⇒ `replayed=true` 且落库恰好一张）；
2. **状态机**：`pending/processing/resolved/rejected/closed` 的合法与**非法**流转（跳级、回退、终态再改）⇒ 各给期望，独立从 DB 验终态；
3. **退款金额**：全额 / 部分 / 超额（> 实收）/ 负数 / **重复退款**（累计封顶实收款）/ 不可退状态（`pending`、`cancelled` 等）；
4. **退货回补库存的开关两侧**：
   - 开：退货完结 ⇒ 库存**回补**（断言 `stock_ledger_entries` 新增行、`product_skus.stock` / 批次余量变化 = 独立算式结果）；
   - 关：⇒ 库存**零变化**（同一组快照前后对照）；
   - **两侧都要有**（只有一侧 = 未判定）；
5. **金额与流水的自洽**：`orders.refund_amount` 累计、`refund_at`、售后单 `refund_amount`/`refund_method` 三者一致；涉钱面**期望必须本包独立算出**。

### B2 并发 / 竞态（**本轮方法学重点**）

至少覆盖这四类（用户上一条明确点名的形态）：
1. **同一订单并发退款**（防双花）：N=4~8 并发 ⇒ 成功次数 × 金额 ≤ 实收；DB `refund_amount` 终值 ≤ 实收；
   ⚠️ 源码 `OrderService.refundOrder` 已用"原子条件更新（`COALESCE + WHERE 上限`）"防并发 ⇒ **必须验证这个守卫真的有效**，
   并用**注入式红证**证明判据有判别力（例：临时把条件更新换成无条件 `set`，**在副本/测试分支上**跑一次 ⇒ 必须红；不许改产品源码提交）；
2. **同一 SKU 并发扣减（超卖）**：并发下单 / 出库 N 次，库存不足时 ⇒ 成功数 == 库存允许数、`stock` 不得为负、台账与余量守恒；
3. **同一单据并发派工 / 并发改状态**：两个"调度员"同时分配同一工序 / 同一订单并发 `update_status` ⇒ 断言终态合法且只有一个赢家，或如实登记"最后一个写赢"（**先给期望再测**）；
4. **大批量读**：>1000 行的列表 / 看板在真实数据量下的表现（分页上限、总数与行数一致性、导出、响应时间的**机器读数**——记录读数即可，**不设主观阈值、不判性能缺陷**，但 5xx / 截断 / 总数与行数不符 = 真缺陷）。

**并发判据的写法要求（本轮的"方法学产出"）**：
- 每次并发必须记录：**并发度 N**、**逐请求结局（状态码 + 业务码）**、**DB 终态**、**独立算式的期望**；
- 每类至少**重复 3 轮**并给三轮读数（区分"偶尔假红"与"真泄漏"）；
- 判别力证明：给出**会红的注入**（把守卫摘掉 / 把上限改成常量 / 降低并发到串行）与其实跑读数；
- 结果里必须区分：`真缺陷` / `判据无判别力（并发未真正重叠）` / `假红`——**并发没真重叠时的"绿"不算通过**（要给出重叠证据，如服务端日志同秒或响应时间交叠）。

### B3 与线A 的分工（防抢写）
线A 已占：工人端 `/api/worker/**` 写面、bmini-app 的入库/派工/发货写面、`PUT /api/admin/after-sales/{id}/status` 的**输入校验与权限**小面。
⇒ 本线**不要**重复那两块；本线专注：**售后状态机语义与并发**、**退款金额闭环**、**库存回补开关**、**订单/SKU 并发**。

> ⛔ **明确不做**：真实 LLM 评测（#4262）；跑 `verify-all.sh gate/full`、`batch-gate`、全量 pytest（机器级重活锁，拿不到锁要出声拒绝）；改产品源码。

## 3. 纪律（违反任一条 = 本线读数不可引用）

1. **不自我验收**：只产读数 + 判定 + 证据，**不得**写"验收通过/交付完成"；
2. **可执行断言 + 红证**（并发类见 §2.B2 的加强要求）；
3. **判定必须引证据**：`R轮次 / 请求响应原文 / DB 读数 / 源码符号`（仓库相对全路径 + 符号名，**不写行号**）；
4. **四态分列**：`pass` / `fail(产品)` / `假红(判据缺陷)` / `skip(未覆盖 —— 永不记 pass)`；
5. **零残留**：探针对象用后自清，逐表计数 = 0（带注入→删除红证）；存量行零改动（sha256 前后对照）；
6. **跨包隔离**：与线A 同租户并发 ⇒ 探针对象自建、短写窗口逐条还原、**归因按行内容**（外来行 ⇒ 记 `skip` 并还原重跑）；
7. **时间口径**：一律 +08；复用共享 lib 的 `nowCST()`（**已修** Intl 版）；
8. **涉钱数据的处置**：仅用探针自建订单；**不得**对存量订单做退款/改状态；测试后必须还原（能还原的）；
9. **发现即登记**：真缺陷写清"逐字读数 + 可复制最小复现 + 会红的判据 + 边界"，供主会话开单派包（**不要自己开 issue / 不提 PR**）。

## 4. 工具与复用

- 共享库：`acceptance/2026-10-03/batch-writeface-sweep/harness/lib.mjs`（`api()` / `loginApi()` / `psql()` / `guardedWrite()` → 写 SQL 必带 `-- probe-ok` / `assertProbe()` / `sha256()` / `nowCST()` / `tableSnap()` / `qtyEq()`）。
  **复制一份到你自己的 `harness/lib.mjs` 再改**。
- 并发原语：Node 侧用 `Promise.all` + 同一起跑线（`Promise.all` 前先 `await` 一个共同 barrier）；必要时对每个请求单独 `fetch` 避免连接复用掩盖竞态。
- 参考上轮同类包：`acceptance/2026-10-03/batch-writeface-sweep/harness/run-all.mjs`（分组 → 判据 → 汇总 → `out/SUMMARY.json`）。

## 5. 交付物（缺一不算交付）

```
acceptance/2026-10-03/aftersales-concurrency-sweep/
├── REPORT.md          # 结论(不下"通过") / 四态读数汇总 / 逐条判据与证据 / 红证 / 零残留 / 未覆盖清单
├── harness/
│   ├── lib.mjs
│   ├── p0-env.mjs     # 构建点自证 + 时钟自检（对 SQL now() at time zone 'Asia/Shanghai'）
│   ├── p1..pN.mjs     # 分组判据（B1 串行闭环 / B2 并发族）
│   └── run-all.mjs    # 一键重跑
└── out/               # 逐条 JSON + SUMMARY.json + run.log
```

`out/SUMMARY.json` 必须含：`buildPoint`（sha + 采集时刻 + 取证方式）、`counts{pass,fail,skip,falseRed}`、
逐条 `{id, group, verdict, evidence, redProof}`、并发族额外含 `{N, rounds[3], overlapEvidence}`。
