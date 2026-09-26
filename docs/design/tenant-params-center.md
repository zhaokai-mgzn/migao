# 企业参数中心（tenant params center）设计 —— issue #5131

> **性质**：设计文档（口径真值源）。**触发** = 用户 2026-09-22 的两条输入：
> ① 「我建议是**整合到一块**」（配置面散在 6 处）；
> ② 「**我们的配置类页面务必要考虑配置复杂度和用户体验**」。
>
> **裁定**：**D6′ = 方案 A** —— **整合落在「页面 / 信息架构」，存储保持结构化列**（用户 2026-09-22）。
> **规范**：本单从开工起按 `migao-dev-flow` **§22「配置类页面规范」**（v1.47.0）执行。
>
> ⚠️ 引用一律用**仓库相对全路径** + **符号/文本锚点**，**不写行号**（裸 `文件名:行号` 会被
> `Case Trust Gate` 判 `CASE-TRUST-STALE-LINE-REF` 阻塞）。

---

## 1. 问题（照实写，不粉饰）

商家可配的参数今天散在 **6 个页面 / 7 张表**：

| 域 | 落点（页面） | 存储（表） | 可配项 |
|---|---|---|---|
| **算料** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx`（算料配置） | `craft_calc_configs` | **11 个键**（结构化列；`per_fold_single` / `tiers` / `hem_margin` / `oversize_width_threshold` …） |
| **加工费组合** | `frontend/admin-web/src/app/(dashboard)/production/processing-fees/page.tsx` | `processing_fee_combinations` | 每组合一行（`composition_key` → `unit_price` 元/米） |
| **工序路线** | `production/routings`（路线 tab） | `production_route_rules` | 规则行（`trigger_kind` + `action` + `operation`/`after_operation`/`priority`） |
| **工序库** | `frontend/admin-web/src/app/(dashboard)/production/operations/page.tsx` | `production_operations` | 每工序 ×（计件单价 / 必完 / 单位 / 分组 / 停用 / 排序） |
| **特殊选项价** | `frontend/admin-web/src/app/(dashboard)/production/processing/page.tsx` | `production_route_rules.customer_unit_price` | 16 项（元/套） |
| **AI 客服 / 会话** | `frontend/admin-web/src/app/(dashboard)/settings/page.tsx`（AI 客服设置 tab） | `tenant_ai_configs` | ~15 项（欢迎语 / 营业时间 / 自动转人工关键词 / 兜底阈值 / 推荐策略 / 快捷回复 …） |
| **基本设置 / 通知** | `settings/page.tsx`（另两个 tab） | `tenant_ai_configs` + `tenants` | 机器人名称 / Logo / 通知开关 … |

**商家的真实痛点不是「参数太多」**，是这两条（§22 的读数）：

1. **不知道改这个会变什么** —— 算料参数**每一项都直接改米数 = 改钱**；
2. **找不到** —— 同一件事的配置散在两个页面（例：「超高」的阈值在算料配置，
   而「超高」这个特征名进的是**加工费组合** —— 两处相隔两个导航层级）。

---

## 2. 形态（D6′ = 方案 A）：整合落在页面，不落在表

```
┌─ 企业参数中心（新增页 /settings/params）───────────────────────┐
│  [算料] [加工费] [工艺] [接单] [AI 客服] [通知]      ← P1 按域分组      │
│                                                              │
│  算料 · 常用                    （默认展开）                     │
│   ├ 上下卷边 0.3 米            （默认 0.3）      [说明] [去配置]     │
│   ├ 单色每折吃布 0.25 米        （默认 0.25）                     │
│   ├ 超宽阈值 6 米              ⚠️ 未配置（正在用默认 6）           │
│   └ 超高阈值 4 米              ⚠️ 未配置（正在用默认 4）           │
│                                                              │
│  算料 · 高级                    （默认收起）                     │
│   └ 褶倍下限 1.5（护栏：不得低于引擎默认） …                      │
└──────────────────────────────────────────────────────────────┘
```

**存储一字不动**：算料键仍在 `craft_calc_configs` 的**结构化列**（列名 = 引擎配置键，
6 处同源守卫、SQL 可审计全部保留）；其他域各自成表。
中心页只是**统一的读面 + 分组导航 + 每参数说明**。

🔴 **为什么不是键值表**：本仓算料配置**明确选择结构化列**（`V80__create_craft_calc_configs.sql`
的注释登记了理由：列名与引擎配置键逐字同名 ⇒ 读写两侧零映射）。通用 `key`/`value_json` 表会让
「列名 = 引擎键名」这条契约失效，而它正是 `tests/unit_ci_workflows/test_craft_calc_config_contract.py`
6 处同源守卫的**锚**。

---

## 3. §22 七条原则怎么落（逐条，含判据）

| # | 原则 | 本单怎么落 | 判据（可执行） |
|---|---|---|---|
| **P1** | 一处入口，按域分组 | 新增 `/settings/params`，六个域 tab；组内分「常用（展开）/ 高级（收起）」 | 页面存在 + 六个域 tab 可达 + 高级默认收起 |
| **P2** | 每参数三件套 | 把 `craft-calc-glossary.ts` 的 `CALC_PARAM_COPY`（`label`/`hint`/`impact`）**扩成覆盖全部域的单一真值模块** | **键集守卫**：清单里每个键都必须有文案；引擎加键不补文案 ⇒ 红 |
| **P3** | 默认值可见（**租户级 + 逐键**） | 租户级：读面 `source !== 'stored'` ⇒ 逐键标「未配置（正在用引擎默认值）」；**逐键**：`GET …?with_defaults=true` 附 `defaults` + `defaults_source` ⇒ 标「已改（默认 X）」/「默认」 | 未配置的键必须渲染出标记；引擎默认值**取不到**时**显式**显示「判不了」，**不得**画成「就是默认值」 |
| **P4** | 改钱的参数给护栏 + 预览 | 算料域给**算例预览**：复用既有服务端真值（自动特征判定 / 算料试算），**不前端自拼** | 改阈值后预览数字跟着变；预览串**逐字来自服务端** |
| **P5** | 术语可就地查 | 参数旁「说明」锚点到术语条目（复用 `glossaryAnchorOf` / `glossaryTermAnchorOf`） | 锚点 id 存在且唯一（两组同名术语用独立命名空间） |
| **P6** | 变更留痕 | ✅ **已落**（写面，见 §6.3；口径 **B = best-effort**） | 改一个键 ⇒ 恰好一行审计且改前→改后正确；审计写失败 ⇒ 配置照常保存 **且** 失败可观测（日志 + 计数） |
| **P7** | 复杂配置可交给 AI | **本增量不做**（复用 `docs/design/ai-craft-config.md` 阶段 2，另有单） | 见 §6 未实装登记 |

---

## 4. 参数清单（单一真值模块的骨架）

页面与守卫**共读**这一份清单（本模块**不自己判口径**，只描述「有哪些参数、属于哪个域、文案是什么」）：

| 域 | 参数键 | 存储 | 三件套来源 |
|---|---|---|---|
| 算料 | `per_fold_single` / `per_fold_mixed_times` / `margin_single` / `margin_multi` / `min_fullness` / `tiers` / `default_formula` / `hem_margin` / `meters_rounding_step` / `oversize_width_threshold` / `oversize_height_threshold` | `craft_calc_configs`（结构化列） | **已有**：`CALC_PARAM_COPY`（键集守卫已存在） |
| AI 客服 | `greeting_template` / `business_hours` / `timezone` / `auto_handoff_keywords` / `emotion_handoff` / `ai_fallback_handoff` / `ai_fallback_threshold` / `after_hours_mode` / `after_hours_message` / `recommend_strategy` / `recommend_count` / `recommend_trigger` / `quick_replies` / `bot_name` | `tenant_ai_configs` | 本单补（同款三件套） |
| 加工费组合 / 工序路线 / 工序库 / 特殊选项价 / 计件 | **行式配置**（不是标量键） | 各自表 | 本增量**只做「去配置」跳转**，不逐项搬运文案 |

⚠️ **行式配置与标量参数不是一类**（同 §22 P1 的分组理由）：前者是**列表编辑**（组合价、工序库），
后者是**标量表单**。把列表塞进「参数中心」会让页面变成两套交互的杂糅 ——
故本增量对前者**只给入口与一句话说明**。

---

## 5. 交付切分（避免一个大 PR 混合「读面重构」与「写面重构」）

| 增量 | 内容 | 状态 |
|---|---|---|
| **增量 1（PR #5135）** | 企业参数中心页（四域分组 + 算料/AI 客服逐参数三件套 + **默认值可见** + 行式配置入口）+ **§22 P4 阈值试算块**（当前口径 vs 调整后阈值，服务端判定真值、不保存） | ✅ 已交付 |
| **增量 1.5（PR #5140 / `9b4e3a1bd`）** | §22 **P3 逐键「我改过没有」**：读面 `?with_defaults=true` 按需附引擎默认值 | ✅ 已交付 |
| **增量 2（P6）** | §22 **P6 变更留痕**：`tenant_param_audit` + 当前唯一写面的留痕（口径 **B = best-effort**）+ 身份来源 / 「未知 + 原因」 | ✅ 本 PR（**只落写面**，读面见增量 3） |
| 增量 3 | 写面收口（一套 PUT 覆盖六域）+ **把 P4 推广到其余算料参数**（前置：给算料试算端点加 `config` 透传）+ **P6 的读面**（「这个参数被谁改过」的展示） | 后续 |
| 增量 4 | P7 AI 辅助改配置（复用 `docs/design/ai-craft-config.md` 阶段 2） | 后续 |

---

## 6. 未实装 / 边界（照实登记，不粉饰）

1. ✅ **P4 已落**（在增量 1 内）：`OversizeThresholdPreview` 用 `POST /api/admin/orders/auto-features`
   的 **`config` 透传**做「当前口径 vs 调整后阈值」的**双列试算** —— **服务端判定真值**，
   本组件不本地判、不本地拼文案、**不发任何 PUT**（改口径仍走有护栏与 422 逐条理由的既有路径）。
   ⚠️ **但它只覆盖 `oversize_width_threshold` / `oversize_height_threshold` 两个键**：
   算料试算端点（`craftCalcApi`）**不收 `config`**（用的是库里的租户配置）⇒ 其余算料参数
   （每折吃布 / 余量 / 上下卷边 / 进位步长 …）**今天做不到「改前预演」** ⇒
   要推广**必须先给试算端点加 `config` 透传**（属增量 2 的前置）。**不得**把本块说成「所有算料参数都能预演」。
2. ✅ **P3 逐键「我改过没有」已落**（**算料域**，issue #5131 增量 2）：读面
   `GET /api/admin/production/craft-calc-config` **按需**附 `defaults` + `defaults_source`（`?with_defaults=true`）。
   🔴 **默认不带是有意的**：既有调用方（算料配置页）响应**逐字节不变**，也**不新增**
   「读配置要依赖引擎可达性」这条依赖 —— 有配置行的读，值来自库。
   引擎默认值取不到 ⇒ **显式** `defaults_source='unavailable'` + 页面显示「**无法判断哪些参数被你改过**」
   （**不得**把「拿不到」画成「就是默认值」；这条有 Java 与前端两侧测试 + 红证）。
   ⚠️ **边界**：只覆盖**算料域标量键**；AI 客服域那两个字段（名称 / 欢迎语）没有「引擎默认值」这个概念
   （它们是租户文案，不是算料口径）⇒ **不标**。
3. ✅ **P6 变更留痕已落**（**只落写面**；口径 **B = best-effort**，用户 2026-09-26 裁定，见下「A/B 裁定留档」）。
   - **表**：`backend/admin-api/src/main/resources/db/migration/V131__create_tenant_param_audit.sql`
     （同批同步进建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 的终态）。
     **一行 = 一个参数键的一次变更**：`tenant_id` / `param_domain` / `param_key` / `old_value` → `new_value` /
     `operation` + `operation_id` / `actor_id` + `actor_name` + `actor_source` + `actor_unknown_reason` / `created_at`；
     同一次 PUT 的多行共享 `operation_id`（应用侧把同一个 id 打进配置写入的日志行 ⇒ 日志 ↔ 账本可对账）。
     形状**照既有家法**：只追加旁路账同 `worker_report_audits`（V98，含「身份是怎么确定的」那一列）、
     逐键 before→after 同 `agent_batch_items`（V127）。
   - **谁改的**：**复用既有机制**（读 `SecurityContextHolder` 的 `SecurityUser`，与
     `backend/admin-api/src/main/java/com/migao/admin/service/StockLedgerService.java` 的 `resolveOperator` **同源**；
     同源由单测 `actorSourceStaysHomologousWithStockLedgerOperator` 钉住），并**多记一列身份来源**
     （`actor_source`：`security_context` / `unknown`）。取不到身份 ⇒ 如实记 `unknown` + **原因**
     （`no_authentication_context`），**不编用户**、也**不**借用库存账的 `"system"` 冒充归属
     （DB 侧 `ck_tenant_param_audit_unknown` 钉住「未知必带原因」）。
   - **口径 B 的落码**：审计写在 `TenantParamAuditService` 内**吞掉一切 RuntimeException** ⇒ **配置保存照常成功**；
     失败**必须显眼** ⇒ 结构化日志 `PARAM_AUDIT_WRITE_FAILED`（含 tenant / domain / operation / operationId /
     待写行数 / **已写行数** / 异常栈）+ 计数指标 `migao.tenant_param_audit.write_failed`。
     ⚠️ `CraftCalcConfigService.put` 仍**无** `@Transactional`（口径 A 的前提一字未动：本单**不改**事务语义）。
   - 判据：`backend/admin-api/src/test/java/com/migao/admin/service/TenantParamAuditServiceTest.java` 九条 +
     `CraftCalcConfigServiceTest` 的 P6 四条（改一个键 ⇒ **恰好一行**且改前→改后逐值正确 / 审计写失败 ⇒ **保存照常**
     且计数 + ERROR 日志都在 / 422 被拒的写不写行 / 首次保存的改前值为 `null`）。
   - ⚠️ **边界（如实登记）**：① 只覆盖**当前唯一写面** `PUT /api/admin/production/craft-calc-config`（算料域）；
     其余域随**增量 3** 的写面收口接入（表已按 `param_domain` 预留，接域**不需要**新迁移）；
     ② **本单没有任何读面** —— 「这个参数被谁改过」的展示属增量 3；
     ③ 口径 B 的残留：可能出现「改了钱、查不到谁改的」—— 它**不会**让任何门禁变红，
     可观测性只有上面那条日志与那个计数（这是 B 的**已知代价**，不是缺陷被发现后的说辞）；
     ④ 「同一次 PUT 的多行」是**逐条 insert**（各自 autocommit）：极端情况下可能只落一部分 ——
     这些行共享 `operation_id`，且失败日志会报「已写行数」，故**部分落库可被发现**。
4. 🔴 **P7 AI 辅助未落码** —— 归 `docs/design/ai-craft-config.md` 阶段 2，另一单。
5. ⚠️ **行式配置（加工费组合 / 工序库 / 工序路线 / 特殊选项价 / 计件）本增量只给入口**，
   不做统一读面 —— 它们是列表编辑，与标量参数的交互不同类。
6. ⚠️ **只有 P2 的键集守卫是机械判据**，P1/P3/P5 由页面测试钉住；**P6 这一格现有机械判据**
   （上面点名的 Java 测试，含注入式红证），P4/P7 仍是纪律。
7. ⚠️ 本设计**不改任何门禁的通过条件**、**不新增豁免**。
8. 🔴 **附带修复（本 PR 内独立提交，发现即修）**：`CraftCalcConfigService.apply(...)` **漏写三个键**
   —— `hem_margin` / `oversize_width_threshold` / `oversize_height_threshold` 在 `CONFIG_KEYS` 里（`PUT` 缺它们 ⇒ 422）、
   在 `validate(...)` 里被校验，但 `apply(...)` 自 #4528 起只落 8 个键，而 #5133（issue #5130）加键时**没同步加进 apply**
   ⇒ **商家改了这三个参数、接口返回 200、库里一个字都没变**（引擎按旧值算钱），且当时**没有任何东西会因此变红**。
   判据 = `CraftCalcConfigServiceTest#putPersistsHemMarginAndOversizeThresholds`（**改前实测红**：`insert`/`updateById`
   拿到的实体这三个字段仍是旧值/null，响应也回显旧值）；修法是补三行 `setXxx(...)`（**不**新增任何口径）。
   ⚠️ 这条是 P6 的**前置正确性**：留痕记的是「库里真的变了什么」，写面漏写会让账本如实记下「没变」而商家以为改了 —— 两条合起来才是「改了什么 = 记了什么」。

---

## 7. 裁定留档：P6 的 A/B 二选一取 **B = best-effort**（用户 2026-09-26）

**问题的形态**（技术摸底时登记在 issue #5131 评论）：`CraftCalcConfigService.put` **无** `@Transactional`
⇒ 审计写入与配置写入**天然不原子**，只有两个口径可选，必须显式选一个：

| 口径 | 语义 | 代价 |
|---|---|---|
| A · 同事务（fail-closed） | 给 `put` 加 `@Transactional`；审计写不进去 ⇒ **配置也不保存** | 「改了钱却没留痕」不可能发生；**但给钱的写路径新增一个失败面** |
| **B · 尽力而为（best-effort）** ✅ **裁定** | 审计失败只记日志（+ 计数），不影响配置保存 | 钱的写路径零新增失败面；**但可能出现「改了钱、查不到谁改的」** |

**用户裁定（2026-09-26）：取 B。** 理由（逐字口径 → 落码形态）：

1. **这是配置页，不是资金流转** ⇒ **可用性优先**：审计表抖动不该让商家改不了配置；
2. **审计表是主要留痕载体** ⇒ 写入失败**必须以显眼的方式留痕**：
   结构化日志 `PARAM_AUDIT_WRITE_FAILED` + 计数 `migao.tenant_param_audit.write_failed`；
3. **不得静默** ⇒ 吞异常**只能**发生在这一处（`TenantParamAuditService`），且同一段代码里
   必有日志 + 计数 —— 「静默失败」与「大声失败」的差别就是这条判据的落点。

**残留（如实登记，不粉饰）**：B 允许「改了钱、查不到谁改的」这一形态存在，
且它**不会**让任何门禁/探活变红。它的可观测面只有上面那条日志与那个计数 ——
本单**不声称**「变更 100% 可归因」。
