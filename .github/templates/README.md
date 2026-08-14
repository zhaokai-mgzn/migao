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
> 每次代码演进后必须重新核对模板真值，否则二郎神按错误真值验收会写出有漏洞的功能。
