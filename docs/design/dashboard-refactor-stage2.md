# 经营看板重构 · 第二阶段设计与实施清单（指标扩充 + 可插拔）

> 状态：**设计已定，实施待下一单**（本文件随 PR #5793 落地）。
> 上游：`docs/design/dashboard-as-is-inventory.md`（现状盘点，随 #5788 合并）；
> 本轮已修 3 处客观缺陷（见 issue #5792 / PR #5793）。
> 角色：本文是**规格**（口径 + 判据），实施时按它写代码；口径若与本文不符，以**人类最新裁定**为准。

## 1. 决策记录（口径裁定）

用户 2026-09-29 指示「需要我裁定的部分，我觉得你自己先拍一个版本即可」⇒ 以下为本 Agent 拍定的版本，
**未经人类逐条否决即按此实施**；每条都写明「代价」，便于事后回溯。

| # | 事项 | 拍定版本 | 代价 / 理由 |
|---|---|---|---|
| 1 | 「今日销售额 / 客单价」是否含未付款、已取消单 | **只算四态** `confirmed/producing/shipped/completed`（与「本月销售额」同口径） | 数字变小但**同页可解释**；若人类更看重「下单即算」，则「本月」必须同动（两侧不得再分叉） |
| 2 | 「待发货」卡计数含 `producing` 而下钻只筛「待发货」 | **以计数为准，改下钻链接**（筛「待发货 + 生产中」） | 保住卡片语义；改文案更省事但会让「待发货」名不副实 |
| 3 | 环比分母为 0 一律显示 0% | **显示「—」+ 悬停「无上期可比」** | 0% 与「无上期」不可区分，会被读成「与上期持平」= **误导** |
| 4 | 失败态与空数据不可区分 | **显式区分**：接口失败 ⇒ 该区块「数据加载失败 · 重试」并**保留上次成功值**；空数据 ⇒ 保留现有空态 | 加了指标后，「接口挂了」被画成「今天没单」会直接影响决策 |

> ✅ **已实装**（2026-09-29，本 PR）：看板 `blockErrors` 分块标记 + `role="alert"` 告警条（`data-testid="dashboard-load-failed"`）
> + 「只重试失败项」；两条判据（显式告警 / **失败不清零**）均带**注入式红证**（去掉标记 ⇒ 2 failed；改成失败即清零 ⇒ 1 failed）。
| 5 | 首屏补哪些指标 | **先补 4 个「后端已算好/已实现但看板没用」的**（见 §3） | 前三个零或极低后端成本；第 4 个组件已写好但从未接线 |
| 6 | 应收 / 毛利 / 产能交期 | **本阶段不做** | 涉钱口径（应收按订单还是按收款、毛利含不含加工费）必须真裁定 |

## 2. 可插拔机制（用户 2026-09-29 追加要求）

用户原话：「**AI 接待占比这个需要设计成可插拔的，未来有部分企业可能未购买智能客服**」。

### 2.1 复用本仓**现成**范式，不新造机制

`GET /api/auth/me` 已经下发 **`capabilities` 能力位**（现仅 `mibaoChat`）：

- 单一真值在**服务端**（`AuthService.capabilitiesOf` → `AdminGate.canSummonMibao`）；
- 端侧**只消费布尔位、不自己判权限码**（见 `frontend/admin-web/src/components/business/MibaoAccessGate.tsx`）；
- 前端类型已就位：`frontend/admin-web/src/types/index.ts` 的 `capabilities?: { mibaoChat?: boolean }`。

### 2.2 落地口径

### 2.3 🔴 未决缺口（实施前必须先定，2026-09-29 实作时发现）

**「该企业是否启用智能客服」在本仓目前没有真值源** —— 实测：

- `tenants` 表**没有** `ai_service_enabled` 之类字段（只有 `briefing_enabled` / `notification_enabled` 两个先例）；
- 全仓 grep `ai_service|aiService|agent_enabled|customer_service_enabled` 在 admin-api 与建库脚本里**零命中**；
- 现有相关的只有**权限码**：`agent:session`（会话读）/ `agent:session:manage`（写）。

⇒ 因此 `capabilities.aiService` 的**判定依据必须先裁定**（三选一，各有代价）：

| 方案 | 判定 | 代价 |
|---|---|---|
| A. 企业级新开关 | `tenants.ai_service_enabled`（迁移 + 设置页开关），与 `briefing_enabled` 同范式 | 最正确、可运营；代价 = 迁移 + 设置页 + 控制台（**超一个包**） |
| B. 按**租户**派生 | 租户下**任一岗位**持有 `agent:session` ⇒ true | 零迁移；但「岗位权限配置」同时决定两件事（授权与产品可见性），且新租户默认无该码时卡片全不显示 |
| C. 按**当前用户**派生 | 我是否持有 `agent:session` | 最省事；但**把「企业有没有买」退化成「我有没有权」** —— 无该码的老板将看不到 AI 接入情况，与「经营看板给决策者看」的初衷冲突 |

**本 Agent 建议 A**（语义最准、可运营、可审计），但它超一个包；若本阶段要零迁移，则退 B（**不得**用 C）。

1. **新增能力位** `capabilities.aiService`（服务端判定「该企业是否启用智能客服能力」；
   判定依据必须落成**一处**，且与既有 `agent:session` 等码的关系写明 —— 建议：
   企业级开关（若人类裁定要独立开关）或按「是否持有智能客服相关码」派生，二选一，**不得两处各判**）。
2. **看板指标卡改为注册表**：每张卡声明 `requires?: CapabilityKey`；
   渲染时按能力位过滤。
3. **未购买 ⇒ 卡片不渲染**（**不是**渲染成 0、**不是**空白占位）——「插拔」是数据驱动的，不散落 `if`。
4. **判据**：
   - `capabilities.aiService === false` ⇒ 该卡**不在 DOM 里**（断言 `queryByTestId` 为 null）；
   - `true` ⇒ 卡片在且数字来自服务端字段（不得前端硬编码 0）；
   - **反向自证**：能力位缺失（`undefined`）时的行为必须**显式**定义（建议按 `false` 处理并在判据里断言）。

## 3. 首屏要补的 4 个指标（本阶段范围）

| 指标 | 后端现状 | 前端要做的 | 判据要点 |
|---|---|---|---|
| **待支付订单数** | ✅ **已交付**（PR #5802）：`/stats` 增 `pending_payment_orders` 聚合 FILTER | 第 4 张卡 + 下钻 `/orders?status=pending_payment` | 数字来自聚合 FILTER |
| **超时工单数** | `/briefing/snapshot` 已算 `overdue_tickets`（`pending/processing` 且 `deadline` 已过） | ⛔ **被前置条件挡住**：`after-sales` 页**不支持任何筛选参数**（全页无 `searchParams`）⇒ 做下钻卡会立刻制造一个新的「计数与下钻不一致」缺陷 | 需先给 after-sales 页加筛选能力（跨模块） |
| **AI 接待占比** | `/stats` 已返回 `aiSessionRate`（另有 `activeSessions`） | 新卡；**必须可插拔**（§2：`capabilities.aiService`） | 未购买 ⇒ 卡不渲染；已购买 ⇒ 数字来自 `aiSessionRate` |
| **订单状态分布图** | `GET /api/admin/dashboard/order-status` + 组件 `frontend/admin-web/src/components/dashboard/OrderStatusChart.tsx` **都已写好**，从未被任何页面引用 | 接线即可（组件已是死代码） | 逐状态计数与后端一致；空态与失败态按 §1-4 区分 |

## 4. 实施顺序（下一单）

1. **先红**：为 §3 四个指标各写「会红」的判据（含「未购买 ⇒ 卡不渲染」那条）+ §2.2 的能力位判据；
2. 后端：`capabilities.aiService`（单一真值）+ 超时工单读面（择一后不再二算）；
3. 前端：指标卡注册表 + 4 张卡 + 失败态显式化（§1-4）；
4. 口径改动（§1-1 / §1-2 / §1-3）与指标扩充**同批**——它们都改同一批数字，分批会让商家看到两次变化；
5. 门禁：`verify-all.sh gate` + `check-ui-regression.sh` +（跨端）`contract-check.sh`；
6. PR body 必须写明「改前/改后数字差在哪」+ 固化声明。

## 5. 边界（如实登记，不在本阶段射程）

- **应收 / 毛利 / 成本 / 产能 / 交期**：需新建聚合与涉钱口径裁定（§1-6 明确不做）。
- **`product_return_stats`（按商品退货率）**：简报快照已算好，但上不上首屏属产品取舍，本阶段不接。
- **`/dashboard` 根路径重定向**：仓库路由树里没有根 `page.tsx`，部署层是否有 `/` → `/dashboard` 未验证（盘点文档 §8 已登记）。
- **前端 DTO 缺字段**：`/briefing/today` 的响应含 `sourceSnapshot`，而前端 `TodayBriefingResponse` **没有该字段**
  ⇒ 前端结构性拿不到快照（盘点文档 §7 已登记）；若 §3 选择复用快照端点，需同批补类型。
