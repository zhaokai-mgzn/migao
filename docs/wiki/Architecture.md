# 系统架构

## 服务拓扑

```
小程序(SSE) + 管理后台(REST)
    → Admin API(:8080, Java)  ←→  AI Agent(:8000, Python/LangGraph)
    → PostgreSQL(39表,RLS) + Redis + DashVector + DeepSeek/MiniMax
```

## 多租户隔离 (5层)

1. JWT token 提取 tenant_id (不可伪造)
2. Spring Security RBAC 校验
3. MyBatis 拦截器自动注入 tenant_id
4. PostgreSQL RLS 行级安全
5. DashVector 分区键隔离
+ 字段脱敏 (日志/响应)

## 数据模型 (39表)

**业务**: tenants, users, roles, permissions, products, categories, processing_items, orders, order_items, after_sales

**对话**: customers, customer_tags, chat_sessions, chat_messages, human_agents

**知识**: knowledge_docs, knowledge_chunks, knowledge_vectors

**系统**: notifications, notification_templates, system_configs, login_logs, audit_logs

## AI 对话流 (LangGraph StateGraph)

```
消息 → 意图分类(L1关键词+L2 LLM) → Skill选择 → Plan(Tool列表) → Execute(调用) → Verify(检查)
→ 追问澄清? → 回到Execute : → Response(含confirm卡片/form)
→ SSE流式推送
```

## 前端路由 (admin-web)

| 路由 | 页面 |
|------|------|
| /admin/ | 数据看板 |
| /admin/products | 商品管理 (SKU矩阵) |
| /admin/categories | 分类管理 |
| /admin/processing | 加工项管理 |
| /admin/orders | 订单管理 (全生命周期) |
| /admin/after-sales | 售后工单 |
| /admin/customers | 客户CRM (RFM) |
| /admin/chat | 人工坐席 |
| /admin/knowledge | 知识库 |
| /admin/notifications | 通知中心 |
| /admin/settings | 系统设置 + 角色权限 |

## 认证

**小程序**: wx.login() → code → JWT(RS256)
**管理后台**: 用户名+密码 → JWT(RS256)
**服务间**: X-Service-Token 中间件
