"""PieceworkQueryTool 单测 — 计件工资查询（issue #3996 / M4-I）。

契约（由并行包 #3995 冻结）：
  GET /api/admin/agent/production/piecework?worker_name={姓名}&period=YYYY-MM
  → {"success": true, "data": {"worker_name", "period", "total",
       "details": [{"operation", "qty", "amount"}]}}

仅 B 端可见（工人工资不对 C 端顾客开放）。零真实网络：`get_admin_api_client` 全 mock。
"""
# case_ids: CH-041
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.piecework_query import PieceworkQueryTool

PIECEWORK_PATH = "/api/admin/agent/production/piecework"

# 冻结契约样例（与后端端点 data 结构逐字段一致）
PIECEWORK_DATA = {
    "worker_name": "王师傅",
    "period": "2026-09",
    "total": 1234.0,
    "details": [
        {"operation": "韩褶-布", "qty": 120.5, "amount": 964.0},
        {"operation": "打孔", "qty": 90.0, "amount": 270.0},
    ],
}


@pytest.fixture
def tool():
    return PieceworkQueryTool()


#: 商户员工 JWT 的 `permissions` claim（#4106 F3：工具层细粒度门禁按权限码判定）。
#: 计件端点 `/api/admin/agent/production/piecework` 的 `@RequirePermission("order:list")`
#: （AgentProductionController 类级）⇒ 运营岗持码。
SELLER_PERMISSIONS = ["order:list"]


@pytest.fixture
def seller_context():
    """B 端商户员工（米宝）上下文 —— 持 `order:list`（计件端点的权限码）"""
    return ToolContext(
        tenant_id=1, user_id="agent_001", session_id="sess_pw_1",
        role="operator", permissions=list(SELLER_PERMISSIONS),
    )


@pytest.fixture
def customer_context():
    """C 端顾客（小布）上下文 —— 计件工资不对其开放"""
    return ToolContext(tenant_id=1, user_id="customer_001", session_id="sess_pw_2", role="customer")


class TestMetadataContract:
    """Tool 元数据：仅 B 端角色；description 自带触发/前置/反例/标注"""

    def test_read_only_metadata(self, tool):
        assert tool.name == "piecework_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_b_end_only_roles(self, tool):
        """工人工资/人工成本只对**持码的商户员工**开放，C 端必须不可见。

        #4106 后判据不再是角色白名单（会与 admin-api 目录漂移），而是权限码 +
        C 端硬闸。
        """
        assert tool.required_permissions == ["order:list"], "计件端点 = AgentProductionController 的 order:list"
        customer = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        assert tool.check_permission(customer) is False, "C 端顾客必须被拒（工人工资不对顾客开放）"

    def test_description_carries_trigger_prereq_counterexample(self, tool):
        desc = tool.description
        assert "【触发】" in desc and "计件" in desc
        assert "【前置】" in desc and "worker_name" in desc
        assert "【反例】" in desc and "dashboard_stats" in desc
        assert "READONLY" in desc

    def test_parameters_require_worker_name(self, tool):
        params = tool.parameters
        assert params["properties"]["worker_name"]["type"] == "string"
        assert params["properties"]["period"]["type"] == "string"
        assert params["required"] == ["worker_name"]


class TestExecuteSuccess:
    """成功路径：total/details 透传 + LLM 友好摘要 + 调用冻结契约端点"""

    @patch("app.tools.piecework_query.get_admin_api_client")
    async def test_query_with_period(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PIECEWORK_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=seller_context, worker_name="王师傅", period="2026-09")

        assert result.success is True
        args, kwargs = mock_client.get.call_args
        assert args[0] == PIECEWORK_PATH
        assert kwargs["params"] == {"worker_name": "王师傅", "period": "2026-09"}
        assert kwargs["tenant_id"] == 1
        assert kwargs["user_id"] == "agent_001"
        # 汇总 + 明细
        assert result.data["total"] == 1234.0
        assert result.data["period"] == "2026-09"
        assert result.data["details"][1] == {"operation": "打孔", "qty": 90.0, "amount": 270.0}
        # LLM 摘要文案（金额千分位 + 两位小数）
        assert result.summary == "王师傅 2026-09 计件合计 ¥1,234.00"

    @patch("app.tools.piecework_query.get_admin_api_client")
    async def test_period_optional(self, mock_get_client, tool, seller_context):
        """period 不传时不带该参数（由服务端取当月），不得编造月份"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PIECEWORK_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, worker_name="王师傅")

        assert result.success is True
        assert mock_client.get.call_args.kwargs["params"] == {"worker_name": "王师傅"}
        assert result.summary == "王师傅 2026-09 计件合计 ¥1,234.00"


class TestExecuteFailure:
    """失败路径：不抛异常、success=False、必须给 suggestion（反幻觉引导）"""

    @patch("app.tools.piecework_query.get_admin_api_client")
    async def test_api_business_failure(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "WORKER_NOT_FOUND", "message": "未找到该工人"},
            "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, worker_name="查无此人", period="2026-09")

        assert result.success is False
        assert result.message == "查询计件失败，请稍后重试"
        assert result.suggestion, "失败必须给 suggestion 引导 LLM 修复"

    @patch("app.tools.piecework_query.get_admin_api_client")
    async def test_http_exception_is_caught(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, worker_name="王师傅")

        assert result.success is False
        assert result.message == "查询计件失败，请稍后重试"
        assert result.suggestion

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_missing_worker_name(self, tool, seller_context, missing):
        result = await tool.execute(context=seller_context, worker_name=missing)

        assert result.success is False
        assert result.error == "缺少工人姓名"
        assert "姓名" in result.message
        assert result.suggestion

    @patch("app.tools.piecework_query.get_admin_api_client")
    async def test_bad_period_format_rejected_before_call(
            self, mock_get_client, tool, seller_context):
        """period 非法（非 YYYY-MM）→ 参数错误，不发起调用（防把脏参数透传给后端）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PIECEWORK_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, worker_name="王师傅", period="2026/09")

        assert result.success is False
        assert result.error == "月份格式错误"
        assert mock_client.get.call_count == 0


class TestPermission:
    """权限：C 端顾客不可用（按其基类权限校验方式断言）"""

    def test_customer_role_not_allowed(self, tool, customer_context):
        assert tool.check_permission(customer_context) is False

    async def test_customer_execute_returns_permission_denied(self, tool, customer_context):
        result = await tool.execute(context=customer_context, worker_name="王师傅")

        assert result.success is False
        assert result.message == "您没有权限查询计件"
        assert result.suggestion

    def test_seller_roles_allowed(self, tool):
        """持 `order:list` 的商户角色（含 admin 通配）应可查计件。"""
        for role in ("admin", "operator", "customer_service", "sales", "finance"):
            perms = ["*"] if role == "admin" else list(SELLER_PERMISSIONS)
            ctx = ToolContext(
                tenant_id=1, user_id="u_001", session_id="s", role=role, permissions=perms,
            )
            assert tool.check_permission(ctx) is True, f"{role} 持 order:list，应可查计件"

    def test_role_without_the_code_is_denied(self, tool):
        """负向：真实商户角色但不持 `order:list` ⇒ 拒绝。"""
        ctx = ToolContext(
            tenant_id=1, user_id="u_002", session_id="s",
            role="product_manager", permissions=["product:list"],
        )
        assert tool.check_permission(ctx) is False
