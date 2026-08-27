"""CustomerManageTool 单元测试 — 客户档案 + 标签库 CRUD。

覆盖 list 脱敏/分页、detail/update 参数校验、标签增删、标签库 CRUD，
以及 destructive 工具只读 action 的确认豁免（DF-008）。
"""
# case_ids: DF-008, CU-001, CU-002, CU-003, CU-004
import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills.base_skill import _requires_confirmation
from app.tools.customer_manage import CustomerManageTool, VALID_ACTIONS


@pytest.fixture
def tool():
    return CustomerManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


class TestCustomerReadOnlyConfirmation:
    """destructive 工具只读 action 的确认豁免（DF-008）"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail", "list_tags"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查客户列表") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "customer_id": "x"}, "查客户详情") is False

    def test_list_tags_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list_tags"}, "有哪些客户标签") is False

    def test_write_actions_still_require_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "update"}, "帮我改客户信息") is True
        assert _requires_confirmation(tool, {"action": "add_tag"}, "给客户打标签") is True
        assert _requires_confirmation(tool, {"action": "delete_tag"}, "删除标签") is True


class TestCustomerPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="merge")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestCustomerList:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_defaults_and_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            page="2",
            size="5",
            keyword="张三",
            source_channel="wechat",
            vip_level="gold",
        )

        assert result.success is True
        assert result.data["customers"] == []
        assert result.data["total"] == 0
        assert result.data["page"] == 2
        assert result.data["size"] == 5

        call_kwargs = mock_client.get.call_args[1]
        params = call_kwargs["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["keyword"] == "张三"
        assert params["sourceChannel"] == "wechat"
        assert params["vipLevel"] == "gold"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_phone_masking(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "c1", "name": "张三", "phone": "13800138000", "sourceChannel": "wechat", "vipLevel": "gold"},
                    {"id": "c2", "name": "李四", "phone": "1234", "sourceChannel": None, "vipLevel": None},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        customers = result.data["customers"]
        # len>=11 → 前3+****+后4；否则原样
        assert customers[0]["phone"] == "138****8000"
        assert customers[1]["phone"] == "1234"
        assert "找到 2 个客户" in result.message

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_name_fallback_wechat_nickname(self, mock_get_client, tool, admin_tool_context, mock_client):
        """生产回归：admin-api 客户列表无 name 字段（返回 wechatNickname），
        米宝曾显示"姓名字段都为空"。必须回退到 wechatNickname/nickname。"""
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "c1", "phone": "13800138000", "wechatNickname": "张三"},
                    {"id": "c2", "phone": "13900000000", "name": "李四"},
                    {"id": "c3", "phone": "13700000000", "nickname": "王五"},
                ],
                "total": 3,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        customers = result.data["customers"]
        assert customers[0]["name"] == "张三"
        assert customers[1]["name"] == "李四"
        assert customers[2]["name"] == "王五"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_empty_message(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        assert "未找到符合条件的客户" in result.message

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "服务不可用"


class TestCustomerDetail:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少客户 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        payload = {"id": "c1", "name": "张三", "profile": {}, "tags": [], "orders": [], "sessions": []}
        mock_client.get = AsyncMock(return_value={"success": True, "data": payload})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", customer_id="c1")
        assert result.success is True
        assert result.data == payload
        assert mock_client.get.call_args[0][0] == "/api/admin/customers/c1"


class TestCustomerUpdate:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", data={"name": "张三"})
        assert result.success is False
        assert "缺少客户 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_missing_data(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", customer_id="c1")
        assert result.success is False
        assert "缺少更新数据" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", customer_id="c1", data={"name": "新名字"})
        assert result.success is True
        assert result.data == {"customer_id": "c1"}
        assert mock_client.put.call_args[0][0] == "/api/admin/customers/c1"
        assert mock_client.put.call_args[1]["json_data"] == {"name": "新名字"}


class TestCustomerTags:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_add_tag_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="add_tag", tag_id="t1")
        assert r1.success is False and "缺少客户 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="add_tag", customer_id="c1")
        assert r2.success is False and "缺少标签 ID" in r2.error
        mock_client.post.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_add_tag_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="add_tag", customer_id="c1", tag_id="t1")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/customers/c1/tags/t1"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_remove_tag_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="remove_tag", tag_id="t1")
        assert r1.success is False and "缺少客户 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="remove_tag", customer_id="c1")
        assert r2.success is False and "缺少标签 ID" in r2.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_remove_tag_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="remove_tag", customer_id="c1", tag_id="t1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/customers/c1/tags/t1"


class TestCustomerTagLibrary:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_tags(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "t1", "name": "VIP"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_tags")
        assert result.success is True
        assert result.data["count"] == 1
        assert mock_client.get.call_args[0][0] == "/api/admin/customer-tags"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_create_tag_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create_tag")
        assert result.success is False
        assert "缺少标签名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_create_tag_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "t-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create_tag", name="VIP", color="red")
        assert result.success is True
        assert mock_client.post.call_args[1]["json_data"] == {"name": "VIP", "color": "red"}

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_tag_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_tag", name="VIP")
        assert result.success is False
        assert "缺少标签 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_tag_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_tag", tag_id="t1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_update_tag_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="update_tag", tag_id="t1", name="新名")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/customer-tags/t1"
        assert mock_client.put.call_args[1]["json_data"] == {"name": "新名"}

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_delete_tag_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_tag")
        assert result.success is False
        assert "缺少标签 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_delete_tag_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_tag", tag_id="t1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/customer-tags/t1"
