"""BaseTool / ToolContext / ToolResult 单元测试"""
import pytest
from app.tools.base import BaseTool, ToolContext, ToolResult


class TestToolContext:
    def test_create_context(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="admin")
        assert ctx.tenant_id == 1
        assert ctx.user_id == "u1"
        assert ctx.role == "admin"

    def test_default_session(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", role="customer")
        assert ctx.session_id is None


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(success=True, data={"key": "val"}, message="ok")
        assert r.success is True
        assert r.data == {"key": "val"}
        assert r.message == "ok"

    def test_failure_result(self):
        r = ToolResult(success=False, error="NOT_FOUND", message="not found",
                       suggestion="try again")
        assert r.success is False
        assert r.error == "NOT_FOUND"
        assert r.suggestion == "try again"


class TestBaseTool:
    def test_concrete_tool_structure(self):
        """验证具体的 tool 子类具备必要属性"""
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        assert tool.name == "validate_input"
        assert isinstance(tool.description, str)
        assert isinstance(tool.parameters, dict)
        assert "type" in tool.parameters
        assert isinstance(tool.allowed_roles, list)

    def test_check_permission_admin(self):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        assert tool.check_permission(ctx) is True

    def test_check_permission_denied(self):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        ctx = ToolContext(tenant_id=1, user_id="u1", role="guest")
        assert tool.check_permission(ctx) is False

    def test_get_schema(self):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "validate_input"
        assert "description" in schema["function"]
