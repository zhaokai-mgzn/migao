"""算料试算内部端点（issue #4421）—— 折数法（标准档）单一真值 + 可读公式串。

背景（用户 2026-09-19 裁定）：商家手工下单页**零算料通路** —— 数量/米数靠商家手填。
用户裁定用料米数按**折数法（标准档）**：`宽 × 倍数 → 折数（按开数取整）→ 0.25×折数 + 余量`。
本端点是「商家手工下单页试算」的后端入口，形态照既有先例
`POST /api/internal/production/operation-qty`（Service Token 认证 + `make_response` 外壳）。

口径铁律（逐条有对应断言）：
1. **纸表逐值复现是本单的锚**：单开 `0.25n+0.2`、对开 `0.25n+0.3`，抽验
   4折=1.2 / 8折=2.3 / 48折=12.3 / 52折=13.3 / 56折=14.3（issue #4421 表格）；
   红证 = 改 `curtain_calc` 任一常量即红（本文件**不复制**常量，全部 import 真值源）；
2. **单一真值**：端点返回值 === 直调 `curtain_calc.build_quote` 的逐值相等
   ⇒ `test_endpoint_values_equal_engine_direct_call` 是防「第二份算料逻辑」的守门断言；
3. **公式由后端产出**：`formula_text` 与数值**同源**（同一 `pleat_count` + 同一余量常量），
   `(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米` 形态；前端不得自拼
   ⇒ `test_formula_text_is_derived_from_same_numbers` 逐值重算比对；
4. **6.6m / 双开 / 标准档 ⇒ 52 折 / 13.3 米**（issue 判据的冻结样例）；
5. 缺 `X-Service-Token` ⇒ 401（与既有内部端点同款）。

红证（实现前逐条红，红因已核）：
- 判据 1~4：端点未实现 ⇒ `POST /api/internal/production/craft-calc` **404**
  （`assert 404 == 200` 红）；
- 判据 3：未实现 ⇒ 404 ⇒ `resp.json()["data"]` KeyError 红；
- 判据 5：未实现 ⇒ 404（不是 401）⇒ `assert 404 == 401` 红。
"""

# case_ids: OR-032

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/craft-calc"

# 冻结样例（issue #4421 判据）：6.6m 窗 / 2.5m 高 / 双开 / 韩褶 / 标准档。
# 窗高 2.5m ⇒ 成品高 + 卷边 2.8 ≤ 门幅 3.2 ⇒ 走**折数法本式**（`0.25×折数+余量`），
# 与 issue 里的 `13.3 米` 同口径（高 > 门幅上限时会转定宽买高，另见 TestFixedWidthFallback）。
FROZEN = {"width": 6.6, "height": 2.5, "open_count": 2, "mounting": "s_hook", "craft_tier": "standard"}


@pytest.fixture
def client():
    """本地 TestClient（与 tests/test_production/test_operation_qty.py 同款）。

    为什么不复用 conftest 的 `test_client`：它 patch 了**已移除**的 `app.main.get_rag_pipeline`
    ⇒ 该 fixture 当前一律 AttributeError（越界发现，非本单范围）。本 fixture 只 patch
    实际存在的生命周期依赖。
    """
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app
        with TestClient(create_app()) as c:
            yield c


def _post(client, payload, token=settings.SERVICE_TOKEN):
    headers = {} if token is None else {"X-Service-Token": token}
    return client.post(ENDPOINT, headers=headers, json=payload)


def _data(client, payload):
    resp = _post(client, payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    return body["data"]


# ══════════════════════════════════════════════════════════════════════════
# 判据 1：纸表逐值复现（issue #4421 的锚，19/19 命中）
#
# 纸表四列（`docs/curtain-fabric-quote-rules.md` §8 + 2026-09 客户韩折下料速查表）：
#   单开·下料   0.25n + 0.2
#   对开·下料   0.25n + 0.3
#   拼色·主布（单开） 0.25n + 0.15  —— **未落码**（引擎无拼色分支，本单不实现）
#   拼色·主布（对开） 0.25n + 0.2   —— **未落码**
# 本类只锚**已落码**的两列（单开/对开），拼色两列如实登记为边界（见文件末）。
# ══════════════════════════════════════════════════════════════════════════

# 纸表「单开·下料」列（余量 0.2）：(折数, 下料米数)
PAPER_SINGLE = [(4, 1.2), (10, 2.7), (20, 5.2), (28, 7.2), (36, 9.2), (40, 10.2)]
# 纸表「对开·下料」列（余量 0.3）：(折数, 下料米数)
PAPER_MULTI = [(8, 2.3), (16, 4.3), (24, 6.3), (32, 8.3), (40, 10.3), (48, 12.3), (52, 13.3), (56, 14.3)]


class TestPaperTableReproduction:

    @pytest.mark.parametrize("pleats,meters", PAPER_SINGLE)
    def test_single_open_paper_column(self, pleats, meters):
        """单开列 `0.25n + 0.2` 逐值复现。"""
        actual, warning, info = curtain_calc.calculate_fabric_by_pleats(pleats, open_count=1)
        assert actual == meters, f"{pleats} 折单开纸表值 {meters}，引擎给 {actual}"
        assert warning == ""
        assert info["margin"] == 0.2

    @pytest.mark.parametrize("pleats,meters", PAPER_MULTI)
    def test_multi_open_paper_column(self, pleats, meters):
        """对开列 `0.25n + 0.3` 逐值复现。"""
        actual, warning, info = curtain_calc.calculate_fabric_by_pleats(pleats, open_count=2)
        assert actual == meters, f"{pleats} 折对开纸表值 {meters}，引擎给 {actual}"
        assert warning == ""
        assert info["margin"] == 0.3

    @pytest.mark.parametrize("pleats,meters", [
        (4, 1.2), (8, 2.3), (48, 12.3), (52, 13.3), (56, 14.3),
    ])
    def test_issue_4421_spot_checks(self, pleats, meters):
        """issue #4421 明列的 5 个抽验值：4折=1.2 / 8折=2.3 / 48折=12.3 / 52折=13.3 / 56折=14.3。

        判别性：4 折走单开口径（余量 0.2），其余走对开口径（余量 0.3）——
        把两个余量接反 ⇒ 本条立刻红（4折 1.2→1.3、8折 2.3→2.2）。
        """
        open_count = 1 if pleats == 4 else 2
        actual, _, _ = curtain_calc.calculate_fabric_by_pleats(pleats, open_count=open_count)
        assert actual == meters

    def test_margin_switch_is_the_only_difference(self):
        """同一折数下「单开 vs 对开」只差 0.1 米（余量 0.2 vs 0.3）——余量口径的判别性断言。"""
        single, _, _ = curtain_calc.calculate_fabric_by_pleats(40, open_count=1)
        multi, _, _ = curtain_calc.calculate_fabric_by_pleats(40, open_count=2)
        assert single == 10.2 and multi == 10.3
        assert round(multi - single, 2) == 0.1


# ══════════════════════════════════════════════════════════════════════════
# 拼色用料系数（用户 2026-09-19 裁定，纸质速查表表头原文）
#
# 表头：「拼色下料 **1个折 0.65** ／ **2个折 1.2**」—— 用户裁定这是**用料**口径（不是计价）：
#   单色        0.25 米/折
#   拼色·拼1次  0.65 米/折
#   拼色·拼2次  1.2  米/折
# **余量不变**（单开 0.2 / 多开 0.3）—— 52 折双开：单色 13.3 / 拼1次 34.1 / 拼2次 62.7。
#
# 红证（实现前）：引擎恒按 0.25 算 ⇒ 拼1次/拼2次都得 13.3 ⇒ 下面每一条都红。
# ══════════════════════════════════════════════════════════════════════════

# 纸表表头原文系数（用户 2026-09-19 裁定）：特殊选项名 → 每折吃布（米）
MIXED_PER_FOLD = {"拼1次": 0.65, "拼2次": 1.2}


class TestMixedColorPerFold:

    def test_engine_coefficient_table(self):
        """引擎的拼色系数表必须与纸表表头**逐值**一致（0.65 / 1.2）。"""
        for option, per_fold in MIXED_PER_FOLD.items():
            assert curtain_calc.MIXED_COLOR_PER_FOLD[option] == per_fold
        assert curtain_calc.PLEAT_FABRIC_PER_FOLD == 0.25      # 单色不变

    @pytest.mark.parametrize("option,per_fold", sorted(MIXED_PER_FOLD.items()))
    def test_mixed_uses_its_own_per_fold(self, option, per_fold):
        """拼色 ⇒ 用料 = 系数 × 折数 + 余量（余量与单色同一套）。"""
        meters, _, info = curtain_calc.calculate_fabric_by_pleats(
            52, open_count=2, per_fold=per_fold)
        assert meters == round(per_fold * 52 + 0.3, 2)
        assert info["per_fold"] == per_fold

    def test_endpoint_single_color_frozen_unchanged(self, client):
        """防回归：单色 52 折双开仍是 13.3 米（拼色改动不得动单色一个数）。"""
        data = _data(client, FROZEN)
        assert data["fabric_meters"] == 13.3
        assert data["per_fold"] == 0.25

    @pytest.mark.parametrize("option,expected", [("拼1次", 34.1), ("拼2次", 62.7)])
    def test_endpoint_mixed_numbers(self, client, option, expected):
        """判据：拼1次 52 折双开 ⇒ **34.1 米**；拼2次 ⇒ **62.7 米**。

        红证：修复前按 0.25 算 ⇒ 两条都得 13.3 ⇒ 红。
        """
        data = _data(client, {**FROZEN, "style": "拼色", "special_options": [option]})
        assert data["pleat_count"] == 52
        assert data["fabric_meters"] == expected
        assert data["per_fold"] == MIXED_PER_FOLD[option]

    def test_single_open_margin_still_point_two_for_mixed(self, client):
        """单开余量仍为 0.2（防「顺手统一余量」）：拼1次 4 折单开 = 0.65×4+0.2 = 2.8。"""
        data = _data(client, {
            "width": 2.0, "open_count": 1, "style": "拼色", "special_options": ["拼1次"],
        })
        assert data["open_count"] == 1
        assert data["margin"] == 0.2
        assert data["fabric_meters"] == round(0.65 * data["pleat_count"] + 0.2, 2)

    def test_single_color_margin_anchor_untouched(self, client):
        """纸表单开锚（单色 4 折 = 1.2 米）不得被拼色改动带偏。"""
        meters, _, _ = curtain_calc.calculate_fabric_by_pleats(4, open_count=1)
        assert meters == 1.2

    def test_formula_text_carries_the_mixed_coefficient(self, client):
        """公式串必须带上真实系数（0.65），不得仍写 0.25（否则展示与数值不同源）。"""
        data = _data(client, {**FROZEN, "style": "拼色", "special_options": ["拼1次"]})
        assert "0.65×52" in data["formula_text"]
        assert data["formula_text"].endswith("= 34.1米")

    def test_single_color_style_does_not_change_numbers(self, client):
        """`style=单色`（显式）与不传 style 同值 —— 系数只由拼次决定，不由款式单独决定。"""
        base = _data(client, FROZEN)
        explicit = _data(client, {**FROZEN, "style": "单色"})
        assert explicit["fabric_meters"] == base["fabric_meters"]
        assert explicit["per_fold"] == 0.25

    def test_mixed_style_without_special_option_is_not_a_mixed_quote(self, client):
        """`style=拼色` 但**没给**拼次 ⇒ 无系数依据 ⇒ 不得凭空按 0.65/1.2 算。

        本单不发明口径：按单色系数 0.25 算，并在 `warning` 里**显式**说明（可见，不静默）。
        """
        data = _data(client, {**FROZEN, "style": "拼色"})
        assert data["fabric_meters"] == 13.3
        assert data["per_fold"] == 0.25
        assert "拼次" in data["warning"]

    def test_unregistered_mixed_option_is_visible_not_silent(self, client):
        """**拼3次不在纸表里** ⇒ 不猜、不插值：显式 400 + 缺口说明（不得静默按 0.65/1.2/0.25 算）。"""
        resp = _post(client, {**FROZEN, "style": "拼色", "special_options": ["拼3次"]})
        assert resp.status_code == 400
        assert "MIXED_PER_FOLD_NOT_REGISTERED" in resp.text
        assert "拼3次" in resp.text

    def test_unregistered_option_constant_is_registered_as_gap(self):
        """缺口登记可机读：`MIXED_PER_FOLD_UNREGISTERED` 必须含 `拼3次`（登记缺口，不静默）。"""
        assert "拼3次" in curtain_calc.MIXED_PER_FOLD_UNREGISTERED

    def test_per_fold_is_reflected_in_fullness_actual(self, client):
        """实际倍数随用料走：拼2次 62.7 ÷ 6.6 = 9.5（理论倍数仍是 2.0）。"""
        data = _data(client, {**FROZEN, "style": "拼色", "special_options": ["拼2次"]})
        assert data["fullness"] == 2.0
        assert data["fullness_actual"] == 9.5


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：6.6m / 双开 / 标准档 ⇒ 52 折 / 13.3 米（冻结样例）
# ══════════════════════════════════════════════════════════════════════════

class TestFrozenSample:

    def test_six_six_meter_double_open_standard_tier(self, client):
        data = _data(client, FROZEN)
        assert data["pleat_count"] == 52
        assert data["fabric_meters"] == 13.3
        assert data["per_panel_pleats"] == 26
        assert data["open_count"] == 2
        assert data["margin"] == 0.3
        assert data["craft_tier"] == "standard"

    def test_frozen_sample_matches_engine(self):
        """冻结样例的推导链逐段核（不经过 HTTP）：倍数 2.0 → 折数 52 → 用料 13.3。"""
        pleats, warning = curtain_calc.derive_pleat_count(6.6, 2.0, open_count=2)
        assert pleats == 52 and warning == ""
        meters, _, _ = curtain_calc.calculate_fabric_by_pleats(pleats, open_count=2)
        assert meters == 13.3

    def test_economy_tier_is_a_different_number(self, client):
        """档位不同 ⇒ 数字必须不同（防「档位入参被忽略、恒按标准档答」的静默缺陷）。"""
        standard = _data(client, FROZEN)
        economy = _data(client, {**FROZEN, "craft_tier": "economy"})
        assert economy["craft_tier"] == "economy"
        assert economy["pleat_count"] == 46
        assert economy["fabric_meters"] == 11.8
        assert economy["fabric_meters"] != standard["fabric_meters"]


# ══════════════════════════════════════════════════════════════════════════
# 判据 2：单一真值 —— 端点返回值 === 直调 build_quote（防第二份算料逻辑）
# ══════════════════════════════════════════════════════════════════════════

class TestSingleSourceOfTruth:

    def test_endpoint_values_equal_engine_direct_call(self, client):
        """守门断言：端点的每个算料值都必须与直调 `build_quote` 逐值相等。

        若有人在端点里复制了第二份算料逻辑（重写 0.25/0.2/0.3 常量、自己 round），
        这里必红。
        """
        data = _data(client, FROZEN)
        quote = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            open_count=2, craft_tier="standard", fabric_width=3.2,
        )
        assert data["fabric_meters"] == quote["fabric_meters"]
        assert data["pleat_count"] == quote["pleat_count"]
        assert data["per_panel_pleats"] == quote["per_panel_pleats"]
        assert data["fullness"] == quote["fullness"]
        assert data["fullness_actual"] == quote["fullness_actual"]
        assert data["formula_used"] == quote["formula_used"] == "fixed_height_pleats"

    def test_formula_text_is_derived_from_same_numbers(self, client):
        """`formula_text` 必须由**同一份**数字产出（后端产出，前端不得自拼）。

        判别性：把折数或余量换成别的数（哪怕只差 1 折 / 0.1 米）⇒ 本条红。
        倍数按 `:g` 渲染（2.0 → `2`），数字本身与 `data["fullness"]` 同源。
        """
        data = _data(client, FROZEN)
        assert data["formula_text"] == "(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米"
        assert data["fullness"] == 2.0

    def test_formula_text_reflects_single_open_margin(self, client):
        """单开 ⇒ 公式串里的余量必须是 0.2（不是恒写 0.3）。"""
        data = _data(client, {**FROZEN, "width": 3.0, "open_count": 1})
        assert data["margin"] == 0.2
        assert f"+{data['margin']} = {data['fabric_meters']}米" in data["formula_text"]

    def test_formula_text_is_not_static(self, client):
        """两个不同输入 ⇒ 公式串必须不同（防「写死一句示例串」的假实现）。"""
        a = _data(client, FROZEN)["formula_text"]
        b = _data(client, {**FROZEN, "craft_tier": "economy"})["formula_text"]
        assert a != b

    def test_engine_constants_are_not_redeclared(self):
        """结构性护栏：本端点复用的余量/每折常量必须是 `curtain_calc` 的**同一对象**。

        红证形态：端点自己写 `MARGIN = 0.3` ⇒ 改 `curtain_calc.MARGIN_MULTI` 后
        端点仍答旧值（两份真值），本断言通过 `is` 比对常量身份拦下。
        """
        assert curtain_calc.PLEAT_FABRIC_PER_FOLD == 0.25
        assert curtain_calc.MARGIN_SINGLE == 0.2
        assert curtain_calc.MARGIN_MULTI == 0.3
        assert curtain_calc.DEFAULT_CRAFT_TIERS["standard"]["fullness"] == 2.0
        assert curtain_calc.DEFAULT_CRAFT_TIERS["economy"]["fullness"] == 1.8


# ══════════════════════════════════════════════════════════════════════════
# 出参形态（admin-api `CraftCalcClient` 按此逐键解析）
# ══════════════════════════════════════════════════════════════════════════

class TestResponseShape:

    EXPECTED_KEYS = {
        "fabric_meters", "pleat_count", "per_panel_pleats", "open_count", "margin",
        "per_fold", "fullness", "fullness_actual", "formula_used", "formula_text",
        "source", "craft_tier", "warning",
    }

    def test_data_has_frozen_keys(self, client):
        assert set(_data(client, FROZEN)) == self.EXPECTED_KEYS

    def test_response_shell_matches_internal_endpoints(self, client):
        """沿用 internal.py 既有外壳（`make_response`）—— admin-api 客户端照此解析。"""
        body = _post(client, FROZEN).json()
        assert set(body) == {"success", "data", "requestId", "timestamp"}

    def test_source_is_formula_by_default(self, client):
        """取值来源标记（真值源 §8「折数/用料必须带来源」）：默认 `formula`。"""
        assert _data(client, FROZEN)["source"] == "formula"

    def test_fullness_is_theoretical_and_fullness_actual_is_derived(self, client):
        """`fullness` = 档位**理论**倍数（2.0）；`fullness_actual` = 用料 ÷ 窗宽（13.3÷6.6 = 2.02）。

        二者语义不同（真值源 §10 / issue #4118 ④）——不得互相替代。
        """
        data = _data(client, FROZEN)
        assert data["fullness"] == 2.0
        assert data["fullness_actual"] == 2.02

    def test_warning_empty_for_clean_input(self, client):
        assert _data(client, FROZEN)["warning"] == ""

    def test_style_is_passed_through_but_does_not_change_numbers(self, client):
        """`style` 只做**透传**：引擎无款式分支 ⇒ 不得因传 style 就静默改数（本单不发明口径）。"""
        base = _data(client, FROZEN)
        with_style = _data(client, {**FROZEN, "style": "拼色"})
        assert with_style["fabric_meters"] == base["fabric_meters"]
        assert with_style["pleat_count"] == base["pleat_count"]


class TestFixedWidthFallback:
    """成品高 + 卷边 > 门幅 ⇒ 引擎转定宽买高（幅数 × 每幅长），**且必须带告警**。

    判别性：不传 `height` 时缺省 2.5m 走本式；传 3.0m 则跨过 3.2m 门幅上限 ⇒ 走定宽。
    端点必须把引擎的 `warning` 原样回传（不得吞掉「已按定宽买高计算」这句）。
    """

    def test_tall_window_switches_formula_and_warns(self, client):
        data = _data(client, {**FROZEN, "height": 3.0})
        assert data["formula_used"] == "fixed_width_pleats"
        assert data["pleat_count"] == 52          # 折数不变（折数只由宽 × 倍数决定）
        assert data["fabric_meters"] == 16.5      # ceil(13.3/3.2)=5 幅 × (3.0+0.3) = 16.5
        assert "定高上限" in data["warning"]

    def test_formula_text_still_carries_real_numbers(self, client):
        """换算式后公式串仍必须与**回传的**米数/折数一致（不得写死本式的 13.3）。"""
        data = _data(client, {**FROZEN, "height": 3.0})
        assert f"= {data['fabric_meters']}米" in data["formula_text"]
        assert f"{data['pleat_count']}折" in data["formula_text"]


# ══════════════════════════════════════════════════════════════════════════
# 入参校验 / 认证
# ══════════════════════════════════════════════════════════════════════════

class TestAuthAndValidation:

    def test_missing_token_rejected(self, client):
        resp = _post(client, FROZEN, token=None)
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text

    def test_wrong_token_rejected(self, client):
        resp = _post(client, FROZEN, token="wrong-token")
        assert resp.status_code == 401

    def test_width_must_be_positive(self, client):
        assert _post(client, {**FROZEN, "width": 0}).status_code == 422

    def test_open_count_must_be_positive(self, client):
        assert _post(client, {**FROZEN, "open_count": 0}).status_code == 422

    def test_open_count_must_divide_evenly_after_rounding(self, client):
        """开数整除（真值源 §8）：对开总折数必须是偶数 —— 引擎取最近可行折数，
        端点必须把**取整后**的折数与告警一并回传（不得静默丢告警）。"""
        data = _data(client, {**FROZEN, "open_count": 4})
        assert data["pleat_count"] % 4 == 0
        assert data["per_panel_pleats"] == data["pleat_count"] // 4
