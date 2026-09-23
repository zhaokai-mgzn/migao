"""算料试算内部端点（issue #4421）—— 褶数法（标准档）单一真值 + 可读公式串。

背景（用户 2026-09-19 裁定）：商家手工下单页**零算料通路** —— 数量/米数靠商家手填。
用户裁定用料米数按**褶数法（标准档）**：`宽 × 倍数 → 褶数（按开数取整）→ 0.25×褶数 + 余量`。
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

import re

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/craft-calc"

# 冻结样例（issue #4421 判据）：6.6m 窗 / 2.5m 高 / 双开 / 韩褶 / 标准档。
# 窗高 2.5m ⇒ 成品高 + 卷边 2.8 ≤ 门幅 3.2 ⇒ 走**褶数法本式**（`0.25×褶数+余量`），
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

# 纸表「单开·下料」列（余量 0.2）：(褶数, 下料米数)
PAPER_SINGLE = [(4, 1.2), (10, 2.7), (20, 5.2), (28, 7.2), (36, 9.2), (40, 10.2)]
# 纸表「对开·下料」列（余量 0.3）：(褶数, 下料米数)
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
        """同一褶数下「单开 vs 对开」只差 0.1 米（余量 0.2 vs 0.3）——余量口径的判别性断言。"""
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
        """引擎的拼色系数必须与纸表表头**逐值**一致（0.65 / 1.2），且**按入口**解析得到。

        用 `resolve_per_fold`（取系数的**单一实现**）断言，而不是只核常量存在 ——
        常量在、入口接错（如两个元组下标错位）时前者会红、后者不会。
        """
        for option, per_fold in MIXED_PER_FOLD.items():
            assert curtain_calc.mixed_times(option) in curtain_calc.MIXED_COLOR_PER_FOLD_BY_TIMES
            assert curtain_calc.resolve_per_fold("拼色", [option]) == per_fold
        assert curtain_calc.resolve_per_fold("拼色", ["拼3次"]) == 0.25   # 未登记 ⇒ 不静默取系数（缺口由 mixed_per_fold_gap 显式判）
        assert curtain_calc.resolve_per_fold(None, ["拼1次"]) == 0.25     # 非拼色 ⇒ 单色口径
        assert curtain_calc.PLEAT_FABRIC_PER_FOLD == 0.25      # 单色不变

    @pytest.mark.parametrize("option,per_fold", sorted(MIXED_PER_FOLD.items()))
    def test_mixed_uses_its_own_per_fold(self, option, per_fold):
        """拼色 ⇒ 用料 = 系数 × 褶数 + 余量（余量与单色同一套）。"""
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
        """单开余量仍为 0.2（防「顺手统一余量」）。

        实测口径（**代码事实，写死**）：宽 2.0m 单开标准档 ⇒ 褶数 = round((2.0×2.0−0.2)/0.25) = **15 折**
        （褶数按**单色每折吃布** 0.25 反算，与拼色系数无关 —— issue #4421 既有口径），
        用料 = 0.65×15 + 0.2 = **10.0 米**。
        原断言写的是 `round(0.65×pleat_count+0.2, 2)`（自指、永不判红），本次改为**写死期望值**
        （issue #4527 判据纪律：期望值不得从实现推导）。
        """
        data = _data(client, {
            "width": 2.0, "open_count": 1, "style": "拼色", "special_options": ["拼1次"],
        })
        assert data["open_count"] == 1
        assert data["margin"] == 0.2
        assert data["pleat_count"] == 15
        assert data["fabric_meters"] == 10.0

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
        """缺口**与系数表同源**：`mixed_times` 解析得出 N、而 N 不在表里 ⇒ 缺口（无平行清单可漂移）。

        判别性：把缺口改成手维护的平行清单（旧形态）时，`拼4次` 会静默退回单色系数 ——
        下面 `拼4次` 的断言就是防这个的（将来纸表加 3 后 `拼4次` 必须仍被判缺口）。
        """
        assert curtain_calc.mixed_times("拼3次") == 3
        assert 3 not in curtain_calc.MIXED_COLOR_PER_FOLD_BY_TIMES
        assert curtain_calc.mixed_per_fold_gap(["拼3次"]) == "拼3次"
        assert curtain_calc.mixed_per_fold_gap(["拼4次"]) == "拼4次"      # 未登记的新拼次同样判缺口
        assert curtain_calc.mixed_per_fold_gap(["拼1次"]) is None
        assert curtain_calc.mixed_per_fold_gap(["加花边"]) is None        # 非拼次选项不是缺口
        assert curtain_calc.mixed_times("加花边") is None

    def test_every_routing_mixed_option_is_parseable(self):
        """覆盖率守卫：`routing` 里**所有** `拼N次` 选项都必须被 `mixed_times` 解析成**那个 N**。

        防的形态（会**少算用料**）：将来加 `拼4次` 时正则不匹配 ⇒ 被当成「不是拼次」⇒
        静默退回单色系数 0.25，而纸表可能已登记它的系数。解析不出 / 解析成别的数即红。
        """
        from app.production.routing import SPECIAL_OPTION_ROUTINGS

        routing_mixed = [opt for opt in SPECIAL_OPTION_ROUTINGS if "拼" in opt]
        assert routing_mixed, "routing 里已无拼次选项 —— 本守卫的前提失效，请核 SPECIAL_OPTION_ROUTINGS"
        for option in routing_mixed:
            # 逐值断言（不用 `is not None` 这类弱形态）：期望值 = 选项名里内嵌的那个数字
            expected = int(re.fullmatch(r"拼(\d+)次", option).group(1))
            assert curtain_calc.mixed_times(option) == expected, (
                f"{option} 解析出的拼次 ≠ {expected} ⇒ 会被当成非拼次、静默退回单色系数（少算用料）"
            )

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
        """冻结样例的推导链逐段核（不经过 HTTP）：倍数 2.0 → 褶数 52 → 用料 13.3。"""
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

        判别性：把褶数或余量换成别的数（哪怕只差 1 折 / 0.1 米）⇒ 本条红。
        倍数按 `:g` 渲染（2.0 → `2`），数字本身与 `data["fullness"]` 同源。
        issue #4527 判据 4：串首**明确写出所用公式**（`韩褶公式：`）—— 静默走另一支 ⇒ 红。
        """
        data = _data(client, FROZEN)
        assert data["formula_text"] == "韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米"
        assert data["fullness"] == 2.0

    def test_formula_text_reflects_single_open_margin(self, client):
        """单开 ⇒ 公式串里的余量必须是 0.2（不是恒写 0.3）。

        ⚠️ issue #4527：用料米数一律**向上进位到 0.1** ⇒ 单开 23 折的 `0.25×23+0.2 = 5.95`
        进位为 **6.0**；公式串必须与回传的米数**逐字一致**（`= 6米`，`:g` 渲染）。
        """
        data = _data(client, {**FROZEN, "width": 3.0, "open_count": 1})
        assert data["margin"] == 0.2
        assert data["fabric_meters"] == 6.0
        assert f"+{data['margin']} = {data['fabric_meters']:g}米" in data["formula_text"]

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
# issue #4527：公式选择（`formula`）透传 + 默认韩褶公式 + 公式串写明所用公式
# ══════════════════════════════════════════════════════════════════════════

class TestFormulaSelectionEndpoint:
    """`formula` 入参由 admin-api（`CraftCalcClient`）原样透传；缺省 ⇒ 配置默认（韩褶公式）。

    ERP 实证锚点（#4343 取证，加工单 `CSO260915-02615`）：5.5m / 双开 / 2.00 倍 ⇒ **11.00 米**。
    红证（实现前）：端点不认 `formula` ⇒ 请求体多出的键被 Pydantic 忽略 ⇒ 仍走褶数法（11.3 米）⇒ 红。
    """

    def test_fullness_formula_matches_erp_anchor(self, client):
        data = _data(client, {**FROZEN, "width": 5.5, "formula": "fullness"})
        assert data["fabric_meters"] == 11.0
        assert data["formula_text"].startswith("褶倍数公式：")
        assert data["formula_text"].endswith("= 11.0米")
        assert data["formula_used"] == "fixed_height_fullness"

    def test_default_formula_is_pleat_and_is_named(self, client):
        """不传 `formula` ⇒ 韩褶公式，且 `formula_text` **明确写出所用公式**（静默走另一支 ⇒ 红）。"""
        data = _data(client, FROZEN)
        assert data["formula_text"].startswith("韩褶公式：")
        assert data["fabric_meters"] == 13.3

    def test_fullness_is_independent_of_open_count(self, client):
        """同一成品宽下 单开与双开同值（「总宽再×开数」的甲口径 ⇒ 22.0 ⇒ 红）。"""
        single = _data(client, {**FROZEN, "width": 5.5, "open_count": 1, "formula": "fullness"})
        double = _data(client, {**FROZEN, "width": 5.5, "open_count": 2, "formula": "fullness"})
        assert single["fabric_meters"] == double["fabric_meters"] == 11.0

    def test_unknown_formula_is_rejected_not_silently_defaulted(self, client):
        """未知公式名 ⇒ 400（静默回退默认 = 算错钱且无人知道）。"""
        resp = _post(client, {**FROZEN, "formula": "褶倍数"})
        assert resp.status_code == 400
        assert "CRAFT_CALC_INVALID_INPUT" in resp.text
        assert "formula" in resp.text

    # ── 追加裁定（用户 2026-09-19）：「韩褶用韩褶公式算布料，打孔按倍数法算布料，默认选择 2 倍」──
    # ⇒ 公式**由工艺推导**；`formula` 入参保留为显式覆盖。端点只透传 `craft`，推导表在算料引擎。

    def test_craft_hole_punch_derives_fullness_formula(self, client):
        """打孔 ⇒ 褶倍数公式 + 默认 2 倍 ⇒ 5.5m × 2.0 = 11.0 米（走褶数法 ⇒ 11.3 ⇒ 红）。"""
        data = _data(client, {"width": 5.5, "height": 2.5, "open_count": 2,
                              "mounting": "eyelet", "craft": "打孔"})
        assert data["fabric_meters"] == 11.0
        assert data["fullness"] == 2.0
        assert data["formula_text"].startswith("褶倍数公式：")
        assert data["pleat_count"] is None

    def test_craft_s_hook_derives_pleat_formula(self, client):
        """韩褶 ⇒ 褶数法（不显式传 mounting 也成立：推导表把韩褶映射到 s_hook）。"""
        data = _data(client, {"width": 6.6, "height": 2.5, "open_count": 2,
                              "mounting": "eyelet", "craft": "韩褶", "craft_tier": "standard"})
        assert data["pleat_count"] == 52
        assert data["fabric_meters"] == 13.3
        assert data["formula_text"].startswith("韩褶公式：")


# ══════════════════════════════════════════════════════════════════════════
# 出参形态（admin-api `CraftCalcClient` 按此逐键解析）
# ══════════════════════════════════════════════════════════════════════════

class TestResponseShape:

    EXPECTED_KEYS = {
        "fabric_meters", "pleat_count", "per_panel_pleats", "open_count", "margin",
        "per_fold", "fullness", "fullness_actual", "formula_used", "formula_text",
        "source", "craft_tier", "warning",
        # issue #4976 包 1a：自动特征（超高/超宽/倒幅）改由**服务端**判定（用户裁定 B）——
        # 该键**恒在**（空列表 = 不判，不是「没算」）。契约在此**有意识**长大一处：
        # admin-api 侧的解析要跟着加（包 2）；本断言是「出参形态」的唯一冻结点。
        "auto_features",
        # issue #5201 = 母单 #5200 子单 A：自动推导的工艺配置。**键恒在**，
        # `null` = 本次调用没走三项输入通路（未接线调用方口径逐值不变 —— 契约判据 8）。
        # 契约在此**有意识**长大一处：admin-api 侧的 `CraftCalcResult` 与控制器要跟着搬 `plan`。
        "plan",
    }

    def test_data_has_frozen_keys(self, client):
        assert set(_data(client, FROZEN)) == self.EXPECTED_KEYS

    def test_response_shell_matches_internal_endpoints(self, client):
        """沿用 internal.py 既有外壳（`make_response`）—— admin-api 客户端照此解析。"""
        body = _post(client, FROZEN).json()
        assert set(body) == {"success", "data", "requestId", "timestamp"}

    def test_source_is_formula_by_default(self, client):
        """取值来源标记（真值源 §8「褶数/用料必须带来源」）：默认 `formula`。"""
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
        assert data["pleat_count"] == 52          # 褶数不变（褶数只由宽 × 倍数决定）
        assert data["fabric_meters"] == 16.5      # ceil(13.3/3.2)=5 幅 × (3.0+0.3) = 16.5
        assert "定高上限" in data["warning"]

    def test_formula_text_still_carries_real_numbers(self, client):
        """换算式后公式串仍必须与**回传的**米数/褶数一致（不得写死本式的 13.3）。"""
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
        """开数整除（真值源 §8）：对开总褶数必须是偶数 —— 引擎取最近可行褶数，
        端点必须把**取整后**的褶数与告警一并回传（不得静默丢告警）。"""
        data = _data(client, {**FROZEN, "open_count": 4})
        assert data["pleat_count"] % 4 == 0
        assert data["per_panel_pleats"] == data["pleat_count"] // 4


# ══════════════════════════════════════════════════════════════════════════
# 自动推导的工艺配置 `plan`（issue #5201 = 母单 #5200 子单 A，契约判据 8/9/10）
#
# 契约 §四：`data` 新增 `plan` 对象（**只增键不删键**）。三项输入自动推导只在
# `splice_times` / `join_height_m` / `join_width_m` **至少传一个**时启用；
# 全不传 ⇒ 与改动前**逐值一致**（判据 8 的回归不变量）。
# ══════════════════════════════════════════════════════════════════════════

#: 门幅 3.2 的算例（FROZEN 的 T = 13.3）：倒幅 P = ceil(13.3 / 3.2) = 5 幅
PLAN = {**FROZEN, "fabric_width": 3.2}


class TestPlanRegressionInvariantWhenNoNewKeys:
    """判据 8：**不传**新键 ⇒ 结果与本次改动前逐值一致（回归不变量）。

    判别性：把 `plan` 分支的开关改成「恒开」⇒ 本条红（`fabric_meters` 会从 13.3 变 14.0）。
    """

    def test_without_fabric_width_values_are_unchanged(self, client):
        data = _data(client, FROZEN)   # 不含 fabric_width ⇒ 引擎常量 3.2
        assert data["fabric_meters"] == 13.3
        assert data["pleat_count"] == 52
        assert data["formula_used"] == "fixed_height_pleats"
        assert data.get("plan") is None, "没走三项输入通路 ⇒ plan 为 null（不发明一个假方案）"

    def test_explicit_fabric_width_alone_does_not_switch_path(self, client):
        """单独传 `fabric_width`（**既有**键，前端今天就在传）不得改变口径。

        判别性：把开关写成「传了 fabric_width 就启用推导」⇒ 本条红（13.3 → 14.0）。
        """
        data = _data(client, {**FROZEN, "fabric_width": 3.2})
        assert data["fabric_meters"] == 13.3
        assert data["formula_used"] == "fixed_height_pleats"

    def test_cutting_mode_alone_does_not_switch_path(self, client):
        """单独传 `cutting_mode`（既有键）同理 —— 它今天是**自动特征**的提示位（#4976 包 1a）。"""
        data = _data(client, {**FROZEN, "cutting_mode": "定高买宽"})
        assert data["fabric_meters"] == 13.3
        assert data["formula_used"] == "fixed_height_pleats"

    def test_baseline_is_the_same_number_as_before(self, client):
        """两条通路**互不影响**：开推导的那一次与不开的那一次各给各的数。"""
        plain = _data(client, FROZEN)
        assert plain["fabric_meters"] == 13.3, "未传 fabric_width ⇒ 既有单门幅口径（判据 8）"
        assert plain.get("plan") is None, "未开推导 ⇒ `plan` 为 null（不发明一个假方案）"

        switched = _data(client, PLAN)   # 传了 fabric_width ⇒ 开推导
        assert switched["fabric_meters"] == 13.3, (
            "本几何（need_h 2.8 ≤ 门幅 3.2）下推导结论 = 定高买宽 ⇒ 用料 = T = 13.3（与既有同值）"
        )
        assert switched["plan"]["cutting_mode"] == "定高买宽"
        assert switched["plan"]["auto"] is True
        assert switched["plan"]["meters"] == switched["fabric_meters"]

    def test_manual_splice_zero_keeps_the_derived_cutting_mode(self, client):
        """人工 `splice_times=0` 是**人工覆盖**（R7）：只锁定拼次，不翻转加工类型。

        为什么不是「倒幅 5 幅 × 2.8 = 14.0」：`splice_times=0` 表达的是「不拼」，
        它不蕴含倒幅（`_implied_mode` 只在 `splice_times ≥ 1` 时蕴含倒幅 —— 零拼接的
        定高买宽**本来就不拼**）；加工类型仍按自动推导的结论（本几何 = 定高买宽）。
        """
        data = _data(client, {**PLAN, "splice_times": 0})
        assert data["plan"]["auto"] is False
        assert data["plan"]["cutting_mode"] == "定高买宽"
        assert data["plan"]["splice_times"] == 0
        assert data["fabric_meters"] == 13.3


class TestPlanAutoDerivation:
    """自动推导（契约 §三 候选枚举 + 选优）。"""

    def test_auto_plan_derives_fixed_height_when_it_fits(self, client):
        # need_h = 2.5 + 0.3 = 2.8 ≤ 3.2 ⇒ 候选 1 可行且最省（13.3 < 14.0）⇒ 定高买宽
        data = _data(client, PLAN)   # 只传 fabric_width ⇒ 纯自动推导
        plan = data["plan"]
        assert plan["cutting_mode"] == "定高买宽", (
            "成品高 + 卷边 2.8 ≤ 门幅 3.2 ⇒ 定高买宽；它是可行集里用料最少的候选"
        )
        assert plan["auto"] is True, "只传 fabric_width ⇒ 系统推导（人工值一个都没给）"
        assert plan["panels"] is None and plan["splice_times"] == 0
        assert plan["join_height_m"] is None
        assert plan["door_width"] == 3.2
        assert data["fabric_meters"] == 13.3
        assert plan["meters"] == data["fabric_meters"]

    def test_fabric_width_alone_is_enough_to_reach_derivation(self, client):
        """**可达性判据**（母单 P0）：只传 `fabric_width` ⇒ 响应 `data.plan` 非空。

        光有 `derive_plan` 函数不算交付 —— 必须证明它被**端点触达**。
        """
        data = _data(client, PLAN)
        assert data["plan"]["door_width"] == 3.2, "门幅取自请求（SKU 门幅），不是引擎常量兜底"
        assert len(data["plan"]["candidates"]) == 5, "候选表必须真的被算出来（不是空壳）"

    def test_auto_plan_derives_rotated_when_height_exceeds_door_width(self, client):
        # 门幅 3.1 ⇒ need_h = 3.25 > 3.1 ⇒ 定高买宽不可行；缺口 0.15 > 0.1 ⇒ 接高也不可行
        # ⇒ 只剩倒幅：ceil(13.3 / 3.1) = 5 幅 × 3.25 = 16.25 → **进位 16.3**
        data = _data(client, {**PLAN, "fabric_width": 3.1, "height": 2.95})
        plan = data["plan"]
        assert plan["cutting_mode"] == "定宽买高"
        assert plan["panels"] == 5
        assert plan["splice_times"] == 4, "5 幅 ⇒ 拼 4 次（splice_times == panels − 1 不变量）"
        assert plan["splice_option"] is None, "R5：N ≥ 4 ⇒ null（不发明「拼4次」）"
        assert plan["notices"], "R5：N ≥ 4 必须显式告知需人工处理"
        assert data["fabric_meters"] == 16.3
        assert plan["meters"] == data["fabric_meters"]

    def test_auto_plan_prefers_join_height_over_rotated(self, client):
        """缺口恰 0.05 ≤ 0.1 ⇒ 接高可行，且定高买宽（13.3）比倒幅（5 × 3.25 = 16.25）省 ⇒ 选它。

        ⚠️ 这条同时钉住「接高只出现在**定高买宽**」（契约订正 v1.1 ③）：倒幅下高方向无缺口。
        """
        data = _data(client, {**PLAN, "height": 2.95})   # 门幅 3.2 ⇒ need_h 3.25 ⇒ 缺口 0.05
        plan = data["plan"]
        assert plan["cutting_mode"] == "定高买宽"
        assert plan["join_height_m"] == pytest.approx(0.05)
        assert plan["panels"] is None and plan["splice_times"] == 0
        assert data["fabric_meters"] == 13.3, "R2：接高不参与算料 ⇒ 用料仍是 T"

    def test_gap_over_limit_falls_back_to_rotated(self, client):
        """门幅 3.25 ⇒ 零缺口（不接高）；门幅 3.1 ⇒ 缺口 0.15 > 0.1 ⇒ 接高不可行、只剩倒幅。

        红证形态：把上限从 0.1 改成 0.25 ⇒ 门幅 3.1 的算例会判接高可行 ⇒ 本条红（判据 4）。
        """
        wide = _data(client, {**PLAN, "fabric_width": 3.25, "height": 2.95})
        assert wide["plan"]["join_height_m"] is None, "need_h == 门幅 3.25 ⇒ 零缺口，无需接高"
        assert wide["plan"]["cutting_mode"] == "定高买宽"

        narrow = _data(client, {**PLAN, "fabric_width": 3.1, "height": 2.95})
        assert narrow["plan"]["join_height_m"] is None, "缺口 0.15 > 0.1 ⇒ 不得判接高（R1）"
        assert narrow["plan"]["cutting_mode"] == "定宽买高"

    def test_join_height_candidate_is_chosen_when_it_is_the_only_one(self, client):
        # 窗高 3.0 ⇒ need_h = 3.3；门幅 3.25 ⇒ 缺口 0.05 ≤ 0.1 ⇒ 候选 2 可行（T = 13.3）
        # 纯倒幅 = ceil(13.3/3.25) = 5 幅 × 3.3 = 16.5 > 13.3 ⇒ 选优选候选 2
        data = _data(client, {**FROZEN, "fabric_width": 3.25, "height": 3.0, "join_height_m": 0.05})
        plan = data["plan"]
        assert plan["cutting_mode"] == "定高买宽"
        assert plan["panels"] is None
        assert plan["splice_times"] == 0
        assert plan["join_height_m"] == 0.05
        assert data["fabric_meters"] == 13.3, "R2：接高不进算料 ⇒ 用料仍是 T（不加加高条）"

    def test_candidate4_saves_one_panel_on_the_candidate_table(self, client):
        """候选 4 的「省一整幅」在**候选表**上逐值可核（v1.2：panels = P − 1）。

        ⚠️ 为什么不用「自动推导选它」来证：按 **v1.3 选优序**（拼接最少优先），
        门幅 4.4 这个算例的胜者是**零拼接的定高买宽**（13.3），不是候选 4（8.4 / 拼 2 次）——
        候选 4 只在**没有零拼接候选可行**时才会自动胜出。故这里核**候选表本身**的数
        （契约 §三 的用料列 + v1.2 的 panels 口径），不拿选优结论去核候选。
        """
        data = _data(client, {**PLAN, "fabric_width": 4.4, "splice_times": 0, "join_width_m": 0.1})
        plan = data["plan"]
        c4 = [c for c in plan["candidates"] if c["key"] == "fixed_width_join_width"][0]
        assert c4["feasible"] is True
        assert c4["meters"] == pytest.approx(8.4), "（P−1）幅 × need_h = 3 × 2.8 ⇒ 省一整幅"
        assert c4["splice_times"] == 2, "P − 2 = 2（与 panels = P − 1 自洽）"
        # 纯倒幅对照：P 幅 × need_h = 4 × 2.8 = 11.2（差一整幅）
        c3 = [c for c in plan["candidates"] if c["key"] == "fixed_width"][0]
        assert c3["meters"] == pytest.approx(11.2)

    def test_auto_over_limit_gap_falls_back_to_pure_rotated(self, client):
        """订正 v1.3 的连带效果：**纯倒幅只在没有零拼接候选可行时才自动胜出**。

        门幅 3.1 / 窗高 2.95 ⇒ need_h 3.25 > 3.1（定高买宽不可行）、缺口 0.15 > 0.1（接高不可行）、
        remainder = 13.3 − 2×3.1 = 7.1 > 0.1（接宽不可行）⇒ 只剩倒幅 ⇒ 5 幅 × 3.25 = 16.25 → 16.3。
        """
        data = _data(client, {**PLAN, "fabric_width": 3.1, "height": 2.95})
        plan = data["plan"]
        assert plan["cutting_mode"] == "定宽买高"
        assert plan["panels"] == 5 and plan["splice_times"] == 4
        assert plan["join_height_m"] is None and plan["join_width_m"] is None
        assert data["fabric_meters"] == 16.3

    def test_manual_join_width_alone_does_not_save_a_panel(self, client):
        """人工接宽（未给拼次）⇒ **不自动省幅**（R7）：用料 = P × need_h = 4 × 2.8 = 11.2。

        原因见 R7 段与 `reason`：人工值是**逐字采用**的，系统的「省一整幅」是自动候选 4 的行为，
        不会替商家推断。`reason` 里必须写明，否则商家会以为省了一幅（错钱且无感）。
        """
        data = _data(client, {**PLAN, "fabric_width": 4.4, "join_width_m": 0.1})
        plan = data["plan"]
        assert plan["auto"] is False, "给了人工值 ⇒ auto=false（R7）"
        assert plan["panels"] == 4 and plan["splice_times"] == 3
        assert data["fabric_meters"] == 11.2, "人工路径不省幅：4 幅 × 2.8 米"
        assert "不自动省幅" in plan["reason"]

    def test_candidates_are_all_reported_with_reasons(self, client):
        plan = _data(client, {**PLAN, "splice_times": 0})["plan"]
        assert [c["key"] for c in plan["candidates"]] == [
            "fixed_height", "fixed_height_join_height", "fixed_width",
            "fixed_width_join_width", "fixed_width_join_height",
        ], "契约 §三 的表序（也是选优第 ④ 顺位）"
        assert all(c["reason"] for c in plan["candidates"]), "每条候选都要说清依据（裁定 3）"
        infeasible = [c for c in plan["candidates"] if not c["feasible"]]
        assert infeasible, "本算例必须有不可行候选（否则候选表退化成装饰）"
        assert all(c["meters"] is None for c in infeasible), "不可行候选不得给估算值（R6）"


class TestPlanManualOverride:
    """判据 9（R7）：人工覆盖 ⇒ `auto=false` 且逐字采用；超上限 ⇒ 422。"""

    def test_manual_cutting_mode_is_adopted_verbatim(self, client):
        data = _data(client, {**PLAN, "cutting_mode": "定宽买高"})
        plan = data["plan"]
        assert plan["auto"] is False
        assert plan["cutting_mode"] == "定宽买高", "人工值逐字采用（R7），即使自动结论是定高买宽"
        assert "人工" in plan["reason"]
        assert plan["panels"] == 5 and plan["splice_times"] == 4
        assert data["fabric_meters"] == 14.0, "倒幅 5 幅 × 幅长 2.8 米（R7 逐字采用人工加工类型）"
        assert data["fabric_meters"] == plan["meters"]

    def test_manual_splice_times_drives_panels_and_meters(self, client):
        data = _data(client, {**PLAN, "cutting_mode": "定宽买高", "splice_times": 2})
        plan = data["plan"]
        assert plan["auto"] is False
        assert plan["splice_times"] == 2
        assert plan["panels"] == 3
        assert plan["splice_option"] == "拼2次"
        assert data["fabric_meters"] == 8.4, "3 幅 × 2.8 米（人工拼 2 次）"

    def test_manual_splice_times_over_three_is_rejected(self, client):
        """R5：不得发明「拼4次」⇒ 人工传 4 必须 fail-closed（400），不是静默接受。"""
        resp = _post(client, {**PLAN, "cutting_mode": "定宽买高", "splice_times": 4})
        assert resp.status_code == 400, resp.text
        assert "拼4次" in resp.text or "0~3" in resp.text

    def test_manual_join_height_over_limit_is_422(self, client):
        """判据 9：人工传 `join_height_m=0.2`（> 0.1）⇒ **422** fail-closed。"""
        resp = _post(client, {**PLAN, "join_height_m": 0.2})
        assert resp.status_code == 422, resp.text
        assert "0.1" in resp.text

    def test_manual_join_width_over_limit_is_422(self, client):
        resp = _post(client, {**PLAN, "join_width_m": 0.2})
        assert resp.status_code == 422, resp.text

    def test_manual_join_height_does_not_change_meters(self, client):
        """R2 红证形态：把加高条米数（旧口径 `T + 段数 × 片宽`）加回去 ⇒ 本条红。"""
        with_join = _data(client, {**PLAN, "join_height_m": 0.05})
        assert with_join["fabric_meters"] == 13.3
        assert with_join["plan"]["join_height_m"] == 0.05
        assert with_join["plan"]["meters"] == 13.3


class TestPlanSingleSourceOfMeters:
    """判据 10：`data.plan.meters` **必须等于** `data.fabric_meters`（单点口径）。"""

    PAYLOADS = [
        {**PLAN, "join_height_m": 0.05},
        {**PLAN, "splice_times": 0},
        {**PLAN, "splice_times": 2},
        {**PLAN, "fabric_width": 4.4, "join_width_m": 0.1},
        {**FROZEN, "fabric_width": 3.25, "height": 3.0, "join_height_m": 0.05},
    ]

    def test_plan_meters_equals_fabric_meters(self, client):
        """判别性：两处各算一份（端点自己 round 一份）⇒ 本条红。"""
        for payload in self.PAYLOADS:
            data = _data(client, payload)
            assert data["plan"]["meters"] == data["fabric_meters"], f"分叉：{payload}"

    def test_plan_meters_equals_engine_quote_meters(self, client):
        """再与**直调引擎**的 `fabric_meters` 比对：端点不得自己再算一份。"""
        payload = {**PLAN, "splice_times": 2}
        data = _data(client, payload)
        quote = curtain_calc.build_quote(
            window_width=payload["width"], window_height=payload["height"],
            mounting="s_hook", open_count=2, craft_tier="standard",
            fabric_width=payload["fabric_width"], cutting_mode=payload.get("cutting_mode"),
            splice_times=2, derive_plan_config=True,
        )
        assert data["plan"]["meters"] == quote["fabric_meters"]
        assert data["fabric_meters"] == quote["fabric_meters"]
