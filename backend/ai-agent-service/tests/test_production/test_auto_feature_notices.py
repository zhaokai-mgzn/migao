# case_ids: OR-040
"""系统识别的**提示**（notices）由**服务端**给 —— issue #5036。

用户 2026-09-21 裁定：「**需要统一迁移到服务端；未来 agent 也需要**」。

## 治的缺陷形态（读源实测）

切源（#5019）后**判定**（进加工费组合键的那个）已由服务端给，但**提示**仍在前端本地算
（`frontend/admin-web/src/lib/craft-auto-features.ts::detectAutoFeatureNotices`），
而它读的是**模块常量副本** `SIDE_MARGIN` / `HEM_MARGIN`（0.3）——
判定面读的却是**该租户配置**（`side_margin` / `hem_margin` / 档位褶倍）。
#5005 把 `hem_margin` 做成第 7 个可配键之后 ⇒ **提示句会显示错的数、几何矛盾的判断本身也会错**
（判定面已是租户配置，提示面还是 `0.3` 常量）。

## 判据（每条都能单独判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **租户配置生效**：`hem_margin` 改它 ⇒ `cutting-mode-conflict` 的判定与文案数字随之变 | 用模块常量 0.3 ⇒ 红 |
| 2 | 三类提示服务端**逐字可表达**（`missing-door-width` / `missing-fullness` / `cutting-mode-conflict`），各带 `reason` | 少一类 ⇒ 红 |
| 3 | 缺门幅 ⇒ `missing-door-width` + **不回落任何默认门幅**（#4877 口径） | 回落 2.8 / 3.2 ⇒ 红 |
| 4 | **没有依据就不下结论**（加工类型缺失/表外、高未知、几何一致）⇒ 不提示 | 无依据也提示 ⇒ 红 |
| 5 | 提示**不影响**判定（提示不是特征：不进组合键） | 让提示改判定 ⇒ 红 |
| 6 | 端点 `data` 含 `notices` 且与直调函数**同源**；`notice` 单码字段**保留**（向后兼容） | 端点自己拼一套 ⇒ 红；删掉 `notice` ⇒ 红 |
| 7 | `reason` 里的数字格式与**改前前端**逐字一致（JS `` `${2.0}` `` → `2`，不是 `2.0`） | 直接用 f-string ⇒ 整数值变 `2.0` ⇒ 红 |

⚠️ 判据 7 不是洁癖：`#4976` 复核时实测过这条漂移（引擎 `f"{2.0}"` → `2.0`，前端 → `2`），
当时包 1a 那句「与下单页同一句」**旧值从未相等**。提示搬过来后商家看到的就是引擎这句 ⇒ 现在必须钉住。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/auto-features"
FIXED_HEIGHT = "定高买宽"
FIXED_WIDTH = "定宽买高"


@pytest.fixture
def client():
    """本地 TestClient（与 `test_auto_features_endpoint.py` 同款）。"""
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


def _notices(**kwargs):
    """直调引擎（不带端点）—— 判定面。"""
    params = {
        "window_width": 1.6, "window_height": 2.0, "fabric_width": 2.8,
        "fullness": 2.0, "cutting_mode": FIXED_HEIGHT,
    }
    params.update(kwargs)
    return curtain_calc.detect_auto_feature_notices(**params)


def _kinds(notices):
    return [n["kind"] for n in notices]


def _reason(notices, kind):
    """取某类提示的 reason；**不存在 ⇒ 直接失败**（不得静默跳过）。"""
    hits = [n["reason"] for n in notices if n["kind"] == kind]
    assert len(hits) == 1, f"期望恰好一条 {kind}，实际 {_kinds(notices)}"
    return hits[0]


class TestMissingDoorWidthNotice:
    """判据 2 / 3：缺门幅 ⇒ 显式告知，且**不回落任何默认门幅**（#4877）。"""

    def test_missing_door_width_is_explicit(self):
        notices = _notices(fabric_width=None)
        assert _kinds(notices) == ["missing-door-width"]
        assert "未维护门幅" in _reason(notices, "missing-door-width")

    def test_no_default_door_width_leaks_into_the_reason(self):
        reason = _reason(_notices(fabric_width=None), "missing-door-width")
        # 注入：回落到引擎端点的 `_FABRIC_WIDTH`（3.2）或旧前端缺省（2.8）⇒ 必红
        assert "2.8" not in reason and "3.2" not in reason

    def test_fixed_width_without_door_width_also_reports_it(self):
        # 缺门幅时**判定面一个方向都不判**，但提示必须照给（不静默）
        assert _kinds(_notices(fabric_width=None, cutting_mode=FIXED_WIDTH)) == ["missing-door-width"]


class TestMissingFullnessNotice:
    """判据 2 / 7：缺褶倍 ⇒ 未判超宽（只在宽方向真的受门幅约束时才说得通）。"""

    def test_fixed_width_without_fullness_reports_it(self):
        notices = _notices(cutting_mode=FIXED_WIDTH, fullness=None, window_width=2)
        assert "missing-fullness" in _kinds(notices)
        # 判据 7：整数值不得被写成 `2.0`（改前前端产出 `2`）
        assert "成品宽 2 + 左右余量 0.3" in _reason(notices, "missing-fullness")

    def test_fixed_height_does_not_ask_for_fullness(self):
        # 定高买宽的宽方向**不受门幅约束** ⇒ 缺褶倍无可指摘（提示会误导）
        assert "missing-fullness" not in _kinds(_notices(cutting_mode=FIXED_HEIGHT, fullness=None))

    def test_side_margin_comes_from_tenant_config(self):
        reason = _reason(
            _notices(cutting_mode=FIXED_WIDTH, fullness=None, config={"side_margin": 0.5}),
            "missing-fullness",
        )
        # 注入：用模块常量 0.3 ⇒ 必红
        assert "左右余量 0.5" in reason


class TestCuttingModeConflictNotice:
    """判据 1 / 2：几何矛盾 ⇒ 显式告知「系统实际会按哪种算」（裁定 C）。"""

    def test_conflict_when_geometry_disagrees(self):
        # 2.6 + 0.3 = 2.9 > 2.8 ⇒ 引擎的几何分支会走定宽买高，而商家选了定高买宽
        notices = _notices(window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT)
        assert "cutting-mode-conflict" in _kinds(notices)
        reason = _reason(notices, "cutting-mode-conflict")
        assert "超过" in reason and FIXED_WIDTH in reason and FIXED_HEIGHT in reason

    def test_no_conflict_when_geometry_agrees(self):
        # 2.0 + 0.3 = 2.3 ≤ 2.8 ⇒ 与所选一致 ⇒ 不制造噪音
        assert "cutting-mode-conflict" not in _kinds(
            _notices(window_height=2.0, fabric_width=2.8, cutting_mode=FIXED_HEIGHT)
        )

    def test_hem_margin_from_tenant_config_flips_the_verdict(self):
        """🔴 判据 1（核心）：租户把卷边调小 ⇒ 同输入不再矛盾。

        红证：提示读模块常量 0.3 ⇒ 2.6 + 0.3 = 2.9 > 2.8 ⇒ 仍报矛盾 ⇒ 必红。
        """
        notices = _notices(
            window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT,
            config={"hem_margin": 0.1},
        )
        assert "cutting-mode-conflict" not in _kinds(notices)

    def test_hem_margin_shows_in_the_reason(self):
        reason = _reason(
            _notices(
                window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT,
                config={"hem_margin": 0.5},
            ),
            "cutting-mode-conflict",
        )
        # 注入：用模块常量 0.3 ⇒ 必红
        assert "上下卷边 0.5" in reason

    def test_conflict_does_not_claim_the_page_computed_it(self):
        # 判定已搬到服务端 ⇒ 文案不得再说「**本页**按本 SKU 门幅判」（那是前端口径的残留）
        reason = _reason(
            _notices(window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT),
            "cutting-mode-conflict",
        )
        assert "本页" not in reason


class TestNoBasisNoNotice:
    """判据 4：没有依据就不下结论（不猜）。"""

    @pytest.mark.parametrize("mode", [None, "", "斜着裁"])
    def test_unknown_cutting_mode_is_silent(self, mode):
        assert _notices(cutting_mode=mode) == []

    def test_missing_height_skips_the_conflict_notice(self):
        # 高未知 ⇒ 「几何矛盾」没有依据（判据依赖 高 + 卷边 vs 门幅）⇒ 不提示
        assert "cutting-mode-conflict" not in _kinds(_notices(window_height=None))

    def test_missing_height_with_door_width_still_reports_nothing(self):
        assert _notices(window_height=None) == []


class TestNoticesDoNotChangeFeatures:
    """判据 5：提示**不是特征** —— 不进 `AUTO_FEATURE_NAMES`、不进组合键、不改判定。"""

    def test_notice_kinds_are_not_feature_names(self):
        # 同时拿到两类提示（缺褶倍 + 矛盾）与全部特征名，断言两者**不相交**
        # 高 2.0 + 0.3 = 2.3 ≤ 2.8 ⇒ 几何会走定高买宽，而所选是定宽买高 ⇒ 矛盾
        notices = _notices(window_height=2.0, cutting_mode=FIXED_WIDTH, fullness=None)
        assert set(_kinds(notices)) == {"missing-fullness", "cutting-mode-conflict"}
        names = {f["name"] for f in curtain_calc.detect_auto_features(
            window_width=1.6, window_height=2.6, fabric_width=2.8,
            fullness=2.0, cutting_mode=FIXED_WIDTH)}
        assert set(_kinds(notices)).isdisjoint(names)

    def test_features_are_identical_with_or_without_notices(self):
        kwargs = {"window_width": 1.6, "window_height": 2.6, "fabric_width": 2.8,
                  "fullness": 2.0, "cutting_mode": FIXED_HEIGHT}
        before = curtain_calc.detect_auto_features(**kwargs)
        _notices(**kwargs)  # 调提示
        assert curtain_calc.detect_auto_features(**kwargs) == before


class TestEndpointReturnsNotices:
    """判据 6：端点加性扩展 —— 新增 `notices`，**保留** `notice`（向后兼容）。"""

    BASE = {"width": 1.6, "height": 2.6, "fabric_width": 2.8,
            "cutting_mode": FIXED_HEIGHT, "fullness": 2.0}

    def test_endpoint_equals_engine_function(self, client):
        expected = curtain_calc.detect_auto_feature_notices(
            window_width=self.BASE["width"],
            window_height=self.BASE["height"],
            fabric_width=self.BASE["fabric_width"],
            fullness=self.BASE["fullness"],
            cutting_mode=self.BASE["cutting_mode"],
        )
        # 注入：端点自己拼一套提示 ⇒ 逐值比对必红
        assert _data(client, self.BASE)["notices"] == expected

    def test_notice_single_code_field_is_kept(self, client):
        # 向后兼容：`notice` 单码字段仍在（旧调用方不破）
        assert _data(client, self.BASE)["notice"] == ""

    def test_missing_door_width_reports_both_fields(self, client):
        payload = {k: v for k, v in self.BASE.items() if k != "fabric_width"}
        data = _data(client, payload)
        assert data["notice"] == "missing-door-width"
        assert _kinds(data["notices"]) == ["missing-door-width"]

    def test_tenant_config_reaches_the_notices(self, client):
        payload = {**self.BASE, "config": {"hem_margin": 0.1}}
        # 2.6 + 0.1 = 2.7 ≤ 2.8 ⇒ 不再矛盾
        assert _kinds(_data(client, payload)["notices"]) == []
