"""售后工单真实来源（source）声明契约测试 — issue #3686

服务端侧：`AfterSalesTicketService.createTicket` 不再无条件硬编码 `source="agent"`
（原实现 :348），来源按真实调用方写入（C 端小布 `customer` / AI 建单 `agent` /
后台人工 `merchant`）。本文件锁 **ai-agent 侧的三条下发路径**：

admin-api 的 `POST /api/admin/agent/after-sales` 由 3 个工具共用，且都以 Service Token
认证 ⇒ 服务端 `getCurrentOperator()` 恒为 `internal-service`、body 无 source（#3605 已删）
⇒ **服务端无法自行判定来源**，必须由 ai-agent 侧按 `ToolContext.ticket_source` 经
`X-Agent-Client` 头声明（放 header 不放 body：来源不由客户端 payload 决定）。

缺发该头时服务端保守回退 `agent`（= 既有行为），故本文件同时锁「必须发」这一侧。
"""
# case_ids: AS-003, AS-005
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext

CLIENT_HEADER = "X-Agent-Client"


def _ctx(role: str, permissions=("*",)) -> ToolContext:
    """显式构造上下文：role 是来源判定的唯一输入（C 端折叠为 customer，B 端为员工角色码）。

    `permissions` 是**工具层细粒度门禁**的输入（#4106 F3：按 JWT `permissions` claim
    判定，不再按角色名硬编码）；商户侧默认给通配 `*`，与 `admin` 在 admin-api 的实际
    claim 一致（`RoleService.getUserPermissions` 特判）。
    """
    return ToolContext(
        tenant_id=1, user_id="user_001", session_id="sess_test_001",
        role=role, permissions=list(permissions),
    )


class TestTicketSourceDerivation:
    """来源派生：与既有 context.role == "customer" 口径同源，不新增第二套身份判定"""

    def test_customer_role_is_customer_source(self):
        assert _ctx("customer").ticket_source == "customer"

    def test_merchant_staff_role_is_agent_source(self):
        # 任意非 C 端角色（admin/员工自定义角色码）→ AI 建单
        assert _ctx("admin").ticket_source == "agent"
        assert _ctx("merchant_staff").ticket_source == "agent"

    def test_source_value_in_server_whitelist(self):
        # 服务端白名单 customer/agent/merchant（AfterSalesTicketService.VALID_SOURCES）
        for role in ("customer", "agent", "admin", "任意员工角色"):
            assert _ctx(role).ticket_source in {"customer", "agent", "merchant"}


class TestAftersaleCreateDeclaresCustomer:
    """C 端小布建单（顾客发起）→ 必须声明 customer（不能是 agent —— 原硬编码 bug 的现场）"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_declares_customer_header(self, mock_get_client):
        from app.tools.aftersale_create import AftersaleCreateTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [{"id": "order-123", "orderNo": "ORD-001", "customerId": "user_001"}],
                "total": 1,
            },
        })
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "as-cust-001", "ticketNo": "AS-2024-C001", "ticketType": "refund"},
        })
        mock_get_client.return_value = mock_client

        result = await AftersaleCreateTool().execute(
            context=_ctx("customer"),
            order_id="order-123",
            ticket_type="refund",
            reason="商品与描述不符",
        )

        assert result.success is True
        assert mock_client.post.call_args.kwargs["headers"][CLIENT_HEADER] == "customer"


class TestAfterSalesManageDeclaresAgent:
    """B 端米宝建单（AI 建单）→ 声明 agent"""

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_declares_agent_header(self, mock_get_client):
        from app.tools.after_sales_manage import AfterSalesManageTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "t-new"}})
        mock_get_client.return_value = mock_client

        result = await AfterSalesManageTool().execute(
            context=_ctx("admin"),
            action="create",
            order_id="o1",
            ticket_type="refund",
            reason="尺寸不符",
        )

        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/agent/after-sales"
        assert mock_client.post.call_args.kwargs["headers"][CLIENT_HEADER] == "agent"
        # 仍不下发 body 里的 source（#3605 取舍不变：来源不由 payload 决定）
        assert "source" not in mock_client.post.call_args.kwargs["json_data"]


class TestHumanHandoffDeclaresCallerSource:
    """转人工工单的来源 = 发起转人工的调用方

    实测收口（本用例证明）：`HumanHandoffTool.check_permission` 只放 C 端角色
    （admin 一律拒绝）⇒ 该工具**恒为顾客侧**，声明值必为 `customer`。
    故 3 个建单工具里只有小布（C 端）会打这条路径，B 端转人工不存在。
    """

    @pytest.fixture(autouse=True)
    def _no_db_history(self):
        with patch(
            "app.memory.session_memory.SessionMemory.get_history",
            new=AsyncMock(return_value=[]),
        ):
            yield

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_declares_customer_header_for_xiaobu(self, mock_get_client):
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "admin_eval_1", "role": "admin", "status": "active"}]},
        })
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "ticket-handoff-001", "ticketNo": "AS-2024-H001"}},
            {"success": True, "data": {"id": "notif-001"}},
        ])
        mock_get_client.return_value = mock_client

        result = await HumanHandoffTool().execute(
            context=_ctx("customer"),
            reason="我要投诉产品质量问题",
            description="窗帘收到后有色差",
        )

        assert result.success is True
        ticket_call = mock_client.post.call_args_list[0]
        assert ticket_call[0][0] == "/api/admin/agent/after-sales"
        assert ticket_call.kwargs["headers"][CLIENT_HEADER] == "customer"

    def test_b_end_is_denied_so_handoff_is_customer_only(self):
        """权限层证明：B 端角色不可用转人工 ⇒ 该路径来源恒为 customer（不可能标 agent）"""
        from app.tools.human_handoff import HumanHandoffTool

        assert HumanHandoffTool().check_permission(_ctx("admin")) is False
