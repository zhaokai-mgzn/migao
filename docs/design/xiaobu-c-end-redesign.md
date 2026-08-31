# 小布 C 端重构设计：无会话 UX + 上下文自动管理 + AI 验收体系

> 版本：v1.0（待评审）
> 日期：2026-09-01
> 范围：frontend/mini-app（UX 重构）+ backend/ai-agent-service（上下文管理）+ tests（验收体系）
> 背景：用户反馈——当前 UI 不适合 C 端推给用户：会话概念用户不理解不应透出；"我的"页应有订单/售后信息；单会话内上下文自动清理/重置机制是核心难点。

---

## 一、现状诊断（为什么不能直接推给用户）

### 1.1 前端透出了"工程师概念"

| 现状 | 问题 |
|---|---|
| tabBar 3 个：**对话 / 会话 / 我的** | 「会话」是后端术语（session），C 端用户不理解；会话列表页（搜索/删除/新建）是后台管理思维 |
| 进入对话页先 `createSession()` | 用户没有"创建会话"的心智模型，他只想"找小布聊天" |
| 会话列表含「暂无会话记录/开始对话」空态 | 暗示用户需要"管理"对话，而非自然对话 |
| "我的"页只有会话统计（总会话数/本月对话） | 用户关心的订单、售后、物流完全没有入口 |

### 1.2 上下文管理已有基础，但缺"自动清理/重置"设计

已有（[session-management-redesign.md](session-management-redesign.md) 已落地）：
- 会话生命周期状态机（active/closed，SessionService）
- 跨轮实体缓存（AgentContextManager：entities/tool_results/last_skill）
- 对话压缩（>20 条 → 最近 12 条 + 摘要）
- 空闲关闭（4h，后台任务）

**缺口**：所有机制都是"累积式"——实体越积越多（MAX 10 个/类）、tool_results 滑动窗口（8 条）、压缩只按条数不按主题。**没有"主题切换重置""操作完成重置""意图域隔离"**。这正是用户点名的核心难点。

---

## 二、主流 C 端 agent 参考

| 产品 | 会话模型 | 上下文处理 | 订单/售后入口 |
|---|---|---|---|
| **淘宝/天猫客服** | 单会话续聊，无会话列表 | 按订单卡片切上下文；下单后清空购物车草稿 | 对话内订单卡片 + "我的订单"直达 |
| **京东客服** | 单会话，无列表 | 意图切换时旧上下文归档 | 对话内卡片 + 订单/售后 tab |
| **微信小程序客服** | 由微信托管，业务无感知 | — | 会话内卡片 |
| **Coze 扣子客服** | 单会话 + 长期记忆库 | [记忆库](https://docs.coze.cn/guides_long_term_memory)（用户级长记忆 vs 会话级短记忆分离） | 卡片式 |
| **LangGraph/OpenAI Agents** | thread + Store 分离 | [Checkpointer(短时) + Store(长时)](https://github.com/google/adk-python/discussions/3896)（topic switch 不携带旧上下文） | — |

**提炼出的共同模式**：
1. **用户无感知会话**——打开即聊，续聊最近一次，不展示会话列表
2. **上下文分层**——用户级长期记忆（偏好/常购）与 会话级短期状态（当前草稿/待确认）严格分离
3. **主题域隔离**——切域即归档旧域实体（topic-shift reset），而不是无限累积
4. **事务终态重置**——下单/售后完成 = 事务结束，草稿/待确认状态立即清空
5. **时间衰减**——短空闲保留可续聊，长空闲自然遗忘

---

## 三、UX 重构设计（前端）

### 3.1 tabBar：3 tab → 2 tab

```
对话（默认）          我的
┌────────────────┐   ┌────────────────┐
│ 小布            │   │ 头像 昵称 ID     │
│ (最近一次续聊)   │   │ ──────────────  │
│                 │   │ 📦 我的订单      │
│ [消息流]         │   │ 🔄 我的售后      │
│                 │   │ 📚 服务说明      │
│ [输入框]        │   │ 关于/隐私/退出   │
└────────────────┘   └────────────────┘
```

- **删除** `pages/chat/sessions/index`（会话列表页 + tab），app.config 只留 chat + profile
- 对话页顶部：品牌区 + 右侧「🔄 新对话」轻按钮（清除当前草稿，不强暗示"新建会话"）
- 「我的」页顶部：用户信息；中部：**我的订单**（近 3 单卡片，点进订单详情或唤起对话追问）、**我的售后**（工单状态列表）；底部：设置/关于/隐私/退出

### 3.2 无会话 UX 的数据流（前端）

```
进入对话页
  → checkAuth()（静默登录）
  → 调 GET /api/chat/latest          ← 新增：返回最近一个 active 会话（或 null）
    → null  → POST /api/chat/sessions（自动创建，前端无感）
    → 有    → 复用该 session_id（续聊，加载历史消息）
  → 用户点「🔄 新对话」→ POST /api/chat/sessions（新 id，旧会话置 closed）
```

**前端 store 变化**：
- `chatStore` 去掉 `sessions` 列表状态（不再拉取/渲染会话列表），保留 `currentSessionId/messages`
- 新增 `latestSession` 动作：进入页面时拉取续聊，用户无感知
- profile 页去掉会话统计卡片，改为订单/售后入口（拉 `customer_order_query` 结果 + 售后接口）

### 3.3 订单/售后在「我的」页透出

| 区块 | 数据源 | 交互 |
|---|---|---|
| 我的订单（近 3 单） | `GET /chat/orders/mine`（ai-agent C 端端点，转发 `/api/admin/agent/orders/mine`，强制按 X-User-Id 过滤） | 点卡片 → 唤起对话追问进度（闭环在对话里，不另造详情页） |
| 我的售后（近 3 条） | `GET /chat/after-sales/mine`（透传 customerId=当前用户） | 点卡片 → 唤起对话追问工单进度 |

> 订单/售后入口复用 C 端数据隔离端点，天然安全。

### 3.4 新品推荐位（商家显式打标闭环）

用户反馈：即聊页面需要有向用户推荐新品的快捷方式。**完整业务闭环**（商家控制 → C 端展示）：

```
商家端（admin-web 商品管理页）
  → 商品行「推荐/取消推荐」按钮（仅 on_sale 商品可推荐）
  → PUT /api/admin/products/{id}/recommend
admin-api
  → products.recommended 落库（V20260903 迁移 + 索引）
  → 列表查询支持 recommended 过滤；仅上架商品可设推荐
ai-agent-service
  → GET /chat/products/new-arrivals 只查 recommended=true + on_sale
mini-app
  → 空态欢迎屏 NewArrivals 横滑卡片（🔥 新品推荐）
  → 点商品 → 唤起对话询问该商品
  → QuickActions 保留原 4 项（查订单/找产品/退换货/转人工），新品由卡片位承载
```

> 关键设计：**推荐 = 商家显式打标**，不是"最新创建自动取"——后者商家无控制权，且最新创建≠值得推荐。下架商品不可设为推荐（不应出现在 C 端推荐位），已推荐商品下架后自动从推荐位消失（recommended + on_sale 双条件）。

---

## 四、上下文自动清理/重置机制（核心设计）

### 4.1 分层模型：三层上下文，三种生命周期

| 层 | 内容 | 生命周期 | 存储 |
|---|---|---|---|
| **L1 用户级长期记忆** | 偏好（风格/尺寸习惯/常购）、身份 | 永久（可衰减） | `user_memory` 表（已有） |
| **L2 会话级工作状态** | 当前草稿、待确认项、pending_skill、本轮 entities | 随会话（主题切换/事务完成即清） | `session_states` + context_manager |
| **L3 对话历史** | 消息流 | 随会话（滚动压缩） | `session_messages` |

**铁律**：L1 永不因会话清理而丢；L2 是"易失"状态，任何清理动作都先清 L2；L3 只做滚动压缩不删用户可见消息。

### 4.2 四种自动清理触发器（核心机制）

#### T1 主题域切换重置（topic-shift reset）

**问题**：用户先问"查订单"（实体：ORD-A），再问"推荐窗帘"——若 ORD-A 实体残留，LLM 可能把"它"错误指代到订单。

**设计**：引入 **domain epoch（域纪元）** 机制
- `AgentContextManager` 按域分桶：`entities: {order: [...], product: [...], aftersales: [...], general: [...]}`
- 每次意图路由确定 `skill` 时（base_skill 入口），若与 `last_skill` 不同 → **域切换事件**：
  1. 旧域 entities 打 `stale` 标记（不移除，供"我还想问刚才那个订单"回溯）
  2. 新轮 context 注入：`【话题已切换】上一话题（订单域）的上下文已归档；若用户回到原话题，可重新查询`
  3. `build_context` 默认只注入**当前域** entities + 最近 1 个域的 stale 索引（名称级，不带 ID 细节）
- 这样"切域不丢名、不丢语义、只丢精确 ID 依赖"，LLM 被迫重新查询获得最新数据（避免用过期的 ID 操作）

#### T2 事务终态重置（transaction-complete reset）

**问题**：下单流程 pending_skill 靠字符串匹配清除（"创建成功/已取消"），脆弱；下单成功后若用户说"再买一个"，旧商品明细可能残留。

**设计**：引入 **terminal event（终态事件）**
- `ToolResult` 增加 `terminal: bool` 字段；`order_create` 成功、`aftersale_create` 成功、`human_handoff` 成功时置 True
- base_skill 在 tool 执行返回 terminal 后：
  1. 清空该域全部 entities + tool_results + vision_fields（购物车/草稿语义）
  2. 清 pending_skill（结构化触发，替代字符串匹配）
  3. 注入 system 提示：`【事务完成】上一笔订单已提交，以下为新对话`
- 保留 user_memory（L1）：下单完成 → 提取"顾客张三 138xxxx"进用户记忆，供下次"还是老样子"复用

#### T3 时间衰减（idle decay，两级）

| 空闲时长 | 动作 | 效果 |
|---|---|---|
| ≥15 分钟 | 清 L2 工具级状态（tool_results/vision_fields），保留 entities + 历史 | 用户回来可续聊"刚才那个订单"，但工具缓存已失效需重查 |
| ≥4h（已有） | 会话 close；清全部 L2；保留 L1 + 历史 | 续聊只带用户记忆摘要，不带中间状态 |

**实现**：现有 `close_idle_sessions` 后台任务扩展为两级；第一级（15min）由 `touch_activity` 附带检查（发送前懒清理，无需轮询）。

#### T4 显式新对话（user-initiated reset）

- 前端「🔄 新对话」→ 新 session；旧 session close（状态清空）
- 后端同样走 T2 的 terminal 清理逻辑，保证无残留

### 4.3 触发矩阵（汇总）

| 事件 | T1 域切换 | T2 事务完成 | T3a 15min | T3b 4h | T4 新对话 |
|---|---|---|---|---|---|
| 清旧域 entities | ✅ | ✅(本域) | — | ✅ | ✅ |
| 清 tool_results/vision | — | ✅(本域) | ✅ | ✅ | ✅ |
| 清 pending_skill | — | ✅ | — | ✅ | ✅ |
| 注入过渡提示 | ✅ | ✅ | — | — | — |
| 保留对话历史 | ✅ | ✅ | ✅ | ✅(可读) | 分离 |
| 保留用户记忆 L1 | ✅ | ✅ | ✅ | ✅ | ✅ |

### 4.4 后端实现落点

| 文件 | 改动 |
|---|---|
| `app/memory/context_manager.py` | entities 按域分桶 + stale 标记 + `record_domain_switch()` + `reset_domain(domain)` + `reset_session()` |
| `app/tools/base.py` | ToolResult 加 `terminal` 字段（默认 False） |
| `app/tools/order_create.py` | 成功返回 terminal=True |
| `app/tools/aftersale_create.py` | 成功返回 terminal=True |
| `app/tools/human_handoff.py` | 成功返回 terminal=True |
| `app/graph/skills/base_skill.py` | 入口检测域切换（T1）；tool 循环后检查 terminal（T2）；context 注入按当前域过滤 |
| `app/memory/session_service.py` | 加 `decay_tool_state()`（T3a 懒清理） |
| `app/memory/session_state_store.py` | schema 兼容 domain 分桶（若存 PG） |
| `app/api/chat.py` | 新增 `GET /api/chat/latest`（续聊）+ C 端订单入口端点 |

### 4.5 与既有机制的关系

- **不推翻** session-management-redesign 的决策（状态机/合并语义持久化/压缩都保留）
- 压缩（>20→12）是 **L3 层** 手段；本设计新增的 T1/T2 是 **L2 层** 手段，两者正交
- `user_memory` 已是 L1 实现，本设计只补"下单完成→写入用户记忆"的联动

---

## 五、AI 验收体系（三条路径落地）

### 5.1 路径①：local_runner 用 C 端身份

**问题**：现有 runner 请求不带 Authorization → DEBUG 默认 `dev_user`（role=ADMIN）→ 测的是米宝。

**方案**：local_runner 增加 `--persona xiaobu` 模式：
- 新增 fixture 登录：`POST /api/auth/sms/login`（手机号 + 万能码）→ 但该接口只认平台管理员/员工
- **更稳妥**：新增 `POST /api/auth/dev/login`（仅 DEBUG 模式开放）：`{role: "customer", tenantId: 1}` → 签发 customer 角色 JWT
- runner 带 `Authorization: Bearer <customer-jwt>` → 路由到小布，跑 OR-001（查订单）、OR-010（下单）等用例
- 校验点：小布调用 `customer_order_query`（不调 `order_query`）；返回订单只含当前用户（数据隔离）

### 5.2 路径②：`test_xiaobu_acceptance.py`（真实 LLM E2E）

放 `backend/ai-agent-service/tests/e2e/real/`，`case_ids` 引用 OR-001/OR-010/DF-002：

```
用例：C 端查订单（数据隔离验收）
  session 以 customer JWT 创建
  send("查一下我的订单")
  → 断言 SSE tools 含 customer_order_query
  → 断言不含 order_query（物理隔离）
  → 断言 card 事件 type=order
  → admin-api 对照：返回订单全部属于该用户（user_id 匹配）

用例：C 端下单完整链路（事务终态验收）
  send 下单流程 → 断言 order_create 成功 + terminal 清理生效
  → 下一轮 send("那个商品再买一个") 不残留旧明细

用例：主题切换上下文隔离
  send("查订单") → send("推荐窗帘") → 断言第二轮不含订单实体注入
```

### 5.3 路径③：Playwright H5 视觉回归

**前提**：mini-app 有 `build:h5`（Taro → H5），可被 Playwright 驱动（[MUI no-history chat 先例](https://next--material-ui.netlify.app/x/react-chat/material/examples/no-conversation-history/)）。

**方案**：
- 新增 `tests/e2e/specs/xiaobu/`：`xiaobu-chat.spec.ts`（对话 + 截图）、`xiaobu-orders.spec.ts`（订单卡片视觉断言）
- 复用 `tests/playwright.config.ts`（baseURL 指向 H5 服务，如 `localhost:10086`）
- 视觉断言：`expect(page).toHaveScreenshot()` 基线入库 + CI 对比；关键节点截图：空态欢迎屏、订单卡片（订单号/状态 chip/合计金额可见）、"我的"页订单入口
- mock 后端：SSE 事件 mock（`tests/e2e/mocks/`），保证视觉测试确定性（不依赖真实 LLM）

### 5.4 三条路径分工

| 路径 | 验证什么 | 确定性 | 跑在哪 |
|---|---|---|---|
| ① local_runner xiaobu | Agent 行为（工具选择/数据隔离） | 真实 LLM（flaky 容忍） | 本地 + CI（agent-eval.yml 扩展） |
| ② test_xiaobu_acceptance | 行为 + 上下文清理（T1/T2） | 真实 LLM（断言宽松） | 本地 + CI（real E2E 开关） |
| ③ Playwright H5 | **视觉/交互回归**（卡片渲染、无会话 UX） | mock 数据（高确定性） | 本地 + CI（mini-app.yml 或前端 workflow） |

---

## 六、实施顺序（建议）

1. **P0 验收先行**（TDD）：路径③ Playwright H5 视觉基线（先锁"当前 UI 长什么样"，再改 UI 防回归）
2. **P0 后端上下文管理**：T1 域切换 + T2 terminal 重置 + T3a 懒清理（含单测）
3. **P1 前端无会话改版**：2 tab、latest 续聊、新对话按钮、"我的"页订单/售后
4. **P1 路径①+②**：dev login + xiaobu runner 模式 + 验收用例
5. **P2 三把工具全绿 + 契约 + 提交 PR**

## 七、风险与开放点

| 项 | 说明 | 建议 |
|---|---|---|
| dev/login 端点安全 | 仅 DEBUG 开放，需 fail-closed（非 DEBUG 返回 404） | 参照 SERVICE_TOKEN fail-closed 先例 |
| 视觉基线稳定性 | 微信字体/设备差异 → 截图基线漂移 | 用 mock 数据 + 固定 viewport + CI 专用容器 |
| T1 域切换误伤 | 用户"订单→物流"同属 order 域，不应触发切换 | 按 skill 域（order/product/aftersales）而非工具级 |
| latest 续聊并发 | 多设备同时进入 → 两个 active 会话 | 服务端 latest 返回最近 updated，前端幂等 |
