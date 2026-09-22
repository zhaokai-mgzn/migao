# case_ids: OR-040
"""系统识别的**提示**（notices）由**服务端**给 —— issue #5036；**issue #5130 改判**。

用户 2026-09-21 裁定：「**需要统一迁移到服务端；未来 agent 也需要**」。

## 2026-09-22 改判（issue #5130）：三条提示**各有归属**

判据由「与门幅比」换成「与企业阈值参数比」（D3 替换）之后，旧的三条提示里**两条变成假话**：

| 提示类别 | 文案逐字 | 改判后的状态 |
|---|---|---|
| `missing-door-width` | 「该 SKU 未维护门幅 ⇒ **超高/超宽都判不了**」 | 🔴 **退役** —— 新判据**不读门幅** ⇒ 这句话是**假话** |
| `missing-fullness` | 「缺褶倍 ⇒ **未判超宽**」 | 🔴 **退役** —— 新判据**不含褶倍** ⇒ 同样是假话 |
| `cutting-mode-conflict` | 「加工类型选了 X，但几何按 Y 算」 | ✅ **保留** —— 它说的是**几何层**（成品高 + 卷边 vs 门幅 ⇒ 引擎实际按哪种算），**仍然为真** |

- 常量 `NOTICE_MISSING_DOOR_WIDTH` / `NOTICE_MISSING_FULLNESS` **一并删除**（不留死常量）；
  「门幅未维护」的告知改由**门幅规则端点**（`door-width-plan`）与下单页的
  `door-width-missing` / `size-door-width-missing` 徽标承担（它们说的是**几何层**能不能算，仍为真）。
- `fullness` 入参随 `missing-fullness` 一起**收窄出签名**；`window_width` 的唯一消费者
  （`missing-fullness` 的依据文案）也随之消失 ⇒ 一并收窄（同族先例：issue #5030 的 `side_margin`）。
- `fabric_width` 与 `hem_margin` **保留** —— `cutting-mode-conflict` 靠它们判几何矛盾。

## 判据（每条都能单独判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **租户配置生效**：`hem_margin` 改它 ⇒ `cutting-mode-conflict` 的判定与文案数字随之变 | 用模块常量 0.3 ⇒ 红 |
| 2 | `missing-door-width` **已退役**（常量不在 + 缺门幅不再产出该提示） | 把它加回 ⇒ 红 |
| 3 | `missing-fullness` **已退役**（常量不在 + `fullness` 不在签名里） | 把它加回 ⇒ 红 |
| 4 | **没有依据就不下结论**（加工类型缺失/表外、几何一致）⇒ 不提示 | 无依据也提示 ⇒ 红 |
| 5 | 提示**不影响**判定（提示不是特征：不进组合键） | 让提示改判定 ⇒ 红 |
| 6 | 端点 `data` 含 `notices` 且与直调函数**同源**；判定单码字段 `notice` **已删**（取值已成假话） | 端点自己拼一套 ⇒ 红；把 `notice` 加回 ⇒ 红 |
| 7 | `reason` 里的数字格式与**改前前端**逐字一致（JS `` `${2.0}` `` → `2`，不是 `2.0`） | 直接用 f-string ⇒ 整数值变 `2.0` ⇒ 红 |

⚠️ 判据 7 不是洁癖：`#4976` 复核时实测过这条漂移（引擎 `f"{2.0}"` → `2.0`，前端 → `2`）
—— 提示搬到服务端后商家看到的就是引擎这句 ⇒ 必须钉住。
"""

import inspect

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
    """直调引擎（不带端点）—— 判定面。

    ⚠️ 默认入参**不含** `fullness` / `window_width`：它们已随 `missing-fullness` 退役
    **收窄出签名**（判据 3 就是拿这件事判红的）。
    """
    params = {"window_height": 2.0, "fabric_width": 2.8, "cutting_mode": FIXED_HEIGHT}
    params.update(kwargs)
    return curtain_calc.detect_auto_feature_notices(**params)


def _kinds(notices):
    return [n["kind"] for n in notices]


def _reason(notices, kind):
    """取某类提示的 reason；**不存在 ⇒ 直接失败**（不得静默跳过）。"""
    hits = [n["reason"] for n in notices if n["kind"] == kind]
    assert len(hits) == 1, f"期望恰好一条 {kind}，实际 {_kinds(notices)}"
    return hits[0]


class TestRetiredNotices:
    """判据 2 / 3：`missing-door-width` 与 `missing-fullness` **整体退役**（#5130 改判）。

    旧判据（#5036）把这两条钉成「服务端必须逐字可表达」。用户 2026-09-22 裁定 D3 = **替换**判据后，
    它们的文案（「未维护门幅 ⇒ 超高/超宽都判不了」/「缺褶倍 ⇒ 未判超宽」）**都成了假话**
    ⇒ 判据的**前提消失**，改成**同强度的死亡条件**（旧做法不得回来）。
    """

    def test_missing_door_width_is_no_longer_a_notice(self):
        # 注入：把 `if fabric_width is None: notices.append(NOTICE_MISSING_DOOR_WIDTH)` 加回 ⇒ 红
        assert _notices(fabric_width=None) == []
        assert _notices(fabric_width=None, cutting_mode=FIXED_WIDTH) == []

    def test_missing_fullness_is_no_longer_a_notice(self):
        # 定高买宽 + 高 2.0 ⇒ 几何一致 ⇒ 一条提示都没有（旧实现会因「缺褶倍」说话，但它只管定宽买高）
        assert _notices(cutting_mode=FIXED_HEIGHT) == []
        # 定宽买高：几何会报「矛盾」（它与褶倍无关）—— 但**不得**再出现 `missing-fullness`
        # 注入：把缺褶倍提示加回（并重新加 fullness 入参）⇒ 签名断言 + 本断言双红
        assert "missing-fullness" not in _kinds(_notices(cutting_mode=FIXED_WIDTH))

    def test_retired_notice_constants_are_gone(self):
        # 死常量不留（最少代码）：加回任一个 ⇒ 红
        for gone in ("NOTICE_MISSING_DOOR_WIDTH", "NOTICE_MISSING_FULLNESS"):
            assert not hasattr(curtain_calc, gone), (
                f"`{gone}` 又回到了引擎 —— 它配的那句文案（「⇒ 超高/超宽都判不了」/「缺褶倍 ⇒ 未判超宽」）"
                "在 issue #5130 的新判据下已是假话 ⇒ 常量与提示一并退役 ⇒ 红"
            )
        assert curtain_calc.NOTICE_CUTTING_MODE_CONFLICT == "cutting-mode-conflict", (
            "`cutting-mode-conflict` 是**保留**的那一条（它说的是几何层，仍然为真）—— 缺了 = 过度删除"
        )

    def test_signature_is_narrowed(self):
        """判定面不读的量**收窄出签名**（`fullness` 与 `window_width` 都失去唯一消费者）。"""
        params = list(inspect.signature(
            curtain_calc.detect_auto_feature_notices).parameters)
        assert params == ["window_height", "fabric_width", "cutting_mode", "config"], (
            f"入参不是收窄后的签名（实际 {params}）—— `fabric_width` / `hem_margin` 必须**保留**"
            "（几何矛盾提示靠它们），`fullness` / `window_width` 已失去消费者 ⇒ 不得留死参数"
        )


class TestCuttingModeConflictNotice:
    """判据 1 / 2：几何矛盾 ⇒ 显式告知「系统实际会按哪种算」（裁定 C，**保留**）。"""

    def test_conflict_when_geometry_disagrees(self):
        # 2.6 + 0.3 = 2.9 > 2.8 ⇒ 引擎的几何分支会走定宽买高，而商家选了定高买宽
        notices = _notices(window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT)
        assert _kinds(notices) == ["cutting-mode-conflict"]
        reason = _reason(notices, "cutting-mode-conflict")
        assert "超过" in reason and FIXED_WIDTH in reason and FIXED_HEIGHT in reason

    def test_no_conflict_when_geometry_agrees(self):
        # 2.0 + 0.3 = 2.3 ≤ 2.8 ⇒ 与所选一致 ⇒ 不制造噪音
        assert _notices(window_height=2.0, fabric_width=2.8, cutting_mode=FIXED_HEIGHT) == []

    def test_conflict_also_fires_for_fixed_width_choice(self):
        # 反向覆盖：所选 = 定宽买高、而几何走得通定高买宽 ⇒ 同样提示（不偏袒某一档）
        notices = _notices(window_height=2.0, fabric_width=2.8, cutting_mode=FIXED_WIDTH)
        assert _kinds(notices) == ["cutting-mode-conflict"]

    def test_hem_margin_from_tenant_config_flips_the_verdict(self):
        """🔴 判据 1（核心）：租户把卷边调小 ⇒ 同输入不再矛盾。

        红证：提示读模块常量 0.3 ⇒ 2.6 + 0.3 = 2.9 > 2.8 ⇒ 仍报矛盾 ⇒ 必红。
        """
        notices = _notices(
            window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT,
            config={"hem_margin": 0.1},
        )
        assert notices == []

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
        assert _notices(window_height=None) == []


class TestNoticesDoNotChangeFeatures:
    """判据 5：提示**不是特征** —— 不进 `AUTO_FEATURE_NAMES`、不进组合键、不改判定。"""

    def test_notice_kinds_are_not_feature_names(self):
        notices = _notices(window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT)
        assert _kinds(notices) == ["cutting-mode-conflict"]
        names = {f["name"] for f in curtain_calc.detect_auto_features(
            window_width=6.5, window_height=4.5, cutting_mode=FIXED_WIDTH)}
        assert set(_kinds(notices)).isdisjoint(names)

    def test_features_are_identical_with_or_without_notices(self):
        kwargs = {"window_width": 6.5, "window_height": 4.5, "cutting_mode": FIXED_HEIGHT}
        before = curtain_calc.detect_auto_features(**kwargs)
        _notices(window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT)  # 调提示
        assert curtain_calc.detect_auto_features(**kwargs) == before


class TestEndpointReturnsNotices:
    """判据 6：端点 `notices` 与直调函数**同源**；判定单码字段 `notice` **已删**。"""

    BASE = {"width": 1.6, "height": 2.6, "fabric_width": 2.8,
            "cutting_mode": FIXED_HEIGHT}

    def test_endpoint_equals_engine_function(self, client):
        expected = curtain_calc.detect_auto_feature_notices(
            window_height=self.BASE["height"],
            fabric_width=self.BASE["fabric_width"],
            cutting_mode=self.BASE["cutting_mode"],
        )
        # 注入：端点自己拼一套提示 ⇒ 逐值比对必红
        assert _data(client, self.BASE)["notices"] == expected

    def test_single_code_notice_field_is_gone(self, client):
        """🔴 最少代码：`notice` 的两个取值（`missing-door-width` / `unknown-cutting-mode`）
        在新判据下**都是假话** ⇒ 字段整体删除（不留死字段）。
        """
        assert "notice" not in _data(client, self.BASE)
        assert "notice" not in _data(
            client, {k: v for k, v in self.BASE.items() if k != "fabric_width"})

    def test_missing_door_width_reports_no_notice(self, client):
        """门幅未维护**不再**产判定面提示（#4877 判定面退役）—— 告知改由门幅规则面承担。"""
        payload = {k: v for k, v in self.BASE.items() if k != "fabric_width"}
        assert _data(client, payload)["notices"] == []

    def test_tenant_config_reaches_the_notices(self, client):
        payload = {**self.BASE, "config": {"hem_margin": 0.1}}
        # 2.6 + 0.1 = 2.7 ≤ 2.8 ⇒ 不再矛盾
        assert _data(client, payload)["notices"] == []
