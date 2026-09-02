# 小布 AI 自动引导转人工（Guided Handoff）设计

> 状态：设计评审中 ｜ 范围：ai-agent-service 为主（admin-api/admin-web 零改动）｜ 目标版本：v1
> 关联：CH-008（转人工→人工会话闭环）、ST-008（关键词/非营业降级）、UI-010（快捷入口改版）、tdd-iron-law §3（写操作 confirm 守卫）

## 1. 背景与目标

### 1.1 问题

小布（C 端）「转人工」目前**只靠用户主动触发**，且触发即直接创建投诉工单 + 人工会话：

| 触发方式 | 现状 | 评价 |
|---|---|---|
| 用户输入"转人工/人工客服/我要投诉…" | LLM 调 `human_handoff` 直接执行 | 用户主动，OK |
| 商家配置 `autoHandoffKeywords`（找老板/我要投诉） | intent_router 命中 → complaint → human_handoff | 商家显式指令，OK |
| 用户不满/情绪激动/多次未解决/AI 能力外 | 仅 prompt 一句"转人工触发条件"，LLM 自觉 | **不可控、无信号、无评测** |

用户诉求：**把"引导转人工"自动化**——不是放固定按钮让用户点，而是让 AI 依据**结构化信号**判断"该建议转人工了"，先安抚+建议，**用户确认后才真正转**（该转才转，控制转人工率）。固定按钮早已移除（UI-010），"输入'转人工'仍可触发"的能力不得退化。

### 1.2 目标（v1）

1. 新增「AI 主动引导转人工」：检测到用户不满等信号时，AI 先表达理解并给出**确认式建议**（建议消息 + 确认卡片），用户点「转人工」后才走 human_handoff 闭环。
2. 判定基于**结构化、可单测**的信号（情绪/重复表达/能力外），非 LLM 玄学。
3. **不打断、不骚扰**：每会话建议有限次数；用户拒绝后本会话不再自动建议；用户可随时手动输入"转人工"（能力不退化）。
4. 用户**显式**要求转人工（说"转人工"等词）与商家关键词：**保持现状直接转**，不引入多余确认（不破坏 CH-008/ST-008 语义）。

### 1.3 非目标（v1 不做）

- ❌ 管理后台「转人工规则」配置页（情绪开关/阈值 UI）——admin-dashboard-design §4.2 的完整规则面板后续版本
- ❌ 情绪 LLM 识别模型（微调/情感分类模型）
- ❌ 转人工后坐席分配/排队优化（已在 agent-workspace-design 范畴，本次不动）
- ❌ C 端新 UI 组件——确认卡片复用现有 `interact`（ChoiceCard）机制，**前端零改动**

## 2. 现状链路（事实核查）

```
用户消息
 → intent_router_node（nodes.py）
     · 商家 autoHandoffKeywords 命中 → intent=complaint, source=tenant_auto_handoff
     · 否则 L1 规则/L2 分类 → (intent, action)
 → route_by_intent → skill 节点（xiaobu: customer_order/product/quote/aftersales/knowledge/general）
     · customer_general / customer_aftersales 挂载 human_handoff 工具
     · ReAct 循环中 LLM 可调 human_handoff
 → human_handoff.execute
     · 非营业时间 → afterHoursMessage 降级（不建工单）
     · 创建 complaint 售后工单 + 人工会话(agent_session, waiting) + 通知管理员
     · terminal=True → 前端 chatStore 检测 tool=human_handoff → handedOff 横幅 + 轮询人工会话
```

**关键缺口**：
- `human_handoff` 属性 `destructive=False, requires_confirmation=False` → **不经过 base_skill 的写操作 confirm 守卫**（`_requires_confirmation` 只拦 destructive / requires_confirmation）→ LLM 一旦决定转就直接执行。
- 情绪/能力外信号**没有任何结构化检测**，prompt 中的触发条件仅靠 LLM 自觉（customer_general L51-56 / customer_aftersales L21-24）。

## 3. 触发分类与判定策略

### 3.1 三类触发（新语义）

| 类型 | 判定 | 动作 |
|---|---|---|
| **D1 用户显式请求** | 用户消息命中转人工请求词（转人工/人工客服/找人工/找老板/找真人/我要投诉…） | **直接转**（现状不变：complaint → human_handoff） |
| **D2 商家关键词** | `autoHandoffKeywords` 命中 | **直接转**（现状不变） |
| **D3 AI 主动建议**（新增） | 结构化信号命中且非 D1/D2 | **先安抚+建议卡片 → 用户确认 → 转** |

> D1/D2 直转是产品共识：用户/商家已明确表达意图，再加确认是负体验且破坏既有用例（CH-008/ST-008 期望单轮触发成功）。

### 3.2 D3 结构化信号（v1，纯规则）

判定函数 `judge_handoff(...) -> HandoffJudgeResult`，输入为（用户消息文本、会话最近消息列表、租户配置）：

| 信号 | 规则 | 命中示例 |
|---|---|---|
| S1 不满/负面情绪表达 | 消息命中负面情绪词表（命中 **1 次**即触发） | "你们太坑了""气死我了""再也不买了""差评""垃圾""服务太差""投诉你们" |
| S2 负面情绪**重复**（防单次口误打扰） | 最近 3 条用户消息中 ≥2 条命中情绪词且含同一诉求主题 | 用户三轮说"质量问题没人管" |
| S3 能力外/超范围请求 | 消息命中能力外提示词（赔钱/赔偿/法律/起诉/315/消协/找领导） | "我要赔 5000""不走法律程序不行" |
| S4 显式请求（D1 用，不进建议） | 命中转人工请求词 | "转人工""找真人客服" |

**词表位置**：`app/graph/handoff_judge.py` 模块级常量（v1 硬编码默认词表，设计上预留租户配置挂载点，见 §7.4）。

**冷却规则（防骚扰，核心）**：
- 会话状态 `handoff`（存 `session_states.state` JSON，经 `SessionStateStore`）：
  - `offer_count`：累计建议次数；`>= 1` 后不再自动建议（D3 每会话至多 1 次自动建议）
  - `last_user_refused`：用户拒绝过 → 本会话永不再自动建议
- 建议被用户**确认/拒绝/忽略**后写入状态；建议卡片未回复不阻塞对话（用户可继续聊天，仅不再重复弹）。

### 3.3 意图过滤（防打断业务流，与实现精确对齐）

`judge_handoff` 内置**意图白名单** `_OFFER_ALLOWED_INTENTS = {"general", "after_sales"}`，
其余意图（下单/查单/报价/售后创建/知识问答/greeting 等明确业务流）**一律不 offer**，
防止弹卡打断正常业务推进。白名单内的分级语义：

| 意图 | S1 单轮负面 | S2 多轮未解决 | S3 能力外 |
|---|---|---|---|
| `general`（兜底/未知） | ✅ offer | ✅ offer | ✅ offer |
| `after_sales`（售后沟通） | ❌ 不 offer（该走 aftersale_create 售后流程） | ✅ offer（反复未解决） | ✅ offer |

> 反例（防误弹）：用户在售后流程中表达对商品不满（"质量太差我要退货"）→ 意图
> after_sales + 单轮 → 不弹转人工卡，继续售后创建流程；只有当用户多轮诉求未获解决
> 才建议转人工。

### 3.4 判定优先级

```
D2 autoHandoffKeywords 命中      → 直转（complaint）
D1 显式转人工请求词命中          → 直转（complaint）
D3 信号命中 & 冷却未过 & 未拒绝  → offer（建议卡片）
否则                              → 正常路由（现状）
```

## 4. 交互与时序（建议卡片复用 interact）

### 4.1 卡片形态

复用现有 `interact` 工具的 **choice** 组件（C 端 ChoiceCard 已渲染，点击即把 `value` 作为下一条用户消息发送）：

```json
{
  "component": "choice",
  "title": "这个问题比较特殊，需要为您转接人工客服吗？",
  "options": [
    {"label": "👩‍💼 转人工客服", "value": "转人工客服"},
    {"label": "继续咨询小布", "value": "继续咨询小布"}
  ]
}
```

### 4.2 闭环时序

```
用户："你们窗帘质量问题第三次了，没人处理"
  → intent_router_node：非 D1/D2 → judge 命中 S2 → route 到新节点 handoff_offer
  → handoff_offer 节点（确定性输出，不走 LLM）：
      final_answer = "非常抱歉让您反复遇到问题🙏 这个情况我可以帮您转人工客服专员处理，由专人跟进您的售后问题，您看需要吗？"
      messages 含 ToolMessage(name=interact, 上述 choice 卡片)   ← SSE 自动发 interactive 事件
  → 用户点「转人工客服」→ 发送文本"转人工客服"
  → intent_router_node：命中 D1（含"转人工"）→ complaint
  → customer_aftersales_skill → LLM 调 human_handoff（last_msg="转人工客服"，D1 场景直转）
  → 创建工单+人工会话 → 前端 handedOff 横幅（chatStore 现成逻辑，零改动）
  → 客服工作台接待（CH-008 既有闭环）
```

用户点「继续咨询小布」→ 消息"继续咨询小布"正常路由（general），会话状态记 `last_user_refused=true`，不再建议。

### 4.3 建议节点为何不调 LLM

- 确定性输出 → 完全可单测/评测，无 LLM 波动；
- 话术模板 + 卡片一次成型，时延低；
- 不消耗 token、不受模型质量影响。
（D3 建议本身不需要"聪明的措辞"，需要的是"对的时机"——时机由 §3.2 信号保证。）

## 5. 落点设计（文件级）

### ai-agent-service（唯一改动模块）

| 文件 | 改动 |
|---|---|
| `app/graph/handoff_judge.py`（新） | 判定纯函数 + 词表 + `HandoffJudgeResult`（纯逻辑，可单测） |
| `app/graph/handoff_offer.py`（新，可选并入 nodes.py） | handoff_offer 节点：生成安抚文案 + interact choice ToolMessage + 更新会话 handoff 状态 |
| `app/graph/nodes.py` | `intent_router_node` 尾部接入 judge：D3 命中 → state 标 `route_to_handoff_offer`；`route_by_intent` 返回 `"handoff_offer"` |
| `app/graph/builder.py` | 注册 `handoff_offer` 节点 + route_map 加入 `handoff_offer` → 节点；仅 xiaobu 图生效（conditional 边按 state 标记走） |
| `app/graph/skills/customer_general_skill.py` / `customer_aftersales_skill.py` | prompt 措辞强化（可选微调：把"转人工触发条件"改为指向自动引导 + 保留直转语义） |
| `app/memory/session_state_store.py` | 复用（无改动）——handoff 状态读写走既有 load/commit |

### 测试（AI-TDD）

| 文件 | 内容 | case_ids |
|---|---|---|
| `tests/test_handoff_judge.py`（新） | judge 纯函数：S1/S2/S3 命中、D1/D2 优先、词表边界、冷却输入 | 对应新增 case（见 §7） |
| `tests/test_xiaobu_handoff_offer.py`（新，mock LLM） | 情绪信号 → 建议节点产出（final_answer + interact 卡片）→ 点"转人工"→ human_handoff 调用 → 人工会话创建；拒绝 → 不再建议；显式请求直转不弹卡 | 同上 |
| `.github/cases/chat.yml` | 新增用例（chat 域，见 §7） | CH-xxx |
| `docs/testing/mibao-verification-cases.md` + `tests/agent_eval/eval_cases.py` | render_cases.py 重渲染提交 | — |

### 契约与前端

- **前端（mini-app）零改动**：ChoiceCard 已有；SSE `interactive` 事件链路现成（chat.py L600+）；handedOff 逻辑现成。
- admin-api 零改动。
- contract-check：仅 ai-agent 内部新增 state 标记 + 路由 key，不跨模块字段 → 不破坏契约（提交前仍跑一次确认）。

## 6. 会话状态模型

`session_states.state.handoff`：

```json
{
  "offer_count": 1,
  "last_offer_at": "2026-09-02T10:00:00Z",
  "last_user_refused": false,
  "refused_at": null
}
```

读写：`SessionStateStore.load/commit`（现有方法，PG `session_states`）。读失败/异常 → 按"无状态"降级（不弹卡），不影响主流程。写入 best-effort（失败仅记日志）。

## 7. 评测与门禁

### 7.1 新增行为用例（.github/cases/chat.yml，chat 域）

> 注：CH-009~CH-012 已被既有用例占用（interact form/后续场景），新用例从 **CH-013** 起编号。

| ID | 标题 | 关键断言 |
|---|---|---|
| CH-013 | AI 检测不满情绪 → 建议转人工卡片 → 用户确认后创建人工会话 | judge 命中 → 建议卡片出现（interact choice）；确认后 human_handoff；agent_session(waiting) |
| CH-014 | 用户拒绝建议 → 继续 AI 咨询且本会话不再自动建议 | 拒绝后消息正常路由；再次不满不弹卡 |
| CH-015 | 用户显式"转人工"不经建议卡片直接转（能力不退化） | 直转，无卡片 |
| CH-016 | 非营业时间建议场景仍走 afterHours 降级（若建议后确认） | 确认转人工但非营业 → afterHoursMessage，不建工单 |

> CH-013~CH-016 需在 registry.yml 或 chat.yml 登记并通过 render_cases 渲染。测试文件头声明 `# case_ids: CH-013, CH-014, ...`。

### 7.2 回归保障

- CH-008/ST-008/UI-010 既有用例**不得破坏**（D1/D2 直转语义不变）。
- `customer_general` 等 prompt 微调后跑 Agent Eval（smoke）确认无退化。

## 8. 实现顺序（AI-TDD）

1. **Red**：`test_handoff_judge.py`（纯函数判定的失败测试）
2. **Green**：`handoff_judge.py` 最小实现
3. **Red**：`test_xiaobu_handoff_offer.py`（多轮场景：建议→确认→直转闭环）
4. **Green**：`handoff_offer.py` + nodes.py/builder.py 接线
5. 评测用例：cases/chat.yml + render_cases 重渲染
6. 验证：`./verify-all.sh gate` + `./check-ui-regression.sh`（跨模块无 → contract-check 仅确认）
7. 提交（禁 add -A，逐个确认）→ PR 关联 Issue

## 9. 风险与边界

| 风险 | 缓解 |
|---|---|
| 建议卡片打扰正常对话 | 每会话 ≤1 次自动建议 + 拒绝后不再建议 + 仅 S1/S2/S3 命中才弹 |
| 词表误判（"你们窗帘质量真好"含"好"类词） | 词表只收**负面强表达**，不收录中性词；S1 需整句命中词表条目（子串）；评测覆盖反向样例（不触发） |
| 与 autoHandoffKeywords 语义重叠 | D2 优先级最高先判；商家关键词走直转（商家已明确） |
| human_handoff 无确认守卫（现状） | 本次 D3 走「卡片确认后才触发」，D1/D2 维持（用户已确认）。如需全局守卫可后续评估 `requires_confirmation=True`（会改变 CH-008 语义，须单独评审） |
| 非营业时间 | human_handoff 内部降级逻辑已存在，建议卡片仍可弹（AI 照常服务，确认后走降级文案，不建工单） |
| route_by_intent 的 pending_interact_skill 干扰 | handoff_offer 路由在 pending_skill 处理之前判定；建议卡片 value（"转人工客服"/"继续咨询小布"）设计为可被领域词识别，不依赖 pending 逃逸 |

## 10. 验收标准（Done 定义）

1. `test_handoff_judge.py` / `test_xiaobu_handoff_offer.py` 全绿，头部含 case_ids；
2. cases 渲染生成物同步提交（eval_cases.py + mibao-verification-cases.md）；
3. `./verify-all.sh gate` 通过、`./check-ui-regression.sh` 通过；
4. Agent Eval smoke：CH-008/ST-008 不退化 + 新 CH-013~016 通过（或列为 manual）；
5. 提交小步、走 PR 关联 Issue（禁直推 main / 禁 add -A）。

---

### 附录：与既有文档的关系

- `poc-xiaobu-enhancement.md` §"emotionHandoff / aiFallbackHandoff → POC 后" → 本次 v1 落地为 D3 结构化信号（词表版，未做管理后台配置）。
- `admin-dashboard-design.md` §4.2 转人工规则（情绪触发/AI 无法解决触发）→ 完整配置面板留待 v2（judge 词表/阈值参数化 + 管理后台 UI）。
