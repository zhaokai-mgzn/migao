"""工艺路线实例化测试（app/production/routing.py，issue #3993，M4-G-1）"""
# case_ids: PP-010
import pytest

from app.production.routing import (
    HOLE_KEYS,
    HOLE_PER_METER,
    METER_KEYS,
    OPERATION_CATALOG,
    PANEL_KEYS,
    PENDING_CUSTOMER_CONFIRMATION_OPERATIONS,
    ROUTINGS,
    SET_KEYS,
    SPECIAL_OPTION_ROUTINGS,
    build_routing,
    instance_operations,
)

POSITION = {
    "curtain_type": "布帘",
    "craft": "韩褶",
    "is_shaped": True,
    "special_options": [],
    "open_count": 2,
}
CALC = {
    "pleat_count": 48,
    "meters": 12.3,
    "panels": 4,
    "holes": 72,
    "set_count": 1,
    "source": "formula",
    "craft_tier": "standard",
}


def test_build_routing_korean_pleat_11_steps():
    """布帘·韩褶 11 道实证走线（行业 ERP 截图 2026-09）"""
    route = build_routing(POSITION)
    assert route == [
        "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ]


def test_build_routing_unshaped_removes_shaping():
    """定型=否 → 移除 定型-布/复烫-布（部位级开关）"""
    route = build_routing({**POSITION, "is_shaped": False})
    assert "定型-布" not in route
    assert "复烫-布" not in route
    assert "韩褶-布" in route


def test_build_routing_special_option_inserts_operation():
    """特殊选项：拼2次 → 在布三边后插入 拼2次-布"""
    route = build_routing({**POSITION, "special_options": ["拼2次"]})
    assert route.index("拼2次-布") == route.index("布三边") + 1


def test_unsupported_position_rejected():
    with pytest.raises(ValueError):
        build_routing({"curtain_type": "布帘", "craft": "波浪褶"})


def test_instance_operations_qty_from_calc():
    """应做数量=算料引擎输出：韩褶-布按折数 48、米工序按用料 12.3、套工序=1"""
    insts = instance_operations(POSITION, CALC)
    by_op = {i["operation"]: i for i in insts}
    assert by_op["韩褶-布"]["qty"] == 48
    assert by_op["韩褶-布"]["unit"] == "折"
    assert by_op["精裁-布"]["qty"] == 12.3
    assert by_op["外帘装袋"]["qty"] == 1
    assert by_op["精裁-布"]["is_start_marker"] is True
    assert by_op["外帘装袋"]["is_must_finish"] is True
    assert by_op["韩褶-布"]["qty_source"] == "formula"


def test_instance_operations_one_split_factor():
    """一分二 特殊选项 → 计件系数 ×1.7（不插工序）"""
    insts = instance_operations({**POSITION, "special_options": ["一分二"]}, CALC)
    assert all(i["factor"] == 1.7 for i in insts)
    assert all(i["operation"] != "一分二" for i in insts)


def test_operation_catalog_grouping():
    """工序库分组与按部位分设（韩褶-布/韩褶-纱 独立）"""
    assert OPERATION_CATALOG["韩褶-布"]["group"] == "车位"
    assert OPERATION_CATALOG["精裁-布"]["group"] == "裁剪"
    assert OPERATION_CATALOG["外帘发货"]["group"] == "后道"
    assert "韩褶-布" in OPERATION_CATALOG and "韩褶-纱" in OPERATION_CATALOG


# ══════════════════════════════════════════════════════════════════════════════
# 契约漂移回归（issue #4116）：`_qty_for` 的键集 vs 算料引擎**真产出**
#
# 病根：`_qty_for` 读 `meters`，而 `curtain_calc.build_quote` 实际返回 **`fabric_meters`**
# ⇒ 接线到引擎真产出后「米」类工序应做数量**恒 0**（幅/套类再叠加读不到 panels/set_count
# ⇒ 恒 1）。这段漂移此前藏在**零运行时消费者**的死代码里，只有用引擎真产出喂
# `instance_operations` 才照得出来（下面的用例就是这么构造的）。
#
# 红证：把 `METER_KEYS` 里的 `fabric_meters` 去掉（或让 `_qty_for` 回到读 `meters`）⇒
# `test_qty_for_uses_real_engine_output` 必红（精裁-布 qty 由 12.3 变 0/1）。
# ══════════════════════════════════════════════════════════════════════════════


def _quote_source_keys() -> set:
    """算料引擎 build_quote **返回字典**的字面量键集（从源码文本解析，不 import 执行）。

    为什么用源码解析而不是调用引擎：本用例要断言的是「引擎**产出**了哪些键」这一
    **契约事实**，调用一次只能说明某个输入下的取值，换个输入（如非折数法）键就变了。
    解析对象 = `return {...}` 里显式写出的键 + `**pleat_fields` 展开的键集。
    """
    import re
    from pathlib import Path

    import app.tools.curtain_calc as calc

    source = Path(calc.__file__).read_text(encoding="utf-8")
    start = source.index("def build_quote")
    end = source.index("def calculate_multi_position", start)
    body = source[start:end]
    keys = set(re.findall(r'^\s+"([a-z_]+)":', body, re.M))
    # `**pleat_fields` 展开：其键在 pleat_fields = {...} 里显式写出
    if "**pleat_fields" in body:
        pleat_block = re.search(r"pleat_fields\s*=\s*\{(.*?)\}", body, re.S)
        assert pleat_block, "pleat_fields 字面量结构变了，请同步本解析器"
        keys |= set(re.findall(r'"([a-z_]+)":', pleat_block.group(1)))
    return keys


def test_engine_quote_keys_are_pinned():
    """引擎真产出键集**钉死**（改名/删除即红）—— 这是 _qty_for 契约的另一侧"""
    keys = _quote_source_keys()
    # 本包依赖的引擎真产出键：米数主键就在这里
    assert "fabric_meters" in keys, "引擎不再产出 fabric_meters ⇒ _qty_for 的米数契约已破"
    assert "pleat_count" in keys, "引擎不再产出 pleat_count ⇒ 折数类工序应做数量失据"


def test_qty_for_uses_real_engine_output():
    """用**引擎真产出**喂 instance_operations：米/折类应做数量不得落 0（红证判据）"""
    from app.tools.curtain_calc import build_quote

    quote = build_quote(
        window_width=3.0, window_height=2.6, mounting="s_hook",
        fabric_price=80, craft_tier="standard", open_count=2,
    )
    # 前置自断言：真产出里确实有 fabric_meters（否则本用例的前提不成立，等于空跑）
    assert quote["fabric_meters"] > 0, f"引擎真产出异常: {quote}"

    insts = instance_operations(POSITION, quote)
    by_op = {i["operation"]: i for i in insts}

    assert by_op["精裁-布"]["qty"] == quote["fabric_meters"], (
        "米类工序应做数量必须等于引擎产出的 fabric_meters"
        "（读 meters 时这里会变成 0 —— issue #4116 的契约漂移形态）"
    )
    assert by_op["韩褶-布"]["qty"] > 0, "折类工序应做数量不得落 0"
    assert all(i["qty"] > 0 for i in insts), (
        "任何工序应做数量落 0 ⇒ done_qty ≥ qty 恒真 ⇒ 工序一开始就算完成（假完工）"
    )


def test_qty_for_falls_back_to_one_not_zero():
    """引擎缺键（幅/套/孔）时兜底 1，绝不落 0"""
    insts = instance_operations(POSITION, {"source": "formula"})
    by_op = {i["operation"]: i for i in insts}
    assert all(i["qty"] >= 1 for i in insts), "缺键必须兜底 1（0 会让工序一开始就算完成）"
    assert by_op["外帘装袋"]["qty"] == 1  # 套
    assert by_op["韩褶-布"]["qty"] == 1  # 折（缺 pleat_count）


def test_qty_for_hole_fallback_uses_meter_key():
    """孔类：引擎无 holes ⇒ 按米数 × HOLE_PER_METER 估算；米数也缺才兜底 1"""
    from app.production.routing import _qty_for

    assert _qty_for("打孔-布", {"fabric_meters": 12.3}) == 12.3 * HOLE_PER_METER
    assert _qty_for("打孔-布", {"holes": 72}) == 72
    assert _qty_for("打孔-布", {}) == 1.0


def test_qty_keys_are_declared():
    """`_qty_for` 只会读这几个键（声明与实现一致；新增隐式读键时本断言即红）"""
    import inspect

    from app.production import routing

    body = inspect.getsource(routing._qty_for)
    assert "METER_KEYS" in body and "HOLE_KEYS" in body and "PANEL_KEYS" in body
    assert "FOLD_KEYS" in body and "SET_KEYS" in body
    # 引擎侧已知待补键（引擎暂未产出，属**显式登记**的缺口，不是静默兜底）
    for keys in (HOLE_KEYS, PANEL_KEYS, SET_KEYS):
        assert isinstance(keys, tuple) and keys, "待补键清单不得为空"
    assert METER_KEYS[0] == "fabric_meters", "米数主键必须是引擎真产出键名"


# ══════════════════════════════════════════════════════════════════════════════
# 纱帘工艺路线补齐（issue #4246，P2）
#
# 病根（真值源 §3 列了「韩褶/打孔/四爪钩/穿杆/纱帘/帘头/罗马帘」，而 ROUTINGS 只有 6 条、
# 纱帘只有「韩褶」一条）：`deriveRouteKey`（Java）派生出的「纱帘×打孔」在路线库里取不到 ⇒
# **回落默认 布帘×韩褶** ⇒ 一张「纱帘+打孔」的订单拿到**布帘的 11 道工序**（精裁-布/布三边/
# 韩褶-布…）⇒ 工人按布帘工序报工、计件按布帘单价算 ⇒ **工序与工资都是错的**。
#
# 本单只补 3 条路线，**零新造工序**（`上车布-纱` ¥0.5/米、`打孔-纱` ¥0.15/孔 早已在库里、
# 有价、零消费 —— 设计时就打算给纱帘用，只是路线没建）。
# ══════════════════════════════════════════════════════════════════════════════

#: issue #4246 §二 表格的逐字工序序列（真值源 = issue 正文，不是本测试的发明）
SHEER_ROUTES = {
    ("纱帘", "打孔"): ["精裁-纱", "纱三边", "打孔-纱", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "四爪钩"): ["精裁-纱", "纱三边", "上车布-纱", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "穿杆"): ["精裁-纱", "纱三边", "外帘打卷", "外帘装袋", "外帘发货"],
}


@pytest.mark.parametrize("key,expected", sorted(SHEER_ROUTES.items()))
def test_sheer_route_is_exact(key, expected):
    """3 条纱帘路线可用且序列与 #4246 §二 表格**逐字相等**（判据 1）"""
    curtain_type, craft = key
    route = build_routing({"curtain_type": curtain_type, "craft": craft, "is_shaped": True})
    assert route == expected, f"{curtain_type}×{craft} 路线漂移"


def test_sheer_drill_route_does_not_fall_back_to_cloth_route():
    """判据 4（本单的核心）：纱帘×打孔 命中自己的路线，**不再**回落 布帘×韩褶。

    回落形态（实现前）：`build_routing` 会抛 `ValueError`（ROUTINGS 里没有该键），
    而 Java 侧 `deriveRouteKey` 的兜底是「取不到路线 ⇒ 用默认路线 布帘×韩褶」⇒
    纱帘订单拿到 11 道布帘工序。故断言：既不得等于布帘路线，也不得含任何 `-布` 工序。
    """
    sheer_drill = build_routing({"curtain_type": "纱帘", "craft": "打孔"})
    cloth_route = build_routing({"curtain_type": "布帘", "craft": "韩褶"})
    assert sheer_drill != cloth_route, "纱帘×打孔 落回了布帘×韩褶 ⇒ 工序与计件单价全错"
    assert not [op for op in sheer_drill if op.endswith("-布")], (
        "纱帘路线上出现了布帘工序 ⇒ 工人按布帘工序报工、按布帘单价计件")
    assert "打孔-纱" in sheer_drill and "精裁-布" not in sheer_drill


def test_sheer_routes_consume_only_existing_operations():
    """零新造工序（判据 2）：3 条新路线的每道工序都必须是**已存在**的工序库条目"""
    missing = sorted({op for ops in SHEER_ROUTES.values() for op in ops
                      if op not in OPERATION_CATALOG})
    assert not missing, f"纱帘路线引用了工序库里不存在的工序（本单不许新造工序）：{missing}"


def test_operation_catalog_size_is_frozen_for_this_issue():
    """零新造工序（判据 2 红线）：工序库条目数 = V54 的 30 道 + V56 的 5 道 = 35。

    本单**只加路线**；任何「顺手加一道工序/改一个单价」都会让这里红
    （工序库 ↔ 种子 SQL 的逐行逐值比对另见
    `tests/unit_ci_workflows/test_production_catalog_seed.py`）。
    """
    assert len(OPERATION_CATALOG) == 35, (
        "工序库条目数变了 —— 本单（#4246）不许新造工序/改单价；"
        "确需新增请走新迁移 + 同步 V54∪V56∪V58 聚合守卫")
    assert OPERATION_CATALOG["上车布-纱"] == {"group": "车位", "unit": "米", "unit_price": 0.5}
    assert OPERATION_CATALOG["打孔-纱"] == {"group": "车位", "unit": "孔", "unit_price": 0.15}


def _orphan_operations() -> set:
    """有工序、有价、**零消费**的工序（既不在任何路线里，也不被任何特殊选项条件工序引用）。"""
    consumed = {op for ops in ROUTINGS.values() for op in ops}
    consumed |= {rule["operation"] for rule in SPECIAL_OPTION_ROUTINGS.values()
                 if "operation" in rule}
    return set(OPERATION_CATALOG) - consumed


def test_orphan_operations_are_explicitly_registered():
    """孤儿工序**显式登记**（判据 3）：有意不消费的 4 道必须与常量集合**恰等**。

    为什么要有这条：`上车布-纱`/`打孔-纱` 被 #4246 的新路线消费后不再是孤儿；
    `裁剪-布`/`裁剪-纱`/`质检`/`腰靠垫` **仍为孤儿**且是**有意**的（需客户确认，不许猜，
    见 #4246 §二「不做」表）⇒ 登记在 `PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`。
    双向可红：① 谁「顺手」给这 4 道建了路线 ⇒ 计算集变小 ⇒ 红（逼他显式销账并说明依据）；
    ② 谁新造了工序却没建路线/没登记 ⇒ 计算集变大 ⇒ 红（不再沉默）。
    """
    assert _orphan_operations() == set(PENDING_CUSTOMER_CONFIRMATION_OPERATIONS), (
        "孤儿工序集合漂移：有意不消费（待客户确认）与「忘了建路线」必须在数据上可区分")
    assert _orphan_operations() == {"裁剪-布", "裁剪-纱", "质检", "腰靠垫"}


def test_sheer_routes_deorphan_the_two_sheer_operations():
    """判据 3 前半：`上车布-纱` / `打孔-纱` 被新路线消费 ⇒ **不再**是孤儿"""
    orphans = _orphan_operations()
    assert "上车布-纱" not in orphans, "上车布-纱 仍零消费（#4246 的四爪钩路线没消费它）"
    assert "打孔-纱" not in orphans, "打孔-纱 仍零消费（#4246 的打孔路线没消费它）"
    assert ("纱帘", "四爪钩") in ROUTINGS and ("纱帘", "打孔") in ROUTINGS


def test_existing_routes_unchanged():
    """判据 6（不回归）：既有 6 条路线逐值不变（布帘×韩褶 仍是 11 道实证走线）"""
    assert len(ROUTINGS) == 9, "路线总数应为 既有 6 条 + #4246 新增 3 条"
    assert len(ROUTINGS[("布帘", "韩褶")]) == 11
    assert ROUTINGS[("纱帘", "韩褶")] == ["精裁-纱", "纱三边", "韩褶-纱",
                                          "外帘打卷", "外帘装袋", "外帘发货"]
    assert ROUTINGS[("帘头", "平幔")] == ["精裁-布", "布三边", "帘头制作", "定型-布",
                                          "外帘打卷", "外帘装袋", "外帘发货"]