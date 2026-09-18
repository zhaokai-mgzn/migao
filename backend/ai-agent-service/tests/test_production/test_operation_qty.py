"""应做数量内部端点（issue #4208）—— 算料引擎的第一个运行时消费者。

背景：商家后台生产明细页「应做数量」退化成**订单数量**（订单数量=3 ⇒ 11 道工序全 3，
「韩褶-布」显示 3 折、「外帘装袋」显示 3 套）。真值源 `docs/curtain-production-rules.md` §3：
工序实例的应做数量 = **算料引擎输出**（折数/孔数/用料米数/幅数），报工只确认不心算。
`app/production/routing.py::_qty_for` 此前**零运行时消费者**，本端点（方案 A）即接线点。

口径铁律（逐条有对应断言）：
1. 数量**只**来自 `routing._qty_for`（唯一算料真相源），严禁第二份算料逻辑
   ⇒ `test_qty_equals_engine_direct_call` 逐值直调比对（防复制逻辑的守门断言）；
2. 缺键**一律兜底 1、绝不落 0**（应做 0 ⇒ `done_qty ≥ qty` 恒真 ⇒ 假完工）
   ⇒ `test_empty_calc_info_falls_back_to_one` 断言 `== 1.0` 且 `!= 0`；
3. 引擎不认识的工序/单位 ⇒ 兜底 1 + `qty_source="fallback"`，HTTP 仍 200（不得把加工单生成打成硬失败）
   ⇒ `test_unknown_operation_...` / `test_engine_unknown_unit_falls_back_to_one`；
4. 路线/单价/必完标记**不由本端点提供**（真相源是 DB 工序库 #4193）⇒ `test_response_shape_only_qty`。

`qty_source` 三态（字段存在的唯一理由：让「真兜底」与「有依据的推算」可区分）：
① 键名（fabric_meters/pleat_count/holes）= 直接供数；
② `<键名>_x6` = 「孔」类无 holes 时按每米 6 孔的行业口径估算（分支②，值 ≠ 1）；
③ "fallback" = 真兜底 1（无键可读 / 未知工序或单位 / panels・set_count 引擎**待补键**）。

红证（实现前逐条红，红因已核）：
- 判据 1/2/3：端点未实现 ⇒ `POST /api/internal/production/operation-qty` 404（`assert 404 == 200` 红）；
  且判据 3 的断言是**判别性**的：若实现只把 `_qty_for` 原样透传（引擎对未知工序/单位默认按「米」读
  `fabric_meters`）⇒ 未知工序会得到 12.3、「个」类会得到 12.3，本断言仍红；
- 判据 4：未实现 ⇒ 404 ⇒ `resp.json()["data"]` KeyError/断言红；
- 键漂移门禁（`TestSourceKeysDriftGate`）：`routing.KNOWN_QTY_UNITS`/`DIRECT_QTY_KEYS`/`_qty_keys_for_unit` 未定义 ⇒
  import 即红（Collection Error）；把「孔」分支②（按米估算）错标 fallback ⇒
  `test_hole_estimate_is_not_reported_as_placeholder_fallback` 红。
"""
# case_ids: PP-010

import pytest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.production.routing import (
    DIRECT_QTY_KEYS,
    FOLD_KEYS,
    HOLE_ESTIMATE_SUFFIX,
    HOLE_KEYS,
    HOLE_PER_METER,
    METER_KEYS,
    KNOWN_QTY_UNITS,
    OPERATION_CATALOG,
    _qty_for,
    _qty_keys_for_unit,
    qty_and_source,
)

ENDPOINT = "/api/internal/production/operation-qty"

# 引擎认识的单位（`_qty_for` 有分支的口径）；其余单位（如「个」）按铁律 3 走 fallback
KNOWN_UNITS = set(KNOWN_QTY_UNITS)

POSITION_NAME = "2699系列雪尼尔窗帘面料"
OPERATIONS = ["精裁-布", "布三边", "韩褶-布", "外帘装袋"]
# 冻结契约样例（issue #4208）：set_count=1 也在，但「套」类引擎**不产出** ⇒ 口径来源标 fallback
CALC_INFO = {"fabric_meters": 12.3, "pleat_count": 24, "panels": 2, "set_count": 1}

POSITION = {
    "position_name": POSITION_NAME,
    "curtain_type": "布帘",
    "craft": "韩褶",
    "operations": OPERATIONS,
    "calc_info": CALC_INFO,
}


@pytest.fixture
def client():
    """本地 TestClient。

    为什么不复用 conftest 的 `test_client`：它 patch 了**已移除**的 `app.main.get_rag_pipeline`
    ⇒ 该 fixture 当前一律 AttributeError（越界发现，非本单范围；同 tests/test_registration_review.py
    的 `client` 处置）。本 fixture 只 patch 实际存在的生命周期依赖。
    """
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app
        with TestClient(create_app()) as c:
            yield c


def _post(client, positions, token=settings.SERVICE_TOKEN):
    """POST 端点；token=None ⇒ 完全不带头（判据 4 的缺 token 形态）。"""
    headers = {} if token is None else {"X-Service-Token": token}
    return client.post(ENDPOINT, headers=headers, json={"positions": positions})


def _first_position(resp):
    body = resp.json()
    assert body["success"] is True
    return body["data"]["positions"][0]


def _source(operation, calc_info):
    """口径来源标签（`qty_and_source` 的第二个返回值）。"""
    return qty_and_source(operation, calc_info)[1]


# ══════════════════════════════════════════════════════════════════════════
# 判据 1：calc_info={fabric_meters:12.3, pleat_count:24} ⇒ 精裁-布 12.3 / 韩褶-布 24
#        且与直调 `_qty_for` 逐值相等（防「复制第二份算料逻辑」的守门断言）
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion1EngineOutput:

    def test_qty_by_operation_is_engine_output(self, client):
        resp = _post(client, [POSITION])
        assert resp.status_code == 200
        pos = _first_position(resp)
        assert pos["position_name"] == POSITION_NAME
        assert pos["qty_by_operation"] == {
            "精裁-布": 12.3,      # 米：用料米数
            "布三边": 12.3,       # 米：用料米数
            "韩褶-布": 24.0,      # 折：折数（**不是订单数量的 3**）
            "外帘装袋": 1.0,      # 套：1 樘 = 1 套
        }
        assert pos["qty_source_by_operation"] == {
            "精裁-布": "fabric_meters",
            "布三边": "fabric_meters",
            "韩褶-布": "pleat_count",
            "外帘装袋": "fallback",   # 引擎不产出 set_count（build_quote 返回键实测无该键）
        }

    def test_qty_equals_engine_direct_call(self, client):
        """守门断言：端点每个数量都必须与直调 `routing._qty_for` 逐值相等。

        若有人在端点里复制了第二份算料逻辑（历史教训：`meters` vs `fabric_meters`
        键名漂移，见 routing.py 第 93-105 行），这里必红。
        """
        pos = _first_position(_post(client, [POSITION]))
        for operation, qty in pos["qty_by_operation"].items():
            assert qty == _qty_for(operation, CALC_INFO), (
                f"{operation} 的应做数量 {qty} ≠ 直调 _qty_for 的 "
                f"{_qty_for(operation, CALC_INFO)} ⇒ 存在第二份算料逻辑"
            )

    def test_real_engine_quote_is_consumed_without_key_drift(self, client):
        """用**引擎真产出**（build_quote 返回字典）喂端点：米/折类数量不得落 0/1。

        红证形态 = issue #4116：`_qty_for` 读 `meters` 而引擎返回 `fabric_meters`
        ⇒ 米类工序应做数量恒兜底（本断言在那种实现下 8.7 → 1.0 变红）。
        """
        from app.tools.curtain_calc import build_quote

        quote = build_quote(
            window_width=3.0, window_height=2.6, mounting="s_hook",
            fabric_price=80, pleat_count=24, open_count=2,
        )
        assert quote["fabric_meters"] > 0, f"引擎真产出异常，本用例前提不成立: {quote}"

        pos = _first_position(_post(client, [{**POSITION, "calc_info": quote}]))
        assert pos["qty_by_operation"]["精裁-布"] == quote["fabric_meters"]
        assert pos["qty_by_operation"]["韩褶-布"] == float(quote["pleat_count"])
        assert all(qty > 0 for qty in pos["qty_by_operation"].values())
        assert pos["qty_source_by_operation"]["精裁-布"] == "fabric_meters"


# ══════════════════════════════════════════════════════════════════════════
# 判据 2：calc_info={} ⇒ 各工序 qty 全为 1（**不是 0**）
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion2NeverZero:

    def test_empty_calc_info_falls_back_to_one(self, client):
        pos = _first_position(_post(client, [{**POSITION, "calc_info": {}}]))
        assert pos["qty_by_operation"] == {op: 1.0 for op in OPERATIONS}
        # 显式断言「不落 0」（应做 0 ⇒ done_qty ≥ qty 恒真 ⇒ 假完工）
        assert all(qty != 0 for qty in pos["qty_by_operation"].values())
        assert set(pos["qty_source_by_operation"].values()) == {"fallback"}

    def test_partial_calc_info_only_missing_key_falls_back(self, client):
        """只给米数：折数缺失 ⇒ 韩褶-布 兜底 1（**不落 0**），米类仍取 12.3。"""
        pos = _first_position(
            _post(client, [{**POSITION, "calc_info": {"fabric_meters": 12.3}}])
        )
        assert pos["qty_by_operation"] == {
            "精裁-布": 12.3, "布三边": 12.3, "韩褶-布": 1.0, "外帘装袋": 1.0,
        }
        assert pos["qty_source_by_operation"]["韩褶-布"] == "fallback"

    def test_missing_key_uses_default_one_not_zero(self, client):
        """缺键（不是 0）⇒ 兜底 1：这是「绝不落 0」的判别性形态。"""
        pos = _first_position(
            _post(client, [{**POSITION, "calc_info": {"panels": 2}}])
        )
        assert pos["qty_by_operation"]["精裁-布"] == 1.0
        assert pos["qty_by_operation"]["精裁-布"] != 0
        assert pos["qty_source_by_operation"]["精裁-布"] == "fallback"


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：未知工序 ⇒ qty=1 + qty_source="fallback"，HTTP 仍 200（不报错）
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion3UnknownOperation:

    def test_unknown_operation_falls_back_to_one_and_http_200(self, client):
        """工序库（#4193 切库后由商家配置）出现 python 侧不认识的工序名。

        判别性：`_qty_for` 对未知工序默认按「米」读 `fabric_meters`（会得 12.3）
        ⇒ 直接把 `_qty_for` 透传的实现本断言红。
        """
        resp = _post(
            client,
            [{**POSITION, "operations": ["韩褶-布", "烫金-布", "外帘装袋"]}],
        )
        assert resp.status_code == 200
        pos = _first_position(resp)
        assert pos["qty_by_operation"] == {"韩褶-布": 24.0, "烫金-布": 1.0, "外帘装袋": 1.0}
        assert pos["qty_source_by_operation"] == {
            "韩褶-布": "pleat_count", "烫金-布": "fallback", "外帘装袋": "fallback",
        }

    def test_unknown_operation_does_not_fail_the_whole_position(self, client):
        """一个未知工序不得把整张加工单打成硬失败（HTTP 200 + 其余部位照常）。"""
        resp = _post(client, [
            {**POSITION, "operations": ["精裁-布", "烫金-布"]},
            {**POSITION, "position_name": "2699系列雪尼尔窗帘纱", "operations": ["韩褶-纱"]},
        ])
        assert resp.status_code == 200
        positions = resp.json()["data"]["positions"]
        assert positions[0]["qty_by_operation"] == {"精裁-布": 12.3, "烫金-布": 1.0}
        assert positions[1]["position_name"] == "2699系列雪尼尔窗帘纱"
        assert positions[1]["qty_by_operation"] == {"韩褶-纱": 24.0}

    def test_engine_unknown_unit_falls_back_to_one(self, client):
        """铁律 3 的另一半：引擎**不认识的单位**（「个」：帘头制作）⇒ 兜底 1 + fallback。

        判别性：`_qty_for` 对未知单位走「米」分支（会得 fabric_meters=12.3）
        ⇒ 直接透传的实现本断言红（12.3 个 ≠ 1 个，也是数量与单位不匹配的同族缺陷）。
        """
        pos = _first_position(_post(client, [{**POSITION, "operations": ["帘头制作"]}]))
        assert pos["qty_by_operation"] == {"帘头制作": 1.0}
        assert pos["qty_source_by_operation"] == {"帘头制作": "fallback"}

    def test_empty_operations_list_is_accepted(self, client):
        """部位无工序（空列表）⇒ 空映射，不是 500。"""
        resp = _post(client, [{**POSITION, "operations": []}])
        assert resp.status_code == 200
        pos = _first_position(resp)
        assert pos["qty_by_operation"] == {}
        assert pos["qty_source_by_operation"] == {}


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：缺 X-Service-Token ⇒ 401/403
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion4ServiceToken:

    def test_missing_token_rejected(self, client):
        resp = _post(client, [POSITION], token=None)
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text

    def test_wrong_token_rejected(self, client):
        resp = _post(client, [POSITION], token="wrong-token")
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text


# ══════════════════════════════════════════════════════════════════════════
# 铁律 4：本端点**只**答数量 —— 路线/单价/必完标记的真相源是 DB 工序库（#4193）
# ══════════════════════════════════════════════════════════════════════════

class TestResponseShapeOnlyQty:

    def test_position_payload_has_only_qty_fields(self, client):
        resp = _post(client, [POSITION])
        pos = _first_position(resp)
        assert set(pos) == {"position_name", "qty_by_operation", "qty_source_by_operation"}

    def test_no_unit_price_or_must_finish_leaks(self, client):
        resp = _post(client, [POSITION])
        assert resp.status_code == 200  # 前置：404 的空响应体不得让本条静默变绿
        text = resp.text
        assert "unit_price" not in text
        assert "is_must_finish" not in text

    def test_response_shell_matches_internal_endpoints(self, client):
        """沿用 internal.py 既有外壳（make_response）—— admin-api 客户端照此解析。"""
        body = _post(client, [POSITION]).json()
        assert body["success"] is True
        assert set(body) == {"success", "data", "requestId", "timestamp"}
        assert set(body["data"]) == {"positions"}


# ══════════════════════════════════════════════════════════════════════════
# 键漂移门禁（不复制第二份算料逻辑的结构性护栏）
#
# `qty_source` 要知道「哪个键供了数」就必须声明「单位 → 候选键」。这份声明与
# `_qty_for` 的分支结构是**同一事实的两处表述** ⇒ 必须有门禁钉住，否则它会像
# `meters`/`fabric_meters` 那样悄悄漂移（本仓已有一次同族事故，issue #4116）。
# ══════════════════════════════════════════════════════════════════════════

class TestSourceKeysDriftGate:

    def test_every_catalog_operation_has_a_defined_source(self):
        """混合轮询：库里**每个**工序都要能给出明确来源（已知单位命中键名/估算/fallback，
        未知单位（「个」）恒 fallback）—— 不留「未定义」的静默分支。"""
        for operation, meta in OPERATION_CATALOG.items():
            source = _source(operation, CALC_INFO)
            if meta["unit"] in KNOWN_UNITS:
                assert source in set(DIRECT_QTY_KEYS) | {"holes", "fallback"} | {
                    key + HOLE_ESTIMATE_SUFFIX for key in _qty_keys_for_unit("孔")
                }
            else:
                assert source == "fallback", f"{operation}（{meta['unit']}）应走 fallback"

    def test_declared_units_all_have_candidate_keys(self):
        """声明过的单位必须真有候选键（删掉 `_qty_keys_for_unit` 的某个分支 ⇒ 红）。"""
        for unit in KNOWN_QTY_UNITS:
            assert _qty_keys_for_unit(unit) != (), (
                f"已声明单位 {unit} 没有候选键 ⇒ qty_source 会静默错报 fallback"
            )

    def test_direct_qty_keys_are_declared_qty_keys(self):
        """「直接供数」清单必须是 `_qty_for` 读键的子集（改名/删除即红）。"""
        assert set(DIRECT_QTY_KEYS) <= set(METER_KEYS) | set(FOLD_KEYS)

    @pytest.mark.parametrize("operation", sorted(OPERATION_CATALOG))
    def test_declared_source_key_is_really_consumed_by_qty_for(self, operation):
        """逐单位喂 7.0：`_qty_for` 必须真的读该键（得 1.0 = 该键已不被读 ⇒ 漂移）。"""
        unit = OPERATION_CATALOG[operation]["unit"]
        if unit not in KNOWN_UNITS:
            return  # 未知单位无候选键（铁律 3 ⇒ fallback），由 test_unknown_unit_ops_are_fallback 覆盖
        for key in _qty_keys_for_unit(unit):
            qty = _qty_for(operation, {key: 7.0})
            assert qty != 1.0, (
                f"{operation}（{unit}）不再读 {key}（qty=1.0 兜底值）"
                f" ⇒ `_qty_keys_for_unit` 与 `_qty_for` 已漂移"
            )

    @pytest.mark.parametrize("operation", sorted(OPERATION_CATALOG))
    def test_source_label_follows_three_state_rule(self, operation):
        """逐键核标签三态：直接供数 ⇒ 键名；孔类按米估算 ⇒ `<键名>_x6`；其余（panels/set_count/
        meters 别名）⇒ fallback。标签与 `_qty_for` 的**分支**逐条对应，是本门禁的判据本体。"""
        unit = OPERATION_CATALOG[operation]["unit"]
        if unit not in KNOWN_UNITS:
            return
        for key in _qty_keys_for_unit(unit):
            if unit == "孔":                      # holes 直采；米数键 ⇒ 每米 6 孔估算
                expected = key if key in HOLE_KEYS else key + HOLE_ESTIMATE_SUFFIX
            elif key in DIRECT_QTY_KEYS:          # fabric_meters / pleat_count 直采
                expected = key
            else:                                 # panels / set_count ⇒ 待补键，真兜底
                expected = "fallback"
            assert _source(operation, {key: 7.0}) == expected

    def test_unknown_unit_ops_are_fallback(self):
        """「个」类工序（帘头制作/抱枕/腰靠垫）不在引擎口径内 ⇒ 铁律 3 的未知 unit 形态。"""
        for operation in ("帘头制作", "抱枕", "腰靠垫"):
            assert OPERATION_CATALOG[operation]["unit"] == "个"
            assert _source(operation, CALC_INFO) == "fallback"

    def test_unknown_operation_source_is_fallback(self):
        assert _source("烫金-布", CALC_INFO) == "fallback"

    def test_value_and_label_are_decoupled(self):
        """值一律取 `_qty_for`（键命中即有值）；标签只表达「值从哪来」。"""
        assert qty_and_source("精裁-布", {"fabric_meters": 12.3}) == (12.3, "fabric_meters")
        # `meters` 是兼容别名（引擎不产出）⇒ 值照取 12.3，标签如实报 fallback
        assert qty_and_source("精裁-布", {"meters": 12.3}) == (12.3, "fallback")
        # 引擎不认识的工序/单位 ⇒ 兜底 1（**不是** `_qty_for` 对未知工序按「米」读出的 12.3）
        assert qty_and_source("烫金-布", CALC_INFO) == (1.0, "fallback")
        assert qty_and_source("帘头制作", CALC_INFO) == (1.0, "fallback")

    def test_missing_keys_source_is_fallback(self):
        assert _source("精裁-布", {}) == "fallback"

    def test_panels_and_set_count_are_pending_keys_not_engine_output(self):
        """冻结契约样例：set_count=1 在请求里，但「套」类仍标 fallback。

        理由：panels/set_count 是 routing.py 已登记的**待补键**（PANEL_KEYS/SET_KEYS 注释：
        引擎 build_quote 不产出）⇒ 请求里那个 1 与兜底 1 无从区分，不冒称「算料输出」。
        """
        assert _source("外帘装袋", {"set_count": 1}) == "fallback"
        assert _source("拼1次-布", {"panels": 2}) == "fallback"

    def test_hole_branch_three_way_labels(self):
        """「孔」分支三条子路径必须三态可分（① holes 直采 / ② 按米估算 / ③ 真兜底）。"""
        assert qty_and_source("打孔-布", {"holes": 72}) == (72.0, "holes")
        assert qty_and_source("打孔-布", {"fabric_meters": 12.3}) == (
            12.3 * HOLE_PER_METER, f"fabric_meters{HOLE_ESTIMATE_SUFFIX}",
        )
        assert qty_and_source("打孔-布", {"meters": 12.3}) == (
            12.3 * HOLE_PER_METER, f"meters{HOLE_ESTIMATE_SUFFIX}",
        )
        assert qty_and_source("打孔-布", {}) == (1.0, "fallback")

    def test_hole_estimate_is_not_reported_as_placeholder_fallback(self, client):
        """红证（② 支）：`calc_info={fabric_meters:12.3}` + 「孔」工序 ⇒ 值 = 12.3×6 孔、
        标签**不是** fallback（否则「有依据的估算」被说成「占位 1」，正是本单要治的误导）。

        判别性：把②错标 fallback（或错走真兜底 1.0）⇒ 本断言红。
        """
        expected = 12.3 * HOLE_PER_METER          # 12.3 米 × 每米 6 孔
        assert expected == pytest.approx(73.8)    # 行业口径实测值（现场核对一致）
        assert qty_and_source("打孔-布", {"fabric_meters": 12.3}) == (
            expected, f"fabric_meters{HOLE_ESTIMATE_SUFFIX}",
        )
        pos = _first_position(_post(client, [
            {**POSITION, "operations": ["打孔-布"], "calc_info": {"fabric_meters": 12.3}},
        ]))
        assert pos["qty_by_operation"] == {"打孔-布": expected}
        assert pos["qty_source_by_operation"] == {
            "打孔-布": f"fabric_meters{HOLE_ESTIMATE_SUFFIX}",
        }
        assert pos["qty_source_by_operation"]["打孔-布"] != "fallback"
