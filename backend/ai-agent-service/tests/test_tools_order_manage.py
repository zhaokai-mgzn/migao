"""OrderManageTool 单元测试 — Agent BFF PATCH 端点"""
# case_ids: OR-006, OR-007
import pytest
from unittest.mock import AsyncMock, patch

from app.tools import order_manage as order_manage_module
from app.tools.base import ToolContext
from app.tools.order_manage import OrderManageTool


@pytest.fixture
def tool():
    return OrderManageTool()


class TestOrderUpdateStatus:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_update_status(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_status",
            order_id="order-1", status="confirmed")

        assert result.success is True
        # 验证调用了 PATCH Agent 端点
        call_args = mock_client.patch.call_args
        assert "agent/orders/order-1" in call_args[0][0]


class TestOrderUpdateLogistics:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_update_logistics(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_logistics",
            order_id="order-1", logistics_company="顺丰", tracking_number="SF123")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["logisticsCompany"] == "顺丰"
        assert json_data["trackingNumber"] == "SF123"


class TestOrderCancel:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_cancel(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="cancel",
            order_id="ORD-20250718001", cancel_reason="客户要求")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["action"] == "cancel"
        assert json_data["cancelReason"] == "客户要求"


class TestOrderRefund:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_refund(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="refund",
            order_id="order-1", refund_amount=299.0, refund_reason="质量问题")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["action"] == "refund"
        assert json_data["refundAmount"] == 299.0
        assert json_data["refundReason"] == "质量问题"


class TestOrderInvalid:
    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, action="invalid_op", order_id="x")
        assert result.success is False
        assert "不支持" in result.message


class TestOrderPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context, action="cancel", order_id="x")
        assert result.success is False
        assert "权限" in result.error


class TestOrderManageValidation:
    """各 action 必填参数校验"""

    async def test_update_status_missing_status(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_status", order_id="o1")
        assert result.success is False
        assert "缺少状态参数" in result.error

    async def test_update_logistics_missing_company(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_logistics", order_id="o1", tracking_number="SF1")
        assert result.success is False
        assert "缺少快递公司" in result.error

    async def test_update_logistics_missing_tracking(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_logistics", order_id="o1", logistics_company="顺丰")
        assert result.success is False
        assert "缺少运单号" in result.error

    async def test_missing_order_id(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="")
        assert result.success is False
        assert "缺少订单 ID" in result.error


class TestOrderRefundPermissionScope:
    """退款需 `order:refund`（issue #4148）—— 与 admin-api 的 `@RequirePermission` 口径一致。

    缺陷形态（父单 #4146 / 祖父 #4103）：米宝 BFF 的统一 PATCH 端点是**类级** `order:list`
    （status/logistics/cancel/refund 共用一个入口），工具层也只有一条粗粒度
    `required_permissions = ["order:list"]` ⇒ 只持 `order:list` 的商户员工
    （`customer_service` / `sales` / `finance` 三个内置岗位）可借米宝越权退款。
    表单路径 `OrderController` 的退款路由用的是 `order:refund` —— 两条路径口径不一致。

    本类锁两半（缺任一半都成缺陷）：
    ① 越权必须在**工具层**就被挡住（admin-api 的 403 是第二道防线，不是唯一一道）；
    ② 其余 action 不得被顺带收窄（正向对照，防「顺手把 order_manage 全改成 order:refund」）。
    """

    @pytest.fixture
    def list_only_context(self):
        """只持 `order:list` 的商户员工 —— `customer_service` 岗位的真实权限集（内置角色口径）。"""
        return ToolContext(
            tenant_id=1, user_id="staff_cs", session_id="sess_cs",
            role="customer_service", permissions=["order:list"],
        )

    @pytest.fixture
    def refund_context(self):
        """持 `order:refund` 的商户员工（`operator` 岗位的真实权限集）。"""
        return ToolContext(
            tenant_id=1, user_id="staff_op", session_id="sess_op",
            role="operator", permissions=["order:list", "order:refund"],
        )

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_refund_denied_without_order_refund(self, mock_get_client, tool, list_only_context):
        result = await tool.execute(
            context=list_only_context, action="refund",
            order_id="order-1", refund_amount=299.0, refund_reason="质量问题")

        assert result.success is False
        # 结构化错误码：消费方（重试抑制链路）据此判定「换参数也没用」，不得退回套话
        assert result.error_code == "PERMISSION_DENIED"
        suggestion = result.suggestion or ""
        assert "order:refund" in suggestion, "必须说清缺的是哪个权限码（否则模型只能胡编）"
        assert "不要重试" in suggestion, "权限拒绝是确定性的：必须明说不要重试"
        assert "岗位权限" in suggestion, "必须给出管理后台的开通路径"
        # 承重判据：越权退款**压根不该到 admin-api**（工具层是 agent 侧唯一的拦截点）
        mock_get_client.assert_not_called()

    @pytest.mark.parametrize("kwargs", [
        {"action": "update_status", "status": "confirmed"},
        {"action": "cancel", "cancel_reason": "客户不要了"},
        {"action": "confirm_payment"},
        {"action": "update_logistics", "logistics_company": "顺丰", "tracking_number": "SF1"},
    ])
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_other_actions_keep_order_list_only(
            self, mock_get_client, tool, list_only_context, kwargs):
        """正向对照：只持 `order:list` 时，其余四个 action 必须照旧可用（不得过度收窄）。"""
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=list_only_context, order_id="order-1", **kwargs)

        assert result.success is True, f"{kwargs['action']} 只持 order:list 时应照旧放行"
        assert mock_client.patch.call_args.kwargs["json_data"]["action"] == kwargs["action"]

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_refund_allowed_with_order_refund(self, mock_get_client, tool, refund_context):
        """正向对照：持 `order:refund` 的岗位（operator）退款必须真的执行到 admin-api。"""
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=refund_context, action="refund",
            order_id="order-1", refund_amount=299.0, refund_reason="质量问题")

        assert result.success is True
        json_data = mock_client.patch.call_args.kwargs["json_data"]
        assert json_data["action"] == "refund"
        assert json_data["refundAmount"] == 299.0
        assert json_data["refundReason"] == "质量问题"


class TestRefundGuardIsNotVacuous:
    """红证：把 action→权限码映射还原成 #4148 的缺陷形态（退款也只要 `order:list`），
    上面那条「拒绝」断言必须**变红**（放行）—— 证明它由这道门承重、不是恒真断言。"""

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_empty_action_permission_map_reproduces_the_defect(
            self, mock_get_client, tool, monkeypatch):
        monkeypatch.setattr(order_manage_module, "ACTION_PERMISSIONS", {})
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client
        list_only = ToolContext(
            tenant_id=1, user_id="staff_cs", session_id="sess_cs",
            role="customer_service", permissions=["order:list"])

        result = await tool.execute(
            context=list_only, action="refund", order_id="order-1", refund_amount=299.0)

        assert result.success is True, "缺陷形态（无 action 级复检）下必须放行 —— 否则本类失去判别力"
        assert mock_client.patch.call_args.kwargs["json_data"]["action"] == "refund"


class TestOrderManageConfirmPayment:
    """确认支付 confirm_payment"""

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_confirm_payment(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="confirm_payment", order_id="o1")
        assert result.success is True
        assert "订单已确认支付" in result.message


class TestOrderManageFailure:
    """API 失败与异常路径"""

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_api_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": False, "error": {"message": "订单不存在"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="bad-id")
        assert result.success is False
        assert "订单不存在" in result.error

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_execute_exception(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="o1")
        assert result.success is False
        assert result.error == "tool_execution_failed"
