# 门幅规则迁服务端（#5043 包 2b）—— 设计与待裁定项

> **状态**：**待裁定**（未开工）。母单 #5036 的**判定**（#5019 切源）与**提示**（#5036）已迁服务端；
> **算例**已随包 2a 迁服务端。本文覆盖**剩下的最后一块**：**门幅规则**。
>
> **开工前置（用户裁定）**：§5 的「非 `CALC_CRAFTS` 行的用料口径」选 **B / C / D**。
> 另：本单最终要改 `.github/cases/**`（OR-040 / OR-041 改判）⇒ 会撞 Case Trust 的 burn-down 预算
> ⇒ **#5048 需先行**（三条用例真值）。

## 1. 现状（读源）

| 面 | 落点 | 职责 |
|---|---|---|
| **前端门幅规则** | `frontend/admin-web/src/lib/door-width-plan.ts` 的 `resolveCutPlan()` / `judgeDoorWidthChoice()` | 在候选门幅里求「可行 / 需接高 / 不可判定」+「客服所选门幅相对规则解的四态（`optimal` / `suboptimal` / `infeasible` / `unknown`）」+ 建议文案 |
| **引擎门幅规则** | `backend/ai-agent-service/app/tools/curtain_calc.py` 的 `resolve_fabric_plan()` | 同一件事的**另一份实现**（issue #5013）：可行集取**最小门幅** / 定宽买高取**分幅最少**（并列取较小门幅）/ 需接高 + 缺口 + 加高条段数 |
| **引擎规则的真值入口** | 同文件的 `build_quote()`（`fabric_widths` 入参 = 这条通路的唯一开关） | 先按**选定用料公式**算「定高买宽用料 T」，再交 `resolve_fabric_plan` 选门幅/定加工类型 |

**前端那一份已被登记为「第 4 份 `panels` 副本」**（issue #5038；审计 =
`tests/unit_ci_workflows/test_panels_formula_split_audit.py`，其 §4.5 对照表登记在
`docs/design/craft-calc-and-fabric-routing.md`）⇒ 本单与那条审计是**同一件事的两半**。

## 2. 实测分歧：两者**不是同一条规则**（本单的核心依据）

**定宽买高（倒幅）的幅数**，两边算法不同：

| 面 | 幅数 |
|---|---|
| 引擎 `resolve_fabric_plan()` | `ceil(T / g_eff)`，其中 `T` = **定高买宽用料**（由**选定用料公式**算） |
| 前端 `resolveCutPlan()` | `ceil((成品宽 + SIDE_MARGIN) × 褶倍 / g_eff)` ⇒ **恒按倍数法**，**不看用料公式** |

引擎实跑（`per_fold_single = 0.25` / `side_margin = 0.3` / 褶倍 `2.0` / 韩褶褶数法）：

| 成品宽 | 褶数 | 引擎 `T` | 前端分子 | 差 |
|---|---|---|---|---|
| 1.5 | 11 | 2.95 | 3.6 | **−0.65** |
| 2.0 | 15 | 3.95 | 4.6 | **−0.65** |
| 3.0 | 23 | 5.95 | 6.6 | **−0.65** |

⇒ 门幅 **3.2** 时：成品宽 1.5 ⇒ 引擎 **1 幅** / 前端 **2 幅**；成品宽 3.0 ⇒ 引擎 **2 幅** / 前端 **3 幅**。

**结论（两条，都要正面回答）**：

1. 🔴 **本单不是「把前端规则原样搬到服务端」** —— 那样会把一个**与引擎不符的规则**固化成服务端口径。
   正解 = 规则面**复用引擎的实现**（引擎是米数/取价的真值源），前端 `resolveCutPlan()` 随之退场。
2. 🔴 **当前前端规则对韩褶订单可能给出错的「规则解」**（推荐门幅 / 「分幅最少」结论）——
   这是**本单之外已存在**的缺陷（#4877 落地时按倍数法写的），本单顺带修掉。

## 3. 为什么必须有**只读规则端点**（不是「零新端点」）

下单页的**门幅规则要在发算料请求之前**用：`pickAutoSkuForColor()` 靠 `resolveCutPlan()`
决定**选哪个 SKU / 哪个门幅**；而 `POST /api/internal/production/craft-calc` 请求**本身**要带门幅与工艺口径
⇒ **鸡生蛋**（「选哪个门幅」正是规则要回答的，却要先有门幅才能发试算）。

⇒ 必须有一个**只读规则端点**（只吃几何 + 候选门幅 + 工艺口径，**不算用料、不取价、不落库**），
理由与 #4976 包 2 建「独立判定端点」同款（`CALC_CRAFTS` 那三类行也要有规则面）。

## 4. 端点**不得自算 T**（否则 = 第二份口径）

`resolve_fabric_plan()` 需要 `fixed_height_meters`（定高用料 **T**），而 T 在 `build_quote()` 里由**三条分支**算出：

| 分支 | T 的算法 |
|---|---|
| 倍数法（`FORMULA_FULLNESS`） | `_per_panel_fullness_meters(window_width, open_count, N, cfg)` |
| 韩褶褶数法（`FORMULA_PLEAT` + `s_hook` + 档位/褶数） | `calculate_fabric_by_pleats(...)`（每折吃布 × 褶数 + 余量） |
| 默认 / 罗马帘 | `calculate_fabric_meters(..., fabric_width=math.inf, ...)` |

端点若复刻这套「公式选择 + 档位/褶数/拼色系数」= **第二份口径**（同族 #4656 / #4592 的教训）。

**正解**：端点内部**调 `build_quote()`**（T 的唯一实现），从它的 `plan_state` 取规则面字段
（`door_width` / `cutting_mode` / `splice` / `door_width_reason` / `panels` / `meters`）。

## 5. 🔴 待裁定：非 `CALC_CRAFTS` 行的**用料口径**

按 §4 的处方，端点需要一个 T —— 而**四爪钩 / 穿杆 / 平幔**今天**没有用料口径**
（`frontend/admin-web/src/lib/craft-calc-request.ts` 的 `CALC_CRAFTS` 只放行 `韩褶` / `打孔` / 空，
`craftCalcParamsOf()` 对其余返回 `null`）。问题由此精确化为：**这三类行的 T 按什么算？**

| 选项 | 做法 | 代价 |
|---|---|---|
| **B（推荐：不发明口径）** | 这三类行**只判「定高买宽可行性 + 需接高缺口」**（只依赖 `成品高 + hem_margin`，**不需要 T**），**不判倒幅分幅** ⇒ `panels: null` + 显式说明「无用料口径 ⇒ 不推荐分幅」 | 这三类行**不再**得到「分幅最少」推荐 —— 但今天给的那个推荐**是错的**（§2） |
| C | 沿用今天的**倍数法假设**当 T | 把一份**与引擎不符**的口径**固化到服务端**（与「单一真值」纪律相背） |
| D | 给这三类**补用料口径**（业务裁定公式） | 改的是**钱**（米数）⇒ 属另一单，不该混进「搬位置」 |

⚠️ **B 是唯一不需要新口径的选项**，读源依据：`resolve_fabric_plan()` 的 `_fixed_height()` / `_splice()` 分支
**只用 `need_height`**（= 成品高 + `cfg["hem_margin"]`）；`total`（= T）只在 `_fixed_width()`（倒幅幅数）
与接高的**加高条米数**里用到。

⚠️ **实现注意（选 B 时）**：`resolve_fabric_plan()` 的 `fixed_height_meters` 现为**必填** ——
选 B 需要它可缺省（`None`），且**只在真要用到 T 的分支**（`_fixed_width()` / 接高的米数）fail-closed，
不得拿 0 冒充（`0` 会算出「0 幅」「0 米」这类假答案）。

## 6. 目标形态（终态）

| 面 | 终态 |
|---|---|
| 判定 | 服务端（#5019，已） |
| 提示 | 服务端（#5036，已） |
| 算例 | 服务端（#5043 包 2a，已） |
| **门幅规则** | **服务端**（只读规则端点，内部复用 `build_quote()`） |
| 前端 `frontend/admin-web/src/lib/door-width-plan.ts` | **退场**（或降级为「服务端未返回 ⇒ 不可判定」） |
| 前端 `frontend/admin-web/src/lib/craft-auto-features.ts` | `SIDE_MARGIN` / `HEM_MARGIN` **前端副本删除**（连同跨语言漂移守卫改判为纯正向断言） |

## 7. 迁移与验证计划

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **规则面按租户配置**：`hem_margin` 配成非 `0.3` ⇒ 同输入的「单幅做不出 / 需接高」结论与缺口米数随之变 | 退回模块常量 `0.3` ⇒ 红 |
| 2 | **规则面单一真值**：可行 / 需接高 / 分幅数的判据**只在服务端一处**；前端**不得再持有余量常量** | 把常量副本放回前端 ⇒ 红 |
| 3 | **规则面 = 引擎口径**（§2 的分歧被消灭）：韩褶订单的规则解与引擎 `resolve_fabric_plan()` **逐值一致**（含 `panels`） | 前端沿用倍数法假设 ⇒ 红 |
| 4 | **四态语义不变**：`optimal` / `suboptimal` / `infeasible` / `unknown` 的边界（未选 / 未维护 / 规则不可判定 ⇒ `unknown`；并列最优不提示）**一字不放宽** | 把 `unknown` 并进 `optimal` ⇒ 红 |
| 5 | **非 `CALC_CRAFTS` 行按裁定口径**（§5）—— 选 B 时：只给可行性与缺口，`panels` 为 `null` 且显式说明 | 给它一个假 T ⇒ 红 |
| 6 | `./verify-all.sh gate` + `./check-ui-regression.sh` + `./contract-check.sh`（跨模块）绿 | — |

**共享 golden 算例**：跨语言等价性已有既有机制
（`tests/fixtures/panels-cross-language-golden.json` + `tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py`）
⇒ 本单应**复用它**扩展「规则解」的算例表，不另造一套。

## 8. 边界（不做）

- 引擎**试算**的门幅仍是 `backend/ai-agent-service/app/api/internal.py` 的 `_FABRIC_WIDTH` **硬编码**
  （分叉 #4746 / #4652）—— 本单**不动**（它改的是**米数**，属另一件事）。
- 接高用料口径（加高条米数）**未裁定**（#4877 已登记为独立缺口）—— 本单**不动**。
- 门幅**有效余量**（缩水/边损/对花回）的**租户级配置键**尚未落地（`allowance` 今天恒 `0`）——
  本单只**透传**该入参，不新增配置键。
