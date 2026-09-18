"""ProductManageTool 单元测试 — 商品创建/更新/上下架。

对应 app/tools/product_manage.py 的 create/update/toggle_status 三条 action，
覆盖正常路径、参数校验、camelCase 字段映射、异常泛化兜底。
"""
# case_ids: PR-007, PR-008, PR-009
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.tools.product_manage import ProductManageTool


@pytest.fixture
def tool():
    return ProductManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.post = AsyncMock()
    client.patch = AsyncMock()
    client.put = AsyncMock()
    return client


class TestProductPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestProductCreate:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create")
        assert result.success is False
        assert "缺少商品名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_camel_case_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            name="窗帘",
            category_id="cat-1",
            price=100.5,
            stock_quantity=99,
            selling_methods=["bulk_cut"],
            door_widths=["2.8米"],
            sku_code="SKU-1",
            pricing_type="per_meter",
        )

        assert result.success is True
        assert result.data["product_id"] == "p-1"

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["tenant_id"] == admin_tool_context.tenant_id
        assert call_kwargs["user_id"] == admin_tool_context.user_id
        json_data = call_kwargs["json_data"]
        # 字段必须为 camelCase，且 stock 强制 int
        assert json_data["categoryId"] == "cat-1"
        assert json_data["basePrice"] == 100.5
        assert json_data["stock"] == 99
        assert isinstance(json_data["stock"], int)
        # issue #4371：加工项与商品解耦 ⇒ create payload 不再有这两个键
        assert "processingItemIds" not in json_data
        assert "processingItemConfigs" not in json_data
        assert json_data["sellingMethods"] == ["bulk_cut"]
        assert json_data["doorWidths"] == ["2.8米"]
        assert json_data["skuCode"] == "SKU-1"
        assert json_data["pricingType"] == "per_meter"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": False, "error": {"message": "商品名重复"}, "suggestion": "换一个名字",
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert result.error == "商品名重复"
        assert "创建商品失败" in result.message
        assert result.suggestion == "换一个名字"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_4xx_suggestion_reaches_tool_result(
        self, mock_get_client, tool, admin_tool_context
    ):
        """**端到端**：admin-api 400 + 服务端 `suggestion` ⇒ `ToolResult.suggestion` 必须是它。

        上一行 `test_create_failure_passthrough` 直接喂 dict 给工具（绕过 `http_client`），
        所以它对 A3（4xx 分支丢字段）**不构成覆盖** —— 这正是缺陷能长期存活的原因。
        本用例用**真 `AdminApiClient`**（只 mock 底层 httpx 响应），走
        `http_client._request` 的 4xx 分支。修前 `suggestion` 被丢弃 ⇒ 落到工具兜底文案
        「请检查必填字段是否完整」⇒ 断言可判红（断言**值**，不是断言"非空"：兜底文案
        本身非空，写"非空"就是不会红的空断言）。
        """
        from app.utils.http_client import AdminApiClient

        real_client = AdminApiClient(base_url="http://admin-api.test", service_token="tok")
        real_client._client = AsyncMock()
        real_client._client.is_closed = False
        real_client._client.request = AsyncMock(
            return_value=httpx.Response(
                400,
                request=httpx.Request("POST", "http://admin-api.test/api/admin/agent/products"),
                json={"success": False,
                      "error": {"code": "PRODUCT_NAME_DUPLICATE", "message": "商品名已存在"},
                      "suggestion": "换一个商品名后重试"},
            )
        )
        mock_get_client.return_value = real_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")

        assert result.success is False
        assert result.error == "商品名已存在"
        assert result.suggestion == "换一个商品名后重试"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_4xx_without_suggestion_keeps_default_wording(
        self, mock_get_client, tool, admin_tool_context
    ):
        """负例：服务端 400 **没带** `suggestion` 时，失败话术与 fallback 不得回归。"""
        from app.utils.http_client import AdminApiClient

        real_client = AdminApiClient(base_url="http://admin-api.test", service_token="tok")
        real_client._client = AsyncMock()
        real_client._client.is_closed = False
        real_client._client.request = AsyncMock(
            return_value=httpx.Response(
                422,
                request=httpx.Request("POST", "http://admin-api.test/api/admin/agent/products"),
                json={"success": False, "error": {"code": "VALIDATION", "message": "参数不合法"}},
            )
        )
        mock_get_client.return_value = real_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")

        assert result.success is False
        assert result.error == "参数不合法"
        assert result.message == "创建商品失败：参数不合法"
        assert result.suggestion == "请检查必填字段是否完整"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_2xx_unchanged_by_passthrough(
        self, mock_get_client, tool, admin_tool_context
    ):
        """负例（R2）：原本合法的**成功**响应仍必须原样返回 —— 透传只动失败分支。"""
        from app.utils.http_client import AdminApiClient

        real_client = AdminApiClient(base_url="http://admin-api.test", service_token="tok")
        real_client._client = AsyncMock()
        real_client._client.is_closed = False
        real_client._client.request = AsyncMock(
            return_value=httpx.Response(
                200,
                request=httpx.Request("POST", "http://admin-api.test/api/admin/agent/products"),
                json={"success": True, "data": {"id": "p-9"},
                      "warnings": ["skuCode 已存在，系统自动重新生成"]},
            )
        )
        mock_get_client.return_value = real_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")

        assert result.success is True
        assert result.data == {"product_id": "p-9", "name": "窗帘"}
        assert result.suggestion is None
        assert "skuCode 已存在" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_allow_return_restock_transmitted(self, mock_get_client, tool, admin_tool_context, mock_client):
        """create 透传 allowReturnRestock（#2991 建品场景，与 product_update 互补）。"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", name="窗帘", allow_return_restock=True
        )
        assert result.success is True
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["allowReturnRestock"] is True

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_allow_return_restock_default_omitted(self, mock_get_client, tool, admin_tool_context, mock_client):
        """不传 allow_return_restock 时请求体不含该字段（缺省 false 由 admin-api 处理）。"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client
        await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        json_data = mock_client.post.call_args[1]["json_data"]
        assert "allowReturnRestock" not in json_data

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_warnings_appended(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "p-1"},
            "warnings": ["skuCode 已存在，系统自动重新生成"],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is True
        assert "⚠️" in result.message
        assert "skuCode 已存在" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_blank_category_id_omitted(self, mock_get_client, tool, admin_tool_context, mock_client):
        """空分类（''/空白）不下发 categoryId（#3665 冒烟 B1）：
        后端空串会被 BeanUtils 写进实体 → products_category_id_fkey 违例（500）。
        create 走真值判断，口径必须与 update 一致：空串不下发。"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        for blank in ("", "   "):
            mock_client.post.reset_mock()
            result = await tool.execute(
                context=admin_tool_context, action="create", name="窗帘", category_id=blank
            )
            assert result.success is True
            assert "categoryId" not in mock_client.post.call_args[1]["json_data"], (
                f"空分类 {blank!r} 不应下发 categoryId"
            )


class TestProductUpdate:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_missing_product_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", name="新名字")
        assert result.success is False
        assert "缺少商品 ID" in result.error
        mock_client.patch.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_no_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", product_id="p-1")
        assert result.success is False
        assert "没有需要更新的字段" in result.error
        mock_client.patch.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.patch = AsyncMock(return_value={"success": False, "error": {"message": "商品不存在"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="update", product_id="p-1", name="新名字")
        assert result.success is False
        assert result.error == "商品不存在"
        assert "更新商品失败" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_only_non_none_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            product_id="p-1",
            name="新名字",
            price=88.0,
            stock_quantity=5,
        )

        assert result.success is True
        assert result.data["updated_fields"] == ["name", "basePrice", "stock"]

        call_kwargs = mock_client.patch.call_args[1]
        json_data = call_kwargs["json_data"]
        assert json_data == {"name": "新名字", "basePrice": 88.0, "stock": 5}
        assert "categoryId" not in json_data
        assert "description" not in json_data

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_blank_category_id_omitted(self, mock_get_client, tool, admin_tool_context, mock_client):
        """空分类（''/空白）不下发 categoryId（#3665 冒烟 B1，update 路径）。

        修复前用 `if category_id is not None` → 空串照样透传 → 后端 resolveCategoryId('') 返回 null
        → 422「无法找到匹配的分类：」（或 BeanUtils 写 '' 触发 FK 违例）。
        与 create 的真值判断口径统一：空串不下发。"""
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        for blank in ("", "   "):
            mock_client.patch.reset_mock()
            result = await tool.execute(
                context=admin_tool_context, action="update", product_id="p-1",
                name="新名字", category_id=blank,
            )
            assert result.success is True
            json_data = mock_client.patch.call_args[1]["json_data"]
            assert "categoryId" not in json_data, f"空分类 {blank!r} 不应下发 categoryId"
            assert result.data["updated_fields"] == ["name"]

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_valid_category_id_preserved(self, mock_get_client, tool, admin_tool_context, mock_client):
        """合法分类 id 原样下发（空串归一化不得误伤正常值）。"""
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        await tool.execute(
            context=admin_tool_context, action="update", product_id="p-1", category_id="cat-1"
        )

        json_data = mock_client.patch.call_args[1]["json_data"]
        assert json_data["categoryId"] == "cat-1"


class TestProductUpdateStatusGuard:
    """issue #3899：update 收到 status 必须显式拒绝并引导走 toggle_status，禁止静默忽略。

    根因：_update_product 参数 schema 声明 status 但实现不映射（json_data 无 status 键；
    Java updateProduct 也刻意恢复原状态，状态只能走 updateProductStatus 状态机）
    → LLM 把"下架"放进 update args → update 报 success 但 status 没变
    → 复查对不上就误判"未生效、去后台手动操作"。
    修复：status 非空时显式失败（success=False），错误信息引导改用 action=toggle_status。
    """

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_with_status_rejected_not_silently_ignored(
        self, mock_get_client, tool, admin_tool_context, mock_client
    ):
        """update 带 status → 显式失败 + 引导 toggle_status，且不发 PATCH（禁止半成功写入）。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            product_id="p-1",
            name="新名字",
            status="off_sale",
        )

        assert result.success is False, "update 带 status 必须显式失败，禁止报 success 后状态没变"
        assert "toggle_status" in result.error, "错误必须引导用 action=toggle_status"
        assert result.message and "未执行" in result.message, "失败消息必须明确状态未变更"
        mock_client.patch.assert_not_called(), "拒绝时不得发 PATCH（否则字段已写但状态没变 = 半成功写入）"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_status_only_rejected(self, mock_get_client, tool, admin_tool_context, mock_client):
        """只传 status 无其他字段 → 同样显式拒绝，不能静默成功。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", product_id="p-1", status="on_sale"
        )

        assert result.success is False
        assert "toggle_status" in result.error
        mock_client.patch.assert_not_called()

    def test_description_includes_status_guard_guidance(self, tool):
        """description 必须点明：状态变更走 toggle_status，update 不处理 status。"""
        assert "toggle_status" in tool.description
        assert "update" in tool.description

    def test_description_includes_recheck_guidance(self, tool):
        """issue #3899：写后复查指引——写成功返回后复查显示旧值要如实说明，禁止断言"未落库"。"""
        assert "已写入" in tool.description, "description 必须让 agent 按写结果如实说明"
        assert "读取延迟" in tool.description, "description 必须提示旧值可能为读取延迟"
        assert "未落库" in tool.description, "description 必须明令禁止断言'未落库'"


class TestProductSkillRecheckGuidance:
    """issue #3899：product_skill 系统提示必须含写后复查指引（同族 #3885 已在 delete_item 修）。"""

    def test_product_system_prompt_includes_recheck_guidance(self):
        from app.graph.skills.product_skill import PRODUCT_SYSTEM_PROMPT

        assert "已写入" in PRODUCT_SYSTEM_PROMPT
        assert "读取延迟" in PRODUCT_SYSTEM_PROMPT
        assert "toggle_status" in PRODUCT_SYSTEM_PROMPT


class TestProductToggleStatus:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_missing_product_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_status", status="on_sale")
        assert result.success is False
        assert "缺少商品 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="sold_out")
        assert result.success is False
        assert "无效的商品状态" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_on_sale(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {"status": "on_sale"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="on_sale")
        assert result.success is True
        assert "已上架" in result.message
        assert mock_client.put.call_args[0][0] == "/api/admin/products/p-1/status"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_off_sale(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {"status": "off_sale"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="off_sale")
        assert result.success is True
        assert "已下架" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": False, "error": {"message": "商品不存在"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="on_sale")
        assert result.success is False
        assert result.error == "商品不存在"
        assert "商品状态更新失败" in result.message


class TestProductException:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_execute_exception_generic(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert "boom" not in (result.message or "")


class TestProductManageSchemaContract:
    """schema ↔ 后端真实契约对齐（工具审计 A4/B1）。

    背景：`AgentProductCreateRequest` 无 `skus` 字段（下发即丢弃），schema 却声明该参数
    并诱导 LLM 传；`action` enum 曾含运行时必拒的死分支 `manage_processing_items`，
    且描述只有「操作类型」三字。

    issue #4371（商品↔加工项解耦）：`processingItemIds` / `processingItemConfigs`
    已从 Java DTO 与本工具一并移除（工具描述里的加工项铁律同删）。
    """

    # AgentProductCreateRequest 的全部字段（Java DTO 单一事实源），payload 键必须落在其中
    AGENT_CREATE_FIELDS = {
        "name", "categoryId", "basePrice", "skuCode", "description", "brand", "unit",
        "pricingType", "stock", "status", "images", "detailImages", "colors",
        "sellingMethods", "doorWidths",
        "specifications", "stockDeductionMode", "allowReturnRestock",
    }

    def test_skus_param_removed_from_schema_and_signature(self, tool):
        """`skus` 不在后端 DTO 字段里 → 不得继续声明（否则 LLM 按 schema 传、被静默丢弃）"""
        import inspect

        assert "skus" not in tool.parameters["properties"]
        assert "skus" not in inspect.signature(ProductManageTool.execute).parameters

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_payload_keys_are_all_backend_fields(
        self, mock_get_client, tool, admin_tool_context, mock_client
    ):
        """create payload 的每个键都必须是 AgentProductCreateRequest 的字段（无 skus / 无加工项）"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        await tool.execute(
            context=admin_tool_context,
            action="create",
            name="窗帘",
            price=100.0,
            colors=["米白"],
        )

        body = mock_client.post.call_args[1]["json_data"]
        assert "skus" not in body
        # issue #4371：Java DTO 已无这两个字段 ⇒ payload 也不得再有
        assert "processingItemIds" not in body
        assert "processingItemConfigs" not in body
        unknown = set(body) - self.AGENT_CREATE_FIELDS
        assert unknown == set(), f"create payload 含后端 DTO 不认的字段: {unknown}"

    def test_action_enum_subset_of_valid_actions(self, tool):
        """action enum 不得含运行时必拒分支（`manage_processing_items` 已拆出独立工具）"""
        from app.tools.product_manage import VALID_ACTIONS

        enum = tool.parameters["properties"]["action"]["enum"]
        assert set(enum) <= VALID_ACTIONS

    def test_action_description_covers_each_branch(self, tool):
        """action 描述必须逐个说明分支语义（照 customer_manage.py 的写法）"""
        action_prop = tool.parameters["properties"]["action"]
        desc = action_prop["description"]
        for member in action_prop["enum"]:
            assert member in desc, f"action 描述缺少分支 {member} 的语义说明"
        # 不能停留在零信息的「操作类型」占位
        assert desc.strip() != "操作类型"
        assert len(desc) >= 40
