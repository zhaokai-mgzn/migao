# 算料口径与布料基础路线 —— 全链路方案（包 D / E / F）

> **状态**：设计稿（已获用户口径，可开工）。**基线**：`origin/main`（#4524 之后）。
> **与 `processing-fee-and-option-pricing.md` 的分工**：那份管「**对客计价**」（组合价目 + 特殊选项按套）；
> 本份管「**用料计算**」与「**工序路线（布料）**」。两者共用同一个组合键与同一份 `processing_info`，但**不重叠**。
> **本轮范围**：只改 web + 后端确定性层；**agent 的 prompt / 技能 / 工具定义 / graph / 引导流程一字不动**
> （用户裁定 2026-09-19：「当前会话都不要动 Agent 代码，先把 web 功能做成熟」）。
> 相关：`position-instance-routing-model.md`（工序/路线/部位）· `craft-routing-customization.md` · 真值源 `curtain-production-rules.md`。

---

## 0. 一句话结论

```
用料(米) = 公式(每片宽 = 成品宽 ÷ 开数, …) × 开数        ← 结果**向上进位到 0.1**
公式按**工艺**推导：韩褶 → 韩褶公式（褶数法）· 打孔 → 倍数法（默认 2 倍）· 缺省 → 韩褶公式
公式参数（每折吃布 / 余量 / 档位倍数 / 卷边 / 门幅缺省…）**租户可配**，现有常量 = 默认值

布料单（`saleForm = 布料`）工序 = 「**配料** → **打包**」（追加裁定，issue #4529 第 3 条评论）；每租户默认**两条**基础工序路线：
`窗帘工序路线（默认）` + `布料工序路线`
```

---

## 1. 裁定（R1~R9）

| # | 口径 | 来源 |
|---|---|---|
| **R1** | **公式吃「每片宽」（成品宽 ÷ 开数），总用料 = 每片用料 × 开数** | 用户（三选一选「乙」） |
| **R2** | 用料米数**向上进位到 0.1**（`ceil(x*10)/10`） | 用户（三选一选「向上进位」） |
| **R3** | **公式按工艺推导**：韩褶 → 韩褶公式（褶数法）· 打孔 → 倍数法（**默认 2 倍**）· 缺省 → 韩褶公式 | 用户 |
| **R4** | 公式参数**租户级可配**；现有常量 = 默认值 | 用户 |
| **R5** | 布料单**只有一道工序「配料」**，且要在**工序表**中定义 | 用户 |
| **R6** | 每租户默认**两条**基础工序路线：一条**窗帘**的、一条**布料**的 | 用户 |
| **R7** | 「布料」作为**第 4 个部位**（部位价目表 84 → ~~**116 行**~~ ⇒ **落地值 = 120 行**，**行数现取、本文不写死**，逐行显式；见下方「口径订正」注） | 用户（三选一选 A） |
| **R8** | 「配料」工序：**单位 = 米**、**计件单价留空（NULL）+ `source='待确认'`**，商家自配 | 用户（三选一选 A） |
| **R9** | `curtain_calc.py` / `routing.py` 视为**确定性核心**，本轮**放开可改**；prompt / 技能 / 工具定义 / graph / 引导流程**一字不动** | 用户（两轮澄清均选 A） |

> 🔴 **口径订正（issue #4751，2026-09-20）**：R7 原写「部位价目表 84 → **116 行**」。
> **① 当时基线**：**84 → 116**（= 设计稿的**预估**；`84` = V71 终态、`116` = 预估的「84 + 32」）。
> **② 后来变了**：关联 #4529 的 PR #4553 **落地实测 = 120 行**（`84 + 36`；该 PR 的提交信息逐字写着
> 「同步注释/文档字符串里的矩阵行数（**84→120**）」）⇒ **R7 / §5 分包表 F 行的 `116` 未随之更新**，
> 属**设计稿预估值 vs 落地值**的漂移（同文 §4.3 的 120 行已在 #4553 同步，故文内**自相矛盾**）。
> **③ 故改为 Z**：**不写死**，改为「**现取 + 复算命令**」（三条命令互为交叉校验）：
>
> ```bash
> # ① 真值源（Python）：`_POSITION_PRICE_ROWS` 的元组行数
> awk '/^_POSITION_PRICE_ROWS/,/^\]/' backend/ai-agent-service/app/production/routing.py | grep -c '^    ("'
> # ② 迁移链终态（V71 建 84 行 + V79 补 36 行；V88 是软删 `deleted=1`，不减总行数）
> git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | awk '/INSERT INTO production_operation_positions/,/;/' | grep -c "^  ('"
> git show origin/main:backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql | awk '/INSERT INTO production_operation_positions/,/;/' | grep -c "^  ('"
> # ③ 开租播种终态（bootstrap）：同一张表的 INSERT 行数
> awk '/INSERT INTO production_operation_positions/,/;/' docs/sql/schema.sql | grep -c "^  ('"
> ```
>
> （本单实测：① = **120**、② = **84 + 36**、③ = **120** ⇒ 三源一致，**120** 是当前总行数。）
> ⚠️ **口径提示**：`V88` 之后「矩阵行数」与「**生效**格数」**不再相等**（V88 软删 `配料 × 4 部位` +
> 其余布料格共 31 格，但 `deleted=1` 仍在表里）⇒ 引用「多少行」时**必须说清是哪一种**
> （`总行数` / `生效行数` / `applicable=TRUE` 行数）。本设计 R7 指的是**总行数（逐行显式播种）**。

---

## 2. 关键锚点（ERP 实证 —— 防口径漂移，**不得违反**）

加工单 `CSO260915-02615`（#4343 已取证）：宽 **5.5m** / 高 2.69m / 工艺 韩褶 / **双开** /
定高买宽 / 理论褶倍 **2.00**，操作记录**每道工序 11.00 米**。

```
5.5 × 2.00 = 11.00   ⇒ 双开**不得**把总宽再乘 2
```

「公式吃总宽再 ×开数」（甲）会算成 22.00 米 —— **与实证差一倍、直接进订单金额** ⇒ 已被用户否决，取「乙」。
本锚点写进包 D 的**判据 1**（数值 ≠ 11.0 ⇒ 红）。

---

## 3. 术语与自动识别

### 3.1 倒幅 / 正幅（**唯一推导**，不设手选项）

| 术语 | 含义 | 推导 |
|---|---|---|
| **正幅** | 定高买宽：布门幅 = 帘**高**方向，花型**正着**用 | `cuttingMode == 定高买宽` |
| **倒幅** | 定宽买高：布旋转 90°，门幅变成**宽**度方向，花型**倒了** | `cuttingMode == 定宽买高` |

设手选项 = 制造与 `cuttingMode` 冲突的**第二份口径** ⇒ 禁止。

### 3.2 超高 / 超宽（**与门幅比较，自动识别**）

```
门幅 G   = SKU.doorWidth（缺省 2.8 米；窄幅布 1.4）
卷边常量 = 0.3 米（**复用** curtain_calc 既有常量，不新造第二个数）
超高 = (成品高 + 0.3) > G          超宽 = (成品宽 + 0.3) > G      ← 两者独立，可同时为真
```

**推理证据链**（来自 ERP 截图逐行）：
1. 定价对称：`韩褶+超高` 9.00 = `韩褶+超宽` 9.00 ⇒ 同一类加价的两个维度；
2. `韩褶+超高+**接高**+定型` 同时存在 ⇒ **超高 ≠ 需要接高**（否则「接高」冗余）；
3. `韩褶+**超宽+超高**+定型` 同时存在 ⇒ 二者**不互斥**（不是「定高买宽 / 定宽买高」二选一）。

⚠️ **照实登记**：本条是**推理，非实证**（未从 ERP 供应商取得判据）⇒ 阈值给默认值 + 商家可配 + 标 `source='推算'`，**不假装定论**。

### 3.3 自动特征进组合键

自动特征（**超高 / 超宽 / 倒幅 / 正幅**）由**客户端推导**并写入
`processingInfo.processingItems[]`（与手选加工项**同一数组**）—— 因为组合键的唯一来源就是 `processingItems[].name`。
**服务端不得再自行推导**（否则构成第二份口径）。已在 `processing-fee-and-option-pricing.md` §8 包 B 行登记。

> 🔴 **`定型` 已于 2026-09-19 移出本清单**（用户裁定「工艺规格中的工艺、**定型**直接通过加工项来勾选」）：
> 它现在是**手选加工项**（V83 目录里的「定型」，`craft_hint` 为空），不再由 `isShaped` 推导。
> 组合键里的 `定型` 因此来自**手选项的 name**；`order_items.is_shaped` 仍由「定型加工项是否勾选」派生后照旧写入
> （后端「`isShaped=false` ⇒ 剔除 定型/复烫」的接线**一字不动**）。
> ⚠️ 目录里**仍必须存在** `超高 / 超宽 / 倒幅` 三项（商家配「加工费组合」时要能选到），
> 但**下单页的手选控件必须把它们滤掉**（判据 8：自动识别特征出现手选项 ⇒ 红）——
> 清单的单一真值在 `frontend/admin-web/src/lib/craft-auto-features.ts` 的 `AUTO_FEATURE_NAMES`。

---

## 4. 冻结契约

### 4.1 `formula` 推导表（**唯一口径，只写一处**）

| 工艺 | `formula` | 默认褶倍 | 备注 |
|---|---|---|---|
| **韩褶**（`s_hook`） | `pleat`（韩褶公式 = 褶数法） | — | |
| **打孔** | `fullness`（倍数法） | **2.0** | **复用** `DEFAULT_CRAFT_TIERS['standard'].fullness`，不得新造第二个 `2.0` |
| 缺省 / 未指定 | `pleat` | — | |

`formula` 入参**保留为显式覆盖**；**缺省时按 craft 推导**（两条不冲突且都可测）。

### 4.2 配置键表（包 E 的租户级配置；**现有值 = 默认值**）

| 配置键 | 默认值 | 语义 |
|---|---|---|
| `per_fold_single` | `0.25` | 单色每折吃布（米） |
| `per_fold_mixed_times` | `{1: 0.65, 2: 1.2}` | 拼1/2次每折吃布（米） |
| `margin_single` | `0.2` | 单开余量（米） |
| `margin_multi` | `0.3` | 多开余量（米） |
| `min_fullness` | `1.5` | 褶倍下限（**护栏**，行业美学红线） |
| `tiers` | `{standard:{fullness:2.0}, economy:{fullness:1.8}}` | 工艺档位 |
| `default_formula` | `"pleat"` | **craft 推导表缺失时的兜底**（不是恒定默认值） |
| `side_margin` | `0.3` | 定宽买高上下卷边（米） |
| ~~`default_fabric_width`~~ | ~~`2.8`~~ | 🔴 **本键在实现里不存在**（包 D #4527 的 `DEFAULT_CRAFT_CALC_CONFIG` 无此键：门幅是 `build_quote(fabric_width=…)` 的**入参**，不是公式参数）⇒ **以实现为准**，包 E（#4528）**不建该列**、不凭空加一个没有消费者的配置键。跨源守卫 = `tests/unit_ci_workflows/test_craft_calc_config_contract.py`（该键出现在任何一源的**代码**里即红） |
| `meters_rounding_step` | `0.1` | 用料**向上进位**步长 |

**三条实现纪律**：
1. **默认路径逐值不变**：`config=None` 时除「向上进位到 0.1」（R2 明确裁定）外，其余输出与改前**逐值相同**；
2. **护栏不因可配而消失**：配置来自商家 = **不可信输入** ⇒ 非法值 **422 + 逐条理由**，**不得静默回退默认值**；
3. **不得读进模块级可变全局**（并发请求互相污染）⇒ 配置沿调用链显式传递，模块级默认是**只读常量**。

### 4.3 「配料」工序（R5 / R8）

| 属性 | 值 |
|---|---|
| 名称 | `配料` |
| 单位 | **米** |
| 计件单价 | **NULL**（+ `source='待确认'`）⇒ 计件金额 = 0，**必须显式可见**，不得静默 |
| 部位适用性 | `配料 × 布料` = `applicable=TRUE`；`配料 × 布帘/纱帘/帘头` = `FALSE` |

⚠️ **新状态**：既有约定是「`applicable=FALSE` ⇒ `unit_price` NULL」，本方案出现
**「`applicable=TRUE` 但 `unit_price` NULL」= 适用但未定价** ⇒ 该状态必须**可判**，不得与「不适用」混淆。

### 4.4 布料基础路线（R6 / R7）

| 项 | 值 |
|---|---|
| 路线名 | `布料工序路线` |
| `positions` | `["布料"]`（**第 4 个部位**） |
| `mainline` | `["配料"]`（1 道） |
| `is_default` | **FALSE**（`窗帘工序路线（默认）` 保持唯一默认） |
| 选择键 | `processing_info.saleForm === '布料'` |

⚠️ **后端今天完全不认 `saleForm`**（`grep -rn "saleForm" backend/` 零命中）⇒ 读 `saleForm` 是**新增行为**；
**缺键的存量单不得改变既有行为**（回归不变量）。

### 4.5 分幅公式（`panels`）**四份副本**：A / B1 / B2 三条口径不一致 + 通路 C 与 A 同式（issue #4760：已核清 + **已裁定 (A)**，执行依赖 #4652；通路 C = issue #5038）

**本节的公式串是实测读源的结论**（`backend/ai-agent-service/app/tools/curtain_calc.py`），
不是提案；**代码改了本节必须同改**（机械判据 = `tests/unit_ci_workflows/test_panels_formula_split_audit.py`，
它按本节这张表逐行复算，并断言「一致 / 不一致」列与实测相符）。

**通路与调用方**（`panels` = 定宽买高时的分幅数，单位「幅」）：

| 通路 | 入口 | 谁在调 | `panels` 口径（逐字读源） |
|---|---|---|---|
| **A 米宝下单通路** | `calculate_fabric_meters()` 定宽分支（`curtain_calc.py`） | `build_quote` 的**兜底分支**（`formula='pleat'` 且 `mounting != s_hook` 等未命中前两支时）⇒ `CurtainCalcTool` ⇒ 米宝/小布 Agent | `ceil((宽 + side_margin) × 褶倍 ÷ 门幅)` —— **含** `side_margin` |
| **B1 试算通路（倍数法）** | `build_quote()` 的 `formula='fullness'` 分支 | 商家手工下单页（`orders/new` → `POST /api/admin/orders/craft-calc` → `internal.py::craft_calc`）；`craft='打孔'` 由 `resolve_craft_rule` 派生成此式 | `ceil(ceil_to_step(宽 × 褶倍, 0.1) ÷ 门幅)` —— **不含** `side_margin`，且**多一道 `ceil_to_step`** |
| **B2 试算通路（褶数法）** | `build_quote()` 的 `pleat_mode` 分支 | 同上（`craft='韩褶'` / 默认档） | `ceil(褶数法总用料 ÷ 门幅)` —— **不含** `side_margin`（用料本身含余量 `margin_single/multi`，但那是**开数余量**，不是 `side_margin`） |
| **C 下单页门幅规则（前端副本）** | `resolveCutPlan()` 的定宽买高分支（`frontend/admin-web/src/lib/door-width-plan.ts`） | 商家手工下单页自动推导（`frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx`）⇒ 门幅 / 加工类型提示 | `ceil_mm((宽 + SIDE_MARGIN) × 褶倍 ÷ 门幅有效值)` —— **含** `side_margin`，且与引擎 `resolve_fabric_plan` **同式**（**毫米整数**除法；issue #5038 前是浮点 `ceil` ⇒ 总用料恰为门幅整数倍时**多算 1 幅**、并可能翻转选中的门幅） |

⚠️ **通路 C（第 4 份 `panels` 实现，issue #5038）**：它与 A **同式**（含 `side_margin`）且**同取整口径**
（毫米整数）。它与 A 的等价**不再靠人读**：由共享 golden 算例表 `tests/fixtures/panels-cross-language-golden.json`
**三腿共读**（引擎腿 `backend/ai-agent-service/tests/test_curtain_calc_fabric_plan.py` / 静态腿
`tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py` / 前端腿
`frontend/admin-web/tests/unit/lib/door-width-plan.test.ts`）—— 任一侧改回浮点即红。
本表的**通路 C 行**由 `tests/unit_ci_workflows/test_panels_formula_split_audit.py` 的 C7 钉住
（登记与代码自洽：删掉该行、或把前端改回浮点 ⇒ 红）。

**对照表**（门幅 `G = 2.8`、窗高 `H = 2.6` ⇒ `H + HEM_MARGIN(0.3) = 2.9 > 2.8`，
两通路**都**落在定宽买高分支；`W` = 成品宽、`N` = 褶倍）：

| 宽 `W` | 褶倍 `N` | A 米宝 `panels` | B1 试算 `panels` | 一致？ |
|---|---|---|---|---|
| 1.1 | 2.0 | 2 | 1 | ❌ 不一致 |
| 1.2 | 2.0 | 2 | 1 | ❌ 不一致 |
| 1.25 | 2.0 | 2 | 1 | ❌ 不一致 |
| 1.3 | 2.0 | 2 | 1 | ❌ 不一致 |
| 1.4 | 2.0 | 2 | 1 | ❌ 不一致 |
| 1.45 | 1.8 | 2 | 1 | ❌ 不一致 |
| 1.5 | 1.8 | 2 | 1 | ❌ 不一致 |
| 1.5 | 2.0 | 2 | 2 | ✅ 一致 |
| 2.0 | 1.5 | 2 | 2 | ✅ 一致 |
| 3.0 | 2.0 | 3 | 3 | ✅ 一致 |
| 4.0 | 2.0 | 4 | 3 | ❌ 不一致 |

- 差 1 幅 ⇒ 米数差**整整一幅长**（`H + HEM_MARGIN` = 2.9 m/幅）⇒ 面料费 + 加工费**同幅变化**；
- ⚠️ **与 #4746 无关**：本差异在 `curtain_calc.py` 内部（同一次调用、同一 `fabric_width` 入参）
  ⇒ 门幅接线统一后**仍在**（#4746 已统一的是**前端**侧，未动引擎）；
- ⚠️ **与「agent 默认值 vs 租户配置」偏差（§7 第 3 条）不同源**：本条是**同一个引擎、同一份配置**下的
  两个函数口径不同，不靠「配置未注入 agent」解释。

**口径真值源（谁对）**：`docs/curtain-fabric-quote-rules.md` §3 逐字写
`幅数 P = ceil((W + SIDE_MARGIN) × N / G)`（`SIDE_MARGIN` = 左右各 15cm **覆盖余量**，数值见该文 §0「数值常量清单」）⇒ **真值源站 A（含 `side_margin`）**；
前端判据（`frontend/admin-web/src/lib/craft-auto-features.ts` 的 `(宽 + SIDE_MARGIN) × 褶倍 > 门幅`）
亦与 A 同式。**B1/B2 漏 `side_margin` 是引擎内部不一致**，不是「粗估 vs 精算」的有意分工
（两通路都产出进报价的**同一个** `fabric_meters`，无任何文档把它标为粗估）。

### 4.5.1 裁定（2026-09-21，用户）与修法边界

> **用户裁定原文（2026-09-21，issue #4760）**：「**A) 按真值源统一 B1/B2（含 side_margin）**」

- **已裁定**：**统一到 A** —— `build_quote()` 的 **B1**（`formula='fullness'`）与 **B2**（`pleat_mode`）
  两个分支的 `panels` **必须与 `calculate_fabric_meters()` 的定宽分支同式**（**含** `side_margin`）。
  **代价已知情并接受**：改 B1/B2 **会改商家手工下单页试算出来的钱**（窄门幅/小窗场景从 1 幅变 2 幅，
  米数可能翻倍）；**历史订单快照不动**（快照冻结）。
- 🔴 **执行依赖 `backend/ai-agent-service/**` ⇒ 依赖 #4652 排期**（用户裁定「本会话不动 ai-agent」）
  ⇒ 本单（#4760 核清单）**只核清 + 判定 + 登记，未改一个数值**；本节的对照表是**改前实测留档**
  （「谁在何时因何裁定」= 本小节 + issue #4760 + PR #4764 的判定段）。

**修法边界（具体到文件与函数）** —— `backend/ai-agent-service/app/tools/curtain_calc.py`：

| 落点 | 现状 | 改为 |
|---|---|---|
| `calculate_fabric_meters()` 定宽分支 | `ceil((W + cfg["side_margin"]) × N / G)` | **不动**（= 权威式，B1/B2 向它看齐） |
| `build_quote()` 的 `formula='fullness'` 分支 | `panels = ceil(meters / G)`，`meters` = `_per_panel_fullness_meters(...)` 的 `ceil_to_step(W × N, 0.1)` 结果 | `panels = ceil((W + cfg["side_margin"]) × N / G)` |
| `build_quote()` 的 `pleat_mode` 分支（`fixed_width_pleats`） | `panels = ceil(meters / G)`（褶数法总用料 ÷ 门幅） | 同式（含 `side_margin`） |
| 建议 | 三处各写一遍 | 抽**一处** `panels_for_fixed_width(window_width, fullness, fabric_width, cfg)`，三处引用（「一处公式、三处引用」） |

**⚠️ 顺带：`ceil_to_step(宽 × 褶倍, 0.1)` 那道取整该不该保留？—— 建议去掉（依据如下，本单不实施）**

- `meters_rounding_step = 0.1` 的**语义**是「**用料米数**只许向上、不许抹零」（#4527 判据 3，防抹零少算钱）；
- 但 `panels` 数的是「**几幅布**」（整数、物理裁剪单位），**不是**「买几米」⇒ 在**分幅判据**里
  先把 `W × N` 进位到 0.1 再除以门幅，是**对中间量套用了最终量的口径**；
- **实测它会改变 `panels`**（不是无害的表示误差）：`W = 1.45`、`N = 1.8`、`G = 2.8` 时
  `ceil_to_step(2.61, 0.1) = 2.7` ⇒ `ceil(2.7 / 2.8) = 1 幅`；**去掉取整** ⇒ `ceil(2.61 / 2.8) = 1 幅`，
  而**含 `side_margin`** ⇒ `ceil((1.45+0.3) × 1.8 / 2.8) = ceil(3.15 / 2.8) = 2 幅`（与 A 同式）；
  ⚠️ 该组在**只加 `side_margin` 而不去取整**时得 `ceil(ceil_to_step(2.7)/2.8) = 1 幅` ⇒
  **仍与 A 不一致**（`W=4.0/N=2.0/G=2.8` 同族：`ceil_to_step(8.0)/2.8 = 3` vs A `ceil(8.6/2.8) = 4`）
  ⇒ **两道差异都要修，只修 `side_margin` 修不干净**；
- ⇒ 建议：**分幅用原始乘积**（`(W + side_margin) × N / G` 直接 `ceil`），
  `ceil_to_step` 只作用在**最终回传的用料米数**上（今天 B1 的 `meters = panels × 每幅长` 本就**没有**再进位，
  与 A 的 `meters = panels × panel_length` 一致 ⇒ 去掉中间取整**不引入**新的米数口径）。

---

## 5. 分包（文件所有权，零共享写路径）

| 包 | issue | 内容 | 依赖 |
|---|---|---|---|
| **D** | #4527 | `curtain_calc.py` 逐片口径 + 向上进位 + `formula` 推导；Java 代理透传；`craft-calc-request.ts` **放行打孔** | 无 |
| **E** | #4528 | 租户级配置表（V80 `craft_calc_configs`，单行/租户，**缺行 = 引擎默认值，不播种**）+ 读写端点（`GET|PUT /api/admin/production/craft-calc-config`）+ 护栏（422 逐条理由）+ 配置页 tab（挂 `/production/routings` 第三个 tab，不新开菜单）+ `CraftCalcClient` 注入本租户配置 | **等 D**（同文件） |
| **F** | #4529 | `配料` 工序 + 第 4 部位（~~116 行~~ ⇒ **落地值 120 行**，**现取**、见 R7 的口径订正注）+ 第 2 条默认路线 + 订单侧读 `saleForm` + 开租播种 | **等 A（#4525，`schema.sql`）+ C（#4452，`ProcessingOrderService`）** |

---

## 6. 判据（每条必须能红）

| # | 判据 | 红证 |
|---|---|---|
| 1 | **ERP 锚点**：宽 5.5 / 双开 / 褶倍 2.0 / `formula='fullness'` ⇒ 用料 **11.0** | ≠11.0 ⇒ 红 |
| 2 | **逐片口径**：总用料 = 每片用料 × 开数（期望值**写死**，不从实现推导） | 只算一片 / 只算总宽 ⇒ 红 |
| 3 | **向上进位**：构造 x.xx1 ⇒ 结果 x.(x+1) | 截断 / 四舍五入 ⇒ 红 |
| 4 | **公式按 craft 推导**：打孔 ⇒ 倍数法且 `fullness=2.0`；韩褶 ⇒ 褶数法 | 走错支 ⇒ 红 |
| 5 | **开数系数不得翻倍**：同一成品宽下，单开与双开的 `fullness` 结果**相等** | 总宽再×开数 ⇒ 红 |
| 6 | **前端放行打孔**：打孔行**会发**算料请求（今天返回 `null` ⇒ 永不发） | 仍被 `PLEAT_CRAFTS` 挡住 ⇒ 红 |
| 7 | **配置生效**：改 `per_fold_single` ⇒ 褶数法用料随之变 | 不生效 ⇒ 红 |
| 8 | **配置护栏**：非法值 ⇒ 422 逐条理由 | 静默回退默认 ⇒ 红 |
| 9 | **配置不跨租户串** + **不被模块级全局污染** | 串租户 / 污染 ⇒ 红 |
| 10 | **布料单 = `裁剪` + `打包` 两道**（**目标口径 · issue #4676 / 迁移 V88 生效**；旧口径 `配料` + `打包` **已作废** —— 见本表下方「口径变更」注）；成品帘单主线 **9 + 打包 = 10 道**，且 `打包` 只出现 1 行（套级，不按部位展开） | 多/少/重复 ⇒ 红 |
| 11 | **每租户恰好两条路线**，且**恰好一条 `is_default`** | 0/2 条默认 ⇒ 红 |
| 12 | **`unit_price=NULL` 时计件 = 0 且显式可见**，且与「不适用」**可区分** | 静默 0 / 混淆 ⇒ 红 |
| 13 | 三源收敛：`routing.py` ↔ 新迁移 ↔ `schema.sql` 逐行逐值 | 漂移 ⇒ 红 |
| 14 | 三把工具全绿（`verify-all.sh gate` / `check-ui-regression.sh` / `contract-check.sh`） | — |

> ⚠️ **口径变更（issue #4678，2026-09-20）—— 判据 #10 的旧口径已作废**：
> 本判据原文逐字为「**布料单 = `配料` + `打包` 两道**」。**用户裁定（2026-09-20，逐字）**：
> 「**是裁剪**」+「**打包需要计件**」⇒ 布料单改为 **`裁剪` + `打包`**，**`配料` 退场**
> （行业里 `配料` 对应「**物料分配**」= 收发人员的活，**不在车间三段**「裁床 / 车位 / 烫工及后整」里
> ⇒ **不是工序**）。**实施单 = issue #4676**（迁移 **V88**，改 `FABRIC_MAINLINE_STEPS`
> `["配料","打包"]` → `["裁剪","打包"]`；存量加工单/报工快照**一字不动**）。
> 术语真值源：`docs/curtain-production-process-standard.md`。
> ⚠️ **照实登记（issue #4701 的 P1，2026-09-20 复核）**：V88 **已合入**，但**真值源仍是旧口径**
> `["配料","打包"]`（`backend/ai-agent-service/app/production/routing.py` 的 `FABRIC_MAINLINE_STEPS`；
> `_POSITION_PRICE_ROWS` 的 `裁剪 × 布料` 仍为 `FALSE`）⇒ 本判据**至今仍会红**，这是**已知且有意**的：
> 本表钉的是**目标口径**，不是当下代码。
> ⚠️ **钉住它的测试也是「过期裁定」**：`backend/ai-agent-service/tests/test_production/test_fabric_route.py`
> 的断言文案把 `配料` 称「**裁定**」，而 #4673 恰恰**改判**为 `裁剪`
> ⇒ ai-agent 排期时必须**连同该测试一起改判**（文案改成「已被 #4673 改判为 `裁剪`」）并同步 `seed.json`。
> **本会话不动工**（用户裁定 #4652）⇒ 本单**只登记**，登记处见
> `docs/design/set-code-and-scan-loop.md` §10 的 **C12**。
> 上游依据：`docs/design/public-operations-and-craft-ui.md` §7.4 **曾**把此处登记为「该文档需要回改」的冲突点
> —— 该回改**已由 #4678 完成**（本表判据 #10 的上方「口径变更」注即其结果），§7.4 的现状块已同步；
> 此处保留指向，只为**留档**「当时为什么登记这条冲突」。

---

## 7. 照实登记（边界与未验证，不粉饰）

1. **超高/超宽判据是推理**（§3.2）：未从 ERP 供应商取得定义。已给默认值 + 商家可配 + `source='推算'`。
2. **`docs/sql/schema.sql` 的同步面**：包 D/F 都要动它（bootstrap 路径不跑迁移链的**终态**）。
   谁最终持有它由集成时决定；**未同步 = bootstrap 库缺列/缺行**（须显式登记）。
3. **agent 路径不注入租户配置**（包 E）：小布/米宝走同一份 `curtain_calc.py`，但 agent 侧冻结 ⇒
   **agent 仍用默认值，商家配置只在 web 路径生效** ⇒ 两条路径会算出不同米数。**已知且已登记的偏差**，待 agent 统一重构时收口。
4. **米宝路径不推导自动特征**（同 `processing-fee-and-option-pricing.md` §8 包 B 边界）⇒ 组合键缺项 ⇒ `unpriced`；与 #4408 同族。
5. **公式参数可配后的「口径漂移」风险**：商家改参数 ⇒ 同一张单在不同时间算出不同米数。
   **不改历史**（快照冻结）；但**同一张单两次试算结果可能不同** ⇒ 需在 UI 上标出「按当前配置计算」。
6. **`打包` 的位置是推断（issue #4529 追加裁定）**：ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货`，
   `外帘装袋` ≈ ERP 的 `外帘装箱` ⇒ 实现把 `打包` 插在 `外帘装袋` **之前**（窗帘主线 9 → 10 道）；
   但 #4343 明确登记过这两道的对应关系**未能确定** ⇒ **按 ERP 顺序推断、待客户确认**（不假装定论）。
7. **设计稿与 DDL 冲突一处（以代码事实为准，issue #4529）**：§4.3 写「`配料` 计件单价留空（NULL）」，
   而 `production_operations.unit_price` 是 `NOT NULL DEFAULT 0`（V49 DDL）⇒ 工序库行落 **0**；
   「未定价」的真载体 = **部位价目行** `unit_price = NULL` + `applicable = TRUE`（**行数现取**，见 R7
   的口径订正注；原文写 ~~120 行里的~~ = 当时读数 —— **基数未变，但 V88 后「总行数」≠「生效行数」**，
   故此处不再写死；`配料 × 布料` / `打包 × 4 部位`）+ `source` 落受控枚举值 `占位待确认`（**不是** `待确认` ——
   后者不在 `production_operations_source_check` 的枚举里）。
8. **本包未做（照实登记）**：`docs/sql/schema.sql` 与 `routing.py` / V79 / Java 播种（共四源）已逐行收敛；
   **真实 LLM 评测未跑**（用户裁定「默认不自动验证」）⇒ agent 侧行为面未验（本包只动确定性层）。
9. **分幅公式三条口径不一致（issue #4760：**已裁定 (A)，待 ai-agent 排期执行**）**：
   `calculate_fabric_meters`（含 `side_margin`）vs `build_quote` 的 `fullness` / `pleat` 两支（不含）
   ⇒ 同一张单两个 `panels`。**用户 2026-09-21 裁定「A) 按真值源统一 B1/B2（含 side_margin）」**；
   核清读数、修法边界（具体到文件与函数）与 `ceil_to_step` 中间量的处置建议见 **§4.5 / §4.5.1**；
   修法落在 `backend/ai-agent-service/**` ⇒ 依赖 #4652 ⇒ 本单只登记，未改任何数值。
