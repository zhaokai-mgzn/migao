"""
AI 智能客服系统 - 窗帘算料报价 Tool

面向小布（C 端客服）的窗帘用布量计算与报价工具。
**纯计算**（确定性公式）+ 唯一一处外部读取：**本租户的算料口径**（issue #4922）——
`GET /api/admin/production/craft-calc-config`（缺行 ⇒ 不传 `config`；服务端答复了却读不通 ⇒
fail-closed；服务端不可达 ⇒ 显式降级 + 留痕，见 `load_tenant_craft_calc_config`）。
**口径零自造**：本模块不持有第二份算料参数默认值表（唯一默认值 = `DEFAULT_CRAFT_CALC_CONFIG`，
服务端缺行时由引擎自己用它，不从这里发过去）。

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）。

计价口径（issue #4118，以 #3005 为准）：加工费**按面料米数打包**计，罗马圈/四爪钩/S 钩等辅料成本
已含在按米单价里（如「打孔式 8 元/米」即含圈含工）⇒ **辅料数量不得由米数推导**（无「每米 N 个」密度）。
顾客显式要单独买辅料（如单独买罗马圈）时走 `accessories` **显式入参**，数量/单价必须由调用方给出。

核心公式：
- 定高布（买宽）：M = (W + 0.3) × N    （W=窗宽, N=褶皱倍数, 0.3=左右各15cm覆盖余量）
- 定宽布（买高）：P = ceil((W+0.3)×N/G)，M = P × (H + 0.3)   （G=门幅, H=窗高, 0.3=上下卷边）
- 罗马帘：M = (W + 0.2) × (H + 0.3)
- 对花：定宽布每幅长加 1 个花距

**两种「用料计算方法」可选**（issue #4527，用户 2026-09-19 裁定）：
- `formula='pleat'`（**默认**，韩褶公式＝褶数法）：`总用料 = 每片用料 × 开数`，
  每片用料 = 每折吃布 × 每片褶数 + 每片余量；每片宽 = 成品宽 ÷ 开数；
- `formula='fullness'`（褶倍数公式＝倍数法）：`总用料 = 每片宽 × 褶倍 × 开数`（= 成品宽 × 褶倍，
  **线性、与开数无关** —— 双开不得把总宽再乘一遍，见下）；
- 用料米数**一律向上进位到 0.1**（`ceil(x*10)/10`，issue #4527 判据 3）；
- 公式参数（每折吃布/余量/下限/档位/默认公式/进位步长）一律从**配置对象**读，
  `config=None` ⇒ `DEFAULT_CRAFT_CALC_CONFIG`（默认值 = 既有常量逐值不变，商家可注入自定义口径）。

**ERP 实证锚点（不得违反，防口径漂移）**：加工单 `CSO260915-02615`（#4343 已取证）宽 5.5m / 高 2.69m /
工艺韩褶 / **双开** / 定高买宽 / 理论褶倍 **2.00**，操作记录每道工序 **11.00 米** ⇒ `5.5 × 2.00 = 11.00`
⇒ **双开不得把总宽再乘 2**（那会算成 22.00 米，与实证差一倍、直接进订单金额）。

工程陷阱：成品高 H + 0.3 > 门幅 G 时定高布超限，须改用定宽布并返回告警。
"""
from __future__ import annotations

import math
import re
from types import MappingProxyType
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client


# ── 悬挂方式 → 褶皱倍数默认值（【标】行业标准）──
DEFAULT_FULLNESS: Dict[str, float] = {
    "eyelet": 2.0,   # 打孔帘（罗马圈/眼环）1.8~2 倍，默认 2
    "s_hook": 2.0,   # 韩式褶（S 钩/调节钩）2~2.5 倍，默认 2
    "hook": 2.0,     # 四爪钩/普通挂钩 1.5~2 倍，默认 2
    "roman": 1.0,    # 罗马帘/卷帘/百叶帘 1 倍（无褶皱）
}

# ── 悬挂方式 → 加工费默认单价（【默】经验默认，元/米）──
DEFAULT_PROCESSING_PRICE: Dict[str, float] = {
    "eyelet": 8.0,   # 打孔式
    "s_hook": 10.0,  # 韩式褶
    "hook": 5.0,     # 四爪钩/挂钩式
    "roman": 0.0,    # 硬质折叠无加工费
}

# ── 损耗/余量常量（【标】行业标准）──
SIDE_MARGIN = 0.3       # 定高布：左右覆盖余量合计（各 15cm）
HEM_MARGIN = 0.3        # 定宽布：上下卷边合计（脚位+止口）
ROMAN_SIDE = 0.2        # 罗马帘：包边余量
ROD_EXTENSION = 0.4     # 罗马杆两端各伸出 15~20cm，合计 0.3~0.4

# ── 辅料/安装默认单价（【默】经验默认，商家可配置）──
# ⚠️ 此处**不再有**「罗马圈 元/个」+「每米布 N 个」两个常量（issue #4118，口径以 #3005 为准）：
# 加工费按米打包已含圈，**由米数推导圈数 = 双算**（同一单既收 8 元/米又单列 60 元圈费）。
# 顾客显式要单独买圈 ⇒ 走 build_quote(accessories=[...]) 显式入参（数量由调用方给出）。
EYELET_TAPE_PRICE = 8.0       # 孔带 元/米
ROD_PRICE = 25.0              # 罗马杆 元/米
TIEBACK_PRICE = 15.0          # 绑带 元/对
INSTALL_PRICE = 18.0          # 安装 元/米（按杆长）

# ── 韩折褶数法常量（【标】2026-09 客户纸表/行业系统加工单实证）──
PLEAT_FABRIC_PER_FOLD = 0.25       # 每折吃布（米）——**单色**口径
MARGIN_SINGLE = 0.2                # 单开余量（两侧包边各 10cm）
MARGIN_MULTI = 0.3                 # 对开/四开余量（每片外侧包边 10cm + 内侧对缝 5cm）
MIN_FULLNESS = 1.5                 # 褶皱倍数下限（低于影响美观，行业红线）

# ── 拼色每折吃布系数（用户 2026-09-19 裁定；纸质「韩折下料速查表」表头原文）──
# 表头原文：「拼色下料 **1个折 0.65** ／ **2个折 1.2**」——用户明确这是**用料**口径（不是计价）。
# ⚠️ 与真值源冲突并已按用户裁定改正：`docs/curtain-fabric-quote-rules.md` §10 曾把同一行记成
# 「拼色**计价** = 按褶数加价（1 折 0.65、2 折 1.2 ≈ 0.6 元/折）」；本表是**用料**（米/折）。
# 拼色计价（元/折）属 issue #4341 的待裁定项，**本模块不实现**。
# 余量与单色**同一套**（单开 0.2 / 多开 0.3）：52 折双开 ⇒ 单色 13.3 / 拼1次 34.1 / 拼2次 62.7。
STYLE_MIXED = "拼色"                # 款式枚举取值（与 frontend order-craft-fields.ts 的 STYLE_OPTIONS 逐字一致）
# 拼次（**数字**）→ 每折吃布（米）。键刻意是数字：纸表给的是「1 个折 / 2 个折」这两个**档位**，
# 用中文选项名当键会把「措辞」变成判据（改一个字系数就静默失效 —— CI 判据 ②
# `tests/unit_ci_workflows/test_tool_input_contract_guards.py` 明令不得新增该类站点），
# 而**拼次本身是数字**。选项名只是**载体**（`拼N次` 里的 N 才是参数），见 `mixed_times`。
MIXED_COLOR_PER_FOLD_BY_TIMES: Dict[int, float] = {1: 0.65, 2: 1.2}
# 选项名 → 拼次。选项名是**冻结的 join key**（与 `routing.SPECIAL_OPTION_ROUTINGS` /
# frontend `SPECIAL_OPTIONS` 逐字一致；改它就是少发工人钱），这里读的是**契约标识符**，
# 不是从散文里猜语义。
_MIXED_TIMES_RE = re.compile(r"^拼(\d+)次$")


def mixed_times(option: str) -> Optional[int]:
    """特殊选项名 → 拼次（数字）；不是「拼N次」形态 ⇒ None。"""
    m = _MIXED_TIMES_RE.fullmatch(option or "")
    return int(m.group(1)) if m else None


# ── 拼色**报价加价**（用户 2026-09-21 裁定；真值源 `docs/curtain-fabric-quote-rules.md` §10 / §11）──
# 逐字裁定（经 issue #4848）：「**拼色计价规则就是拼色款另加 2.4 元/米 先按这个算吧**」。
#
# ⚠️ **与上面的 `MIXED_COLOR_PER_FOLD_BY_TIMES` 是两件事，别搅在一起**：
#   · 那张表 = 拼色**用料**（米/折，0.65 / 1.2）⇒ 改的是**米数**（已落码、正确，本包不动）；
#   · 本常量 = 拼色**计价**（元/米）⇒ 改的是**钱**（本包落码）。
#   旧措辞把纸表那一行记成「拼色**计价** = 按折加价（0.65 / 1.2 ≈ 0.6 元/折）」是**误记** ——
#   错的是**单位/形态**（把「米/折」记成了「元/折」），**不是**「拼色计价不存在」。
#
# 口径（本仓语境下的确切算法）：`款式=拼色` ⇒ **该款面料米数**（`build_quote` 的 `meters`，
# 含余量、已按拼次口径算出）× 本单价，**另立一行加价**（不改面料/加工/辅料单价 ⇒ 不双算）。
# 「按褶数折算」= 本单价是「每折加价」按**单色每折吃布**（`per_fold_single`）折算成元/米的形态：
#   `0.6 元/折 ÷ 0.25 米/折 = 2.4 元/米`（真值源 §10 的误记更正段 + issue #4341 第 1 项的换算）。
MIXED_COLOR_SURCHARGE_PER_METER = 2.4   # 拼色款报价加价（元/米；按该款面料米数计）

# ── 工艺档位（【默】商家可配；每档 = 名义倍数 → 褶数规则）──
DEFAULT_CRAFT_TIERS: Dict[str, Dict[str, Any]] = {
    "standard": {"fullness": 2.0, "label": "标准工艺"},
    "economy": {"fullness": 1.8, "label": "经济工艺"},
}

# ── 公式选择（issue #4527，用户 2026-09-19 裁定：「根据用户要求选择不同的计算公式，默认用韩折的」）──
FORMULA_PLEAT = "pleat"          # 韩褶公式（褶数法）
FORMULA_FULLNESS = "fullness"    # 褶倍数公式（倍数法）
FORMULA_LABELS: Dict[str, str] = {
    FORMULA_PLEAT: "韩褶公式",
    FORMULA_FULLNESS: "褶倍数公式",
}

# ── 工艺 → 用料公式 + 悬挂方式（**唯一口径**；用户 2026-09-19 追加裁定）──────────────────
# 逐字裁定：「**韩褶用韩褶公式算布料，打孔按倍数法算布料，默认选择 2 倍**」
# ⇒ 公式**由工艺推导**（不是自由选择）：韩褶 → 韩褶公式（褶数法）/ 打孔 → 褶倍数公式（倍数法）。
#
# ⚠️ **为什么是「一个入口函数」而不是「中文 key 的映射表」**：本仓的
# `tests/unit_ci_workflows/test_tool_input_contract_guards.py::TestNoNewChineseWordingJudgement`
# 把「含 ≥2 个中文 key 的 dict 字面量」与「`<中文串> in <表达式>`」都算作**中文措辞当判据**的站点，
# 而该基线**只许缩短**（`curtain_calc.py` 在基线里是 0 条）⇒ 新建中文映射表 = 新增豁免（R4 禁止）。
# 本仓的既有先例同族：`routing.SPECIAL_OPTION_ROUTINGS` 是**冻结的 join key**、判据读**契约标识符**，
# 不从散文里猜语义。故这里把「韩褶 / 打孔」两个**契约枚举值**写成显式分支（各自一处，改一个字即红）。
#
# 本函数是**唯一**的 `craft → (formula, mounting)` 判断（前端 `craft-calc-request.ts` 的那份是
# **有守卫的副本**，由 `frontend/admin-web/tests/unit/lib/craft-calc-formula-sync.test.ts`
# 逐值读本文件比对，漂移即红）；`formula` 入参**保留为显式覆盖**（显式 > 本表 > `default_formula` 兜底）。
# 未登记工艺（四爪钩/穿杆/平幔）⇒ `(None, None)` = 不推导（调用方按既有 fail-closed 处理）；
# `''`/`None` ⇒ 同样不推导 ⇒ 兜底默认（韩褶公式 + 调用方给的悬挂方式）。


#: 工艺契约枚举值（与 `CurtainCalcTool.parameters["craft"]["enum"]` **逐字一致**）
CRAFT_S_HOOK = "韩褶"
CRAFT_EYELET = "打孔"
#: 悬挂方式枚举（与 `DEFAULT_FULLNESS` 的键**逐字一致**）
MOUNTING_S_HOOK = "s_hook"
MOUNTING_EYELET = "eyelet"


def resolve_craft_rule(craft: Optional[str]) -> tuple:
    """工艺（契约枚举值）→ `(用料公式, 悬挂方式)`；未登记 ⇒ `(None, None)`。

    登记项（用户 2026-09-19 追加裁定逐字「**韩褶用韩褶公式算布料，打孔按倍数法算布料，默认选择 2 倍**」）：
      · 韩褶 ⇒ 韩褶公式（褶数法）+ `s_hook`；
      · 打孔 ⇒ 褶倍数公式（倍数法）+ `eyelet`（默认 **2 倍**，取自 `DEFAULT_FULLNESS["eyelet"]`，
        与 `DEFAULT_CRAFT_TIERS["standard"]["fullness"]` 同值 —— 不新造第二个 `2.0` 字面量）。
    """
    if craft == CRAFT_S_HOOK:
        return FORMULA_PLEAT, MOUNTING_S_HOOK
    if craft == CRAFT_EYELET:
        return FORMULA_FULLNESS, MOUNTING_EYELET
    return None, None


# ── 算料公式配置（issue #4527，用户追加裁定：「可能得支持每个商家自定义配置」）──────────────
# 口径：**公式参数一律从这个配置对象读**，不得写死在公式体内。`config=None` ⇒ 本默认值。
# 默认值 = 既有模块常量**逐值不变** ⇒ 「不传配置 ⇒ 数值与改前一致」是本模块的回归不变量。
# 持久化 / 商家配置界面属**后续包**（本包不做）；本包只把公式参数做成「可注入 + 默认值」。
#
# ⚠️ 本对象是**只读常量**（`MappingProxyType`）：任何调用方都不得原地修改它
# （并发请求会互相污染）；要改口径请传自己的 config（`resolve_craft_calc_config` 会**深拷贝**嵌套字典）。
DEFAULT_CRAFT_CALC_CONFIG: MappingProxyType = MappingProxyType({
    "per_fold_single": PLEAT_FABRIC_PER_FOLD,                  # 单色每折吃布（米）
    "per_fold_mixed_times": dict(MIXED_COLOR_PER_FOLD_BY_TIMES),  # 拼次 → 每折吃布（米）
    "margin_single": MARGIN_SINGLE,                            # 单开余量（米）
    "margin_multi": MARGIN_MULTI,                              # 多开余量（米）
    "min_fullness": MIN_FULLNESS,                              # 褶倍下限（护栏）
    "tiers": {k: dict(v) for k, v in DEFAULT_CRAFT_TIERS.items()},
    "default_formula": FORMULA_PLEAT,                          # 默认公式 = 韩褶公式
    "side_margin": SIDE_MARGIN,                                # 宽方向左右覆盖余量合计（各 15cm）
    "hem_margin": HEM_MARGIN,                                  # 高方向上下卷边合计（脚位+止口，issue #4976 包 1b）
    "meters_rounding_step": 0.1,                               # 用料米数**向上进位**步长（米）
})

#: 配置里必须是**正数**的键（0/负数 ⇒ 显式报错，不静默回退默认值）
_POSITIVE_CONFIG_KEYS = (
    "per_fold_single", "margin_single", "margin_multi",
    "min_fullness", "side_margin", "hem_margin", "meters_rounding_step",
)


def resolve_craft_calc_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """配置对象 → 校验后的完整配置（缺省键回落到 `DEFAULT_CRAFT_CALC_CONFIG`）。

    **fail-closed**：配置来自商家（**不可信输入**）⇒ 非法值**显式报错**，
    **不得**静默回退默认值（静默 = 算错钱且无人知道）。校验项：

    - 数值键必须 > 0（`per_fold_single` / 余量 / `min_fullness` / `side_margin` / 进位步长）；
    - `per_fold_mixed_times` 的键必须是**正整数**、值必须 > 0；
    - `tiers` 非空，且每档 `fullness` > 0；
    - `default_formula` 必须是已登记的公式名。

    返回的是**新字典**（嵌套字典也拷贝）⇒ 调用方改它不会污染模块级默认配置。
    """
    merged: Dict[str, Any] = {**DEFAULT_CRAFT_CALC_CONFIG, **(config or {})}
    for key in _POSITIVE_CONFIG_KEYS:
        value = merged.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"算料配置 {key} 必须是正数（收到 {value!r}）")
    mixed = merged.get("per_fold_mixed_times")
    if not isinstance(mixed, dict) or not mixed:
        raise ValueError(f"算料配置 per_fold_mixed_times 必须是非空映射（收到 {mixed!r}）")
    for times, per_fold in mixed.items():
        if not isinstance(times, int) or isinstance(times, bool) or times <= 0:
            raise ValueError(f"算料配置 per_fold_mixed_times 的拼次必须是正整数（收到 {times!r}）")
        if not isinstance(per_fold, (int, float)) or isinstance(per_fold, bool) or per_fold <= 0:
            raise ValueError(f"算料配置 per_fold_mixed_times[{times}] 必须是正数（收到 {per_fold!r}）")
    tiers = merged.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise ValueError(f"算料配置 tiers 必须是非空映射（收到 {tiers!r}）")
    for name, tier in tiers.items():
        fullness = (tier or {}).get("fullness") if isinstance(tier, dict) else None
        if not isinstance(fullness, (int, float)) or isinstance(fullness, bool) or fullness <= 0:
            raise ValueError(f"算料配置 tiers[{name}].fullness 必须是正数（收到 {fullness!r}）")
    formula = merged.get("default_formula")
    if formula not in FORMULA_LABELS:
        raise ValueError(
            f"算料配置 default_formula 必须是 {'/'.join(sorted(FORMULA_LABELS))} 之一（收到 {formula!r}）"
        )
    return {**merged, "per_fold_mixed_times": dict(mixed),
            "tiers": {k: dict(v) for k, v in tiers.items()}}


def ceil_to_step(value: float, step: float) -> float:
    """**向上进位**到 `step` 的整数倍（用料米数保留一位小数 = `ceil(x*10)/10`）。

    issue #4527 判据 3：截断 / 四舍五入 ⇒ 红（用料只许向上，不许抹零）。

    ⚠️ 二进制噪声：`2.3 * 10 == 22.999999999999996`、`13.3 * 10 == 133.00000000000003`
    —— 若直接 `ceil`，前者会被当成「要进位」（纸表 12.3 → 12.4）。故先用
    `round(..., 9)` 把 1e-9 级的表示误差吸掉，**再**进位（1e-9 米 = 1 纳米，物理上无意义）。
    """
    if step <= 0:
        raise ValueError(f"进位步长必须是正数（收到 {step}）")
    units = round(value / step, 9)
    return round(math.ceil(units) * step, 9)


def margin_for_open_count(open_count: int = 1, config: Optional[Dict[str, Any]] = None) -> float:
    """打开方式开数 → 侧边余量（米）：单开 0.2 / 多开 0.3（**总**余量，非每片；见 `per_panel_margin`）。"""
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    return cfg["margin_single"] if open_count <= 1 else cfg["margin_multi"]


def per_panel_margin(open_count: int = 1, config: Optional[Dict[str, Any]] = None) -> float:
    """打开方式开数 → **每片**余量（米）= 总余量 ÷ 开数。

    逐片口径（issue #4527）要求 `总用料 = 每片用料 × 开数` 成立。余量是**整幅窗帘**的包边量
    （单开：两侧包边各 10cm；多开：每片外侧包边 10cm + 内侧对缝 5cm —— 真值源 §8），
    若**每片都加满**再乘开数，等于把包边量按开数翻倍（6.6m 双开 13.3 → 13.6 米，
    改钱且无依据）⇒ 每片余量取 `总余量 ÷ 开数`，使 `每片 × 开数` 与既有的总余量**逐值一致**。
    """
    return margin_for_open_count(open_count, config) / open_count


def resolve_per_fold(
    style: Optional[str] = None,
    special_options: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> float:
    """款式/拼次 → 每折吃布（米）。

    口径（用户 2026-09-19 裁定，纸质速查表表头）：
      · `style=拼色` 且部位级特殊选项含 `拼1次` / `拼2次` ⇒ 0.65 / 1.2 米每折；
      · 其余（含 `style=拼色` 但**没给**拼次）⇒ 单色口径 0.25。

    ⚠️ **纸表未登记的拼次**（如 `拼3次`：`mixed_times` 解析得出 3，但配置里没有 3）
    **不在此静默兜底** —— 本函数只负责「有登记系数就取它」，**缺口判定由调用方显式做**
    （`mixed_per_fold_gap`），以免把「未登记」与「单色」混成同一个数（那就是**少算用料**）。
    """
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    if style != STYLE_MIXED:
        return cfg["per_fold_single"]
    for option in special_options or []:
        times = mixed_times(option)
        if times in cfg["per_fold_mixed_times"]:
            return cfg["per_fold_mixed_times"][times]
    return cfg["per_fold_single"]


def mixed_per_fold_gap(
    special_options: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """拼色下**未登记用料系数**的拼次（如 `拼3次`）→ 该选项名；无缺口 → None。

    判据与系数表**同源**：`mixed_times` 解析得出拼次 N，而 N 不在配置的
    `per_fold_mixed_times` 里 ⇒ 缺口。**没有**平行的「未登记清单」可漂移
    （改一处忘一处 = 将来加 `拼4次` 时静默退回单色系数 ⇒ 少算用料）。

    为什么不猜：纸表表头只有「1个折 0.65 / 2个折 1.2」两行，`拼3次` 是**表外**项
    ⇒ 插值（0.65→1.2 线性外推）或退回单色 0.25 都是**发明口径**。调用方据此 fail-closed。
    """
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    for option in special_options or []:
        times = mixed_times(option)
        if times is not None and times not in cfg["per_fold_mixed_times"]:
            return option
    return None


def explicit_accessories(
    accessories: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], float]:
    """顾客**显式**选定的辅料 → (报价明细行, 合计金额)。

    口径（issue #4118，以 #3005 为准）：辅料**只认显式入参** —— 数量、单价必须由调用方给出；
    **不得**由面料米数推导（「每米布 6 个圈」这种密度已随 #3005 回滚，见
    docs/curtain-fabric-quote-rules.md §5：加工费按米打包、圈的成本已含在按米单价里）。

    这正是「允许偏离 vs 编造/推导」的分界（同 #4011 口径纪律）：顾客说「再单独买 40 个圈」
    ⇒ 如实计入；顾客没说 ⇒ 一个都不加，也不替他按米数推算。

    Args:
        accessories: [{"name": "罗马圈", "quantity": 40, "unit_price": 1.5, "unit": "个"}, ...]
                     （unit 可选，默认「个」）

    Returns:
        (明细行 list, 合计金额)

    Raises:
        ValueError: 缺名称 / 缺数量或单价 / 数量非正 / 单价为负（fail-closed：
                    既不猜默认值，也不静默丢弃顾客的显式选择）。
    """
    rows: List[Dict[str, Any]] = []
    total = 0.0
    for idx, item in enumerate(accessories or [], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx} 项辅料格式不对：应为对象（含 name/quantity/unit_price）")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"第 {idx} 项辅料缺少名称（name）")
        try:
            quantity = float(item["quantity"])
            unit_price = float(item["unit_price"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                f"辅料「{name}」必须同时给出 quantity（数量）与 unit_price（单价）——"
                "辅料数量由顾客显式给出，系统不按面料米数推导"
            ) from None
        if quantity <= 0:
            raise ValueError(f"辅料「{name}」数量须大于 0（收到 {quantity}）")
        if unit_price < 0:
            raise ValueError(f"辅料「{name}」单价不能为负（收到 {unit_price}）")
        unit = str(item.get("unit") or "个")
        cost = quantity * unit_price
        rows.append({
            "name": name,
            "detail": f"{quantity:g}{unit} × ¥{unit_price:g}/{unit}",
            "cost": round(cost, 2),
        })
        total += cost
    return rows, total


def derive_pleat_count(
    width: float,
    fullness: float,
    open_count: int = 1,
    config: Optional[Dict[str, Any]] = None,
) -> tuple[int, str]:
    """倍数意图 → 褶数实现（按开数取整：对开偶数 / 四开 4 的倍数）。

    褶数按**单色每折吃布**（`per_fold_single`，默认 0.25）反算 —— 这是既有口径（issue #4421），
    **本包不改**：拼色只改「每折吃布」这一项（`calculate_fabric_by_pleats` 的 `per_fold`），
    褶数仍是 52（改褶数 = 改既有的拼色数值 34.1 / 62.7 米，属改钱、不在本包）。

    红线：fullness < `min_fullness`（默认 1.5，护栏，可配但**不可关**）拒绝。
    Returns: (褶数, 告警) — 告警非空表示做过取整调整。
    """
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    if fullness < cfg["min_fullness"]:
        raise ValueError(
            f"褶皱倍数 {fullness} 低于行业下限 {cfg['min_fullness']}，影响美观，请选择更高倍数档位"
        )
    pleats = int(
        round((width * fullness - margin_for_open_count(open_count, cfg)) / cfg["per_fold_single"])
    )
    pleats = max(pleats, open_count)
    if open_count > 1:
        adjusted = math.ceil(pleats / open_count) * open_count
    else:
        adjusted = pleats
    warning = (
        f"褶数 {pleats} 无法被开数 {open_count} 整除，已取最近可行 {adjusted} 折"
        if adjusted != pleats else ""
    )
    return adjusted, warning


def calculate_fabric_by_pleats(
    pleat_count: int,
    open_count: int = 1,
    source: str = "formula",
    width: Optional[float] = None,
    per_fold: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> tuple[float, str, dict]:
    """褶数法算料（**逐片**口径，issue #4527）：总用料 = 每片用料 × 开数。

    每片用料 = `per_fold`（每折吃布，米）× 每片褶数 + `per_panel_margin`（每片余量，米）；
    每片褶数 = 总褶数 ÷ 开数。**每片余量 = 总余量 ÷ 开数** ⇒ `每片 × 开数` 与既有的
    「`per_fold × 总褶数 + 总余量`」**逐值一致**（不改钱；见 `per_panel_margin` 的口径说明）。

    `per_fold` = 每折吃布（米）：单色 `per_fold_single`（缺省 0.25）；拼色走
    `per_fold_mixed_times`（拼1次 0.65 / 拼2次 1.2 —— 用户 2026-09-19 裁定）。**余量不随拼色变化**。

    用料米数**向上进位**到 `meters_rounding_step`（默认 0.1，issue #4527 判据 3）——
    进位在**总用料**上做一次，**不得**先对每片进位再乘开数（那会多算 ≤ 0.2 米）。

    开数不可整除时自动取最近可行褶数并告警。
    Returns: (用料米数, 告警, 褶数信息 dict)
    """
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    warning = ""
    if open_count > 1 and pleat_count % open_count != 0:
        adjusted = math.ceil(pleat_count / open_count) * open_count
        warning = f"褶数 {pleat_count} 无法被开数 {open_count} 整除，已取最近可行 {adjusted} 折"
        pleat_count = adjusted
    coefficient = cfg["per_fold_single"] if per_fold is None else per_fold
    per_panel_pleats = pleat_count // open_count if open_count > 1 else pleat_count
    margin_per_panel = per_panel_margin(open_count, cfg)
    per_panel_meters = coefficient * per_panel_pleats + margin_per_panel
    meters = ceil_to_step(per_panel_meters * open_count, cfg["meters_rounding_step"])
    info = {
        "pleat_count": pleat_count,
        "per_panel_pleats": per_panel_pleats,
        "per_panel_meters": round(per_panel_meters, 4),
        "open_count": open_count,
        "margin": margin_for_open_count(open_count, cfg),
        "per_fold": coefficient,
        "source": source,
    }
    if width:
        info["fullness_actual"] = round(meters / width, 2)
    return meters, warning, info


def aggregate_by_fabric(positions: List[Dict[str, Any]]) -> Dict[str, float]:
    """按货号-色号汇总用料（采购/套裁视图）。

    Args:
        positions: [{fabric_code, meters}, ...]
    Returns: {fabric_code: 合计米数}
    """
    agg: Dict[str, float] = {}
    for p in positions:
        code = p.get("fabric_code") or "未指定"
        agg[code] = round(agg.get(code, 0.0) + float(p.get("meters", 0.0)), 2)
    return agg


# ── 自动特征（超高 / 超宽 / 倒幅）：**服务端判定**（issue #4976 包 1a）────────────────────
# 用户 2026-09-21 裁定 B：「**判定移到服务端**」（前端只展示服务端结论）。
# 判据与 `frontend/admin-web/src/lib/craft-auto-features.ts` **同式**（措辞也逐字对齐）——
# 前端退场（包 2）后，本函数成为**唯一**真值源；在此之前两者并存（照实登记在 PR 描述里）。
#
# ⚠️ **两个方向各自受门幅约束，取决于加工类型**（用户 2026-09-20 裁定
# 「定高买宽的话就不用算超宽，定宽买高就不用算超高」）：
#   定高买宽 ⇒ 只判**超高**（宽按米买、无上限）
#   定宽买高 ⇒ 只判**超宽**（= 引擎真实的分幅条件）+ **倒幅**
#   缺省 / 表外取值 ⇒ **都不判**（保守：不猜朝向）
# 常量的唯一落点仍是上面那两行（`SIDE_MARGIN` / `HEM_MARGIN`）—— 本段不新造第二个数。
# ⚠️ 两个常量同时是**配置键的默认值**（`side_margin` / `hem_margin`，issue #4976 包 1b）：
# 引擎函数体里一律读 `cfg[...]`，常量只出现在配置字典那一行。

#: 加工类型 `定高买宽` —— **高**方向受门幅约束 ⇒ 只判 `超高`
CUTTING_MODE_FIXED_HEIGHT = "定高买宽"
#: 加工类型 `定宽买高` —— **宽**方向受门幅约束（分幅）⇒ 只判 `超宽`（+ `倒幅`）
CUTTING_MODE_FIXED_WIDTH = "定宽买高"


def _meters_for_reason(value: float, door_width: float) -> float:
    """判定文案里的米数：取整到毫米；**只有「取整把严格大于抹平了」**这一种情况才给全精度。

    与前端 `craft-auto-features.ts::metersForReason` 同款 —— 否则商家看到的是
    「2.8 米 > 门幅 2.8 米」这种**自相矛盾的依据**（判据要能自证）。
    """
    rounded = round(value, 3)
    return rounded if (rounded > door_width or value <= door_width) else value


def detect_auto_features(
    window_width: Optional[float],
    window_height: Optional[float],
    fabric_width: Optional[float],
    fullness: Optional[float] = None,
    cutting_mode: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """系统**自动推算**的特征（`超高` / `超宽` / `倒幅`）—— issue #4976 包 1a。

    这三项会**进加工费组合键**（商家按「韩折+超宽+定型」这类组合配价），所以判定必须唯一：
    本函数是**服务端**的判定实现（用户裁定 B），前端退场后它就是唯一真值源。

    Args:
        window_width: 成品宽（米）；`None` / 非正 ⇒ **不判超宽**（`倒幅` 照判 —— 它只取决于加工类型）
        window_height: 成品高（米）；`None` / 非正 ⇒ **不判超高**（不回落任何默认层高）
        fabric_width: **该商品/SKU 的门幅**（米）—— 权威值由调用方传入；
            `None` ⇒ **超宽/超高都不判**（**不回落**模块常量，issue #4877：门幅没有缺省值），
            但 **`倒幅` 照判**（它只取决于加工类型、与门幅无关 —— issue #5033）
        fullness: **名义**褶倍（档位值）；缺失 / 非正 ⇒ **不判超宽**（不拿一个假褶倍去判价）
        cutting_mode: 加工类型（`定高买宽` / `定宽买高`）；缺省 / 表外 ⇒ **都不判**
        config: 租户级算料配置（`side_margin` 取自它；缺省 ⇒ 引擎默认值）

    Returns:
        `[{"name", "source", "reason"}, ...]`：顺序 = `超宽 → 超高 → 倒幅` 中命中的那些；
        **空列表 = 不判**（不是「没算」—— `build_quote` 的该键**恒在**）。

    ⚠️ **判据是行业推理、非 ERP 实证** ⇒ 一律标 `source="推算"`（与前端同口径）。
    """
    cfg = resolve_craft_calc_config(config)
    features: List[Dict[str, str]] = []
    if cutting_mode not in (CUTTING_MODE_FIXED_HEIGHT, CUTTING_MODE_FIXED_WIDTH):
        return features  # 不猜朝向（与前端同款：缺省/表外取值一个都不判）

    if cutting_mode == CUTTING_MODE_FIXED_WIDTH:
        side_margin = cfg["side_margin"]
        # 判据 = 引擎**真实的分幅条件** `ceil((宽 + 余量) × 褶倍 ÷ 门幅) ≥ 2`
        # ⟺ `(宽 + 余量) × 褶倍 > 门幅`（原始浮点，不取整 —— 取整会漏报，见前端同款注释）
        # ⚠️ 宽 / 褶倍缺失 ⇒ **不判**（调用方可能只给了高；不拿假值去判价）
        # ⚠️ 宽 / 褶倍 / **门幅**缺失 ⇒ **不判超宽**（调用方可能只给了高，或该 SKU 未维护门幅；
        # 不拿假值去判价 —— issue #4877：门幅**没有**缺省值）。
        # 🔴 `fabric_width is not None` 这条守卫是 **#5033** 的根因修复：缺了它，
        # `product > fabric_width` 会抛 `TypeError` ⇒ 调用方（判定端点）只能**短路**，
        # 而短路会把**与门幅无关**的 `倒幅` 一起吞掉 ⇒ 组合键少一项（改钱）。
        if (
            fabric_width is not None
            and window_width is not None
            and fullness is not None
            and fullness > 0
        ):
            product = (window_width + side_margin) * fullness
            if product > fabric_width:
                features.append({
                    "name": "超宽",
                    "source": "推算",
                    "reason": (
                        f"成品宽 {window_width} + 左右余量 {side_margin} = "
                        f"{round(window_width + side_margin, 3)} 米"
                        f" × 褶倍 {fullness} = {_meters_for_reason(product, fabric_width)} 米"
                        f" > 门幅 {fabric_width} 米"
                    ),
                })
        # 倒幅只取决于加工类型（与褶倍无关）：布旋转九十度用
        features.append({
            "name": "倒幅",
            "source": "推算",
            "reason": f"加工类型 = {CUTTING_MODE_FIXED_WIDTH}",
        })
    elif (
        fabric_width is not None
        and window_height is not None
        and window_height + cfg["hem_margin"] > fabric_width
    ):
        # 定高买宽：只有**高**受门幅约束（`成品高 + 上下卷边 > 门幅` ⇒ 定高买宽不可行）
        # ⚠️ `fabric_width is not None` = 该 SKU 未维护门幅 ⇒ **不判超高**（不回落缺省门幅）。
        features.append({
            "name": "超高",
            "source": "推算",
            "reason": (
                f"成品高 {window_height} + 上下卷边 {cfg['hem_margin']} = "
                f"{_meters_for_reason(window_height + cfg['hem_margin'], fabric_width)} 米"
                f" > 门幅 {fabric_width} 米"
            ),
        })
    return features


#: 提示（notice）类别 —— ⚠️ **不是特征**：不进 `AUTO_FEATURE_NAMES`、不进加工费组合键。
NOTICE_MISSING_DOOR_WIDTH = "missing-door-width"
NOTICE_MISSING_FULLNESS = "missing-fullness"
NOTICE_CUTTING_MODE_CONFLICT = "cutting-mode-conflict"


def _num(value: float) -> str:
    """数字 → 与**前端模板串逐字一致**的文本（issue #5036 迁移期等价性）。

    JS `` `${2.0}` `` → ``2``，而 Python ``f"{2.0}"`` → ``2.0`` —— 直接用 f-string 会让
    「同一输入的提示文案」在迁移前后**字面不同**（`#4976` 复核时实测过这条漂移：包 1a 那句
    「与下单页同一句」**旧值从未相等**）。提示搬到服务端后商家看到的就是引擎这句 ⇒ 必须钉住。

    ⚠️ 只服务**新迁移的提示文案**；`detect_auto_features` 的既有措辞**不动**（它的同款漂移是
    已登记的独立项，改它要动已钉住的措辞断言 —— 那是另一件事）。
    """
    number = float(value)
    return str(int(number)) if number == int(number) else repr(number)


def detect_auto_feature_notices(
    window_width: Optional[float],
    window_height: Optional[float],
    fabric_width: Optional[float],
    fullness: Optional[float] = None,
    cutting_mode: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """系统识别的**提示**（`missing-door-width` / `missing-fullness` / `cutting-mode-conflict`）
    —— issue #5036（用户 2026-09-21 裁定「**需要统一迁移到服务端；未来 agent 也需要**」）。

    与 :func:`detect_auto_features` 是**兄弟函数**（同入参、同配置口径），职责不同：
    判定**进加工费组合键**（判定即钱）；提示**只说明**「为什么没判」或「系统实际会按哪种算」
    —— **不进组合键、不改判定**（用户 2026-09-20 裁定 C 的前半句「以商家选的为准」）。

    🔴 **为什么必须搬服务端**（迁移前的缺陷形态）：提示读的是前端**模块常量副本**
    （宽 / 高两个余量常量，都是 `0.3`），而判定读**该租户配置**
    ⇒ #5005 把 `hem_margin` 做成可配之后，商家改过配置就会看到**错的数**，
    且「几何矛盾」的**判断本身**也会错。本函数一律读 `cfg`（**不新造第二份常量**）。

    Args:
        window_width: 成品宽（米）；缺 ⇒ 不提示「缺褶倍」（没有依据就不下结论）
        window_height: 成品高（米）；缺 ⇒ 不提示「几何矛盾」（该判据依赖它）
        fabric_width: **该商品/SKU 的门幅**（米）；缺 ⇒ `missing-door-width`
            （**不回落任何缺省门幅**，issue #4877）
        fullness: 名义褶倍；缺 / 非正 ⇒ `missing-fullness`（**只在定宽买高且宽已知时**）
        cutting_mode: 加工类型；缺省 / 表外 ⇒ **一条都不提示**（不猜朝向）
        config: 租户级算料配置（读 `side_margin` / `hem_margin`；缺省 ⇒ 引擎默认值）

    Returns:
        `[{"kind", "reason"}, ...]`；**空列表 = 无提示**。
    """
    notices: List[Dict[str, str]] = []
    if cutting_mode not in (CUTTING_MODE_FIXED_HEIGHT, CUTTING_MODE_FIXED_WIDTH):
        return notices  # 加工类型未知 ⇒ 提示的前提句无从谈起（与前端同款）

    cfg = resolve_craft_calc_config(config)
    side_margin = cfg["side_margin"]
    hem_margin = cfg["hem_margin"]

    if fabric_width is None:
        # 缺门幅 ⇒ 判定面**什么都没判**（issue #4877）⇒ 显式告知并直接返回：
        # 再做「缺褶倍」「几何矛盾」两条提示会误导（它们的前提都依赖门幅）。
        notices.append({
            "kind": NOTICE_MISSING_DOOR_WIDTH,
            "reason": "该 SKU 未维护门幅 ⇒ 超高/超宽都判不了（系统不按缺省门幅推算，请先补商品门幅）",
        })
        return notices

    # ① 缺褶倍 ⇒ 未判超宽（只在「该方向真的受门幅约束」且宽已知时才说得通）
    has_fullness = (
        isinstance(fullness, (int, float)) and not isinstance(fullness, bool) and fullness > 0
    )
    if cutting_mode == CUTTING_MODE_FIXED_WIDTH and window_width is not None and not has_fullness:
        notices.append({
            "kind": NOTICE_MISSING_FULLNESS,
            "reason": (
                f"缺褶倍 ⇒ 未判超宽（成品宽 {_num(window_width)} + 左右余量 {_num(side_margin)} "
                f"是否要分幅取决于褶倍，不猜）"
            ),
        })

    # ② 几何矛盾：引擎按「高 + 上下卷边 vs 门幅」**唯一**决定实际档位（与 `超高` 同一条判据）
    if window_height is not None:
        over_height = window_height + hem_margin > fabric_width
        actual_mode = CUTTING_MODE_FIXED_WIDTH if over_height else CUTTING_MODE_FIXED_HEIGHT
        if actual_mode != cutting_mode:
            notices.append({
                "kind": NOTICE_CUTTING_MODE_CONFLICT,
                "reason": (
                    f"加工类型选了「{cutting_mode}」，但成品高 {_num(window_height)} + 上下卷边 "
                    f"{_num(hem_margin)} = "
                    f"{_num(_meters_for_reason(window_height + hem_margin, fabric_width))} 米 "
                    f"{'超过' if over_height else '未超过'}本 SKU 门幅 {_num(fabric_width)} 米"
                    "（判据 = 算料引擎的几何分支「高 + 卷边 vs 门幅」，不读商家选的加工类型）"
                    f"⇒ 按本 SKU 门幅口径，系统实际会按{actual_mode}算"
                    "（⚠️ 引擎试算门幅尚未按本 SKU 门幅接线 —— #4746 / 待 #4652 ⇒ 引擎实际结果可能不同）"
                ),
            })

    return notices


#: 门幅规则的**四态裁决**（issue #5043 包 2b）—— 与前端 `door-width-plan.ts::judgeDoorWidthChoice`
#: **逐条对齐**（前端退场后这里是唯一实现）。
DOOR_WIDTH_VERDICT_OPTIMAL = "optimal"
DOOR_WIDTH_VERDICT_SUBOPTIMAL = "suboptimal"
DOOR_WIDTH_VERDICT_INFEASIBLE = "infeasible"
DOOR_WIDTH_VERDICT_UNKNOWN = "unknown"


def judge_door_width_choice(
    plan: Dict[str, Any],
    *,
    window_height: Optional[float] = None,
    selected_door_width: Optional[float] = None,
    selected_panels: Optional[int] = None,
    allowance: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """客服所选门幅 ⇒ 相对**规则解**的判定与建议（issue #5043 包 2b）。

    三条边界（与前端同款，**一字不放宽**）：
    ① **未选 ⇒ `unknown`**（不提示「最优」—— 没有可比对象）；
    ② **所选门幅不可行 ⇒ `infeasible`**（比「非最优」更强：先告警「需接高」，再给规则解）；
    ③ **并列最优不提示**：定宽买高下**分幅数相同 = 米数相同** ⇒ 判 `optimal`（挑哪个门幅是
       库存/单价的事，系统不 nag）。

    Args:
        plan: `build_quote(..., fabric_widths=[...])` 的返回值（含 `door_width` / `cutting_mode` /
            `splice` / `panels`）—— **规则解由它给**，本函数**不重算规则**。
        window_height: 成品高（米）；定高买宽下判「所选门幅单幅做不做得出」用
        selected_door_width: 客服所选门幅（米）；缺 / 非正 ⇒ `unknown`
        selected_panels: **所选门幅**的分幅数（由调用方用**同一份口径**算出；定宽买高裁决用）
        allowance: 门幅有效余量（米）
        config: 算料配置（读 `hem_margin`；**不新造第二份常量**）

    Returns:
        `{"verdict": <四态之一>, "suggestion": <可执行建议 | None>}`
    """
    cfg = resolve_craft_calc_config(config)
    hem_margin = cfg["hem_margin"]
    selected = (
        float(selected_door_width)
        if isinstance(selected_door_width, (int, float))
        and not isinstance(selected_door_width, bool)
        and selected_door_width > 0
        else None
    )
    if selected is None:
        return {"verdict": DOOR_WIDTH_VERDICT_UNKNOWN, "suggestion": None}

    allow = max(float(allowance or 0.0), 0.0)
    selected_eff = round(selected - allow, 3)
    door_width = plan.get("door_width")

    if plan.get("splice"):
        return {
            "verdict": DOOR_WIDTH_VERDICT_INFEASIBLE,
            "suggestion": (
                f"所选 {_num(selected)} 米门幅单幅做不出成品高 —— 本单**没有任何门幅**能单幅做成"
                "（规则解同此结论，需接高）"
            ),
        }
    if door_width == selected:
        return {"verdict": DOOR_WIDTH_VERDICT_OPTIMAL, "suggestion": None}

    if plan.get("cutting_mode") == CUTTING_MODE_FIXED_HEIGHT:
        if window_height is None:
            return {"verdict": DOOR_WIDTH_VERDICT_UNKNOWN, "suggestion": None}
        need_height = round(float(window_height) + hem_margin, 3)
        if need_height > selected_eff:
            return {
                "verdict": DOOR_WIDTH_VERDICT_INFEASIBLE,
                "suggestion": (
                    f"所选 {_num(selected)} 米门幅单幅做不出（成品高 {_num(window_height)} + 上下卷边 "
                    f"{_num(hem_margin)} = {_num(need_height)} 米，缺口 "
                    f"{_num(round(need_height - selected_eff, 3))} 米 ⇒ **需接高**）；"
                    f"规则解 = {_num(door_width)} 米门幅"
                ),
            }
        return {
            "verdict": DOOR_WIDTH_VERDICT_SUBOPTIMAL,
            "suggestion": (
                f"规则解是 {_num(door_width)} 米门幅（可行集里最小：成品高 {_num(window_height)} + "
                f"上下卷边 {_num(hem_margin)} = {_num(need_height)} 米 ≤ {_num(door_width)} 米）"
                "—— 换它可少占宽幅布（宽幅布留给真正超高的窗）"
            ),
        }

    rule_panels = plan.get("panels")
    if not isinstance(rule_panels, int) or not isinstance(selected_panels, int):
        return {"verdict": DOOR_WIDTH_VERDICT_UNKNOWN, "suggestion": None}
    if selected_panels <= rule_panels:
        return {"verdict": DOOR_WIDTH_VERDICT_OPTIMAL, "suggestion": None}
    per_panel = round((float(window_height) if window_height is not None else 0.0) + hem_margin, 3)
    return {
        "verdict": DOOR_WIDTH_VERDICT_SUBOPTIMAL,
        "suggestion": (
            f"所选 {_num(selected)} 米门幅要 {selected_panels} 幅；规则解 {_num(door_width)} 米只要 "
            f"{rule_panels} 幅（少 {selected_panels - rule_panels} 幅 × 每幅 {_num(per_panel)} 米用料）"
        ),
    }


#: **人工覆盖**值：接高 —— ⚠️ 它**不是** `cuttingMode` 的取值（ERP 加工类型只有上面两项）：
#: 它 = 「定高买宽 + 接高工序」。故本值只作 `resolve_fabric_plan` 的**入参**；
#: 返回值里 `cutting_mode` 恒为前两者之一，另带 `splice` 布尔 —— 不发明第三个加工类型值。
CUTTING_MODE_SPLICE = "接高"

#: 门幅 / 用料计算的**领域精度**（毫米）。为什么用整数：`math.floor(3.2 / 0.1)` 在二进制浮点下
#: 可能是 31 而非 32（`0.1` 不可精确表示）⇒ 并排条数**少算一条**、接高料凭空变贵，且没有任何东西会红。
_MM = 1000


def _mm(value: float) -> int:
    """米 → 整数毫米（四舍五入）。"""
    return int(round(float(value) * _MM))


def resolve_fabric_plan(
    *,
    window_height: float,
    fixed_height_meters: float,
    door_widths: List[float],
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
    allowance: float = 0.0,
    open_count: int = 1,
    cutting_mode: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """**门幅与加工类型的自动选择**（issue #5013，用户 2026-09-21 裁定）。

    口径真值源 = `docs/design/door-width-auto-selection.md`（判据表 = 该文档 §4）。
    自动规则 = **行业口径**：定高买宽（可行）> 倒幅；**接高不参与自动比较**（接高是**上下拼接、
    横缝可见**，而行业实践是超高窗走倒幅把**竖缝藏进褶皱**）⇒ 接高退为**人工覆盖项**。

    Args:
        window_height: 成品高（米）—— 顾客给的尺寸**直接就是成品高**（不做离地/轨道换算）
        fixed_height_meters: **定高买宽用料 T**（米）—— 由调用方按选定用料公式算好（本函数**不改公式**）。
            倒幅分幅数与接高片宽**都由它派生** ⇒ 两者同源，不会各算一份。
        door_widths: 候选门幅（米，来自该颜色的 SKU）；非法值**剔除**，不默认成任何值
        has_pattern / pattern_repeat: 对花 —— 倒幅「每幅 +1 花距」、接高「每条加高条 +1 花距」同口径
        allowance: 门幅**有效余量**（米：缩水/边损/对花回）；缺省 `0`（= 与标称同值）
        open_count: 开数（接高的片宽与加高条段数需要）
        cutting_mode: `None` ⇒ **自动**；也可显式传 `定高买宽` / `定宽买高` / `接高`（人工覆盖）。
            显式 `定高买宽` 而高度超限 ⇒ **接高**（= #4877 的旧语义，本单保留为人工覆盖路径）。
        config: 算料配置（读 `hem_margin`；**不新造第二份常量**）

    Returns:
        `cutting_mode`（**恒为** `定高买宽`/`定宽买高` 之一）/ `door_width` / `effective_door_width` /
        `panels`（定宽买高 ⇒ 分幅数；其余 ⇒ `None`）/ `splice` / `splice_gap` / `splice_strips` /
        `meters`（**未进位** —— 进位由 `build_quote` 单点负责）/ `auto` / `reason`

    Raises:
        ValueError: 加工类型表外 / 候选门幅全无效（**fail-closed，不静默回退缺省门幅**）
    """
    cfg = resolve_craft_calc_config(config)
    hem_margin = cfg["hem_margin"]

    if cutting_mode not in (
        None, CUTTING_MODE_FIXED_HEIGHT, CUTTING_MODE_FIXED_WIDTH, CUTTING_MODE_SPLICE
    ):
        raise ValueError(
            f"加工类型必须是 {CUTTING_MODE_FIXED_HEIGHT} / {CUTTING_MODE_FIXED_WIDTH} / "
            f"{CUTTING_MODE_SPLICE} 之一，或留空走自动（收到 {cutting_mode!r}）"
        )

    allow = max(float(allowance or 0.0), 0.0)
    candidates = sorted({
        (float(g), round(float(g) - allow, 3))
        for g in (door_widths or [])
        if isinstance(g, (int, float)) and not isinstance(g, bool) and float(g) > allow
    })
    if not candidates:
        raise ValueError("候选门幅为空或全部无效 —— 不按缺省门幅推算（fail-closed）")

    total = float(fixed_height_meters)
    pieces = max(1, int(open_count))
    repeat = float(pattern_repeat) if has_pattern else 0.0
    need_height = round(float(window_height) + hem_margin, 3)
    feasible = [(g, ge) for g, ge in candidates if need_height <= ge]
    widest_width, widest_eff = candidates[-1]
    auto = cutting_mode is None

    def _fixed_height() -> Dict[str, Any]:
        width, eff = feasible[0]  # candidates 升序 ⇒ 可行集里**最小**门幅
        return {
            "cutting_mode": CUTTING_MODE_FIXED_HEIGHT,
            "door_width": width,
            "effective_door_width": eff,
            "panels": None,
            "splice": False,
            "splice_gap": 0.0,
            "splice_strips": 0,
            "meters": total,
            "auto": auto,
            "reason": (
                f"成品高 {window_height} + 上下卷边 {hem_margin} = {need_height} 米 ≤ "
                f"门幅 {width} 米（有效 {eff} 米）⇒ 定高买宽单幅可做，取**可行集里最小门幅**"
                f"（用料 {round(total, 3)} 米与门幅无关 ⇒ 取小 = 不占宽幅布）"
            ),
        }

    def _splice() -> Dict[str, Any]:
        gap = round(need_height - widest_eff, 3)
        gap_eff = round(gap + repeat, 3)  # 对花：每条加高条 +1 个花距
        # 一段布（长 = 片宽）能在门幅内**并排**裁出几条加高条 —— 毫米整数除，避免浮点 floor 少算一条
        per_piece = max(1, _mm(widest_eff) // max(1, _mm(gap_eff)))
        strips = max(1, -(-pieces // per_piece))
        piece_width = total / pieces
        meters = total + strips * piece_width
        return {
            "cutting_mode": CUTTING_MODE_FIXED_HEIGHT,
            "door_width": widest_width,
            "effective_door_width": widest_eff,
            "panels": None,
            "splice": True,
            "splice_gap": gap,
            "splice_strips": strips,
            "meters": meters,
            "auto": auto,
            "reason": (
                f"成品高 {window_height} + 上下卷边 {hem_margin} = {need_height} 米 > 最宽门幅 "
                f"{widest_width} 米（有效 {widest_eff} 米）⇒ 缺口 {gap} 米"
                + (f" + 花距 {repeat} 米（对花对齐）" if repeat else "")
                + f" ⇒ 接高：加高条 {strips} 段 × 片宽 {round(piece_width, 3)} 米，共 "
                f"{round(meters, 3)} 米（**加高条按片宽另买**，不从缺口面积折料）"
            ),
        }

    def _fixed_width() -> Dict[str, Any]:
        ranked = sorted(
            ((-(-_mm(total) // max(1, _mm(ge))), ge, g) for g, ge in candidates),
            key=lambda item: (item[0], item[1]),
        )
        panels, eff, width = ranked[0]
        return {
            "cutting_mode": CUTTING_MODE_FIXED_WIDTH,
            "door_width": width,
            "effective_door_width": eff,
            "panels": panels,
            "splice": False,
            "splice_gap": 0.0,
            "splice_strips": 0,
            "meters": panels * (need_height + repeat),
            "auto": auto,
            "reason": (
                f"成品高 {window_height} + 上下卷边 {hem_margin} = {need_height} 米 > 所有候选门幅"
                f"（最宽 {widest_width} 米，有效 {widest_eff} 米）⇒ **倒幅**（定宽买高，"
                f"竖缝藏进褶皱）：用料 {round(total, 3)} 米 ÷ 门幅 {width} 米 ⇒ {panels} 幅"
                f"（取分幅最少；并列取较小门幅）"
            ),
        }

    if cutting_mode == CUTTING_MODE_FIXED_WIDTH:
        return _fixed_width()
    if cutting_mode == CUTTING_MODE_SPLICE:
        # 成品高未超门幅 ⇒ 无可接之处，如实走单幅（**显式告知，不静默**）
        return _fixed_height() if feasible else _splice()
    if cutting_mode == CUTTING_MODE_FIXED_HEIGHT:
        return _fixed_height() if feasible else _splice()
    # 自动（裁定 4）：定高买宽可行 ⇒ 它；否则 ⇒ **倒幅**。接高**不参与自动比较**。
    return _fixed_height() if feasible else _fixed_width()


def calculate_fabric_meters(
    window_width: float,
    window_height: float,
    fullness: float,
    fabric_width: float,
    mounting: str = "eyelet",
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
) -> tuple[float, str, str]:
    """计算窗帘面料用量（米）—— **倍数法**（`formula='fullness'` / 非褶数法悬挂方式）。

    Args:
        window_width: 窗宽（米）
        window_height: 窗高（米，成品窗帘高度）
        fullness: 褶皱倍数
        fabric_width: 面料门幅（米）
        mounting: 悬挂方式（eyelet/s_hook/hook/roman）
        has_pattern: 是否需要对花
        pattern_repeat: 花距（米），对花时有效
        config: 算料配置（issue #4527）；None ⇒ `DEFAULT_CRAFT_CALC_CONFIG`

    Returns:
        (meters, formula_used, warning)
        formula_used: fixed_height（定高买宽）/ fixed_width（定宽买高）/ roman_panel（罗马帘）
        warning: 非空字符串表示存在工程告警（如窗高超定高上限）
    """
    cfg = config or DEFAULT_CRAFT_CALC_CONFIG
    # 罗马帘：无褶皱倍率，按包边计算
    if mounting == "roman":
        meters = (window_width + ROMAN_SIDE) * (window_height + cfg["hem_margin"])
        return meters, "roman_panel", ""

    # 定高布可用条件：成品高 + 卷边 ≤ 门幅（2.8m 定高上限成品高约 2.5m）
    if window_height + cfg["hem_margin"] <= fabric_width:
        # 定高买宽：M = (W + 0.3) × N（逐片表达同值：每片宽 × N × 开数 —— 与开数无关，issue #4527 判据 5）
        meters = (window_width + cfg["side_margin"]) * fullness
        return meters, "fixed_height", ""

    # 定宽买高：幅数向上取整，每幅长 = 窗高 + 卷边（+ 对花花距）
    panels = math.ceil((window_width + cfg["side_margin"]) * fullness / fabric_width)
    panel_length = window_height + cfg["hem_margin"]
    if has_pattern:
        panel_length += pattern_repeat
    meters = panels * panel_length
    warning = (
        f"成品高 {window_height:.2f}m 超过门幅 {fabric_width:.2f}m 的定高上限，"
        f"已按定宽布（买高）计算，幅数 {panels} 幅。"
    )
    return meters, "fixed_width", warning


def _per_panel_fullness_meters(
    window_width: float, open_count: int, fullness: float, config: Dict[str, Any],
) -> tuple[float, float, float]:
    """褶倍数公式（倍数法）的**逐片**表达 → (总用料米数, 每片用料, 每片宽)。

    每片宽 = 成品宽 ÷ 开数；每片用料 = 每片宽 × 褶倍；总用料 = 每片用料 × 开数
    （**数值恒等于「成品宽 × 褶倍」** —— 线性，与开数无关）。

    ⚠️ 这正是 issue #4527 判据 5 的落点：「总宽再 × 开数」（甲口径）会让双开算成 22.00 米，
    与 ERP 实证锚点（`CSO260915-02615`：5.5m 双开 2.00 倍 ⇒ 11.00 米）差一倍 ⇒ 已被用户否决。
    """
    per_panel_width = window_width / open_count
    per_panel_meters = per_panel_width * fullness
    total = ceil_to_step(per_panel_meters * open_count, config["meters_rounding_step"])
    return total, per_panel_meters, per_panel_width


def _formula_text(
    formula: str,
    window_width: float,
    margin: float,
    fullness: float,
    pleat_count: int,
    open_count: int,
    meters: float,
    per_fold: float,
) -> str:
    """可读公式串 —— **后端产出**，与数值同源（issue #4421 交付物 1 / issue #4527 判据 4）。

    必须**明确写出所用公式**（`韩褶公式：` / `褶倍数公式：`）—— 静默走另一支 = 红。

    - 韩褶公式（褶数法）：`韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米`；
    - 褶倍数公式（倍数法）：`褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11米`。

    数字全部取自**同一次算料** ⇒ 公式串不可能与米数不一致；前端**不得**自拼。
    """
    label = FORMULA_LABELS.get(formula, formula)
    if formula == FORMULA_FULLNESS:
        per_panel_width = window_width / open_count
        per_panel_meters = per_panel_width * fullness
        return (
            f"{label}：({window_width:g}÷{open_count:g})×{fullness:g} → "
            f"每片 {per_panel_width:g}×{fullness:g}={per_panel_meters:g}米 ×{open_count:g}片 = {meters:.1f}米"
        )
    return (
        f"{label}：({window_width:g}+{margin:g})×{fullness:g} → {pleat_count:g}折 → "
        f"{per_fold:g}×{pleat_count:g}+{margin:g} = {meters:g}米"
    )


def build_quote(
    window_width: float,
    window_height: float,
    mounting: str = "eyelet",
    fullness: Optional[float] = None,
    fabric_width: float = 2.8,
    fabric_price: float = 30.0,
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
    open_count: int = 1,
    pleat_count: Optional[int] = None,
    source: str = "formula",
    craft_tier: Optional[str] = None,
    accessories: Optional[List[Dict[str, Any]]] = None,
    curtain_type: Optional[str] = None,
    craft: Optional[str] = None,
    is_shaped: Optional[bool] = None,
    style: Optional[str] = None,
    special_options: Optional[List[str]] = None,
    formula: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    cutting_mode: Optional[str] = None,
    fabric_widths: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """构建完整报价单。

    Args:
        window_width: 窗宽（米）
        window_height: 窗高（米）
        mounting: 悬挂方式（默认 eyelet）
        fullness: 褶皱倍数（None 时按悬挂方式默认值）
        fabric_width: 面料门幅（默认 2.8 米）
        fabric_price: 面料单价（元/米）
        has_pattern: 是否对花
        pattern_repeat: 花距（米）
        open_count: 打开方式开数（**正整数** 1 单开 / 2 双开 / 3 三开 / 4 四开 …；默认 1）
        pleat_count: 褶数（韩褶褶数法；给定时按「每折吃布 × 褶数 + 余量」算料，issue #3982）
        source: 褶数/用料取值来源（formula / manual / customer_quoted）
        craft_tier: 工艺档位（standard / economy；与 pleat_count 二选一）
        accessories: **顾客显式**要单独买的辅料（如罗马圈）：[{"name","quantity","unit_price"}...]。
                     不给 ⇒ 一个都不加（**不按米数推导**，issue #4118 / #3005）
        style: 款式（**单色/拼色**，真值源 §10）。传 `拼色` ⇒ 报价**另加**拼色加价
               （`MIXED_COLOR_SURCHARGE_PER_METER` 元/米 × 该款面料米数，用户 2026-09-21 裁定）；
               不传 ⇒ **不判断款式、不计该加价**（既有调用逐值不变）。本函数**不从别处猜款式**。
        formula: 用料**计算方法**（issue #4527，用户 2026-09-19 裁定）：`'pleat'`（韩褶公式＝褶数法，
                 **默认**）｜`'fullness'`（褶倍数公式＝倍数法）。缺省 ⇒ 配置的 `default_formula`。
        config: 算料公式配置（商家可自定义；issue #4527）。None ⇒ `DEFAULT_CRAFT_CALC_CONFIG`
                （默认值 = 既有常量逐值不变）。本函数**不修改**传入的配置。

    Returns:
        报价字典：fabric_meters / processing_meters / fabric_cost / processing_cost /
        accessory_cost / install_cost / mixed_color_surcharge / total / breakdown / formula /
        formula_used / formula_text / warning / fullness
        （褶数法时另含 pleat_count / per_panel_pleats / open_count / margin / per_fold /
        source / craft_tier 以及 fullness_actual）
        （**仅定宽买高**时另含 `panels` 幅数：定高买宽按宽买米、幅数无定义 ⇒ **键缺席**，
        不补 0/1 —— issue #4374 交付物 3）

    语义分工（issue #4118 ④）：
        `fullness` = **理论**倍数（档位名义值 / 款式默认值），随档位走；
        `fullness_actual` = **实际**倍数（褶数法用料 ÷ 窗宽，仅褶数法给出），随用料走。
        顾客自报褶数时二者不等（如 48 折 → 理论 2.0 / 实际 1.86）⇒ 展示必须取实际值。

    默认档告警（issue #4118 ⑤-B）：
        `mounting=s_hook` 且未传 `craft_tier`/`pleat_count` ⇒ 仍走倍数法（**数值一字不变**），
        但 `warning` 里**显式**说明「本次按倍数法计价、非标准档褶数法」——此前这句是缺失的
        （静默回落）。告警只治静默，不改口径。
    """
    cfg = resolve_craft_calc_config(config)
    # 公式选择（issue #4527 + 2026-09-19 追加裁定「韩褶用韩褶公式算布料，打孔按倍数法算布料」）：
    # ① 显式 `formula` 入参**优先**（显式覆盖）；② 否则按**工艺推导**（`resolve_craft_rule`，唯一口径）；
    # ③ 否则用配置的 `default_formula`（= **推导表缺失时的兜底**，默认韩褶公式）。
    # ⚠️ 显式 `formula` **不得**被 `craft_tier` / `pleat_count`（褶数法的触发条件）遮蔽 ——
    # 那正是「新入参静默失效」的形态（判据见 tests/test_craft_calc_formula.py）。
    craft_formula, craft_mounting = resolve_craft_rule(craft)
    if formula is not None:
        selected_formula = formula
    elif craft_formula is not None:
        selected_formula = craft_formula
    else:
        selected_formula = cfg["default_formula"]
    if selected_formula not in FORMULA_LABELS:
        raise ValueError(
            f"用料公式 formula 必须是 {'/'.join(sorted(FORMULA_LABELS))} 之一"
            f"（韩褶公式={FORMULA_PLEAT} / 褶倍数公式={FORMULA_FULLNESS}），收到 {selected_formula!r}"
        )

    # 工艺 → 悬挂方式（用户 2026-09-19 追加裁定：韩褶→s_hook / 打孔→eyelet）：
    # 调用方未显式给 `mounting`（仍是默认值 "eyelet"）而 `craft` 能推导时，按 `craft` 走 ——
    # 否则「打孔按倍数法算布料」拿不到 eyelet 的默认褶倍 2.0（`DEFAULT_FULLNESS['eyelet'] == 2.0`，
    # 与 `DEFAULT_CRAFT_TIERS['standard'].fullness` **同一个 2.0**，不新造第二个字面量）。
    # ⚠️ 显式传的 `mounting`（非默认值）**优先**，不被 craft 改写。
    if craft_mounting is not None and mounting == MOUNTING_EYELET:
        mounting = craft_mounting

    # 褶皱倍数默认值
    N = fullness if fullness is not None else DEFAULT_FULLNESS.get(mounting, 2.0)

    # 韩褶褶数法（工艺档位或客户自报褶数触发）：用料 = 每折吃布 × 褶数 + 余量
    pleat_mode = (
        selected_formula == FORMULA_PLEAT
        and mounting == "s_hook"
        and (pleat_count is not None or craft_tier is not None)
    )
    pleat_fields: Dict[str, Any] = {}
    # 幅数（`panels`）：**只在真的算了幅数的分支**（定宽买高）才有值 —— 定高买宽按宽买米，
    # 幅数无定义 ⇒ 键缺席（不发明数字：既不补 0，也不补 1 冒充「1 幅」）。
    panels: Optional[int] = None

    # ── 门幅与加工类型的**自动选择**（issue #5013）──────────────────────────────
    # ⚠️ **`fabric_widths` 是这条通路的唯一开关**（新入参 ⇒ 既有调用一个字都不变）：
    #    给了候选集 ⇒ 由 `resolve_fabric_plan` 在候选集内选门幅、并自动推导加工类型
    #    （显式 `cutting_mode` 则作为**人工覆盖**生效）；没给 ⇒ 走下方既有单一门幅口径。
    # 口径真值源 = `docs/design/door-width-auto-selection.md`。
    plan_state: Dict[str, Any] = {
        "door_width": fabric_width, "cutting_mode": None, "splice": False, "reason": "",
    }

    def _resolve_plan(meters_fixed_height: float, suffix: str):
        """定高买宽用料 T ⇒（幅数, 最终米数, formula_used, 超限/规则告警）；并写 `plan_state`。"""
        nonlocal fabric_width
        if fabric_widths:
            plan = resolve_fabric_plan(
                window_height=window_height,
                fixed_height_meters=meters_fixed_height,
                door_widths=fabric_widths,
                has_pattern=has_pattern,
                pattern_repeat=pattern_repeat,
                open_count=open_count,
                cutting_mode=cutting_mode,
                config=cfg,
            )
            fabric_width = plan["door_width"]
            plan_state.update(
                door_width=plan["door_width"],
                cutting_mode=plan["cutting_mode"],
                splice=plan["splice"],
                reason=plan["reason"],
            )
            tail = "width" if plan["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH else "height"
            # 只有「真的换了做法」（倒幅 / 接高）才告警 —— 定高买宽单幅是**正常路径**，不 nag。
            over = plan["reason"] if (plan["splice"] or tail == "width") else ""
            return plan["panels"], plan["meters"], f"fixed_{tail}{suffix}", over
        # ── 既有路径（单一门幅）：口径**一字未动**（回归不变量）──
        if window_height + cfg["hem_margin"] > fabric_width:
            count = math.ceil(meters_fixed_height / fabric_width)
            plan_state.update(cutting_mode=CUTTING_MODE_FIXED_WIDTH)
            return (
                count,
                count * (window_height + cfg["hem_margin"] + (pattern_repeat if has_pattern else 0.0)),
                f"fixed_width{suffix}",
                f"成品高 {window_height:.2f}m 超过门幅 {fabric_width:.2f}m 的定高上限，"
                f"已按定宽布（买高）计算，幅数 {count} 幅。",
            )
        plan_state.update(cutting_mode=CUTTING_MODE_FIXED_HEIGHT)
        return None, meters_fixed_height, f"fixed_height{suffix}", ""

    if selected_formula == FORMULA_FULLNESS:
        # 褶倍数公式（倍数法，issue #4527）：逐片表达，数值 = 成品宽 × 褶倍（**与开数无关**）
        meters, _pp_meters, _pp_width = _per_panel_fullness_meters(
            window_width, open_count, N, cfg)
        panels, meters, formula_used, warning = _resolve_plan(meters, "_fullness")
        # 取值来源/档位**如实回显**（与褶数法同一契约：用料必须带来源 —— 真值源 §8）
        pleat_fields = {"source": source, "craft_tier": craft_tier}
    elif pleat_mode:
        if pleat_count is None:
            tier = cfg["tiers"].get(craft_tier or "standard", cfg["tiers"]["standard"])
            pleat_count, tier_warning = derive_pleat_count(
                window_width, tier["fullness"], open_count, cfg)
            N = tier["fullness"]
        else:
            tier_warning = ""
        # 拼色每折吃布系数（用户 2026-09-19 裁定）：`style=拼色` + 特殊选项 `拼1次`/`拼2次`
        # ⇒ 0.65 / 1.2 米每折；其余（含只给 style 没给拼次）⇒ 单色 0.25。余量不随拼色变化。
        # ⚠️ 褶数**仍按单色系数反算**（`derive_pleat_count`，既有口径）：拼色只改「每折吃布」这一项
        # ⇒ 52 折双开拼1次 = 0.65×52+0.3 = 34.1 米（改褶数就是改既有的拼色数值，不在本包）。
        per_fold = resolve_per_fold(style, special_options, cfg)
        meters, pleat_warning, info = calculate_fabric_by_pleats(
            pleat_count, open_count, source=source, width=window_width,
            per_fold=per_fold, config=cfg,
        )
        warning = " ".join(w for w in [tier_warning, pleat_warning] if w)
        # 「拼色但没给拼次」不得静默：无系数依据时如实告警（本单不发明口径，按单色算但说出来）。
        if style == STYLE_MIXED and per_fold == cfg["per_fold_single"]:
            gap = mixed_per_fold_gap(special_options, cfg)
            warning = (warning + " " if warning else "") + (
                f"款式为拼色但未给出纸表已登记的拼次（{'/'.join(f'拼{n}次' for n in sorted(cfg['per_fold_mixed_times']))}），"
                f"本次按单色每折 {cfg['per_fold_single']:g} 米计算，非拼色用料系数。"
            )
            if gap:
                warning += f"（{gap} 的用料系数纸表未登记，需先裁定）"
        _plan_panels, meters, formula_used, _plan_over = _resolve_plan(meters, "_pleats")
        panels = _plan_panels
        if _plan_over:
            warning = (warning + " " if warning else "") + _plan_over
        pleat_fields = {
            "pleat_count": info["pleat_count"],
            "per_panel_pleats": info["per_panel_pleats"],
            "open_count": open_count,
            "margin": info["margin"],
            "per_fold": info["per_fold"],
            "source": source,
            "craft_tier": craft_tier,
        }
        if "fullness_actual" in info:
            # 实际褶倍（= 实际用料 ÷ 窗宽）与上面的 `fullness`（档位/款式**理论**倍数）**语义不同**：
            # 理论值随档位走（standard 2.0 / economy 1.8），实际值随用料走（48 折 → 12.3÷6.6 = 1.86）。
            # 顾客自报褶数时二者必然不等，卡片必须两个都能读到（issue #4118 ④：算了就丢 = 只能拿理论值骗顾客）。
            # ⚠️ 只透传，**不改** `fullness` 的既有含义（那会动既有契约）。
            pleat_fields["fullness_actual"] = info["fullness_actual"]
    else:
        # 给了候选门幅 ⇒ 先用**无限门幅**取「定高买宽用料 T」（该函数的分支只由 `H + 卷边 ≤ 门幅` 决定），
        # 再由门幅规则决定门幅/加工类型；罗马帘没有「定高/定宽」之分 ⇒ 不走门幅规则。
        _t, _fu, _w = calculate_fabric_meters(
            window_width=window_width,
            window_height=window_height,
            fullness=N,
            fabric_width=math.inf if fabric_widths else fabric_width,
            mounting=mounting,
            has_pattern=has_pattern,
            pattern_repeat=pattern_repeat,
        )
        if fabric_widths and _fu != "roman_panel":
            panels, meters, formula_used, warning = _resolve_plan(_t, "")
        else:
            meters, formula_used, warning = _t, _fu, _w
            if formula_used == "fixed_width":
                # 定宽买高：幅数在 `calculate_fabric_meters` 内算出（局部变量 `panels`）却没进返回值
                # ⇒ 报价卡「幅数」行永不出现（issue #4374 交付物 3）。此处按**同一公式**
                # （`ceil((W + side_margin) × N / G)`，与 `calculate_fabric_meters` 的定宽分支逐字同源）
                # 复算暴露它 —— **入参一字未动 ⇒ 米数/金额逐值不变**（本单不改钱）。
                panels = math.ceil((window_width + cfg["side_margin"]) * N / fabric_width)
            # 新键（issue #5013）也要**如实**：罗马帘没有「定高/定宽」之分 ⇒ `None`
            # （不发明第三个加工类型值）。
            plan_state["cutting_mode"] = {
                "fixed_height": CUTTING_MODE_FIXED_HEIGHT,
                "fixed_width": CUTTING_MODE_FIXED_WIDTH,
            }.get(formula_used)
        if mounting == "s_hook":
            # issue #4118 ⑤-B：韩褶（s_hook）的**标准档口径是褶数法**，但褶数法只在显式传
            # `craft_tier` / `pleat_count` 时触发（`pleat_mode` 判据）⇒ 两者都缺时这里**静默**
            # 走了倍数法：实测同一单（6.6m 窗 / 2.6m 高 / 双开 / 3.2m 门幅）倍数法 13.8 米，
            # 而标准档褶数法 13.3 米（52 折），差 0.5 米却**零告警**。
            # 治法 = **只补显式告警、不动一个数值**（把默认档接成标准档 = 改既有报价口径 = 改钱，
            # 需客户裁定，不在本包）。
            warning = (warning + " " if warning else "") + (
                "未指定工艺档位（craft_tier）或褶数（pleat_count），"
                f"本次按倍数法计价（{N:g} 倍），非标准档褶数法；"
                "如需标准档请传 craft_tier 或 pleat_count。"
            )

    # 拼色**报价加价**（用户 2026-09-21 裁定，真值源 §10/§11）：`款式=拼色` ⇒ 该款**面料米数** × 单价。
    # ⚠️ 只在 `style == 拼色` 时计（**显式入参触发**）⇒ 不传 `style` 的既有调用/历史报价**逐值不变**
    # （这正是「不追溯」的机制：新规则只对裁定生效后**新产生**的计算生效）。
    # ⚠️ 加价**另立一行**，不改面料/加工/辅料任一单价（改单价 = 双算 + 动既有契约）。
    mixed_color_surcharge = (
        meters * MIXED_COLOR_SURCHARGE_PER_METER if style == STYLE_MIXED else 0.0
    )

    # 面料费
    fabric_cost = meters * fabric_price

    # 加工费（按款式单价 × 面料米数）
    processing_price = DEFAULT_PROCESSING_PRICE.get(mounting, 0.0)
    processing_cost = meters * processing_price

    # 辅料费（打孔帘默认：孔带 + 罗马杆 + 绑带 —— 罗马圈**不在**默认项里，见下方口径）
    rod_length = window_width + ROD_EXTENSION
    accessory_breakdown: List[Dict[str, Any]] = []
    accessory_cost = 0.0

    if mounting == "eyelet":
        tape_cost = meters * EYELET_TAPE_PRICE
        rod_cost = rod_length * ROD_PRICE
        accessory_breakdown = [
            {"name": "孔带", "detail": f"{meters:.2f}米 × ¥{EYELET_TAPE_PRICE}/米", "cost": round(tape_cost, 2)},
            {"name": "罗马杆", "detail": f"{rod_length:.2f}米 × ¥{ROD_PRICE}/米", "cost": round(rod_cost, 2)},
            {"name": "绑带", "detail": "1对", "cost": TIEBACK_PRICE},
        ]
        accessory_cost = tape_cost + rod_cost + TIEBACK_PRICE

    # 顾客**显式**声明的辅料（如单独买罗马圈）：只按给定数量/单价计入，绝不从米数推导（#4118/#3005）
    extra_rows, extra_cost = explicit_accessories(accessories)
    accessory_breakdown.extend(extra_rows)
    accessory_cost += extra_cost

    # 安装费（按杆长）
    install_cost = rod_length * INSTALL_PRICE

    total = fabric_cost + processing_cost + accessory_cost + install_cost + mixed_color_surcharge

    breakdown = [
        {"name": "面料", "detail": f"{meters:.2f}米 × ¥{fabric_price}/米", "cost": round(fabric_cost, 2)},
        {"name": "加工费", "detail": f"{meters:.2f}米 × ¥{processing_price}/米", "cost": round(processing_cost, 2)},
        # 拼色加价行：**单色款不出现在 breakdown 里**（单色报价单逐值不变 ⇒ 回归不变量）
        *([{
            "name": "拼色加价",
            "detail": f"{meters:.2f}米 × ¥{MIXED_COLOR_SURCHARGE_PER_METER}/米",
            "cost": round(mixed_color_surcharge, 2),
        }] if mixed_color_surcharge else []),
        *accessory_breakdown,
        {"name": "安装费", "detail": f"{rod_length:.2f}米 × ¥{INSTALL_PRICE}/米", "cost": round(install_cost, 2)},
    ]

    # 可读公式串（issue #4527 判据 4）：**明确写出所用公式**，数字与上面回传的**同一份**数值同源。
    formula_text = _formula_text(
        selected_formula,
        window_width,
        pleat_fields.get("margin", margin_for_open_count(open_count, cfg)),
        N,
        pleat_fields.get("pleat_count", 0),
        open_count,
        round(meters, 2),
        pleat_fields.get("per_fold", cfg["per_fold_single"]),
    )

    quote = {
        "fabric_meters": round(meters, 2),
        # §6.1（issue #4346，用户已裁定）：米数**拆两个字段** ——
        # `processing_meters` = **主布行**米数（加工费口径）；`fabric_meters` = Σ 面料行米数。
        # 单面料行时两值恒等 ⇒ **现有单金额一字不变**（本工具当前只算主布）。
        # 配布边的米数/计价属「待裁定」（设计文档 §六 #4），**本包不实现**。
        "processing_meters": round(meters, 2),
        "fabric_cost": round(fabric_cost, 2),
        "processing_cost": round(processing_cost, 2),
        "accessory_cost": round(accessory_cost, 2),
        "install_cost": round(install_cost, 2),
        # 拼色加价（用户 2026-09-21 裁定）：**键恒在**，单色款 = 0.0（不发明数字：0 = 本单没有这一笔）。
        "mixed_color_surcharge": round(mixed_color_surcharge, 2),
        "total": round(total, 2),
        "breakdown": breakdown,
        # ── 公式选择与可读公式串（issue #4527）──────────────────────────────────
        # `formula` = 本次**实际所用**的用料计算方法（pleat 韩褶公式 / fullness 褶倍数公式）；
        # `formula_text` = 可读公式串，**由本模块（算料引擎）产出** —— Java / TS 侧自拼 = 第二份算料逻辑。
        "formula": selected_formula,
        "formula_used": formula_used,
        "formula_text": formula_text,
        "fullness": N,
        "warning": warning,
        **pleat_fields,
        # 幅数（`panels`，issue #4374 交付物 3）：**只在真的算了幅数时才有该键** ——
        # 定高买宽按宽买米，幅数无定义 ⇒ 键缺席（不发明数字）。加工单快照的 `panels` 读的就是它。
        **({"panels": panels} if panels is not None else {}),
        # ── 工艺规格回显（设计文档 §4.9：报价单与订单落库「同源」）──────────────────
        # **原样透传**，不推导、不补默认值：不传 ⇒ `None`（键恒在，便于前端判空与契约测试）。
        # 为什么不让本工具去猜：`craft` 必须与工序库枚举（韩褶/打孔/四爪钩/穿杆/平幔）**逐字一致**，
        # 与 `mounting`（eyelet/s_hook/hook/roman）是**两层**，互相推导会静默给错工序。
        "curtain_type": curtain_type,
        "craft": craft,
        "is_shaped": is_shaped,
        "style": style,
        "special_options": special_options,
        # ── 自动特征（issue #4976 包 1a）：**键恒在** ──────────────────────────────
        # 空列表 = **不判**（缺加工类型 / 表外取值 / 缺褶倍），**不是**「没算」——
        # 调用方据此区分「系统没判」与「系统判了但没有」。
        # 门幅与加工类型（issue #5013）：`fabric_widths` 未给 ⇒ `door_width` = 入参门幅、
        # `splice` 恒 False，`auto_features` 仍吃**入参** `cutting_mode` ⇒ 既有调用读到的键值逐值不变。
        "door_width": plan_state["door_width"],
        "cutting_mode": plan_state["cutting_mode"] or cutting_mode,
        "splice": plan_state["splice"],
        "door_width_reason": plan_state["reason"],
        "auto_features": detect_auto_features(
            window_width=window_width,
            window_height=window_height,
            fabric_width=fabric_width,
            fullness=N,
            cutting_mode=(plan_state["cutting_mode"] or cutting_mode) if fabric_widths else cutting_mode,
            config=config,
        ),
    }
    # 幅数（issue #5043 包 2b，**加性**）：**只在真有幅数时**才出键 ——
    # 定高买宽「按宽买米，**幅数无定义**」⇒ **键缺席**（既有口径：**既不补 0，也不补 1
    # 冒充「1 幅」**；守卫 = 契约测试「定高买宽不得造幅数」）。既有键**逐值不变**。
    if panels is not None:
        quote["panels"] = panels
    return quote


def calculate_multi_position(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """多部位批量算料：逐部位 build_quote + 总用料 + 按货号-色号汇总。

    Args:
        positions: [build_quote 参数 + fabric_code, ...]
    Returns: {positions: [quote...], total_meters, by_fabric}
    """
    results: List[Dict[str, Any]] = []
    for p in positions:
        q = build_quote(
            window_width=p["window_width"],
            window_height=p["window_height"],
            mounting=p.get("mounting", "s_hook"),
            fullness=p.get("fullness"),
            fabric_width=p.get("fabric_width", 2.8),
            fabric_price=p.get("fabric_price", 30.0),
            has_pattern=p.get("has_pattern", False),
            pattern_repeat=p.get("pattern_repeat", 0.0),
            open_count=p.get("open_count", 1),
            pleat_count=p.get("pleat_count"),
            source=p.get("source", "formula"),
            craft_tier=p.get("craft_tier"),
            accessories=p.get("accessories"),
        )
        q["fabric_code"] = p.get("fabric_code") or "未指定"
        results.append(q)
    by_fabric = aggregate_by_fabric(
        [{"fabric_code": r["fabric_code"], "meters": r["fabric_meters"]} for r in results]
    )
    return {
        "positions": results,
        "total_meters": round(sum(r["fabric_meters"] for r in results), 2),
        "by_fabric": by_fabric,
    }


# ── 本租户算料口径的取用（issue #4922）──────────────────────────────────────────
# 真值源 = `craft_calc_configs`（商家在「工艺配置 → 算料配置」改），读面 =
# admin-api `GET /api/admin/production/craft-calc-config`（**同一份实现**：默认值/校验的唯一出处
# 仍是本模块的 `DEFAULT_CRAFT_CALC_CONFIG` 与 `resolve_craft_calc_config`）。
#
# 口径**零自造**（硬红线）：本模块只有这一处取配置，取值只可能来自
#   ① 服务端返回的**本租户**配置；② 缺行 / 服务端不可达 ⇒ **不传 config**
#      （引擎用 `DEFAULT_CRAFT_CALC_CONFIG`；不可达那一族另挂显式 warning + `config_source` 留痕）。
# 与服务端下单路径 `CraftCalcClient#withTenantConfig`（`selectActiveByTenant` → 非空才加 `config` 键）
# 逐字同口径 —— 两条入口必须是同一个米数，否则就是本单要消灭的「同一张单两个答案」。
#: admin-api 的租户算料配置读面（`CraftCalcConfigController`，类级 `@RequirePermission("processing:manage")`）。
TENANT_CRAFT_CALC_CONFIG_PATH = "/api/admin/production/craft-calc-config"
#: 服务端 `data.source` 的两个取值（`CraftCalcConfigService.SOURCE_STORED` / `SOURCE_DEFAULT`）。
_SERVER_SOURCE_STORED = "stored"
_SERVER_SOURCE_DEFAULT = "default"
#: `ToolResult.data.config_source` 取值：**取配置这件事必须可观测**（不留痕 = 静默回落默认值）。
CONFIG_SOURCE_TENANT = "tenant"                    # 用了本租户配置行
CONFIG_SOURCE_DEFAULT_NO_ROW = "default(no_row)"   # 服务端明确回答：本租户没有配置行
#: 服务端**没答复**（不可达 / 熔断）⇒ 只能用引擎默认口径 —— 必须配 `warning` 显式告知，不许静默。
CONFIG_SOURCE_DEFAULT_FETCH_FAILED = "default(fetch_failed)"
#: 降级时随报价单回给模型/商家的**显式**告知（同 `OrderCraftFields` 的「算料配置未加载」amber 提示口径）。
CONFIG_FETCH_FAILED_NOTE = (
    "未能读取本租户的算料口径（算料配置服务不可达）——本次按引擎默认口径试算，"
    "米数可能与下单页/服务端不一致；请稍后重试后再以本租户口径为准。"
)
#: `AdminApiClient` 熔断时的错误码（连调用都不发 ⇒ 与「不可达」同族）。
_CIRCUIT_OPEN_CODE = "CIRCUIT_OPEN"


class CraftCalcConfigUnavailable(RuntimeError):
    """**服务端答复了**但口径读不通（失败信封 / 5xx / 形状漂移 / 配置不可归一）—— fail-closed。

    「服务端**没答复**」（`httpx.TransportError` / 熔断）**不**走这里：那条路是显式降级 + 留痕
    （见 `load_tenant_craft_calc_config`），因为此刻 admin-api 整体不可用 ⇒ 服务端下单路径同样不可用
    （`CraftCalcClient` 对端不可达是 422 fail-closed）⇒ 不存在「米宝一个数、落库另一个数」的窗口。

    `response` 非空 = 服务端给了**失败信封**（`success != true`，如 403/422，由 `AdminApiClient`
    整份透传）⇒ 调用方交给 `admin_api_failure`（**唯一映射点**）：权限拒绝据此拿到
    `PERMISSION_DENIED`（∈ 非重试集合）+ 可行动话术 = **终态**，不会被 `_self_correct_retry`
    拿去换参数重放（issue #4103 的 P0 形态）。形状漂移（`success=true` 但内容不对）**不**走它 ——
    那种响应里没有 `error.code` 可映射，按通用 fail-closed 处理。
    """

    def __init__(self, reason: str, *, response: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.response = response


def _normalize_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """线上配置（JSON ⇒ `per_fold_mixed_times` 的键恒为**字符串**）→ 引擎入参。

    **复用唯一实现**：`app/api/internal.py` 的 `_normalize_craft_calc_config`（服务端经
    `CraftCalcClient` 走的正是它）。在本模块再写一份 = 第二份规范化口径，两边漂移时
    「商家改了拼色系数却算不出料 / 少算用料」不会有任何东西变红。
    延迟导入：`app.api.internal` 在模块级 import 本模块 ⇒ 模块级反向 import 成环。
    """
    from app.api.internal import _normalize_craft_calc_config  # 延迟导入避环（单一实现）
    return dict(_normalize_craft_calc_config(config) or {})


async def load_tenant_craft_calc_config(
    tenant_id: int, user_id: Optional[str] = None,
) -> tuple[Optional[Dict[str, Any]], str]:
    """读本租户算料口径 → `(config, config_source)`；**本租户没有配置行 ⇒ `(None, 'default(no_row)')`**。

    Args:
        tenant_id: 租户 id（`ToolContext.tenant_id`）。
        user_id: 调用方用户 id。**照传**（与 `processing_item_query` 等同族工具同形）：
            admin-api 的 `ServiceTokenFilter` 据此把**本租户商户员工**挂真实角色
            （`service` 旁路失效 ⇒ `@RequirePermission` 真正生效）；C 端顾客 / 查不到的用户行
            / 跨租户一律回退内部服务身份（既有行为，逐字不变）。

    Returns:
        `(config, config_source)`：`config=None` ⇒ 调用方**不得**传 `config` 给引擎。
        `config_source` 三态：`tenant`（本租户配置行）/ `default(no_row)`（服务端明确说没有行）/
        `default(fetch_failed)`（服务端没答 ⇒ 用引擎默认口径，**必须**配显式告警）。

    Raises:
        CraftCalcConfigUnavailable: **服务端答复了**却读不通（失败信封 / 5xx / 形状漂移 / 配置不可归一）
            ⇒ **fail-closed**：绝不按默认口径算钱（那正是 #4922 要消灭的形态）。
            ⚠️ 「服务端没答」（`httpx.TransportError` / 熔断）**不**抛 —— 显式降级 + 留痕（理由见函数内注释）。
    """
    api = get_admin_api_client()
    try:
        response = await api.get(
            TENANT_CRAFT_CALC_CONFIG_PATH, tenant_id=tenant_id, user_id=user_id)
    except httpx.TransportError as e:
        # 服务端**没答复**（DNS / 连接被拒 / 超时）⇒ 显式降级 + 留痕（`execute` 会挂显式 warning）。
        # 为什么这里不 fail-closed：此刻 admin-api 整体不可用 ⇒ 服务端下单路径同样不可用
        # （`CraftCalcClient` 对端不可达 = 422 fail-closed）⇒「米宝一个数、落库另一个数」不可能落地；
        # 而把纯计算工具整条拦下，只会让商家/顾客连估算都拿不到（且离线/单测环境 admin-api 恒不可达）。
        logger.error(
            f"[curtain-calc] 算料口径端点不可达，降级用引擎默认口径: tenant={tenant_id} err={e}")
        return None, CONFIG_SOURCE_DEFAULT_FETCH_FAILED
    except Exception as e:  # 服务端答复了但读不通（5xx = HTTPStatusError / 响应非 JSON）⇒ fail-closed
        raise CraftCalcConfigUnavailable(
            f"算料配置端点答复不可用（{type(e).__name__}: {e}）") from e
    error_info = response.get("error") if isinstance(response, dict) else None
    if isinstance(error_info, dict) and error_info.get("code") == _CIRCUIT_OPEN_CODE:
        # 熔断 = `AdminApiClient` 已判定该端点不可用（连调用都不发）⇒ 与「不可达」同族（降级 + 留痕）
        logger.error(f"[curtain-calc] 算料口径端点熔断，降级用引擎默认口径: tenant={tenant_id}")
        return None, CONFIG_SOURCE_DEFAULT_FETCH_FAILED
    if not isinstance(response, dict) or not response.get("success"):
        raise CraftCalcConfigUnavailable("算料配置端点返回失败（success != true）", response=response)
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    source = data.get("source")
    # 缺行：服务端**明确**回答「本租户没有配置行」⇒ 不传 config（零回归，与 CraftCalcClient 同口径）。
    # ⚠️ 不消费此时响应里的 `config`（那是引擎默认值）——把默认值显式发过去 = 在 Python 侧锚死一份会漂的默认值。
    if source == _SERVER_SOURCE_DEFAULT:
        return None, CONFIG_SOURCE_DEFAULT_NO_ROW
    config = data.get("config")
    if source != _SERVER_SOURCE_STORED or not isinstance(config, dict) or not config:
        # 形状漂移（`success=true` 但内容不对）⇒ 通用 fail-closed：这类响应里没有 `error.code`，
        # 交给 `admin_api_failure` 只会得到一份没有码/没有出路的失败（= 模型原地重试）。
        raise CraftCalcConfigUnavailable(
            f"算料配置端点响应形状不对（source={source!r} / config={type(config).__name__}）")
    try:
        return _normalize_server_config(config), CONFIG_SOURCE_TENANT
    except ValueError as e:  # 服务端配置不可用（键不可归一）⇒ 同样 fail-closed，不静默回退默认值
        raise CraftCalcConfigUnavailable(f"算料配置不可用：{e}") from e


class CurtainCalcTool(BaseTool):
    """窗帘算料报价 Tool

    根据窗户尺寸 + 悬挂方式 + 面料信息，计算用布量与报价。
    纯计算（read_only），不修改任何数据；**唯一外部读取** = 本租户算料口径
    （issue #4922：`GET /api/admin/production/craft-calc-config`，缺行 ⇒ 不传 `config`）。
    """

    name = "curtain_calc"
    description = (
        "计算窗帘用布量与报价。用户询问窗帘需要多少布、多少钱、怎么算料时调用。"
        "【前置】需要窗宽(米)、窗高(米)；面料单价可通过 product_detail 查询得到。"
        "【门幅】顾客**没指定**门幅时，把 product_detail 的 SKU 列表里的门幅**去重**后传 "
        "fabric_widths（如 [2.8,3.2]）—— 系统会自动选门幅、并自动决定定高买宽/定宽买高"
        "（无需你判断朝向）；顾客**明确指定**了门幅才传 fabric_width。"
        "【褶数法·韩褶】mounting=s_hook 时可用褶数法：用料 = 0.25×褶数 + 余量（单开0.2/多开0.3）。"
        "顾客自报褶数或自报用料时：把褶数传 pleat_count；或传 craft_tier=economy 出省料档对比。"
        "开数传 open_count（1/2/4），对开褶数须偶数、四开能被 4 整除。"
        "取值来源传 source（formula/manual/customer_quoted）——客户自报的用料必须标记，"
        "与商家确认的档位分开（商家裁定后以确认值为准）。"
        "【辅料口径】加工费按面料米数打包、罗马圈/四爪钩等辅料成本已含在按米单价里，"
        "**不要**按米数替顾客推算辅料个数；顾客**显式**要单独买某项辅料（如「再单独买 40 个罗马圈」）"
        "时才传 accessories（数量/单价按顾客所说明说）。"
        "【反例】查面料价格/库存用 product_detail，不要用它算料；下单用 order_create。"
        "【反例·重要】顾客**直接说了要买多少米布**（如「要 3 米」「买 3 米布」「3 米，散剪」）时，"
        "那已经是**购买数量**，**不要**调用本工具 —— 把米数当窗宽再乘褶皱倍数会算出 3 倍布量、"
        "顾客被多收 2~3 倍钱（issue #3395 实证：3 米→9 米）。"
        "只有顾客给的是**窗户尺寸**（窗宽/窗高）且要问「需要多少布/多少钱」时才调用；"
        "尺寸不全时先问齐（本工具必须同时有窗宽与窗高）。"
        "READONLY"
    )
    read_only = True
    destructive = False
    idempotent = True
    allowed_roles = ["customer", "admin", "agent", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "window_width": {
                "type": "number",
                "description": "窗宽（米），必填。如 3 米宽窗传 3.0",
            },
            "window_height": {
                "type": "number",
                "description": "窗高（米，成品窗帘高度），必填。如 2.7 米高窗传 2.7",
            },
            "mounting": {
                "type": "string",
                "description": "悬挂方式：eyelet(打孔帘)/s_hook(韩式褶)/hook(四爪钩)/roman(罗马帘)。默认 eyelet",
                "enum": ["eyelet", "s_hook", "hook", "roman"],
            },
            "fullness": {
                "type": "number",
                "description": "褶皱倍数（可选，不传则按悬挂方式默认：打孔/韩式褶/四爪钩=2，罗马帘=1）",
            },
            "fabric_width": {
                "type": "number",
                "description": (
                    "面料门幅（米），默认 2.8。窄幅布为 1.4。"
                    "⚠️ **顾客明确指定了门幅**时用本参数；没指定 ⇒ 改用 `fabric_widths`（候选集），"
                    "本参数被忽略"
                ),
            },
            "fabric_widths": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "**该商品可选的门幅集**（米，如 [2.8, 3.2]）—— 由 `product_detail` 的 SKU 列表里"
                    "**去重**得到（同一商品常同时有 2.8 / 3.2 两种门幅）。"
                    "【推荐】顾客只给了窗宽/窗高、**没指定门幅**时传本参数：系统会在候选集里"
                    "**自动选门幅**，并**自动决定用「定高买宽」还是「定宽买高」**"
                    "（规则：定高买宽做得下 ⇒ 取可行集里最小门幅；做不下 ⇒ 倒幅）。"
                    "传了本参数 ⇒ `fabric_width` 被忽略。"
                    "顾客**明确指定**了门幅 ⇒ 只传 `fabric_width`，不要传本参数。"
                ),
            },
            "fabric_price": {
                "type": "number",
                "description": "面料单价（元/米），必填。可从 product_detail 查询得到",
            },
            "has_pattern": {
                "type": "boolean",
                "description": "是否需要对花（大花型面料），默认 false",
            },
            "pattern_repeat": {
                "type": "number",
                "description": "花距（米），对花时有效，常见 0.3~0.6",
            },
            "open_count": {
                "type": "integer",
                "description": "打开方式开数：**正整数** 1 单开 / 2 双开 / 3 三开 / 4 四开 …（默认 1；不是固定枚举，issue #4430）。对开总褶数必须偶数、四开能被 4 整除",
            },
            "pleat_count": {
                "type": "integer",
                "description": "褶数（韩褶褶数法，mounting=s_hook 时有效）。客户自报褶数/用料时传此值；用料 = 0.25×褶数 + 余量（单开0.2/多开0.3）",
            },
            "source": {
                "type": "string",
                "description": "褶数/用料取值来源：formula 公式计算 / manual 人工指定 / customer_quoted 客户自报（默认 formula）",
                "enum": ["formula", "manual", "customer_quoted"],
            },
            "craft_tier": {
                "type": "string",
                "description": "工艺档位：standard 标准工艺（默认，倍数 2.0）/ economy 经济工艺（倍数 1.8，省料）。顾客要省钱或自报用料时用 economy 档对比；与 pleat_count 二选一",
                "enum": ["standard", "economy"],
            },
            "accessories": {
                "type": "array",
                "description": (
                    "顾客**显式**要求单独购买的辅料（如罗马圈）——每项 "
                    '{"name":"罗马圈","quantity":40,"unit_price":1.5}（unit 可选，默认「个」）。'
                    "【红线】数量必须来自顾客明说；**不要**按面料米数替他推导个数"
                    "（加工费按米打包、圈的成本已含在按米单价里，见 docs/curtain-fabric-quote-rules.md §5）。"
                    "顾客没提单独买辅料 ⇒ 不要传本参数"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "辅料名称，如「罗马圈」"},
                        "quantity": {"type": "number", "description": "数量（顾客明说，如 40）"},
                        "unit_price": {"type": "number", "description": "单价（元/单位，如 1.5）"},
                        "unit": {"type": "string", "description": "单位，默认「个」（如 米/对/个）"},
                    },
                    "required": ["name", "quantity", "unit_price"],
                },
            },
            # ── 工艺规格透传（issue #4346 / 设计文档 §4.9）──────────────────────────
            # 这些字段**不参与算料**，只随报价单展示并被 order_create **原样落库**，
            # 使「报价单展示的工艺参数 === 订单落库值」（一致性硬约束）。
            # 【红线】值一律来自引导清单/顾客勾选；**不传就不传**，不要猜、不要补默认。
            "curtain_type": {
                "type": "string",
                "description": (
                    "部位/帘种（引导清单已采集）：布帘/纱帘/帘头。"
                    "**不要猜**——顾客没说就不传；传错会让加工单取到错误工序路线"
                ),
                "enum": ["布帘", "纱帘", "帘头"],
            },
            "craft": {
                "type": "string",
                "description": (
                    "安装工艺（引导清单已采集，须与工序库枚举逐字一致）：韩褶/打孔/四爪钩/穿杆/平幔。"
                    "注意与 mounting 是**两层**（mounting 是悬挂方式英文枚举），**不要互相推导**"
                ),
                "enum": ["韩褶", "打孔", "四爪钩", "穿杆", "平幔"],
            },
            "is_shaped": {
                "type": "boolean",
                "description": (
                    "是否定型（引导清单已采集：布帘/帘头默认是、纱帘默认否）。"
                    "不传则报价单不展示该行"
                ),
            },
            "style": {
                "type": "string",
                "description": (
                    "款式（引导清单/顾客选择）：单色/拼色。"
                    "传「拼色」时报价**另加拼色加价**（用户 2026-09-21 裁定，真值源 §10：元/米 × 该款面料米数）"
                    "—— 加价由本工具算进 `total` 并单列 `mixed_color_surcharge`/`breakdown`，"
                    "**不要**自己心算或另加一笔（重复加价 = 多收钱）"
                ),
                "enum": ["单色", "拼色"],
            },
            "special_options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "下单勾选的**特殊选项**（部位级，19 项枚举，如 拼1次/加铅块/加花边/抱枕/布绑带）。"
                    "仅随报价单展示与订单落库透传，**不影响本次算料金额**（加价口径待客户裁定）"
                ),
            },
        },
        "required": ["window_width", "window_height"],
    }

    async def execute(
        self,
        context: ToolContext,
        window_width: float,
        window_height: float,
        mounting: str = "eyelet",
        fullness: Optional[float] = None,
        fabric_width: float = 2.8,
        fabric_widths: Optional[List[float]] = None,
        fabric_price: Optional[float] = None,
        has_pattern: bool = False,
        pattern_repeat: float = 0.0,
        open_count: int = 1,
        pleat_count: Optional[int] = None,
        source: str = "formula",
        craft_tier: Optional[str] = None,
        accessories: Optional[List[Dict[str, Any]]] = None,
        curtain_type: Optional[str] = None,
        craft: Optional[str] = None,
        is_shaped: Optional[bool] = None,
        style: Optional[str] = None,
        special_options: Optional[List[str]] = None,
    ) -> ToolResult:
        """执行算料报价"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限使用算料功能",
                suggestion="请联系管理员",
            )

        # 参数校验
        if not window_width or window_width <= 0:
            return ToolResult(
                success=False,
                error="缺少窗宽",
                message="请提供窗户宽度（米）",
                suggestion="请告诉客户窗户的宽度，例如「窗宽3米」",
            )
        if not window_height or window_height <= 0:
            return ToolResult(
                success=False,
                error="缺少窗高",
                message="请提供窗户高度（米）",
                suggestion="请告诉客户窗户的高度，例如「窗高2.7米」",
            )
        if mounting not in DEFAULT_FULLNESS:
            return ToolResult(
                success=False,
                error="不支持的悬挂方式",
                message=f"悬挂方式 {mounting} 不支持",
                suggestion="悬挂方式仅支持：打孔(eyelet)/韩式褶(s_hook)/四爪钩(hook)/罗马帘(roman)",
            )

        # GB/T 47746-2026 承诺边界：面料单价缺失时禁止按默认 30 元/米兜底报价
        # （默认价可能与真实售价不符，属编造报价承诺）。必须先查商品拿到真实单价再报价。
        if fabric_price is None:
            return ToolResult(
                success=False,
                error="缺少面料单价",
                message="缺少面料单价，请先查商品信息再报价",
                suggestion="请先调用 product_detail 或 product_search 查询该商品的面料单价（元/米），拿到真实单价后再重新计算报价",
            )

        # 本租户算料口径（issue #4922）：口径**零自造** —— 只来自服务端返回值。
        # 三条口径（与服务端下单路径 `CraftCalcClient` 同族）：
        #   ① 缺行 ⇒ 不传 config（引擎默认，逐字同口径 = 零回归）；
        #   ② **服务端答复了**却读不通（4xx/5xx/形状漂移）⇒ **fail-closed**（不算料 + 可行动话术）；
        #   ③ **服务端没答**（不可达/熔断）⇒ 显式降级 + 留痕（`config_source` + 报价单 warning 明说）。
        try:
            config, config_source = await load_tenant_craft_calc_config(
                context.tenant_id, context.user_id)
        except CraftCalcConfigUnavailable as e:
            logger.error(
                f"[curtain-calc] 算料口径不可用: tenant={context.tenant_id} err={e}")
            if e.response is not None:
                # 服务端给了失败响应（4xx）⇒ 走唯一映射点：权限拒绝 = 终态 + 可行动话术（issue #4103）
                return admin_api_failure(
                    e.response,
                    error="算料口径不可用",
                    message="读取本租户的算料口径失败，为避免按错误口径报价，本次不报价",
                    suggestion=(
                        "请稍后重试；若持续失败，请让管理员在「角色管理 → 岗位权限」"
                        "为该账号开通「加工管理」权限（本租户算料口径的读面权限）后重新报价"),
                )
            return ToolResult(
                success=False,
                error="算料口径不可用",
                error_code="CRAFT_CALC_CONFIG_UNAVAILABLE",
                message="读取本租户的算料口径失败，为避免按错误口径报价，本次不报价",
                suggestion=(
                    "请确认 admin-api 服务正常后重试。本工具必须按本租户"
                    "「工艺配置 → 算料配置」的口径算料，系统不会用引擎默认口径顶替。"),
            )

        try:
            quote = build_quote(
                window_width=float(window_width),
                window_height=float(window_height),
                mounting=mounting,
                fullness=fullness,
                fabric_width=float(fabric_width),
                # 候选门幅集（issue #5016）：给了 ⇒ 由 `resolve_fabric_plan` 自动选门幅 + 自动定
                # 加工类型（`fabric_width` 被忽略）；没给 ⇒ 既有单一门幅口径逐值不变。
                fabric_widths=fabric_widths,
                fabric_price=float(fabric_price),
                has_pattern=has_pattern,
                pattern_repeat=pattern_repeat,
                open_count=int(open_count),
                pleat_count=int(pleat_count) if pleat_count is not None else None,
                source=source,
                craft_tier=craft_tier,
                accessories=accessories,
                curtain_type=curtain_type,
                craft=craft,
                is_shaped=is_shaped,
                style=style,
                special_options=special_options,
                config=config,
            )

            logger.info(
                f"[curtain-calc] quote: W={window_width} H={window_height} "
                f"mounting={mounting} fullness={quote['fullness']} "
                f"meters={quote['fabric_meters']} total={quote['total']} "
                f"formula={quote['formula_used']} config_source={config_source} "
                f"| tenant={context.tenant_id}"
            )

            # `config_source` = 本次用的是哪一份口径（`tenant` / `default(no_row)` /
            # `default(fetch_failed)`）—— 留痕，不静默。
            data = {**quote, "config_source": config_source}
            if config_source == CONFIG_SOURCE_DEFAULT_FETCH_FAILED:
                # 显式降级：**明说**本次不是本租户口径（不静默回落 —— 同 `OrderCraftFields` 的 amber 提示）
                data["warning"] = " ".join(w for w in [quote["warning"], CONFIG_FETCH_FAILED_NOTE] if w)

            return ToolResult(
                success=True,
                data=data,
                summary=(
                    f"算料结果：{quote['fabric_meters']}米，总价¥{quote['total']} "
                    f"（面料¥{quote['fabric_cost']}+加工¥{quote['processing_cost']}"
                    f"+辅料¥{quote['accessory_cost']}+安装¥{quote['install_cost']}"
                    # 拼色加价：**只在真的收了这一笔时**才进括号（单色款 summary 一字不变）
                    + (f"+拼色加价¥{quote['mixed_color_surcharge']}"
                       if quote["mixed_color_surcharge"] else "")
                    + "）"
                ),
                message=(
                    f"算料完成：共需面料 {quote['fabric_meters']} 米，总价 ¥{quote['total']}"
                    "（以上为 AI 按您提供尺寸的预估报价，最终以实际测量/确认为准）"
                ),
            )
        except ValueError as e:
            # 参数类拒绝（显式辅料不合法 / 褶皱倍数低于红线）→ 把原因回给模型让它自纠，
            # 不与「算料失败」混成一个笼统错误（fail-closed：不猜默认值、不静默丢弃）
            logger.warning(f"[curtain-calc] rejected: {e}")
            return ToolResult(
                success=False,
                error="参数不合法",
                message=str(e),
                suggestion=(
                    "请核对该参数后重试；辅料（如罗马圈）必须由顾客显式给出数量与单价，"
                    "不得按面料米数推导"
                ),
            )
        except Exception as e:
            logger.error(f"[curtain-calc] Failed: {type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="算料失败，请稍后重试",
                suggestion="请检查窗宽窗高是否正确，确认后重试",
            )
