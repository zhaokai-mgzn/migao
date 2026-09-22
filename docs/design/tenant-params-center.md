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
| **P3** | 默认值可见 | 读面显式给 `value` + `default` + `source`（`stored`/`default`），页面标「未配置（正在用默认 X）」 | 未配置的键必须渲染出「正在用默认」标记 |
| **P4** | 改钱的参数给护栏 + 预览 | 算料域给**算例预览**：复用既有服务端真值（自动特征判定 / 算料试算），**不前端自拼** | 改阈值后预览数字跟着变；预览串**逐字来自服务端** |
| **P5** | 术语可就地查 | 参数旁「说明」锚点到术语条目（复用 `glossaryAnchorOf` / `glossaryTermAnchorOf`） | 锚点 id 存在且唯一（两组同名术语用独立命名空间） |
| **P6** | 变更留痕 | **本增量不做**（下一增量：`tenant_param_audit` 表） | 见 §6 未实装登记 |
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
| **增量 1（本 PR）** | 企业参数中心页（四域分组 + 算料/AI 客服逐参数三件套 + **默认值可见** + 行式配置入口）+ **§22 P4 阈值试算块**（当前口径 vs 调整后阈值，服务端判定真值、不保存） | 🔨 本单 |
| 增量 2 | 写面收口（一套 PUT 覆盖六域）+ **把 P4 推广到其余算料参数**（前置：给算料试算端点加 `config` 透传）+ **P6 变更留痕** | 后续 |
| 增量 3 | P6 变更留痕（`tenant_param_audit`）+ P7 AI 辅助改配置 | 后续 |

---

## 6. 未实装 / 边界（照实登记，不粉饰）

1. ✅ **P4 已落**（在增量 1 内）：`OversizeThresholdPreview` 用 `POST /api/admin/orders/auto-features`
   的 **`config` 透传**做「当前口径 vs 调整后阈值」的**双列试算** —— **服务端判定真值**，
   本组件不本地判、不本地拼文案、**不发任何 PUT**（改口径仍走有护栏与 422 逐条理由的既有路径）。
   ⚠️ **但它只覆盖 `oversize_width_threshold` / `oversize_height_threshold` 两个键**：
   算料试算端点（`craftCalcApi`）**不收 `config`**（用的是库里的租户配置）⇒ 其余算料参数
   （每折吃布 / 余量 / 上下卷边 / 进位步长 …）**今天做不到「改前预演」** ⇒
   要推广**必须先给试算端点加 `config` 透传**（属增量 2 的前置）。**不得**把本块说成「所有算料参数都能预演」。
2. 🔴 **P6 变更留痕未落码** —— 今天**没有任何**配置变更审计，改错了无法归因。
3. 🔴 **P7 AI 辅助未落码** —— 归 `docs/design/ai-craft-config.md` 阶段 2，另一单。
4. ⚠️ **行式配置（加工费组合 / 工序库 / 工序路线 / 特殊选项价 / 计件）本增量只给入口**，
   不做统一读面 —— 它们是列表编辑，与标量参数的交互不同类。
5. ⚠️ **只有 P2 的键集守卫是机械判据**，P1/P3/P5 由页面测试钉住，**P4/P6/P7 是纪律**。
6. ⚠️ 本设计**不改任何门禁的通过条件**、**不新增豁免**。
