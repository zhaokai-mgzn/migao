# AI Agent 服务

LangGraph 状态图驱动双 Agent：Plan → Execute → Verify。

## 双 Agent

| Agent | 角色 | 服务对象 | 能力域 |
|-------|------|---------|--------|
| 小布 | C端客服 | 小程序用户 | 咨询/订单/售后/知识问答/图片识别 |
| 米宝 | B端助手 | 管理后台商家 | 商品管理/订单操作/数据分析/系统配置 |

## 代码结构

```
app/
├── agents/      # 双Agent定义 + System Prompt
├── graph/       # LangGraph StateGraph (builder, nodes, state, plan_executor)
│   └── skills/  # 19 Skill节点 + references/(SKILL + EXAMPLES).md
├── tools/       # 30+ 业务工具
├── router/      # 意图分类 (L1关键词 + L2 LLM)
├── rag/         # BM25 + DashVector + Reranker
├── llm/         # LLM工厂/模型路由/成本追踪
├── api/         # SSE流式聊天 + 内部API
├── cache/       # 语义缓存
├── memory/      # 会话记忆 (session + user)
├── core/        # 熔断器 + 降级策略
├── context/     # 请求上下文追踪
├── suggestions/ # 主动建议 (follow_up + preference_tracker)
└── middleware/  # 请求拦截/日志
```

## 意图路由流程

```
用户消息 → L1关键词匹配 → L2 LLM分类 → dispatch_skill → execute_tools → generate_response
                ↑                    ↓
                └── 追问澄清 ←────────┘
```

## 30+ Tools

| 域 | Tools |
|----|-------|
| 商品 | product_search, product_detail, product_manage, category_manage |
| 订单 | order_search, order_detail, order_create, order_manage, logistics_track |
| 售后 | aftersale_create, aftersale_query, after_sales_manage |
| 加工 | processing_item_query, processing_item_manage, processing_items |
| 库存 | inventory_manage |
| 客户 | customer_manage |
| 知识 | knowledge_search, knowledge_upload, knowledge_delete |
| 数据 | dashboard_stats |
| 会话 | session_manage |
| 通知 | notification_manage |
| 人工 | human_handoff, quick_reply_manage |
| 交互 | interact (confirm卡片/form/choice) |
| 员工 | employee_manage |
| 角色 | role_manage |
| 设置 | settings_manage |
| 校验 | validate_input |

## Skill 规范

每个 Skill 必须含：
- `{name}_skill.py` — 节点定义 + System Prompt
- `references/SKILL-{name}.md` — 元数据(name, domain, tools, triggers, constraints)
- `references/EXAMPLES-{name}.md` — Few-shot(正确流程 + 反例)

Tool 铁律：写前校验 → 失败给 suggestion → 写前弹 confirm → 反幻觉规则

## RAG Pipeline

```
文档上传 → Chunker分块 → 向量嵌入 → DashVector
用户查询 → BM25关键词 + 向量语义 → Reranker重排 → Top-K
```

## 模型路由

| 场景 | 模型 | 原因 |
|------|------|------|
| 意图分类 | deepseek-v4-flash | 低延迟 |
| 对话生成 | deepseek-v4-pro | 高质量 |
| 图片识别 | MiniMax-M3 | 多模态 |
| 工具调用 | deepseek-v4-pro | 复杂推理 |
