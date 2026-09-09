"""
KnowledgeSearchTool 单元测试（LLM WIKI 板块 P7，issue #3051）
词条检索工具：命中返回卡片（≤3 条、answer 截断）/ 未命中兜底 / 异常降级 / 权限与参数校验。
"""
# case_ids: API-022, KN-008

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.base import ToolContext


def make_context(tenant_id: int = 1, user_id: str = "u1", role: str = "customer") -> ToolContext:
    return ToolContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        session_id="s1",
    )


def make_client_response(cards):
    return {"success": True, "data": cards}


@pytest.fixture(autouse=True)
def patch_client():
    with patch("app.tools.knowledge_search.get_admin_api_client") as mock:
        yield mock


class TestKnowledgeSearchTool:
    def test_name_and_parameters(self):
        tool = KnowledgeSearchTool()
        assert tool.name == "knowledge_search"
        assert "query" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["query"]

    @pytest.mark.asyncio
    async def test_hit_returns_cards(self, patch_client):
        client = AsyncMock()
        client.get.return_value = make_client_response([
            {"title": "雪尼尔面料会起球吗", "answer": "起球概率较低……" * 20, "category": "faq", "sourceType": "manual"},
            {"title": "雪尼尔保养", "answer": "建议毛球修剪器。", "category": "faq", "sourceType": "template"},
        ])
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="雪尼尔 起球")

        assert result.success is True
        assert result.data["hit"] is True
        assert len(result.data["cards"]) == 2
        assert result.data["cards"][0]["title"] == "雪尼尔面料会起球吗"
        # answer 截断 ≤500 字
        assert len(result.data["cards"][0]["answer"]) <= 500

    @pytest.mark.asyncio
    async def test_miss_returns_hit_false(self, patch_client):
        client = AsyncMock()
        client.get.return_value = make_client_response([])
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="奇怪的问题")

        assert result.success is True
        assert result.data["hit"] is False
        assert "通用行业" in (result.message or "")

    @pytest.mark.asyncio
    async def test_api_failure_returns_error(self, patch_client):
        client = AsyncMock()
        client.get.return_value = {"success": False, "error": {"message": "检索失败"}}
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="雪尼尔")

        assert result.success is False
        assert result.error == "检索失败"

    @pytest.mark.asyncio
    async def test_exception_degrades(self, patch_client):
        client = AsyncMock()
        client.get.side_effect = RuntimeError("boom")
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="雪尼尔")

        assert result.success is False
        assert "暂不可用" in (result.message or "")

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, patch_client):
        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="  ")
        assert result.success is False
        patch_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_passed_to_admin_api(self, patch_client):
        client = AsyncMock()
        client.get.return_value = make_client_response([{"title": "T", "answer": "A", "category": "faq"}])
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        await tool.execute(make_context(), query="遮光等级", category="faq")

        args, kwargs = client.get.call_args
        assert kwargs["params"]["query"] == "遮光等级"
        assert kwargs["params"]["category"] == "faq"
        assert "/api/admin/knowledge/cards/search" in args[0]

    def test_description_has_source_annotation_boundary(self):
        """来源标注边界规则（P2-4，#3076）：📖 标注仅覆盖卡片原文，禁止自补内容混入标注/伪称本店事实。
        防未来 prompt 重构删掉该契约——删规则 = 本测试 fail。"""
        tool = KnowledgeSearchTool()
        desc = tool.description
        assert "来源标注边界" in desc
        assert "仅覆盖卡片原文" in desc
        assert "禁止" in desc and "伪称为本店事实" in desc

    @pytest.mark.asyncio
    async def test_hit_message_carries_annotation_boundary(self, patch_client):
        client = AsyncMock()
        client.get.return_value = make_client_response([
            {"title": "雪尼尔面料会起球吗", "answer": "起球概率较低……", "category": "faq", "sourceType": "manual"},
        ])
        patch_client.return_value = client

        tool = KnowledgeSearchTool()
        result = await tool.execute(make_context(), query="雪尼尔 起球")

        assert result.success is True
        assert result.data["hit"] is True
        # hit message 必须携带边界约束（仅卡片原文可入标注、自补分离、禁伪称）
        assert "仅卡片原文可置于" in (result.message or "")
        assert "伪称本店事实" in (result.message or "")
