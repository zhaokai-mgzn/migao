# 主会话独立复核：源码级假设清单（第三轮 · 线B 售后退款闭环 + 并发）

> **用途**：主会话在两条线在飞期间，**独立**读被测构建点（`main-live` = `43ca70322`）的钱路径源码，
> 形成"待验证假设"。**这些是假设、不是结论**；线B 回收后逐条对照（它发现/未发现/判据怎么写的）。
> 独立性的意义：若线B 的读数与本文冲突，冲突本身就是要复核的对象。
> 引用纪律：只写**仓库相对全路径 + 符号名**，不写行号。

## 假设 H1 · 售后工单状态更新的并发竞态（**最有价值**）

`backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::updateTicketStatus`
的写法是 **读-判-写**，全程无乐观锁 / 无 DB 层条件更新：

1. `afterSalesTicketMapper.selectById(id)` 读当前状态；
2. 应用层比对流转表（`pending→{processing,rejected,closed}` / `processing→{resolved,closed}`，终态不可再变）；
3. `afterSalesTicketMapper.updateById(ticket)` 无条件覆盖。

⇒ 两个并发 `PUT /api/admin/after-sales/{id}/status`（都读 `pending`）会**都通过校验**，两笔写都落库。
**可观察后果（取决于谁后写）**：
- `pending→resolved` 本应非法（`resolved` 不在 `pending` 的出边里）⇒ 若第一个请求把状态改成 `processing`、
  第二个基于旧读仍判 `pending→resolved` 合法 ⇒ **非法流转落地**；
- 更值钱的是它触发的两个副作用各跑一次：`linkRefundToOrderAndFinance`（累加订单退款 + 记资金流水）与
  `maybeRestockOnReturn`（**整单**恢复库存）—— **订单退款双记 / 库存双回补**。

**判据（会红的写法，供对照）**：N=4 并发对同一工单发 `pending→resolved` ⇒
① 工单终态必须是合法路径可达的状态；② `orders.refund_amount` 增量 == **独立算式**的单次金额（不是 N 倍）；
③ 库存变化 == 单次回补量；④ 资金流水 `refund` 条目数 == 1。
⚠️ 预期实现里**没有**这条守卫 ⇒ 若线B 实测"通过"，必须给出"并发确实重叠"的证据，否则记
`判据无判别力`（并发没真重叠时的绿不算通过）。

## 假设 H2 · 同一订单两张不同类工单 ⇒ 库存**双回补**

`maybeRestockOnReturn` 的粒度是**整单**（`orderService.restoreStockForReturn(orderId)`），
而创建工单时的防重复只拦"**同类型**活跃工单"（不同类型仅 `log.warn` 不阻止，见 `createTicket`）。
⇒ 建**一张 refund + 一张 return**（两次都成功），先后都流转到 `resolved`，且订单商品
`allow_return_restock=true` ⇒ **同一份订单库存被回补两次**。

**判据**：同一订单两张不同类工单都 resolved（商品开关=开）⇒ `product_skus.stock` 增量 == 单笔订单量
（独立算式），台账 `stock_ledger_entries` 回补行合计 == 单笔量；实得为 2 倍 ⇒ 真缺陷。

## 假设 H3 · 「回补开关」两态是否真能造出（前置可行性）

`maybeRestockOnReturn` 要求订单**全部**商品 `allow_return_restock = TRUE` 才回补（任一不允许 ⇒ 整单不回补）。
⇒ 线B 必须**自建**探针商品并把开关置 TRUE（否则只能测到"关"的一侧 ⇒ 该判据**未判定**，不得记 pass）。
`allowReturnRestock` 字段见 `backend/admin-api/src/main/java/com/migao/admin/entity/Product.java`。
📌 这一条是**前置条件检查**：若线B 报告"关"侧通过而没测"开"侧，按 §未覆盖登记，不得当闭环。

## 主会话已完成的独立复核（逐条 = 我自己跑/自己读，非转述）

| 时点（+08） | 被复核的包内读数 | 主会话动作（可复制） | 结论 |
|---|---|---|---|
| 16:25 | 线A `A10`「错误 PIN 与不存在工号 ⇒ 同一 401 同一文案」 | `POST /api/worker/login` 两次：`{workerNo:"LAB90104",pin:"9999",tenantId:20}` 与 `{workerNo:"NOPE00000",pin:"1234",tenantId:20}` | ✅ 一致：两跑均 `AUTH_FAILED | 工号或 PIN 不正确`（逐字相同 ⇒ 不泄露工号存在性） |
| 16:25 | 线A `A12`「登录未给租户 ⇒ 显式拒绝」 | `POST /api/worker/login` 不带 `tenantId`/头 | ✅ 一致：`422 VALIDATION_ERROR`「无法识别租户：请通过 <租户ID>.app.migaozn.com 域名访问或提供 tenantId」 |
| 16:25 | 线A `A11`「租户/身份不由请求头决定」 | 读源码 `backend/admin-api/src/main/java/com/migao/admin/worker/WorkerSessionService.java`（类 javadoc「身份只由服务端解…只认 `X-Worker-Session-Id`」+ `SESSION_HEADER` 常量） | ✅ 机制层一致（行为层读数待我另行复跑） |
| 16:25 | 线B `LB-AS-SM-01..07` 状态机族 | 对照源码流转表 `AfterSalesTicketService`（`pending→{processing,rejected,closed}` / `processing→{resolved,closed}` / 终态不可变；`closed`/`rejected` 记 `closed_at`） | ✅ 期望与实现自洽；`pending→closed` 有 #3541 的显式依据 |

## 主会话独立定位的产品发现（已开单）

| # | 发现 | 级别 | 承载体 | 证据 |
|---|---|---|---|---|
| **F1** | **一体机裁高读面 500**：订单明细 `product_id` 为空时，`WorkerCuttingHeightService::positionRow` 对 `brands(...)` 返回的**不可变空表** `Map.of()` 做 `get(null)` ⇒ NPE ⇒ `500 INTERNAL_ERROR`（设计意图相反：javadoc 逐字「缺 ⇒ `null`，**不猜**」） | **P2**（车间屏 500、无可用回执） | **issue #6219**（已开，修复包待派） | ① 线A 读数 `C23`（HTTP 500 + `INTERNAL_ERROR`）；② API 日志 16:26:24.407 逐字 `NullPointerException at WorkerCuttingHeightService.positionRow(:149) → read(:107) → WorkerProductionController.cuttingHeight(:198)`；③ 源码逐字 `brands()` 空 productIds ⇒ `Map.of()`；④ `javap -c` 行号表 `:149 → 偏移 152` = `aload_3(brands) → getProductId() → Map.get`；⑤ **JDK21 实跑**：`Map.of().get(null)` ⇒ NPE，`Map.of(k,v).get(null)` ⇒ NPE，`LinkedHashMap.get(null)` ⇒ `null` |

### F1 的判据形态教训（**假绿**，须回灌到验收口径）

线A 原 `C23` 判为 **pass**，其 `pass` 表达式第二分支是 `(ch.status >= 400 && …)` —— **`>= 400` 把 5xx 一起吞了**，
于是"服务器内部错误"被记成通过。⇒ 任何"4xx 可接受"的期望，**必须写成 `>=400 && <500`**，
且 **5xx 单列为 fail**；这条已发给线A 要求改判并补注入式判据。

## 主会话独立读数：并发派工的**兜底机制**（B2.5，只读查约束）

线B `LB-C5-DISPATCH-POOLED` 判 PASS（N=4×3 轮并发派工，成功数 `[4,4,4]` 但**活跃加工单恒 =1**）、并给了判别力红证
（摘掉唯一约束 ⇒ 4 行 / 加回 ⇒ 1 行）。主会话独立核到**兜底物本体**：

```
processing_orders :: uk_processing_orders_active :: CREATE UNIQUE INDEX ON public.processing_orders USING btree (order_id)
    WHERE ((deleted = 0) AND ((status)::text = ANY (ARRAY['generated','issued','in_processing','completed'])))
```

⇒ 「同一订单同时只能有一张活跃加工单」是**库级部分唯一索引**保证的（不是应用层判重），
这与 `#6220` 的对照组完全对称：**派工有库级谓词兜底 ⇒ 并发安全；售后状态流转没有任何谓词 ⇒ 副作用翻 4 倍**。
复读命令：`select tablename||' :: '||indexname||' :: '||indexdef from pg_indexes where schemaname='public' and tablename like '%processing%' and indexdef like '%UNIQUE%';`

## 主会话独立读数：大批量读（B2.4，只读实测 2026-10-03 16:32~16:33 +08，租户 20）

| 项 | 主会话读数 | 含义 |
|---|---|---|
| 列表响应路径 | `GET /api/admin/orders` ⇒ `data = {total, page, size, items}` | 线B `LB-C4` 的 `total=undefined rows=null` 是**取数路径错**（`records`），不是产品问题 |
| 租户 20 数据量 | `stock_ledger_entries 557+` / `orders 466` / `finance_transactions 499` / `order_items 484` / `after_sales_tickets 40` | **没有任何面 ≥1000 行** ⇒ 「>1000 行」这一档**造不出来**，应如实记 `skip` |
| 规模上限行为 | `GET /api/admin/stock-ledger?size=5000` ⇒ `200 / time≈0.11~0.29s / total=563~567 / 回显 size=500 / rows=500` | 全局 `maxLimit=500` 把 `size` 钳到 500，但 **`total` 诚实** |
| 分页可达性 | `page=1` 500 行 + `page=2` 67 行 = **567 = total** | **无静默丢行**（翻页可取全）⇒ 与上一轮「导出被截断」是两回事（导出**不能翻页**） |
| 数据漂移 | 同一分钟内 `total` 563 → 564 → 567 | 并发族的写造成 ⇒ 大批量读判据**不得硬编码总数** |

## 已读到的既有守卫（作为"期望"的基线，须独立复核）

| 位置（符号） | 守卫写法 | 判定 |
|---|---|---|
| `OrderService.refundOrder` | 可退状态白名单（`confirmed/producing/shipped/completed`）；负数拒；超实收拒；**DB 原子条件更新**：`setSql("refund_amount = COALESCE(refund_amount,0) + <applied>")` + `WHERE COALESCE(refund_amount,0) + <applied> <= <actual>`，`update==0` ⇒ 抛"已全额退款" | 代码级**看起来**能防双花；须实测 + 注入式红证 |
| `AfterSalesTicketService.linkRefundToOrderAndFinance` | 同上原子条件更新（`update==0` ⇒ log.warn 跳过，**不抛**） | 并发下"静默跳过"是可接受语义，但**必须验到** |
| `AfterSalesTicketService.maybeRestockOnReturn` | 整单回补；前置 = 订单全部商品开关 TRUE；回补后按"快照 vs 实际"落库存台账 | 粒度/重复问题见 H2 |
| `AfterSalesTicketService.createTicket` | 同类型活跃工单 ⇒ 拒；不同类型 ⇒ 仅 warn | 与 H2 相关 |
