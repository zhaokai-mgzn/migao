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
├── knowledge/   # 会话知识提炼（LLM WIKI，issue #3051）
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

### 已知窗口：L1 域逃逸的「伪域切换」（**有意不修**，2026-09-26 用户裁定 ②）

**这是什么**：`route_by_intent` 的「L1 高置信域切换」逃逸口——当 L1 **规则**（`source == "rule"`）
判到**别的域**时，它会清掉 `pending_interact_skill` 会话锁并改路由。若那句"别的域"其实只是
**顾客在回答本流程刚刚问的问题**，就发生**伪域切换**：会话被甩到一个**没有在办流程所需工具**的
skill，模型只能"实话实说"自己这条线做不了（能力误宣的原始形态）。

**可复现的最小形态**（OR-014 R3，零 LLM 复算）：

| 轮 | 输入 | L1 判定 | 路由结果 |
|---|---|---|---|
| R1 | 帮我下单，遮光窗帘 3 米，要打孔加工 | `order_create`(rule) | 订单流程（发规格卡） |
| R2 | （agent 问）还需要其他加工项吗 | — | 仍在订单流程 |
| R3 | **不需要其他加工项** | `product_inquiry`(rule)——命中商品域关键词「加工项」 | **逃逸清锁 → 商品 skill**（工具集里没有 `order_create`） |

**第二个入口**：`rule_matcher.py` 的商品创建规则过宽（商品名词组可选 + `.{0,10}` 允许零字符）
⇒ 裸「创建」也判 `product_inquiry(source=rule)` ⇒ 同样触发这条逃逸（**关联 #3731**，
不同的规则、同一个逃逸口）。

**为什么留着（不是"没发现"，是"裁定不做"）**：

1. **候选判据已被证伪**（#3784 正文的反例表）：曾提出的「在办流程是写流程且 pending 的目标动作
   是写 ⇒ 不允许 L1 规则逃逸到服务不了该写的域」会把**合法换域**（「改一下遮光窗帘的价格」
   「查一下库存」）一并拦住——两组输入在**注册表事实 + 会话状态**下**完全同形**
   （pending=订单、L1=商品、目标域工具集缺写工具），实现出来会让
   `TestLegitimateDomainSwitchStillWorks::test_explicit_product_action_still_switches_domain` 变红。
2. **真正的区分只需要一个缺失的状态事实**：「**本 skill 在纯文本轮里问过问题**」。
   现有豁免链（#3677 confirm 卡 / #3718 choice·form 卡）只认**卡**（`last_confirm_*` / `last_card*`
   仅在 `interact` 发卡时落库），而 OR-014 R2 的提问是**纯文本** ⇒ 任何基于"卡"的豁免天然看不见 R3。
3. **该状态事实被用户裁定不做**（2026-09-26，选项 ②「只做缓解 + 登记口径」）：naive 版
   （"上一轮问过问题 ⇒ 紧接的一句就是回答"）会**误吞**合法换域——「改一下遮光窗帘的价格」
   最常见的出现时机恰恰就是紧随一句提问之后；要做对需要"提问的语义槽位 vs 本轮回答是否落在该槽位"
   这类**新判据**，而它当前**没有可证伪的形态**（没有真跑校准就无法排除误吞）。

**当前缓解（已落地，不改变本窗口）**：下游熔断 + 回锁（#3782，已合并）——即使被甩到错误
skill，能力误宣会被纠正并把会话回锁到在办流程的归属 skill（`app/graph/skills/base_skill.py` 的
`_flow_owner_skill` 按**工具注册表声明**取归属，非 skill 名白名单）。

**本窗口的可执行证据**（不靠读代码，靠跑）：
`backend/ai-agent-service/tests/test_or014_pseudo_domain_switch_window.py`
——用真实 `RuleMatcher` + `route_by_intent` + 工具注册表**逐条复算**上表，并**钉住**「逃逸后落到
的 skill 的工具集里没有在办流程所需的写工具」这一事实；同时保留合法换域的绿证
（`test_or014_flow_owner_guard.py::TestLegitimateDomainSwitchStillWorks`）。
窗口若被关闭（无论是引入状态事实还是别的机制），该文件会变红 ⇒ 必须**显式**改口径，
不允许静默漂移。

**重开条件（可证伪）**：出现一条判据，能在**同一份事实集合**下把「R3 式回答」与
「同轮次的换域诉求」分开，并给出 ① 逐条真实文本样本的判定 ② 合法换域红证保持绿
③ 纯文本提问后的**非回答**（换域诉求）不被误吞的反例用例（即 #3784 的验收判据 1~4）。

## 30+ Tools

| 域 | Tools |
|----|-------|
| 商品 | product_search, product_detail, product_manage, category_manage |
| 订单 | order_search, order_detail, order_create, order_manage, logistics_track, customer_order_query, customer_address_query |
| 售后 | aftersale_create, aftersale_query, after_sales_manage |
| 加工 | processing_item_query, processing_item_manage, processing_items |
| 库存 | inventory_manage |
| 客户 | customer_manage |
| 知识 | knowledge_search, knowledge_upload, knowledge_delete |
| 数据 | dashboard_stats |
| 会话 | session_manage |
| 通知 | notification_manage |
| 人工 | human_handoff |
| 交互 | interact (confirm卡片/form/choice) |
| 员工 | employee_manage |
| 角色 | role_manage |
| 设置 | settings_manage |
| 校验 | validate_input |

## Skill 规范

每个 Skill 必须含：
- `{name}_skill.py` — 节点定义 + System Prompt
- `references/prompts/{name}.md` — 域提示词（base_skill.py 组装进 system prompt；无对应文件时读空）
- `references/EXAMPLES-{name}.md` — Few-shot(正确流程 + 反例)

Tool 铁律：写前校验 → 失败给 suggestion → 写前弹 confirm → 反幻觉规则

## 知识检索链路（LLM WIKI，issue #3051）

> 旧 RAG Pipeline（BM25 + DashVector + Reranker）已下线（决策 D1）并随 issue #3051 完全移除。当前知识问答两级策略：
> 1. **知识卡片优先**：`knowledge_search` 工具调 admin-api `GET /api/admin/knowledge/cards/search` 检索本店已发布知识卡片（结构化过滤 + 关键词，无向量库），命中基于卡片回答并注明「📖 来自本店知识库」；
> 2. **通用兜底**：未命中用 LLM 行业通用知识谨慎回答 + 通用建议免责。
> 知识卡片来源：行业模板一键套用 / 商品配置派生 / 会话·文档 AI 提炼（待确认队列，商家采纳后生效）。

（历史实现）文档上传 → Chunker分块 → 向量嵌入 → DashVector（已随 RAG 移除，仅存历史参考）
> `knowledge_search`/`knowledge_manage` 工具已删除（提交 `3215c322`），客服知识问答改用
> LLM 内置知识（见 `customer_knowledge_skill.py`）。B 端知识管理模块（`KnowledgeController` +
> `KnowledgeDocument` 表）**预留未启用**；恢复仅需按 `knowledge_skill.py` 头注 uncomment 注册。

```
（历史实现）文档上传 → Chunker分块 → 向量嵌入 → DashVector（已随 RAG 移除，仅存历史参考）
用户查询 → BM25关键词 + 向量语义 → Reranker重排 → Top-K
```

## 模型路由

| 场景 | 模型 | 原因 |
|------|------|------|
| 意图分类 | deepseek-flash | 低延迟 |
| 对话生成 | deepseek-flash | 高质量 |
| 图片识别 | deepseek-flash | 多模态（V4.1-Flash 原生） |
| 工具调用 | deepseek-flash | 复杂推理 |
