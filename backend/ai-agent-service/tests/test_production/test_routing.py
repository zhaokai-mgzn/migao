"""工艺路线实例化测试（app/production/routing.py，issue #3993，M4-G-1）"""
# case_ids: PP-010
import pytest

from app.production.routing import (
    HOLE_KEYS,
    HOLE_PER_METER,
    METER_KEYS,
    OPERATION_CATALOG,
    PANEL_KEYS,
    SET_KEYS,
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