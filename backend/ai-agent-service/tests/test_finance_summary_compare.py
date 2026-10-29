"""finance_api(action=get_summary, compare=true) — 等长上一期对比（issue #8120）

口径：
- 上一期 = 与本期**等长**且**紧邻其前**的区间（本期 start 的前一天为上一期 end）；
- 返回上一期四项 + 逐项 ``delta`` / ``delta_pct``；上期为 0 ⇒ ``delta_pct = None`` +
  ``previous_is_zero = True``（不得 Infinity/NaN）；
- ``VALID_ACTIONS`` **保持三个**（不新增 action 枚举）；不传 compare ⇒ **不发第二次请求**。
"""
# case_ids: DA-025

import datetime as _dt
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.finance_api import FinanceApiTool

SUMMARY = "/api/admin/finance/summary"


def _payload(income, refund, net, pending):
    return {
        "success": True,
        "data": {
            "totalIncome": income,
            "totalRefund": refund,
            "netIncome": net,
            "pendingReceivable": pending,
        },
    }


def _install(mock_get_client, *responses):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=list(responses))
    mock_get_client.return_value = client
    return client


class TestFinanceComparePeriod:
    """上一期区间 = 等长前移（mock client 逐参数断言）"""

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_previous_period_is_equal_length_and_adjacent(
        self, mock_get_client, admin_tool_context,
    ):
        client = _install(
            mock_get_client,
            _payload(10000.0, 2000.0, 8000.0, 500.0),   # 10-01 ~ 10-07
            _payload(8000.0, 1000.0, 7000.0, 300.0),    # 09-24 ~ 09-30（等长 7 天）
        )

        result = await FinanceApiTool().execute(
            context=admin_tool_context,
            action="get_summary",
            start_date="2026-10-01",
            end_date="2026-10-07",
            compare=True,
        )

        assert result.success is True, result.error
        assert client.get.call_count == 2
        first, second = client.get.call_args_list
        assert first[0][0] == SUMMARY
        assert first[1]["params"] == {"startDate": "2026-10-01", "endDate": "2026-10-07"}
        assert second[0][0] == SUMMARY
        assert second[1]["params"] == {"startDate": "2026-09-24", "endDate": "2026-09-30"}

        compare = result.data["compare"]
        assert compare["previous_period"] == {
            "startDate": "2026-09-24", "endDate": "2026-09-30",
        }
        assert compare["period"] == {
            "startDate": "2026-10-01", "endDate": "2026-10-07",
        }
        assert compare["previous"] == {
            "totalIncome": 8000.0,
            "totalRefund": 1000.0,
            "netIncome": 7000.0,
            "pendingReceivable": 300.0,
        }
        assert compare["delta"] == {
            "totalIncome": 2000.0,
            "totalRefund": 1000.0,
            "netIncome": 1000.0,
            "pendingReceivable": 200.0,
        }
        assert compare["delta_pct"] == {
            "totalIncome": 25.0,
            "totalRefund": 100.0,
            "netIncome": 14.29,
            "pendingReceivable": 66.67,
        }
        assert compare["previous_is_zero"] == {
            "totalIncome": False,
            "totalRefund": False,
            "netIncome": False,
            "pendingReceivable": False,
        }
        # 本期原始四项不被覆盖（既有消费面不回归）
        assert result.data["totalIncome"] == 10000.0
        assert result.data["netIncome"] == 8000.0

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_default_period_uses_month_start_and_equal_previous(
        self, mock_get_client, admin_tool_context,
    ):
        """不带 start_date/end_date 时：本期 = 本月 1 号~今天，上期 = 等长前移。"""
        today = _dt.date.today()
        month_start = today.replace(day=1)
        length = (today - month_start).days + 1
        expected_prev_end = month_start - _dt.timedelta(days=1)
        expected_prev_start = expected_prev_end - _dt.timedelta(days=length - 1)
        client = _install(mock_get_client, _payload(100, 0, 100, 0), _payload(50, 0, 50, 0))

        result = await FinanceApiTool().execute(
            context=admin_tool_context, action="get_summary", compare=True,
        )

        assert result.success is True, result.error
        first, second = client.get.call_args_list
        assert first[1]["params"] == {
            "startDate": month_start.isoformat(), "endDate": today.isoformat(),
        }
        assert second[1]["params"] == {
            "startDate": expected_prev_start.isoformat(),
            "endDate": expected_prev_end.isoformat(),
        }

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_no_compare_keeps_single_request(
        self, mock_get_client, admin_tool_context,
    ):
        """不传 compare（默认）= 旧行为：只查一次、无 compare 键。"""
        client = _install(mock_get_client, _payload(100, 10, 90, 5))

        result = await FinanceApiTool().execute(
            context=admin_tool_context,
            action="get_summary",
            start_date="2026-10-01",
            end_date="2026-10-07",
        )

        assert result.success is True
        assert client.get.call_count == 1
        assert "compare" not in result.data


class TestFinanceCompareZeroBaseline:
    """上期某项为 0 ⇒ 该项 delta_pct=null + previous_is_zero（不得 Infinity/NaN）"""

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_zero_previous_item_is_null_pct(self, mock_get_client, admin_tool_context):
        _install(
            mock_get_client,
            _payload(500.0, 100.0, 400.0, 0.0),
            _payload(0.0, 0.0, 0.0, 0.0),   # 上一期四项全 0
        )

        result = await FinanceApiTool().execute(
            context=admin_tool_context,
            action="get_summary",
            start_date="2026-10-01",
            end_date="2026-10-07",
            compare=True,
        )

        assert result.success is True, result.error
        compare = result.data["compare"]
        assert compare["delta_pct"] == {
            "totalIncome": None,
            "totalRefund": None,
            "netIncome": None,
            "pendingReceivable": None,
        }
        assert compare["previous_is_zero"] == {
            "totalIncome": True,
            "totalRefund": True,
            "netIncome": True,
            "pendingReceivable": True,
        }
        assert compare["delta"] == {
            "totalIncome": 500.0,
            "totalRefund": 100.0,
            "netIncome": 400.0,
            "pendingReceivable": 0.0,
        }
        dumped = json.dumps(result.data, ensure_ascii=False)
        assert "Infinity" not in dumped and "NaN" not in dumped


class TestFinanceCompareFailure:
    """上一期查询失败 / 参数非法 ⇒ 失败 + suggestion（不得 success + 空对象）"""

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_previous_query_failure_is_failure(self, mock_get_client, admin_tool_context):
        _install(
            mock_get_client,
            _payload(500.0, 100.0, 400.0, 0.0),
            {"success": False, "error": {"code": "INTERNAL_ERROR", "message": "上游超时"}},
        )

        result = await FinanceApiTool().execute(
            context=admin_tool_context,
            action="get_summary",
            start_date="2026-10-01",
            end_date="2026-10-07",
            compare=True,
        )

        assert result.success is False
        assert result.error
        assert result.suggestion
        assert not result.data
        assert "上一期" in result.message

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_bad_date_is_explicit_failure(self, mock_get_client, admin_tool_context):
        client = _install(mock_get_client, _payload(500.0, 100.0, 400.0, 0.0))

        result = await FinanceApiTool().execute(
            context=admin_tool_context,
            action="get_summary",
            start_date="2026/10/01",
            end_date="2026-10-07",
            compare=True,
        )

        assert result.success is False
        assert "日期" in result.message or "时间" in result.message
        assert result.suggestion
        assert not result.data
        assert client.get.call_count == 0, "日期非法时不该先发一次查询再失败"
