"""`briefing_query` 的历史回溯分支（issue #8253）—— 复盘的第一块原料

## 为什么要有它

老板问：**「上个月你建议我改价，效果如何？」**
改前答不出来：工具只能拿**当日**，`/briefing/today` 之外没有历史端点 ⇒ 模型根本不知道「提醒过什么」。

## 三条纪律（每条都有对应断言）

1. **历史是另一个端点，不是另一个 view**：`view="history"` 必须走 `/api/admin/briefing/history`，
   **不许**混进 `VALUED_VIEWS`（那会走 `/snapshot`，拿到的是「今天的快照」——名字像、东西完全不是）。
2. **`days` 透传**：默认 30，显式给就按给的传（上限钳制在 Java 侧 `HISTORY_MAX_DAYS`，
   Python 不重复实现，避免两处口径打架）。
3. **空历史必须自己说「没有」**：`data=[]` ≠ 「成功但无事发生」。让模型对着空列表说「一切正常」
   是这类工具最典型的假绿（对齐 P0 的「未知 ≠ 0」）。

case_ids：`DA-031`（与 Java 侧 `DailyBriefingHistoryTest` 同一条用例：一个行为，两端判据）。
"""

# case_ids: DA-031

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.briefing_query import (
    HISTORY_ENDPOINT,
    VALUED_VIEWS,
    BriefingQueryTool,
)

PERMISSION = "dashboard:view"
ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])


def _client_returning(data):
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": data})
    return client


class TestHistoryEndpoint:
    """纪律 1：history 是**独立的端点**，不是 snapshot 的一个 view"""

    def test_history_is_not_a_valued_view(self):
        """混进 VALUED_VIEWS 会走 `/snapshot` ⇒ 拿到「今天的快照」冒充历史（最坏的假绿）。"""
        assert "history" not in VALUED_VIEWS

    @pytest.mark.asyncio
    async def test_history_view_hits_the_history_endpoint(self):
        client = _client_returning([{"bizDate": "2026-10-30", "content": {"suggestions": []}}])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            await BriefingQueryTool().execute(ALLOWED, view="history")

        assert client.get.call_args.args[0] == HISTORY_ENDPOINT
        assert HISTORY_ENDPOINT == "/api/admin/briefing/history"

    @pytest.mark.asyncio
    async def test_history_does_not_touch_the_snapshot_endpoint(self):
        client = _client_returning([])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            await BriefingQueryTool().execute(ALLOWED, view="history")

        paths = [call.args[0] for call in client.get.call_args_list]
        assert "/api/admin/briefing/snapshot" not in paths


class TestDaysPassthrough:
    """纪律 2：`days` 透传（上限在 Java 侧，Python 不重复钳制）"""

    @pytest.mark.asyncio
    async def test_default_days_is_30(self):
        client = _client_returning([])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            await BriefingQueryTool().execute(ALLOWED, view="history")

        assert client.get.call_args.kwargs["params"] == {"days": 30}

    @pytest.mark.asyncio
    async def test_explicit_days_is_passed_through(self):
        client = _client_returning([])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            await BriefingQueryTool().execute(ALLOWED, view="history", days=7)

        assert client.get.call_args.kwargs["params"] == {"days": 7}


class TestEmptyHistoryIsStated:
    """纪律 3：空历史必须自己说「没有」，不许让模型对着空列表说「一切正常」"""

    @pytest.mark.asyncio
    async def test_empty_history_says_so(self):
        client = _client_returning([])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            result = await BriefingQueryTool().execute(ALLOWED, view="history")

        assert result.success is True
        assert "没有历史简报" in result.message
        assert "30" in result.message

    @pytest.mark.asyncio
    async def test_non_empty_history_reports_count_and_date_range(self):
        client = _client_returning([
            {"bizDate": "2026-10-31", "content": {"suggestions": ["给 A 商品补货"]}},
            {"bizDate": "2026-10-29", "content": {"suggestions": ["B 商品改价"]}},
        ])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            result = await BriefingQueryTool().execute(ALLOWED, view="history")

        assert "2 条" in result.message
        assert "2026-10-29" in result.message and "2026-10-31" in result.message
        assert "给 A 商品补货" in result.message

    @pytest.mark.asyncio
    async def test_history_requires_the_same_permission(self):
        client = _client_returning([])
        with patch("app.tools.briefing_query.get_admin_api_client", return_value=client):
            result = await BriefingQueryTool().execute(DENIED, view="history")

        assert result.success is False
        client.get.assert_not_called()
