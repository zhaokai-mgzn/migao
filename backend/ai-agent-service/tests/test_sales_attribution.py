"""sales_attribution — 商品归因：数字与排名由工具确定性计算（issue #8157）

口径（只给数字与排名，不给结论 / 建议）：
- 窗口 = 两个**等长且紧邻**的日期区间（本期 = 最近 days 天 / 上期 = 其前 days 天），
  与 `dashboard_stats(action=trend_compare)` 同一套 `app/utils/compare.py` 口径
  （`finite_number` / `delta_pct` / `MAX_PERIOD_DAYS`）；
- 按 ``product_name`` 聚合销售额（``items[].amount`` 之和）与订单数；
- 上期为 0 ⇒ ``delta_pct = None`` + ``previous_is_zero = True``（**不得** Infinity/NaN）；
- 分页上限显式（5 页 × 200 条/期）：被截断 ⇒ ``window.truncated = True`` + ``page_cap``；
- 结构异常（缺 ``items`` / 金额非数值 / 品名为空）⇒ 失败（**不得**当 0 参与排名）。

权限面（判据 = `tests/unit_ci_workflows/test_agent_permission_parity.py`）：
- ``required_permissions = ["order:list"]`` ≡ 唯一端点 ``GET /api/admin/orders`` 的生效码，
  **不**依赖任何跨码例外；本文件另有一条防回潮判据钉住「dashboard_stats 不再读订单」。

真值面（读源复核）：
- ``GET /api/admin/orders`` 的日期参数是 ``startDate`` / ``endDate``（``YYYY-MM-DD``），
  ``OrderService#resolveListWindow`` 把 ``endDate`` 当**含当日**（半开区间
  ``[startDate 00:00, endDate+1 00:00)``，business clock 时区）；
- 响应 ``data.items[]`` = ``OrderListResponse``，其 ``items[]`` = ``OrderItemBrief``
  （``productName`` / ``amount`` = unitPrice×quantity / ``subtotal`` 可能为 null）。
"""
# case_ids: DA-027

import datetime as _dt
import json
import math

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.dashboard_stats import DashboardStatsTool
from app.tools.sales_attribution import (
    ATTRIBUTION_PAGE_CAP,
    MAX_ATTRIBUTION_PAGES,
    MAX_ATTRIBUTION_TOP,
    SalesAttributionTool,
)
from app.utils.compare import MAX_PERIOD_DAYS
from tests import tool_http_attribution as attribution

# 钉住「今天」⇒ 窗口边界是确定值：本期 2026-10-23~2026-10-29 / 上期 2026-10-16~2026-10-22
END = _dt.date(2026, 10, 29)
CURRENT_START = "2026-10-23"
CURRENT_END = "2026-10-29"
PREVIOUS_START = "2026-10-16"
PREVIOUS_END = "2026-10-22"


def _order(no, *lines):
    """一条订单：lines = (product_name, amount) 若干行。"""
    return {
        "orderNo": no,
        "items": [{"productName": name, "amount": amount} for name, amount in lines],
    }


def _page(items, total=None):
    return {"items": list(items), "total": len(items) if total is None else total}


def _install(mock_get_client, pages_by_window):
    """按窗口（startDate）分发响应；值为 dict ⇒ 单页，为 list ⇒ 逐页（page 从 1 起）。"""
    client = AsyncMock()

    async def fake_get(path, **kwargs):
        assert path == "/api/admin/orders", path
        params = kwargs.get("params") or {}
        window = pages_by_window.get(params.get("startDate"))
        assert isinstance(window, (dict, list)), (
            f"未预期的窗口 startDate={params.get('startDate')!r}"
        )
        if isinstance(window, dict):
            return {"success": True, "data": window}
        return {"success": True, "data": window[int(params.get("page", 1)) - 1]}

    client.get = AsyncMock(side_effect=fake_get)
    mock_get_client.return_value = client
    return client


def _entry_names(result):
    entries = result.data["top_up"] + result.data["top_down"]
    return [entry["product_name"] for entry in entries]


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    """窗口右端钉成 END（不打真实时钟）——否则 8 天后本文件会自己变红。"""
    monkeypatch.setattr("app.tools.sales_attribution._today", lambda: END)


@pytest.fixture
def tool():
    return SalesAttributionTool()


@pytest.fixture
def ctx():
    """持 `order:list` 的商户员工（与 `OrderController#getOrders` 的生效码一致）。"""
    return ToolContext(
        tenant_id=1, user_id="op_001", session_id="s",
        role="operator", permissions=["order:list"],
    )


def _tool_endpoints(module_path: str):
    """复用仓内静态归属机具：`app/tools/<file>` 的 HTTP 调用点 → (verb, 归一化端点)。"""
    return {(call.method, call.endpoint) for call in attribution.tool_calls()
            if call.file == module_path}


class TestSalesAttributionDeclaration:
    """工具声明：名字 / 只读 / 权限码 / 参数契约"""

    def test_metadata_and_permissions(self, tool):
        assert tool.name == "sales_attribution"
        assert tool.read_only is True
        assert tool.destructive is False
        # 与唯一端点 `GET /api/admin/orders` 的生效码同码（判据 2 的前提）
        assert tool.required_permissions == ["order:list"]
        # 参数契约：每期天数默认 7（上限 = 与环比同一份 30）；涨跌榜默认 5 / 上限 10
        days_schema = tool.parameters["properties"]["days"]
        assert days_schema["default"] == 7
        assert days_schema["maximum"] == MAX_PERIOD_DAYS
        top_schema = tool.parameters["properties"]["top"]
        assert top_schema["default"] == 5
        assert top_schema["minimum"] == 1
        assert top_schema["maximum"] == MAX_ATTRIBUTION_TOP


class TestToolPermissionBoundary:
    """判据 2 侧的防回潮：工具码 ≡ 端点码；归因不再是 dashboard_stats 的 action"""

    def test_sales_attribution_reads_only_order_list_endpoint(self):
        assert _tool_endpoints("app/tools/sales_attribution.py") == {("GET", "/api/admin/orders")}

    def test_dashboard_stats_no_longer_reads_orders(self):
        endpoints = _tool_endpoints("app/tools/dashboard_stats.py")
        assert endpoints, "解析面为空 —— 判据会退化成空断言"
        paths = {path for _verb, path in endpoints}
        assert "/api/admin/orders" not in paths, (
            "dashboard_stats 又调了订单列表端点 ⇒ 工具码 dashboard:view ≠ 端点码 order:list"
            "（权限对账判据 2 会红）；商品归因必须留在独立工具 sales_attribution 里"
        )
        # action 面同口径防回潮（把归因塞回看板会同时破坏权限对账与参数契约）
        assert "product_attribution" not in DashboardStatsTool.parameters["properties"]["action"]["enum"]
        from app.tools.dashboard_stats import VALID_ACTIONS

        assert "product_attribution" not in VALID_ACTIONS


class TestSalesAttributionAggregation:
    """聚合正确：同商品多单 / 跨窗口商品 / 新品 / 消失品 ⇒ 逐条 current/previous/delta/delta_pct"""

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_two_windows_aggregate_per_product(self, mock_get_client, tool, ctx):
        client = _install(mock_get_client, {
            CURRENT_START: _page([
                # 同一商品跨两单 ⇒ 销售额相加、订单数=2
                _order("ORD-1001", ("棉麻窗帘A", 120.5), ("遮光窗帘B", 50)),
                _order("ORD-1002", ("棉麻窗帘A", 200)),
                # 新品：上期不存在
                _order("ORD-1003", ("新品C", 80)),
            ]),
            PREVIOUS_START: _page([
                _order("ORD-0901", ("棉麻窗帘A", 420.5)),
                # 遮光窗帘B 两期都有且相等 ⇒ delta=0，不进涨跌榜
                _order("ORD-0902", ("遮光窗帘B", 50), ("停产D", 120)),
            ]),
        })

        result = await tool.execute(context=ctx, days=7)

        assert result.success is True, result.error
        data = result.data
        # 总量：本期 320.5+50+80 / 上期 420.5+50+120
        assert data["current_total"] == 450.5
        assert data["previous_total"] == 590.5
        assert data["delta"] == -140.0
        assert data["delta_pct"] == -23.71           # round(-140/590.5*100, 2)
        assert data["previous_is_zero"] is False
        assert data["top"] == 5
        # 涨榜：只有新品（delta=+80），上期为 0 ⇒ delta_pct 为 null（不是 200%）
        assert data["top_up"] == [{
            "product_name": "新品C",
            "current": 80.0,
            "previous": 0.0,
            "delta": 80.0,
            "delta_pct": None,
            "orders": 1,
        }]
        # 跌榜：按 delta 升序（最负在前）
        assert data["top_down"] == [
            {
                "product_name": "停产D",
                "current": 0.0,
                "previous": 120.0,
                "delta": -120.0,
                "delta_pct": -100.0,
                "orders": 0,
            },
            {
                "product_name": "棉麻窗帘A",
                "current": 320.5,
                "previous": 420.5,
                "delta": -100.0,
                "delta_pct": -23.78,
                "orders": 2,
            },
        ]
        # delta=0 的商品不进任何一榜（涨跌榜不是全量回显）
        assert "遮光窗帘B" not in _entry_names(result)
        # 窗口元信息：等长、紧邻、含当日
        assert data["window"]["current"] == {
            "start": CURRENT_START, "end": CURRENT_END, "days": 7,
        }
        assert data["window"]["previous"] == {
            "start": PREVIOUS_START, "end": PREVIOUS_END, "days": 7,
        }
        assert data["window"]["truncated"] is False
        assert data["window"]["page_cap"] == ATTRIBUTION_PAGE_CAP
        # 读源口径：日期走 startDate/endDate，一次取到取满（size=200、page=1 起）
        current_calls = [
            call for call in client.get.call_args_list
            if (call.kwargs.get("params") or {}).get("startDate") == CURRENT_START
        ]
        assert len(current_calls) == 1
        assert current_calls[0].kwargs["params"] == {
            "page": 1,
            "size": ATTRIBUTION_PAGE_CAP // MAX_ATTRIBUTION_PAGES,
            "startDate": CURRENT_START,
            "endDate": CURRENT_END,
        }

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_top_limit_applies_to_both_lists(self, mock_get_client, tool, ctx):
        _install(mock_get_client, {
            CURRENT_START: _page([
                _order("C1", ("涨一", 10)), _order("C2", ("涨二", 20)), _order("C3", ("涨三", 30)),
            ]),
            PREVIOUS_START: _page([
                _order("P1", ("跌一", 10)), _order("P2", ("跌二", 20)), _order("P3", ("跌三", 30)),
            ]),
        })

        result = await tool.execute(context=ctx, days=7, top=2)

        assert result.success is True, result.error
        data = result.data
        assert data["top"] == 2
        # 涨：delta 降序 ⇒ 涨三(+30) / 涨二(+20)
        assert [e["product_name"] for e in data["top_up"]] == ["涨三", "涨二"]
        # 跌：delta 升序 ⇒ 跌三(-30) / 跌二(-20)
        assert [e["product_name"] for e in data["top_down"]] == ["跌三", "跌二"]
        # `orders` = **本期**含该商品的订单数 ⇒ 消失品（只在上期）为 0
        assert all(entry["orders"] == 1 for entry in data["top_up"])
        assert all(entry["orders"] == 0 for entry in data["top_down"])


class TestSalesAttributionZeroBaseline:
    """上期为 0 ⇒ delta_pct=null + previous_is_zero（不得 Infinity/NaN）"""

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_previous_zero_yields_null_pct(self, mock_get_client, tool, ctx):
        _install(mock_get_client, {
            CURRENT_START: _page([_order("ORD-1", ("棉麻窗帘A", 100))]),
            PREVIOUS_START: _page([], total=0),      # 上期一单都没有
        })

        result = await tool.execute(context=ctx, days=7)

        assert result.success is True, result.error
        data = result.data
        assert data["current_total"] == 100.0
        assert data["previous_total"] == 0
        assert data["previous_is_zero"] is True
        assert data["delta"] == 100.0
        assert data["delta_pct"] is None
        assert data["top_up"][0]["delta_pct"] is None
        # 全字段有限：json.dumps 会把 inf/nan 写成 Infinity/NaN ⇒ 这里一并钉住
        for key in ("current_total", "previous_total", "delta"):
            value = data[key]
            assert isinstance(value, (int, float)) and math.isfinite(value), f"{key}={value!r}"
        for entry in data["top_up"] + data["top_down"]:
            for key in ("current", "previous", "delta"):
                assert math.isfinite(entry[key]), f"{entry['product_name']}.{key}={entry[key]!r}"
        dumped = json.dumps(data, ensure_ascii=False)
        assert "Infinity" not in dumped and "NaN" not in dumped


class TestSalesAttributionTruncation:
    """分页被上限截断 ⇒ truncated=true + page_cap 给出（不许静默丢数据后给出完整排名）"""

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_page_cap_is_disclosed(self, mock_get_client, tool, ctx):
        page_size = ATTRIBUTION_PAGE_CAP // MAX_ATTRIBUTION_PAGES
        # 服务端 total=1500 > 1000（上限）⇒ 取满 5 页后必须披露截断
        full_pages = [
            _page(
                [_order(f"C{page}_{i}", ("棉麻窗帘A", 10.0)) for i in range(page_size)],
                total=1500,
            )
            for page in range(1, MAX_ATTRIBUTION_PAGES + 1)
        ]
        client = _install(mock_get_client, {
            CURRENT_START: full_pages,
            PREVIOUS_START: _page([], total=0),
        })

        result = await tool.execute(context=ctx, days=7)

        assert result.success is True, result.error
        data = result.data
        assert data["window"]["truncated"] is True
        assert data["window"]["page_cap"] == ATTRIBUTION_PAGE_CAP
        assert "分页上限" in result.message
        # 只取了 5 页（没有继续翻到 8 页去凑 1500 条）
        current_calls = [
            call for call in client.get.call_args_list
            if (call.kwargs.get("params") or {}).get("startDate") == CURRENT_START
        ]
        assert len(current_calls) == MAX_ATTRIBUTION_PAGES
        assert [call.kwargs["params"]["page"] for call in current_calls] == [1, 2, 3, 4, 5]
        # 已取到的 1000 单照实参与排名（不是 0）
        assert data["top_up"][0]["orders"] == ATTRIBUTION_PAGE_CAP
        assert data["current_total"] == 10.0 * ATTRIBUTION_PAGE_CAP

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_within_cap_is_not_flagged(self, mock_get_client, tool, ctx):
        _install(mock_get_client, {
            CURRENT_START: _page([_order("ORD-1", ("棉麻窗帘A", 100))], total=1),
            PREVIOUS_START: _page([_order("ORD-0", ("棉麻窗帘A", 90))], total=1),
        })

        result = await tool.execute(context=ctx, days=7)

        assert result.success is True, result.error
        assert result.data["window"]["truncated"] is False


class TestSalesAttributionFailClosed:
    """结构异常 ⇒ 失败（不得当 0 参与排名），且失败不返回 data"""

    @pytest.mark.parametrize("bad_data", [
        {"total": 1},                                              # 缺 items
        {"items": "oops", "total": 1},                             # items 不是数组
        {"items": [], "total": None},                              # 缺 total（算不出是否有下一页）
        {"items": [], "total": "3"},                               # total 非数值
        [],                                                        # data 不是对象
    ])
    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_bad_page_payload_is_failure(self, mock_get_client, tool, ctx, bad_data):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": bad_data})
        mock_get_client.return_value = client

        result = await tool.execute(context=ctx, days=7)

        assert result.success is False
        assert result.error
        assert result.suggestion
        assert not result.data, f"失败却回传了 data={result.data!r}"

    @pytest.mark.parametrize("bad_item", [
        {"productName": "棉麻窗帘A", "amount": "abc"},             # 金额非数值
        {"productName": "棉麻窗帘A", "amount": float("inf")},       # 非有限
        {"productName": "棉麻窗帘A", "amount": True},               # bool 不是金额
        {"productName": "棉麻窗帘A"},                              # 金额/单价/数量全缺
        {"productName": "", "amount": 10},                        # 品名为空（无法归因）
        {"amount": 10},                                           # 缺品名
        "not-a-dict",                                             # 明细不是对象
    ])
    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_bad_item_is_failure(self, mock_get_client, tool, ctx, bad_item):
        _install(mock_get_client, {
            CURRENT_START: _page([{"orderNo": "ORD-1", "items": [bad_item]}], total=1),
            PREVIOUS_START: _page([], total=0),
        })

        result = await tool.execute(context=ctx, days=7)

        assert result.success is False
        assert result.error
        assert result.suggestion
        assert not result.data, f"失败却回传了 data={result.data!r}"

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_admin_api_failure_is_passed_through(self, mock_get_client, tool, ctx):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "PERMISSION_DENIED", "message": "缺少订单查看权限"},
        })
        mock_get_client.return_value = client

        result = await tool.execute(context=ctx, days=7)

        assert result.success is False
        assert result.error_code == "PERMISSION_DENIED"
        assert result.suggestion
        assert not result.data


class TestSalesAttributionDiscrimination:
    """判别力自证：换个确定不存在的商品名 ⇒ 原条目消失（证明不是全量回显）"""

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_entry_follows_the_input_name(self, mock_get_client, tool, ctx):
        _install(mock_get_client, {
            CURRENT_START: _page([_order("ORD-1", ("棉麻窗帘A", 100))]),
            PREVIOUS_START: _page([], total=0),
        })
        baseline = await tool.execute(context=ctx, days=7)
        assert baseline.success is True, baseline.error
        assert _entry_names(baseline) == ["棉麻窗帘A"]

        # 只改商品名 ⇒ 旧名必须消失、新名必须出现（不是把固定名单回显出来）
        _install(mock_get_client, {
            CURRENT_START: _page([_order("ORD-1", ("绝不存在的商品ZZZ", 100))]),
            PREVIOUS_START: _page([], total=0),
        })
        renamed = await tool.execute(context=ctx, days=7)

        assert renamed.success is True, renamed.error
        assert _entry_names(renamed) == ["绝不存在的商品ZZZ"]
        assert "棉麻窗帘A" not in json.dumps(renamed.data, ensure_ascii=False)


class TestSalesAttributionWindow:
    """窗口口径：days 超上限截断并披露；窗口等长紧邻"""

    @patch("app.tools.sales_attribution.get_admin_api_client")
    async def test_over_cap_discloses_actual_window(self, mock_get_client, tool, ctx):
        _install(mock_get_client, {
            (END - _dt.timedelta(days=MAX_PERIOD_DAYS - 1)).isoformat(): _page([]),
            (END - _dt.timedelta(days=2 * MAX_PERIOD_DAYS - 1)).isoformat(): _page([]),
        })

        result = await tool.execute(
            context=ctx, days=MAX_PERIOD_DAYS + 15,
        )

        assert result.success is True, result.error
        data = result.data
        assert data["window_capped"] is True
        assert data["requested_days"] == MAX_PERIOD_DAYS + 15
        assert data["days"] == MAX_PERIOD_DAYS
        assert data["window"]["current"] == {
            "start": (END - _dt.timedelta(days=MAX_PERIOD_DAYS - 1)).isoformat(),
            "end": END.isoformat(),
            "days": MAX_PERIOD_DAYS,
        }
        assert "截断" in result.message
