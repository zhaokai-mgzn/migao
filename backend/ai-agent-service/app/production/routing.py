"""窗帘工艺路线实例化（issue #3993，M4-G-1）

工序库种子（分组：裁剪/车位/后道/其他；按部位分设——韩褶-布/韩褶-纱 单价各自不同）
+ 工艺路线模板（部位×工艺）+ 条件工序（特殊选项触发）+ 工序实例（应做数量=引擎输出）。

真值源：docs/curtain-production-rules.md §2/§3（2026-09 行业 ERP 截图实证）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    # ── issue #4230：特殊选项 A′ 类补齐的 5 道工序（单价为**行业推算**，商家可配）──
    # 推理依据（issue #4230 §2.2）：绑带-纱 与 绑带-布 对称；logo条-布 参照 花边-布 ¥0.6/米
    # （同为缝一条装饰带）；立边-布 参照 布三边 ¥0.4/米（立边更费工）；扣环-布 参照
    # 打孔-布 ¥0.15/孔 ×2（多一道锁边）；防翘扣-布 比扣环简单。
    "绑带-纱": {"group": "其他", "unit": "套", "unit_price": 0.5},
    "logo条-布": {"group": "车位", "unit": "米", "unit_price": 0.6},
    "立边-布": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "扣环-布": {"group": "车位", "unit": "个", "unit_price": 0.3},
    "防翘扣-布": {"group": "车位", "unit": "个", "unit_price": 0.2},
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

# ── 特殊选项 → 条件工序（插在目标工序后；`after` = **锚点在它之前**，见 `_insert_after`）──
# 真值源 §1【默】19 项特殊选项，按处置分三类（**每一类都要显式登记**，见下方
# `NON_PIECEWORK_OPTIONS` / `OPTION_FACTOR_SCOPES` 的注释；门禁 =
# `tests/test_production/test_special_options.py::TestCriterion1CoverageGate`）：
#   ① 加条件工序 = 本表；② 加计件系数 = `OPTION_FACTOR_SCOPES`；③ 不计件 = `NON_PIECEWORK_OPTIONS`。
SPECIAL_OPTION_ROUTINGS: Dict[str, Dict[str, Any]] = {
    "拼1次": {"operation": "拼1次-布", "after": "布三边"},
    "拼2次": {"operation": "拼2次-布", "after": "布三边"},
    "拼3次": {"operation": "拼3次-布", "after": "布三边"},
    "加花边": {"operation": "花边-布", "after": "布三边"},
    "加铅块": {"operation": "铅坠-布", "after": "布三边"},
    "接高": {"operation": "接高-布", "after": "精裁-布"},
    "双眼皮接高": {"operation": "接高-布", "after": "精裁-布"},
    "余料做绑带": {"operation": "绑带-布", "after": "布帘车被"},
    # ── issue #4230：19 项里有 10 项此前**零登记**（既不加工序、也不加系数、也没标不计件），
    # 「忘了映射」与「本来就不计件」在数据上长得一模一样（都是 `.get(opt)` → None 的静默黑洞）。
    # 以下按用户裁定（2026-09-18「按你的行业推算补齐，落成数据，客户反馈再改」）补齐：
    "布绑带": {"operation": "绑带-布", "after": "布帘车被"},      # 推算：与「余料做绑带」同工序，仅材料来源不同
    "余料做帘头": {"operation": "帘头制作", "after": "布三边"},    # 推算：复用库里已有的孤儿工序「帘头制作」
    "抱枕": {"operation": "抱枕", "after": "外帘打卷"},           # 推算：复用孤儿工序「抱枕」，插在打卷后（装袋前）
    "纱绑带": {"operation": "绑带-纱", "after": "布帘车被"},
    "加logo条": {"operation": "logo条-布", "after": "布三边"},
    "加立边": {"operation": "立边-布", "after": "布三边"},
    "扣环": {"operation": "扣环-布", "after": "布三边"},
    "防翘扣": {"operation": "防翘扣-布", "after": "布三边"},
}

# ── 特殊选项 → 计件系数（真值源 §4「条件系数表：特殊选项 → **工序** → 系数」）──
# 每个选项一个**档位列表**（按书写顺序解析，**后面的档覆盖前面的档** —— 与 CSS/路由表同构：
# 先写平摊档，再写逐工序/逐部位的**例外**档），档位字段：
#   `factor`         系数（乘在工序实例的 `factor` 上）
#   `operation_name` 限定工序名；`None` = 该**部位全部**工序（平摊档）
#   `curtain_type`   限定部位（布帘/纱帘/帘头）；`None` = 不限部位
#   `source`         `实证` / `推算`（真值源标注口径，商家可配版本化）
#
# v1 **只种「一分二 ⇒ 1.7 / 全部工序」一个档** —— 它是唯一的**实证**值（真值源 §4 + 行业 ERP）。
# issue #4230 §2.4 的逐工序/逐分组细算档（车位 ≈×2.0 / 后道 ×1.0 / 裁剪 ×1.2）是**纯推算**，
# 且按其细算的总价会**低于**平摊 ×1.7 ⇒ **不拿推算值覆盖实证值**，v1 不启用、不种值。
# 结构留 `operation_name` / `curtain_type` 两个限定档位，等客户确认后再细化（不把路堵死）——
# 「该档位可用」由 `test_operation_scoped_factor_applies_to_that_operation_only` 以限定值构造证明。
OPTION_FACTOR_SCOPES: Dict[str, List[Dict[str, Any]]] = {
    "一分二": [
        {"factor": 1.7, "operation_name": None, "curtain_type": None, "source": "实证"},
    ],
}

# ── 不影响计件的特殊选项（**显式登记**，不留静默黑洞）──
# 真值源 §1【默】把这两项与其余 17 项并列列出，但它们的业务语义是**只是把余料还给客户**，
# 不增加车间任何工序、也不改变已有工序的费工程度 ⇒ 既不加工序也不加系数、计件金额不变。
# 登记在这里的唯一理由：让「本来就不计件」与「忘了映射」在数据上**可区分**
# （前者在这里有名字，后者会撞 `TestCriterion1CoverageGate` 的红）。
NON_PIECEWORK_OPTIONS = frozenset({"余料带回(布)", "余料带回(纱)"})

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

# 引擎有数量口径的单位（= `_qty_for` 的分支覆盖范围）；其余单位（如「个」）无口径
# ⇒ 调用方按铁律「未知单位兜底 1 + fallback」处置（见 `qty_and_source`）。
KNOWN_QTY_UNITS = ("米", "折", "孔", "幅", "套")


def _qty_keys_for_unit(unit: Optional[str]) -> tuple:
    """该单位应做数量会读的候选键（**有序**）——与 `_qty_for` 的分支逐条对应。

    存在理由（issue #4208）：内部端点要回答 `qty_source_by_operation`（口径来源），
    而「哪个键供了数」这件事只在 `_qty_for` 的分支里。此处把它声明成数据供标注
    —— **数量值仍由 `_qty_for` 给出，本函数不参与计算**（严禁第二份算料逻辑）。
    漂移护栏：`tests/test_production/test_operation_qty.py::TestSourceKeysDriftGate`
    逐单位喂键反查 `_qty_for` 是否真读该键（改 `_qty_for` 的读键而不改这里 ⇒ 红）。
    """
    if unit == "折":
        return FOLD_KEYS
    if unit == "孔":
        return HOLE_KEYS + METER_KEYS   # holes 直采；无 holes 时按米数估算
    if unit == "幅":
        return PANEL_KEYS
    if unit == "套":
        return SET_KEYS
    if unit == "米":
        return METER_KEYS
    return ()   # 引擎不认识的工序/单位：无口径 ⇒ 兜底 1 + fallback

# 非「孔」单位**直接供数**的键（命中即报键名）：引擎真产出 `fabric_meters`/`pleat_count`。
# 「孔」的直采键是 `holes`（引擎暂未产出，见 HOLE_KEYS 注释，但调用方可按现场口径给出），
# 在 `qty_and_source` 的「孔」分支单独处理 —— 该分支还有「按米估算」这一中间态。
DIRECT_QTY_KEYS = ("fabric_meters", "pleat_count")

# `qty_source` 的三态语义（字段存在的唯一理由：让「真兜底」与「有依据的推算」可区分）
#   ① 键名（DIRECT_QTY_KEYS）           = 该键直接供数（算料输出 / 现场给定）
#   ② "<键名>_x6"（HOLE_PER_METER 后缀）= 无 holes 时按**每米 HOLE_PER_METER 孔**的行业口径
#      估算（见 `_qty_for` 的「孔」分支②；12.3 米 → 73.8 孔，与现场核对一致）
#      ⇒ 标 fallback 会把「有依据的估算」说成「占位值」，正是本单要治的误导
#   ③ "fallback"                        = 真兜底：无键可读 / 引擎不认识的工序或单位 /
#      panels・set_count（引擎已登记为**待补键**：见 PANEL_KEYS/SET_KEYS 注释，未产出）
HOLE_ESTIMATE_SUFFIX = f"_x{HOLE_PER_METER}"


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


def qty_and_source(operation: str, calc_info: Dict[str, Any]) -> tuple:
    """应做数量 + 口径来源标签（issue #4208）：`(qty, qty_source)`。

    数量：命中算料键 ⇒ 一律取 `_qty_for`（**唯一算料真相源**，严禁第二份逻辑）；
    无口径（缺键 / 引擎不认识的工序 / 引擎不认识的单位）⇒ **兜底 1，绝不落 0**
    （应做 0 ⇒ `done_qty ≥ qty` 恒真 ⇒ 假完工）。

    来源标签三态见模块常量注释（{@link DIRECT_QTY_KEYS} / {@link HOLE_ESTIMATE_SUFFIX}）：
    键名 = 直接供数；`<键名>_x6` = 每米 6 孔的行业估算；"fallback" = 真兜底。
    调用方据此区分「算料输出 / 有依据的估算 / 兜底占位」，**不据此报错**（判据 3：HTTP 仍 200）。
    """
    unit = OPERATION_CATALOG.get(operation, {}).get("unit")
    for key in _qty_keys_for_unit(unit):
        if calc_info.get(key) is None:
            continue
        qty = _qty_for(operation, calc_info)
        if unit == "孔":
            # 分支① holes 直采；分支② 无 holes 有米数 ⇒ 每米 HOLE_PER_METER 孔的行业估算
            # （分支②的值 ≠ 真兜底 1.0 ⇒ 必须可与分支③区分，否则「有依据的估算」被说成占位值）
            return (qty, key) if key in HOLE_KEYS else (qty, f"{key}{HOLE_ESTIMATE_SUFFIX}")
        if key in DIRECT_QTY_KEYS:
            return qty, key
        # panels / set_count：引擎**待补键**（PANEL_KEYS/SET_KEYS 注释）⇒ 不是算料输出
        return qty, "fallback"
    return 1.0, "fallback"


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

    # 特殊选项条件工序（按 after 定位插入；`NON_PIECEWORK_OPTIONS` 与纯系数选项无 operation 档 ⇒ 跳过）
    specials = position.get("special_options") or []
    for opt in specials:
        rule = SPECIAL_OPTION_ROUTINGS.get(opt)
        if rule and "operation" in rule:
            route = _insert_after(route, rule["operation"], rule["after"])
    return route


def _scope_applies(scope: Dict[str, Any], position: Dict[str, Any], operation: str) -> bool:
    """档位是否作用于该（部位, 工序）——`None` 限定 = 不限（见 `OPTION_FACTOR_SCOPES` 注释）。"""
    operation_name = scope.get("operation_name")
    if operation_name is not None and operation_name != operation:
        return False
    curtain_type = scope.get("curtain_type")
    return curtain_type is None or curtain_type == position.get("curtain_type", "布帘")


def factor_for(position: Dict[str, Any], operation: str) -> float:
    """该工序实例的特殊选项计件系数（真值源 §4 条件系数表；无选项 ⇒ 1.0）。

    单个选项内：**后面的档覆盖前面的档**（最后一个命中的档生效，见 `OPTION_FACTOR_SCOPES`
    注释）—— 逐工序/逐部位的**例外档**因此能盖住平摊档，而**不是**与它相乘
    （相乘会把「平摊 ×1.7 + 车位 ×2.0」算成 ×3.4，纯属重复计费）。
    多个加系数选项并存：各自解出的系数**相乘**（独立倍率的合成口径；v1 只种「一分二」一个档）。
    只认 `OPTION_FACTOR_SCOPES` 登记过的选项：未登记的名字**不得**悄悄改系数。
    """
    factor = 1.0
    for opt in position.get("special_options") or []:
        resolved = None
        for scope in OPTION_FACTOR_SCOPES.get(opt, ()):
            if _scope_applies(scope, position, operation):
                resolved = float(scope["factor"])   # 后档覆盖前档
        if resolved is not None:
            factor *= resolved
    return factor


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
            "factor": factor_for(position, operation),
            "is_must_finish": operation in MUST_FINISH_OPS,
            "is_start_marker": operation in START_MARKER_OPS,
            "qty_source": calc_info.get("source", "formula"),
        })
    return instances
