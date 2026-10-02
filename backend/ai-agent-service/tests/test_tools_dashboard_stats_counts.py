# case_ids: ST-004, DA-001
"""`dashboard_stats` 的**计数** action 必须返回 dict 形态的 `data`（issue #6044 缺陷 B）。

## 病（2026-10-02 B 端真实 LLM 评测，20:06:17–18）

```
[app.tools.dashboard_stats:execute] [dashboard-stats] Error: action=pending_shipment_count,
  error=ValidationError: 1 validation error for ToolResult
  Input should be a valid dictionary [type=dict_type, input_value=86, input_type=int]
[同型] action=processing_shipment_count
```

`DashboardController.getPendingShipmentCount()` 返回 `ApiResponse<Long>` ⇒ ai-agent 收到的
`response["data"]` 是**裸 int**，而 `ToolResult.data` 的契约是 `Optional[Dict[str, Any]]`
（`app/tools/base.py`）⇒ pydantic 校验当场失败 ⇒ 这两个 action **一次都没成功过**
（Agent 只能对用户说「数据看板查询失败，请稍后重试」）。

## 本文件锁什么

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | 两个计数 action 在**裸 int** / 裸 float / 裸 str 的上游 `data` 下都返回 `success=True` | 直接复用旧实现 ⇒ `ValidationError` ⇒ 红 |
| 2 | `data` 是 dict 且可读（`data["count"]` 等于上游那个数） | 包成空 dict / 丢数 ⇒ 红 |
| 3 | `summary` 带上那个数（LLM 友好面，与同文件其它 action 同口径） | 忘写摘要 ⇒ 红 |
| 4 | **对照组**：`data` 已经是 dict 时**原样透传**（不许二次包裹成 `{"count": {...}}`） | 过度包裹 ⇒ 红 |
| 5 | 上游失败（`success=False`）照旧走 `admin_api_failure`（失败语义不许被"包 dict"这件事吞掉） | 把失败读成成功 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判据只覆盖这两个**计数** action（`pending_shipment_count` / `processing_shipment_count`）；
  其余 action 的形状由 `tests/test_tools_dashboard_stats.py` 既有用例守着。
- 判据 mock 掉 `get_admin_api_client`（不起真 admin-api）—— 真实链路（HTTP 200 + 真 int）
  由 issue #6044 的现场读数承担，本文件承担的是**形状契约**那一半。
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.dashboard_stats import DashboardStatsTool

COUNT_ACTIONS = ("pending_shipment_count", "processing_shipment_count")


@pytest.fixture
def tool():
    return DashboardStatsTool()


@pytest.fixture
def ctx():
    """持 `dashboard:view` 的商户员工（与 `DashboardController` 类级权限码同源）。"""
    return ToolContext(
        tenant_id=1, user_id="cs_001", session_id="s",
        role="customer_service", permissions=["dashboard:view"],
    )


class TestCountActionsWrapScalars:
    """裸标量上游 ⇒ 包成 dict，且数值可读（判据 1/2/3）。"""

    @pytest.mark.parametrize("action", COUNT_ACTIONS)
    @pytest.mark.parametrize("upstream", [86, 0, 12.0, "7"])
    async def test_scalar_data_is_wrapped_into_a_readable_dict(self, tool, ctx, action, upstream):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": upstream})
        with patch("app.tools.dashboard_stats.get_admin_api_client", return_value=client):
            result = await tool.execute(context=ctx, action=action)

        assert result.success is True, f"{action} 在 data={upstream!r} 时应成功，实际 error={result.error!r}"
        assert isinstance(result.data, dict), (
            f"{action} 的 data 必须是 dict（ToolResult.data 契约），实际 {type(result.data).__name__}"
        )
        assert result.data.get("count") == upstream
        assert str(upstream) in (result.summary or ""), (
            f"{action} 的 summary 必须带上计数（LLM 友好面），实际 {result.summary!r}"
        )

    @pytest.mark.parametrize("action", COUNT_ACTIONS)
    async def test_endpoint_path_is_per_action(self, tool, ctx, action):
        """端点路径仍按 action 字面量分叉（包装改动不许把归属改掉）。"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": 3})
        with patch("app.tools.dashboard_stats.get_admin_api_client", return_value=client):
            await tool.execute(context=ctx, action=action)

        called = client.get.call_args[0][0]
        assert called == "/api/admin/dashboard/" + action.replace("_", "-"), (
            f"{action} 打到 {called!r} —— 端点归属漂移（权限守卫的端点对账靠静态可渲染）"
        )


class TestCountActionsKeepDictAndFailureSemantics:
    """判据 4/5：dict 原样透传；上游失败仍是失败。"""

    @pytest.mark.parametrize("action", COUNT_ACTIONS)
    async def test_dict_data_is_passed_through_untouched(self, tool, ctx, action):
        payload = {"count": 5, "nested": {"a": 1}}
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": payload})
        with patch("app.tools.dashboard_stats.get_admin_api_client", return_value=client):
            result = await tool.execute(context=ctx, action=action)

        assert result.data == payload, "已经是 dict 的 data 必须原样透传（不许二次包裹）"

    @pytest.mark.parametrize("action", COUNT_ACTIONS)
    async def test_upstream_failure_still_fails(self, tool, ctx, action):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False, "error": {"code": "FORBIDDEN", "message": "需要权限: dashboard:view"},
        })
        with patch("app.tools.dashboard_stats.get_admin_api_client", return_value=client):
            result = await tool.execute(context=ctx, action=action)

        assert result.success is False, "上游失败不许被「包 dict」这件事读成成功"
        assert "dashboard:view" in (result.error or "") or "权限" in (result.error or "")
        assert result.error_code == "FORBIDDEN", (
            f"admin-api 错误码必须透传（跨包契约，重试抑制靠它），实际 {result.error_code!r}"
        )
