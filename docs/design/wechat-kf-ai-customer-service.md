# 企业微信「微信客服」智能客服 —— 详细设计（v1.2，2026-11-28）

> **定位（2026-11-28 用户裁定，逐字）**：「C 端也不叫米宝了，C 端现在**不提供 agent 形态，只提供技术能力**，
> 直接叫**智能客服**」「务必结合我们最新的整体方案去更正和改造，特别是 C 端智能客服那块」。
> 同日再裁定（逐字）：「A，**大部分客服工作都要由我们的智能客服完成，只有 AI 搞不定的事情才转人工**」。
>
> ⇒ **智能客服 = 通道（微信客服 kf）+ 判定 + 回复**，节奏是 **AI 主力 / 人工兜底**（不是「AI 兜底」）。
> C 端对话内核（`agent_type="xiaobu"`，工具集原样保留）**降级为内核**：只被通道内部调用来产文，
> **不再对外提供 agent 服务**（无 persona 人设 / 开场白 / 悬浮助手 / 独立聊天面板）。
> 本文 v1.1 里凡是把 C 端写成「与米宝对话 / 米宝 AI 接待 / 米宝 Agent」的措辞，一律按此口径读作「内核产文」。
> 我们不做店铺、不碰交易、不碰资金。
>
> **本文回答**：怎么接、怎么判、怎么发、怎么不重复、怎么不串租户、怎么失败、怎么验收。
> **前置**：商户已有（或新开）**已认证**的企业微信 → 开通微信客服 → 授权我们。
>
> **v1.1 修订说明**：v1.0 经两轮对抗评审（企微协议 / 本仓落地），修正 5 个 P0 假前提：
> `send_msg` 有 `msgid` 幂等键、`change_type` 不是状态、state 4 含「未开始」且不可 API 变更、
> 本仓 RLS 实际不生效、已有 `sessions/session_messages/agent_sessions` 不应另起一套。
> 另修正：事件响应消息 20s/48h TTL、suite 级凭证、access_token 与 event token 混用、调度池单线程。
>
> **v1.2 修订说明**（issue #9302）：① 形态定稿为「通道 + 判定 + 回复，无 agent 形态」，见 §1.1.1；
> ② 接通 `AI_REPLY` 一跳（判定 → 内核产文 → outbox → 发送 / 转人工），见 §1.1.2~§1.1.3；
> ③ 落定三条闸门（一次入站至多 1 条 / 写工具不上通道 / 数值只能来自工具），见 §1.1.4；
> ④ 修两个对抗「AI 主力」口径的现存缺陷：`HUMAN_WORDS` 里「客服」单独出现就升级（§1.1.5）、
> 预算窗口不随客户新消息重置（§1.1.6）。
>
> **设计原则**（冲突时按此裁决）：
> 1. **fail-closed**：状态不明、事件乱序、接口报错 → 不发，落待人工；
> 2. **幂等优先**：回调、消息、发送三层都去重；`send_msg` 用 `msgid` 幂等键；
> 3. **单写者**：同一会话同时只有一个 AI 在生成/发送（版本 CAS，不跨调用持锁）；
> 4. **可解释**：每次介入决策、每次发送、每次失败都落库；
> 5. **复用既有**：会话/消息/转人工用 `sessions/session_messages/agent_sessions`，不新建平行体系；
> 6. **最小依赖**：PG + Redis + Spring 调度；不引 Kafka/MQ、KMS、Prometheus 采集端。

---

## 0.1 开通前置与自检（不做这步，授权成功也收不到消息）

| 前置 | 不满足的表现 | 自检方式 |
|---|---|---|
| 后台勾选「**微信客服-通过API管理微信客服账号**」 | `48001` / 无权限 | 首次调 `service_state/get` 探测 |
| **接待人员在应用可见范围内** | `trans(3)` 失败 / 列表为空 | `获取接待人员列表` 校验 |
| 自建应用配置到「微信客服-可调用接口的应用」 | `48001` | 同上 |
| 第三方应用具「微信客服→管理账号、分配会话和收发消息」 | 授权成功但无权限 | 权限点校验 |
| 接待人员**已激活企业微信** | `95014` | 列表 + 状态事件 |

**规则**：自检失败 → `kf_channels.status = unauthorized`，给商户**可执行指引**（去后台勾哪一项），
而不是记成「发送失败」。`48001`/`95014` 必须与「消息发送失败」分开告警。

---

## 1. 范围与非目标

| 做 | 不做 |
|---|---|
| 微信客服会话接入（回调 + `sync_msg` + `send_msg`） | 店铺/商品列表/下单/支付 |
| 智能客服内核接待（**无 agent 形态**）+ 知识库 + 行业工具（算料/查单/售后） | 微信小店/抖店代运营 |
| 介入策略（AI/人工/静默/转接） | 个人微信 Hook |
| 坐席工作台（复用 `agent_sessions`）+ 质检 + 报表 | 平台代收/分账 |
| Web SDK / 商户自有小程序（后续） | 抖音私信 AI 接管（准入已关） |
| 微信客服通道（唯一 C 端入口） | **C 端 agent 形态**：persona 人设 / 开场白 / 悬浮助手 / 独立聊天面板 |

**SLO**：回调 P99 < 500ms（实测口径，不拍 200ms）；入队到首响 P95 < 10s；发送成功率 > 99%；
`unknown` 率 < 0.5%；跨租户泄漏 = 0；重复发送 = 0。

---

## 1.1 形态定稿与 `AI_REPLY` 一跳（v1.2 落地，2026-11-28，issue #9302）

> **用户裁定（2026-11-28，逐字）**：「C 端也不叫米宝了，C 端现在**不提供 agent 形态，只提供技术能力**，
> 直接叫**智能客服**」/「A，**大部分客服工作都要由我们的智能客服完成，只有 AI 搞不定的事情才转人工**」。

### 1.1.1 形态：智能客服 = 通道 + 判定 + 回复（无 agent 形态）

| 提供 | 结构性不做（不是"还没做"） |
|---|---|
| 微信客服通道（回调 / `sync_msg` / `send_msg` / 预算 / 幂等） | **agent 形态**：persona 人设、开场白、悬浮助手、独立聊天面板 |
| 判定（默认 AI → 规则短路明确索取/高风险 → 语义判定补召回 → 升级取并集） | 客户侧「对话 UI」（C 端小程序已于 2026-11-26 整目录下线，issue #9233） |
| 回复（C 端内核产**一条**文本 → `kf_outbox` → 发送 / 转人工） | 通道上的卡片 / 菜单 / 表单交互（`kf_outbox` 只收 `parts=[{type:text}]`） |
| 内核能力（知识库 / 算料 / 查单 / 售后；工具集原样保留，**只读工具是必需项**） | 把内核当「可独立对外服务的 agent」（**内核降级为内核**） |

**「内核降级为内核」的判据（现取，不是口号）**：

```bash
# 没有任何客户端以 persona 调 chat（0 命中）
git grep -rn "persona" origin/main -- frontend | grep -i "xiaobu"
# 内核标识只活在文案常量里（6 处，值即「企业智能客服」）
git grep -rn "xiaobu" origin/main -- frontend | wc -l
```

⇒ 内核只是被通道调用的一个函数（`agent_type="xiaobu"` 沿用旧标识，工具/路由口径不动），
不是一个对外产品形态。

### 1.1.2 现取现场（v1.2 之前缺的那一环）

| 面 | 现取（`git show origin/main:`） |
|---|---|
| 入站 | `KfSyncWorker` → `KfSessionIngestService` 建 kf 会话 + `session_messages`；**不建 AgentSession** |
| 判定 | `KfDecisionService.decide()` ⇒ `SILENT` / `ESCALATE_HUMAN` / `AI_REPLY` |
| `AI_REPLY` 消费者 | **0 处**：`git grep -n "AI_REPLY" origin/main -- backend` 只命中 `KfDecisionService` 与其单测 |
| 发送 | `KfSendService.enqueueReply(...)`（预算 / 长度 / 会话校验 → `kf_outbox`）+ `KfOutboxSender`（异步 `send_msg`） |
| 判定端点 | `POST /api/internal/kf/decide` —— 仓内无调用方 |

⇒ 通道与判定都齐了，**唯一缺的是「判定说 AI 可以答」之后那一跳**：客户在微信里发消息，永远等不到回复。

### 1.1.3 一跳一跳的时序（AI 主力 / 人工兜底）

```
微信客户发消息
  │
  ▼ ① 入站（KfSyncWorker.poll → syncCursor；30s 固定节奏 + 回调 dirty 加速）
sync_msg → 逐条 origin=3 客户消息
  │   └─ KfSessionIngestService.ingest()：建/取当前段会话 + 落 session_messages（msgid 幂等）
  │        · 落库成功 ⇒ 该会话 kf_send_budget 窗口重置（used=0 / window_start=NOW()，见 §1.1.6）
  │        · 返回 Ingested{sessionId, text, state}；重复/忽略 ⇒ null（不触发后续任何一跳）
  ▼ ② 判定（KfDecisionService.decide：默认 AI，例外升级）
state ∉ {0,1}（人工接待中/已结束）⇒ SILENT —— 不抢话，也不转人工
明确索取人工 / 风险词 ⇒ ESCALATE_HUMAN（规则短路，**不发起**语义判定）
规则未命中 ⇒ 语义判定补召回：它要升级则升级（并集），否则 AI_REPLY
语义判定不可用/超时 ⇒ fail-open 回退规则 AI_REPLY   ← 判定侧既有口径（#9196），本包不改
  ▼ ③ 只有 AI_REPLY 才继续（KfAiReplyLoop.onCustomerMessage）
POST ai-agent /api/internal/kf/reply（Service Token；连接 300ms / 读 8s）
  │   └─ C 端对话内核（agent_type=xiaobu，工具集原样保留，**只读工具真查**）
  │        · 只保留**最后一条**正文（中间过程「正在查询…」丢弃）
  │        · 单轮工具调用 ≤3；总超时 ≤8s；同时回报本轮 tool_calls 次数
  ▼ ④ 可投递判定（KfAiReplyLoop.deliverable：确定性、零 LLM；见 §1.1.7）
空/过短 ✗ 中间过程话术 ✗ 无权承诺（已为您转接/已通知人工）✗ 0 次工具却报金额 ✗ ⇒ 转人工
  ▼ ⑤ 入队（唯一写手：KfSendService.enqueueReply；本类不碰 kf_outbox）
预算（每条客户消息 ≤5 条 / 窗口 48h）→ 正文 ≤2048 字节 → 会话当前段有效 → 生成 msgid → kf_outbox(pending)
  ▼ ⑥ 发送（KfOutboxSender，异步；不在本跳）
claim(pending / sending 超时) → send_msg(msgid 幂等) → accepted / failed / unknown
  │   └─ msg_send_fail 事件 → markFailedBySentMsgid（fail_type 按 FMEA 处置）
  ▼ ⑦ 兜底（唯一例外路径：转人工）
生成失败/超时/空/不可投递/入队被护栏拒绝 ⇒ 0 条 outbox + KfTransferService.transferToHuman（trans(2) + 工作台 waiting）
转人工自身失败 ⇒ 只记日志（消息已落库、游标照常前进），绝不因此重放同一条消息
```

**为什么这一跳放在 `KfSyncWorker` 的同一轮里**（而不是独立 dispatch worker）：本仓现状没有
`KfDispatchWorker`（那只是本文件 v1.1 的构想名），而同步轮已有「消息优先 / 失败不阻塞游标」的成熟口径；
独立 worker 需要新的 claim/租约/重放语义 —— 属**未固化项**（§1.1.8 #3），不在这一包里扩。

### 1.1.4 决策记录：通道稀有度决定的三条闸门（2026-11-28 母单裁定）

**依据（现取命令 + 读数）**：

```bash
# ① 发送预算：48h 内最多 5 条
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/kf/KfSessionStatusProvider.java \
  | grep -n "48h 内最多 5 条"
# ② 单条正文硬上限：2048 字节（微信客服硬上限）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/kf/KfSendService.java \
  | grep -n "MAX_TEXT_BYTES ="
# ③ 预算在 DB 里原子扣减（不是内存计数，也不能"先发再补"）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/mapper/KfSendBudgetMapper.java \
  | grep -n "used < 5"
```

⇒ 每一条自动回复都是**稀缺资源**（一条客户消息只值 5 条里的一格），所以真正的核心不是"带不带工具"，
而是**「绝不在通道上暴露中间过程、绝不发没有工具支撑的数」**。

| # | 闸门 | 落地位置 | 为什么 |
|---|---|---|---|
| 1 | **只读工具要带（而且是必需）**：查商品/价格/库存/订单/物流/算料必须真查；但**全部在服务端串行完成，只发一条最终答复**。**禁止**「正在查询…」「稍等」「我看看」这类中间气泡 | ai-agent `_stream_reply` 只留最后一条文本；admin-api `KfAiReplyLoop.deliverable` 再按话术兜一层；一次入站只调一次 `enqueueReply` | AI 要承担大部分对话，答不了就等于把活推回人工；而中间气泡会烧掉 5 条预算、且异步通道里客户看到一半更困惑 |
| 2 | **写工具一律不带**（建单/改单/退款/发券/改价）⇒ 需要写动作的诉求**转人工** | 通道只发文本；卡片/确认卡不上通道；判定升级即转人工 | 微信客服是**异步通道、无可靠二次确认 UI**，客户可能只看到「已下单」；错一次即不可逆的真实经济损失（与 B 端 order 域只读 #5247 同口径） |
| 3 | **数值只能来自工具**：价格/库存/金额/运费拿不到 ⇒ 转人工，**不许模型编** | ai-agent 回报本轮 `tool_calls`；admin-api：0 次工具调用却出现金额形态 ⇒ 转人工 | 假价格发给客户 = 真实商业损失（与 #9287「环境前置缺失」、`stock_semantics` 的「商品级 stock 列不一致」同口径：数据面读不到 ⇒ 不可判定，不许猜） |

**配套上限（同一裁定）**：一次入站**至多 1 条**自动回复；单轮工具调用 **≤3** 次；总超时 **≤8s**
（Java 读超时 `wechat.kf.reply-timeout-ms` 默认 8000ms，Python `REPLY_TIMEOUT_SECONDS = 8.0` —— 两处同源，改一处必改另一处）；
超限 / 超时 / 工具失败 / 空文本 ⇒ **fail-closed 转人工**。

### 1.1.5 何时升级：默认 AI、例外升级（判据清单）

**升级（`ESCALATE_HUMAN`）只认两类形态**（`KfDecisionService` 的 `HUMAN_REQUEST` + `RISK_WORDS`）：

| 形态 | 例子 | 为什么升级 |
|---|---|---|
| `人工` / `真人` **单独出现** | 我要人工 · 转人工 · 找人工 · 真人吗 | 中文里几乎专指人工服务；「明确索取必须永不漏」（宁可多升级） |
| **动作词 + 对象词**（找/要/叫/联系/转/需要/请 + 人工/真人/**客服**） | 找客服处理 · 联系客服 · 叫客服来 · 要客服 | 有动作词的「客服」= 索取人工服务的动作短语 |
| 风险词（**一个字都不许动**） | 投诉 · 退款 · 赔偿 · 起诉 · 律师 · 曝光 · 差评 | 涉钱/涉法/涉名誉，AI 无权承诺 |
| 语义判定要升级（并集） | 情绪激动、模糊不满、要求承诺 | 规则抓不到的形态靠语义补召回 |

**不升级（继续 AI 处理）**：`客服` **单独**出现 —— 「客服你好」「你们客服在吗」「客服电话多少」
「刚才那个客服说的」。这些是称呼 / 寒暄 / 询问，不是要人工。

> **为什么这条要单独写进设计文档**：v1.2 之前 `HUMAN_WORDS = List.of("人工","真人","客服","转人工")`
> —— **「客服」单独出现就升级**。微信客服场景里客户张口就是「客服在吗」，于是大量本该 AI 接住的对话被
> 推给人工，与「大部分客服工作由智能客服完成」的裁定**正相反**。⇒ 改成「动作词 + 对象词」的组合判据，
> 并在代码里留注释说明**不许改回只匹配「客服」**（issue #9302）。
>
> **一处矛盾已裁定（2026-11-28，母单起草错误；以判据 ① 为准）**：裁定正文里「`客服电话` / `客服在吗`」
> 同时出现在「升级形态」与「不升级（判据 ①）」两处 —— 起草时把「索取**联系方式**」与「索取**人工接管**」
> 混成了一类。**结论 = 不升级**，三条理由：① A 口径的判据是「AI 搞不定才转人工」，不是「提到人工相关词就转」
> —— 「你们客服在吗」是寒暄/确认在线（客户本来就在跟客服说话），「客服电话多少」是**可答的问题**（能答就该答）；
> ② 把「客服」相关词一律算升级 = 退回本版正在修的缺陷（`HUMAN_WORDS` 含「客服」单词 ⇒ 海量假升级），等于没修；
> ③ 升级的正当形态只有一类：**客户明确要求换人**（我要人工 / 转人工 / 找人工 / 人工客服 / 找客服处理）。
>
> **可选加固（本包不做，见 §1.1.8 #9）**：联系方式诉求 —— 能取到租户配置的客服电话 ⇒ AI 直接答（号码从配置取，
> **不写进 prompt**）；取不到 ⇒ 升级（此时才是「搞不定」）。现取：`backend/admin-api` 侧**没有**租户级客服电话
> 字段（`Tenant*` 实体只有 `TenantAiConfig` / `TenantLogisticsConfig` / `TenantPaymentQrcode`；`contactPhone`
> 只存在于 `Supplier`）⇒ 需要新增配置字段 + 管理入口 + 注入路径，属另一跳。

### 1.1.6 预算：窗口 = 客户最后一条消息起的 48h（每条客户消息给 5 条额度）

**微信侧规则**（`docs/wechat-store-and-kefu-research.md`）：「仅当微信客户在**主动发送消息**后的 **48 小时**内，
企业可发送消息，最多 **5 条**；**若用户继续发送消息，企业可再次下发**」。

**v1.2 之前的实现与规则的偏差**：`KfSendBudgetMapper.tryConsume` 只在**窗口过期 48h** 时重置
（`window_start < NOW() - INTERVAL '48 hours'`）⇒ 整个会话**总共 5 条**，聊到第 6 句 AI 再也发不出去，
「AI 主力」在算术上不成立。

**修法（保守，不放宽上限）**：
1. **入站新消息 ⇒ 重置窗口**：`KfSessionIngestService` 在客户消息落库成功后调
   `KfSendBudgetMapper.resetWindow`（`used=0` / `window_start=NOW()`，upsert）；
2. **上限不动**：`tryConsume` 的 `used < 5` 与表约束 `ck_kf_send_budget_used CHECK (used <= 5)` 原样保留
   ⇒ 每条客户消息仍然最多 5 条；
3. **重复消息（`msgid` 幂等）不重置** —— 否则一次重放能给同一条消息白送 5 条额度；
4. **撞额度 ⇒ 转人工**（现行为 `KfBudgetExhaustedException` ⇒ `KfAiReplyLoop` 落 `ESCALATE_HUMAN`，
   **不许静默丢消息**）。

**一句话**：预算窗口 = **客户最后一条消息起的 48h**，每条客户消息给 5 条额度；AI 默认一入站一回一条 ⇒
正常对话不撞额度；撞额度 ⇒ 转人工。

**与「AI 主力」的张力（登记，不擅自放宽）**：5 条/48h 对「大部分对话由 AI 完成」是否够，**需产品确认**；
另有一条读数待登记：工作台人工回复（`AgentSessionService.sendMessage`）每条坐席消息**恰 1 次**
`enqueueReply`（同一事务内），不按 turn 扇出 —— 但同一 turn 里坐席连发多条消息仍会各自吃额度。

### 1.1.7 fail-closed 矩阵（触发 → 后果）

| 触发 | outbox | 判定结果 | 客户看到 |
|---|---|---|---|
| 生成失败 / 超时（>8s） / 内核报错 | **0 条** | `ESCALATE_HUMAN` | 无（转入人工接待池） |
| 空正文 / 只有空白 / 短于 2 字 | **0 条** | `ESCALATE_HUMAN` | 无 |
| 中间过程话术（正在查询/稍等/我看看） | **0 条** | `ESCALATE_HUMAN` | 无 |
| 无权承诺（已为您转接 / 已通知人工 / 已提交转人工） | **0 条** | `ESCALATE_HUMAN` | 无 |
| 0 次工具调用却报金额 | **0 条** | `ESCALATE_HUMAN` | 无 |
| 单轮工具调用 >3 | **0 条** | `ESCALATE_HUMAN` | 无 |
| 预算耗尽 / 48h 窗口过期 / 会话已结束（`KfSendService` 拒绝） | **0 条** | `ESCALATE_HUMAN` | 无 |
| 判定 `ESCALATE_HUMAN`（明确索取/风险词/语义升级） | **0 条** | `ESCALATE_HUMAN` | 无 |
| 判定 `SILENT`（人工接待中） | **0 条** | `SILENT` | 无（不抢话） |
| 全部通过 | **恰 1 条** | `AI_REPLY` | 一条最终答复 |

### 1.1.8 边界与未固化项（照实登记）

| # | 项 | 现状 | 为什么本包不做 |
|---|---|---|---|
| 1 | 回复质量不设 LLM 判据 | 「低置信」用**确定性代理**（空 / 过短 / 中间过程 / 无权承诺 / 无数值支撑） | 每题多一次模型调用，且判据自身要长红证；阈值应由产品定 |
| 2 | 多轮上下文 | 单轮（只传客户最新一条） | kf 历史在 `session_messages`，取几条 / 是否取 AI 侧口径未定 |
| 3 | 独立 dispatch worker / 重放 | 同步轮内一跳；崩溃窗口内「已落库未回复」的消息**不会自动重放** | 需要 claim / 租约 / 重放语义（另起一张待办面） |
| 4 | 写工具在通道下的可达性 | 工具集原样保留，但**通道只发文本**；内核若想发卡片/确认卡，本通道渲染不出来 | 写动作按 §1.1.4 一律转人工；真要上通道需先定卡片降级（§18.5.1）与二次确认方案 |
| 5 | `sessions.ai_enabled` 未接 | kf 建会话恒 `true`，判定只看 `kf_session_remote.state` | 商户级 AI 开关注解与 UI 未定 |
| 6 | 「每条客户消息 5 条」这一读法的真机验证 | 依据 = 官方文档转述（`docs/wechat-store-and-kefu-research.md`），本机无真机/无线上凭据 | **需一次真实通道验证**（另开单，不在本包伪造读数） |
| 7 | 工作台人工回复的额度扇出 | 现取：每条坐席消息恰 1 次 `enqueueReply`，不按 turn 扇出 | 只登记读数，归工作台包 |
| 8 | 继承 v1.1 的灰度/shadow 档 | 未做（判定 + 回复直接生效） | 需产品定灰度范围与判据 |
| 9 | 联系方式诉求未做「配置取号」 | 现状：`客服电话多少` 不升级，由 AI 按知识库答；租户级客服电话字段**不存在**（现取：`Tenant*` 实体无该字段，`contactPhone` 只在 `Supplier`） | 需新配置字段 + 管理入口；判据 = 有配置时 `AI_REPLY` 且回复含该号码、无配置时 `ESCALATE_HUMAN`（号码从配置取，**不写进 prompt**） |

---

## 2. 架构

```
微信客户
  │ 消息
  ▼
企业微信（回调：加密 XML + msg_signature）
  │
  ▼
admin-api（Java）
  ├─ KfCallbackController   GET 验证（1s 内返回明文 echostr）
  │                         POST 验签/解密 → msg_signature 去重 → 落 kf_inbox
  │                              → UPDATE kf_sync_cursor.dirty_at → 200 空串（<5s）
  ├─ KfSyncWorker（独立 kfScheduler 线程池）
  │    ├─ 固定 30–60s / 每 active open_kfid 增量 sync_msg（不依赖回调）
  │    └─ 回调 dirty 触发加速；cursor 持久化；has_more 循环带空列表保护
  ├─ KfDispatchWorker
  │    ├─ 会话单写者：kf_session_remote.version CAS（不跨 LLM 持锁）
  │    ├─ AiAgentClient → /internal/kf/decide + /internal/kf/reply（非流式）
  │    ├─ 介入策略结果 → AI_REPLY / SILENT / TRANSFER / ESCALATE
  │    └─ 写 kf_outbox（预算扣减在毫秒级事务内）
  └─ KfSenderWorker → send_msg（带 msgid）→ 回写 sent/failed/unknown
        │
        ▼
ai-agent-service（Python）
  ├─ Intervention Policy（规则 + LLM 判定）
  ├─ LangGraph Agent + Tools（知识/算料/查单/售后）
  └─ 回复编排（1–2 条：文本 / 小程序卡片 / 图片）
```

> **落地形态（v1.2 现取）**：本仓**没有**独立的 `KfDispatchWorker` —— 判定与 `AI_REPLY` 一跳在
> `KfSyncWorker` 的同一轮内同步执行（`KfAiReplyLoop`），发送仍由 `KfOutboxSender` 异步做；
> 完整时序见 §1.1.3。

**线程与连接池（本仓实测约束）**：
- Spring Boot 默认 `spring.task.scheduling.pool.size = 1`，现有 5 条定时腿共用；kf 必须建**独立**
  `ThreadPoolTaskScheduler`（bean `kfScheduler`，core 4 / max 8 / 有界队列 / `CallerRunsPolicy`）；
- `Hikari maximum-pool-size = 20`：kf worker 用**独立 DataSource/HikariPool（8）**，不与 Web 请求抢连接；
- 所有 worker SQL 照 `ScheduledTaskMapper` 范式：`@InterceptorIgnore(tenantLine="true")` +
  **显式** `tenant_id = #{tenantId}` 参数；claim 用 CTE `FOR UPDATE SKIP LOCKED` + `claimed_by/claimed_at` fencing。

**为什么不用 MQ**：现有基建只有 PG + Redis + Spring 调度；`ScheduledTaskMapper` 已把 PG 队列的
LIMIT 压平、RETURNING 类型、回收幂等三个坑趟过，复用它，不重写。

---

## 3. 数据模型

### 3.1 复用既有表（不新建平行体系）

| 既有表 | kf 用法 |
|---|---|
| `sessions`（已有 `channel`） | kf 会话 = `channel='wechat_kf'` 的一行；`status`、`ai_enabled`、`assigned_agent_id` 直接复用 |
| `session_messages` | kf 消息 = 一行；`origin 3/4/5 → role user/assistant/system`；`msgtype → content_type` |
| `agent_sessions` | 转人工 = 一行（`ai_session_id → sessions.id`）；排队/分配/结束/转接全复用 |
| `agent_messages` | 人工侧消息 + `is_internal` 备注 |

**远端镜像**单独放 1:1 扩展表，避免污染既有表：

```sql
CREATE TABLE kf_session_remote (
  session_id      VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
  tenant_id       BIGINT NOT NULL REFERENCES tenants(id),
  open_kfid       VARCHAR(128) NOT NULL,
  external_userid VARCHAR(128) NOT NULL,
  state           SMALLINT NOT NULL DEFAULT 4,  -- 0..4 远端状态
  servicer_userid VARCHAR(128),
  version         INT NOT NULL DEFAULT 0,       -- 单写者 CAS
  epoch           INT NOT NULL DEFAULT 1,       -- 会话分段
  last_msg_at     TIMESTAMPTZ,
  last_sync_at    TIMESTAMPTZ,
  closed_at       TIMESTAMPTZ,
  close_reason    VARCHAR(32),                  -- human_end | api_end | expired_48h
  UNIQUE(open_kfid, external_userid, epoch)
);
CREATE UNIQUE INDEX uq_kf_remote_current ON kf_session_remote(open_kfid, external_userid)
  WHERE closed_at IS NULL;
```

### 3.2 kf 专属表

```sql
-- 套件级凭证（第三方应用）：Token/AESKey 是 suite 级，不是租户级
CREATE TABLE kf_suites (
  suite_id       VARCHAR(128) PRIMARY KEY,
  token          VARCHAR(128) NOT NULL,
  encoding_aes_key VARCHAR(128) NOT NULL,
  suite_secret_enc TEXT NOT NULL
);

CREATE TABLE kf_channels (
  id             VARCHAR(64) PRIMARY KEY,
  tenant_id      BIGINT NOT NULL REFERENCES tenants(id),
  corp_id        VARCHAR(128) NOT NULL,
  open_kfid      VARCHAR(128) NOT NULL,
  auth_mode      VARCHAR(16) NOT NULL,        -- third_party | self_built
  suite_id       VARCHAR(128),                -- 第三方
  callback_token VARCHAR(128),                -- 自建：静态回调 Token（不过期）
  encoding_aes_key VARCHAR(128),              -- 自建：静态 EncodingAESKey
  secret_enc     TEXT,                        -- 换 access_token 的 secret / permanent_code（加密）
  secret_key_id  VARCHAR(32),
  status         VARCHAR(16) DEFAULT 'active',-- active|expired|revoked|unauthorized
  UNIQUE(corp_id, open_kfid)
);

-- 回调收件箱（只做入站事件，不当消息表）
CREATE TABLE kf_inbox (
  id             BIGSERIAL PRIMARY KEY,
  msg_signature  VARCHAR(256) NOT NULL UNIQUE, -- 已覆盖 timestamp+nonce+密文
  corp_id        VARCHAR(128),
  tenant_id      BIGINT,
  open_kfid      VARCHAR(128) NOT NULL,
  payload        JSONB NOT NULL,
  status         VARCHAR(16) DEFAULT 'pending',
  attempts       INT DEFAULT 0,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 拉取游标 + 数据新鲜度
CREATE TABLE kf_sync_cursor (
  tenant_id      BIGINT NOT NULL,
  open_kfid      VARCHAR(128) NOT NULL,
  cursor         VARCHAR(128),
  dirty_at       TIMESTAMPTZ,                 -- 回调触发（含重复回调）
  last_success_at TIMESTAMPTZ,
  updated_at     TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (tenant_id, open_kfid)
);

-- 发送预算（48h / 5 条）
CREATE TABLE kf_send_budget (
  session_id     VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
  tenant_id      BIGINT NOT NULL,
  window_start   TIMESTAMPTZ NOT NULL,
  used           INT NOT NULL DEFAULT 0,
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 发件箱（msgid 幂等 + 租约）
CREATE TABLE kf_outbox (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      BIGINT NOT NULL,
  session_id     VARCHAR(64) NOT NULL REFERENCES sessions(id),
  msgid          VARCHAR(32) NOT NULL UNIQUE,  -- ≤32B [0-9a-zA-Z_-]，客服账号内唯一
  parts          JSONB NOT NULL,
  status         VARCHAR(16) DEFAULT 'pending',-- pending|sending|accepted|failed|unknown
  attempts       INT DEFAULT 0,
  sent_msgid     VARCHAR(128),
  fail_type      INT,
  sending_at     TIMESTAMPTZ,
  lease_owner    VARCHAR(64),
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 介入决策（可解释）
CREATE TABLE intervention_decisions (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      BIGINT NOT NULL,
  session_id     VARCHAR(64) NOT NULL,
  message_id     VARCHAR(128),
  decision       VARCHAR(32) NOT NULL,
  scores         JSONB,
  rule_id        VARCHAR(64),
  model_version  VARCHAR(32),
  reason         TEXT,
  latency_ms     INT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 租户策略
CREATE TABLE kf_policies (
  tenant_id      BIGINT PRIMARY KEY REFERENCES tenants(id),
  mode           VARCHAR(16) DEFAULT 'shadow',
  risk_threshold INT DEFAULT 70,
  emotion_threshold INT DEFAULT 80,
  confidence_threshold NUMERIC(3,2) DEFAULT 0.40,
  human_cooldown_sec INT DEFAULT 600,
  keywords       JSONB,
  business_hours JSONB,
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 接待人员映射
CREATE TABLE kf_agents (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      BIGINT NOT NULL REFERENCES tenants(id),
  corp_id        VARCHAR(128) NOT NULL,
  wecom_userid   VARCHAR(128),
  open_userid    VARCHAR(128),
  display_name   VARCHAR(64),
  status         VARCHAR(16) DEFAULT 'offline', -- online|busy|offline
  stop_type      SMALLINT,                      -- 1 暂时挂起
  skills         JSONB,
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 媒体缓存
CREATE TABLE kf_media (
  id             BIGSERIAL PRIMARY KEY,
  tenant_id      BIGINT NOT NULL,
  open_kfid      VARCHAR(128),
  media_id       VARCHAR(256) NOT NULL,
  direction      VARCHAR(8) NOT NULL,
  mime           VARCHAR(64),
  size_bytes     BIGINT,
  storage_key    VARCHAR(512),
  expires_at     TIMESTAMPTZ,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(direction, media_id)
);
```

**建表必做**：`db/init/schema.sql` + `db/migration/V217__create_wechat_kf_tables.sql` **两处同源**；
每表 `tenant_id BIGINT NOT NULL` + `(tenant_id, ...)` 索引；
**不启用 FORCE RLS**（本仓无 GUC，FORCE 会让 owner 查询直接报错），隔离靠 MyBatis 拦截器 + 显式 `tenant_id`。

---

## 4. 状态机

### 4.1 会话状态（远端权威）

| 状态 | 含义 | AI 可发 | 允许变更 |
|---|---|---|---|
| 0 | 未处理（客户已发消息） | ✅ | → 2 / 3（0 可直接发消息，无需先 trans） |
| 1 | 智能助手接待 | ✅ | → 2 / 3 |
| 2 | 待接入池 | ❌ | → 3 |
| 3 | 人工接待 | ❌ | → 3（转交）/ 4（结束） |
| 4 | 已结束 / **未开始**（进入但未发消息） | ❌ | **不可 API 变更**；客户发消息 → 0 |

**`change_type` 是变更类型，不是状态序数**（禁止数值比较）：

| `change_type` | 含义 | → state |
|---|---|---|
| 1 | 从接待池接入 | **3** |
| 2 | 转接（人工→人工） | **3** |
| 3 | 结束会话 | **4** |
| 4 | 重新接入已结束/已转接 | **3** |

该事件**无时间戳字段**；乱序以 `sync_msg` 返回顺序为准。

**一致性规则**：
- 本地 `kf_session_remote.state` 由 `send_msg` 结果、`service_state/get` 对账、`session_status_change` 事件三类写者更新；
- 更新带 `version` CAS；冲突重读再判；
- **会话分段**：客户消息到达时，若当前会话已 `closed` 或 `last_msg_at > 48h` → 关闭旧段，`epoch+1` 新建；
  `change_type=4` 属于「人工重新打开最近一段」，**不新建 epoch**；
- **事件丢失**：固定 30–60s 增量 `sync_msg` 兜底；对账抽样 1%（不与 60s 全量混用）。

### 4.2 预算状态机

```
客户消息到达 → window_start = now, used = 0
发送前原子扣减：
  UPDATE kf_send_budget SET used = used + 1, updated_at = now()
   WHERE session_id = ? AND used < 5
     AND window_start > now() - interval '48 hours'
  RETURNING used;
无返回 → 不发（额度耗尽 / 窗口过期）
```

- 欢迎语/结束语走 `send_msg_on_event`，**不占 5 条**，但有独立 TTL（见 §10）；
- 发送失败不退还额度（避免超发）；
- 并发以 DB 原子更新为准，不用 Redis 计数。

### 4.3 发送状态机

```
pending → sending → accepted（接口已受理，≠ 送达）
                   ↘ failed（明确失败/不可重试）
                   ↘ unknown（超时/网络断，不自动重发）
accepted → 等 msg_send_fail 事件 → 若失败置 failed
```

- **`send_msg` 有 `msgid` 幂等键**（≤32B，客服账号内唯一）：建单时生成并落库；
  超时/5xx 用**同一 msgid** 重试；返回「msgid 重复」视为已受理；
- 接口返回成功**不代表送达**（官方原文），必须消费 `msg_send_fail` 事件才能定终态；
- `sending` 带租约（60s），崩溃后置 `unknown`，不重发。

---

## 5. 消息处理流水线

| 步 | 动作 | 失败处置 |
|---|---|---|
| 1 | 回调验签（`msg_signature`+`timestamp`+`nonce`）+ AES 解密 + `receiveid` 校验 | 丢弃 + 告警 |
| 2 | `msg_signature` 去重 → 落 `kf_inbox`；**无论是否重复**都 `UPDATE dirty_at` | 重复 → 仍 200 |
| 3 | 返回 **200 + 空串**（5s 内；超时平台重试 3 次，且不保证 100% 送达） | — |
| 4 | `KfSyncWorker`：固定 30–60s + dirty 触发；`sync_msg(cursor, token?)` | 退避；cursor 不前进 |
| 5 | `has_more` 循环：**空 `msg_list` 也推进/退避**，最大轮次 20 | 防死循环 |
| 6 | 消息归档 + 会话归并 + 介入判定 + **`AI_REPLY` 一跳**（`KfAiReplyLoop`：内核产文 → 入 outbox，见 §1.1.3） | fail-closed 转人工（矩阵见 §1.1.7） |
| 7 | 预算扣减 → `msgid` 发送 → 回写 | 按 §4.3 |

**单写者（不跨 LLM 持锁）**：

```sql
-- 抢本会话生成权：0 行 = 别人在生成 → 丢弃
UPDATE kf_session_remote SET version = version + 1, last_msg_at = now()
 WHERE session_id = ? AND version = ?;
```

LLM 调用、发送都在**事务外**；只在「读状态 + 扣预算 + 插 outbox」用毫秒级事务。
**不用** `pg_advisory_xact_lock` 跨外部调用（会吃干 20 连接池）。

**回调可靠性**：企业微信明确「无法保证 100% 回调成功」「超时会重试 3 次」⇒ 回调只当加速器，
真实消息以 `sync_msg` 为准；每个 active `open_kfid` **固定节奏**拉取，不依赖「有未读」判断
（没有 API 能查未读）。

**端点登记**（否则 CI 红）：`SecurityConfig` permitAll、`deploy/swas/nginx.conf` location、
`tests/unit_ci_workflows` 的端点/前缀登记。

### 5.1 入站消息类型

| `msgtype` | 处理 | 回复 |
|---|---|---|
| `text` | 直接进 Agent | 文本 / 卡片 |
| `image` | 下载（≤2MB）→ Vision | 文本 / 卡片；超限提示 |
| `voice` | 下载 → **AMR 转 wav** → ASR | 文本；失败请发文字 |
| `video` / `file` | 归档 + 提示 | 转人工 / 请发文字 |
| `link` / `miniprogram` / `menu` / `location` | 解析为上下文 | 正常回复 |
| `event` | `enter_session` / `session_status_change` / `servicer_status_change` / `msg_send_fail` / 撤回 | 按事件处理 |

### 5.2 AI 服务契约

```
POST /internal/kf/decide
  req:  {tenant_id, session_id, open_kfid, external_userid, recent_messages[], customer, state}
  resp: {decision, scores{risk,emotion,confidence}, rule_id, reason}

POST /internal/kf/reply
  req:  {tenant_id, session, message, context, budget_left}
  resp: {parts:[{type:text|image|link|miniprogram, ...}], knowledge_refs[], tool_calls[]}
```

- 单一 `AiAgentClient`：connect 2s / read 8s、连接池、仅 `ConnectException` 重试 1 次；
- 熔断：Redis 连续 5 次失败 → 开 60s，期间**Java 侧固定兜底文案**（不请求 AI）；
- 非流式（kf 不需要 SSE）；
- `AI_AGENT_SERVICE_TOKEN` 未配置 → 启动即 fail-closed，不用 `localhost:8000` 默认值。

### 5.3 回调 URL 模型

| 模式 | 回调 URL | 租户识别 |
|---|---|---|
| **第三方应用** | **全局一个 URL**（suite 配置） | 解密后 `corp_id` → `kf_channels` |
| 自建应用 | 每商户 `/api/kf/callback/{channelKey}` | `channelKey` → `corp_id` |

---

## 6. 关键时序

### 6.1 首次进入

```
客户点客服链接 → enter_session（state=4「未开始」，不要 trans）
  → 若有 welcome_code：20 秒内发欢迎语（1 条，不占 5 条）
  → 客户首条消息 → state=0 → 预算窗口开启（= 客户最后一条消息起 48h）→ 内核回复（§1.1.3）
```

### 6.2 普通问答（v1.2 现取）

```
消息 → sync_msg → 去重 → ingest（落 session_messages + 重置预算窗口）
     → 判定 AI_REPLY → 内核产文（/api/internal/kf/reply，≤3 次工具调用 / ≤8s）
     → 可投递判定 → 预算扣减 → kf_outbox → send_msg(msgid) → accepted → 等 msg_send_fail
     任一环节不可用 ⇒ 0 条 outbox + 转人工（§1.1.7）
```

### 6.3 转人工

```
判定 TRANSFER_QUEUE：trans(2)（不需要 servicer_userid，MVP 默认）
判定 TRANSFER_AGENT：trans(3) + open_userid（需台账 + 在线校验）
  → 「正在为您转接」必须在 trans 之前用 send_msg 发（占 1 条）
  → trans 返回的 msg_code 语义是「进入接待池/接入后的提示语」，不是「正在转接」
  → 本地 state=3，AI 静默
```

- `msg_code` 约束：进池/接入 1 条 / 48h / 仅文本；结束 1 条 / **20s** / 文本+菜单；code 一次性；
  除「进入会话」外，**仅能在获取 code 的会话状态时发送**；
- MVP 只做 `trans(2)`；指定坐席需 `open_userid` 台账（`servicer_status_change` + 接待人员列表），
  `trans(3)` 前硬校验 `status=1 且 stop_type≠1`，否则 `95014`。

### 6.4 人工结束 → AI 恢复

```
change_type=3 → state=4, close_reason=human_end
客户再发 → state=0 → 按策略 auto_ai / cool_down(N) / manual
```

### 6.5 竞态：AI 生成中被人接管

```
生成前 state=1 → 生成中 change_type=1/2/4 → state=3
  → 发送前 CAS 刷新 state → 非 0/1 → 丢弃（drop_reason=human_takeover）
```

---

## 7. 失败模式与处置（FMEA）

| # | 故障 | 检测 | 处置 |
|---|---|---|---|
| 1 | 验签失败 | 签名比对 | 丢弃 + 告警 |
| 2 | 回调重复 | `msg_signature` 唯一键 | 仍更新 dirty；200 |
| 3 | 回调超时重试 3 次 | 平台行为 | 幂等 + 200 空串 |
| 4 | 回调丢失/网关 5xx | **固定节奏 sync 新鲜度**（>5min 告警） | 增量重拉 |
| 5 | cursor 丢失 | DB 空/报错 | 3 天前重拉，`msgid` 去重 |
| 6 | `sync_msg` 限频 | 错误码 | 退避 + 单 open_kfid 串行 |
| 7 | `event.token` 过期（10min） | 报错 | 无 token 走限频档；**不是** access_token |
| 8 | `access_token` 过期 | `42001/40014` | 提前 5min 预刷 + 重试 1 次（**无 401**） |
| 9 | `send_msg` 状态 2/3/4 | 本地 state + 错误码 | 不发，落 pending_manual |
| 10 | `send_msg` 超时 | 8s | 同一 `msgid` 重试；仍失败记 unknown |
| 11 | `msg_send_fail` `fail_type` | 事件 | 按下表处置 |
| 12 | `has_more=1` 但 `msg_list` 空 | 循环检测 | 推进/退避，最大 20 轮 |
| 13 | 文本 >2048 字节 | 发送前校验 | 按字节截断 + 告警 |
| 14 | 图片入站 >2MB | 收到文本提示 | 引导重发 |
| 15 | 图片出站 >10MB / 非 JPG-PNG | 上传前校验 | 压缩/转码 |
| 16 | `media_id` 3 天过期 | 到期检查 | 重传；失败降级文本 |
| 17 | 语音 AMR 无法识别 | 转码/ASR 失败 | 请客户发文字 |
| 18 | LLM 超时 | 8s | Java 兜底文案 + 转人工 |
| 19 | AI 服务不可用 | 熔断 | 固定话术，不请求 |
| 20 | 工具失败 | 异常 | 告知稍后核实 + 转人工 |
| 21 | 无坐席在线 | `kf_agents` 全 offline | 不转 3；留 1 + 留资 |
| 22 | 排队超时 | 60s | 退回 1（AI）+ 留资 |
| 23 | `95014` | trans 错误码 | 坐席未激活企微 → 指引 |
| 24 | `48001` | 接口错误码 | 渠道 `unauthorized` + 开通指引 |
| 25 | 跨租户越权 | 租户校验 | 拒绝 + 审计告警 |
| 26 | 队列积压 | 深度指标 | 扩容/告警 |
| 27 | 认证过期/授权撤销 | 定时校验 | 渠道 `expired/revoked` |
| 28 | 消息风暴 | 单会话 60s > 10 条 | 合并 + 限流 |

**`fail_type` 全量处置**：

| fail_type | 含义 | 处置 |
|---|---|---|
| 0 | 未知 | 记 failed + 告警 |
| 1 | 客服账号已删除 | **停渠道** + 告警商户 |
| 2 | 应用已关闭 | **停渠道** + 告警 |
| 4 | 超 48h | 关窗口，等客户再发 |
| 5 | 会话已关闭 | 同步 state=4 |
| 6 | 超 5 条 | 停止发送；合并/转人工/等客户下一条（**换卡片无用**，同受 5 条限制） |
| 8 | 主体未验证 | 告警商户去认证 |
| 10 | 用户拒收 | 停该会话自动发送 |
| 11 | 企业无成员登录企微 | 告警：至少一人登录 |
| 12 | 禁发消息类型 | 降级文本 |
| 13 | 安全限制 | 停止发送 + 告警 |

---

## 8. 幂等与一致性

| 层 | 键 | 语义 |
|---|---|---|
| 回调 | `msg_signature`（已覆盖 timestamp+nonce+密文） | 重复只省 payload；**仍置 dirty** |
| 消息 | `msgid`（`sync_msg`） | 重复丢弃 |
| 发送 | `kf_outbox.msgid`（≤32B） | 超时/5xx 用同一 msgid 重试；重复错误视为已受理 |
| 预算 | `session_id` 行内原子更新 | 不超发 |
| 会话 | `kf_session_remote.version` CAS | 单写者 |

**不再假设「`sync_msg` 读不到自己发的消息」**：PR1 用一条真实消息实测（发 1 条 → 立刻 sync）；
可读则 `unknown` 自动对账（同 `external_userid` + 内容 + 时间窗）；不可读则转 `agent_messages.is_internal`
待坐席确认，并保留 `unknown_rate` 告警。

---

## 9. 介入策略（Intervention Policy）

> **命名澄清**：这里的 `TRANSFER_*`/`ESCALATE_HUMAN` 是**通道能力**（交回企微人工接待台），
> **不是** `human_handoff` 工具复活（该工具 2026-09-19 已被用户裁定退场，agent 侧不注册任何转人工工具）。
> 转人工 = 判定器输出 + `service_state/trans`，不经 LLM 工具调用。

### 9.1 判定顺序（短路）

```
1. 硬约束：state ∉ {0,1} → SILENT；预算耗尽 → SILENT；主体未验证 → BLOCK
2. 人工活跃：最近 600s 有 origin=5 → SILENT
3. 明确要人工：关键词/意图 → ESCALATE_HUMAN
4. 高风险：退款/投诉/赔偿/合同/法律 → ESCALATE_HUMAN
5. 情绪 ≥ 80 → ESCALATE_HUMAN
6. 置信度 < 0.4 → ASK_CLARIFY（连续 2 次 → TRANSFER_QUEUE）
7. 连续未解决 ≥ 3 轮 → TRANSFER_QUEUE
8. 非工作时间 → AI_REPLY（留言）
9. 默认 → AI_REPLY
```

### 9.2 LLM 判定器

```json
{"intent":"quote|order|after_sales|complaint|chitchat|spam|other",
 "risk":0,"emotion":0,"wants_human":false,"confidence":0.0,"reason":"一句话"}
```

温度 0；超时 800ms；失败走纯规则；LLM 只判语义，不判权限；结果落 `intervention_decisions`。

### 9.3 判定失败

规则异常 → BLOCK；LLM 超时 → 规则结果；都不可用 → SILENT_WAIT + 告警；降级原因落库。

---

## 10. 回复编排

| 规则 | 说明 |
|---|---|
| 默认 1 条文本 | ≤**2048 字节**（官方硬上限，按字节截断 + 告警） |
| 最多 1 张卡片 | 小程序卡片/图文链接优先 |
| 图片仅在必要时 | 色卡/效果图；多图拼一张；10MB / JPG-PNG |
| 禁止承诺 | 价格区间 + 以量尺为准；时效/折扣/退款过滤 |
| 可追溯 | 带 `knowledge_id` / `tool_call_id` |
| 事件响应消息 | 见下表，**严格 TTL** |

**落地闸门（v1.2，issue #9302；推理链见 §1.1.4）**：

- **先产一条最终正文**：中间过程（「正在查询…」「稍等」）内核侧丢弃、发送边界再兜一层；一次入站至多入队 **1 条**；
- **写动作不上通道**：卡片/确认卡/表单不发；需要写动作的诉求 ⇒ 转人工；
- **数值只能来自工具**：0 次工具调用却报金额 ⇒ 转人工（不许模型编价格/库存/运费）；
- **fail-closed**：生成失败/超时/空/不可投递 ⇒ **0 条 outbox** + 转人工（绝不发半成品或空话）。

**事件响应消息约束（官方）**：

| 场景 | 条数 | code 有效期 | 类型 |
|---|---|---|---|
| 用户进入（欢迎语） | 1 | **20s** | 文本/菜单 |
| 进入接待池 | 1 | 48h | 文本 |
| 从接待池接入 | 1 | 48h | 文本 |
| 结束会话 | 1 | **20s** | 文本/菜单 |

- code **一次性**；除「进入会话」外，仅能在获取 code 的会话状态时发送；
- 超时未发 → 降级（不发/坐席待办），**不要**在异步流水线里等 8s 后再发欢迎语/结束语。

**媒体**：入站下载走 `FileStorageService`（`UploadGuard` 字节级校验）；出站上传企微素材，
`media_id` 3 天有效，剩余 <1h 重传；清理只标记 `expired`，不新增无人值守删除 cron。
**语音**：微信客服是 **AMR**，现有 ASR 不含 AMR → ffmpeg 转 wav；失败请客户发文字。

### 10.1 安全护栏

| 风险 | 护栏 |
|---|---|
| 提示注入 | 客户消息只作 user data；系统提示固定；工具白名单；不执行客户 URL/代码 |
| 乱承诺 | 输出过滤：价格/时效/退款模式 → 改写或转人工 |
| 编造 | 回复带 `knowledge_id`/`tool_call_id`；无来源不输出 |
| PII | 日志脱敏；图片不写日志；`kf_media` 加密 |
| 越权工具 | 按租户开通工具，未开通拒绝 |
| 质量漂移 | 每日抽 20 条人工评；低分进「知识缺口」 |

---

## 11. 多租户与安全

### 11.1 隔离的真实机制（本仓实测）

- **RLS 目前不生效**：`schema.sql` 虽 `ENABLE ROW LEVEL SECURITY`，但全仓无 `SET app.current_tenant_id`、
  无 `FORCE ROW LEVEL SECURITY`，且 `app_user` 是表 owner ⇒ owner 绕过 RLS；
- **真正生效的是 MyBatis `TenantLineInnerInterceptor`**：`tenantId == null` 且非 super_admin → **抛异常**（fail-closed）；
- 因此 kf 表必须**有 `tenant_id` 列**，worker SQL 用 `@InterceptorIgnore` + 显式 `tenant_id`；
- **本 PR 不启用 FORCE RLS**：policy 里的 `current_setting('app.current_tenant_id')` 未带 `missing_ok`，
  GUC 未设置时 owner 查询也会直接报错（现网 RLS 靠 owner 绕过错觉生效）。RLS 待单独 PR
  引入「每请求 SET LOCAL」后再开；在那之前**文档不得声称已有 RLS 隔离**；
- 判据：真 PG 用例「`TenantContext` 空 ⇒ 查 `kf_inbox` 抛」+「A 租户查不到 B 租户行」。

### 11.2 鉴权与 token（三种语义，别混）

| 凭证 | 用途 | 有效期 | 存储 |
|---|---|---|---|
| 回调 `Token` | 回调签名（静态） | 不过期 | `kf_channels.callback_token` / `kf_suites.token` |
| 回调 `event.token` | `sync_msg` 入参 | **10 分钟** | 落 `kf_inbox.payload` |
| `access_token` | 调 kf 接口 | 7200s | Redis 缓存，提前 5min 预刷 |
| `suite_access_token` + `permanent_code` | 第三方换 corp token | suite 级 | `kf_suites` |

- 自建：`gettoken(corpid, corpsecret)`；第三方：`suite_access_token` → `service/get_corp_token`；
- 解密后校验 `receiveid`（自建=corpid / 第三方=suiteid）；
- **加密**：本仓无加密工具、`tenant_apps` 是明文列 ⇒ 新增最小 `SecretCipher`（AES-256-GCM，
  主密钥 env，密文 `v1:keyId:base64(iv|ct|tag)`，支持轮换），不引 KMS。

### 11.3 客户身份与审计

- `external_userid` 按 `corp_id` 隔离；映射到该租户 `customer_profiles`；跨渠道只认手机号，不跨租户；
- 发送、转人工、授权变更、密钥读取落审计日志；
- 保留期默认 180 天，支持导出/删除（法务确认）。

---

## 12. 可观测性

本仓无 metrics 采集端（只有 `health,info,metrics`、无 Prometheus registry、零 `Meter` 使用）⇒
**不纸上谈兵**，分两层：

**① 能判红的 4 条进 `/actuator/health`（`KfHealthContributor`）**：
- 队列积压 > 500；
- `unknown` 未清 > 10min；
- `fail_type ∈ {8,11}` 出现即红；
- 跨租户拒绝 > 0。

**② 其余用只读 SQL 读数**（`deploy/ops/*.sql`）：首响 P95、发送成功率、`unknown_rate`、
转人工率、抢话率、sync 新鲜度（>5min 告警）。按需人工/CRON 读，不进 SLO 门禁。

**对账**：每分钟抽样 1% 活跃会话 `service_state/get`；不做 60s 全量（会打满配额）。

---

## 13. 测试策略

| 层 | 内容 |
|---|---|
| 单测 | 预算扣减、状态映射、`msgid` 重试、去重、介入规则、编排 |
| 真 PG | 预算并发、CAS 单写者、租户隔离、claim 只领 1 条、`SKIP LOCKED` |
| 集成 | `MockRestServiceServer` + 手写企微 XML fixture（无 WireMock） |
| 混沌 | 重复/乱序/超时/断网/cursor 丢失/media 过期/has_more 空列表 |
| E2E | 1 家真实商户全链路 |

**`AI_REPLY` 一跳的判据（v1.2，issue #9302；每条都带红证）**：

| # | 判据 | 执行点 | 红证（改坏 ⇒ 具名红） |
|---|---|---|---|
| 1 | `AI_REPLY` ⇒ `kf_outbox` **恰 1 条**、正文非空、tenant/session 对得上 | `KfAiReplyLoopTest`（真 `KfSendService` + 假 mapper，断言 `enqueue` 调用次数与 parts 文本） | 把 outbox 写入挪出 `KfSendService`（直接调 `outboxMapper.enqueue`）⇒ 该条红 |
| 2 | 生成失败 / 超时 / 空正文 / 中间过程话术 / 无权承诺 / 无工具支撑的金额 ⇒ **0 条 outbox** + `ESCALATE_HUMAN` | 同上 | 把「不可投递 ⇒ 转人工」改成「失败也发兜底话术」⇒ 具名红 |
| 3 | 「客服」单独出现**不升级**；明确索取（人工/真人/动作短语）**必升级**；风险词集合**逐字未变** | `KfDecisionServiceTest` | 把 `HUMAN_REQUEST` 改回 `List.of("人工","真人","客服","转人工")` ⇒ 判据 ① 具名红 |
| 4 | 入站新消息**重置预算窗口**、重放**不重置**、`used<5` 硬上限未放宽 | `KfSessionIngestServiceTest` + `KfSendBudgetMapperTest` | 摘掉「入站重置」⇒ 具名红 |
| 5 | 内核侧 fail-closed：错误事件 / 空正文 / 工具调用 >3 / 超时 ⇒ 判不可用（不产半成品） | `backend/ai-agent-service/tests/test_kf_reply.py` | 让端点在 `type="error"` 时仍返回 text ⇒ 具名红 |
| 6 | worker 侧接线：新消息触发一跳、重复消息不触发、一跳抛错不阻塞游标 | `KfSyncWorkerTest` | 去掉 `replySafely` 的 try/catch ⇒ 游标不前进 ⇒ 具名红 |

**必测 24 条**：1 重复回调只回一次；2 `change_type=4 → state 3` 且 AI 0 发送；3 人工接管 0 发送；
4 生成中被接管 0 发送；5 5 条用尽；6 48h 过期；7 `fail_type=8/11` 告警；8 `fail_type=1/2` 停渠道；
9 图片 2MB 边界；10 AMR 转码失败降级；11 空 `msg_list` 不死循环；12 文本 2048 字节截断；
13 `msgid` 超时重试不重复；14 `unknown` 不重发且率告警；15 人工结束→再发→恢复；16 `change_type=2` 不误判结束；
17 shadow 不发送；18 预算并发不超发；19 会话串行；20 灰度开关；21 欢迎语 20s 过期不发；
22 转人工提示在 trans 前发；23 `48001/95014` 映射指引；24 `TenantContext` 空必抛。

---

## 14. 灰度与上线

| 阶段 | 范围 | 判据 |
|---|---|---|
| 内测 | 1 商户 + 内部 | 全链路、0 重复、0 抢话 |
| shadow | 3 商户（只判不发） | 与人工一致率 ≥85% |
| suggest | 3 商户（草稿） | 坐席采纳率 ≥60% |
| auto | 逐步放量 | 首响/解决率/投诉率达标 |

回滚：租户 `kf_mode=off`；渠道 `status=disabled`。

---

## 15. Runbook

| 场景 | 动作 |
|---|---|
| cursor 丢失 | 置空 → 3 天前重拉 → `msgid` 去重 |
| 积压 | 扩容 kf worker；查 `sync_msg` 限频 |
| `fail_type=6` | 合并未发内容 / 转人工 / 等客户下一条（换卡片无效） |
| `fail_type=8/11` | 认证 / 至少一人登录企微 |
| `fail_type=1/2` | 停渠道 + 商户告警 |
| 发送 unknown | 实测能否 sync 自见；可读则自动对账，否则坐席确认 |
| `access_token` 42001 | 清缓存重取；仍失败查 secret/suite |
| `95014` | 坐席未激活企微 |
| `48001` | 后台「通过API管理」未勾选 / 权限点缺失 |
| 回调 URL 被覆盖（自建） | `channelKey` 校验 + 告警停渠道 |
| 媒体存储满 | 清理 >3 天 `kf_media`；80% 告警 |

---

## 16. 开放问题（需实测/裁定）

| # | 问题 | 验证 |
|---|---|---|
| 1 | 重复 `msgid` 的具体 errcode（文档只说「返回错误」） | 实测一条 |
| 2 | `sync_msg` 能否读到 API 自己发的消息 | PR1 实测 |
| 3 | 回调 query 是否恒带 `nonce`（决定去重键） | 抓一条真实报文 |
| 4 | kf 接口具体 QPM 配额（与 send_msg 共享） | 压测/官方确认 |
| 5 | 第三方 `open_userid` 与自建 `userid` 映射来源 | 文档/实测 |
| 6 | 多客服账号如何路由（门店/品类） | 业务确认 |
| 7 | 卡片跳转目标（商户小程序/我们的 H5） | 业务确认 |
| 8 | 保留期与《个人信息保护法》口径 | 法务确认 |
| 9 | `trans` 目标状态 1 是否允许（实现不依赖） | 实测 |

---

## 17. 实施拆分（PR 计划）

**落地进度（v1.2 现取）**：通道层（`WeChatKfClient` / 回调 / 媒体）、发送层（`KfSendService` / `KfOutboxSender`）、
判定层（`KfDecisionService` + `KfJudgeClient` + 语义判定端点）**均已合并**；**P4 = `AI_REPLY` 一跳**由
issue #9302 落地（`KfAiReplyLoop` + `POST /api/internal/kf/reply` + 判定精确化 + 预算窗口重置）。
剩余：灰度/shadow 档、工作台改造（§18.4）、卡片降级（§18.5.1）。

**PR1 — 契约矫正 + 最小 schema（先不改业务代码）**
- 落 `V217__create_wechat_kf_tables.sql` + `schema.sql`（12 张 kf 表，含 `kf_customer_link/kf_handoff`），
  全部 `tenant_id` + 索引；**不启用 FORCE RLS**（理由见 §11.1），隔离靠拦截器 + 显式 `tenant_id`；
- 两条零成本实测写进 PR body：`send_msg` 能否被 `sync_msg` 读到；回调是否带 `nonce`；
- 先开 issue 拿「转人工命名与 `human_handoff` 裁定」的确认（2026-09-19 裁定不复活工具）。
- 判据：`test_schema_integrity` 绿；真 PG「空租户必抛」「A 查不到 B」。

**PR2 — 通道层（不含 LLM）**
- `WeChatKfClient`（gettoken/sync/send/service_state，单一超时策略）；
- `SecretCipher`（AES-GCM）；
- `KfCallbackController`（验签/解密/inbox/dirty，短事务）+ 端点三处登记；
- 独立 `kfScheduler` 线程池；`SKIP LOCKED` claim 照抄 `ScheduledTaskMapper`（含 `claimed_by` fencing）。
- 判据：手写 XML fixture 验签/解密；`msg_signature` 去重；多实例 claim 只领 1 条；空租户必抛。

**PR3 — 决策与发送**
- `/internal/kf/decide` + `AiAgentClient`（2s/8s、1 次重试、Redis 熔断、Java 兜底）；
- `version` CAS 单写者；预算原子扣减；outbox + sender（`msgid` 幂等、`unknown` 不重发）；
- 判据：预算不超发、`msgid` 重试不重复、人工接管 0 发送、`fail_type` 6/8/11 各自处置。

**不建议现在做**：Kafka/Redis Stream、Prometheus 采集端、KMS、录制回放。

---

## 18. 与现有工作台 / 转人工 / 知识卡的串联

### 18.1 现有资产（直接复用，不另起）

| 资产 | 位置 | 在 KF 链路中的角色 |
|---|---|---|
| `sessions` / `session_messages` | `schema.sql` | AI 会话主线；kf 会话 = `channel='wechat_kf'` |
| `agent_sessions` / `agent_messages` | 同上 | 人工会话；`ai_session_id → sessions.id`，排队/分配/结束/转接全复用 |
| `agent_employees` | 同上 | 坐席在线状态、最大并发 |
| `knowledge_cards` + `/api/admin/knowledge/cards/search` | `KnowledgeCardService` | 知识卡检索（`knowledge_search` 工具） |
| `AgentSessionController` | `/api/admin/agent-sessions` | 列表/详情/分配/结束/发消息/监控 |
| `CustomerAgentSessionController` | `/api/customer/agent-sessions` | C 端查人工会话/发消息 |
| `human-sessions/page.tsx` | admin-web | **在线接待工作台**（真正的人工接待页） |
| `sessions/page.tsx` | admin-web | AI 会话管理（不同页，别混） |

### 18.2 一条会话的主线

```
微信客户
  → KF 回调 / sync_msg
  → sessions(channel=wechat_kf) + kf_session_remote
  → session_messages(role=user)
  → 介入判定 → C 端对话内核（knowledge_search / 算料 / 查单；无 agent 形态）
  → session_messages(role=assistant, metadata.cards=[knowledge_id])
  → kf_outbox → send_msg（msgid 幂等）

转人工：
  判定 TRANSFER_* → 建 agent_sessions(status=waiting, ai_session_id=sessions.id,
                    ai_context_summary/messages = 最近 N 轮)
  → trans(2)（排队）或 trans(3)（指定坐席）
  → 工作台 human-sessions 看到 waiting → assign → trans(3)
  → 坐席在 agent_messages 回复 → kf_outbox → send_msg
  → 客户消息 → session_messages + agent_messages(sender_type=customer) 双写

结束：
  endSession → trans(4) → kf_session_remote.closed_at
  → 客户再发 → epoch+1 新会话 → AI 恢复
```

### 18.3 三套状态的映射（必须唯一口径）

| KF `state` | `agent_sessions.status` | 工作台显示 | AI 可否发送 |
|---|---|---|---|
| 0 / 1 | 无（或 waiting 前的瞬时态） | — | ✅ |
| 2 | `waiting` | 待接待 | ❌ |
| 3 | `active` | 接待中 | ❌ |
| 4 | `ended` / `transferred` | 已结束 / 已转接 | ❌（等新消息） |

**顺序约束**：先建 `agent_sessions`（waiting）→ 再 `trans(2/3)`；`trans` 失败则回滚 waiting 并保留 AI 接待，
不允许「工作台显示待接待、KF 其实还在 AI」的错位。

### 18.4 必须改造的 7 个点

| # | 现状 | 改造 |
|---|---|---|
| 1 | `AgentSessionService.sendMessage` 只写 `agent_messages`，**不推微信** | 写库后若 `ai_session.channel=wechat_kf` → 入 `kf_outbox` 异步发送；接口返回 `accepted/failed`，不阻塞工作台 |
| 2 | `assignSession` 只改本地状态，且**仅允许 `waiting`** | 分配成功后 `trans(3, open_userid)`；**active 会话无法用现有 API 转接** → 新增 `POST /{id}/transfer`（写 `transferred` + 新 `agent_session` 或重分配）并联动 `trans(3)` |
| 3 | `endSession` 只改本地 | 调 `trans(4)`；失败则保持 `active` 并报错（fail-closed），成功才写 `ended` |
| 4 | `createSessionForHandoff` 由已退场的 `human_handoff` 调用 | KF 走**内部转人工端点**（service token），按 `session_id+epoch` 幂等；不复用已退场工具 |
| 5 | 客户消息只进 `session_messages` | 若 `agent_sessions.status=active` → **双写** `agent_messages(sender_type=customer)`，工作台实时可见 |
| 6 | 工作台不区分渠道 | 列表/详情加 `channel=微信客服` 标识 + KF 状态徽标 + `external_userid`（脱敏）+ `scene_param` 归因 |
| 7 | 工作台只能发文本 | 新增「插入知识卡」：`POST /api/admin/agent-sessions/{id}/cards`，服务端解析卡片 → KF 消息 |
| 8 | `transferred` 状态存在但**无转接 API** | 补 `transfer`：`active → transferred` + 新建/重分配 `agent_sessions`；KF 侧 `trans(3, 新 open_userid)` |

### 18.5 知识卡 → 微信客服消息的映射

| 卡片形态 | KF `msgtype` | 规则 |
|---|---|---|
| 纯文本答案 | `text` | `title + answer`，≤**2048 字节**，带「📖 来自本店知识库」 |
| 有落地页 URL | `link` | `title/desc/url/picurl`；URL 加 `kf_click_id` 追踪 |
| 有自有小程序 | `miniprogram` | `appid/pagepath/thumb_media_id`；**需实测**是否要求关联关系 |
| 多张命中 | 只发 1 条 | 其余转「回复关键词查看」，避免吃满 5 条 |

- **可追溯**：`session_messages.metadata` 记 `knowledge_id`/`card_id`；质检可回放「哪张卡被用过」；
- **点击追踪**：link 可加参数；miniprogram 无回传 → 用「发送后是否追问/转人工」估效果；
- **禁止**：卡片 answer 原样超长、承诺类内容未过滤、把「通用建议」标成「本店知识」。

### 18.5.1 C 端对话内核现有卡片的降级矩阵（重要）

> 原名「米宝现有卡片」；C 端已不叫米宝、也没有 agent 形态（§1.1.1），卡片是**内核产物**。
> v1.2 现取：`kf_outbox` 只收 `parts=[{type:text}]`（`KfSendService` 只发文本）⇒ 下表是**将来**要上
> 通道时的降级目标，**当前通道一条卡片都发不出去**（写动作按 §1.1.4 一律转人工）。

微信客服 `send_msg` 只支持 10 种消息：**文本、图片、语音、视频、文件、图文链接、小程序、菜单、地理位置、获客链接**。
C 端内核的富交互卡片**不能原样渲染**，但不是「全废」——按下面降级：

| 内核卡片 | KF 形态 | 保真度 | 说明 |
|---|---|---|---|
| `ProductCard` 商品卡 | 图文链接 / 小程序卡 | 中 | 一条一个商品；横滑多卡 → 文本列表或菜单选类目 |
| `QuotationCard` 报价卡 | 文本明细 + 链接 | 中 | 明细压到 ≤2048 字节；「确认」用菜单消息 |
| `OrderCard` 订单卡 | 文本摘要 + 链接 | 中 | 链接到 H5 订单详情 |
| `LogisticsCard` 物流卡 | 文本（最新节点）+ 链接 | 中 | 无时间轴 UI |
| `ProductionProgressCard` 生产进度 | 文本 + 链接 | 中 | 同上 |
| `PaymentCard` 支付卡 | **图片（二维码）** + 文本 | 高 | 二维码必须走图片上传（10MB/JPG-PNG） |
| `ConfirmCard` 确认卡 | **菜单消息**（确认/取消） | 高 | click 回传需实测；失败降级「回复 1 确认」 |
| `ChoiceCard` 选择卡 | **菜单消息** | 高 | 可点击项 ≤10，总项 ≤50；支持 click/view/miniprogram |
| `QuickActions` 快捷操作 | **菜单消息** | 高 | 同上 |
| `FormCard` 表单卡 | ❌ 不可用 | 无 | 改多轮追问，或发 H5 链接 |
| `KnowledgeCard` 知识卡 | 文本 / 图文链接 | 高 | 带「📖 来自本店知识库」 |

**硬约束**：
- 每条 `text` ≤**2048 字节**；菜单 `head_content` ≤1024 字节、可点击项 ≤10；
- 5 条/48h 预算 ⇒ **一条消息尽量合并多卡信息**，禁止「一卡一条」；
- 无横滑、无折叠、无内嵌按钮、无动态刷新；链接点击与小程序点击**无法可靠回传**；
- 小程序 `pagepath` 需以 `.html` 结尾（官方要求），否则微信内打不开。

**实现**：新增 `KfCardRenderer`（纯函数）：输入 `card_type + data`，输出 `parts[]`（text/link/miniprogram/image/msgmenu）
+ `fallback` 文本；每种卡片一个单测。**Agent 不重写**，只换渲染器——小程序/Web 通道继续用原卡片。

### 18.6 工作台交互（human-sessions）

- 列表：`channel` 徽标、KF 状态、等待时长、排队位；
- 详情：客户 `external_userid`（脱敏）、进入场景 `scene_param`、`ai_context_summary`（已有字段）；
- 回复：文本 + 知识卡插入；发送失败**显式可见**（KF `fail_type` 翻译成人话），输入不丢；
- 结束：二次确认 → `endSession` → `trans(4)` → 20s 内发结束语；
- 转接：`assign` 其他坐席 → `trans(3)` 新 `open_userid`；旧坐席立即失去发送权；
- 坐席离线/挂起：消费 `servicer_status_change` → 更新 `kf_agents.status`，工作台不再派单给离线者。

### 18.7 端到端验收（6 条）

1. 微信问「雪尼尔怎么洗」→ 知识卡命中 → 文本带「📖 来源」→ 客户收到；
2. 客户说「转人工」→ `trans(2)` → 工作台出现 waiting → 接入 `trans(3)` → 坐席回复 → 客户收到；
3. 坐席结束 → `trans(4)` → 客户再发 → `epoch+1` → AI 恢复；
4. 人工接待中（含 AI 生成中被接管）→ AI **0 发送**；
5. 知识卡发送失败（超 5 条 / 媒体过期）→ 工作台显式失败 + 自动降级文本；
6. 坐席 A 转接 B → KF state 3 → B 可发、A 不可发。

**PR 拆分追加**：P6 = 上述 7 个改造点 + 6 条验收；P6 依赖 P2（通道）/P3（发送）/P4（判定）。

---

## 19. 审计补强（v1.2，第三轮）

> 第三轮按「能不能上线」重新过了一遍，补 8 个 P0、8 个 P1。前两轮修的是「会写错」，
> 这一轮修的是「写完也跑不起来 / 跑起来会伤客户」。

### 19.1 P0（不补就上不了线）

| # | 遗漏 | 现状/证据 | 风险 | 补法 |
|---|---|---|---|---|
| 1 | **客户身份没解析** | `sessions.customer_id`、`agent_sessions.customer_id` 均可空；KF 只有 `external_userid`，没有 `customer_id` | 工作台客户名空白、RFM/画像断、跨渠道归并失效 | 新增 `kf_customer_link(tenant_id, corp_id, external_userid, customer_id, first_seen_at)`；首条消息解析：手机号命中 → 绑已有客户，否则建匿名档案；**不跨租户** |
| 2 | **双写方向不全** | `session_messages` 是 AI 主线，`agent_messages` 是工作台主线；人工回复**不写** `session_messages`，客户消息**不写** `agent_messages` | 转回 AI 后上下文缺失；工作台看不到客户新消息 | 定义「**双写 + 去重键**」：`(session_id, source, source_msg_id)`；人工回复同时写 `session_messages(role=assistant, metadata.source=agent)`；客户消息同时写 `agent_messages(sender_type=customer)` |
| 3 | **`open_userid` 无来源** | `agent_employees` 只有 `userId/name/status/maxConcurrent`，**没有企微 userid**；`trans(3)` 必填 `open_userid` | 指定坐席转人工直接不可用 | MVP 只 `trans(2)`；要 `trans(3)` 先做绑定：企微通讯录 `user/get`（需通讯录权限）或坐席 OAuth 登录回填；落 `kf_agents` |
| 4 | **转人工不幂等** | `createSessionForHandoff` 无幂等键；同一 `session+epoch` 重复事件会建多条 `waiting` | 工作台出现重复会话、坐席重复接待 | 加唯一键 `handoff_key = session_id:epoch`（或 `kf_handoff` 表唯一约束）；存在则复用 |
| 5 | **`fail_msgid` 映射缺失** | `msg_send_fail` 事件带 `fail_msgid`；`kf_outbox.sent_msgid` 无索引/映射规则 | 失败事件无法回写，消息永远 `accepted` | `sent_msgid` 建索引；事件到达按 `sent_msgid` 回写 `failed + fail_type`；找不到则记孤儿事件 |
| 6 | **48h 过期不关闭** | 只有「客户再发时惰性分段」；无后台关闭 | 工作台「待接待/接待中」永久挂着，CSAT 不触发 | 惰性关闭 + **每小时**扫描 `last_msg_at < now()-48h` 置 `closed(expired_48h)`；只更新状态，不删除 |
| 7 | **坐席离线无处置** | `servicer_status_change(status=2)` 只在 §18 提了一句 | 客户在人工态发消息没人回，AI 又不能发 | 策略：离线 → 会话回 `trans(2)` 排队 / 通知主管 / 超时回 AI；三种按租户配置 |
| 8 | **新 epoch 未结束旧人工会话** | 客户再发创建新 `epoch`，旧 `agent_sessions` 可能仍 `active` | 工作台两条并存、坐席混乱 | 新 epoch 时强制关闭旧 `agent_session`（`ended`）+ 记 `close_reason` |

### 19.2 P1（不补会伤体验/运营）

| # | 遗漏 | 补法 |
|---|---|---|
| 9 | **客户连发多条**（3 条 → AI 回 3 次） | 1.5–2s **聚合窗口** + 合并成一次回复；窗口内新消息重置计时 |
| 10 | **撤回消息** | 消费 `user_recall_msg`/`servicer_recall_msg`，标记 `recalled`；AI 不引用已撤回内容 |
| 11 | **CSAT 未落地** | `change_type=3` 的 20s code 发满意度菜单（满意/不满意），落 `kf_sessions` 或 `agent_sessions` 扩展字段；进报表 |
| 12 | **转人工摘要谁生成** | 复用现有摘要/提炼能力，在 `createSessionForHandoff` 前生成 `ai_context_summary`；失败则用最近 20 条原文 |
| 13 | **`kf_inbox` 含 PII 无 TTL** | 默认 7 天清理（标记/分区，不做无人值守硬删）；审计需要则延长 |
| 14 | **容量与索引** | `kf_inbox(created_at)`、`session_messages(session_id, created_at)`、`kf_outbox(status, created_at)`、`kf_media(expires_at)`；单企业 5000 客服账号、单账号 2000 接待人员 |
| 15 | **计费/配额** | 按租户统计 AI 调用数、发送条数、坐席数；超限降级（只留人工/只留文本） |
| 16 | **AI 身份与隐私披露** | 欢迎语/首条回复注明「AI 助手」；隐私政策链接；不承诺、不收集无关个人信息 |

### 19.3 P2（工程收尾）

- `KfCardRenderer` 每种卡片一个单测（11 种 + fallback）；
- `kf_suites` 密钥轮换流程（双 key 并存 → 切换 → 下线）；
- `kf_agents` 与 `agent_employees` 定时对账（离线/挂起状态）；
- admin-web 新增 `kfChannelApi` + 类型；工作台渠道徽标；
- 每条用例落 `.github/cases/*.yml` + 测试头 `# case_ids:`；
- `unknown` 自动对账前置实测（发 1 条 → sync 是否可见）；
- 2048 字节按 **UTF-8 边界**截断（不能切半个汉字）；
- 图片 WebP→JPG、超 10MB 压缩；二维码单独走图片；
- 小程序 `pagepath` 以 `.html` 结尾的适配；
- 回调端点三处登记（SecurityConfig / nginx / 测试台账）。

**结论**：补完 19.1 的 8 条，才具备「真实商户跑一周不出事故」的条件；19.2 决定客户体感；
19.3 是合并前的工程卫生。**其中 #1/#2/#3 是新增工作量，不是文档措辞——PR1 必须先把 #1/#4 的表和约束落下来。**

---

## 20. 用户体验：客户侧、坐席侧与失败话术

> 前 19 节解决「能不能跑」，本节解决「客户愿不愿意继续聊、坐席敢不敢用」。
> 原则：**2 秒内必须有反馈；一次只问一个问题；不假装人类；转人工不挽留；结束要体面。**

### 20.1 客户侧（微信里）

| 场景 | 客户感受 | 处理 |
|---|---|---|
| 首次进入 | 不知道对面是 AI 还是人 | 欢迎语明示「我是本店智能客服，随时可转人工」+ 3 个高频问题菜单（20s 内，走 `send_msg_on_event` 不占 5 条） |
| 发了消息没反应 | 以为没人 | 2s 内先回一句「收到，正在为您查询」；仅当工具耗时 >3s 且预算 ≥2 时发，避免浪费 5 条 |
| AI 答非所问 | 烦躁、重复说 | 连续 2 轮未解决 → 主动给菜单「换个说法 / 转人工」，不硬撑 |
| 发图片 | 不知道收到没 | 回「图片收到，正在识别」；>2MB 提示重发；识别失败请描述 |
| 发语音 | 怕白说 | 转文字后复述关键信息；失败请发文字，不猜 |
| 连发 3 条 | 怕被漏掉 | 1.5–2s 聚合窗口，合并成一次回复；不逐条回 |
| 说「人工」 | 怕被机器人缠住 | **立即转**，不说「您先说说问题」；转接中给一句「正在为您转接」 |
| 排队等待 | 不知道等多久 | 「前面还有 N 位，预计 X 分钟」；超 60s 给「留个电话，稍后回电」 |
| 坐席下班/离线 | 等不到人 | 不排队；AI 接待 + 留资，明确告知「人工 9:00–18:00」 |
| 人工接待 | 不知道是谁 | 坐席先自报「我是客服小李」；微信侧无法显示头像，靠文字 |
| 人工结束 | 怕被抛弃 | 结束语 + 「还有问题直接发消息，我会继续接待」；20s 内发 |
| 满意度 | 不想填长问卷 | 一条菜单「满意 / 不满意」，点一下即可 |
| 48h 后再来 | 怕要重新讲 | 新会话，AI 先接；**不假装记得**，可问「还是上次那扇窗吗？」 |
| 5 条用完 | 突然没人理 | 最后一条必须是有用信息（结论/电话/链接），不发「额度用完」 |
| 报价/支付 | 怕被坑 | 只给区间 + 「以实际量尺为准」；二维码走图片；不承诺折扣/时效 |
| 隐私 | 怕信息被滥用 | 不索要身份证/银行卡；手机号仅用于留资，说明用途 |
| 客户骂人 | 更生气 | 先道歉 + 转人工；不辩解、不重复模板 |
| 问「你是机器人吗」 | 信任 | 如实回答，不冒充人工 |
| 广告/骚扰 | — | 不回复，标记 BLOCK |
| 夜间 | 没人 | AI + 留资；不转人工、不让排队 |

### 20.2 坐席侧（工作台）

| 场景 | 坐席感受 | 处理 |
|---|---|---|
| 新会话 | 怕漏接 | 列表置顶 + 未读数 + 5s 轮询；「待接待」按等待时长排序 |
| 抢单/重复分配 | 怕白干 | 现有 `markAssignedIfWaiting` CAS；冲突提示「已被 XX 接手」 |
| 上下文 | 怕客户重复说 | 详情顶部展示 `ai_context_summary` + 最近 20 条；标注「AI 已聊 N 轮」 |
| 发消息失败 | 以为发出去了 | **显式失败 + 输入不丢 + 重试**；KF `fail_type` 翻译成人话 |
| 插入知识卡 | 怕说错 | 搜索卡片 → 预览 → 发送；服务端转 text/link，不贴原始 JSON |
| 转接 | 怕客户重复 | `POST /{id}/transfer`；新坐席看到完整上下文 |
| 结束 | 怕结束错 | 二次确认；先 `trans(4)` 成功再落 `ended` |
| 微信侧状态变了 | 困惑 | 顶部横幅「微信侧已由他人接待/会话已结束」，输入框禁用 |
| 坐席离线 | 会话挂起 | 停止派单；已接待的转排队/通知主管（租户配置） |
| 多渠道 | 分不清 | 列表「微信客服 / 小程序 / Web」徽标 + 筛选 |

### 20.3 失败话术（客户看到 vs 坐席看到）

| 失败 | 客户看到 | 坐席看到 |
|---|---|---|
| `fail_type=6` 超 5 条 | 无感（不发） | 「未发送：已达微信 5 条限制，请合并或等客户回复」 |
| `fail_type=8` 未认证 | 无感 | 「商户未完成微信认证，无法发送，请先去认证」 |
| `fail_type=11` 无成员登录 | 无感 | 「请至少一位同事登录企业微信 App」 |
| `95014` | 无感 | 「坐席未激活企业微信，无法指定接待」 |
| `48001` | 无感 | 「后台未勾选『通过API管理微信客服账号』」 |
| 发送 `unknown` | 可能没收到 | 「发送状态未知，请勿重复发送；已通知技术核对」 |
| AI 超时 | 「稍等，我确认后回复您」 | 「AI 超时，已转人工/已记录」 |

### 20.4 三条硬 UX 约束

1. **不让客户重复说**：转人工必须带上下文；转接必须带上下文；新会话不假装记得。
2. **不浪费客户的 5 条**：能一条说完的绝不发两条；「收到」类 ack 只在必要时发。
3. **不制造假象**：不假装人工、不承诺做不到的事、不显示假的「正在输入」。
