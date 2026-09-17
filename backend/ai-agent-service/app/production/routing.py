"""窗帘工艺路线实例化（issue #3993，M4-G-1）

工序库种子（分组：裁剪/车位/后道/其他；按部位分设——韩褶-布/韩褶-纱 单价各自不同）
+ 工艺路线模板（部位×工艺）+ 条件工序（特殊选项触发）+ 工序实例（应做数量=引擎输出）。

真值源：docs/curtain-production-rules.md §2/§3（2026-09 行业 ERP 截图实证）。
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── 工序库种子（【默】单价占位，商家可配；单位：米/折/幅/套/个）──
# 分组：裁剪 / 车位 / 后道 / 其他（行业 ERP 实证，非按阶段）
OPERATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "精裁-布": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "精裁-纱": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "裁剪-布": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "裁剪-纱": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "布三边": {"group": "车位", "unit": "米", "unit_price": 0.4},
    "纱三边": {"group": "车位", "unit": "米", "unit_price": 0.4},
    "韩褶-布": {"group": "车位", "unit": "折", "unit_price": 0.4},
    "韩褶-纱": {"group": "车位", "unit": "折", "unit_price": 0.4},
    "上车布-布": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "上车布-纱": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "打孔-布": {"group": "车位", "unit": "孔", "unit_price": 0.15},
    "打孔-纱": {"group": "车位", "unit": "孔", "unit_price": 0.15},
    "拼1次-布": {"group": "车位", "unit": "幅", "unit_price": 0.8},
    "拼2次-布": {"group": "车位", "unit": "幅", "unit_price": 1.2},
    "拼3次-布": {"group": "车位", "unit": "幅", "unit_price": 1.6},
    "花边-布": {"group": "车位", "unit": "米", "unit_price": 0.6},
    "铅坠-布": {"group": "车位", "unit": "米", "unit_price": 0.3},
    "接高-布": {"group": "车位", "unit": "幅", "unit_price": 1.0},
    "帘头制作": {"group": "车位", "unit": "个", "unit_price": 2.0},
    "熨烫-布": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "定型-布": {"group": "后道", "unit": "米", "unit_price": 0.4},
    "复烫-布": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "布帘车被": {"group": "后道", "unit": "米", "unit_price": 0.4},
    "外帘打卷": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "外帘装袋": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "质检": {"group": "后道", "unit": "套", "unit_price": 1.5},
    "外帘发货": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "绑带-布": {"group": "其他", "unit": "套", "unit_price": 0.5},
    "抱枕": {"group": "其他", "unit": "个", "unit_price": 2.0},
    "腰靠垫": {"group": "其他", "unit": "个", "unit_price": 2.0},
}

# ── 工艺路线模板（部位×工艺 → 基准工序序列）──
# 布帘·韩褶：行业 ERP 实证 11 道走线（2026-09 截图）
ROUTINGS: Dict[str, List[str]] = {
    ("布帘", "韩褶"): [
        "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "打孔"): [
        "精裁-布", "布三边", "打孔-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "四爪钩"): [
        "精裁-布", "布三边", "上车布-布", "熨烫-布",
        "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "穿杆"): [
        "精裁-布", "布三边", "熨烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("纱帘", "韩褶"): [
        "精裁-纱", "纱三边", "韩褶-纱", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("帘头", "平幔"): [
        "精裁-布", "布三边", "帘头制作", "定型-布", "外帘打卷", "外帘装袋", "外帘发货",
    ],
}

# ── 特殊选项 → 条件工序（插在目标工序后；一分二为计件系数不插工序）──
SPECIAL_OPTION_ROUTINGS: Dict[str, Dict[str, Any]] = {
    "拼1次": {"operation": "拼1次-布", "after": "布三边"},
    "拼2次": {"operation": "拼2次-布", "after": "布三边"},
    "拼3次": {"operation": "拼3次-布", "after": "布三边"},
    "加花边": {"operation": "花边-布", "after": "布三边"},
    "加铅块": {"operation": "铅坠-布", "after": "布三边"},
    "接高": {"operation": "接高-布", "after": "精裁-布"},
    "双眼皮接高": {"operation": "接高-布", "after": "精裁-布"},
    "余料做绑带": {"operation": "绑带-布", "after": "布帘车被"},
    "一分二": {"factor": 1.7},  # 计件系数（同族选项，行业 ERP 实证 1.7）
}

# 必完工序 / 生产开始标记（默认；商家可配「此工序必须完成才可打包」）
MUST_FINISH_OPS = {"外帘装袋"}   # 打包前置（截图「此工序必须完成才可打包」）
START_MARKER_OPS = {"精裁-布", "精裁-纱"}  # 首工序触发订单进入生产中


# 应做数量的来源键（**契约钉死点**，issue #4116 契约漂移修复）
# ---------------------------------------------------------------------------
# 病根：`_qty_for` 读 `meters`，而算料引擎 `curtain_calc.build_quote` 实际返回的是
# **`fabric_meters`**（键名不同）⇒ 一旦接线到真实引擎产出，「米」类工序应做数量**恒 0**
# （幅/套类再叠加「读不到 panels/set_count」⇒ 恒 1）。这段漂移此前藏在**零调用者**的死代码里
# （routing.py 在本仓无运行时消费者），靠 `tests/test_production/test_routing.py` 用**引擎真产出**
# 喂 `_qty_for` 才照出来。
#
# 本常量是「_qty_for 会读哪些键」的单一清单，测试用它把两侧键集钉住
# （引擎真产出键集 ⊇ 各 unit 的主键，或显式登记为待补键）。
METER_KEYS = ("fabric_meters", "meters")   # 主键 = 引擎真产出；`meters` 为兼容位（同族工具聚合视图口径）
FOLD_KEYS = ("pleat_count",)               # 韩褶折数法才产出；非折数法（定宽米数法）缺失 ⇒ 兜底 1
HOLE_KEYS = ("holes",)                     # 引擎暂未产出 ⇒ 按 HOLE_PER_METER 估算（见 _qty_for）
PANEL_KEYS = ("panels",)                   # 引擎暂未产出（build_quote 内部局部量）⇒ 兜底 1，待补
SET_KEYS = ("set_count",)                  # 引擎暂未产出 ⇒ 兜底 1（一个部位 = 一樘，语义成立）

# 孔数估算：引擎不产出 `holes` 时的行业口径（每米约 6 孔；12.3 米 → 72 孔与现场核对一致）
HOLE_PER_METER = 6


def _qty_for(operation: str, calc_info: Dict[str, Any]) -> float:
    """应做数量 = 算料引擎输出（折数/用料/孔数/幅数/套数），报工只确认不心算。

    键口径见模块常量（{@link METER_KEYS} 等）；缺键**一律兜底 1**，绝不落 0
    （应做 0 会让 `done_qty ≥ qty` 恒真 ⇒ 工序一开始就算完成 ⇒ 假完工，同族缺陷）。
    """
    unit = OPERATION_CATALOG.get(operation, {}).get("unit", "米")
    if unit == "折":
        return float(_pick(calc_info, FOLD_KEYS, 1))
    if unit == "孔":
        holes = _pick(calc_info, HOLE_KEYS, None)
        if holes is not None:
            return float(holes)
        meters = _pick(calc_info, METER_KEYS, 0)
        # 引擎真产出没有 holes（见 HOLE_KEYS 注释）：按每米 6 孔估算；米数也读不到才兜底 1
        return float(meters) * HOLE_PER_METER if meters else 1.0
    if unit == "幅":
        return float(_pick(calc_info, PANEL_KEYS, 1))
    if unit == "套":
        return float(_pick(calc_info, SET_KEYS, 1))
    return float(_pick(calc_info, METER_KEYS, 1))  # 米


def _pick(calc_info: Dict[str, Any], keys: tuple, default: Any) -> Any:
    """按 keys 顺序取第一个非空值（键名漂移的双读兼容），全缺 ⇒ default。"""
    for key in keys:
        value = calc_info.get(key)
        if value is not None:
            return value
    return default


def build_routing(position: Dict[str, Any]) -> List[str]:
    """部位×工艺基准路线 + 条件工序（特殊选项触发）+ 定型开关。

    Args:
        position: {curtain_type, craft, is_shaped, special_options: [..]}
    Returns: 工序名序列
    """
    curtain_type = position.get("curtain_type", "布帘")
    craft = position.get("craft", "韩褶")
    key = (curtain_type, craft)
    if key not in ROUTINGS:
        raise ValueError(f"不支持的 部位×工艺 组合: {key}")
    route = list(ROUTINGS[key])

    # 定型=否 → 移除 定型-布/复烫-布（部位级开关）
    if position.get("is_shaped") is False:
        route = [op for op in route if op not in ("定型-布", "复烫-布")]

    # 特殊选项条件工序（按 after 定位插入）
    specials = position.get("special_options") or []
    for opt in specials:
        rule = SPECIAL_OPTION_ROUTINGS.get(opt)
        if rule and "operation" in rule:
            route = _insert_after(route, rule["operation"], rule["after"])
    return route


def _insert_after(route: List[str], operation: str, after: str) -> List[str]:
    """把 operation 插到 after 之后（after 不在路线中则追加到末尾）。"""
    try:
        idx = route.index(after)
    except ValueError:
        route.append(operation)
        return route
    route.insert(idx + 1, operation)
    return route


def instance_operations(
    position: Dict[str, Any],
    calc_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """实例化工序（应做数量=引擎输出 + 单价 + 必完/开始标记 + 特殊选项系数）。

    Args:
        position: {curtain_type, craft, is_shaped, special_options, open_count}
        calc_info: 算料引擎输出（`curtain_calc.build_quote` 的返回，键见 METER_KEYS/FOLD_KEYS 等；
                   缺 `panels`/`set_count`/`holes` 时按 _qty_for 的兜底口径处理，不落 0）
    Returns: 工序实例列表 [{seq, operation, group, unit, qty, unit_price, factor,
             is_must_finish, is_start_marker, qty_source}]
    """
    route = build_routing(position)
    specials = position.get("special_options") or []
    factor = 1.0
    for opt in specials:
        rule = SPECIAL_OPTION_ROUTINGS.get(opt)
        if rule and "factor" in rule:
            factor = float(rule["factor"])

    instances: List[Dict[str, Any]] = []
    for seq, operation in enumerate(route, start=1):
        meta = OPERATION_CATALOG[operation]
        instances.append({
            "seq": seq,
            "operation": operation,
            "group": meta["group"],
            "unit": meta["unit"],
            "qty": _qty_for(operation, calc_info),
            "unit_price": meta["unit_price"],
            "factor": factor,
            "is_must_finish": operation in MUST_FINISH_OPS,
            "is_start_marker": operation in START_MARKER_OPS,
            "qty_source": calc_info.get("source", "formula"),
        })
    return instances
