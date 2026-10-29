"""dashboard_stats(action=trend_compare) — 环比对比由工具确定性计算（issue #8120）

口径（只做算术，不做业务解释）：
- 取 2×days 天趋势序列 ⇒ 工具内切成「本期（最近 days 天）/ 上期（其前 days 天）」；
- 上期为 0 ⇒ ``delta_pct = None`` + ``previous_is_zero = True``（**不得** Infinity/NaN）；
- 窗口超上限 ⇒ ``window_capped = True`` + 实际窗口（不许悄悄退化）；
- 服务端结构异常 ⇒ 失败 + 明确 suggestion（不得 success + 空对象）。

真值面（读源复核）：admin-api ``DashboardController#getOrderTrend`` 返回
``List<OrderTrendPointResponse>``，逐日字段 = ``date``（YYYY-MM-DD）/ ``orders``（订单数）/
``amount``（金额，long），且**逐日补零**（无数据日也在序列里）。
"""
# case_ids: DA-025

import datetime as _dt
import json
import math

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.dashboard_stats import (
    MAX_PERIOD_DAYS,
    MAX_WINDOW_DAYS,
    DashboardStatsTool,
)

END = _dt.date(2026, 10, 29)


def _series(n: int, orders_at=lambda i: i + 1, amount_at=None):
    """构造升序趋势序列（date/orders/amount），最后一天 = END。"""
    start = END - _dt.timedelta(days=n - 1)
    amount_at = amount_at or (lambda i: orders_at(i) * 100)
    return [
        {
            "date": (start + _dt.timedelta(days=i)).isoformat(),
            "orders": orders_at(i),
            "amount": amount_at(i),
        }
        for i in range(n)
    ]


def _install(mock_get_client, data):
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": data})
    mock_get_client.return_value = client
    return client


@pytest.fixture
def tool():
    return DashboardStatsTool()


@pytest.fixture
def ctx():
    """持 `dashboard:view` 的商户员工（与 DashboardController 类级权限码一致）。"""
    return ToolContext(
        tenant_id=1, user_id="op_001", session_id="s",
        role="operator", permissions=["dashboard:view"],
    )


class TestTrendCompareDeclaration:
    """action 已声明（枚举 / VALID_ACTIONS 双向一致）"""

    def test_action_declared(self, tool):
        from app.tools.dashboard_stats import VALID_ACTIONS

        assert "trend_compare" in VALID_ACTIONS
        enum = tool.parameters["properties"]["action"]["enum"]
        assert "trend_compare" in enum
        # 参数契约：days 默认 7（本期/上期各 7 天）
        assert tool.parameters["properties"]["days"]["default"] == 7


class TestTrendCompareSplit:
    """本期 / 上期切分（正好 2N 条 / 少于 2N 条）"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_exactly_2n_splits_evenly(self, mock_get_client, tool, ctx):
        client = _install(mock_get_client, _series(14))

        result = await tool.execute(context=ctx, action="trend_compare", days=7)

        assert result.success is True, result.error
        data = result.data
        assert data["days"] == 7
        assert data["window_days"] == 14
        assert data["window_capped"] is False
        assert data["partial"] is False
        # 本期 = 最近 7 天（orders 8..14 = 77），上期 = 其前 7 天（1..7 = 28）
        assert data["current_total"] == 77
        assert data["previous_total"] == 28
        assert data["delta"] == 49
        assert data["delta_pct"] == 175.0
        assert data["current_daily_avg"] == 11.0
        assert data["previous_daily_avg"] == 4.0
        assert data["previous_is_zero"] is False
        # 金额口径同形（四舍五入后仍是同一批数字）
        assert data["amount"]["current_total"] == 7700
        assert data["amount"]["previous_total"] == 2800
        assert data["amount"]["delta_pct"] == 175.0
        # 每日明细切片：本期最早一天 = 上期最后一天的次日
        assert len(data["current_daily"]) == 7
        assert len(data["previous_daily"]) == 7
        assert data["previous_daily"][-1]["date"] == "2026-10-22"
        assert data["current_daily"][0]["date"] == "2026-10-23"
        assert data["current_period"] == {
            "start": "2026-10-23", "end": "2026-10-29", "days": 7,
        }
        assert data["previous_period"] == {
            "start": "2026-10-16", "end": "2026-10-22", "days": 7,
        }
        # 一次取 2×days 天（不两次查询、不在客户端重算）
        assert client.get.call_args[0][0] == "/api/admin/dashboard/order-trend"
        assert client.get.call_args[1]["params"] == {"days": 14}

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_short_series_marks_partial(self, mock_get_client, tool, ctx):
        """少于 2N 条：本期取最近 N 条，上期取仅存的前若干条 ⇒ partial=True。"""
        _install(mock_get_client, _series(10))

        result = await tool.execute(context=ctx, action="trend_compare", days=7)

        assert result.success is True, result.error
        data = result.data
        assert data["partial"] is True
        assert data["current_period"]["days"] == 7
        assert data["previous_period"]["days"] == 3
        assert data["current_total"] == 49      # orders 4..10
        assert data["previous_total"] == 6      # orders 1..3
        assert data["delta"] == 43
        assert data["delta_pct"] == 716.67      # round(43/6*100, 2)
        assert data["current_daily_avg"] == 7.0
        assert data["previous_daily_avg"] == 2.0
        assert data["previous_period"] == {
            "start": "2026-10-20", "end": "2026-10-22", "days": 3,
        }
        assert "不足" in result.message


class TestTrendCompareZeroBaseline:
    """上期为 0 ⇒ delta_pct=null + previous_is_zero（不得 Infinity/NaN）"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_previous_zero_yields_null_pct(self, mock_get_client, tool, ctx):
        # 上期 7 天全 0，本期 7 天各 2 单
        _install(mock_get_client, _series(14, orders_at=lambda i: 0 if i < 7 else 2))

        result = await tool.execute(context=ctx, action="trend_compare", days=7)

        assert result.success is True, result.error
        data = result.data
        assert data["previous_total"] == 0
        assert data["previous_is_zero"] is True
        assert data["delta_pct"] is None
        assert data["delta"] == 14
        assert data["amount"]["previous_total"] == 0
        assert data["amount"]["delta_pct"] is None
        assert data["amount"]["previous_is_zero"] is True
        # 全字段有限（json.dumps 会把 inf/nan 写成 Infinity/NaN ⇒ 这里一并钉住）
        for key in ("current_total", "previous_total", "delta",
                    "current_daily_avg", "previous_daily_avg"):
            value = data[key]
            assert isinstance(value, (int, float)) and math.isfinite(value), f"{key}={value!r}"
        dumped = json.dumps(data, ensure_ascii=False)
        assert "Infinity" not in dumped and "NaN" not in dumped


class TestTrendCompareWindowCap:
    """窗口被上限截断 ⇒ window_capped + 实际窗口（不许悄悄退化）"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_over_cap_discloses_actual_window(self, mock_get_client, tool, ctx):
        client = _install(mock_get_client, _series(MAX_WINDOW_DAYS))
        requested = MAX_PERIOD_DAYS + 15

        result = await tool.execute(context=ctx, action="trend_compare", days=requested)

        assert result.success is True, result.error
        data = result.data
        assert data["window_capped"] is True
        assert data["requested_days"] == requested
        assert data["days"] == MAX_PERIOD_DAYS
        assert data["window_days"] == MAX_WINDOW_DAYS
        assert data["current_period"]["days"] == MAX_PERIOD_DAYS
        assert client.get.call_args[1]["params"] == {"days": MAX_WINDOW_DAYS}
        assert "截断" in result.message
        # 明细长度与披露的实际窗口一致（不是请求的 2×45=90）
        assert len(data["current_daily"]) + len(data["previous_daily"]) == MAX_WINDOW_DAYS

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_exactly_at_cap_is_not_flagged(self, mock_get_client, tool, ctx):
        _install(mock_get_client, _series(MAX_WINDOW_DAYS))

        result = await tool.execute(context=ctx, action="trend_compare", days=MAX_PERIOD_DAYS)

        assert result.success is True, result.error
        assert result.data["window_capped"] is False
        assert result.data["days"] == MAX_PERIOD_DAYS


class TestTrendCompareBadPayload:
    """服务端结构异常 ⇒ 失败 + suggestion（不得 success + 空对象）"""

    @pytest.mark.parametrize("data", [
        {"list": "oops"},                       # list 位置不是数组
        [],                                      # 空序列（没有任何可对比数据）
        {"list": [{"orders": 3, "amount": 1}]},  # 缺 date
        {"list": [{"date": "2026-10-01", "orders": "3", "amount": 1}]},  # orders 非数值
        {"list": [{"date": "2026-10-01", "orders": 3}]},                 # 缺 amount
        {"list": [{"date": "2026-10-01", "orders": 3, "amount": float("inf")}]},  # 非有限
        {"list": [{"date": "不是日期", "orders": 3, "amount": 1}]},
    ])
    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_bad_structure_is_failure(self, mock_get_client, tool, ctx, data):
        _install(mock_get_client, data)

        result = await tool.execute(context=ctx, action="trend_compare", days=7)

        assert result.success is False
        assert result.error
        assert result.suggestion
        assert not result.data, f"失败却回传了 data={result.data!r}"

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_admin_api_failure_is_passed_through(self, mock_get_client, tool, ctx):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "PERMISSION_DENIED", "message": "缺少看板权限"},
        })
        mock_get_client.return_value = client

        result = await tool.execute(context=ctx, action="trend_compare", days=7)

        assert result.success is False
        assert result.error_code == "PERMISSION_DENIED"
        assert result.suggestion
        assert not result.data
