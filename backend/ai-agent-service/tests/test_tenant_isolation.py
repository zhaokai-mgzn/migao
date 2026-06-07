"""
跨租户隔离安全测试

验证 AI Agent 服务的多租户隔离机制持续有效，包括：
1. API 层：send_message / delete_session / get_history 端点的租户隔离
2. Tools 层：product_search / product_detail / logistics_track 的响应数据 tenant_id 验证
3. 错误处理层：registry.py 的敏感信息隐藏
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException

from app.tools.base import ToolContext, ToolResult
from app.tools.product_search import ProductSearchTool
from app.tools.product_detail import ProductDetailTool
from app.tools.logistics_track import LogisticsTrackTool
from app.tools.registry import ToolRegistry


# ========== 公用 Fixtures ==========

TENANT_A = 1
TENANT_B = 2
USER_A = "user_tenant_a"
USER_B = "user_tenant_b"
USER_A2 = "user_tenant_a_other"  # 同租户但不同用户


@pytest.fixture
def ctx_tenant_a():
    """租户 A 的用户上下文"""
    return ToolContext(tenant_id=TENANT_A, user_id=USER_A, session_id="sess_a", role="customer")


@pytest.fixture
def ctx_tenant_b():
    """租户 B 的用户上下文"""
    return ToolContext(tenant_id=TENANT_B, user_id=USER_B, session_id="sess_b", role="customer")


@pytest.fixture
def session_owned_by_tenant_a():
    """属于租户 A / USER_A 的会话数据"""
    return {
        "id": "sess_a_001",
        "tenant_id": TENANT_A,
        "customer_id": USER_A,
        "title": "租户A的会话",
        "status": "active",
        "channel": "web",
        "created_at": "2026-04-25T10:00:00Z",
        "updated_at": "2026-04-25T10:05:00Z",
    }


# ============================================================
# 第一部分：API 层租户隔离测试
# ============================================================


class TestSendMessageTenantIsolation:
    """send_message 端点的租户隔离测试"""

    @patch("app.api.chat.get_agent")
    @patch("app.api.chat.get_tool_registry")
    @patch("app.api.chat.SessionMemory")
    async def test_cross_tenant_session_access_denied(
        self, MockSessionMemory, mock_registry, mock_agent, session_owned_by_tenant_a
    ):
        """跨租户访问会话 —— 租户 B 用户尝试访问租户 A 的会话，应返回 403"""
        from app.api.chat import send_message
        from app.api.schemas import ChatSendRequest
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        MockSessionMemory.return_value = mock_memory

        request = ChatSendRequest(session_id="sess_a_001", message="你好")
        # 租户 B 的用户身份
        current_user = UserIdentity(
            user_id=USER_B, tenant_id=TENANT_B,
            identity_type="wechat_mini", role="customer",
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_message(request=request, current_user=current_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"]["code"] == "PERMISSION_DENIED"

    @patch("app.api.chat.get_agent")
    @patch("app.api.chat.get_tool_registry")
    @patch("app.api.chat.SessionMemory")
    async def test_same_tenant_different_user_access_denied(
        self, MockSessionMemory, mock_registry, mock_agent, session_owned_by_tenant_a
    ):
        """同租户不同用户 —— 同一租户内其他用户尝试访问他人会话，应返回 403"""
        from app.api.chat import send_message
        from app.api.schemas import ChatSendRequest
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        MockSessionMemory.return_value = mock_memory

        request = ChatSendRequest(session_id="sess_a_001", message="偷看消息")
        # 同租户但不同用户
        current_user = UserIdentity(
            user_id=USER_A2, tenant_id=TENANT_A,
            identity_type="wechat_mini", role="customer",
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_message(request=request, current_user=current_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"]["code"] == "PERMISSION_DENIED"


class TestDeleteSessionTenantIsolation:
    """delete_session 端点的租户隔离测试"""

    @patch("app.api.chat.SessionMemory")
    async def test_cross_tenant_delete_denied(
        self, MockSessionMemory, session_owned_by_tenant_a
    ):
        """跨租户删除 —— 租户 B 用户尝试删除租户 A 的会话，应返回 403"""
        from app.api.chat import delete_session
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        MockSessionMemory.return_value = mock_memory

        current_user = UserIdentity(
            user_id=USER_B, tenant_id=TENANT_B,
            identity_type="wechat_mini", role="customer",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_session(session_id="sess_a_001", current_user=current_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"]["code"] == "PERMISSION_DENIED"

    @patch("app.api.chat.SessionMemory")
    async def test_owner_delete_success(
        self, MockSessionMemory, session_owned_by_tenant_a
    ):
        """正常路径 —— 会话所有者成功删除自己的会话"""
        from app.api.chat import delete_session
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        mock_memory.delete_session = AsyncMock(return_value=True)
        MockSessionMemory.return_value = mock_memory

        current_user = UserIdentity(
            user_id=USER_A, tenant_id=TENANT_A,
            identity_type="wechat_mini", role="customer",
        )

        result = await delete_session(session_id="sess_a_001", current_user=current_user)

        assert result["success"] is True
        mock_memory.delete_session.assert_called_once_with("sess_a_001")


class TestGetHistoryTenantIsolation:
    """get_history 端点的租户隔离测试"""

    @patch("app.api.chat.SessionMemory")
    async def test_cross_tenant_history_access_denied(
        self, MockSessionMemory, session_owned_by_tenant_a
    ):
        """跨租户获取历史 —— 租户 B 用户尝试获取租户 A 的会话历史，应返回 403"""
        from app.api.chat import get_history
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        MockSessionMemory.return_value = mock_memory

        current_user = UserIdentity(
            user_id=USER_B, tenant_id=TENANT_B,
            identity_type="wechat_mini", role="customer",
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_history(session_id="sess_a_001", current_user=current_user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"]["code"] == "PERMISSION_DENIED"

    @patch("app.api.chat.SessionMemory")
    async def test_same_tenant_different_user_history_denied(
        self, MockSessionMemory, session_owned_by_tenant_a
    ):
        """同租户不同用户获取历史 —— 同一租户内其他用户尝试获取他人会话历史，应返回 403"""
        from app.api.chat import get_history
        from app.utils.auth import UserIdentity

        mock_memory = AsyncMock()
        mock_memory.get_session = AsyncMock(return_value=session_owned_by_tenant_a)
        MockSessionMemory.return_value = mock_memory

        current_user = UserIdentity(
            user_id=USER_A2, tenant_id=TENANT_A,
            identity_type="wechat_mini", role="customer",
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_history(session_id="sess_a_001", current_user=current_user)

        assert exc_info.value.status_code == 403


# ============================================================
# 第二部分：Tools 层响应数据 tenant_id 验证测试
# ============================================================


class TestProductSearchTenantFilter:
    """product_search 的 tenant_id 过滤测试"""

    @pytest.fixture
    def tool(self):
        return ProductSearchTool()

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_filters_out_other_tenant_products(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """过滤不属于当前租户的商品 —— 返回列表中混入了其他租户数据时应被过滤"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "p1", "name": "租户A商品", "tenantId": TENANT_A, "price": 100},
                    {"id": "p2", "name": "租户B商品", "tenantId": TENANT_B, "price": 200},
                    {"id": "p3", "name": "租户A商品2", "tenantId": TENANT_A, "price": 150},
                ],
                "total": 3,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, keyword="商品")

        assert result.success is True
        products = result.data["products"]
        # 应只返回租户 A 的商品，租户 B 的被过滤
        assert len(products) == 2
        product_ids = [p["id"] for p in products]
        assert "p1" in product_ids
        assert "p3" in product_ids
        assert "p2" not in product_ids
        # total 也应减少
        assert result.data["total"] == 2

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_all_products_belong_to_current_tenant(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """所有商品属于当前租户 —— 无需过滤，全量返回"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "p1", "name": "商品1", "tenantId": TENANT_A, "price": 100},
                    {"id": "p2", "name": "商品2", "tenantId": TENANT_A, "price": 200},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, keyword="商品")

        assert result.success is True
        assert len(result.data["products"]) == 2
        assert result.data["total"] == 2


class TestProductDetailTenantValidation:
    """product_detail 的 tenant_id 验证测试"""

    @pytest.fixture
    def tool(self):
        return ProductDetailTool()

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_rejects_other_tenant_product(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """拒绝返回其他租户的商品详情 —— 返回 '商品不存在'"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "p_other",
                "name": "其他租户商品",
                "tenantId": TENANT_B,  # 不属于当前租户
                "price": 999,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, product_id="p_other")

        assert result.success is False
        assert result.error == "商品不存在"

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_accepts_own_tenant_product(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """正常返回当前租户的商品详情"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "p_own",
                "name": "自家商品",
                "tenantId": TENANT_A,
                "price": 299,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, product_id="p_own")

        assert result.success is True
        assert result.data["name"] == "自家商品"


class TestLogisticsTrackTenantValidation:
    """logistics_track 的 tenant_id 验证测试"""

    @pytest.fixture
    def tool(self):
        return LogisticsTrackTool()

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_rejects_other_tenant_order(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """拒绝返回其他租户的订单物流 —— 返回 '订单不存在'"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order_other",
                "tenantId": TENANT_B,  # 不属于当前租户
                "logistics": {
                    "trackingNo": "SF123",
                    "company": "顺丰",
                },
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, order_id="order_other")

        assert result.success is False
        assert result.error == "订单不存在"

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_accepts_own_tenant_order(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """正常返回当前租户的订单物流"""
        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            if url == "/api/admin/orders" and kwargs.get("params", {}).get("keyword"):
                # 列表搜索返回 records
                return {"success": True, "data": {"records": [{"id": "order_own", "tenantId": TENANT_A}]}}
            # 详情查询
            return {
                "success": True,
                "data": {
                    "id": "order_own",
                    "tenantId": TENANT_A,
                    "logistics": {"trackingNo": "SF456", "company": "顺丰速运"},
                },
            }
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, order_id="order_own")

        # 物流查询成功（返回 mock 数据）
        assert result.success is True


# ============================================================
# 第三部分：Tool 错误处理安全测试
# ============================================================


class TestRegistryErrorHandling:
    """registry.py 错误处理不泄露敏感信息"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def failing_tool(self):
        """创建一个执行时抛出包含敏感信息的异常的 Tool"""
        tool = MagicMock()
        tool.name = "failing_tool"
        tool.description = "会失败的工具"
        tool.parameters = {"type": "object", "properties": {}}
        tool.check_permission = MagicMock(return_value=True)
        # 模拟抛出包含敏感信息（如数据库连接串、内部路径）的异常
        tool.execute = AsyncMock(
            side_effect=Exception(
                "Connection refused: postgresql://admin:secret@10.0.0.5:5432/prod_db"
            )
        )
        return tool

    async def test_execute_tool_hides_sensitive_error(
        self, registry, failing_tool, ctx_tenant_a
    ):
        """execute_tool 异常时不暴露原始错误内容 —— 返回泛化错误码"""
        registry._tools[failing_tool.name] = failing_tool

        result = await registry.execute_tool(
            name="failing_tool",
            context=ctx_tenant_a,
        )

        # 应返回泛化错误，不包含敏感信息
        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert "postgresql" not in (result.message or "")
        assert "secret" not in (result.message or "")
        assert "admin" not in (result.error or "")

    async def test_langchain_tool_hides_sensitive_error(
        self, registry, failing_tool, ctx_tenant_a
    ):
        """LangChain Tool wrapper 异常时不暴露原始错误内容"""
        registry._tools[failing_tool.name] = failing_tool

        # 获取 LangChain 格式 Tool
        lc_tools = registry.get_langchain_tools()
        assert len(lc_tools) == 1
        lc_tool = lc_tools[0]

        # 设置 ToolContext
        from app.tools.registry import set_tool_context
        set_tool_context(ctx_tenant_a)

        # 调用 LangChain Tool
        result_str = await lc_tool.ainvoke({})
        result = json.loads(result_str)

        # 应返回泛化错误
        assert result["success"] is False
        assert result["error"] == "tool_execution_failed"
        assert "postgresql" not in result.get("message", "")
        assert "secret" not in result.get("message", "")
