# 验证模板

模板文件位于 `templates/`（部署后位于 `/opt/ershen/templates/`）。

当前 16 个模板，覆盖 8 大业务域（对照 [业务真值设计链路](../../product/truth-design-pipeline.md)）：

| 域 | 模板 |
|------|------|
| 商品域 | product-sku-stock（SKU 库存/状态机）、processing-manage（加工项）、file-upload（文件上传） |
| 订单域 | order（6 状态机 + 库存/销量副作用 + 原子流转） |
| 售后域 | aftersales-flow（英文状态枚举 + 流转 + 工单号规则） |
| 客户域 | customer-list（搜索/筛选/详情 profile/标签 TODO） |
| 账户权限域 | auth-sms、registration-approval（企业入驻）、employee-role |
| 坐席通知域 | agent-notification（客服会话 + 快捷回复 + 通知，合并自 quick-reply/notification） |
| 知识库域 | knowledge-ai（MySQL LIKE 检索，RAG 未启用） |
| AI 对话域 | ai-chat（意图路由 + 工具分类 + confirm + suggestion） |
| 通用/看板 | dashboard-jump、settings-manage、frontend-fix、unknown |

> ⚠️ **真值准确性铁律**：模板真值必须与代码实际行为一致。
> 2026-08 全量校准（8 域对照代码）修正了大量过时/错误真值，关键案例：
> - 订单状态：旧「待付款/待发货…」→ 实际 `pending/confirmed/producing/shipped/completed/cancelled`
> - 售后状态：旧「待处理/已完成…」→ 实际 `pending/processing/resolved/rejected/closed`
> - 登录返回：旧 `data.token` → 实际 `data.accessToken`
> - 客户详情统计：旧 `data.orderCount` → 实际 `data.profile.totalOrders`
> - 知识库检索：旧「向量 RAG」→ 实际「MySQL LIKE + RAG 禁用」
> - 员工端点：旧 `/api/admin/employees` → 实际 `/api/admin/users`
>
> 每次代码演进后必须重新核对模板真值，否则 QA Growth Gate 引擎按错误真值验收会写出有漏洞的功能。

## 已否证真值：`retired_truths`（issue #4430）

真值条目被**后续 issue 否证**后（例：`[processing-manage.product-link] 加工项关联商品` ——
#4371 把「商品 ↔ 加工项」绑定彻底解耦、关联表已 DROP），**不能只是删掉**：删掉是静默的
（`truths.py check` 只校验引用完整性、不校验真值内容 ⇒ 过期真值永远不红）。
⇒ 在模板里显式登记否证依据：

```yaml
retired_truths:
  <模板名>.<短名>:
    retired_by: <否证它的 issue 号>
    reason: "<否证依据：什么已不成立（点名可核对的事实，如「关联表已 DROP」）>"
```

`truths.py check` 会因此判红（fail-closed，exit 1）的三种形态：

| 形态 | 含义 |
|---|---|
| `retired` | 用例的 `truths_ref` 仍引用**已否证**的真值 |
| `retired-live` | 同一 ID 既在 `business_truths`（活着）又在 `retired_truths`（否证）—— 自相矛盾 |
| `retired-meta` | 登记缺 `retired_by` 或 `reason`（没有依据的「否证」与随手删除不可区分） |

判定与红证：`tests/unit_ci_workflows/test_truth_retirement_guard.py`。
