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


class TestCheckPermissionFineGrained:
    """细粒度权限检查测试 — required_permissions 字段"""

    @pytest.fixture
    def admin_tool(self):
        """创建一个需要 employee:list 权限的工具"""
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        tool.required_permissions = ["employee:list"]
        return tool

    def test_admin_role_with_star_permission_passes(self, admin_tool):
        """admin 角色 + * 通配符权限 → 通过"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=["*"])
        assert admin_tool.check_permission(ctx) is True

    def test_admin_role_with_matching_permission_passes(self, admin_tool):
        """admin 角色 + 精确匹配权限码 → 通过"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=["employee:list"])
        assert admin_tool.check_permission(ctx) is True

    def test_admin_role_with_non_matching_permission_fails(self, admin_tool):
        """admin 角色 + 不匹配权限码 → 拒绝"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=["order:list"])
        assert admin_tool.check_permission(ctx) is False

    def test_admin_role_with_empty_permissions_fails(self, admin_tool):
        """admin 角色 + 空权限列表 → 拒绝（required_permissions 没匹配）"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=[])
        assert admin_tool.check_permission(ctx) is False

    def test_wrong_role_with_star_permission_fails(self, admin_tool):
        """非允许角色（customer）+ * 通配符 → 拒绝（角色检查先失败）"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="customer", permissions=["*"])
        assert admin_tool.check_permission(ctx) is False

    def test_backward_compat_empty_required_permissions(self):
        """required_permissions 为空时向后兼容 — 不检查细粒度权限"""
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        # 未设置 required_permissions，默认为 []
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=[])
        assert tool.check_permission(ctx) is True  # role 检查通过，无细粒度要求

    def test_tenant_admin_role_with_matching_permission(self):
        """tenant_admin 角色 + 匹配权限 → 通过"""
        from app.tools.employee_manage import EmployeeManageTool
        tool = EmployeeManageTool()
        tool.required_permissions = ["employee:list"]
        ctx = ToolContext(tenant_id=1, user_id="u1", role="tenant_admin",
                          permissions=["employee:list", "order:list"])
        assert tool.check_permission(ctx) is True

    def test_customer_role_blocked_by_employee_tool(self):
        """customer 角色被 employee_manage 工具拒绝（角色不匹配）"""
        from app.tools.employee_manage import EmployeeManageTool
        tool = EmployeeManageTool()
        # EmployeeManageTool.allowed_roles = ["admin", "tenant_admin"]
        ctx = ToolContext(tenant_id=1, user_id="u1", role="customer",
                          permissions=["employee:list"])
        assert tool.check_permission(ctx) is False

    def test_permissions_default_to_empty_list(self):
        """ToolContext 默认 permissions 为空列表"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        assert ctx.permissions == []
