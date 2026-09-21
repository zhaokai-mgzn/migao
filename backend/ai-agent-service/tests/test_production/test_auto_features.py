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

## 与前端的关系（issue #5009 = #4976 包 2 后）

下单页 `frontend/admin-web/src/lib/craft-auto-features.ts` 的 `detectAutoFeatures` / `detectAutoFeatureNotices`
**已退场**（包 2 删除）—— 本模块的输出是**唯一真值**，前端只展示服务端结论。
⇒ 包 1a 里「两侧措辞逐字对齐」那句**当时是假声明**（Python `f"{2.0}"` = `2.0` 而 JS `` `${2.0}` `` = `2`，
标准档褶倍 2.0 是常见情形），由本包修掉并**用 golden 表逐字钉住**（见 `TestMigrationEquivalence`）。
"""

import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/craft-calc"
#: 只读判定端点（issue #5009 = #4976 包 2）
FEATURES_ENDPOINT = "/api/internal/production/auto-features"

#: 迁移期等价性 golden 表（由**改前**前端实现实际执行捕获，见文件头 `_provenance`）
GOLDEN = json.loads(
    (Path(__file__).resolve().parents[4] / "tests/fixtures/auto-features-migration-golden.json").read_text(
        encoding="utf-8"
    )
)

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
        """措辞**钉死** —— 前端退场后商家看到的文案**逐字**由这里决定（#5009 判据 6）。

        🔴 **本断言的值在包 2 被有意识地改过一次**（`褶倍 2.0` → `褶倍 2`）：
        包 1a 写它时声称「与下单页同一句」，**但旧值从未与前端相等**
        （Python `f"{2.0}"` = `2.0` / JS `` `${2.0}` `` = `2`）—— 那条声明**没有任何判据验证过**
        （前端腿只钉自己的串）⇒ 属于 `migao-acceptance` 的「不会红的断言 = 空断言」形态。
        包 2 把引擎侧对齐成 **JS 语义**（商家今天看到的就是前端那句）⇒ 改后两侧逐字一致，
        并由 `TestMigrationEquivalence` 用 golden 表**逐例**钉住。
        """
        assert [f["reason"] for f in _detect(cutting_mode=FIXED_WIDTH)] == [
            "成品宽 1.6 + 左右余量 0.3 = 1.9 米 × 褶倍 2 = 3.8 米 > 门幅 2.8 米",
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


# ══════════════════════════════════════════════════════════════════════════════
# issue #5009 = #4976 包 2（用户裁定 B「判定移到服务端」的前端退场收口）
# ══════════════════════════════════════════════════════════════════════════════


def _features(client, payload):
    resp = client.post(FEATURES_ENDPOINT, headers={"X-Service-Token": settings.SERVICE_TOKEN}, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    return body["data"]


def _golden_rows():
    return GOLDEN["rows"]


class TestMigrationEquivalence:
    """判据 1（本单核心）：**迁移期等价性** —— 服务端结论 == 改前前端 `detectAutoFeatures`。

    表驱动、**逐例对账**（不是抽样）：golden 表由**改前**前端实现实际执行捕获
    （`frontend/admin-web/src/lib/craft-auto-features.ts @ a4ede77bc`，见 `_provenance`），
    本腿把同一输入喂给引擎，断言 `name` / `source` / `reason` **逐字**相等。

    ⚠️ **必须逐字对 `reason`**（不只 `name`）：包 1a 的「与下单页同一句」正是一条
    **只对名字、没对文案**的假声明（`褶倍 2.0` vs `褶倍 2`）—— 只对名字的话，本表**全绿**。
    """

    def test_golden_table_is_not_empty_and_covers_the_hard_states(self):
        """反恒真下界：表里必须真的有「未知态」样本（否则空表/抽样都能全绿）。"""
        rows = _golden_rows()
        assert len(rows) >= 20, f"golden 表样本过少（{len(rows)}）⇒ 等价性退化成抽样"
        assert {r["input"]["cutting_mode"] for r in rows} >= {FIXED_HEIGHT, FIXED_WIDTH, None}
        # 「拿不到门幅 / 高未知 / 宽未知 / 缺褶倍」四种**未知态**必须在表里
        assert any(r["input"]["door_width"] is None for r in rows)
        assert any(r["input"]["width"] is None for r in rows)
        assert any(r["input"]["height"] is None for r in rows)
        assert any(r["input"]["fullness"] is None for r in rows)

    @pytest.mark.parametrize("row", _golden_rows(), ids=[r["id"] for r in _golden_rows()])
    def test_server_equals_pre_change_frontend(self, row):
        inp = row["input"]
        got = curtain_calc.detect_auto_features(
            window_width=inp["width"],
            window_height=inp["height"],
            fabric_width=row["fabric_width"],  # 页面解析后的数字（golden 里记着，本腿不重写解析）
            fullness=inp["fullness"],
            cutting_mode=inp["cutting_mode"],
        )
        # 注入：把 `_js_num` 去掉（回到 `f"{2.0}"`）⇒ M06/M08/M15/M17~M19/M21 全红
        assert got == row["auto_features"], f"{row['id']} {row['note']}"


class TestMigrationEquivalenceNotices:
    """提示（`notices`）也搬到了服务端（issue #5009）—— 同样逐例对账。

    为什么搬：用户裁定 B 是「前端**只展示**服务端结论」，「为什么没判」属于判定面；
    且 `cutting-mode-conflict` 的依据里嵌着**上下卷边** ⇒ 留前端副本会在商家改
    `hem_margin` 后**给商家看一个错的数**（0.3）。
    """

    @pytest.mark.parametrize("row", _golden_rows(), ids=[r["id"] for r in _golden_rows()])
    def test_server_notices_equal_pre_change_frontend(self, row):
        inp = row["input"]
        got = curtain_calc.detect_auto_feature_notices(
            window_width=inp["width"],
            window_height=inp["height"],
            fabric_width=row["fabric_width"],
            fullness=inp["fullness"],
            cutting_mode=inp["cutting_mode"],
        )
        assert got == row["notices"], f"{row['id']} {row['note']}"

    def test_notice_kinds_are_the_frozen_contract(self):
        """类别键集冻结（前端按 `kind` 分流渲染，改名 = 前端静默不渲染）。"""
        assert set(curtain_calc.AUTO_FEATURE_NOTICE_KINDS) == {
            "missing-door-width",
            "missing-fullness",
            "cutting-mode-conflict",
        }


class TestReadOnlyFeaturesEndpoint:
    """落点 1 改为**只读判定端点**（`POST /api/internal/production/auto-features`）。

    为什么不是复用试算端点：试算端点只对韩褶/打孔发请求、且下单页只对「公式计算」的行发请求，
    而四爪钩/穿杆/平幔行与人工指定用料行**今天照样带特征进组合键** ⇒ 复用 = 这些行静默少组合项（改钱）；
    且试算端点的 `fabric_width` / `height` 缺省回落 3.2 / 2.5，**表达不了「未知 ⇒ 不判」**。
    """

    def test_all_optional_inputs_express_unknown(self, client):
        """三个几何入参全缺 ⇒ 不判超宽/超高（**不回落** 3.2 / 2.5），只剩「倒幅」（它只取决于加工类型）。

        注入：让 `fabric_width` 缺省回落 `_FABRIC_WIDTH`（或 `height` 回落 2.5）⇒ 会凭空多出
        「超宽 / 超高」⇒ 本条红。
        """
        assert _names(_features(client, {"cutting_mode": FIXED_WIDTH})["auto_features"]) == ["倒幅"]
        # 连加工类型都缺 ⇒ 一个都不判（不猜朝向）
        assert _features(client, {})["auto_features"] == []

    def test_missing_door_width_judges_nothing_but_keeps_reverse(self, client):
        """判据 3：拿不到门幅 ⇒ **不判**超宽/超高（不是回落 3.2）+ 显式告知；**倒幅照判**（#4877）。"""
        data = _features(client, {"width": 1.6, "height": 2.6, "cutting_mode": FIXED_WIDTH, "fullness": 2.0})
        assert _names(data["auto_features"]) == ["倒幅"]
        assert [n["kind"] for n in data["notices"]] == ["missing-door-width"]

    def test_missing_height_does_not_fall_back_to_default_floor_height(self, client):
        """高未知 ⇒ 不判超高（**不回落 `_DEFAULT_HEIGHT = 2.5`**：回落 = 拿不是这张单的值判价）。"""
        data = _features(client, {"width": 1.6, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT, "fullness": 2.0})
        assert data["auto_features"] == []

    def test_missing_width_still_judges_reverse(self, client):
        """宽未知 ⇒ 仍判倒幅（今天前端如此；吞掉它 = 静默少一个组合键项）。"""
        data = _features(client, {"height": 2.6, "fabric_width": 2.8, "cutting_mode": FIXED_WIDTH, "fullness": 2.0})
        assert _names(data["auto_features"]) == ["倒幅"]

    def test_hem_margin_from_tenant_config_drives_over_height(self, client):
        """判据 5：改本租户 `hem_margin` ⇒ 服务端判「超高」随之变（组合键跟着变）。

        成品高 2.6 / 门幅 2.8：默认卷边 0.3 ⇒ 2.9 > 2.8 **判超高**；
        把卷边改成 0.1 ⇒ 2.7 ≤ 2.8 **不判**（注入：判定读模块常量而不是 `cfg` ⇒ 两次相同 ⇒ 红）。
        """
        base = {"width": 1.6, "height": 2.6, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT, "fullness": 2.0}
        assert _names(_features(client, base)["auto_features"]) == ["超高"]
        assert _features(client, {**base, "config": {"hem_margin": 0.1}})["auto_features"] == []

    def test_side_margin_from_tenant_config_drives_over_width(self, client):
        """判据 5（宽方向）：改 `side_margin` ⇒ 超宽判定随之变。"""
        base = {"width": 1.6, "fabric_width": 4.0, "cutting_mode": FIXED_WIDTH, "fullness": 2.0}
        assert _names(_features(client, base)["auto_features"]) == ["倒幅"]
        assert _names(_features(client, {**base, "config": {"side_margin": 0.9}})["auto_features"]) == ["超宽", "倒幅"]

    def test_illegal_config_is_rejected_not_silently_defaulted(self, client):
        """护栏：非法配置 ⇒ 400（静默回退默认值 = 算错钱且无人知道）。"""
        resp = client.post(
            FEATURES_ENDPOINT,
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            json={"width": 1.6, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT, "config": {"hem_margin": 0}},
        )
        assert resp.status_code == 400, resp.text

    def test_requires_service_token(self, client):
        """内部端点：无 token ⇒ 401/403（与同族内部端点一致）。"""
        resp = client.post(FEATURES_ENDPOINT, json={"cutting_mode": FIXED_WIDTH})
        assert resp.status_code in (401, 403), resp.text

    def test_does_not_touch_meters(self, client):
        """红线：**判定通路不算料** —— 响应里没有 `fabric_meters`（试算米数一字不变，#4746 不在本单）。"""
        data = _features(client, {"width": 6.6, "height": 2.5, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT})
        assert "fabric_meters" not in data



class TestGlossaryExamplesAreEngineOutput:
    """「算料配置」页算例文案 = **引擎产出**（issue #5009 = #4976 包 2b）—— fixture 与引擎逐字一致。

    为什么需要：前端退场后**不能再自己算**算例（那会变成第二份判定实现），而算例文案必须与
    商家在下单页看到的一致 ⇒ 唯一来源只能是**引擎**。fixture =
    `frontend/admin-web/src/lib/auto-feature-examples.json`（由引擎产出），由本用例逐字钉住：
    引擎改措辞 ⇒ 本用例红 ⇒ 必须重生成该 fixture（不重生成 = 页面显示旧文案）。
    """

    EXAMPLES = (
        Path(__file__).resolve().parents[4] / "frontend/admin-web/src/lib/auto-feature-examples.json"
    )

    SPECS = {
        "超高": dict(window_width=None, window_height=2.6, fabric_width=2.8,
                     cutting_mode="定高买宽", fullness=2.0),
        "超宽": dict(window_width=2.0, window_height=2.6, fabric_width=2.8,
                     cutting_mode="定宽买高", fullness=2.0),
        "倒幅": dict(window_width=2.0, window_height=2.6, fabric_width=2.8,
                     cutting_mode="定宽买高", fullness=2.0),
    }

    def test_fixture_matches_engine_output_verbatim(self):
        pinned = json.loads(self.EXAMPLES.read_text(encoding="utf8"))["examples"]
        # 反恒真：三个特征都要有（少一个 ⇒ 说明例已失效，本判据空跑）
        assert [e["name"] for e in pinned] == ["超高", "超宽", "倒幅"]
        for row in pinned:
            features = curtain_calc.detect_auto_features(**self.SPECS[row["name"]])
            hit = next((f for f in features if f["name"] == row["name"]), None)
            assert hit is not None, f"{row['name']} 的举例输入已推不出该特征（判据失去意义）"
            # 注入：改引擎措辞而不重生成 fixture ⇒ 红（页面会显示旧文案）
            assert hit["reason"] == row["reason"], row["name"]
