# GB/T 47746-2026 合规差距与落地（AI 客服新国标）

> 状态：⏳ 差距审计进行中 · 追踪 Issue：[#2775](https://github.com/zhaokai-mgzn/migao/issues/2775)
> 本文档 = 官网「符合国标」宣称的**证据底稿**。宣称上线前，本文档每项「缺口」必须闭合或明确豁免理由。

## 1. 标准事实卡

| 项 | 内容 |
|---|---|
| 标准号 | **GB/T 47746-2026《顾客联络服务 人工与智能客户服务协同要求》** |
| 性质 | 推荐性国家标准；我国首个聚焦「人工客服+智能客服协同机制」的国标 |
| 发布 / 实施 | 2026-05-25 发布，**2026-09-01 实施**（计划号 20242868-T-469） |
| 归口 | 全国服务标准化技术委员会 |
| 效力 | 推荐性，无直接强制力；可作监管检查、服务质量评估、纠纷裁决参考 |

相关标准：GB/T 36464.3-2026《信息技术 智能语音交互系统 第3部分：智能客服》（修订 2018 版，语音域，2026-12-01 实施）——与本产品（文本客服为主）关联弱，不纳入宣称范围。

## 2. MIGAO 范围界定与宣称口径（广告红线）

- 产品形态：多租户 SaaS。**小布（C 端顾客 AI 客服）** 是对外顾客联络触点，直接适用本标准的协同机制要求；**米高/米宝（B 端商户内部助手）** 是内部运营工具，不在「顾客联络服务」宣称范围内（若对其作 AI 内容宣称另按《人工智能生成合成内容标识办法》评估）。
- 责任视角：平台（米高/杭州词元通达）与商户双方。平台负责把「能力与机制」做对并**可配置**；商户负责按标准运营（安排人工坐席等）。
- **宣称措辞红线**：推荐性国标无认证/备案机制 → 主页不得写「通过国标认证/检测/备案」，只能写「遵循/对标 GB/T 47746-2026」+ 具体能力点，且**每一项能力点都必须真实存在**（本文档第 4 节为准）。

## 3. 条款 → 机制对照矩阵

> 逐条对照标准公开报道归纳的要求（标准全文以全国标准信息公共服务平台为准）。填充状态：🟢 满足 / 🟡 部分 / 🔴 缺口 / ⏳ 审计中。

| # | 国标要求维度 | MIGAO 对应机制 | 审计证据（文件） | 状态 |
|---|---|---|---|---|
| 3.1 | 服务范围科学划分（AI 标准化问题，人工复杂/涉安全） | 双 Agent + 意图路由 + Skill 分工；复杂投诉(赔偿/法律)→转人工 | `app/graph/`、`app/graph/skills/` | ⏳ |
| 3.2 | 转人工便捷入口、不层层隐藏 | D1 显式请求直转、商家 autoHandoffKeywords、mini-app 入口可见性 | `graph/handoff_judge.py`、`frontend/mini-app/src/pages/chat/index/index.tsx` | ⏳ |
| 3.3 | 达到条件自动流转人工 | D3 judge S1(负面情绪)/S2(多轮未解决)/S3(超范围) + 冷却 | `graph/handoff_judge.py`、`graph/nodes.py`、`graph/handoff_offer.py` | 🟢 已确认 |
| 3.4 | 切换后信息同步，不重复询问 | **🔴 人工工作台未见 AI 对话上下文（aiSessionId 仅引用）** | `admin-api AgentSessionService`、`admin-web human-sessions/page.tsx` | 🔴 |
| 3.5 | AI 回复显著 AI 生成标识 + 必要风险提示 | ⏳ 审计中（nav「小布+AI」badge 是否为充分标识待定） | `mini-app MessageBubble/chat page` | ⏳ |
| 3.6 | 价格/折扣/退款/赔偿/合同变更：AI 只解释规则、收集材料、生成工单，最终确认归人工或规范化流程 | ⏳ 审计中（confirm 卡 + 状态机 + prompt 约束） | `app/tools/`、`app/graph/skills/`、admin-api 售后状态机 | ⏳ |
| 3.7 | 过程可追溯 | 会话/消息/工单落库 + 审计日志 | 全链路 | 🟢 待确认 |

## 4. 已确认机制清单（现状证据）

### 4.1 转人工触发（C 端小布）
- **D1 显式请求**：`app/graph/handoff_judge.py` `_EXPLICIT_HANDOFF_WORDS`（转人工/转接人工/找人工/找真人…），`nodes.py` intent_router 短路直转 complaint，不经建议卡。
- **D3 AI 主动建议**：`judge_handoff()` → S1 单轮负面情绪（general）/ S2 近 3 条 ≥2 负面 / S3 赔偿·法律·维权类超范围；每会话建议上限 1 次 + 用户拒绝后冷却（`DEFAULT_HANDOFF_MAX_OFFERS`）。
- **商家自定义关键词**：`agents/tenant_config.py` `autoHandoffKeywords`（每租户可配）。
- **执行**：`app/tools/human_handoff.py` → 建投诉工单（`POST /api/admin/agent/after-sales`）+ 通知管理员 + 建人工会话（`POST /api/admin/agent-sessions`，带 `aiSessionId`）+ 返回安抚话术；非营业时间降级留言（`afterHoursMessage`）；`terminal=True` 清会话状态。

### 4.2 转人工后的通道（人机协同闭环）
- C 端：`frontend/mini-app/src/store/chatStore.ts` `handedOff` → 消息走人工会话 API；chat 页顶部「已为您转接人工客服」横幅。
- 人工侧：admin-web `agent-workspace/human-sessions/page.tsx` 人工客服工作台（waiting/active 列表 + 对话 + 轮询）。
- admin-api：`AgentSessionService`（createSessionForHandoff / sendMessage / assignSession / endSession / getSessionDetail），人工会话状态机 waiting→active→ended/transferred；顾客消息归属校验（防注入）；系统消息承载会话创建记录。

### 4.3 承诺边界既有约束（prompt 层）
- `customer_aftersales_skill.py`：仅明确转人工/情绪激动/涉赔偿法律才 human_handoff；禁止编造售后信息/退款金额。
- `customer_order_skill.py`：不能修改/取消订单 → 引导转人工；已发货可走售后申请。
- `customer_quote_skill.py`：优惠需到店/人工申请。
- 反例库 `references/EXAMPLES-*.md` 均含「越权承诺→正确转人工」校准。

## 5. 差距清单（GB-NN，随审计更新）

| ID | 关联条款 | 现状 | 影响 | 方案（草案） | 状态 | 关联 PR/Issue |
|---|---|---|---|---|---|---|
| GB-01 | 3.4 切换后信息同步 | 人工工作台仅见人工会话内消息，AI 对话仅存 `aiSessionId` 引用 | 顾客需向人工重复描述问题（国标点名痛点） | 转人工时透传 AI 会话最近 N 轮摘要/原文（或关键上下文），入人工会话并展示 | 🔴 | #2775 |

> 占位：GB-02（AI 生成标识）GB-03（风险提示）GB-04（承诺边界动作级缺口）GB-05（转人工入口可见性）待 4 路审计回收后补全。

## 6. 落地路线（PR 追踪）

| PR | 内容 | Issue | 状态 |
|---|---|---|---|
| 本文档 | 差距分析 + INDEX 登记 | #2775 | ⏳ |
| — | 转人工上下文同步（ai-agent→admin-api→admin-web） | #2775 | ⏳ |
| — | AI 生成标识与风险提示 | #2775 | ⏳ |
| — | 承诺边界收口 | #2775 | ⏳ |
| — | 官网主页合规宣称 + UI 测试 | #2775 | ⏳ |

## 7. 验证与验收

- 每项改造遵守仓库铁律：test-first、测试文件带 `# case_ids`、提交前 `./verify-all.sh gate` + `./check-ui-regression.sh`、跨模块 `./contract-check.sh`。
- 收尾验收：宣称能力点逐条用 E2E/单测固化（防止未来回归造成「宣称与实际不符」）。

## 8. 一手来源

- 全国标准信息公共服务平台 GB/T 47746-2026 详情页（发布/实施/归口）
- 人民日报 2026-09-02 消息（实施报道）
- 人民日报海外版「融观中国」2026-08-31 深度报道（条款归纳来源）
