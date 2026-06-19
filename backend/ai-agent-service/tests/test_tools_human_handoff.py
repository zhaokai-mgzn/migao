"""HumanHandoffTool 单元测试 — 转人工客服"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.tools.base import ToolContext, ToolResult
from app.tools.human_handoff import HumanHandoffTool


@pytest.fixture
def ctx():
    return ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="customer")


@pytest.fixture
def tool():
    return HumanHandoffTool()


class TestHumanHandoffBasic:
    """基础结构验证"""

    def test_tool_metadata(self, tool):
        """验证 Tool 元数据正确"""
        assert tool.name == "human_handoff"
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0
        assert tool.read_only is False
        assert tool.destructive is False

    def test_tool_parameters_schema(self, tool):
        """验证 Tool 参数 Schema 结构"""
        assert tool.parameters["type"] == "object"
        props = tool.parameters.get("properties", {})
        assert "reason" in props
        assert "priority" in props
        assert "summary" in props
        assert props["reason"]["type"] == "string"
        assert props["priority"]["type"] == "string"
        assert props["summary"]["type"] == "string"

    def test_get_schema_includes_tags(self, tool):
        """验证 schema 中包含工具类型标注"""
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "human_handoff"
        # 写操作应包含 WRITE 标注
        assert "WRITE" in schema["function"]["description"]

    def test_check_permission_customer(self, tool, ctx):
        """验证 customer 角色有权限"""
        assert tool.check_permission(ctx) is True

    def test_check_permission_agent(self, tool):
        """验证 agent 角色也有权限"""
        agent_ctx = ToolContext(tenant_id=1, user_id="u2", role="agent")
        assert tool.check_permission(agent_ctx) is True


class TestHumanHandoffExecute:
    """执行逻辑验证"""

    @pytest.mark.asyncio
    async def test_execute_basic(self, tool, ctx):
        """基本转人工请求 — 仅 reason"""
        result = await tool.execute(
            ctx,
            reason="顾客要求退款",
        )
        assert result.success is True
        assert result.data is not None
        assert "handoff_id" in result.data
        assert result.data["status"] == "queued"
        assert result.data["reason"] == "顾客要求退款"
        assert "工单号" in result.message

    @pytest.mark.asyncio
    async def test_execute_full_params(self, tool, ctx):
        """全部参数 — reason + priority + summary"""
        result = await tool.execute(
            ctx,
            reason="复杂投诉 — 质量问题",
            priority="high",
            summary="顾客反馈窗帘有异味，要求退货退款，情绪激动",
        )
        assert result.success is True
        assert result.data["priority"] == "high"
        assert result.data["reason"] == "复杂投诉 — 质量问题"
        assert result.data["summary"] == "顾客反馈窗帘有异味，要求退货退款，情绪激动"
        assert "高优先级" in result.message

    @pytest.mark.asyncio
    async def test_execute_default_priority(self, tool, ctx):
        """未传 priority — 默认 normal"""
        result = await tool.execute(
            ctx,
            reason="查询促销活动",
        )
        assert result.success is True
        assert result.data["priority"] == "normal"

    @pytest.mark.asyncio
    async def test_execute_handoff_id_unique(self, tool, ctx):
        """两次调用生成不同的 handoff_id"""
        result1 = await tool.execute(ctx, reason="问题A")
        result2 = await tool.execute(ctx, reason="问题B")
        assert result1.data["handoff_id"] != result2.data["handoff_id"]
