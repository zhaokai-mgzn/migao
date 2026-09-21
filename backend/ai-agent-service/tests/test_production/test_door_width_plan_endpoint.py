# case_ids: OR-040
"""门幅规则**只读端点**（issue #5043 包 2b）—— 把前端 `door-width-plan.ts` 的口径搬到服务端。

## 用户裁定

- 2026-09-21（#5043 包 2b）：「**四爪钩 / 穿杆 / 平幔 这三个工艺不影响用料和门幅**」
  ⇒ 规则面**按引擎的正常用料口径算**，**不需要**为这三类另立口径、也**不需要**降级成「只判可行性」。
- 2026-09-21（#5036 母单）：「提示统一迁移到服务端」+ 拆包 A：先做算例（包 2a），规则面随后。

## 治的缺陷形态（读源实测）

前端 `frontend/admin-web/src/lib/door-width-plan.ts` 的规则与引擎
`backend/ai-agent-service/app/tools/curtain_calc.py::resolve_fabric_plan` **不是同一条规则**：

| 面 | 定宽买高的幅数 |
|---|---|
| 引擎 | `ceil(T / g_eff)`，`T` = **定高买宽用料**（按**选定用料公式**算） |
| 前端 | `ceil((成品宽 + SIDE_MARGIN) × 褶倍 / g_eff)` ⇒ **恒按倍数法** |

引擎实跑（`per_fold_single = 0.25` / 褶倍 2.0 / 韩褶）：`T` 比前端分子**小 0.65 米**
⇒ 门幅 3.2 时成品宽 1.5 ⇒ 引擎 **1 幅** / 前端 **2 幅**。
⇒ 本单**不是搬位置**：搬过去**采用引擎口径**（否则等于把错规则固化成服务端口径）。

## 判据（每条都能单独判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **规则面与引擎同源**：端点的 `door_width` / `cutting_mode` / `panels` 与 `resolve_fabric_plan` **逐值一致** | 端点自己写一套选择规则 ⇒ 红 |
| 2 | **不是倍数法**：韩褶行的 `panels` 按 `T` 算（不是 `(宽 + 余量) × 褶倍`） | 用倍数法分子 ⇒ 红（实测差 0.65 米，门幅 3.2 时 1 幅 vs 2 幅） |
| 3 | **租户配置生效**：`hem_margin` 改它 ⇒ 可行性与需接高结论随之变 | 用模块常量 `0.3` ⇒ 红 |
| 4 | **四态裁决**：`optimal` / `suboptimal` / `infeasible` / `unknown` 的边界与前端**逐条对齐** | 把 `unknown` 并进 `optimal` ⇒ 红 |
| 5 | **缺门幅 / 缺尺寸 ⇒ 显式 `undecidable`**（不回落缺省门幅 —— #4877 口径） | 回落 2.8 ⇒ 红 |
| 6 | **非 `CALC_CRAFTS` 工艺（四爪钩 / 穿杆 / 平幔）规则面照常可算**（用户裁定：它们不影响用料与门幅） | 让它们返回 `undecidable` ⇒ 红 |
| 7 | 端点**只读**：不落库、不取价（响应里没有金额字段） | 回传金额 ⇒ 红 |
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.tools import curtain_calc

ENDPOINT = "/api/internal/production/door-width-plan"
FIXED_HEIGHT = "定高买宽"
FIXED_WIDTH = "定宽买高"

#: 与 `craft-calc-request.ts` 的 `CALC_CRAFTS` 对照：这三类**不发试算请求**，
#: 但用户 2026-09-21 裁定它们**不影响用料和门幅** ⇒ 规则面照常可算。
NON_CALC_CRAFTS = ("四爪钩", "穿杆", "平幔")


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


#: 基准：成品 1.5 × 2.6、候选 [2.8, 3.2]、韩褶（褶数法）
BASE = {
    "width": 1.5,
    "height": 2.6,
    "door_widths": [2.8, 3.2],
    "craft": "韩褶",
    "craft_tier": "standard",
    "fullness": 2.0,
}


class TestRuleSolutionMatchesEngine:
    """判据 1 / 2：规则解与引擎 `resolve_fabric_plan` 同源（**不是倍数法**）。"""

    def test_solution_equals_engine_plan(self, client):
        data = _data(client, BASE)
        # 引擎直算（同一入参）—— 端点的规则面必须与它**逐值一致**
        plan = curtain_calc.build_quote(
            window_width=BASE["width"],
            window_height=BASE["height"],
            fabric_widths=BASE["door_widths"],
            craft=BASE["craft"],
            craft_tier=BASE["craft_tier"],
            fullness=BASE["fullness"],
            config=None,
        )
        assert data["door_width"] == plan["door_width"]
        assert data["effective_cutting_mode"] == plan["cutting_mode"]
        # 注入：端点自己写一套选择规则 ⇒ 逐值比对必红
        assert data["panels"] == plan.get("panels")

    def test_panels_use_formula_dependent_meters_not_the_multiples_assumption(self, client):
        """判据 2：韩褶行的 `panels` 按 `T` 算 —— 倍数法分子会**多算一幅**（实测差 0.65 米）。

        引擎实跑：成品宽 1.5 / 褶倍 2.0 / 韩褶 ⇒ `T ≈ 2.95`；
        门幅 3.2 ⇒ `ceil(2.95/3.2) = 1` 幅，而倍数法分子 `3.6` ⇒ `ceil(3.6/3.2) = 2` 幅。
        """
        data = _data(client, {**BASE, "door_widths": [3.2], "cutting_mode": FIXED_WIDTH})
        assert data["panels"] == 1, "应按定高用料 T 算（1 幅）；2 幅说明用了倍数法分子"
        # 反向自证：倍数法分子确实会得到 2 幅 ⇒ 上面那条不是空断言
        assert -(-(1.5 + 0.3) * 2.0 // 3.2) == 2


class TestTenantConfigWins:
    """判据 3：`hem_margin` 来自**该租户配置**（不是模块常量）。"""

    def test_hem_margin_from_config_flips_feasibility(self, client):
        # 成品高 2.6 + 卷边 0.3 = 2.9 > 2.8 ⇒ 单幅不可行
        base = {"width": 1.5, "height": 2.6, "door_widths": [2.8], "cutting_mode": FIXED_HEIGHT}
        assert _data(client, base)["state"] == "needs_splice"
        # 卷边调到 0.1 ⇒ 2.7 ≤ 2.8 ⇒ 单幅可做
        tuned = _data(client, {**base, "config": {"hem_margin": 0.1}})
        # 注入：读模块常量 0.3 ⇒ 这里仍会报 needs_splice ⇒ 红
        assert tuned["state"] == "single_panel"


class TestVerdict:
    """判据 4：四态裁决与前端 `judgeDoorWidthChoice` **逐条对齐**。"""

    def test_optimal_when_selected_is_the_rule_solution(self, client):
        # 成品高 2.4 + 卷边 0.3 = 2.7 ≤ 2.8 ⇒ **两个候选都可行** ⇒ 规则解取**最小** 2.8
        payload = {**BASE, "height": 2.4, "selected_door_width": 2.8}
        data = _data(client, payload)
        assert data["door_width"] == 2.8
        assert data["verdict"] == "optimal"
        assert data["suggestion"] is None

    def test_suboptimal_when_selected_is_feasible_but_not_the_solution(self, client):
        # 可行集 = [2.8, 3.2]（2.7 ≤ 2.8）⇒ 规则解取**最小** 2.8；客服选 3.2 ⇒ 可行但非最优
        data = _data(client, {**BASE, "height": 2.4, "selected_door_width": 3.2})
        assert data["door_width"] == 2.8
        assert data["verdict"] == "suboptimal"
        assert data["suggestion"]

    def test_infeasible_when_selected_cannot_be_single_panel(self, client):
        # 成品高 3.0 + 0.3 = 3.3 > 3.2（最宽）⇒ 没有任何门幅能单幅做 ⇒ needs_splice
        # **显式**定高买宽 + 高度超限 ⇒ 走接高（`resolve_fabric_plan` 的 `_splice()` 分支）
        data = _data(client, {"width": 1.5, "height": 3.0, "door_widths": [2.8, 3.2],
                              "cutting_mode": FIXED_HEIGHT, "selected_door_width": 2.8})
        assert data["state"] == "needs_splice"
        assert data["verdict"] == "infeasible"
        assert data["suggestion"]

    def test_unknown_when_nothing_selected(self, client):
        data = _data(client, BASE)
        assert data["verdict"] == "unknown"
        assert data["suggestion"] is None

    def test_unknown_when_undecidable(self, client):
        data = _data(client, {**BASE, "door_widths": [], "selected_door_width": 2.8})
        assert data["state"] == "undecidable"
        assert data["verdict"] == "unknown"


class TestUndecidable:
    """判据 5：缺门幅 / 缺尺寸 ⇒ 显式 `undecidable`（**不回落缺省门幅**，#4877）。"""

    def test_no_door_width(self, client):
        data = _data(client, {**BASE, "door_widths": []})
        assert data["state"] == "undecidable"
        assert data["code"] == "no-door-width"

    def test_invalid_door_widths_are_dropped(self, client):
        # 非正数剔除（字符串形态由前端 `parseDoorWidth` 归一后再传 —— 服务端只收数字）
        data = _data(client, {**BASE, "door_widths": [0.0, -1.0]})
        assert data["state"] == "undecidable"
        assert data["code"] == "no-door-width"

    def test_missing_height(self, client):
        payload = {k: v for k, v in BASE.items() if k != "height"}
        data = _data(client, payload)
        assert data["state"] == "undecidable"
        assert data["code"] == "missing-size"


class TestNonCalcCraftsStillGetARule:
    """判据 6：**四爪钩 / 穿杆 / 平幔** 照常可算（用户 2026-09-21：「这三个工艺不影响用料和门幅」）。"""

    @pytest.mark.parametrize("craft", NON_CALC_CRAFTS)
    def test_rule_is_computed_for_these_crafts(self, client, craft):
        data = _data(client, {**BASE, "craft": craft})
        # 注入：让这三类返回 undecidable ⇒ 红
        assert data["state"] in ("single_panel", "needs_splice")
        assert data["door_width"] in (2.8, 3.2)
        assert data["effective_cutting_mode"] in (FIXED_HEIGHT, FIXED_WIDTH)

    @pytest.mark.parametrize("craft", NON_CALC_CRAFTS)
    def test_these_crafts_do_not_change_the_rule(self, client, craft):
        """用户裁定「**不影响用料和门幅**」⇒ 与不带工艺的规则面**逐值一致**。"""
        baseline = _data(client, {k: v for k, v in BASE.items() if k != "craft"})
        got = _data(client, {**BASE, "craft": craft})
        assert (got["door_width"], got["effective_cutting_mode"], got["panels"]) == (
            baseline["door_width"], baseline["effective_cutting_mode"], baseline["panels"]
        )


class TestReadOnly:
    """判据 7：只读 —— 不算钱、不落库。"""

    def test_response_carries_no_money_fields(self, client):
        data = _data(client, BASE)
        for money in ("total_price", "fabric_price", "amount", "price"):
            assert money not in data, f"只读规则端点不该回传金额字段 {money}"

    def test_missing_token_is_unauthorized(self, client):
        assert _post(client, BASE, token=None).status_code == 401
