"""OrderCreateTool 单元测试 — 创建订单（SMS 安全 + 参数校验 + camelCase 透传）"""
# case_ids: OR-008, OR-009, OR-010
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.order_create import OrderCreateTool
from app.tools.base import ToolContext


@pytest.fixture
def tool():
    return OrderCreateTool()


@pytest.fixture
def customer_ctx():
    return ToolContext(tenant_id=1, user_id="user_001", session_id="s", role="customer")


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")


@pytest.fixture
def valid_items():
    return [
        {
            "product_name": "遮光窗帘",
            "quantity": 2,
            "unit_price": 99.5,
            "subtotal": 199.0,
        }
    ]


class TestOrderCreateDeclaration:
    """工具元数据声明"""

    def test_metadata(self, tool):
        assert tool.name == "order_create"
        assert tool.read_only is False
        assert tool.destructive is False
        assert tool.idempotent is False

    def test_allowed_roles(self, tool):
        assert set(tool.allowed_roles) == {"admin", "agent", "tenant_admin", "customer"}

    def test_related_tools(self, tool):
        assert "validate_input" in tool.related_tools


class TestOrderCreateOtpKey:
    """SMS 验证码 Redis key 构造"""

    def test_otp_key(self):
        assert OrderCreateTool._otp_key("13800138000", 1) == "sms:otp:1:13800138000"


class TestOrderCreateVerifySms:
    """_verify_sms_code — 一次性验证码校验"""

    async def test_invalid_code_pattern(self):
        """非 4-6 位数字直接拒绝，不碰 Redis"""
        assert await OrderCreateTool._verify_sms_code("13800138000", "abc", 1) is False
        assert await OrderCreateTool._verify_sms_code("13800138000", "123", 1) is False

    @patch("app.tools.order_create.RedisClient")
    async def test_verify_success_and_delete(self, mock_redis_cls):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="123456")
        mock_redis.delete = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_redis

        ok = await OrderCreateTool._verify_sms_code("13800138000", "123456", 1)

        assert ok is True
        mock_redis.delete.assert_awaited_once_with("sms:otp:1:13800138000")

    @patch("app.tools.order_create.RedisClient")
    async def test_verify_mismatch(self, mock_redis_cls):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="654321")
        mock_redis_cls.return_value = mock_redis

        ok = await OrderCreateTool._verify_sms_code("13800138000", "123456", 1)

        assert ok is False
        mock_redis.delete.assert_not_awaited()

    async def test_verify_bypass_code_skips_redis(self, monkeypatch):
        """万能验证码 bypass：POC/测试阶段直接通过，不碰 Redis"""
        monkeypatch.setattr("app.tools.order_create.SMS_BYPASS_CODE", "123456")
        # 不 mock RedisClient，若误触 Redis 会抛异常 → 测试失败
        ok = await OrderCreateTool._verify_sms_code("13800138000", "123456", 1)
        assert ok is True

    async def test_verify_bypass_disabled_when_empty(self, monkeypatch):
        """bypass 码为空时禁用，走原 Redis 校验逻辑"""
        monkeypatch.setattr("app.tools.order_create.SMS_BYPASS_CODE", "")
        # 非 4-6 位数字仍直接拒绝（不碰 Redis）
        assert await OrderCreateTool._verify_sms_code("13800138000", "abc", 1) is False

    @patch("app.tools.order_create.RedisClient")
    async def test_verify_redis_error(self, mock_redis_cls):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
        mock_redis_cls.return_value = mock_redis

        ok = await OrderCreateTool._verify_sms_code("13800138000", "123456", 1)

        assert ok is False


class TestOrderCreateStoreSms:
    """_store_sms_code"""

    @patch("app.tools.order_create.RedisClient")
    async def test_store_success(self, mock_redis_cls):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_redis

        ok = await OrderCreateTool._store_sms_code("13800138000", "123456", 1)

        assert ok is True
        mock_redis.set.assert_awaited_once()

    @patch("app.tools.order_create.RedisClient")
    async def test_store_error(self, mock_redis_cls):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
        mock_redis_cls.return_value = mock_redis

        ok = await OrderCreateTool._store_sms_code("13800138000", "123456", 1)

        assert ok is False


class TestOrderCreateNeedsSms:
    """_needs_sms_verification — 仅 customer 需要"""

    def test_customer_needs_sms(self, tool, customer_ctx):
        assert tool._needs_sms_verification(customer_ctx) is True

    def test_admin_skips_sms(self, tool, admin_tool_context):
        assert tool._needs_sms_verification(admin_tool_context) is False


class TestOrderCreateValidation:
    """execute 参数校验"""

    async def test_permission_denied(self, tool):
        guest = ToolContext(tenant_id=1, user_id="g", session_id="s", role="guest")
        result = await tool.execute(context=guest, customer_name="张三", customer_phone="13800138000", items=[])
        assert result.success is False
        assert "权限" in result.error

    async def test_missing_customer_name(self, tool, agent_ctx, valid_items):
        result = await tool.execute(context=agent_ctx, customer_name="", customer_phone="13800138000", items=valid_items)
        assert result.success is False
        assert "缺少客户姓名" in result.error

    async def test_missing_customer_phone(self, tool, agent_ctx, valid_items):
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="", items=valid_items)
        assert result.success is False
        assert "缺少客户电话" in result.error

    async def test_invalid_phone_format(self, tool, agent_ctx, valid_items):
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="12800138000", items=valid_items)
        assert result.success is False
        assert "手机号格式无效" in result.error

    async def test_missing_items(self, tool, agent_ctx):
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=None)
        assert result.success is False
        assert "缺少商品明细" in result.error

    async def test_items_not_list(self, tool, agent_ctx):
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="13800138000", items="not-a-list")
        assert result.success is False
        assert "缺少商品明细" in result.error

    async def test_item_not_dict(self, tool, agent_ctx):
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=["bad"])
        assert result.success is False
        assert "第 1 项格式错误" in result.error

    async def test_item_missing_field(self, tool, agent_ctx):
        items = [{"product_name": "窗帘", "quantity": 1, "unit_price": 10.0}]  # 缺 subtotal
        result = await tool.execute(context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=items)
        assert result.success is False
        assert "第 1 项缺少 subtotal" in result.error


class TestOrderCreateSmsFlow:
    """customer 角色 SMS 验证流程（#518 安全）"""

    async def test_customer_missing_sms_code(self, tool, customer_ctx, valid_items):
        result = await tool.execute(context=customer_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items)
        assert result.success is False
        assert "缺少短信验证码" in result.error

    async def test_customer_invalid_sms_format(self, tool, customer_ctx, valid_items):
        result = await tool.execute(context=customer_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items, sms_code="12ab")
        assert result.success is False
        assert "验证码格式无效" in result.error

    @patch("app.tools.order_create.RedisClient")
    async def test_customer_wrong_sms_code(self, mock_redis_cls, tool, customer_ctx, valid_items):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="999999")
        mock_redis_cls.return_value = mock_redis

        result = await tool.execute(
            context=customer_ctx, customer_name="张三", customer_phone="13800138000",
            items=valid_items, sms_code="123456",
        )

        assert result.success is False
        assert "验证码错误或已过期" in result.error


class TestOrderCreateSuccess:
    """创建订单成功路径"""

    @patch("app.tools.order_create.get_admin_api_client")
    @patch("app.tools.order_create.RedisClient")
    async def test_customer_success_with_sms(self, mock_redis_cls, mock_get_client, tool, customer_ctx, valid_items):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="123456")
        mock_redis.delete = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_redis

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "order-123"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=customer_ctx, customer_name="张三", customer_phone="13800138000",
            items=valid_items, sms_code="123456",
        )

        assert result.success is True
        assert "order-123" in result.message
        mock_redis.delete.assert_awaited_once()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_agent_success_without_sms(self, mock_get_client, tool, agent_ctx, valid_items):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "order-456"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items,
        )

        assert result.success is True
        assert "order-456" in result.message

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_success_uses_order_no_fallback(self, mock_get_client, tool, agent_ctx, valid_items):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"orderNo": "ORD-20260825-0001"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items,
        )

        assert result.success is True
        assert "ORD-20260825-0001" in result.message


class TestOrderCreatePayload:
    """camelCase 构建 + 可选字段透传（不静默丢弃）"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_payload_camelcase_and_passthrough(self, mock_get_client, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
        mock_get_client.return_value = mock_client

        items = [{
            "product_name": "窗帘",
            "quantity": 3,
            "unit_price": 50,
            "subtotal": 150,
            "product_id": "pid-1",
            "width": 2.8,
            "height": 2.0,
            "processing_info": {"colorName": "白色", "sellingMethod": "bulk_cut"},
        }]

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=items, customer_address="杭州", remark="加急",
        )

        assert result.success is True
        json_data = mock_client.post.call_args.kwargs["json_data"]
        assert json_data["customerName"] == "张三"
        assert json_data["customerPhone"] == "13800138000"
        assert json_data["customerAddress"] == "杭州"
        assert json_data["remark"] == "加急"
        entry = json_data["items"][0]
        assert entry["productName"] == "窗帘"
        assert entry["quantity"] == 3
        assert entry["unitPrice"] == 50.0
        assert entry["subtotal"] == 150.0
        assert entry["productId"] == "pid-1"
        assert entry["width"] == 2.8
        assert entry["height"] == 2.0
        assert entry["processingInfo"]["sellingMethod"] == "bulk_cut"
        # 端点
        assert "/api/admin/agent/orders" in mock_client.post.call_args[0][0]


class TestOrderCreateFailure:
    """创建订单失败/异常路径"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_post_failure(self, mock_get_client, tool, agent_ctx, valid_items):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": False, "error": {"message": "库存不足"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items,
        )

        assert result.success is False
        assert "库存不足" in result.error

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_post_exception(self, mock_get_client, tool, agent_ctx, valid_items):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items,
        )

        assert result.success is False
        assert result.error == "tool_execution_failed"
