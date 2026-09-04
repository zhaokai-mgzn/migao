# 双 Agent 记忆功能体系调研与评估报告

> 版本：v1.0（2026-09）
> 范围：`backend/ai-agent-service` — 小布（C 端）/ 米宝（B 端）记忆体系现状评估
> 方法：代码逐文件核实（证据带 文件:行号）+ 主流方案一手文档调研（LangGraph/LangMem、Mem0、Zep/Graphiti、Letta、OpenAI）
> 结论先行：**短期记忆达标不需强化；长期记忆只写不读是最大短板，需优化完善（接线 + 安全防护 + 合规闭环）；偏好读取未接线；语义/程序记忆层空置**

---

## 一、现状盘点（代码事实，全部经主线程核实）

### 1.1 双 Agent 与记忆模块的关系

| Agent | 服务对象 | Skill 域 | 记忆策略 |
|---|---|---|---|
| 小布 xiaobu | C 端消费者 | customer_order/product/quote/aftersales/knowledge + customer_general | **与米宝共用同一套 memory 模块** |
| 米宝 mibao | B 端商家员工 | order/product/aftersales/customer/staff/settings/data + general | 同上，无 agent 维度区分 |

双 Agent 差异仅体现在 Skill 组合与 persona prompt（`agents/agents/xiaobu.py`、`agents/agents/mibao.py`），记忆存储与提取策略完全共享：`user_memories` 表只有 `tenant_id+user_id` 维度，**无 agent_type 列**（`docs/sql/migrations/V20260608__add_user_memories.sql:3-15`）。

### 1.2 声明 vs 实际（memory/__init__.py:4-9）

| 声明层 | 存储 | 实际状态 |
|---|---|---|
| 1. Short-term Memory | PG `session_messages` + `session_states` | ✅ 已实现且较完善 |
| 2. Long-term Memory | PG `user_memories` | ⚠️ **只写不读（半成品）** |
| 3. Semantic Memory | DashVector 向量库 | ❌ 已禁用（RAG 下线，决策 D1，见 `registry.py` `[RAG 禁用]`） |
| 4. Procedural Memory | Tool 执行经验（PG） | ❌ 仅声明，无任何实现 |

### 1.3 短期记忆（会话级）——已实现，质量较高

| 组件 | 职责 | 证据 |
|---|---|---|
| `SessionMemory` | sessions/session_messages 表；token 预算动态加载历史（64K，`get_history_by_tokens`）、token 估算、生命周期 SQL | `app/memory/session_memory.py:294-397` |
| `SessionStateStore` | PG `session_states` 表（JSONB），跨轮工作状态**单一事实源**（entities/pending_skill/stage/vision/last_skill/plan/summary），load/commit/clear 深模块 | `app/memory/session_state_store.py:18-89`；`V12__create_session_states.sql` |
| `AgentContextManager` | 跨轮跨 skill 上下文：实体提取（商品/订单/客户/加工项）、tool_results 摘要、T1 域切换 / T2 事务终态 / T3 空闲衰减清理；持久化经 SessionStateStore | `app/memory/context_manager.py:76-172,389-453` |
| `ContextBuilder` | 历史压缩：>10 轮时对早期消息滚动摘要（摘要回写 state.summary，下次并入输入，历史不丢） | `app/memory/context_builder.py:26-98,112-164` |
| `SessionService` | 生命周期状态机（active⇄closed 迁移表 + 单一写入者）、send 守卫、空闲关闭、90 天清理 | `app/memory/session_service.py:23-124`；后台任务 `app/main.py:38-68` |

注入链路已接通（`app/graph/skills/base_skill.py:921-949`）：域切换记录 → build_context 注入（实体/工具链/话题归档）→ 压缩摘要 → 拼入 system prompt。**这部分体系完整，无需强化。**

### 1.4 长期记忆（用户级）——只写不读，最大短板

**已实现（写入侧）：**
- `UserMemoryManager`：`user_memories` 表 upsert（tenant_id+user_id+key 去重）、importance 0-1 评分、注入阈值 0.5 / LIMIT 20 / 按 importance 降序读取、`format_for_prompt` 分组输出 XML、`decay_importance` 衰减、delete 方法
  - `app/memory/user_memory.py:39-87,89-131,135-252,255-294,298-325`
- `extractor.py`：每轮对话后 fire-and-forget 异步 LLM 提取（短对话跳过、PII 黑名单 + 手机号/邮箱正则过滤）
  - `app/memory/extractor.py:16-34,84-134,137-173`
- 调用链：`chat.py:196-218` → `_extract_memories_async` → `chat.py:671-679`（每轮 send 后 `asyncio.create_task`）

**关键问题（已核实）：**
1. **`format_for_prompt` / `get_important_memories` 全仓无生产调用点**——只有 `user_memory.py` 自身与测试引用（`grep format_for_prompt|get_important_memories` 仅命中 `tests/test_user_memory.py` 与定义处）。**收集却从不注入**，长期记忆形同虚设。
2. **`decay_importance` 无生产调度**（无后台任务调用，仅测试引用）——记忆永不衰减，过期偏好永久残留。
3. **无保留期/删除 API**——用户无法查询/删除自己的记忆，不满足个保法最小化/删除权要求（审计 06 A3 已确认）。
4. **注入安全**：一旦接线，`extractor` 可被诱导存注入文本（审计 07 P1-L9「记忆提取可被诱导植入持久化注入，当前 format_for_prompt 未接线，潜伏」），且 P1-L1 已指出"DB/工具结果/记忆/vision 间接注入数据原样进 prompt 无信任分级"——**接线前必须先做消毒与信任分级**。
5. admin-api 侧只有 entity+mapper（`admin-api/.../entity/UserMemory.java`、`mapper/UserMemoryMapper.java`），**无 service/controller 消费**。

### 1.5 偏好追踪（建议点击）——写入接线、读取未接线

| 方向 | 状态 | 证据 |
|---|---|---|
| 写入 | ✅ 已接线：建议点击 → `PreferenceTracker.record_click` upsert `user_suggestion_prefs`（click_count+1） | `chat.py:1530-1541`；`suggestions/preference_tracker.py:69-119` |
| 读取 | ❌ 未接线：`FollowUpSuggestionGenerator.generate` 生产代码**零调用点**（仅测试引用 `tests/test_follow_up_suggestions.py` 等）；chat.py:662 注释「suggestions 由 LLM 在回复中自然生成，无需在此额外生成」 | `suggestions/follow_up.py:488-580`；全仓 grep 无 graph/api 调用 |

即：用户点击建议的偏好**有收集、无消费**——动态建议生成本可注入 `preference_intents`（`follow_up.py:713-718` 已实现该能力）但从未被调用。

### 1.6 双 Agent 记忆差异化缺失

- 小布（C 端）需要的：消费者画像（风格偏好、预算、常用尺寸、历史订单倾向、复购线索）
- 米宝（B 端）需要的：商家操作习惯（常用功能、处理规则、常用快捷操作、偏好设置）
- 现状：**两者共用同一 extractor prompt 与同一张表**，提取出的画像无法按角色/agent 区分消费，也无 agent 维度检索（`extractor.py:37-56` 的提取 prompt 是通用客服模板）。

---

## 二、主流方案对照（一手文档调研）

| 方案 | 核心机制 | 与本项目关系 | 参考价值 |
|---|---|---|---|
| **LangGraph / LangMem** | Checkpointer（thread 短期快照）+ MemoryStore（namespace 跨线程长期 + 语义检索）+ LangMem `SemanticMemory`/`manage_memory` 自动提取（ADD/UPDATE/DELETE/NOOP）+ 滚动摘要；`focus_memory` 会话开头预取注入 | **项目已用 LangGraph**，本项目手工实现（SessionStateStore）与 Checkpointer 高度同构，但**未用官方能力** | ★★★★★ 零新增组件、namespace 天然多租户；短期记忆可保持自研（P3c 评估已否决 checkpointer 接入），长期记忆可借鉴 MemoryStore 语义检索 |
| **Mem0** | OpenMemory 扁平事实库 + GraphMemory 图谱；提取 → embedding 相似度匹配 → LLM 裁决 ADD/UPDATE/DELETE/NOOP 冲突消解；Qdrant/PGVector 后端；按 user_id 隔离 | 本项目 extractor 只有 upsert-by-key，**无冲突消解**，同义不同 key 会累积膨胀 | ★★★★ 记忆去重/更新语义是本项目缺失的 |
| **Zep / Graphiti** | 时序知识图谱：实体关系边带 `valid_at/invalid_at`，矛盾自动作废旧边；事实锚定对话片段；图谱遍历+语义混合检索 | B 端「商品-规则-商家」关系记忆未来可能需要 | ★★★ 基建重（图库+服务端），适合二期 |
| **Letta (MemGPT)** | core（常驻上下文分块）+ archival（向量外存）+ recall（历史）分层；agent 工具自我编辑记忆 | 与 LangGraph 双 Agent 编排重叠度高，不宜整体迁移 | ★★ 参考「分块常驻 + 外存检索」思想即可 |
| **OpenAI** | Threads/Session 只解决会话窗口（截断/压缩），官方明确长期记忆需外部存储+检索注入 | 佐证「短期窗口 + 外部长期记忆」分层是行业共识 | ★★ 方向验证 |

**行业共识（用于对照本项目）：**
1. 分层：工作窗口（原始消息）→ 滚动摘要 → 向量检索（情景记忆）→ 结构化 profile（语义记忆）→ 图谱（关系记忆，可选）
2. 提取时机：推荐**后台异步**（会话结束 + 关键事件触发），而非每轮同步
3. 记忆去重/更新：用 LLM 裁决 ADD/UPDATE/DELETE，避免越攒越多
4. PII 合规（个保法）：提取前脱敏、敏感字段标签化 + TTL、提供用户查询/删除 API、取得同意
5. 多租户：存储 namespace = tenant_id，检索强制租户过滤
6. 注入方式：核心画像走 system prompt（小而精 ≤10 条）；历史/相关事实走检索注入（top-k + 时效排序）

---

## 三、评估结论

### 3.1 总体判断：需要「优化完善」，无需推倒重来

| 层 | 现状 | 判断 |
|---|---|---|
| 短期记忆（会话级） | 完整：token 预算 + 滚动摘要 + 状态机 + 域清理 | ✅ **达标，不需强化**（已超多数同类项目） |
| 长期记忆（用户级） | 只写不读 + 无衰减 + 无合规闭环 | ⚠️ **最大短板，需优化完善** |
| 偏好追踪 | 写已接、读未接 | ⚠️ 需接线 |
| 语义记忆 | 禁用（RAG 下线） | ⏸ 与记忆体系解耦，恢复时再评估 |
| 程序记忆 | 仅声明 | 🗑 实现或删声明（二选一） |

### 3.2 长期记忆数据质量实证（2026-09 真实库抽样，733 行 / 20 用户）

> 对生产 `user_memories` 表做了全量聚合 + 随机抽样 + PII 专项核查，结论：**当前提取的长期记忆数据质量很低，且存在 P0 级合规问题（PII 明文入库）**——不值得接线，建议停用提取 + 清理存量。

**证据 1：PII 明文入库且过滤实际失效（13.1%，96/733 行）**
- `_filter_pii` 黑名单只有 6 个精确 key（`phone/mobile/address/email/id_card/idcard`），但 LLM 自由生成 key，实测出现 **40+ 种 PII 变体 key** 全部绕过：`customer_phone / order_phone / recipient_phone / phone_tail / phone_numbers / shipping_address / delivery_address / customer_zhangsan_A_phone / new_employee_phone` 等（`extractor.py:17`）
- 手机号正则 `1[3-9]\d{9}` 只匹配纯数字串，`"138****8000"`、`"尾号5678"` 这类描述不匹配
- **铁证：filter 提交于 2026-08-30 08:20（f3467413），但 08-31 仍有 `phone`/`address`/`customer_name` 明文入库**（值含 `138****8000`、`杭州西湖区文三路1号`、`张三`）
- **context 字段明文 PII**：`extractor.py:123` 把 `user_message[:100]` 原样写入 context，实测 `'session=... | user: 张三 13800138000 杭州西湖区文三路1号'`（5 行）——即使 value 被过滤，context 仍明文存手机号+地址

**证据 2：84.7%（621/733 行）是开发/测试噪音**
- `dev_user` 367 行 + `user_admin_001` 208 行 + `user_superadmin` 32 行 + `cust_deepl_eval_01` 8 行 + `cust_reg_001` 6 行
- 真实用户（hash id）仅 112 行（15.3%）；值里含 `E2E测试`、`TEST-CURTAIN-2563`、`test_product_name` 等测试残留

**证据 3：会话态一次性数据被错配为长期记忆（44+ 行）**
- `order_count(160个订单待付款)`、`duplicate_orders(41个相同待付款订单)`、`pending_processing_add(尚未执行)`、`color_removed(藏青被移除)`、`intent(用户想取消订单)`、`ticket_id / refund_tickets / order_status`——全是会话内瞬时状态，注入未来会话即过期/误导

**证据 4：key 语义漂移 → upsert 去重失效（同义多 key 累积）**
| 语义 | 变体 key 数 | 合计行数 |
|---|---|---|
| 尺寸 | window_width/window_height/window_size/curtain_length/curtain_width | 31 |
| 价格 | fabric_price/product_price/price_per_meter/price_target/... | 24 |
| 风格颜色 | curtain_style/color/product_category/curtain_color/... | 26 |
| 订单号 | order_id/order_number/order_no/recent_order_id/... | 21 |
| 用户身份 | phone/customer_phone/recipient_phone/... | 40 |

upsert 按 `(tenant,user,key)` 去重，但 key 由 LLM 自由生成 → 同一事实多 key 全部入库，记忆膨胀 + 注入冗余/矛盾

**证据 5：importance 自评无校准**
- 分布：0.6(325)/0.7(192)/0.5(164)/0.8(35)/1.0(17)——全部由提取 LLM 自评，无验证、无反馈修正；`customer_name=张三` 这类纯 PII 也评 0.6

**质量根因（机制层面）**
1. 提取模型是轻量 suggestion 模型（`factory.py:203-215`：temperature 0.3、max_completion_tokens=200），非专用记忆提取模型
2. 单轮 500 字截断提取（`extractor.py:103-107`），无多轮聚合 → 碎片化、无上下文
3. key 无受控词表（无 schema/枚举），LLM 自由发明 → 语义漂移
4. 无去重/冲突消解（对比 Mem0 的 ADD/UPDATE/DELETE/NOOP 裁决）
5. 无保留期/衰减调度（`decay_importance` 零生产调用）

**结论**：数据质量低 + 合规 P0 并存。之前建议"接线或下线"应更新为——**当前数据不值得接线（接进去只会把 PII 和过期事实注入 prompt），推荐：① 停用提取落库（开关）；② 清理存量（尤其 96 行 PII 与 621 行 dev/test）；③ 未来若重启，先建 key 受控词表 + 专用提取模型 + 会话末聚合 + PII 前置过滤再谈接线**。

### 3.3 业务价值评估（为什么值得完善）

- **C 端小布**：消费者画像记忆是客服体验差异化的核心——「上次看过的遮光窗帘」「偏好简约风」「上次退过货的款」直接影响转化与信任。当前画像提取了却不注入，等于零价值。
- **B 端米宝**：商家操作习惯记忆（常用功能排序、处理规则偏好）可显著降低操作路径成本，且 B 端数据量小、结构化程度高，最适合先落地。
- **合规底线**：`user_memories` 已收集真实用户偏好但无查询/删除接口，个保法合规风险客观存在（审计 06 A3 已列为 P0）。

---

## 四、优化建议（按落地顺序，均遵循 AI-TDD 与 case_ids 铁律）

### P0-1 停用长期记忆提取 + 清理存量（2026-09 数据实证后更新优先级）
> 原 P0-1「长期记忆接线」在数据质量实证（§3.2）后**降级**：当前 733 行数据中 13.1% 含 PII、84.7% 为 dev/test 噪音，**不值得接线**。接线的前提是先解决质量与合规，故顺序调整为：
1. **停用提取落库**（extractor 入口加开关，`chat.py:671-679` 不再调度）——立即止血，合规面归零；未来重启可恢复
2. **清理存量**：删 PII 行（96 行，含 context 字段）、dev/test 行（621 行）、过期会话态行（44+ 行）
3. **若未来重启**（P2 及以后）：先补 key 受控词表 + 专用提取模型（或 LangMem SemanticMemory）+ 会话末聚合 + PII 前置过滤 + importance 校准，再谈接线与注入安全（审计 07 P1-L9 仍适用）

### P0-2 记忆生命周期合规闭环（若保留提取才需要；停用后可简化）
1. `decay_importance` 接入后台调度（`main.py` 已有 `_session_auto_close_loop`，可同批）
2. 新增记忆查询/删除 API（ai-agent 内部接口或 admin-api 侧，遵循 `session_manage` 风格）
3. `user_memories` 90 天保留期清理（对齐 sessions purge 语义）

### P1-1 偏好读取接线
- `nodes.py` 建议生成处（或 LLM 自然生成 prompt）注入 `PreferenceTracker.get_top_intents`（能力已实现于 `follow_up.py:713-718`，只需生产调用）；按 agent 分流（xiaobu/mibao 不同建议域）

### P1-2 双 Agent 记忆差异化
- extractor prompt 按 agent_type 分流：C 端提取「风格/预算/尺寸/复购倾向」，B 端提取「常用功能/处理规则/快捷操作」
- `user_memories` 增加 `agent_type` 维度（或 `key` 前缀 `c_`/`b_`），注入时按 agent 过滤

### P2-1（可选）向量长期记忆
- 评估引入 LangGraph MemoryStore 或 Mem0（Qdrant/PGVector 后端）做语义检索记忆，解决「按相关性召回而非全量注入 top-20」；namespace = `tenant_id` 天然多租户

### P2-2（可选）程序记忆决策
- Procedural Memory 若无落地计划，删除 `memory/__init__.py:8` 声明，避免文档失实（对齐 RAG 下线处理方式）

---

## 五、证据索引

| 事实 | 证据 |
|---|---|
| user_memories 表结构（无 agent_type） | `docs/sql/migrations/V20260608__add_user_memories.sql:3-15` |
| format_for_prompt 无生产调用点 | `grep format_for_prompt` 仅命中 `user_memory.py` 定义 + `tests/test_user_memory.py` |
| 记忆提取链路 | `chat.py:196-218`（_extract_memories_async）、`chat.py:671-679`（fire-and-forget） |
| 提取 prompt 通用无 agent 分流 | `extractor.py:37-56` |
| 偏好读取未接线 | `grep FollowUpSuggestionGenerator` 生产代码零调用；`chat.py:662` 注释 |
| 偏好写入已接线 | `chat.py:1530-1541` |
| 短期记忆注入链路 | `base_skill.py:921-949` |
| 生命周期后台任务 | `main.py:38-68` |
| 审计佐证（A3/P1-L9） | `docs/audit-2026-08/06-open-source-production-gap-analysis.md:81`、`docs/audit-2026-08/07-security-and-llm-attack-audit.md:109` |
| 会话重构设计（P1-P3 已完成） | `docs/design/session-management-redesign.md:245-268` |
| 主流方案一手文档 | `/tmp/agent-memory-research.md`（LangGraph/LangMem、Mem0、Graphiti、Letta、OpenAI 官方链接均已验证） |

---

## 六、实施记录（issue #2815，2026-09）

> 决策：**C 端（小布）启用长期记忆；B 端（米宝）本期不落库**。复用 `user_memories` 表加 `agent_type` 列。全部改动经 AI-TDD + `case_ids:`（CH-024/CH-025/MC-013/MC-014/MC-015）+ 三把工具预检。

| 项 | 落地内容 | 证据/验证 |
|---|---|---|
| 数据层 | `user_memories` 加 `agent_type`（默认 xiaobu）+ 索引；存量清理 733→76 行（PII 96 行 + dev/test 621 行 + 会话态 44 行全删，备份表可回滚） | `docs/sql/migrations/V20260904__add_agent_type_to_user_memories.sql`；`scripts/cleanup_user_memories.py`（dry-run 默认） |
| extractor | C 端受控词表 `CEND_MEMORY_KEYS`（12 画像字段，词表外 key 丢弃）+ PII 变体词根过滤（40+ 变体）+ `agent_type` 分流（mibao 不提取）+ context 去 PII（不再写原始 user_message）+ 会话末聚合（`extract_and_accumulate` 按 key 合并 → `flush_memories` 会话关闭落库） | `app/memory/extractor.py`；`tests/test_memory_extractor.py`（33 例，case MC-013/MC-014） |
| user_memory | upsert/batch_upsert 带 `agent_type`（参与去重）；get_important_memories/format_for_prompt 支持 `agent_type` 过滤；`format_for_prompt` 注入消毒（XML 转义 + 截断 + 去控制字符，审计 07 P1-L9）；新增 `get_all_memories`/`delete_all`（合规） | `app/memory/user_memory.py`；`tests/test_user_memory.py`（24 例） |
| 注入接线 | `base_skill._inject_user_memories`：仅 xiaobu 在 identity_prefix 后注入消毒后的 `<user_memories>` 块；chat.py 每轮传 `agent_type` | `tests/test_memory_injection.py`（4 例，case CH-024） |
| 合规 API | `GET /api/chat/memories`（查询权）+ `DELETE /api/chat/memories`（删除权），仅本人 tenant+user | `app/api/chat.py`；`tests/test_memories_api.py`（6 例，case MC-015） |
| 会话末聚合挂载 | close_session / close_idle_sessions / delete_session 前 `_flush_pending_memories`（候选落库后再清状态） | `tests/test_session_memory.py`（含 flush 断言） |
| 下单地址自动填充 | admin-api `OrderListResponse` 增 `customerAddress`（BeanUtils 自动复制）；新增 `customer_address_query` 工具（C 端只读，调 `/orders/mine` 取最近订单地址）；customer_order_skill 下单流程先查历史地址 → form 预填 value → 用户确认/修改 | `tests/test_tools_customer_address_query.py`（7 例，case CH-025）；`AgentOrderControllerMineTest` 增 customerAddress 断言 |
| 场景调研 | 6 个记忆主动提示场景清单 + 地址预填详设（数据源优先级/掩码/回写确认/多地址策略） | `/tmp/c-end-memory-scenarios.md`（微信官方文档与合规来源已验证） |

**后续可选项**（本次未做，供排期）：
- `decay_importance` 接入后台调度 + 90 天保留期清理（P0-2）
- 偏好读取接线（`PreferenceTracker.get_top_intents` → 建议生成，P1-1）
- 向量长期记忆（LangGraph MemoryStore / Mem0，P2-1）
- B 端记忆启用（agent_type='mibao' 词表 + 分流开关打开）
