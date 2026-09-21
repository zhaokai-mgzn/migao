# case_ids: OR-040
"""自动特征**判定端点**（issue #4976 包 2）—— 「判定移到服务端」的**读面**。

## 为什么需要一个**独立**端点（不复用算料试算）

读源事实：`frontend/admin-web/src/lib/craft-calc-request.ts` 的 `CALC_CRAFTS` 只含
`韩褶 / 打孔 / 空` ⇒ **四爪钩 / 穿杆 / 平幔 不发试算请求**；而自动特征是**每一行**都要判的。
⇒ 若判定只挂在「试算响应」上，那三类工艺的行会**没有特征** ⇒ 组合键少一项 ⇒
**加工费匹配不到组合价**（P1 钱风险）。

⇒ 本端点的判定**只吃**「几何 + SKU 门幅 + 加工类型 + 租户配置」，与**用料公式 / 工艺口径无关**；
也**不改**试算米数（把门幅接进 `craft-calc` 是 #4746 / #4652 的另一件事）。

## 判据（每条都能单独判红）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 与引擎 `detect_auto_features` **同源**：端点返回 == 直调函数（防第二份判据） | 端点自己拼一套判定 ⇒ 红 |
| 2 | 按加工类型分流（定高买宽 ⇒ 只判超高；定宽买高 ⇒ 超宽 + 倒幅） | 去掉分流 ⇒ 红 |
| 3 | 缺门幅 ⇒ **不判** + `notice='missing-door-width'`（**不回落默认门幅**，#4877） | 回落到 2.8/3.2 ⇒ 红 |
| 4 | 缺 / 表外加工类型 ⇒ 不判 + `notice='unknown-cutting-mode'`（不猜朝向） | 缺省时按定高买宽兜底 ⇒ 红 |
| 5 | 褶倍缺省 ⇒ 取**该租户配置**的标准档（并回显 `fullness_used` 供核对） | 写死 2.0 ⇒ 红 |
| 6 | 租户配置 `side_margin` / `hem_margin` 生效 | 用模块常量 ⇒ 红 |
| 7 | 响应**自描述**：`door_width` / `fullness_used` 回显实际用于判定的值（商家可核对） | 不回显 ⇒ 红 |
| 8 | 缺 `X-Service-Token` ⇒ 401（与既有内部端点同款） | — |
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


#: 一份能判出特征的输入（定宽买高：(1.6 + 0.3) × 2.0 = 3.8 > 门幅 2.8）
BASE = {
    "width": 1.6, "height": 2.0, "fabric_width": 2.8,
    "cutting_mode": FIXED_WIDTH, "fullness": 2.0,
}


class TestEndpointJudges:
    """判据 2 / 7：端点判得出特征，并把「用了哪些值」回显出来。"""

    def test_over_width_and_reverse(self, client):
        data = _data(client, BASE)
        assert _names(data["auto_features"]) == ["超宽", "倒幅"]
        # 自描述：判定用的门幅与褶倍必须回显（商家要能核对「为什么判它超宽」）
        assert data["door_width"] == 2.8
        assert data["fullness_used"] == 2.0
        assert data["notice"] == ""

    def test_over_height(self, client):
        data = _data(client, {"width": 1.6, "height": 2.6, "fabric_width": 2.8,
                              "cutting_mode": FIXED_HEIGHT, "fullness": 2.0})
        assert _names(data["auto_features"]) == ["超高"]

    def test_nothing_judged_when_geometry_is_fine(self, client):
        data = _data(client, {"width": 1.0, "height": 2.0, "fabric_width": 2.8,
                              "cutting_mode": FIXED_HEIGHT, "fullness": 2.0})
        # 键恒在：空列表 = **不判**（不是「没算」）
        assert data["auto_features"] == []
        assert data["notice"] == ""


class TestNoDefaultDoorWidth:
    """判据 3：缺门幅 ⇒ 不判（**不回落任何默认门幅**，与 #4877 同口径）。"""

    def test_missing_door_width_is_explicitly_not_judged(self, client):
        """🔴 **2026-09-21 改判（issue #5009 = #4976 包 2b）**：原断言是 `auto_features == []`。

        改判理由（**不是放宽**）：`BASE` 的加工类型是 `定宽买高` ⇒ 缺门幅时**「倒幅」仍要判**
        —— 它只取决于加工类型、**与门幅无关**（`detect_auto_features` 的 `fabric_width=None` 分支）。
        原断言把「缺门幅」整段吞成空列表 ⇒ `定宽买高 + 门幅未维护` 的行**静默少一个组合键项**
        （= 改钱，同 #4592「组合键恒 ¥0.00」同族），而**改前的前端实现是判它的**
        （迁移期等价性，见 `tests/test_production/test_auto_features.py::TestMigrationEquivalence`
        的 M10/M12/M16 行）。

        ⇒ 现在钉的是**精确**形态：**几何特征（超宽）不判**（不回落任何默认门幅，本用例的原意一字未丢）、
        **倒幅照判**、`notice` 仍是 `missing-door-width`、`door_width` 仍回 `None`。
        红证：把端点改回「缺门幅 ⇒ `features = []`」⇒ 本断言红；回落到 2.8/3.2 ⇒ 会判出「超宽」⇒ 也红。
        """
        payload = {k: v for k, v in BASE.items() if k != "fabric_width"}
        data = _data(client, payload)
        # 几何特征**不判**（注入：回落到 2.8 / 3.2 ⇒ 会判出超宽 ⇒ 红）
        assert [f["name"] for f in data["auto_features"]] == ["倒幅"]
        assert data["notice"] == "missing-door-width"
        assert data["door_width"] is None

    def test_unknown_cutting_mode_is_explicitly_not_judged(self, client):
        data = _data(client, {**BASE, "cutting_mode": "表外取值"})
        assert data["auto_features"] == []
        assert data["notice"] == "unknown-cutting-mode"

    def test_missing_cutting_mode_is_explicitly_not_judged(self, client):
        payload = {k: v for k, v in BASE.items() if k != "cutting_mode"}
        assert _data(client, payload)["notice"] == "unknown-cutting-mode"


class TestTenantConfig:
    """判据 5 / 6：褶倍缺省取**该租户配置**的标准档；`side_margin`/`hem_margin` 生效。"""

    def test_fullness_defaults_to_tenant_standard_tier(self, client):
        payload = {k: v for k, v in BASE.items() if k != "fullness"}
        data = _data(client, payload)
        assert data["fullness_used"] == 2.0  # 引擎默认标准档
        # 把标准档改成 1.6 ⇒ 3.8 仍 > 2.8（判定不变），但回显值必须跟着变
        tuned = _data(client, {**payload, "config": {"tiers": {"standard": {"fullness": 1.6}}}})
        assert tuned["fullness_used"] == 1.6

    def test_side_margin_from_tenant_config_changes_the_verdict(self, client):
        roomy = {**BASE, "fabric_width": 4.0}
        assert _names(_data(client, roomy)["auto_features"]) == ["倒幅"]
        tuned = _data(client, {**roomy, "config": {"side_margin": 0.9}})
        # (1.6 + 0.9) × 2.0 = 5.0 > 4.0 ⇒ 判超宽
        assert _names(tuned["auto_features"]) == ["超宽", "倒幅"]

    def test_hem_margin_from_tenant_config_changes_the_verdict(self, client):
        base = {"width": 1.6, "height": 2.4, "fabric_width": 2.8,
                "cutting_mode": FIXED_HEIGHT, "fullness": 2.0}
        assert _data(client, base)["auto_features"] == []
        tuned = _data(client, {**base, "config": {"hem_margin": 0.5}})
        assert _names(tuned["auto_features"]) == ["超高"]


class TestSameSourceAsEngine:
    """判据 1：端点 == 直调 `curtain_calc.detect_auto_features`（**防第二份判据**）。"""

    @pytest.mark.parametrize("payload", [
        BASE,
        {**BASE, "fabric_width": 4.0},
        {"width": 1.6, "height": 2.6, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT, "fullness": 2.0},
        {**BASE, "config": {"side_margin": 0.9}},
    ])
    def test_endpoint_equals_engine_function(self, client, payload):
        expected = curtain_calc.detect_auto_features(
            window_width=payload["width"],
            window_height=payload["height"],
            fabric_width=payload["fabric_width"],
            fullness=payload["fullness"],
            cutting_mode=payload["cutting_mode"],
            config=payload.get("config"),
        )
        # 注入：端点自己写一套判定（不复用引擎函数）⇒ 逐值比对必红
        assert _data(client, payload)["auto_features"] == expected


class TestAuth:
    """判据 8：与既有内部端点同款认证。"""

    def test_missing_token_is_unauthorized(self, client):
        assert _post(client, BASE, token=None).status_code == 401
