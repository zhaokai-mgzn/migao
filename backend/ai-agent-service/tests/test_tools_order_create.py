"""OrderCreateTool 单元测试 — 创建订单（SMS 安全 + 参数校验 + camelCase 透传）"""
# case_ids: OR-008, OR-009, OR-010, OR-022
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


def _with_library(client, price, name="遮光窗帘", pid="p1"):
    """给 mock client 装上商品库 GET（order_create 单价接地校验用）。

    新增的 `_reject_unit_price_not_grounded` 会在 POST 前按商品名查库价；
    既有成功路径测试的 mock 只有 .post，必须补 .get（否则服务异常拒绝）。
    """
    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": pid, "name": name}], "total": 1}}
        return {"success": True, "data": {
            "id": pid, "name": name, "price": price, "basePrice": price,
            "skus": [{"id": f"{pid}-1", "skuCode": "SKU-1", "colorName": "米白",
                      "price": price, "stock": 1}],
        }}
    client.get = AsyncMock(side_effect=_get)
    return client


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

    def test_requires_confirmation(self, tool):
        # GB/T 47746-2026 承诺边界：下单=交易合同（含 B 端代下单），必须先确认再执行
        assert tool.requires_confirmation is True

    def test_description_points_to_processing_info(self, tool):
        """description 必须引导 LLM 把 sellingMethod/doorWidth 放进 processing_info，
        不得误导平铺（平铺字段 execute 不消费，会被静默丢弃——契约 bug 防线）。
        """
        desc = tool.description
        assert "processing_info" in desc
        assert "sellingMethod" in desc
        # 禁止再出现「sellMethod」平铺误导（schema/execute/frontend 统一 sellingMethod）
        assert "sellMethod" not in desc

    def test_schema_declares_selling_method_in_processing_info(self, tool):
        """items schema 的 sellingMethod/doorWidth/colorName 必须嵌套在 processing_info 里
        （与 execute 透传、admin-api processingInfo、前端 OrderDetail 读取一致）。"""
        items_props = tool.parameters["properties"]["items"]["items"]["properties"]
        pi_props = items_props["processing_info"]["properties"]
        assert "sellingMethod" in pi_props
        assert "doorWidth" in pi_props
        assert "colorName" in pi_props
        # 顶层 items 不得再声明这些字段（防平铺误导）
        assert "sellingMethod" not in items_props
        assert "sellMethod" not in items_props


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


class TestOrderCreateDuplicateLines:
    """同一张单里**完全相同的商品行**必须 fail-closed（issue #3392，DB 实证）。

    实证（run 34747025719）：新客用例 OR-022 期望 3 米（168×3 + 打孔 8×3 = ¥528），
    落库却是 **¥1584**（9×168 + 9×8）与 **¥1056**（6×168 + 6×8）—— 数量按确认轮次
    累加（3 → 6 → 9），顾客被多收 2~3 倍的钱，且全链路无告警。
    `db_verify[order_items]` 按商品名**汇总**行数量才看见这个 9；单行数量看起来都正常，
    正是"重复行"最容易漏掉的形态 —— 故在工具层用"完全相同的行"判据 fail-closed。
    """

    async def test_exact_duplicate_lines_rejected(self, tool, agent_ctx):
        items = [
            {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0},
            {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0},
        ]
        result = await tool.execute(context=agent_ctx, customer_name="张三",
                                    customer_phone="13800138000", items=items)
        assert result.success is False, "完全相同的两行必须拦下（否则顾客被重复计费）"
        assert "重复" in result.error
        assert "合并" in result.message, "必须告诉模型怎么改（合并成一行、数量取合计）"

    async def test_three_duplicate_lines_rejected(self, tool, agent_ctx):
        """实测形态：三轮确认后三行各 3 米 → 顾客实付 ¥1584。"""
        row = {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0}
        result = await tool.execute(context=agent_ctx, customer_name="张三",
                                    customer_phone="13800138000", items=[dict(row) for _ in range(3)])
        assert result.success is False
        assert "重复" in result.error

    async def test_same_product_different_spec_allowed(self, tool, agent_ctx, valid_items):
        """同商品**不同规格**（单价/尺寸不同）是合法多行 —— 不得误伤。"""
        items = [
            {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0,
             "width": 3.0},
            {"product_name": "遮光窗帘", "quantity": 2, "unit_price": 168.0, "subtotal": 336.0,
             "width": 2.0},
        ]
        with patch.object(tool, "_needs_sms_verification", return_value=False), \
             patch("app.tools.order_create.get_admin_api_client") as gc:
            gc.return_value.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
            _with_library(gc.return_value, 168.0)
            result = await tool.execute(context=agent_ctx, customer_name="张三",
                                        customer_phone="13800138000", items=items)
        assert "重复" not in (result.error or ""), f"不同规格被误判成重复行: {result.error}"

    async def test_single_line_untouched(self, tool, agent_ctx, valid_items):
        """正常单行订单不受影响（守卫不能拦成"永远下不了单"）。"""
        with patch.object(tool, "_needs_sms_verification", return_value=False), \
             patch("app.tools.order_create.get_admin_api_client") as gc:
            gc.return_value.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
            _with_library(gc.return_value, 99.5)
            result = await tool.execute(context=agent_ctx, customer_name="张三",
                                        customer_phone="13800138000", items=valid_items)
        assert result.success is True


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
        _with_library(mock_client, 99.5)
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
        _with_library(mock_client, 99.5)
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
        _with_library(mock_client, 99.5)
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
        _with_library(mock_client, 50.0, name="窗帘", pid="pid-1")
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

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_payload_carries_order_line_craft_spec_keys(self, mock_get_client, tool, agent_ctx):
        """下单行要素必须**真的**发到服务端（issue #4362，S1）。

        判据：真值源 §1 的 11 个要素里，此前只有 3 个有 schema 声明 ⇒ 加工类型/开数/褶距/对花/转角
        **无处可写**；`processing_info` 是整体透传的 ⇒ 只要模型填了、schema 认了，就必须原样上行
        （服务端 `OrderLineCraftFields.materialize` 再把它落到 `order_items` 的列上）。
        """
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
        _with_library(mock_client, 50.0, name="窗帘", pid="pid-1")
        mock_get_client.return_value = mock_client

        items = [{
            "product_name": "窗帘",
            "quantity": 3,
            "unit_price": 50,
            "subtotal": 150,
            "product_id": "pid-1",
            "processing_info": {
                "colorName": "米白", "sellingMethod": "bulk_cut",
                "curtainType": "纱帘", "craft": "打孔", "openCount": 4,
                "cuttingMode": "定高买宽", "isShaped": False, "pleatSpacing": 0.1,
                "hasPattern": False, "corner": "转角",
                "pleat_count": 48, "fullness": 2.0, "fullness_actual": 1.86,
            },
        }]

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=items,
        )

        assert result.success is True
        pi = mock_client.post.call_args.kwargs["json_data"]["items"][0]["processingInfo"]
        assert pi["curtainType"] == "纱帘"
        assert pi["craft"] == "打孔"
        assert pi["openCount"] == 4
        assert pi["cuttingMode"] == "定高买宽"
        assert pi["isShaped"] is False
        assert pi["pleatSpacing"] == 0.1
        assert pi["hasPattern"] is False
        assert pi["corner"] == "转角"
        assert pi["pleat_count"] == 48
        assert pi["fullness"] == 2.0
        assert pi["fullness_actual"] == 1.86

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_checklist_field_ids_are_normalized_to_craft_spec_keys(
            self, mock_get_client, tool, agent_ctx):
        """C 端小布按**清单 id** 采集的字段，必须被归一成工艺规格键后上行（issue #4362，S1）。

        病根：`curtain_checklist` 问到的字段只活在会话的 collector 字典里（**零消费者**）
        ⇒ 会话结束即丢。归一实现只有一处（`curtain_checklist.to_craft_spec`）；
        这里钉的是「order_create 真的调它」—— 断言落在**上行 payload** 上，不是「代码里有这行」。
        """
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
        _with_library(mock_client, 50.0, name="窗帘", pid="pid-1")
        mock_get_client.return_value = mock_client

        items = [{
            "product_name": "窗帘",
            "quantity": 3,
            "unit_price": 50,
            "subtotal": 150,
            "product_id": "pid-1",
            "processing_info": {
                "sellingMethod": "bulk_cut",
                # 清单 id（snake_case，C 端小布的词汇）
                "curtain_type": "纱帘", "open_count": 4, "is_shaped": False,
                "pleat_spacing": 0.1, "has_pattern": True, "window_type": "转角",
            },
        }]

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=items,
        )

        assert result.success is True
        pi = mock_client.post.call_args.kwargs["json_data"]["items"][0]["processingInfo"]
        assert pi["curtainType"] == "纱帘"
        assert pi["openCount"] == 4
        assert pi["isShaped"] is False
        assert pi["pleatSpacing"] == 0.1
        assert pi["hasPattern"] is True
        assert pi["corner"] == "转角"
        # 归一**不覆盖**已给 canonical 键的值（只做键改名，不做业务推导）
        assert pi["sellingMethod"] == "bulk_cut"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_canonical_keys_win_over_checklist_aliases(self, mock_get_client, tool, agent_ctx):
        """同一事实两种写法同时出现 ⇒ **canonical 键优先**（清单别名不得盖掉显式值）。"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "o1"}})
        _with_library(mock_client, 50.0, name="窗帘", pid="pid-1")
        mock_get_client.return_value = mock_client

        items = [{
            "product_name": "窗帘",
            "quantity": 3,
            "unit_price": 50,
            "subtotal": 150,
            "product_id": "pid-1",
            "processing_info": {
                "sellingMethod": "bulk_cut",
                "curtainType": "布帘", "curtain_type": "纱帘",
            },
        }]

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=items,
        )

        assert result.success is True
        pi = mock_client.post.call_args.kwargs["json_data"]["items"][0]["processingInfo"]
        assert pi["curtainType"] == "布帘"


class TestOrderCreateFailure:
    """创建订单失败/异常路径"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_post_failure(self, mock_get_client, tool, agent_ctx, valid_items):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": False, "error": {"message": "库存不足"}})
        _with_library(mock_client, 99.5)
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
        _with_library(mock_client, 99.5)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000", items=valid_items,
        )

        assert result.success is False
        assert result.error == "tool_execution_failed"
