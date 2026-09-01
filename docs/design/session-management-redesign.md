# 米宝（mibao）会话管理与会话状态重新设计

> 版本：v1.1（已评审，决策已确认）
> 日期：2026-08-26
> 范围：`backend/ai-agent-service` — 会话生命周期、跨轮状态、上下文构建（仅 migao 仓库）
> 参考：LangGraph Checkpointer / Store、OpenAI Agents SDK Sessions、Microsoft Agent Framework AgentSession

## 已确认决策（2026-08-26 评审）

| # | 开放点 | 决策 |
|---|---|---|
| 1 | 会话工作状态存储选型 | **方案 A**：PG 行 `session_states` 表（与消息同库、事务一致） |
| 2 | reopen 语义 | **只保留消息历史**，工作状态从空开始（keep_state 默认 False） |
| 3 | 空闲超时判定 | 保留后台轮询，判定改用 `last_activity_at`（替代"最后消息时间 or created_at 回退"），阈值保持 4h 可配置 |
| 4 | ConversationTracker 死路径 | **删除** stage/intent_chain/实体提取死路径（含 `tracker.extract()` 不存在的调用），仅保留测试迁移 |

---

## 一、现状诊断（为什么乱）

米宝的会话管理不是"一个模块"，而是散落在 4 个文件、3 种存储、5 套 Redis key 里的**状态拼盘**。每条用户消息要经过 6 处安全校验、4 层状态读写才能完成一轮对话。

### 1.1 状态存了 4 份，schema 互不相同

同一个"会话状态"被以下四处各自维护，**schema 不一致、TTL 不一致、恢复路径不唯一**：

| 存储位置 | 承载内容 | TTL / 生命周期 | 证据 |
|---|---|---|---|
| PostgreSQL `sessions.metadata` (jsonb) | title、pending_skill、plan_state、vision_analysis 混装 | 随会话行 | `session_memory.py:98, 657, 803` |
| PostgreSQL `session_messages` | 消息历史（追加式） | 随消息行 | `session_memory.py:202` |
| Redis `ctx:{session_id}` | 跨轮实体、tool_results、last_skill、vision_fields | 1 小时 | `context_manager.py:214-215` |
| Redis `ai:tracker:{session_id}` | ExtractedEntities、stage、intent_chain | 30 分钟 | `tracker.py:131-132, 197` |
| Redis `collected_fields:{session_id}` / `auto_interact:{session_id}` | 收集字段 / 防重复 flag | 7 天 / 30 分钟 | `session_memory.py:724, 770` |

同一语义的"实体"在 **3 套 schema** 里各存一份：
- `AgentState.entities`（扁平 str 列表，`base_skill.py:1064-1067`）
- `ConversationTracker.ExtractedEntities`（dataclass，`tracker.py:54-62`）
- `AgentContextManager`（`{type: [{id,name,source}]}`，`context_manager.py:24-28`）

跨轮恢复**没有统一入口**：pending_skill 走 DB metadata、实体走两个不同 TTL 的 Redis key，恢复结果依赖时序。

### 1.2 SessionMemory 是 39 个方法的"上帝类"

`session_memory.py`（1098 行）同时承担五类职责：会话 CRUD、消息存储、标题管理、生命周期（close/reopen/cleanup）、跨轮状态（pending_skill/plan_state/vision/collected_fields/auto_interact）。跨轮状态又拆成 **PG metadata + Redis 两套存储**。

### 1.3 生命周期状态机缺失

- 状态只有 `active` / `closed` 两态（schema 里定义了 `waiting`，代码从不用），无 `expired`、无显式迁移表。
- `close_idle_sessions` 用"最后消息时间或 created_at 回退"判空闲（`session_memory.py:1054-1098`），但 `updated_at` 写语义不一致（pending_skill/plan_state 不更新 updated_at、vision/title 更新），空闲判定被污染。
- **close 后 Redis 状态残留**：`close_session` 只清 collected_fields（`session_memory.py:559`），`ctx:`、`ai:tracker:`、`auto_interact:` 全残留；reopen 不恢复任何状态。关闭的会话带着陈旧跨轮状态被重开。
- 清理靠后台任务轮询（`main.py:35-73`），无事件驱动、无逐会话 TTL 语义。

### 1.4 图状态与持久化脱节

- `AgentState`（18 字段）里**真正跨轮的只有 1 个**（`pending_interact_skill`），`recent_entities`、`cached_answer`、`intent_chain`、`stage` 全是死字段（`state.py`，`graph-state 分析` 证实生产路径零写入）。
- **没有 LangGraph checkpointer**：`builder.py:109` 的 `compile()` 未接任何持久化，跨轮全靠 `_build_initial_state` 手工拼装（`customer_service_agent.py:158-211`），图不可重放、不可恢复。
- pending_skill 的清除靠**字符串关键字匹配**（`base_skill.py:1070-1082` 匹配"创建成功/已取消"），脆弱。
- `nodes.py:462` 就地改 `state.pending_interact_skill` 却不回写 DB → 图内副本与 DB 长期漂移。

### 1.5 API 层重复 + 死代码

- 同一份"get_session + 租户/用户/closed 校验"在 chat.py 复制 **6 处**（send/page/close/reopen/delete/history），错误格式不统一（`make_response` vs 裸 dict 混用）。
- 死代码：`suggestions_node` 已定义未注册；`tracker.extract()` 方法不存在却被调用（`base_skill.py:1048`，异常被吞）；`set/clear_plan_state`、`collected_fields`、`auto_interact` 生产代码零调用方；`_infer_stage` 与 FollowUpSuggestionGenerator 仅测试引用。

---

## 二、主流 agent 做法参考

### 2.1 LangGraph：checkpointer（短时状态）+ Store（长时记忆）

主流 LangGraph 应用把"会话"建模为 **thread**：graph 每次执行携带 `thread_id`，`Checkpointer`（PostgresSaver / MemorySaver / RedisSaver）在每个 super-step 后自动持久化图状态；跨会话的长期记忆放进 **Store**（按 namespace 隔离）。会话恢复 = 用 `thread_id` 重新 invoke，图自动回放。

**对本项目的启示**：`thread_id = session_id`，把 `pending_interact_skill`、实体、意图链等跨轮字段并入图状态由 checkpointer 持久化，删掉手工 `_build_initial_state` 恢复逻辑与散落的 Redis key。

### 2.2 OpenAI Agents SDK：会话 = 消息历史 + 会话状态 分离

OpenAI Sessions 明确区分：
- **conversation history**（消息，追加式、不可变）
- **session state**（agent 可读写的结构化状态，独立于消息）
- 会话带 **expiry（TTL）**，到点自动过期/归档，可显式 `set_state`/`snapshot`。

**对本项目的启示**：`session_messages` 是唯一消息源；跨轮工作状态独立成一份结构化状态（而非塞进消息或 metadata 混装）；每个会话有明确的 TTL 语义。

### 2.3 Microsoft Agent Framework：AgentSession 的命名空间状态

`AgentSession` 保持基类不变，把"可续接的协议状态"按命名空间 key 存入会话对象，消息与状态分离，状态按域隔离（`namespaced keys`）。

### 2.4 共同原则（本次设计遵循）

1. **单一事实源**：消息、会话记录、会话工作状态各一份，其余层只读派生。
2. **状态与消息分离**：消息是 append-only 日志；工作状态是可变的结构化记录。
3. **显式生命周期状态机**：会话有明确状态迁移与 TTL，单一写入者。
4. **上下文构建是管道**：检索 → 裁剪 → 压缩 → 组装，集中一处，可测试，而不是散在 send 流程里。
5. **权限/所有权校验收敛**：一次校验，多处复用，错误格式统一。
6. **持久化由框架负责**：graph 状态交给 checkpointer，业务代码不再手工搬状态。

---

## 三、目标架构

```
┌─────────────────────────────────────────────────────────────┐
│  API 层（chat.py）—— 只做协议转换，不再内联状态逻辑          │
│  · 会话守卫中间件（tenant/customer/status 一次性校验）        │
│  · 端点调 SessionService，不直接碰 SessionMemory             │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  SessionService（新，深模块）—— 会话生命周期唯一写入者         │
│  · create / get / send-gate / close / reopen / expire / purge│
│  · 状态机迁移表：active ⇄ closed（idle 超时与手动 close 同落 closed）│
│  · 保留期语义：closed 保留期→物理清理                           │
└───────────────┬──────────────────────────┬──────────────────┘
                ▼                          ▼
┌────────────────────────┐   ┌───────────────────────────────┐
│  SessionStore（存储适配）│   │  SessionState（跨轮工作状态）   │
│  · sessions 表          │   │  · 独立结构化状态（PG 行 or    │
│  · session_messages 表  │   │    Redis hash），不再混装       │
│  · 消息 append-only     │   │  · entities / pending_skill /  │
└────────────────────────┘   │    stage / vision / last_skill  │
                             └───────────────┬───────────────┘
                                             ▼
┌─────────────────────────────────────────────────────────────┐
│  LangGraph 图（checkpointer = session_id）                    │
│  · AgentState 精简：仅单轮字段 + messages reducer            │
│  · 跨轮字段进图状态，由 Checkpointer 自动持久化               │
│  · 删除 _build_initial_state 手工恢复                         │
│  · ContextBuilder（上下文构建管道）集中注入                   │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 会话生命周期状态机（核心改动）

```
                    ┌──────────────────────────────────────────┐
                    │           Session Lifecycle              │
                    └──────────────────────────────────────────┘

  create ──► active ── idle 超时（默认 4h，可配置）──► closed（自动）
              │  ▲                                          │
              │  │ 用户手动 close / 转人工                  │
              │  └──────────► closed（手动）                │
              │                │                            │
              │                │ 用户 reopen（保留历史）     │
              └────────────────┘                            │
  closed ── 保留期（默认 90d）──► 物理删除                    │
```

> 注：DB `sessions.status` 只有 `active`/`closed`/`waiting`（schema 定义）。「空闲超时」与「手动关闭」同落 `closed`，用 `ended_at` 区分来源；不引入 `expired` 状态（避免与前端/历史 API 的 status 语义分叉）。设计初稿的 expired/purged 已据此简化。

规则：
- **状态迁移表集中定义**（`SessionService.STATE_TRANSITIONS`），任何非法迁移直接拒绝。
- **单一写入者**：只有 `SessionService` 能改 `sessions.status`；API / graph / 后台任务都走它。
- **空闲判定**：用 `last_activity_at`（每轮 send 更新）替代"最后消息时间 or created_at 回退"，语义明确。
- **close/reopen 清理语义**：close 时清跨轮工作状态（Redis hash）；reopen 只恢复消息历史，工作状态从空开始（如需保留，显式参数 `keep_state=true`）。
- **后台任务瘦身**：保留轮询 close_idle，但只调用 SessionService；purge 走同一条路径。

### 3.2 状态分层（三份，各司其职）

| 层 | 存储 | 内容 | 生命周期 |
|---|---|---|---|
| 会话记录 | `sessions` 表 | 身份/租户/用户/渠道/状态/时间戳 + 仅 title 的 metadata | 随会话 |
| 消息日志 | `session_messages` 表 | 全部消息（append-only，含 token_count） | 随消息，purge 时删 |
| 会话工作状态 | 独立存储（新） | entities、pending_skill、stage、vision、last_skill、plan 等 | 随会话，close 即清 |

会话工作状态从 `sessions.metadata` 中**迁出**（metadata 只留 title 等展示字段）；`ctx:`、`ai:tracker:`、`collected_fields:`、`auto_interact:` 四套 Redis key **合并为一套** `session:state:{session_id}`（Redis hash 或 JSON），统一 TTL 与恢复入口。

### 3.3 SessionState：深模块

```python
class SessionState:
    """跨轮工作状态，单一事实源。由 graph 每轮末尾 commit。"""

    entities: dict            # {type: [{id, name, source}]}  ← 统一 schema
    pending_skill: str        # 跨轮锁定 skill
    stage: str                # 对话阶段（若仍需要）
    vision_fields: dict       # 图片识别结果
    last_skill: str           # 上一轮 skill
    plan: dict | None         # P&E 计划（如仍需要）

# 存储适配（唯一实现 = PG 行 or Redis hash，二选一，其余都是假的 seam）
class SessionStateStore:
    async def load(self, session_id) -> SessionState | None
    async def commit(self, session_id, state: SessionState) -> None
    async def clear(self, session_id) -> None
```

- `entities` 统一为 `{type: [{id, name, source}]}` 一种 schema，删除 tracker 的 dataclass 与 AgentState 的扁平拷贝。
- **删除**：`ConversationTracker`（实体/stage/intent_chain 生产路径全是死代码）、`AgentContextManager` 的 Redis 持久化（内存缓存可留，持久化职责并入 SessionStateStore）、`collected_fields`/`auto_interact`/`plan_state` 死代码。
- `get_context_manager().load/save`、`tracker.persist` 等全部收敛到 `SessionStateStore`。

### 3.4 LangGraph checkpointer 接入

- `build_agent_graph` 的 `compile(checkpointer=PostgresSaver(...))`，`thread_id = session_id`。
- `AgentState` 精简为：单轮字段（messages/intent_result/route_decision/final_answer/skill_used/suggestions）+ 从 checkpointer 恢复的跨轮字段。
- `_build_initial_state` 不再手工读 pending_skill；恢复交给 LangGraph。
- **迁移期间兼容**：checkpointer 上线前保留 `SessionState.pending_skill` 读写作为双写窗口（见 §5）。

### 3.5 上下文构建管道（ContextBuilder）

把散在 send 流程与 `base_skill.py:827-853` 里的"历史加载 → 压缩 → 实体注入 → tool 提示 → vision 注入"收敛为一条管道：

```python
class ContextBuilder:
    async def build(self, *, session_id, messages, state: SessionState, skill) -> BuiltContext:
        # 1. 历史窗口：get_history_by_tokens（token 预算）
        # 2. 压缩：超限时压缩早期消息（保留 1 套压缩实现）
        # 3. 实体/vision/last_skill 注入（来自 SessionState）
        # 4. 组装 system prompt 块
```

- 删除 `tracker.compress_history` 与 `context_manager.compress_conversation` 两套并存，保留 1 套。
- 压缩结果**回写**工作状态（`state.summary`），并在下次压缩时读回作为「更早历史」并入输入，形成**滚动摘要**（历史累积不丢，不依赖每轮重压原始消息）。

### 3.6 API 层瘦身

- 新增 `get_guarded_session` FastAPI 依赖：get_session + tenant/customer/status 校验 + `last_activity_at` 刷新，**6 处重复删除**，错误格式统一。
- `SessionService.send_gate(session_id, user, tenant)` 返回 (session, error) 二元组，端点不再自己拼 404/403/409。
- 创建会话与发送解耦：`POST /sessions` 是唯一创建入口，send 无 session_id 时先调 `POST /sessions`（或 `SessionService.create`），不再隐式建。

---

## 四、数据模型变更

```sql
-- 1) sessions：metadata 只留展示字段，状态列语义化
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ;  -- 可选：显式过期点

-- 2) 会话工作状态（二选一）
-- 方案 A（推荐，与消息同库、事务一致）：
CREATE TABLE IF NOT EXISTS session_states (
    session_id VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
    state JSONB NOT NULL DEFAULT '{}',        -- SessionState 序列化
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
-- 方案 B（Redis hash，低延迟，但无事务）：
--   session:state:{session_id}  (hash, TTL = 会话 TTL)

-- 3) 迁移存量数据：把 metadata->'pending_skill' 等迁入 session_states.state
```

---

## 五、迁移路径（分 4 阶段，每阶段 TDD）

> 遵循项目 AI-TDD：每阶段先写测试（FAIL）→ 实现（PASS）→ 全量单测。

| 阶段 | 内容 | 产出 | 关键测试 |
|---|---|---|---|
| **P0 清死代码** | **✅ 已完成（2026-08-26）**：删 `SessionMemory.set/clear_plan_state`（保留 `get_plan_state`，读取路径是活的）、`get/set_collected_fields`（保留 `clear_collected_fields`→P1 后整体删除）、`get/set_auto_interact_flag`；删 `nodes.py: suggestions_node`（未注册）与 `_infer_stage`（零生产调用）；删 `base_skill.py` 的 `tracker.extract()` 死调用（方法不存在）；同步删对应测试。**暂缓**：`FollowUpSuggestionGenerator`（749 行测试覆盖，独立模块，另立任务）。净删 359 行，全量 1941 测试绿 | 依赖面收窄，后续改动可控 | ✅ 现有相关模块用例保持绿；删除后无 ImportError、无残留引用 |
| **P1 状态收敛** | **✅ 已完成（2026-08-26）**：新建 `SessionStateStore`（PG `session_states` 表，方案 A，V12 迁移）+ `session_state_store.py`；`AgentContextManager` 持久化改经 SessionStateStore（合并语义）；`pending_skill`/`vision_analysis` 从 `sessions.metadata` 迁入 SessionStateStore（读双路兼容存量，写清存量防漂移）；`close_session` 清理工作状态；删 `ConversationTracker` 的 Redis 持久化层（`ai:tracker:` key）；四套 Redis key（ctx:/ai:tracker:/collected_fields:/auto_interact:）零残留 | 跨轮状态单一事实源（PG），`sessions.metadata` 仅剩 title | ✅ `test_session_state_store.py`（11 例）+ 改造后相关模块 279 例绿；`grep` 确认四套 Redis key 零残留 |
| **P2 生命周期** | **✅ 已完成（2026-08-26）**：新建 `SessionService`（状态迁移表 `active ⇄ closed` + `can_transition` 校验 + close/reopen/delete/expire_idle/purge/send_gate）；chat.py 6 处重复校验收敛为 `_guard_session`（4 个管理端点）+ `SessionService.send_gate`（send/page，含 last_activity 刷新 + `_raise_session_error` 统一 make_response 格式）；`last_activity_at` 列（V13 迁移 + 存量回填）+ `close_idle_sessions` 改用该列并清理工作状态；main.py 后台任务改走 SessionService；生命周期 SQL 调用全部收敛（grep 零残留） | 会话生命周期单一写入者，守卫一处实现 | ✅ `test_session_service.py`（14 例）+ 改造后 chat/main 测试 137 例绿 |
| **P3 图持久化** | **✅ 已完成（2026-08-26）**：AgentState 精简（删 recent_entities/cached_answer/intent_chain/stage/entities 死字段，18→13 键，含测试改造）；`ContextBuilder` 管道化（压缩单实现：`tracker.compress_history` 迁入并回写 `state.summary`，chat.py 改调）；删 base_skill `get_tracker` 残留；**整模块删除 `app/context/tracker.py`**（P1 删 Redis 持久化 + P3 删 compress_history/get_entities 后生产零调用，37 个测试一并清理，`app/context` 包移除）。**checkpointer：经用户确认不接入**（见下） | AgentState 精简，压缩单实现+回写，tracker 死模块清零 | ✅ 全量 1935 测试绿；被删符号 app/tests 零残留 |

### P3c checkpointer 接入的架构评估（2026-08-26）

设计文档 §3.4 原计划接入 LangGraph Checkpointer（`thread_id = session_id` 自动持久化图状态、删 `_build_initial_state` 手工恢复）。落地评估后发现**与已完成架构冲突**：

1. **消息双写**：当前消息单一事实源是 DB `session_messages`（前端 `/history` API 依赖）。checkpointer 会再持久化一份 `messages`（LangGraph 内部表），且实测**全量传入历史 + checkpointer 恢复会重复**（add_messages 按消息 ID 去重，但 DB 重建的 HumanMessage 无稳定 ID）→ 必须改为"只传新消息、历史靠 checkpoint 恢复"，与 `/history` 数据流分叉。
2. **跨轮状态双写**：P1 已用 `SessionStateStore`（PG `session_states` 表）作为跨轮状态单一事实源，checkpointer 再持久化 `pending_interact_skill` 会重复。
3. **收益有限**：checkpointer 的核心价值（图可重放/恢复）在本架构中已被 `SessionStateStore + SessionService + DB 消息` 覆盖；graph 本身每轮全量重建，无需依赖 checkpoint 恢复。
4. **成本高**：需新增 `checkpoints` 表迁移、lifespan 连接管理、15+ 处测试调用改造（传 config）。

**建议**：不接入 checkpointer，保持"DB 消息 + SessionStateStore 跨轮状态"双表单一事实源；图的可重放由 `_build_initial_state` 从 store 恢复实现（已在 P1 完成）。若未来需要，可作为独立增强另行评估。

**兼容窗口**：P2→P3 之间 pending_skill 双写（`SessionState` + DB metadata），P3 完成删除 DB 侧。

**风险与回滚**：每阶段独立合入，可单独回滚；checkpointer 引入先灰度一个 agent（mibao）验证多轮稳定性再切 xiaobu。

---

## 六、验收标准（已按落地结果修订）

1. 跨轮状态只有 1 个写入点（SessionStateStore，PG `session_states` 表）✅
2. 会话状态迁移只能经 `SessionService`，非法迁移被拒绝且有测试 ✅
3. close 后 Redis 无残留 key（四套 key 已清零）；reopen 语义明确（默认空工作状态）✅
4. API 层会话校验只存在 1 处实现（`_guard_session` + `send_gate`），错误格式统一（make_response）✅
5. graph 跨轮状态可由 `_build_initial_state` 从 SessionStateStore 恢复（代替 checkpointer；checkpointer 经评估不接入，见 §P3c）✅
6. 死代码清零：`grep` 确认被删符号（plan_state 写路径/collected_fields/auto_interact/suggestions_node/_infer_stage/ConversationTracker 模块/AgentState 死字段）无生产引用 ✅
7. 全量单测绿（1935 passed）+ 多轮场景测试通过 ✅
