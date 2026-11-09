# AI Agent 服务（元元 / 黄金策）

LangGraph 状态图驱动双 Agent：**Plan → Execute → Verify**。两位 persona 共用同一张图，
工具集由 persona 绑定的 Skill 决定；业务真值始终由 `admin-api` 裁决，AI 只经工具读写。

## 双 Agent

| Agent | 角色 | 服务对象 | 能力域 |
|-------|------|---------|--------|
| 元元 | C 端顾客服务 | 小程序用户 | 商品咨询 / 算料报价 / 下单 / 订单物流 / 售后 / 知识卡片 / 图片识别 |
| 黄金策 | B 端经营助手 | 商家管理员与员工 | 经营看板 / 商品与 SKU / 订单与加工单 / 库存 / 生产计件 / 财务客户 / 口径卡 |

能力边界与四端说明见 [Product](Product.md)。

## 代码结构

```
app/
├── agents/      # 双 Agent 定义 + System Prompt / persona
├── graph/       # LangGraph StateGraph (builder, nodes, state, plan_executor)
│   └── skills/  # Skill 节点 + references/(SKILL + EXAMPLES).md（数量现取）
├── tools/       # 业务工具（数量以 registry.py 注册表为单一源）
├── router/      # 意图分类 (L1 关键词 + L2 LLM)
├── knowledge/   # 会话知识提炼（LLM WIKI，issue #3051）
├── llm/         # LLM 工厂 / 模型路由 / 成本追踪
├── api/         # SSE 流式聊天 + 内部 API
├── cache/       # 语义缓存
├── memory/      # 会话记忆 (session + user)
├── core/        # 熔断器 + 降级策略
├── context/     # 请求上下文追踪
├── suggestions/ # 主动建议 (follow_up + preference_tracker)
└── middleware/  # 请求拦截 / 日志
```

**数量现取**（本页不写死）：

```bash
grep -cE '^[[:space:]]*registry\.register\(' backend/ai-agent-service/app/tools/registry.py  # 工具
ls backend/ai-agent-service/app/graph/skills/*_skill.py | wc -l                              # Skill
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

## 工具（数量现取）

注册表 = `backend/ai-agent-service/app/tools/registry.py`。**注册表只决定「工具存在」；
可达性由 persona 绑定的 Skill 工具集决定**。下表按域节选（完整清单以注册表为准）：

| 域 | 工具 |
|----|------|
| 商品 | `product_search` / `product_detail` / `product_manage` / `product_update` / `sku_update` / `product_batch_update` / `category_manage` / `marketing_poster` / `product_image_generate` |
| 订单 | `order_query` / `order_create` / `order_manage` / `customer_order_query` / `logistics_track` / `customer_logistics_track` / `payment_qrcode_query` |
| 售后 | `aftersale_create` / `aftersale_query` / `after_sales_manage` |
| 加工 / 生产 | `processing_item_query` / `processing_item_manage` / `processing_order_generate` / `processing_order_query` / `processing_order_update` / `processing_order_set_query` / `production_progress_query` / `production_worklog_query` / `piecework_query` / `operation_catalog_query` / `craft_config_query` / `craft_calc_config_query` / `craft_calc_config_update` |
| 库存 / 仓储 | `inventory_manage` / `batch_stock_query` / `stock_ledger_query` / `inbound_order_query` |
| 客户 | `customer_manage` / `employee_manage` / `role_manage` |
| 知识 | `knowledge_search`（只读；已发布知识卡片） |
| 经营 / 财务 | `dashboard_stats` / `sales_attribution` / `briefing_query` / `finance_api` |
| 会话 / 设置 | `session_manage` / `notification_manage` / `settings_manage` |
| 交互 / 输入 | `interact`（confirm / form / choice 卡）/ `validate_input` |
| 行业工具 | `curtain_calc`（算料报价）/ `image_recognize`（图片识别）/ `nav_guide` |
| 定时 | `scheduled_task_manage`（可逆写：提醒） |

> `human_handoff` 与 `knowledge_manage` **未注册**：前者按用户 2026-09-19 裁定下线
> （「以后全是 AI 来判断」），后者随 RAG 移除（issue #3051）。
> 能力边界与写操作清单见 [agent-write-boundary](agent-write-boundary.md)。

## Skill 规范

每个 Skill 必须含：
- `{name}_skill.py` — 节点定义 + System Prompt
- `references/prompts/{name}.md` — 域提示词（base_skill.py 组装进 system prompt；无对应文件时读空）
- `references/EXAMPLES-{name}.md` — Few-shot（正确流程 + 反例）

Tool 铁律：写前校验 → 失败给 suggestion → 写前弹 confirm → 反幻觉规则。

## 知识检索链路（LLM WIKI，issue #3051）

> 旧 RAG Pipeline（BM25 + DashVector + Reranker）已下线并随 issue #3051 完全移除。
> 当前知识问答是**两级策略**：

1. **知识卡片优先**：`knowledge_search` 调 admin-api `GET /api/admin/knowledge/cards/search`
   检索本店**已发布**知识卡片（结构化过滤 + 关键词，**无向量库**）；
   命中则基于卡片回答并注明「📖 来自本店知识库」。
2. **通用兜底**：未命中用 LLM 行业通用知识谨慎回答，并给出免责说明。

知识卡片来源：行业模板一键套用 / 商品配置派生 / 会话·文档 AI 提炼（进待确认队列，商家采纳后才生效）。
卡片四态：草稿 / 待审核 / 已发布 / 已归档 —— 只有**已发布**会进入检索面。

## 模型路由

模型名由环境变量配置（默认 `deepseek-flash`，原生多模态），本页不写死模型版本：

| 场景 | 配置项 | 说明 |
|------|--------|------|
| 意图分类 | `LLM_MODEL_FAST` | 低延迟 |
| 对话生成 | `LLM_MODEL_PRIMARY` | 默认主模型 |
| 图片识别 | `VISION_MODEL` | 视觉模型（`VISION_ENABLED` 控制开关） |
| 工具调用 | 主模型 | 复杂推理与多工具协同 |

> 成本口径与降级策略见 `backend/ai-agent-service/app/llm/cost_tracker.py` 与
> [Observability](Observability.md)。
