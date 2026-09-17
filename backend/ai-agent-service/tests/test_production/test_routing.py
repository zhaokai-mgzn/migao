"""工艺路线实例化测试（app/production/routing.py，issue #3993，M4-G-1）"""
# case_ids: PP-010
import pytest

from app.production.routing import (
    OPERATION_CATALOG,
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
