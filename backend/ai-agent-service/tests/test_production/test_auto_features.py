# case_ids: OR-040
"""算料**自动特征**（超高 / 超宽 / 倒幅）由**服务端**判定 —— issue #4976 包 1a。

用户 2026-09-21 裁定 B：「**判定移到服务端**」（前端只展示服务端结论）。本包只做**引擎侧**：
① 端点接收 `fabric_width`（**SKU 门幅**）与 `cutting_mode`（加工类型）；
② `build_quote` 输出 `auto_features`（键恒在）。

## 为什么必须接线门幅（不接线就做不成 B）

引擎端点此前把门幅写死成模块常量（`app/api/internal.py::_FABRIC_WIDTH`），请求模型里**没有**门幅字段
⇒ 服务端判「超宽/超高」用的不是这张单的 SKU 门幅（分叉 #4652 / #4746）。本包把该值**接进来**：
传 ⇒ 按该 SKU 门幅判；**不传 ⇒ 与今天逐值一致**（回归不变量，见判据 3）。

## 判据（每条都能单独判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | 按 `cutting_mode` 分流：`定高买宽` ⇒ 只判超高；`定宽买高` ⇒ 超宽 + 倒幅；缺省/表外 ⇒ **都不判**（不猜朝向） | 去掉分流（两边都判）⇒ 红 |
| 2 | 超宽判据 = `(成品宽 + side_margin) × 褶倍 > 门幅`（**与下单页同式**）；**缺褶倍 ⇒ 不判超宽** | 改成「只比 宽 + 余量」（漏褶倍）⇒ 红 |
| 3 | **门幅接线**：传 SKU 门幅 ⇒ 分幅与自动特征随它变；**不传 ⇒ 与今天逐值一致** | 端点忽略入参（仍用常量）⇒ 红 |
| 4 | `build_quote` 的 `auto_features` **键恒在**（空列表 = 不判，不是「没算」） | 改成「不判时省略键」⇒ 红 |
| 5 | 租户配置 `side_margin` 生效（改它 ⇒ 超宽判定随之变） | 用模块常量而不是 `cfg` ⇒ 红 |
| 6 | 判定依据（`reason`）带**真实数字**（商家要能核对「为什么判它超宽」） | reason 写成固定串 ⇒ 红 |
| 7 | **倒幅与褶倍无关**（它是加工类型的函数） | 让缺褶倍把倒幅也吃掉 ⇒ 红 |

## 与前端的关系（照实登记）

下单页 `frontend/admin-web/src/lib/craft-auto-features.ts` **本包不动** —— 它仍是取价路径的判定源。
两条判据（服务端 / 前端）在本包内**并存**，措辞逐字对齐（同一句「成品宽 … + 左右余量 … × 褶倍 …
= … 米 > 门幅 … 米」）；前端退场（只展示服务端结论）是**包 2**，届时本包的输出成为唯一真值。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/craft-calc"

#: 加工类型（与下单页 `craft-auto-features.ts` 的两个常量**逐字一致**）
FIXED_HEIGHT = "定高买宽"
FIXED_WIDTH = "定宽买高"


@pytest.fixture
def client():
    """本地 TestClient（与 `tests/test_production/test_craft_calc.py` 同款）。"""
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


def _names(features):
    return [f["name"] for f in features]


def _detect(**kwargs):
    """直调引擎（不带端点）—— 判据 1/2/5/7 的判定面。"""
    params = {"window_width": 1.6, "window_height": 2.0, "fabric_width": 2.8, "fullness": 2.0}
    params.update(kwargs)
    return curtain_calc.detect_auto_features(**params)


class TestCuttingModeSplit:
    """判据 1：按加工类型分流（用户 2026-09-20 裁定「定高买宽就不用算超宽，定宽买高就不用算超高」）。"""

    def test_fixed_height_judges_over_height_only(self):
        # 成品高 2.6 + 上下卷边 0.3 = 2.9 > 门幅 2.8 ⇒ 超高；宽方向**不判**（按宽买米无上限）
        assert _names(_detect(window_height=2.6, cutting_mode=FIXED_HEIGHT)) == ["超高"]

    def test_fixed_height_below_door_width_judges_nothing(self):
        # 成品高 2.0 + 0.3 = 2.3 ≤ 2.8 ⇒ 不判（注入：去掉比较 ⇒ 红）
        assert _detect(window_height=2.0, cutting_mode=FIXED_HEIGHT) == []

    def test_fixed_width_judges_over_width_and_reverse(self):
        # (1.6 + 0.3) × 2.0 = 3.8 > 2.8 ⇒ 超宽；定宽买高 ⇒ 倒幅（两者都在）
        assert _names(_detect(cutting_mode=FIXED_WIDTH)) == ["超宽", "倒幅"]

    def test_missing_or_unknown_cutting_mode_judges_nothing(self):
        # 不猜朝向：缺省 / 表外取值 ⇒ 一个都不判（注入：缺省时按定高买宽兜底 ⇒ 红）
        assert _detect(window_height=2.6, cutting_mode=None) == []
        assert _detect(window_height=2.6, cutting_mode="表外取值") == []


class TestOverWidthCriterion:
    """判据 2 / 7：超宽含**褶倍**（分幅才是多花钱的地方）；倒幅与褶倍无关。"""

    def test_over_width_multiplies_fullness(self):
        # 只比「宽 + 余量」= 1.9 ≤ 2.8 会**漏报**；含褶倍 3.8 > 2.8 才是引擎真实的分幅条件
        assert _names(_detect(cutting_mode=FIXED_WIDTH)) == ["超宽", "倒幅"]

    def test_missing_fullness_skips_over_width_but_keeps_reverse(self):
        # 缺褶倍 ⇒ 不判超宽（不拿一个假褶倍去判价）；但倒幅只取决于加工类型
        assert _names(_detect(fullness=None, cutting_mode=FIXED_WIDTH)) == ["倒幅"]

    def test_roomy_door_width_skips_over_width(self):
        # (1.6 + 0.3) × 2.0 = 3.8 ≤ 4.0 ⇒ 不分幅 ⇒ 不判超宽（仍判倒幅）
        assert _names(_detect(fabric_width=4.0, cutting_mode=FIXED_WIDTH)) == ["倒幅"]


class TestTenantConfigWins:
    """判据 5：`side_margin` 取自**该租户的配置**（不是模块常量）。"""

    def test_side_margin_from_config_changes_the_verdict(self):
        # 门幅 4.0：默认余量 0.3 ⇒ 3.8 ≤ 4.0 不判；把余量调到 0.9 ⇒ 2.5 × 2.0 = 5.0 > 4.0 ⇒ 判超宽
        assert _names(_detect(fabric_width=4.0, cutting_mode=FIXED_WIDTH)) == ["倒幅"]
        assert _names(
            _detect(fabric_width=4.0, cutting_mode=FIXED_WIDTH, config={"side_margin": 0.9})
        ) == ["超宽", "倒幅"]


class TestReasonCarriesNumbers:
    """判据 6：判定依据必须能被商家核对（带真实数字，不是固定串）。"""

    def test_reasons_quote_the_real_numbers(self):
        over_width = _detect(cutting_mode=FIXED_WIDTH)
        over_height = _detect(window_height=2.6, cutting_mode=FIXED_HEIGHT)
        reasons = {f["name"]: f["reason"] for f in [*over_width, *over_height]}
        assert "1.6" in reasons["超宽"] and "2.8" in reasons["超宽"] and "门幅" in reasons["超宽"]
        assert "2.6" in reasons["超高"] and "2.8" in reasons["超高"] and "门幅" in reasons["超高"]
        # 倒幅的依据就是加工类型本身（无数字）
        assert reasons["倒幅"] == f"加工类型 = {FIXED_WIDTH}"

    def test_every_feature_is_marked_as_inferred(self):
        # 超高/超宽判据是**行业推理、非 ERP 实证** ⇒ 一律标 `推算`（与下单页同口径）
        for feature in _detect(cutting_mode=FIXED_WIDTH):
            assert feature["source"] == "推算"

    def test_reason_wording_is_pinned(self):
        """措辞**钉死**（与下单页 `craft-auto-features.ts` 同一句）。

        理由：前端退场（包 2）时**商家看到的文案不得变** —— 措辞一改就是可见的行为变化，
        必须是有意识的改动（本断言红 ⇒ 先想清楚再改）。
        """
        assert [f["reason"] for f in _detect(cutting_mode=FIXED_WIDTH)] == [
            "成品宽 1.6 + 左右余量 0.3 = 1.9 米 × 褶倍 2.0 = 3.8 米 > 门幅 2.8 米",
            "加工类型 = 定宽买高",
        ]
        assert [f["reason"] for f in _detect(window_height=2.6, cutting_mode=FIXED_HEIGHT)] == [
            "成品高 2.6 + 上下卷边 0.3 = 2.9 米 > 门幅 2.8 米",
        ]


class TestBuildQuoteEmitsAutoFeatures:
    """判据 4：`build_quote` 的 `auto_features` **键恒在**。"""

    def test_key_always_present_even_when_nothing_judged(self):
        quote = curtain_calc.build_quote(window_width=1.6, window_height=2.0, fabric_width=2.8)
        # 注入：不判时省略该键 ⇒ KeyError 红（「没判」与「没算」必须可区分）
        assert quote["auto_features"] == []

    def test_quote_carries_the_features_when_cutting_mode_given(self):
        quote = curtain_calc.build_quote(
            window_width=1.6, window_height=2.0, fabric_width=2.8,
            mounting="s_hook", craft_tier="standard", cutting_mode=FIXED_WIDTH,
        )
        assert _names(quote["auto_features"]) == ["超宽", "倒幅"]

    def test_default_path_values_unchanged(self):
        """回归不变量：不传 `cutting_mode` ⇒ 既有输出**逐值不变**（只多一个空键）。"""
        quote = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            open_count=2, craft_tier="standard",
        )
        assert quote["fabric_meters"] == 13.3
        assert quote["pleat_count"] == 52
        assert quote["auto_features"] == []


class TestEndpointWiring:
    """判据 3：端点把 **SKU 门幅** 与 **加工类型** 接进来；不传 ⇒ 与今天逐值一致。"""

    BASE = {
        "width": 1.6, "height": 2.0, "open_count": 1,
        "mounting": "s_hook", "craft_tier": "standard", "cutting_mode": FIXED_WIDTH,
    }

    def test_sku_door_width_decides_over_width(self, client):
        # 同一张单：门幅 2.8 ⇒ 3.8 > 2.8 判超宽；门幅 4.0 ⇒ 3.8 ≤ 4.0 不判
        tight = _data(client, {**self.BASE, "fabric_width": 2.8})
        roomy = _data(client, {**self.BASE, "fabric_width": 4.0})
        # 注入：端点忽略 `fabric_width`（仍用模块常量）⇒ 两者相同 ⇒ 红
        assert _names(tight["auto_features"]) == ["超宽", "倒幅"]
        assert _names(roomy["auto_features"]) == ["倒幅"]

    def test_door_width_also_drives_meters(self, client):
        # 门幅真的接进了**算料**（不只是判定）：窄门幅 ⇒ 分幅 ⇒ 米数变
        tight = _data(client, {**self.BASE, "fabric_width": 1.0})
        roomy = _data(client, {**self.BASE, "fabric_width": 4.0})
        assert tight["fabric_meters"] > roomy["fabric_meters"]

    def test_over_height_via_endpoint(self, client):
        data = _data(client, {
            "width": 1.6, "height": 2.6, "open_count": 1,
            "mounting": "s_hook", "craft_tier": "standard",
            "cutting_mode": FIXED_HEIGHT, "fabric_width": 2.8,
        })
        assert _names(data["auto_features"]) == ["超高"]

    def test_omitting_door_width_keeps_today_values(self, client):
        """回归不变量：不传门幅 ⇒ 端点用既有常量（与直调引擎同值）。"""
        payload = {"width": 6.6, "height": 2.5, "open_count": 2, "mounting": "s_hook", "craft_tier": "standard"}
        data = _data(client, payload)
        direct = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, open_count=2, mounting="s_hook",
            craft_tier="standard", fabric_width=3.2,
        )
        assert data["fabric_meters"] == direct["fabric_meters"] == 13.3
        assert data["formula_text"] == direct["formula_text"]

    def test_omitting_cutting_mode_judges_nothing(self, client):
        payload = {"width": 1.6, "height": 2.6, "open_count": 1, "mounting": "s_hook", "craft_tier": "standard"}
        assert _data(client, payload)["auto_features"] == []
