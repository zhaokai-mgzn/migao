# 2026-10-17 全链路回归报告（云测试环境 · API 级）

> 生成时间：2026-10-18T07:10:19+08:00（补充场景更新：2026-10-18T07:45+08:00）　被测环境：`https://api.migaozn.com`　被测租户：**46**（`f-l9lu`）
> 口径：不做 UI 验收、不做 agent 评测、不跑真实 LLM；skip 永不折算成 pass。
> 被测 SHA：`fabcba31ea971803a0075b9f4252348f1563dc14`（`/api/version` 实读，与本地 HEAD 一致）

## 0. 结论（供验收）

- **核心回归：70/70 断言通过，0 fail / 0 skip，313 次真实 API 调用。**
- **补充场景：工人端「打包 → 撤销打包 → 再打包 → 发货 → 商家确认收货」7/7 通过**（覆盖主链路未触发的 `packed` 状态，见 §7）。
- **通知中心补测：7/7 通过**——配置「售后新工单」模板+规则，真实创建 2 张工单触发 `after_sales_created`，通知中心留下 **2 条真实站内信（1 未读 / 1 已读）**（见 §8）。
- **数据质量前置：6 商品 / 16 颜色 / 34 SKU（含门幅）/ 15 个启用加工项 / 7 个启用加工费组合 / 8 个已定价特殊选项**，全部经真实 API 建数，DB 独立复核。
- **7 张订单覆盖 `pending → confirmed → producing → packed → shipped → completed`、`cancelled`；** 加工单覆盖 `generated/issued/in_processing/completed/cancelled`；售后覆盖 `resolved/rejected/closed`。
- **本轮未发现可复现的产品缺陷**；未做 UI 验收、未做 agent 评测（按用户口径）。历史轮次出现的 1 次「确认支付后自动派单 fail-soft 未落单」未在最终轮复现，且有手动补单恢复路径，登记为观察项（不作为缺陷单）。

## 1. 总览

| 状态 | 条数 |
|---|---|
| ✅ pass | **70** |
| ❌ fail | **0** |
| ⏭️ skip | **0** |
| API 请求 | 313 |

### 分阶段

| 阶段 | pass | fail | skip |
|---|---|---|---|
| P0 | 4 | 0 | 0 |
| P1 | 8 | 0 | 0 |
| P10 | 4 | 0 | 0 |
| P11 | 3 | 0 | 0 |
| P2 | 8 | 0 | 0 |
| P3 | 9 | 0 | 0 |
| P4 | 5 | 0 | 0 |
| P5 | 3 | 0 | 0 |
| P6 | 11 | 0 | 0 |
| P7 | 10 | 0 | 0 |
| P8 | 3 | 0 | 0 |
| P9 | 2 | 0 | 0 |

## 2. 失败清单（逐条含证据）

（无）
## 3. 未覆盖（skip）清单

（无）

## 4. 数据面读数（DB 现取）

```json
{
  "products": 6,
  "product_colors": 16,
  "product_skus": 34,
  "processing_items": 16,
  "processing_fee_combinations": 8,
  "customers": 1,
  "orders": 7,
  "order_items": 9,
  "processing_orders": 4,
  "production_work_logs": 36,
  "quality_inspections": 3,
  "inbound_orders": 2,
  "stock_batches": 2,
  "stock_ledger_entries": 36,
  "order_shipments": 2,
  "after_sales_tickets": 5,
  "finance_transactions": 10,
  "piecework_settlements": 1,
  "notifications": 2,
  "knowledge_cards": 1,
  "tenant_param_audit": 13,
  "users": 11
}
```

> 注：`processing_items` 16 含 1 条本轮**创建后已软删**的测试项（active = 15）；`processing_fee_combinations` 8 含 1 条**已停用**的测试组合（active = 7）；`order_shipments` 已由 §7 补充场景增至 2（1 admin + 1 worker）；`after_sales_tickets` 已由 §8 补测增至 5；`notifications` 为 §8 保留的 2 条真实站内信。

## 5. 逐条结果

| ID | 阶段 | 状态 | 说明 |
|---|---|---|---|
| ENV-01 | P0 | ✅ |  |
| ENV-02 | P0 | ✅ |  |
| ENV-03 | P0 | ✅ |  |
| SET-01 | P1 | ✅ |  |
| SET-02 | P1 | ✅ |  |
| SET-03 | P1 | ✅ |  |
| SET-04 | P1 | ✅ |  |
| SET-05 | P1 | ✅ |  |
| SET-06 | P1 | ✅ |  |
| SET-07 | P1 | ✅ |  |
| SET-08 | P1 | ✅ |  |
| PRC-01 | P2 | ✅ |  |
| PRC-02 | P2 | ✅ |  |
| PRC-03 | P2 | ✅ |  |
| PRC-04 | P2 | ✅ |  |
| PRC-05 | P2 | ✅ |  |
| PRC-06 | P2 | ✅ |  |
| PRC-07 | P2 | ✅ |  |
| PRC-08 | P2 | ✅ |  |
| PRD-01 | P3 | ✅ |  |
| PRD-02-blackout | P3 | ✅ |  |
| PRD-02-sheer | P3 | ✅ |  |
| PRD-02-roller | P3 | ✅ |  |
| PRD-02-fabric | P3 | ✅ |  |
| PRD-02-rod | P3 | ✅ |  |
| PRD-02-valance | P3 | ✅ |  |
| PRD-03 | P3 | ✅ |  |
| PRD-04 | P3 | ✅ |  |
| ENV-04 | P0 | ✅ |  |
| ORG-01 | P4 | ✅ |  |
| ORG-02 | P4 | ✅ |  |
| ORG-03 | P4 | ✅ |  |
| ORG-04 | P4 | ✅ |  |
| ORG-05 | P4 | ✅ |  |
| STK-01 | P5 | ✅ |  |
| STK-02 | P5 | ✅ |  |
| STK-03 | P5 | ✅ |  |
| ORD-O1 | P6 | ✅ |  |
| ORD-O2 | P6 | ✅ |  |
| ORD-O3 | P6 | ✅ |  |
| ORD-O4 | P6 | ✅ |  |
| ORD-O5 | P6 | ✅ |  |
| ORD-O6 | P6 | ✅ |  |
| ORD-O7 | P6 | ✅ |  |
| ORD-S1 | P6 | ✅ |  |
| ORD-S2 | P6 | ✅ |  |
| ORD-S3 | P6 | ✅ |  |
| ORD-S4 | P6 | ✅ |  |
| PRD-10 | P7 | ✅ |  |
| PRD-11 | P7 | ✅ |  |
| PRD-12 | P7 | ✅ |  |
| PRD-13 | P7 | ✅ |  |
| PRD-14 | P7 | ✅ |  |
| PRD-15 | P7 | ✅ |  |
| PRD-16 | P7 | ✅ |  |
| PRD-17 | P7 | ✅ |  |
| PRD-18 | P7 | ✅ |  |
| PRD-19 | P7 | ✅ |  |
| AFS-01 | P8 | ✅ |  |
| AFS-02 | P8 | ✅ |  |
| AFS-03 | P8 | ✅ |  |
| FIN-01 | P9 | ✅ |  |
| FIN-02 | P9 | ✅ |  |
| DASH-01 | P10 | ✅ |  |
| NTF-01 | P10 | ✅ |  |
| KB-01 | P10 | ✅ |  |
| BRIEF-01 | P10 | ✅ |  |
| RBAC-01 | P11 | ✅ |  |
| RBAC-02 | P11 | ✅ |  |
| RBAC-03 | P11 | ✅ |  |

## 6. 产物

- `out/results.json`：逐条断言 + 证据
- `out/api_calls.jsonl`：每次 API 请求（方法/路径/状态/耗时）
- `evidence/register-response.json`：全新租户真实入驻回执
- `evidence/wipe-tenants.json`：旧租户清除读数

## 7. 补充场景：工人端打包 / 撤销打包 / 发货（7/7 通过）

> 主链路用商家侧发货覆盖 `shipped`；本节用工人端 `/api/worker/shipment/**` 补齐 `packed` 与 `unpack` 撤销路径。
> 证据：`out/worker-shipment-postcheck.json`

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| 1 | 订单由工人发货（`shipped`） | ✅ | `order.status=shipped` |
| 2 | 存在 `source=worker` 发货单 | ✅ | `SH202610180711166212` |
| 3 | 发货单含实发明细（6 米） | ✅ | `shipped_quantity=6.0, unit=米` |
| 4 | 打包留痕 | ✅ | `packed_at=2026-10-18T07:11:28.298162+08:00, packed_by=回归工人一` |
| 5 | 撤销打包留痕 | ✅ | `unpacked_at=2026-10-18T07:11:28.139951+08:00, unpack_reason=回归补充-打包规格复核` |
| 6 | 发货人身份 | ✅ | `shipped_by=回归工人一`（来自工人 session，不由 body 自称） |
| 7 | 商家确认收货 | ✅ | `status=completed, receivedAt=2026-10-18T07:11:54.38384+08:00` |

补充验证后最终状态：订单 7 张（2 completed / 1 cancelled / 4 confirmed）；发货单 2 张（1 admin + 1 worker）；打包/撤销打包/发货留痕均可读回。

## 8. 补充场景：通知中心事件驱动真实消息（7/7 通过）

> 背景：主回归 `NTF-01` 只验证了「手动创建 → 列表 → 未读 → 已读 → 删除」，
> 且最后把测试消息删除 ⇒ 通知中心空、也没有验证「业务事件 → 规则 → 模板 → 站内信」。
> 本节补的正是这条真实生成链路，并**保留**消息供验收查看。

配置：模板 `售后新工单待办（回归）`（`internal`，`{{ticketNo}}` / `{{ticketType}}`）
+ 规则 `eventType=after_sales_created`、`channels=internal`、`recipientType=employee`。
触发：真实创建 2 张售后工单（`repair` / `other`）⇒ `AfterSalesTicketService.notifyTicketCreated`
→ `NotificationService.triggerForTenantAdmins` → 模板变量替换 → 写 `notifications`。

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| 1 | 通知中心有 2 条事件生成的真实站内信 | ✅ | `total=2` |
| 2 | DB 同一规则生成 2 行 | ✅ | `notifications.rule_id` 一致 |
| 3 | 通知内容含工单号 `AS-20261018-0004` | ✅ | `新售后工单：AS-20261018-0004（维修）…` |
| 4 | 通知内容含工单号 `AS-20261018-0005` | ✅ | `新售后工单：AS-20261018-0005（其他）…` |
| 5 | 保留 1 条未读 | ✅ | `unread-count=1` |
| 6 | `sent` 筛选 = 1（未读） | ✅ | `status=sent total=1` |
| 7 | `read` 筛选 = 1（已读） | ✅ | `status=read total=1` |

证据：`out/notification-center-backfill.json`。补测后租户 46 的通知中心有 2 条真实消息：
1 条「维修」未读、1 条「其他」已读；模板/规则保留在租户配置中，可供后续事件继续触发。

