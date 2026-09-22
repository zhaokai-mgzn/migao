# case_ids: OR-040
"""自动特征**判定端点**（issue #4976 包 2）—— 「判定移到服务端」的**读面**；**issue #5130 改判**。

## 为什么需要一个**独立**端点（不复用算料试算）

读源事实：`frontend/admin-web/src/lib/craft-calc-request.ts` 的 `CALC_CRAFTS` 只含
`韩褶 / 打孔 / 空` ⇒ **四爪钩 / 穿杆 / 平幔 不发试算请求**；而自动特征是**每一行**都要判的。
⇒ 若判定只挂在「试算响应」上，那三类工艺的行会**没有特征** ⇒ 组合键少一项 ⇒
**加工费匹配不到组合价**（P1 钱风险）。

⇒ 本端点的判定**只吃**「净窗宽 / 净窗高 + 加工类型 + 租户配置」，与**用料公式 / 工艺口径 /
门幅 / 褶倍全无关**（issue #5130 起：判定面读的是**企业阈值参数**，不是门幅）。

## 2026-09-22 改判（issue #5130）

| 面 | 旧口径（**已退役**） | 新口径（本单） |
|---|---|---|
| 判据 | 与**门幅**比（`窗宽 × 褶倍 > 门幅` / `成品高 + 卷边 > 门幅`） | 与**企业阈值参数**比（`净窗宽 > oversize_width_threshold` / `净窗高 > oversize_height_threshold`） |
| 分流 | 按 `cutting_mode` 分流（缺省 ⇒ 一个都不判，#4661） | **与加工类型无关**（缺省 ⇒ 超高/超宽照判；只有 `倒幅` 看加工类型） |
| 缺门幅 | `notice='missing-door-width'` + 判不了（#4877） | **判定面不读门幅** ⇒ 不影响判定（门幅仍是几何层输入） |
| 响应字段 | `fullness_used`（回显判定用的褶倍）/ `notice`（不判的单码） | **两者都已删**（失去消费者；且旧 `notice` 的取值在新判据下是**假话**） |

三条退役裁定的完整留档见 `backend/ai-agent-service/tests/test_production/test_auto_features.py`
的模块 docstring（#4661 / #4662 / #4877）。

## 判据（每条都能单独判红）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 与引擎 `detect_auto_features` **同源**：端点返回 == 直调函数（防第二份判据） | 端点自己拼一套判定 ⇒ 红 |
| 2 | 判据 = 绝对阈值，**与加工类型无关**（缺省 / 表外 ⇒ 超高/超宽**照判**） | 把 `cutting_mode` 分流加回 ⇒ 红 |
| 3 | 缺门幅**不影响**判定（#4877 判定面退役）；门幅仍是**几何层**输入 | 把「缺门幅 ⇒ 不判」加回 ⇒ 红 |
| 4 | 租户配置的两个阈值生效（改它 ⇒ 判定变） | 端点忽略 `config` ⇒ 红 |
| 5 | 响应**不再**含 `fullness_used` / `notice`（失去消费者；旧取值已成假话） | 把任一字段加回 ⇒ 红 |
| 6 | 缺 `X-Service-Token` ⇒ 401（与既有内部端点同款） | — |
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


#: 一份能判出**全部三条**特征的输入（净窗宽 6.5 > 6、净窗高 4.5 > 4、加工类型 = 定宽买高）
BASE = {"width": 6.5, "height": 4.5, "cutting_mode": FIXED_WIDTH}


class TestEndpointJudges:
    """判据 2：端点按**绝对阈值**判，且顺序恒为 `超宽 → 超高 → 倒幅`。"""

    def test_over_width_over_height_and_reverse(self, client):
        assert _names(_data(client, BASE)["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_over_height_only(self, client):
        data = _data(client, {"width": 1.6, "height": 4.5, "cutting_mode": FIXED_HEIGHT})
        assert _names(data["auto_features"]) == ["超高"]

    def test_nothing_judged_when_geometry_is_small(self, client):
        data = _data(client, {"width": 1.0, "height": 2.0, "cutting_mode": FIXED_HEIGHT})
        # 键恒在：空列表 = **不判**（不是「没算」）
        assert data["auto_features"] == []

    def test_equal_to_threshold_does_not_judge(self, client):
        # 边界 = 严格大于（6.0 / 4.0 都不判）
        assert _data(client, {"width": 6.0, "height": 4.0}) ["auto_features"] == []


class TestCuttingModeNoLongerGates:
    """判据 2（**改判 ③**）：加工类型缺省 / 表外 ⇒ 超高/超宽**照判**，只有 `倒幅` 缺席。"""

    @pytest.mark.parametrize("mode", [None, "", "表外取值"])
    def test_unknown_cutting_mode_still_judges_oversize(self, client, mode):
        payload = {k: v for k, v in BASE.items() if k != "cutting_mode"}
        if mode is not None:
            payload["cutting_mode"] = mode
        assert _names(_data(client, payload)["auto_features"]) == ["超宽", "超高"]


class TestDoorWidthNoLongerGates:
    """判据 3：门幅（几何层输入）**不再**影响判定面的结论。"""

    def test_door_width_does_not_change_the_verdict(self, client):
        """#4877 的**判定面**已退役：门幅缺 / 给都不影响超高与超宽（它们只看净窗宽高）。

        红证：把 `fabric_width is None ⇒ 不判超宽/超高` 的守卫加回判定面 ⇒ 两侧结果不再逐值相同 ⇒ 红。
        """
        without = _data(client, BASE)["auto_features"]
        with_door = _data(client, {**BASE, "fabric_width": 2.8})["auto_features"]
        assert without == with_door, (
            "给 / 不给门幅改变了判定结果 —— 判定面已按 issue #5130 改为与**企业阈值参数**比，"
            "门幅只剩**几何层**（用料 / 加工类型 / 规则面）的消费点 ⇒ 它又被接回了判定面 ⇒ 红"
        )

    def test_door_width_still_reaches_the_notices(self, client):
        """反向自证（不是空断言）：门幅**仍在**读面里（`notices` 的几何矛盾提示要它）。"""
        data = _data(client, {"width": 1.6, "height": 2.6, "fabric_width": 2.8,
                              "cutting_mode": FIXED_HEIGHT})
        assert [n["kind"] for n in data["notices"]] == ["cutting-mode-conflict"]


class TestTenantConfig:
    """判据 4：两个阈值是**企业参数** —— 端点必须把 `config` 接到判定上。"""

    def test_tenant_thresholds_change_the_verdict(self, client):
        # 阈值抬到 10 ⇒ 6.5 / 4.5 都不超 ⇒ 只剩倒幅
        tuned = _data(client, {**BASE, "config": {
            "oversize_width_threshold": 10, "oversize_height_threshold": 10}})
        assert _names(tuned["auto_features"]) == ["倒幅"]

    def test_tenant_width_threshold_alone_flips_over_width(self, client):
        tuned = _data(client, {**BASE, "config": {"oversize_width_threshold": 3}})
        assert _names(tuned["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_tenant_height_threshold_alone_flips_over_height(self, client):
        tuned = _data(client, {**BASE, "config": {"oversize_height_threshold": 3}})
        assert _names(tuned["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_invalid_threshold_is_rejected_with_400(self, client):
        # 护栏：0 / 负 ⇒ 400（**不静默回退默认值**）
        resp = _post(client, {**BASE, "config": {"oversize_width_threshold": 0}})
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"]["code"] == "CRAFT_CALC_INVALID_INPUT"

    def test_hem_margin_in_config_does_not_change_the_verdict(self, client):
        """改判：`hem_margin` 已**离开判定面**（它仍管几何层 —— 见 `notices` 与用料）。

        红证：把 `成品高 + cfg["hem_margin"] > 门幅` 加回判定面 ⇒ 本断言红。
        """
        plain = _data(client, BASE)["auto_features"]
        assert _data(client, {**BASE, "config": {"hem_margin": 0.9}})["auto_features"] == plain


class TestResponseFields:
    """判据 5：失去消费者的字段**已删**（`fullness_used` / `notice`）。"""

    def test_fullness_used_is_gone(self, client):
        assert "fullness_used" not in _data(client, BASE)

    def test_judgement_notice_is_gone(self, client):
        """旧 `notice` 的两个取值在新判据下都是**假话** ⇒ 删掉，不留死字段。

        ① `missing-door-width`（「未维护门幅 ⇒ 超高/超宽都判不了」）—— 新判据不读门幅；
        ② `unknown-cutting-mode`（「缺加工类型 ⇒ 不判」）—— 新判据与加工类型无关。
        """
        assert "notice" not in _data(client, {k: v for k, v in BASE.items() if k != "cutting_mode"})

    def test_door_width_is_still_echoed(self, client):
        # 反向自证：`door_width` 仍在（它是**几何层**回显，仍被 notices 的几何矛盾提示消费）
        assert _data(client, {**BASE, "fabric_width": 2.8})["door_width"] == 2.8


class TestSameSourceAsEngine:
    """判据 1：端点 == 直调 `curtain_calc.detect_auto_features`（**防第二份判据**）。"""

    @pytest.mark.parametrize("payload", [
        BASE,
        {"width": 1.6, "height": 4.5, "cutting_mode": FIXED_HEIGHT},
        {"width": 1.0, "height": 2.0, "cutting_mode": FIXED_HEIGHT},
        {**BASE, "fabric_width": 2.8},
        {**BASE, "config": {"oversize_width_threshold": 10, "oversize_height_threshold": 10}},
        {**BASE, "config": {"oversize_height_threshold": 3}},
    ])
    def test_endpoint_equals_engine_function(self, client, payload):
        expected = curtain_calc.detect_auto_features(
            window_width=payload["width"],
            window_height=payload["height"],
            cutting_mode=payload.get("cutting_mode"),
            config=payload.get("config"),
        )
        # 注入：端点自己写一套判定（不复用引擎函数）⇒ 逐值比对必红
        assert _data(client, payload)["auto_features"] == expected


class TestAuth:
    """判据 6：与既有内部端点同款认证。"""

    def test_missing_token_is_unauthorized(self, client):
        assert _post(client, BASE, token=None).status_code == 401
