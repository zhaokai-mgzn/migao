# case_ids: OR-040
"""算料**自动特征**（超高 / 超宽 / 倒幅）由**服务端**判定 —— issue #4976 包 1a；**issue #5130 改判**。

## 2026-09-22 改判（issue #5130，用户裁定 D1 / D2 / D3 / D7 / D10 / D11）

判据由 **与门幅比**（几何层）换成 **与企业参数比**（绝对阈值）：用户裁定
**D1 = 工艺分档**（超阈值时加工费与标准档不同，沿用「特征名 → 加工费组合键」这条既有链）、
**D2 = `6 / 4` 是客户给的口径 ⇒ 做成企业参数**、**D3 = 替换**当前判定公式、
**D7 = 默认 `6 / 4`、对所有租户立即生效**。

| 特征 | 旧判据（**2026-09-22 退役**） | 新判据（本单） |
|---|---|---|
| `超宽` | 加工类型 = `定宽买高` 且 `窗宽 × 褶倍 > 门幅` | **净窗宽 > `oversize_width_threshold`** |
| `超高` | 加工类型 = `定高买宽` 且 `成品高 + 上下卷边 > 门幅` | **净窗高 > `oversize_height_threshold`** |
| `倒幅` | 加工类型 = `定宽买高` | **不变**（唯一用途 = 它仍需要 `cutting_mode`） |

### 三条既有裁定一并退役（用户裁定 D10；**改判留档**，不是删掉旧文字让后人不知道口径变过）

- **#4661「按加工类型分流」退役** —— 绝对阈值与加工类型无关，且两者**可同时为真**
  ⇒ 旧判据「`定高买宽` ⇒ 只判超高 / `定宽买高` ⇒ 只判超宽 / 缺省 ⇒ 都不判」**失效**。
  新判据：`超宽` / `超高` **一律照判**（只看净窗宽 / 净窗高与阈值）；`倒幅` **仍只在 `定宽买高`** 产出。
- **#4662「超宽须含褶倍」退役** —— 新判据是 `净窗宽 > 阈值`，**不含褶倍**（也不含任何宽方向余量）。
- **#4877「判定面：缺门幅不判」退役** —— 新判据**不读门幅** ⇒ 该 SKU 未维护门幅**不再**让超高/超宽判不了。
  门幅仍是**几何层**输入（决定用料 / 加工类型 / 门幅规则面），那一层**一字未动**。

### 留档位置（三处，缺一不可）

1. 引擎 `backend/ai-agent-service/app/tools/curtain_calc.py::detect_auto_features` 的 docstring 与判据注释；
2. 前端 `frontend/admin-web/src/lib/craft-calc-glossary.ts` 的 `AUTO_FEATURE_TERMS` / `GLOSSARY_FORMULAS`；
3. 用例库 `.github/cases/order.yml` 的「下单页系统识别」用例（title / 判据表 / merge_log）。

## 判据（每条都能单独判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | `超宽` ⟺ **净窗宽 > 阈值**（**严格**大于；等于阈值不判） | 把判据改回 `窗宽 × 褶倍 > 门幅` ⇒ 红 |
| 2 | `超高` ⟺ **净窗高 > 阈值**（严格大于） | 把判据改回 `成品高 + 上下卷边 > 门幅` ⇒ 红 |
| 3 | 输出顺序恒为 `超宽 → 超高 → 倒幅` | 交换两段 ⇒ 红 |
| 4 | 阈值是**企业参数**：`config` 改它 ⇒ 判定随之变（判据读 `cfg`，不读模块常量） | 判据内联成字面量 ⇒ 红 |
| 5 | 默认阈值 == 模块常量 `6` / `4`（D7），且在 `_POSITIVE_CONFIG_KEYS`（0/负 ⇒ 报错） | 默认值写成别的数 ⇒ 红；漏登记 ⇒ 红 |
| 6 | **D11 签名收窄**：`fabric_width` / `fullness` **已不是入参**（新判据不读它们） | 传 `fabric_width=` ⇒ `TypeError` ⇒ 红 |
| 7 | `倒幅` 仍**只在** `定宽买高` 时产出（D11 保留 `cutting_mode` 的唯一理由） | `定高买宽` 也推倒幅 ⇒ 红 |
| 8 | 加工类型**缺省 / 表外 ⇒ `超宽`/`超高` 照判**（改判 ③：旧「都不判」是为分流服务的） | 缺省时短路成 `[]` ⇒ 红 |
| 9 | `reason` 带**真实数字**（商家要能核对），`source` 恒为 `推算` | reason 写成固定串 ⇒ 红 |
| 10 | `build_quote` 的 `auto_features` **键恒在**（空列表 = 不判，不是「没算」） | 不判时省略键 ⇒ 红 |

⚠️ 旧判据里的「按方向分流 / 超宽含褶倍 / 缺门幅不判」**不是被删掉，是被裁定退役**——
它们的红证在新判据下仍然可注入（见上表右列），只是**期望值反向**。
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
    """直调引擎（不带端点）—— 判据面的唯一入口。

    ⚠️ 默认入参**故意不含** `fabric_width` / `fullness`：它们已按 D11 **收窄出签名**
    （传进去会 `TypeError` —— 判据 6 就是拿这件事判红的）。
    """
    params = {"window_width": 1.6, "window_height": 2.0}
    params.update(kwargs)
    return curtain_calc.detect_auto_features(**params)


class TestOverWidthCriterion:
    """判据 1：`超宽` ⟺ **净窗宽 > `oversize_width_threshold`**（#4662 褶倍口径**退役**）。"""

    def test_over_width_is_the_absolute_width_threshold(self):
        # 高 2.0 远低于超高阈值 ⇒ 只可能判超宽；宽 6.5 > 默认阈值 6 ⇒ 超宽
        assert _names(_detect(window_width=6.5, window_height=2.0)) == ["超宽"]

    def test_equal_to_the_threshold_does_not_judge(self):
        """边界 = **严格大于**（`净窗宽 == 阈值` ⇒ 不判）。

        红证：把 `>` 写成 `>=` ⇒ 本断言红（口径从「超过」变成「达到」= 静默改钱）。
        """
        assert _detect(window_width=6.0, window_height=2.0) == []

    def test_below_the_threshold_does_not_judge(self):
        """🔴 改判的判别性锚：1.6 宽 × 褶倍 2.0 对 2.8 门幅**旧判据判超宽**，新判据**不判**。

        红证：把旧判据（含褶倍 / 与门幅比）加回来 ⇒ 本断言红 —— 这正是 §4.4 的改钱形态。
        """
        assert _detect(window_width=1.6, window_height=2.0) == []

    def test_threshold_is_an_enterprise_parameter(self):
        """判据 4：阈值取自 `config`（企业参数）⇒ 改它 ⇒ 判定随之变。"""
        assert _names(_detect(window_width=3.5, window_height=2.0)) == []
        assert _names(
            _detect(window_width=3.5, window_height=2.0,
                    config={"oversize_width_threshold": 3.0})
        ) == ["超宽"]


class TestOverHeightCriterion:
    """判据 2：`超高` ⟺ **净窗高 > `oversize_height_threshold`**（#4877 门幅口径**退役**）。"""

    def test_over_height_is_the_absolute_height_threshold(self):
        assert _names(_detect(window_width=1.6, window_height=4.5)) == ["超高"]

    def test_equal_to_the_threshold_does_not_judge(self):
        assert _detect(window_width=1.6, window_height=4.0) == []

    def test_door_width_is_no_longer_read(self):
        """🔴 #4877 **判定面退役**：门幅未维护**不再**让超高/超宽判不了。

        红证：把 `fabric_width is None ⇒ 不判` 的守卫加回判定面 ⇒ 本断言红。
        ⚠️ 门幅仍是**几何层**输入（用料 / 加工类型 / 规则面）—— 退役的只是**判定面**那一处。
        """
        assert _names(_detect(window_width=6.5, window_height=4.5)) == ["超宽", "超高"]

    def test_hem_margin_is_no_longer_read(self):
        """🔴 改判：上下卷边**不再**参与超高判定（它仍管几何层：定高可行性 / 每幅长 / 罗马帘）。

        红证：把 `成品高 + cfg["hem_margin"] > 门幅` 加回判定面 ⇒ 本断言红
        （传 `hem_margin` 会改变结果）。反向自证：该键**仍在**键集里（几何层仍在用它）。
        """
        plain = _detect(window_width=1.6, window_height=4.5)
        assert _names(plain) == ["超高"]
        assert _detect(window_width=1.6, window_height=4.5,
                       config={"hem_margin": 0.9}) == plain
        assert "hem_margin" in curtain_calc.DEFAULT_CRAFT_CALC_CONFIG, (
            "`hem_margin` 必须**保留**在算料配置键集里（几何层四处消费点仍在用它）—— "
            "缺了 = 过度删除"
        )

    def test_height_threshold_is_an_enterprise_parameter(self):
        assert _names(_detect(window_width=1.6, window_height=4.5)) == ["超高"]
        assert _names(
            _detect(window_width=1.6, window_height=4.5,
                    config={"oversize_height_threshold": 5.0})
        ) == []


class TestOutputOrderAndReverse:
    """判据 3 / 7：顺序恒为 `超宽 → 超高 → 倒幅`；`倒幅` 仍**只**由加工类型推导。"""

    def test_order_is_width_then_height_then_reverse(self):
        assert _names(_detect(window_width=6.5, window_height=4.5,
                              cutting_mode=FIXED_WIDTH)) == ["超宽", "超高", "倒幅"]

    def test_reverse_only_for_fixed_width(self):
        # 定高买宽**不推**倒幅（它仍是「朝向特征」的唯一来源 = D11 保留 cutting_mode 的理由）
        assert _names(_detect(window_width=6.5, window_height=4.5,
                              cutting_mode=FIXED_HEIGHT)) == ["超宽", "超高"]

    def test_reverse_reason_is_the_cutting_mode(self):
        reverse = [f for f in _detect(window_width=1.0, window_height=2.0,
                                      cutting_mode=FIXED_WIDTH) if f["name"] == "倒幅"]
        assert [f["reason"] for f in reverse] == [f"加工类型 = {FIXED_WIDTH}"]


class TestCuttingModeDefaultNoLongerShortCircuits:
    """判据 8（**改判 ③**）：加工类型缺省 / 表外 ⇒ `超宽`/`超高` **照判**、只有 `倒幅` 缺席。

    旧判据（#4661）「缺省 / 表外取值 ⇒ **一个都不判**」的口径是**为分流服务**的（不猜朝向）；
    新判据与加工类型无关 ⇒ 那句失去依据。

    红证：把 `if cutting_mode not in (…) : return []` 的短路加回 ⇒ 本断言红。
    """

    @pytest.mark.parametrize("mode", [None, "", "表外取值"])
    def test_oversize_still_judged_without_cutting_mode(self, mode):
        assert _names(_detect(window_width=6.5, window_height=4.5,
                              cutting_mode=mode)) == ["超宽", "超高"]

    def test_nothing_judged_when_geometry_is_small(self):
        # 反向自证：判定面**不是**恒真（小窗仍然一条都不判）
        assert _detect(window_width=1.6, window_height=2.0, cutting_mode=None) == []


class TestTenantConfigKeys:
    """判据 4 / 5：两个新键进键集、默认值 == 模块常量、且必须是正数（护栏）。"""

    def test_defaults_equal_the_module_constants(self):
        cfg = curtain_calc.DEFAULT_CRAFT_CALC_CONFIG
        # 注入：把默认值写成别的数（而常量仍 6 / 4）⇒ 红（「默认值有两个落点」）
        assert cfg["oversize_width_threshold"] == curtain_calc.OVERSIZE_WIDTH_THRESHOLD
        assert cfg["oversize_height_threshold"] == curtain_calc.OVERSIZE_HEIGHT_THRESHOLD

    def test_defaults_are_the_customer_figures(self):
        """D7：阈值默认 = `6 / 4`（用户已知会改存量租户的加工费组合键，明确接受）。

        红证：把常量改成别的数 ⇒ 红。⚠️ **不写死断言**：值与模块常量逐值比对，
        但**同时**要求它们是正值 —— 否则「默认 = 客户口径」这句话无法被判红。
        """
        assert curtain_calc.OVERSIZE_WIDTH_THRESHOLD == 6.0
        assert curtain_calc.OVERSIZE_HEIGHT_THRESHOLD == 4.0

    def test_keys_are_registered_as_positive_scalars(self):
        # 注入：漏登记 ⇒ 0/负数被静默接受 ⇒ 红
        assert "oversize_width_threshold" in curtain_calc._POSITIVE_CONFIG_KEYS
        assert "oversize_height_threshold" in curtain_calc._POSITIVE_CONFIG_KEYS

    @pytest.mark.parametrize("key", ["oversize_width_threshold", "oversize_height_threshold"])
    @pytest.mark.parametrize("bad", [0, -1, "abc"])
    def test_invalid_threshold_is_rejected(self, key, bad):
        with pytest.raises(ValueError):
            curtain_calc.resolve_craft_calc_config({key: bad})


class TestNarrowedSignature:
    """判据 6（D11）：`fabric_width` / `fullness` **已不是** `detect_auto_features` 的入参。"""

    def test_fabric_width_is_not_a_parameter(self):
        import inspect

        params = inspect.signature(curtain_calc.detect_auto_features).parameters
        assert list(params) == ["window_width", "window_height", "cutting_mode", "config"], (
            f"入参不是收窄后的签名（实际 {list(params)}）—— 新判据不读门幅与褶倍，"
            "留着已无消费者的入参 = 死参数（D11 明写「收窄签名」）"
        )

    def test_passing_fabric_width_raises(self):
        with pytest.raises(TypeError):
            curtain_calc.detect_auto_features(
                window_width=6.5, window_height=2.0, fabric_width=2.8)

    def test_passing_fullness_raises(self):
        with pytest.raises(TypeError):
            curtain_calc.detect_auto_features(
                window_width=6.5, window_height=2.0, fullness=2.0)


class TestReasonCarriesNumbers:
    """判据 9：判定依据必须能被商家核对（带真实数字，不是固定串）。"""

    def test_reasons_quote_the_real_numbers(self):
        reasons = {f["name"]: f["reason"] for f in _detect(window_width=6.5, window_height=4.5)}
        assert "6.5" in reasons["超宽"] and "6.0" in reasons["超宽"]
        assert "4.5" in reasons["超高"] and "4.0" in reasons["超高"]

    def test_reason_wording_is_pinned(self):
        """措辞**钉死**（商家看到的文案不得悄悄变 —— 措辞一改就是可见的行为变化）。

        红证：改一个字 ⇒ 红（本断言红 ⇒ 先想清楚再改）。
        """
        assert [f["reason"] for f in _detect(window_width=6.5, window_height=4.5,
                                             cutting_mode=FIXED_WIDTH)] == [
            "净窗宽 6.5 米 > 超宽阈值 6.0 米",
            "净窗高 4.5 米 > 超高阈值 4.0 米",
            "加工类型 = 定宽买高",
        ]

    def test_reason_shows_the_tenant_threshold(self):
        """判据 4 的文案面：依据里显示的必须是**该租户**的阈值（不是模块常量）。"""
        reasons = [f["reason"] for f in _detect(
            window_width=3.5, window_height=2.0, config={"oversize_width_threshold": 3.0})]
        assert reasons == ["净窗宽 3.5 米 > 超宽阈值 3.0 米"]

    def test_every_feature_is_marked_as_inferred(self):
        # 判据是客户口径 + 工艺分档，**非 ERP 实证** ⇒ 一律标 `推算`（与下单页同口径）
        for feature in _detect(window_width=6.5, window_height=4.5, cutting_mode=FIXED_WIDTH):
            assert feature["source"] == "推算"


class TestBuildQuoteEmitsAutoFeatures:
    """判据 10：`build_quote` 的 `auto_features` **键恒在**。"""

    def test_key_always_present_even_when_nothing_judged(self):
        quote = curtain_calc.build_quote(window_width=1.6, window_height=2.0, fabric_width=2.8)
        # 注入：不判时省略该键 ⇒ KeyError 红（「没判」与「没算」必须可区分）
        assert quote["auto_features"] == []

    def test_quote_carries_the_features_when_geometry_exceeds(self):
        quote = curtain_calc.build_quote(
            window_width=6.5, window_height=4.5, fabric_width=2.8,
            mounting="s_hook", craft_tier="standard", cutting_mode=FIXED_WIDTH,
        )
        assert _names(quote["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_default_path_values_unchanged(self):
        """回归不变量：判定面改的是**特征**，不是**用料**（§4.4：几何层与特征层在代码里分离）。

        用料锚点（6.6 窗 / 2.5 高 / 双开 / 韩褶标准档 ⇒ 13.3 米 / 52 折）**逐值不变**；
        唯一变化 = `auto_features` 现在多出 `超宽`（`6.6 > 默认阈值 6`）—— 这正是本单的**改钱面**
        （特征名进加工费组合键），也是「替换判定公式 = 只改组合键、不改米数」的现场证据。

        红证：把判定接进用料 / 加工类型 ⇒ 米数断言红；不再判超宽 ⇒ 特征断言红。
        """
        quote = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            open_count=2, craft_tier="standard",
        )
        assert quote["fabric_meters"] == 13.3
        assert quote["pleat_count"] == 52
        assert _names(quote["auto_features"]) == ["超宽"]


class TestEndpointWiring:
    """端点把加工类型与企业参数接进来；判定面**不再**需要门幅与褶倍。"""

    BASE = {
        "width": 6.5, "height": 4.5, "open_count": 1,
        "mounting": "s_hook", "craft_tier": "standard", "cutting_mode": FIXED_WIDTH,
    }

    def test_oversize_features_via_endpoint(self, client):
        data = _data(client, self.BASE)
        assert _names(data["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_tenant_thresholds_reach_the_endpoint(self, client):
        # 阈值抬到 10 ⇒ 6.5 宽 / 4.5 高都不超 ⇒ 只剩倒幅
        data = _data(client, {**self.BASE, "config": {
            "oversize_width_threshold": 10, "oversize_height_threshold": 10}})
        assert _names(data["auto_features"]) == ["倒幅"]

    def test_omitting_cutting_mode_still_judges_oversize(self, client):
        payload = {"width": 6.5, "height": 4.5, "open_count": 1,
                   "mounting": "s_hook", "craft_tier": "standard"}
        assert _names(_data(client, payload)["auto_features"]) == ["超宽", "超高"]

    def test_door_width_no_longer_gates_the_verdict(self, client):
        """旧口径「缺门幅 ⇒ 判不了」在**判定面**已退役；缺门幅也不再给「不判」的单码说明。"""
        payload = {"width": 6.5, "height": 4.5, "open_count": 1,
                   "mounting": "s_hook", "craft_tier": "standard", "cutting_mode": FIXED_WIDTH}
        data = _data(client, payload)
        assert _names(data["auto_features"]) == ["超宽", "超高", "倒幅"]

    def test_endpoint_does_not_report_fullness_used_or_judgement_notice(self, client):
        """🔴 最少代码：失去消费者的两个字段**已删**（`fullness_used` / `notice`）。

        旧 `notice` 的取值（`missing-door-width` / `unknown-cutting-mode`）在新判据下**都是假话**
        （缺门幅不再让超高/超宽判不了；缺加工类型不再让它们不判）；`fullness_used` 的消费方
        （判定面与 `missing-fullness` 提示）都随本单退役 ⇒ 一并删除，不留死字段。

        红证：把任一字段加回响应 ⇒ 红。
        """
        data = _data(client, self.BASE)
        assert "fullness_used" not in data, "`fullness_used` 已无消费者 ⇒ 不得再回传"
        assert "notice" not in data, "`notice` 的两个取值都成了假话 ⇒ 不得再回传"

    def test_omitting_door_width_keeps_meters_values(self, client):
        """回归不变量：不传门幅 ⇒ 端点用既有常量算料（与直调引擎同值）。

        ⚠️ 这钉的是**几何层**（管用料）—— 判定面已与门幅无关，但用料这一层一字未动。
        """
        payload = {"width": 6.6, "height": 2.5, "open_count": 2,
                   "mounting": "s_hook", "craft_tier": "standard"}
        data = _data(client, payload)
        direct = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, open_count=2, mounting="s_hook",
            craft_tier="standard", fabric_width=3.2,
        )
        assert data["fabric_meters"] == direct["fabric_meters"] == 13.3
        assert data["formula_text"] == direct["formula_text"]
