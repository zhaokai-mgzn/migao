# case_ids: CH-036, OR-032
"""`curtain_calc` 消费**本租户算料口径**（`craft_calc_configs`）—— issue #4922 的守卫。

## 病灶（本文件要钉住的形态）

商家在「工艺配置 → 算料配置」改口径（`per_fold_single` / `margin_*` / `min_fullness` /
`default_formula` / `hem_margin` / `meters_rounding_step`）后，**服务端下单路径读它**
（`CraftCalcClient#withTenantConfig` → `craftCalcConfigMapper.selectActiveByTenant`），
而米宝/小布的 `CurtainCalcTool.execute` **从不传 `config`** ⇒ 引擎回落模块级
`DEFAULT_CRAFT_CALC_CONFIG` ⇒ **同一张单两个米数/两个金额**（口径的每一项都直接改米数 = 改钱）。

## 判据（每条都独立可红，互不掩盖）

| # | 判据 | 红证形态（改动前） |
|---|---|---|
| 1 | 租户有配置行 ⇒ 工具米数 == 同一 config 直调 `build_quote`，且 **≠ 默认口径米数** | 改动前工具恒等于默认口径 ⇒ 第二条断言红 |
| 2 | 服务端明确「本租户无配置行」⇒ 输出与改动前**逐值相同**（引擎收到的 `config is None`） | 改动前也相同 ⇒ 本条是**零回归**锁（防「顺手把默认值显式发过去」） |
| 3 | 取配置失败 ⇒ **分两族**：服务端**答复了**读不通（4xx/5xx/形状漂移）= **fail-closed**（不算料 + 可行动话术）；服务端**没答**（不可达/熔断）= **显式降级 + 留痕**（默认口径 + `config_source` + 报价单 warning 明说） | 改动前根本不取配置 ⇒ 两族都恒 `success=True` 且无痕 ⇒ 红 |
| 4 | 口径**零自造**：引擎收到的 config 就是服务端那一份（键集不变），且规范化复用**唯一实现** | 改动前 `config is None`（recorder 捕获到 None）⇒ 红 |
| 5 | 同口径：同一 config + 同一入参 ⇒ 工具路径与内部试算端点路径米数逐值相等（**函数级**；服务端那一半的真栈覆盖见下方「已知缺口」） | 改动前工具路径用默认口径 ⇒ 红 |

## 已知缺口（如实登记，不粉饰）

- **判据 5 的覆盖现状（issue #4945 处 1，2026-09-26 更新 —— 原文那句「真栈形态在本机不可得」已不成立）**：
  · **服务端半边已升到真栈**（真库 + 真装配）：
    `backend/admin-api/src/test/java/com/migao/admin/service/CraftCalcConfigRealDbTest.java` 在一次性真 PG 上
    建 `craft_calc_configs` **真行** ⇒ 真 MyBatis 读（谓词 / 列名 / 软删过滤 / JSONB 解码）⇒ 真
    `toConfigMap()` ⇒ 真 `CraftCalcClient` **出参**逐值核对（另含「无配置行 ⇒ 请求体**没有** config 键」
    的零回归锁）。它跑在**既有**的 `admin-api-test` job 里 —— 该 job 已注入 `MIGAO_REQUIRE_REALDB=1`
    ⇒ 缺 PG 判**红**（不是 skip）；
  · **两侧必须是同一份 config，且有机器钉住**：本文件的 `TENANT_CONFIG_JSON` 与上面那份 Java 判据的
    声明**逐值一致性**由 `tests/unit_ci_workflows/test_craft_calc_config_contract.py` 的**判据 9** 看住
    （改一侧不改另一侧 ⇒ CI 必红）—— 否则「同一 config」只是账面成立；
  · **仍然不覆盖（本判据的残留降级，不许当已覆盖读）**：**跨进程那一跳**，以及「在两个活服务上跑一条
    判据、逐值比米数」这件事。PR 触发的 job 里**没有一条**同时起 `DB + admin-api + ai-agent` 的腿：
    `admin-api-test` 无 Python 运行时；`ci workflow helper unit tests` 只装 `pytest pyyaml`
    （连 `app.tools.curtain_calc` 都 import 不了 —— 它经 `app.tools.base` 依赖 pydantic）；
    唯一起双服务的是 `.github/workflows/post-deploy-eval.yml` 的 docker 栈，**手动触发 + 真实 LLM 档**
    （按 issue #4262 不得自动跑；本包也不得跑真实 LLM 评测）。
    ⇒ 「服务端发出去的 config == 库里那一行」已由那份真库判据覆盖，「同一 config ⇒ 工具路径 ≡
    内部试算端点路径」由本文件覆盖；两者**拼接起来**才等于判据 5 的真栈形态，而**拼接是论证，
    不是一次真跑**。
  · **重启条件（可执行）**：一旦出现一条**零 LLM** 的双服务腿（或在既有 docker 栈腿里加一个零 LLM 步骤），
    就把双路径判据接进去 —— 形态 = ① 经真 `PUT /api/admin/production/craft-calc-config` 写入本租户配置行
    ② 同一入参分别走 `POST /api/admin/orders/craft-calc`（`CraftCalcClient` 路径）与
    `CurtainCalcTool`（米宝工具路径）③ 断言 `fabric_meters` / `total` **逐值相等** ④「删掉配置行 ⇒
    两侧逐值回到默认口径 13.2 米」的零回归。缺口与重启条件同时登记在 issue #4945。
- 权限通路（`GET /api/admin/production/craft-calc-config` 的**读码**：issue #5291 起为方法级
  `production:view`，此前与写面同用类级 `processing:manage`）：
  携 `X-User-Id` 且命中本租户商户员工时走**真实角色**（`PermissionInterceptor#hasBypassRole` 旁路失效）
  ⇒ 不持 `production:view` 的岗位（如 `customer_service` / `sales` / `finance`）会拿到 403。
  本文件按「权限拒绝 = **终态** + 可行动话术」钉住（issue #4103 的 P0 形态：拒绝被当成参数问题
  ⇒ agent 反复重试烧轮次）。**该岗位面的能力影响已登记在 PR/报告，不在本文件内放宽**。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.api.internal import _normalize_craft_calc_config
from app.tools import curtain_calc as cc
from app.tools.base import NON_RETRYABLE_ERROR_CODES, ToolContext
from app.tools.curtain_calc import (
    DEFAULT_CRAFT_CALC_CONFIG,
    CurtainCalcTool,
    build_quote,
)

TENANT_ID = 7
USER_ID = "u-4922"

#: 入参锚点（6.6m 窗 / 2.5m 高 / 打孔 / 单开 / 门幅 2.8）：默认口径 = **13.2 米**（`6.6 × 2`）。
#: ⚠️ issue #5030（2026-09-21 用户裁定）：订单宽 = **净窗宽** ⇒ 宽方向没有左右覆盖余量
#: ⇒ 旧读数 `(6.6+0.3)×2 = 13.8` 已退场；**本文件守的东西一字未动**（租户配置真的被消费）。
ANCHOR: Dict[str, Any] = dict(window_width=6.6, window_height=2.5, fabric_price=30.0)

#: 服务端返回的**租户配置**（形状 = `GET /api/admin/production/craft-calc-config` 的 `data.config`；
#: JSON 对象键恒为字符串 ⇒ `per_fold_mixed_times` 的键是 `"1"` / `"2"`）。
#: 与引擎默认值的两处**实质不同**：`default_formula`（pleat → fullness）、`meters_rounding_step`（0.1 → 0.5）
#: ⇒ 米数 **13.2 → 13.5**（不是「相同数字换了个来源」，那样判据 1 是恒真的空断言）。
TENANT_CONFIG_JSON: Dict[str, Any] = {
    "per_fold_single": 0.25,
    "per_fold_mixed_times": {"1": 0.65, "2": 1.2},
    "margin_single": 0.2,
    "margin_multi": 0.3,
    "min_fullness": 1.5,
    "tiers": {
        "standard": {"fullness": 2.0, "label": "标准工艺"},
        "economy": {"fullness": 1.8, "label": "经济工艺"},
    },
    "default_formula": "fullness",
    "hem_margin": 0.3,
    "meters_rounding_step": 0.5,
}

#: 服务端响应信封（`ApiResponse.success` 形态：`{success, data, error}`）。
STORED_RESPONSE: Dict[str, Any] = {
    "success": True,
    "data": {"source": "stored", "config": TENANT_CONFIG_JSON},
}
NO_ROW_RESPONSE: Dict[str, Any] = {
    "success": True,
    # 缺行时服务端回的是**引擎默认值** + source='default'（`CraftCalcConfigService#get`）；
    # 工具侧**不消费**这份 config（缺行 ⇒ 不传 config，与 CraftCalcClient 逐字同口径）。
    "data": {"source": "default", "config": dict(DEFAULT_CRAFT_CALC_CONFIG)},
}
DENIED_RESPONSE: Dict[str, Any] = {
    "success": False,
    "data": None,
    "error": {"code": "PERMISSION_DENIED", "message": "权限不足，需要权限: processing:manage",
              "details": [{"field": "requiredPermission", "message": "processing:manage"}]},
    "suggestion": None,
}


class _FakeAdminApi:
    """`AdminApiClient` 替身：只记录出参、回一份可控响应（**不发真实 HTTP**）。"""

    def __init__(self, response: Optional[Dict[str, Any]] = None, exc: Optional[Exception] = None):
        self.response = response
        self.exc = exc
        self.calls: List[Dict[str, Any]] = []

    async def get(self, path: str, params=None, tenant_id=None, user_id=None, headers=None):
        self.calls.append({"path": path, "tenant_id": tenant_id, "user_id": user_id})
        if self.exc is not None:
            raise self.exc
        return self.response


def _ctx() -> ToolContext:
    """上下文：**商户员工**身份（`admin` ⇒ 持 `*`）—— 与米宝 B 端主路径同形。"""
    return ToolContext(tenant_id=TENANT_ID, user_id=USER_ID, role="admin", permissions=["*"])


def _use(monkeypatch, fake: _FakeAdminApi) -> _FakeAdminApi:
    monkeypatch.setattr(cc, "get_admin_api_client", lambda: fake)
    return fake


async def _run(monkeypatch, fake: _FakeAdminApi, **params):
    _use(monkeypatch, fake)
    return await CurtainCalcTool().execute(_ctx(), **{**ANCHOR, **params})


def _same_metrics(actual: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """逐值比对**引擎输出**（`config_source` 是本单**新增**的留痕键，不在比对集内）。"""
    assert {k: v for k, v in actual.items() if k != "config_source"} == expected


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1 —— 接线（红证：改动前必红）
# ══════════════════════════════════════════════════════════════════════════════

async def test_tenant_config_reaches_build_quote(monkeypatch):
    fake = _FakeAdminApi(STORED_RESPONSE)
    result = await _run(monkeypatch, fake)

    assert result.success is True, result.message
    # ① 出参：带本租户 id + 调用方用户 id（与 `processing_item_query` 等既有工具**同形**）
    assert fake.calls == [{
        "path": "/api/admin/production/craft-calc-config",
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
    }]
    # ② 米数 == 同一 config（经**唯一**规范化实现）直调引擎
    expected = build_quote(
        window_width=6.6, window_height=2.5, mounting="eyelet", fabric_price=30.0,
        config=_normalize_craft_calc_config(TENANT_CONFIG_JSON),
    )
    assert result.data is not None
    assert result.data["fabric_meters"] == expected["fabric_meters"] == 13.5
    assert result.data["total"] == expected["total"]
    # ③ **不是**默认口径（默认 = 韩褶公式 + 1 位进位 ⇒ **13.2** 米）—— 这一条才是「接线生效」的红证
    baseline = build_quote(window_width=6.6, window_height=2.5, mounting="eyelet", fabric_price=30.0)
    assert baseline["fabric_meters"] == 13.2
    assert result.data["fabric_meters"] != baseline["fabric_meters"]
    # ④ 留痕：配置来源可观测
    assert result.data["config_source"] == "tenant"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2 —— 零回归：本租户无配置行 ⇒ 与改动前逐值相同
# ══════════════════════════════════════════════════════════════════════════════

async def test_no_config_row_is_zero_regression(monkeypatch):
    result = await _run(monkeypatch, _FakeAdminApi(NO_ROW_RESPONSE))

    assert result.success is True, result.message
    assert result.data is not None
    baseline = build_quote(window_width=6.6, window_height=2.5, mounting="eyelet", fabric_price=30.0)
    _same_metrics(result.data, baseline)
    assert result.data["fabric_meters"] == 13.2
    assert result.data["config_source"] == "default(no_row)"
    # 摘要/话术也不因本单而变（缺行 = 商家没配口径，没有任何新信息要对顾客说）
    assert result.summary == (
        f"算料结果：{baseline['fabric_meters']}米，总价¥{baseline['total']} "
        f"（面料¥{baseline['fabric_cost']}+加工¥{baseline['processing_cost']}"
        f"+辅料¥{baseline['accessory_cost']}+安装¥{baseline['install_cost']}）"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3 —— 失败语义：服务端「答复了」⇒ fail-closed；服务端「没答」⇒ 显式降级 + 留痕
# ══════════════════════════════════════════════════════════════════════════════

def _status_error(status: int) -> httpx.HTTPStatusError:
    """构造「服务端**答复了**错误状态」（5xx）的异常 —— `AdminApiClient` 对 5xx 正是抛它。"""
    request = httpx.Request("GET", f"http://admin-api:8080{cc.TENANT_CRAFT_CALC_CONFIG_PATH}")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status} error", request=request, response=response)


async def test_answered_but_broken_is_fail_closed(monkeypatch):
    """服务端**答复了**（5xx / 响应非 JSON）⇒ fail-closed：不给任何米数/金额 + 可行动话术。

    口径理由：服务端可达却读不通时，服务端下单路径（直读 `craft_calc_configs` 的
    `CraftCalcClient`）**仍然可用** ⇒ 按默认口径报数会真的落地成「米宝一个数、落库另一个数」。
    """
    result = await _run(monkeypatch, _FakeAdminApi(exc=_status_error(503)))

    assert result.success is False
    assert result.data is None                      # 不给任何米数/金额（fail-closed 的形态判据）
    assert result.error_code == "CRAFT_CALC_CONFIG_UNAVAILABLE"
    assert result.message and "不报价" in result.message
    assert result.suggestion and len(result.suggestion) > 10


async def test_permission_denied_is_terminal_with_actionable_suggestion(monkeypatch):
    """403 ⇒ 码 = `PERMISSION_DENIED`（∈ 非重试集合）⇒ **终态**，且话术给出去哪开通（issue #4103）。"""
    result = await _run(monkeypatch, _FakeAdminApi(DENIED_RESPONSE))

    assert result.success is False
    assert result.data is None
    assert result.error_code == "PERMISSION_DENIED"
    assert result.error_code in NON_RETRYABLE_ERROR_CODES  # 消费方据此抑制重试
    assert "不要重试" in result.suggestion
    assert "processing:manage" in result.suggestion


async def test_malformed_success_response_is_fail_closed(monkeypatch):
    """`success=true` 但缺 `data.config`（形状漂移）⇒ 也算取配置失败，**不得**按默认口径算。"""
    bad = {"success": True, "data": {"source": "stored"}}
    result = await _run(monkeypatch, _FakeAdminApi(bad))

    assert result.success is False
    assert result.data is None
    assert result.error_code == "CRAFT_CALC_CONFIG_UNAVAILABLE"


@pytest.mark.parametrize(
    "exc,label",
    [
        (httpx.ConnectError("connection refused"), "unreachable"),
        (httpx.ReadTimeout("timed out"), "timeout"),
    ],
)
async def test_transport_failure_degrades_with_trace(monkeypatch, exc, label):
    """服务端**没答复**（DNS/连接/超时）⇒ 显式降级 + 留痕：照常算料（默认口径），但**不静默**。

    口径理由：此刻 admin-api 整体不可用 ⇒ 服务端下单路径同样不可用
    （`CraftCalcClient` 对端不可达是 422 fail-closed）⇒「米宝一个数、落库另一个数」无法落地；
    且纯计算工具在离线/单测环境（admin-api 恒不可达）不该整条失效 —— 既有 71 条
    `tests/test_curtain_calc.py` 用例都不 mock admin-api，fail-closed 会让它们全红。
    """
    result = await _run(monkeypatch, _FakeAdminApi(exc=exc))

    assert result.success is True, result.message
    assert result.data is not None
    assert result.data["config_source"] == "default(fetch_failed)"
    assert result.data["fabric_meters"] == 13.2          # 引擎默认口径（issue #5030：6.6 × 2）
    # **不静默**：降级必须明说（报价单 warning 随卡片/模型一起回给商家）
    assert "算料口径" in result.data["warning"]
    assert "默认口径" in result.data["warning"]


async def test_circuit_open_degrades_with_trace(monkeypatch):
    """熔断（`AdminApiClient` 认定端点不可用，连调用都不发）⇒ 与「不可达」同族：降级 + 留痕。"""
    open_envelope = {"success": False, "error": {"code": "CIRCUIT_OPEN", "message": "服务暂时不可用"},
                     "data": None}
    result = await _run(monkeypatch, _FakeAdminApi(open_envelope))

    assert result.success is True, result.message
    assert result.data is not None
    assert result.data["config_source"] == "default(fetch_failed)"
    assert "算料口径" in result.data["warning"]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4 —— 口径零自造（只透传服务端那一份，且缺行时**不传**）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "response,expected_config",
    [
        (STORED_RESPONSE, _normalize_craft_calc_config(TENANT_CONFIG_JSON)),
        (NO_ROW_RESPONSE, None),
    ],
    ids=["stored-config-passthrough", "no-row-config-is-none"],
)
async def test_engine_receives_server_config_verbatim(monkeypatch, response, expected_config):
    seen: Dict[str, Any] = {}
    real_build_quote = cc.build_quote

    def recorder(**kwargs):
        seen.update(kwargs)
        return real_build_quote(**kwargs)

    _use(monkeypatch, _FakeAdminApi(response))
    monkeypatch.setattr(cc, "build_quote", recorder)
    result = await CurtainCalcTool().execute(_ctx(), **ANCHOR)

    assert result.success is True, result.message
    assert seen["config"] == expected_config
    if expected_config is not None:
        # 键集一字不多、一字不少（工具**不得**补默认值/改名 —— 那是第二份口径）
        assert set(seen["config"]) == set(TENANT_CONFIG_JSON)
        # 规范化来自**唯一实现**（`per_fold_mixed_times` 的字符串键 → 正整数键），本模块不自造第二份
        assert set(seen["config"]["per_fold_mixed_times"]) == {1, 2}
    assert not hasattr(cc, "_normalize_craft_calc_config"), "第二份规范化实现"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5 —— 同口径（纯函数级；真栈缺口见文件头）
# ══════════════════════════════════════════════════════════════════════════════

def test_permission_face_is_bounded_by_the_tool_role_gate():
    """本条锚定「403 那一族**只**可能命中谁」——它是上一条 fail-closed 裁定的前提。

    `CurtainCalcTool.allowed_roles`（工具层角色闸，`check_permission`）只放行
    `customer` / `admin` / `agent` / `tenant_admin`：
      · `admin`（米宝 B 端主用户）在 admin-api 恒持 `*` ⇒ 读配置**不会** 403；
      · C 端（`customer`/`agent`）不是本租户商户员工 ⇒ `ServiceTokenFilter` 回退内部服务身份 ⇒ 读配置**不会** 403；
      · `operator` / `customer_service` / `sales` / `finance` **进不了本工具**（角色闸先拒），故它们的
        生产域读码（`production:view`，issue #5291）持有与否对本工具无影响；
      · 只剩 legacy `tenant_admin`（admin-api 无该角色/无权限映射 ⇒ 所有 `@RequirePermission` 都 403，
        跨服务口径断裂已由 issue #4106 登记）与自定义同名角色会走到 403 那一支。

    ⇒ 「403 ⇒ fail-closed」不会把米宝报数能力砍掉一个默认岗位（放闸前先看这一条）。
    """
    tool = CurtainCalcTool()
    for role in ("admin", "customer", "agent"):
        assert tool.check_permission(
            ToolContext(tenant_id=TENANT_ID, user_id=USER_ID, role=role, permissions=[])) is True
    for role in ("operator", "customer_service", "sales", "finance"):
        assert tool.check_permission(
            ToolContext(tenant_id=TENANT_ID, user_id=USER_ID, role=role, permissions=[])) is False


async def test_meters_match_internal_endpoint_path(monkeypatch):
    """同一租户 + 同一入参 ⇒ 工具路径 ≡ 内部试算端点路径（`CraftCalcClient` 走的那条）的米数。

    端点侧入参形状照 `app/api/internal.py` 的 `craft_calc`（width/height/mounting/open_count/
    fabric_width/craft_tier/style/special_options/formula/craft/has_pattern/pattern_repeat）。
    """
    result = await _run(monkeypatch, _FakeAdminApi(STORED_RESPONSE),
                        mounting="eyelet", open_count=1, fabric_width=2.8)
    assert result.success is True, result.message

    endpoint_side = build_quote(
        window_width=6.6, window_height=2.5, mounting="eyelet", open_count=1, fabric_width=2.8,
        config=_normalize_craft_calc_config(TENANT_CONFIG_JSON),
    )
    assert result.data is not None
    assert result.data["fabric_meters"] == endpoint_side["fabric_meters"] == 13.5
    assert result.data["formula_used"] == endpoint_side["formula_used"]
    # 反向：两侧若各自回落默认口径会得 13.2 ⇒ 本判据不是恒真
    assert endpoint_side["fabric_meters"] != build_quote(
        window_width=6.6, window_height=2.5, mounting="eyelet", open_count=1,
        fabric_width=2.8)["fabric_meters"]
