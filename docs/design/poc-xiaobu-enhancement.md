# POC 前小布 Agent 增强实施蓝图

> 版本 v1.0 ｜ 目标：POC 演示前补齐小布「AI 客服接单闭环」+ 小程序 C 端界面现代化
> 现状基于代码逐文件核实，非文档宣称。

## 一、现状盘点（已核实）

### 后端 AI 服务（ai-agent-service）
- 小布 Agent 框架完整：LangGraph 图 + SSE 流式 + 多模态消息 + 跨轮记忆（pending_skill/plan 恢复）
- 4 个业务 Skill + 1 兜底：customer_order（查询）/ customer_product（查询）/ customer_aftersales（创建工单）/ customer_knowledge（LLM 内置知识）/ customer_general
- `order_create` 工具已存在且安全设计完整（SMS 验证码 + 手机号格式校验 + 透传字段），`allowed_roles` 含 `customer`，但**小布 skill 未接入**
- `interact` 工具已完整支持 choice / confirm / form 三种组件
- SSE 服务端已支持 `suggestions` 和 `interactive` 事件（sse.py）
- chat.py 在 interact 工具成功时下发 `interactive` 事件

### 前端小程序（mini-app）
- 基础组件齐全：MessageBubble（气泡/打字机/图片/卡片）、MessageInput（文本/图片上传/停止）、MessageList（滚动/TypingIndicator）、QuickActions（2×2 网格）
- 已支持卡片类型：product_list / product_recommend / product_detail / logistics / knowledge
- **断层**：sse.ts 无 `onInteractive` / `onSuggestions` 回调 → interact 卡片、追问建议无法渲染
- 缺卡片：报价单（quotation）、下单确认（confirm）、订单成功（order_created）、SMS 验证码输入

## 二、差距清单（按模块）

### 后端 AI 服务
| # | 项 | 说明 |
|---|---|---|
| B1 | 算料工具（新） | 纯计算工具：窗宽高 + 褶皱倍数 + 门幅 → 面料米数 + 加工费 + 辅料 + 总价 |
| B2 | 算料报价 Skill（新） | 注册 skill + 路由 + 意图，小布对话内算料报价 |
| B3 | 小布接 order_create | customer_order_skill 加 tool_names + prompt，形成报价→下单闭环 |

### SSE 通道
| # | 项 | 说明 |
|---|---|---|
| S1 | 小程序端消费 interactive 事件 | sse.ts + chatStore 加 onInteractive |
| S2 | 小程序端消费 suggestions 事件 | sse.ts + chatStore + MessageList 加 onSuggestions |

### 前端小程序（UI 重设计）
| # | 项 | 说明 |
|---|---|---|
| F1 | 报价单卡片 | 多行明细 + 合计 + 确认下单按钮 |
| F2 | 下单确认卡片（confirm） | 渲染 interact confirm 组件 |
| F3 | SMS 验证码输入交互 | 对话流内验证码输入 + 倒计时 |
| F4 | 建议追问 chips | suggestions 渲染，横向滚动，点击即发送 |
| F5 | 欢迎区品牌化 | 对齐 ui-design-spec 3.2（渐变背景 + 品牌头像 + 快捷入口） |
| F6 | 图片/语音入口优化 | 加号展开菜单 + 语音按钮预留 |

## 三、实施顺序（依赖关系）

```
第一梯队（P0 核心闭环）：
  B1 算料工具 → B2 算料 skill → B3 小布接 order_create
  （并行）S1+S2 SSE 事件消费 → F1 报价单卡片 → F2 确认卡片 → F3 验证码
  → 形成「咨询→算料报价→SMS验证→下单→后台可见」闭环

第二梯队（P1 增强）：
  F4 追问 chips → F5 欢迎区 → F6 语音/图片
  图片识别闭环 skill（拍窗帘/布料→识别→荐款）
  微信渠道接入（企业微信/公众号）

第三梯队（演示准备）：
  真实感演示数据 + 全链路联调 + 30 分钟脚本彩排
```

## 四、关键设计决策

1. **算料真值来源**：现有 `knowledge_base/size_guide/measurement_guide.md` 第 149-182 行已含褶皱倍数表 + 算料公式 + 17.7 米完整算例。工具化时以行业调研规则为准，补充门幅/对花对格损耗/计价参数。
2. **算料工具定位**：纯计算（不调 admin-api），输入窗宽高/褶皱倍数/门幅/加工项，输出结构化报价单。参数默认值进 Skill Prompt（领域知识），公式进工具代码（确定性）。
3. **confirm 卡片复用**：下单确认用现有 `interact` 工具的 confirm 组件，前端补 interactive 事件消费 + confirm 卡片渲染，不改后端 interact 工具。
4. **SMS 验证**：复用 `order_create` 现有 SMS 机制（Redis OTP），前端补验证码输入卡片。
5. **UI 重设计**：以 ui-design-spec.md（v8.0 已有完整设计规范）为基础，参考主流 AI 助手产品补齐交互组件，不推翻现有设计语言。

## 五、验收标准

- 算料工具：褶皱倍数 1.5/2.0/2.5、门幅 1.4/2.8m、对开/单开均算对，与行业公式一致（单测覆盖）
- 闭环：小布对话内「3米窗 2倍褶皱 遮光布」→ 报价单卡片 → 确认 → SMS 验证 → 订单创建成功 → admin-web 订单列表可见
- UI：报价单/确认/验证码/追问 chips 均渲染，interact 卡片不出现"未知卡片占位"
- 三把工具全绿 + 测试带 case_ids

## 六、机器人设置集成（商家后台 → 小布行为）

> 原则：按合理性评估落地，不盲目照搬 TenantAiConfig 全部字段（评估见下）。

### 已集成（P0，端到端验证通过）

| 设置项 | 集成点 | 行为 |
|---|---|---|
| `autoHandoffKeywords` | intent_router_node | 用户消息命中商家关键词 → complaint 意图 → human_handoff（转人工） |
| `afterHoursMode/Message` | human_handoff 工具 | 非营业时间转人工降级为 afterHoursMessage（AI 照常服务，仅转人工降级） |
| `businessHours/timezone` | tenant_config.is_after_hours | 营业时间判断（`{"start":"09:00","end":"18:00"}`） |

### 架构

- `app/agents/tenant_config.py`：统一拉取 TenantAiConfig（60s 缓存），提供 is_auto_handoff_trigger / is_after_hours
- `human_handoff` 改调 Agent 版工单接口（转人工工单无关联订单）
- `customer_aftersales/general` 挂载 human_handoff 工具（此前 LLM 无法调用）
- admin-api `createTicket`：complaint 类型豁免订单校验（投诉可无订单）

### 合理性评估（不照搬项）

| 设置项 | 结论 | 理由 |
|---|---|---|
| `recommendStrategy/Count/Trigger` | ❌ 不做 | 过度设计：推荐应靠 AI 理解上下文自主判断，商家配参数反而僵化 |
| `emotionHandoff` | POC 后 | 与 autoHandoffKeywords 部分重叠 |
| `aiFallbackHandoff/Threshold` | POC 后 | 与现有 prompt"答不上来转人工"重复 |
| `quickReplies` | 待澄清 | 语义不清（C 端欢迎区 vs 客服工作台，后者已有 QuickReplyTemplate） |

## 七、人工客服工作台（转人工 → 人工客服对话）

> 打通「用户触发转人工 → 客服工作台接待 → 用户看到回复」的完整闭环。

### 链路

```
用户"我要找老板"
  → human_handoff：创建投诉工单 + 创建人工会话(agent_session, waiting)
  → 客服工作台（/agent-workspace/human-sessions）看到会话
  → 客服发消息（POST /{id}/messages）→ 会话 waiting→active
  → 用户查人工会话（GET /api/customer/agent-sessions/by-ai/{aiSessionId}）看到回复
```

### 后端

- `AgentSessionService`：createSessionForHandoff / sendMessage / getSessionByAiSessionId
- `AgentSessionController`：POST 创建会话 + POST /{id}/messages（客服，agent:session）
- `CustomerAgentSessionController`（/api/customer/agent-sessions，customer 可访问）：
  - GET by-ai/{aiSessionId}（用户查人工会话，归属校验）
  - POST /{id}/messages（用户发消息）
- `human_handoff`：工单创建成功后同步创建人工会话

### 前端（admin-web）

- 新建 `/agent-workspace/human-sessions`（人工客服工作台）：会话列表 + 对话区 + 发消息
- 轮询刷新（POC 简单版），WebSocket 实时推送后置

### 验证

- 单元：AgentSessionServiceTest 21 全绿
- 端到端：转人工→会话创建→客服工作台可见→客服回复→用户看到→会话 active
