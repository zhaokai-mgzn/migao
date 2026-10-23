# case_ids: PR-074
"""
商品图生成工具（issue #7541）单测

钉住五条口径：
1. **入口 = 已选商品**：`product_id` 必填，缺参 / `kind` 越界 ⇒ fail-closed 且**零外部调用**；
2. **样图 = 该商品主图**：没有主图（或主图不是可访问的完整地址）⇒ **可行动拒绝**，不编造、
   不降级去调生图内核；
3. **不落库**：全程只 `GET /api/admin/products/{id}` —— 没有任何写端点调用；
4. 🔴 **失败语义如实**：`ImageGenerationUnavailable`（含「模型接不了这类请求」）与
   `ImageGenerationQuotaExceeded` **可区分**，前者绝不说成「额度用尽」；
5. **卡发射条件**：成功**且真有 `image_url`** 才发卡；失败 / 空图不发卡。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.chat import _detect_card_type, _should_send_card
from app.images.generator import (
    ImageGenerationError,
    ImageGenerationQuotaExceeded,
    ImageGenerationUnavailable,
)
from app.tools.base import ToolContext
from app.tools.product_image_generate import ProductImageGenerateTool

SAMPLE_IMAGE = "https://img.example.com/main.jpg"


def _context(permissions=("*",), role="admin") -> ToolContext:
    return ToolContext(
        tenant_id=1,
        user_id="user_001",
        session_id="sess_image_gen_001",
        role=role,
        permissions=list(permissions),
    )


def _product(**overrides):
    data = {
        "id": "prod_001",
        "tenantId": 1,
        "name": "高遮光雪尼尔窗帘",
        "mainImage": SAMPLE_IMAGE,
        "images": [SAMPLE_IMAGE],
    }
    data.update(overrides)
    return data


@pytest.fixture
def tool():
    return ProductImageGenerateTool()


def _mock_client(data=None, success=True, error_code=None):
    client = AsyncMock()
    response = {"success": success, "data": data}
    if not success:
        response["error"] = {"code": error_code or "INTERNAL_ERROR", "message": "查询失败"}
    client.get = AsyncMock(return_value=response)
    return client


def _patch_all(client):
    """同时替换 admin-api 客户端与生图内核（后者断言「有没有真的去生图」）。"""
    return (
        patch("app.tools.product_image_generate.get_admin_api_client", return_value=client),
        patch("app.tools.product_image_generate.generate_product_image",
              new=AsyncMock(return_value={"image_url": "https://out.example.com/1.jpg",
                                          "model": "qwen-image-3.0"})),
    )


class TestToolContract:
    """工具面契约：只读、仅 B 端、权限码与商品读端点同码。"""

    def test_tool_is_readonly_and_b_end_only(self, tool):
        assert tool.read_only is True
        assert tool.c_end_reachable is False
        assert tool.required_permissions == ["product:list"]

    def test_parameters_declare_required_product_id_and_kind_enum(self, tool):
        params = tool.parameters
        assert params["required"] == ["product_id"]
        assert params["properties"]["kind"]["enum"] == ["main", "texture", "craft", "scene"]
        assert params["properties"]["kind"]["default"] == "main"

    def test_description_is_b_side_only(self, tool):
        """散文口径：B 端工具不得写成「顾客也能用」（否则模型会对 C 端谎报能力）。"""
        assert "product_search" in tool.description  # 前置：先定位商品
        assert "营销文案" in tool.description  # 边界：不写文案（文案走 marketing_poster）
        assert "READONLY" in tool.description


class TestParameterValidation:
    """缺参 / 越界 ⇒ 立刻失败，且**零外部调用**（不查商品、不生图）。"""

    @pytest.mark.asyncio
    async def test_missing_product_id_is_rejected_without_any_call(self, tool):
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch as mock_get, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="   ")

        assert result.success is False
        assert result.missing_params == ["product_id"]
        assert "商品" in (result.message or "")
        mock_get.assert_not_called()
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_kind_is_rejected_without_any_call(self, tool):
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch as mock_get, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_001", kind="poster")

        assert result.success is False
        assert result.missing_params == ["kind"]
        assert "main" in (result.message or "")
        mock_get.assert_not_called()
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_permission_denied_blocks_before_fetch(self, tool):
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch as mock_get, generate_patch as mock_gen:
            result = await tool.execute(context=_context(permissions=[], role="viewer"),
                                        product_id="prod_001")

        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get.assert_not_called()
        mock_gen.assert_not_awaited()


class TestSampleImage:
    """样图只来自该商品档案；取不到 ⇒ 可行动拒绝（不拿别的商品凑、不凭空编造）。"""

    @pytest.mark.asyncio
    async def test_missing_main_image_is_actionable_rejection(self, tool):
        client = _mock_client(_product(mainImage=None, images=[]))
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert result.error == "IMAGE_SOURCE_MISSING"
        assert "主图" in (result.message or "")
        assert "商品管理" in (result.suggestion or "")   # 可行动：去后台上传
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_relative_image_path_is_not_sent_to_generator(self, tool):
        """相对路径 / 本地文件 ⇒ 不拼域名去猜，按「样图不可用」如实拒绝。"""
        client = _mock_client(_product(mainImage="/uploads/2026/10/x.jpg", images=[]))
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert result.error == "IMAGE_SOURCE_MISSING"
        assert "图片地址" in (result.suggestion or "")
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_main_image_wins_over_images_list(self, tool):
        client = _mock_client(_product(mainImage="https://img.example.com/main.jpg",
                                       images=["https://img.example.com/other.jpg"]))
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            await tool.execute(context=_context(), product_id="prod_001")

        kwargs = mock_gen.await_args.kwargs
        assert kwargs["image_url"] == SAMPLE_IMAGE
        assert kwargs["product_name"] == "高遮光雪尼尔窗帘"

    @pytest.mark.asyncio
    async def test_falls_back_to_first_image_when_main_image_absent(self, tool):
        client = _mock_client(_product(mainImage=None,
                                       images=["https://img.example.com/first.jpg"]))
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            await tool.execute(context=_context(), product_id="prod_001")

        assert mock_gen.await_args.kwargs["image_url"] == "https://img.example.com/first.jpg"


class TestSuccessPayload:
    """成功载荷 = 卡载荷：`{image_url, model, product: {id, name, kind}}`，且**不落库**。"""

    @pytest.mark.asyncio
    async def test_success_returns_card_payload(self, tool):
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch:
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is True
        assert result.data == {
            "image_url": "https://out.example.com/1.jpg",
            "model": "qwen-image-3.0",
            "product": {"id": "prod_001", "name": "高遮光雪尼尔窗帘", "kind": "main"},
        }
        assert "高遮光雪尼尔窗帘" in (result.message or "")

    @pytest.mark.asyncio
    async def test_kind_is_passed_through_to_kernel(self, tool):
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_001", kind="texture")

        assert mock_gen.await_args.kwargs["kind"] == "texture"
        assert result.data["product"]["kind"] == "texture"
        assert "材质" in (result.message or "")

    @pytest.mark.asyncio
    async def test_no_write_endpoint_is_called(self, tool):
        """**不落库 / 不写表单**：只有一次 GET，且没有任何写方法被调用。"""
        client = _mock_client(_product())
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch:
            await tool.execute(context=_context(), product_id="prod_001")

        client.get.assert_awaited_once()
        assert client.get.await_args.args[0] == "/api/admin/products/prod_001"
        for method in ("post", "put", "patch", "delete"):
            assert not getattr(client, method).called, f"工具不得调用写端点 {method.upper()}"

    @pytest.mark.asyncio
    async def test_cross_tenant_product_is_treated_as_not_found(self, tool):
        client = _mock_client(_product(tenantId=2))
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert "未找到" in (result.message or "")
        mock_gen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_product_not_found_is_actionable(self, tool):
        client = _mock_client(None, success=False, error_code="NOT_FOUND")
        get_client_patch, generate_patch = _patch_all(client)
        with get_client_patch, generate_patch as mock_gen:
            result = await tool.execute(context=_context(), product_id="prod_404")

        assert result.success is False
        assert "product_search" in (result.suggestion or "")
        mock_gen.assert_not_awaited()


class TestFailureSemantics:
    """🔴 「模型不接这类请求」≠「额度用尽」—— 两个失败码必须可区分，且都不静默。"""

    @pytest.mark.asyncio
    async def test_unavailable_is_not_reported_as_quota(self, tool):
        client = _mock_client(_product())
        get_client_patch, _ = _patch_all(client)
        with get_client_patch, patch(
            "app.tools.product_image_generate.generate_product_image",
            new=AsyncMock(side_effect=ImageGenerationUnavailable("qwen-mt-image-2.0: InvalidParameter")),
        ):
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert result.error == "IMAGE_GEN_UNAVAILABLE"
        assert "额度" not in (result.message or "")
        assert "额度" in (result.suggestion or "")  # 明确点出「这不是额度问题」
        assert "商品管理" in (result.suggestion or "")  # 可行动出路

    @pytest.mark.asyncio
    async def test_quota_exceeded_is_its_own_code(self, tool):
        client = _mock_client(_product())
        get_client_patch, _ = _patch_all(client)
        with get_client_patch, patch(
            "app.tools.product_image_generate.generate_product_image",
            new=AsyncMock(side_effect=ImageGenerationQuotaExceeded("所有模型均不可用")),
        ):
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert result.error == "IMAGE_GEN_QUOTA_EXCEEDED"
        assert "额度" in (result.message or "")

    @pytest.mark.asyncio
    async def test_generic_generation_error_has_its_own_code(self, tool):
        client = _mock_client(_product())
        get_client_patch, _ = _patch_all(client)
        with get_client_patch, patch(
            "app.tools.product_image_generate.generate_product_image",
            new=AsyncMock(side_effect=ImageGenerationError("HTTP 500")),
        ):
            result = await tool.execute(context=_context(), product_id="prod_001")

        assert result.success is False
        assert result.error == "IMAGE_GEN_FAILED"
        assert result.suggestion

    @pytest.mark.asyncio
    async def test_same_text_alone_would_not_distinguish(self, tool):
        """判据自证：两个失败码**确实不同**（不是同一句话换个地方）。"""
        codes = set()
        for exc in (ImageGenerationUnavailable("x"), ImageGenerationQuotaExceeded("x")):
            client = _mock_client(_product())
            get_client_patch, _ = _patch_all(client)
            with get_client_patch, patch(
                "app.tools.product_image_generate.generate_product_image",
                new=AsyncMock(side_effect=exc),
            ):
                result = await tool.execute(context=_context(), product_id="prod_001")
            codes.add(result.error)
        assert codes == {"IMAGE_GEN_UNAVAILABLE", "IMAGE_GEN_QUOTA_EXCEEDED"}


class TestCardEmission:
    """卡发射点：`_detect_card_type` 映射 + 「成功且有图才发卡」。"""

    def test_detect_card_type_maps_to_generated_image(self):
        assert _detect_card_type("product_image_generate", {}) == "generated_image"

    def test_card_is_sent_only_with_a_real_image_url(self):
        ok = {"success": True, "data": {"image_url": SAMPLE_IMAGE, "product": {"id": "p"}}}
        assert _should_send_card("product_image_generate", ok) is True

        no_url = {"success": True, "data": {"image_url": "  ", "product": {"id": "p"}}}
        assert _should_send_card("product_image_generate", no_url) is False

        empty = {"success": True, "data": {}}
        assert _should_send_card("product_image_generate", empty) is False

    @pytest.mark.asyncio
    async def test_failed_result_never_emits_card(self, tool):
        """注入式：失败结果即使带 image_url 也不发卡（success=False 是硬闸）。"""
        failed = {"success": False, "data": {"image_url": SAMPLE_IMAGE}}
        assert _should_send_card("product_image_generate", failed) is False
