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
├── graph/       # LangGraph StateGraph
│   └── skills/  # Skill节点 + references/(SKILL + EXAMPLES).md
├── tools/       # 23业务工具
├── router/      # 意图分类 (LLM + 规则)
├── rag/         # BM25 + DashVector + Reranker
├── llm/         # LLM工厂/模型路由/成本追踪
├── api/         # SSE流式聊天 + 内部API
├── cache/       # 语义缓存
├── memory/      # 会话记忆
└── middleware/  # 请求拦截/日志
```

## 意图路由流程

```
用户消息 → analyze_intent → dispatch_skill → execute_tools → generate_response
                ↑                    ↓
                └── 追问澄清 ←────────┘
```

## 23 Tools

| 域 | Tools |
|----|-------|
| 商品 | product_search, product_detail, product_create, product_update, product_delete |
| 订单 | order_search, order_detail, order_create, order_update_status, order_ship |
| 售后 | aftersale_create, aftersale_search, aftersale_update |
| 知识 | knowledge_search, knowledge_upload, knowledge_delete |
| 客户 | customer_profile, customer_search, customer_tag_update |
| 系统 | dashboard_stats, system_config, human_handoff, image_analyze |

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
