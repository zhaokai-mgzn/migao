# case_ids: CH-042
"""`curtain_calc` **工具层**的门幅候选集接线（issue #5016）。

## 病灶（本文件要钉住的形态）

引擎侧（#5013）已能「候选门幅集内自动选门幅 + 自动推导加工类型」
（`curtain_calc.resolve_fabric_plan`，判据见 `tests/test_curtain_calc_fabric_plan.py`），
`build_quote` 也已收 `fabric_widths` —— 但**工具 schema 不收、`execute` 不传** ⇒
线上**根本走不到**那条通路（「函数写好了但没人调」）。本文件钉的就是这一层。

## 判据（每条都独立可红，互不掩盖）

1. schema 暴露 `fabric_widths`（数组、元素 number），且 `fabric_width` 的文案**明说会被忽略**；
2. 工具 `description` 告诉模型「顾客没指定门幅 ⇒ 传 fabric_widths，系统自动选」；
3. `execute(fabric_widths=[2.8, 3.2], 成品高 2.75)` ⇒ 自动解 = **3.2 门幅 + 定高买宽**
   （2.8 会判需接高：`2.75 + 0.3 = 3.05 > 2.8`）；
4. `execute(fabric_widths=[2.8, 3.2], 成品高 3.0)` ⇒ **倒幅**（`ceil(6.6/2.8) = 3` 幅）；
5. **只给 2.8**（成品高 2.75）⇒ 倒幅（候选里没有可行门幅）—— 证明候选集**真的参与判定**；
6. **不传 `fabric_widths`** ⇒ 既有单一门幅口径**逐值不变**（回归不变量）；
7. `build_quote` **真的收到** `fabric_widths`（接线红证：删掉 `execute` 里那一行 ⇒ 红）。
"""
from typing import Any, Dict, List, Optional

import pytest

from app.tools import curtain_calc as cc
from app.tools.base import ToolContext

CurtainCalcTool = cc.CurtainCalcTool

TENANT_ID = 7
USER_ID = "u-5016"

#: 基线入参（成品宽 3.0 / 2 倍褶 ⇒ 定高买宽用料 T = (3.0 + 0.3) × 2 = 6.6 米）
ANCHOR: Dict[str, Any] = {
    "window_width": 3.0,
    "fabric_price": 98.0,
    "fullness": 2.0,
}

NO_ROW_RESPONSE: Dict[str, Any] = {
    "success": True,
    "data": {"source": "default", "config": dict(cc.DEFAULT_CRAFT_CALC_CONFIG)},
}


class _FakeAdminApi:
    """`AdminApiClient` 替身：只记录出参、回一份可控响应（**不发真实 HTTP**）。"""

    def __init__(self, response: Optional[Dict[str, Any]] = None):
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    async def get(self, path: str, params=None, tenant_id=None, user_id=None, headers=None):
        self.calls.append({"path": path, "tenant_id": tenant_id, "user_id": user_id})
        return self.response


def _ctx() -> ToolContext:
    return ToolContext(tenant_id=TENANT_ID, user_id=USER_ID, role="admin", permissions=["*"])


async def _run(monkeypatch, **params):
    monkeypatch.setattr(cc, "get_admin_api_client", lambda: _FakeAdminApi(NO_ROW_RESPONSE))
    return await CurtainCalcTool().execute(_ctx(), **{**ANCHOR, **params})


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1/2 —— schema 与文案（模型看得到的契约）
# ══════════════════════════════════════════════════════════════════════════════

def test_schema_exposes_fabric_widths_candidates():
    props = CurtainCalcTool.parameters["properties"]
    assert "fabric_widths" in props, "工具 schema 必须暴露候选门幅集（否则线上走不到自动选门幅）"
    assert props["fabric_widths"]["type"] == "array"
    assert props["fabric_widths"]["items"]["type"] == "number"
    # 红证：把 `fabric_widths` 从 properties 删掉 ⇒ 本断言红
    assert "fabric_widths" not in CurtainCalcTool.parameters["required"], (
        "候选集是**可选**入参：不传 ⇒ 既有单一门幅口径（回归不变量）"
    )


def test_fabric_width_description_says_it_is_ignored_when_candidates_given():
    props = CurtainCalcTool.parameters["properties"]
    assert "忽略" in props["fabric_width"]["description"], (
        "两个入参并存时必须说清优先级，否则模型会同时传、结果不可预期"
    )


def test_tool_description_tells_model_to_pass_candidates():
    desc = CurtainCalcTool.description
    assert "fabric_widths" in desc, "工具描述必须告诉模型该传候选集（否则模型只会传单值门幅）"
    assert "自动" in desc, "描述里要说清「系统自动选门幅 + 自动决定加工类型」"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3/4/5 —— execute 真的按候选集自动选
# ══════════════════════════════════════════════════════════════════════════════

async def test_candidates_pick_widest_feasible_and_fixed_height(monkeypatch):
    # 2.75 + 0.3 = 3.05：2.8 不可行、3.2 可行 ⇒ 自动解 = 3.2 + 定高买宽，用料 = T = 6.6
    result = await _run(monkeypatch, window_height=2.75, fabric_widths=[2.8, 3.2])
    assert result.success is True, result.message
    assert result.data["door_width"] == 3.2
    assert result.data["cutting_mode"] == cc.CUTTING_MODE_FIXED_HEIGHT
    assert result.data["splice"] is False
    assert result.data["fabric_meters"] == pytest.approx(6.6)
    assert result.data["formula_used"] == "fixed_height"


async def test_candidates_fall_back_to_rotated_when_none_feasible(monkeypatch):
    # 3.0 + 0.3 = 3.3 > 3.2 ⇒ 无可行门幅 ⇒ 倒幅；ceil(6.6 / 2.8) = 3 幅 × 3.3 = 9.9
    result = await _run(monkeypatch, window_height=3.0, fabric_widths=[2.8, 3.2])
    assert result.success is True, result.message
    assert result.data["cutting_mode"] == cc.CUTTING_MODE_FIXED_WIDTH
    assert result.data["panels"] == 3
    assert result.data["fabric_meters"] == pytest.approx(9.9)
    assert result.data["formula_used"] == "fixed_width"


async def test_narrow_only_candidate_also_rotates(monkeypatch):
    # 候选里**只有 2.8**（3.05 > 2.8）⇒ 也必须倒幅 —— 证明候选集真的参与判定，
    # 而不是「没给候选就走默认 2.8」的假接线（红证：把 fabric_widths 原样丢掉 ⇒ 本断言红）
    result = await _run(monkeypatch, window_height=2.75, fabric_widths=[2.8])
    assert result.data["cutting_mode"] == cc.CUTTING_MODE_FIXED_WIDTH
    assert result.data["door_width"] == 2.8
    assert result.data["panels"] == 3
    assert result.data["fabric_meters"] == pytest.approx(9.15)


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6/7 —— 回归不变量 + 接线红证
# ══════════════════════════════════════════════════════════════════════════════

async def test_without_candidates_single_width_behaviour_is_unchanged(monkeypatch):
    # 不传候选集 ⇒ 既有单一门幅口径：3.05 > 2.8 ⇒ 倒幅（与 #5013 之前逐值一致）
    result = await _run(monkeypatch, window_height=2.75, fabric_width=2.8)
    assert result.data["door_width"] == 2.8
    assert result.data["cutting_mode"] == cc.CUTTING_MODE_FIXED_WIDTH
    assert result.data["splice"] is False
    assert result.data["fabric_meters"] == pytest.approx(9.15)


async def test_build_quote_receives_candidates_verbatim(monkeypatch):
    """接线红证：删掉 `execute` 里 `fabric_widths=fabric_widths` 那一行 ⇒ 本断言红。"""
    seen: Dict[str, Any] = {}
    real_build_quote = cc.build_quote

    def recorder(**kwargs):
        seen.update(kwargs)
        return real_build_quote(**kwargs)

    monkeypatch.setattr(cc, "get_admin_api_client", lambda: _FakeAdminApi(NO_ROW_RESPONSE))
    monkeypatch.setattr(cc, "build_quote", recorder)
    result = await CurtainCalcTool().execute(
        _ctx(), **{**ANCHOR, "window_height": 2.75, "fabric_widths": [2.8, 3.2]}
    )

    assert result.success is True, result.message
    assert seen["fabric_widths"] == [2.8, 3.2], "候选集必须**原样**传给引擎（不得改名/补默认）"
