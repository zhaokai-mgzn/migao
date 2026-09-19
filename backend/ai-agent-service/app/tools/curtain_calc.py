"""
AI 智能客服系统 - 窗帘算料报价 Tool

面向小布（C 端客服）的窗帘用布量计算与报价工具。
纯计算（确定性公式），不调用 admin-api。

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）。

计价口径（issue #4118，以 #3005 为准）：加工费**按面料米数打包**计，罗马圈/四爪钩/S 钩等辅料成本
已含在按米单价里（如「打孔式 8 元/米」即含圈含工）⇒ **辅料数量不得由米数推导**（无「每米 N 个」密度）。
顾客显式要单独买辅料（如单独买罗马圈）时走 `accessories` **显式入参**，数量/单价必须由调用方给出。

核心公式：
- 定高布（买宽）：M = (W + 0.3) × N    （W=窗宽, N=褶皱倍数, 0.3=左右各15cm覆盖余量）
- 定宽布（买高）：P = ceil((W+0.3)×N/G)，M = P × (H + 0.3)   （G=门幅, H=窗高, 0.3=上下卷边）
- 罗马帘：M = (W + 0.2) × (H + 0.3)
- 对花：定宽布每幅长加 1 个花距

工程陷阱：成品高 H + 0.3 > 门幅 G 时定高布超限，须改用定宽布并返回告警。
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult


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

# ── 韩折折数法常量（【标】2026-09 客户纸表/行业系统加工单实证）──
PLEAT_FABRIC_PER_FOLD = 0.25       # 每折吃布（米）——**单色**口径
MARGIN_SINGLE = 0.2                # 单开余量（两侧包边各 10cm）
MARGIN_MULTI = 0.3                 # 对开/四开余量（每片外侧包边 10cm + 内侧对缝 5cm）
MIN_FULLNESS = 1.5                 # 褶皱倍数下限（低于影响美观，行业红线）

# ── 拼色每折吃布系数（用户 2026-09-19 裁定；纸质「韩折下料速查表」表头原文）──
# 表头原文：「拼色下料 **1个折 0.65** ／ **2个折 1.2**」——用户明确这是**用料**口径（不是计价）。
# ⚠️ 与真值源冲突并已按用户裁定改正：`docs/curtain-fabric-quote-rules.md` §10 曾把同一行记成
# 「拼色**计价** = 按折数加价（1 折 0.65、2 折 1.2 ≈ 0.6 元/折）」；本表是**用料**（米/折）。
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

# ── 工艺档位（【默】商家可配；每档 = 名义倍数 → 折数规则）──
DEFAULT_CRAFT_TIERS: Dict[str, Dict[str, Any]] = {
    "standard": {"fullness": 2.0, "label": "标准工艺"},
    "economy": {"fullness": 1.8, "label": "经济工艺"},
}


def margin_for_open_count(open_count: int = 1) -> float:
    """打开方式开数 → 侧边余量（米）：单开 0.2 / 多开 0.3"""
    return MARGIN_SINGLE if open_count <= 1 else MARGIN_MULTI


def resolve_per_fold(
    style: Optional[str] = None,
    special_options: Optional[List[str]] = None,
) -> float:
    """款式/拼次 → 每折吃布（米）。

    口径（用户 2026-09-19 裁定，纸质速查表表头）：
      · `style=拼色` 且部位级特殊选项含 `拼1次` / `拼2次` ⇒ 0.65 / 1.2 米每折；
      · 其余（含 `style=拼色` 但**没给**拼次）⇒ 单色口径 0.25。

    ⚠️ **纸表未登记的拼次**（如 `拼3次`：`mixed_times` 解析得出 3，但
    `MIXED_COLOR_PER_FOLD_BY_TIMES` 里没有 3）**不在此静默兜底** ——
    本函数只负责「有登记系数就取它」，**缺口判定由调用方显式做**（`mixed_per_fold_gap`），
    以免把「未登记」与「单色」混成同一个数（那就是**少算用料**）。
    """
    if style != STYLE_MIXED:
        return PLEAT_FABRIC_PER_FOLD
    for option in special_options or []:
        times = mixed_times(option)
        if times in MIXED_COLOR_PER_FOLD_BY_TIMES:
            return MIXED_COLOR_PER_FOLD_BY_TIMES[times]
    return PLEAT_FABRIC_PER_FOLD


def mixed_per_fold_gap(special_options: Optional[List[str]] = None) -> Optional[str]:
    """拼色下**纸表未登记用料系数**的拼次（如 `拼3次`）→ 该选项名；无缺口 → None。

    判据与系数表**同源**：`mixed_times` 解析得出拼次 N，而 N 不在
    `MIXED_COLOR_PER_FOLD_BY_TIMES` 里 ⇒ 缺口。**没有**平行的「未登记清单」可漂移
    （改一处忘一处 = 将来加 `拼4次` 时静默退回单色系数 ⇒ 少算用料）。

    为什么不猜：纸表表头只有「1个折 0.65 / 2个折 1.2」两行，`拼3次` 是**表外**项
    ⇒ 插值（0.65→1.2 线性外推）或退回单色 0.25 都是**发明口径**。调用方据此 fail-closed。
    """
    for option in special_options or []:
        times = mixed_times(option)
        if times is not None and times not in MIXED_COLOR_PER_FOLD_BY_TIMES:
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


def derive_pleat_count(width: float, fullness: float, open_count: int = 1) -> tuple[int, str]:
    """倍数意图 → 折数实现（按开数取整：对开偶数 / 四开 4 的倍数）。

    红线：fullness < MIN_FULLNESS 拒绝（行业美学下限）。
    Returns: (折数, 告警) — 告警非空表示做过取整调整。
    """
    if fullness < MIN_FULLNESS:
        raise ValueError(
            f"褶皱倍数 {fullness} 低于行业下限 {MIN_FULLNESS}，影响美观，请选择更高倍数档位"
        )
    pleats = int(
        round((width * fullness - margin_for_open_count(open_count)) / PLEAT_FABRIC_PER_FOLD)
    )
    pleats = max(pleats, open_count)
    if open_count > 1:
        adjusted = math.ceil(pleats / open_count) * open_count
    else:
        adjusted = pleats
    warning = (
        f"折数 {pleats} 无法被开数 {open_count} 整除，已取最近可行 {adjusted} 折"
        if adjusted != pleats else ""
    )
    return adjusted, warning


def calculate_fabric_by_pleats(
    pleat_count: int,
    open_count: int = 1,
    source: str = "formula",
    width: Optional[float] = None,
    per_fold: Optional[float] = None,
) -> tuple[float, str, dict]:
    """折数法算料：用料 = **每折吃布** × 折数 + 余量（单开 0.2 / 多开 0.3）。

    `per_fold` = 每折吃布（米）：单色 0.25（缺省，`PLEAT_FABRIC_PER_FOLD`）；
    拼色走 `MIXED_COLOR_PER_FOLD_BY_TIMES`（拼1次 0.65 / 拼2次 1.2 —— 用户 2026-09-19 裁定）。
    **余量不随拼色变化**（与单色同一套）。

    开数不可整除时自动取最近可行折数并告警。
    Returns: (用料米数, 告警, 折数信息 dict)
    """
    warning = ""
    if open_count > 1 and pleat_count % open_count != 0:
        adjusted = math.ceil(pleat_count / open_count) * open_count
        warning = f"折数 {pleat_count} 无法被开数 {open_count} 整除，已取最近可行 {adjusted} 折"
        pleat_count = adjusted
    coefficient = PLEAT_FABRIC_PER_FOLD if per_fold is None else per_fold
    meters = round(coefficient * pleat_count + margin_for_open_count(open_count), 2)
    info = {
        "pleat_count": pleat_count,
        "per_panel_pleats": pleat_count // open_count if open_count > 1 else pleat_count,
        "open_count": open_count,
        "margin": margin_for_open_count(open_count),
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


def calculate_fabric_meters(
    window_width: float,
    window_height: float,
    fullness: float,
    fabric_width: float,
    mounting: str = "eyelet",
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
) -> tuple[float, str, str]:
    """计算窗帘面料用量（米）。

    Args:
        window_width: 窗宽（米）
        window_height: 窗高（米，成品窗帘高度）
        fullness: 褶皱倍数
        fabric_width: 面料门幅（米）
        mounting: 悬挂方式（eyelet/s_hook/hook/roman）
        has_pattern: 是否需要对花
        pattern_repeat: 花距（米），对花时有效

    Returns:
        (meters, formula_used, warning)
        formula_used: fixed_height（定高买宽）/ fixed_width（定宽买高）/ roman_panel（罗马帘）
        warning: 非空字符串表示存在工程告警（如窗高超定高上限）
    """
    # 罗马帘：无褶皱倍率，按包边计算
    if mounting == "roman":
        meters = (window_width + ROMAN_SIDE) * (window_height + HEM_MARGIN)
        return meters, "roman_panel", ""

    # 定高布可用条件：成品高 + 卷边 ≤ 门幅（2.8m 定高上限成品高约 2.5m）
    if window_height + HEM_MARGIN <= fabric_width:
        # 定高买宽：M = (W + 0.3) × N
        meters = (window_width + SIDE_MARGIN) * fullness
        return meters, "fixed_height", ""

    # 定宽买高：幅数向上取整，每幅长 = 窗高 + 卷边（+ 对花花距）
    panels = math.ceil((window_width + SIDE_MARGIN) * fullness / fabric_width)
    panel_length = window_height + HEM_MARGIN
    if has_pattern:
        panel_length += pattern_repeat
    meters = panels * panel_length
    warning = (
        f"成品高 {window_height:.2f}m 超过门幅 {fabric_width:.2f}m 的定高上限，"
        f"已按定宽布（买高）计算，幅数 {panels} 幅。"
    )
    return meters, "fixed_width", warning


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
        open_count: 打开方式开数（1 单开 / 2 双开 / 4 四开；默认 1）
        pleat_count: 折数（韩褶折数法；给定时按 0.25×折数+余量 算料，issue #3982）
        source: 折数/用料取值来源（formula / manual / customer_quoted）
        craft_tier: 工艺档位（standard / economy；与 pleat_count 二选一）
        accessories: **顾客显式**要单独买的辅料（如罗马圈）：[{"name","quantity","unit_price"}...]。
                     不给 ⇒ 一个都不加（**不按米数推导**，issue #4118 / #3005）

    Returns:
        报价字典：fabric_meters / fabric_cost / processing_cost / accessory_cost /
        install_cost / total / breakdown / formula_used / warning / fullness
        （折数法时另含 pleat_count / per_panel_pleats / open_count / margin / source / craft_tier
        以及 fullness_actual）
        （**仅定宽买高**时另含 `panels` 幅数：定高买宽按宽买米、幅数无定义 ⇒ **键缺席**，
        不补 0/1 —— issue #4374 交付物 3）

    语义分工（issue #4118 ④）：
        `fullness` = **理论**倍数（档位名义值 / 款式默认值），随档位走；
        `fullness_actual` = **实际**倍数（折数法用料 ÷ 窗宽，仅折数法给出），随用料走。
        顾客自报折数时二者不等（如 48 折 → 理论 2.0 / 实际 1.86）⇒ 展示必须取实际值。

    默认档告警（issue #4118 ⑤-B）：
        `mounting=s_hook` 且未传 `craft_tier`/`pleat_count` ⇒ 仍走倍数法（**数值一字不变**），
        但 `warning` 里**显式**说明「本次按倍数法计价、非标准档折数法」——此前这句是缺失的
        （静默回落）。告警只治静默，不改口径。
    """
    # 褶皱倍数默认值
    N = fullness if fullness is not None else DEFAULT_FULLNESS.get(mounting, 2.0)

    # 韩褶折数法（工艺档位或客户自报折数触发）：用料 = 0.25 × 折数 + 余量
    pleat_mode = mounting == "s_hook" and (pleat_count is not None or craft_tier is not None)
    pleat_fields: Dict[str, Any] = {}
    # 幅数（`panels`）：**只在真的算了幅数的分支**（定宽买高）才有值 —— 定高买宽按宽买米，
    # 幅数无定义 ⇒ 键缺席（不发明数字：既不补 0，也不补 1 冒充「1 幅」）。
    panels: Optional[int] = None
    if pleat_mode:
        if pleat_count is None:
            tier = DEFAULT_CRAFT_TIERS.get(craft_tier or "standard", DEFAULT_CRAFT_TIERS["standard"])
            pleat_count, tier_warning = derive_pleat_count(window_width, tier["fullness"], open_count)
            N = tier["fullness"]
        else:
            tier_warning = ""
        # 拼色每折吃布系数（用户 2026-09-19 裁定）：`style=拼色` + 特殊选项 `拼1次`/`拼2次`
        # ⇒ 0.65 / 1.2 米每折；其余（含只给 style 没给拼次）⇒ 单色 0.25。余量不随拼色变化。
        per_fold = resolve_per_fold(style, special_options)
        meters, pleat_warning, info = calculate_fabric_by_pleats(
            pleat_count, open_count, source=source, width=window_width, per_fold=per_fold
        )
        warning = " ".join(w for w in [tier_warning, pleat_warning] if w)
        # 「拼色但没给拼次」不得静默：无系数依据时如实告警（本单不发明口径，按单色算但说出来）。
        if style == STYLE_MIXED and per_fold == PLEAT_FABRIC_PER_FOLD:
            gap = mixed_per_fold_gap(special_options)
            warning = (warning + " " if warning else "") + (
                f"款式为拼色但未给出纸表已登记的拼次（{'/'.join(f'拼{n}次' for n in sorted(MIXED_COLOR_PER_FOLD_BY_TIMES))}），"
                f"本次按单色每折 {PLEAT_FABRIC_PER_FOLD:g} 米计算，非拼色用料系数。"
            )
            if gap:
                warning += f"（{gap} 的用料系数纸表未登记，需先裁定）"
        formula_used = "fixed_height_pleats"
        if window_height + HEM_MARGIN > fabric_width:
            panels = math.ceil(meters / fabric_width)
            meters = panels * (window_height + HEM_MARGIN + (pattern_repeat if has_pattern else 0.0))
            formula_used = "fixed_width_pleats"
            warning = (warning + " " if warning else "") + (
                f"成品高 {window_height:.2f}m 超过门幅 {fabric_width:.2f}m 的定高上限，"
                f"已按定宽布（买高）计算，幅数 {panels} 幅。"
            )
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
            # 顾客自报折数时二者必然不等，卡片必须两个都能读到（issue #4118 ④：算了就丢 = 只能拿理论值骗顾客）。
            # ⚠️ 只透传，**不改** `fullness` 的既有含义（那会动既有契约）。
            pleat_fields["fullness_actual"] = info["fullness_actual"]
    else:
        meters, formula_used, warning = calculate_fabric_meters(
            window_width=window_width,
            window_height=window_height,
            fullness=N,
            fabric_width=fabric_width,
            mounting=mounting,
            has_pattern=has_pattern,
            pattern_repeat=pattern_repeat,
        )
        if formula_used == "fixed_width":
            # 定宽买高：幅数在 `calculate_fabric_meters` 内算出（局部变量 `panels`）却没进返回值
            # ⇒ 报价卡「幅数」行永不出现（issue #4374 交付物 3）。此处按**同一公式**
            # （`ceil((W + SIDE_MARGIN) × N / G)`，与 `calculate_fabric_meters` 的定宽分支逐字同源）
            # 复算暴露它 —— **入参一字未动 ⇒ 米数/金额逐值不变**（本单不改钱）。
            panels = math.ceil((window_width + SIDE_MARGIN) * N / fabric_width)
        if mounting == "s_hook":
            # issue #4118 ⑤-B：韩褶（s_hook）的**标准档口径是折数法**，但折数法只在显式传
            # `craft_tier` / `pleat_count` 时触发（`pleat_mode` 判据）⇒ 两者都缺时这里**静默**
            # 走了倍数法：实测同一单（6.6m 窗 / 2.6m 高 / 双开 / 3.2m 门幅）倍数法 13.8 米，
            # 而标准档折数法 13.3 米（52 折），差 0.5 米却**零告警**。
            # 治法 = **只补显式告警、不动一个数值**（把默认档接成标准档 = 改既有报价口径 = 改钱，
            # 需客户裁定，不在本包）。
            warning = (warning + " " if warning else "") + (
                "未指定工艺档位（craft_tier）或折数（pleat_count），"
                f"本次按倍数法计价（{N:g} 倍），非标准档折数法；"
                "如需标准档请传 craft_tier 或 pleat_count。"
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

    total = fabric_cost + processing_cost + accessory_cost + install_cost

    breakdown = [
        {"name": "面料", "detail": f"{meters:.2f}米 × ¥{fabric_price}/米", "cost": round(fabric_cost, 2)},
        {"name": "加工费", "detail": f"{meters:.2f}米 × ¥{processing_price}/米", "cost": round(processing_cost, 2)},
        *accessory_breakdown,
        {"name": "安装费", "detail": f"{rod_length:.2f}米 × ¥{INSTALL_PRICE}/米", "cost": round(install_cost, 2)},
    ]

    return {
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
        "total": round(total, 2),
        "breakdown": breakdown,
        "formula_used": formula_used,
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
    }


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


class CurtainCalcTool(BaseTool):
    """窗帘算料报价 Tool

    根据窗户尺寸 + 悬挂方式 + 面料信息，计算用布量与报价。
    纯计算（read_only），不修改任何数据。
    """

    name = "curtain_calc"
    description = (
        "计算窗帘用布量与报价。用户询问窗帘需要多少布、多少钱、怎么算料时调用。"
        "【前置】需要窗宽(米)、窗高(米)；面料单价可通过 product_detail 查询得到。"
        "【折数法·韩褶】mounting=s_hook 时可用折数法：用料 = 0.25×折数 + 余量（单开0.2/多开0.3）。"
        "顾客自报折数或自报用料时：把折数传 pleat_count；或传 craft_tier=economy 出省料档对比。"
        "开数传 open_count（1/2/4），对开折数须偶数、四开能被 4 整除。"
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
                "description": "面料门幅（米），默认 2.8。窄幅布为 1.4",
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
                "description": "打开方式开数：1 单开 / 2 双开 / 4 四开（默认 1）。对开总折数必须偶数、四开能被 4 整除",
            },
            "pleat_count": {
                "type": "integer",
                "description": "折数（韩褶折数法，mounting=s_hook 时有效）。客户自报折数/用料时传此值；用料 = 0.25×折数 + 余量（单开0.2/多开0.3）",
            },
            "source": {
                "type": "string",
                "description": "折数/用料取值来源：formula 公式计算 / manual 人工指定 / customer_quoted 客户自报（默认 formula）",
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
                "description": "款式（引导清单/顾客选择）：单色/拼色",
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

        try:
            quote = build_quote(
                window_width=float(window_width),
                window_height=float(window_height),
                mounting=mounting,
                fullness=fullness,
                fabric_width=float(fabric_width),
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
            )

            logger.info(
                f"[curtain-calc] quote: W={window_width} H={window_height} "
                f"mounting={mounting} fullness={quote['fullness']} "
                f"meters={quote['fabric_meters']} total={quote['total']} "
                f"formula={quote['formula_used']} | tenant={context.tenant_id}"
            )

            return ToolResult(
                success=True,
                data=quote,
                summary=(
                    f"算料结果：{quote['fabric_meters']}米，总价¥{quote['total']} "
                    f"（面料¥{quote['fabric_cost']}+加工¥{quote['processing_cost']}"
                    f"+辅料¥{quote['accessory_cost']}+安装¥{quote['install_cost']}）"
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
