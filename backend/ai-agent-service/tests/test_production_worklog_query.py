"""ProductionWorklogQueryTool 单测 — 加工单「过程明细」查询（issue #4201）。

契约（由 #4201 冻结，#3995 的同族端点）：
  GET /api/admin/agent/production/worklog?order_no={订单号}
  → {"success": true, "data": {"order_no", "processing_order_no", "processing_status",
       "operations": [{"position", "operation_name", "logical_name", "group_name", "seq",
                       "status", "required_qty", "qualified_qty", "rework_qty", "scrap_qty",
                       "is_must_finish", "workers", "last_work_date"}],
       "work_logs": [{"operation_name", "logical_name", "position", "worker_name", "qty",
                      "qualified_qty", "work_type", "work_date"}],
       "totals": {"qualified_qty", "rework_qty", "scrap_qty", "piecework_amount"}}}

仅 B 端：工序报工明细含**报工人与计件金额**（车间/工资面），不对 C 端顾客开放。
投影纪律：端点不下发内部单价/系数 —— 本工具的摘要只转述**数量与金额**，不得自行心算计价。
零真实网络：`get_admin_api_client` 全部 mock。
"""
# case_ids: PG-057
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.production_worklog_query import ProductionWorklogQueryTool

WORKLOG_PATH = "/api/admin/agent/production/worklog"

#: 冻结契约样例（与后端端点 data 结构逐字段一致）——
#: 形态取自「下料（裁剪组）做到哪一步」这一问：一道裁剪工序 + 一道待做工序。
WORKLOG_DATA = {
    "order_no": "ORD-20260917-0001",
    "processing_order_no": "JG-20260917-0001",
    "processing_status": "in_processing",
    "operations": [
        {
            "position": "布帘",
            "operation_name": "精裁-布",
            "logical_name": "精裁",
            "group_name": "裁剪",
            "seq": 1,
            "status": "done",
            "required_qty": 12.0,
            "qualified_qty": 10.0,
            "rework_qty": 2.0,
            "scrap_qty": 0.0,
            "is_must_finish": False,
            "workers": ["王师傅"],
            "last_work_date": "2026-09-20",
        },
        {
            "position": None,
            "operation_name": "外帘装袋",
            "logical_name": "外帘装袋",
            "group_name": "后道",
            "seq": 2,
            "status": "pending",
            "required_qty": 1.0,
            "qualified_qty": 0.0,
            "rework_qty": 0.0,
            "scrap_qty": 0.0,
            "is_must_finish": True,
            "workers": [],
            "last_work_date": None,
        },
    ],
    "work_logs": [
        {
            "operation_name": "精裁-布",
            "logical_name": "精裁",
            "position": "布帘",
            "worker_name": "王师傅",
            "qty": 2.0,
            "qualified_qty": 0.0,
            "work_type": "rework",
            "work_date": "2026-09-20",
        },
        {
            "operation_name": "精裁-布",
            "logical_name": "精裁",
            "position": "布帘",
            "worker_name": "王师傅",
            "qty": 10.0,
            "qualified_qty": 10.0,
            "work_type": "normal",
            "work_date": "2026-09-19",
        },
    ],
    "totals": {
        "qualified_qty": 10.0,
        "rework_qty": 2.0,
        "scrap_qty": 0.0,
        "piecework_amount": 4.0,
    },
}

#: 无加工单/零报工（「未开始」态）—— 端点返回 success=true 的空明细
EMPTY_DATA = {
    "order_no": "ORD-20260917-0001",
    "processing_order_no": None,
    "processing_status": None,
    "operations": [],
    "work_logs": [],
    "totals": {"qualified_qty": 0, "rework_qty": 0, "scrap_qty": 0, "piecework_amount": 0.0},
}


@pytest.fixture
def tool():
    return ProductionWorklogQueryTool()


#: 商户员工 JWT 的 `permissions` claim —— 过程明细端点 = AgentProductionController 类级的
#: `@RequirePermission("order:list")`（与 /progress、/piecework 同一授权面，不新增权限码）。
SELLER_PERMISSIONS = ["order:list"]


@pytest.fixture
def seller_context():
    """B 端商户员工（米宝）上下文 —— 持 `order:list`"""
    return ToolContext(
        tenant_id=1, user_id="agent_001", session_id="sess_wl_1",
        role="operator", permissions=list(SELLER_PERMISSIONS),
    )


@pytest.fixture
def customer_context():
    """C 端顾客（小布）上下文 —— 车间报工明细/计件不对其开放"""
    return ToolContext(tenant_id=1, user_id="customer_001", session_id="sess_wl_2", role="customer")


class TestMetadataContract:
    """Tool 元数据：只读 + 仅 B 端 + description 自带触发/前置/反例/标注"""

    def test_read_only_metadata(self, tool):
        assert tool.name == "production_worklog_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_b_end_only_by_permission_code(self, tool):
        assert tool.required_permissions == ["order:list"], (
            "过程明细端点 = AgentProductionController 类级 order:list（不新增授权面）"
        )
        customer = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        assert tool.check_permission(customer) is False, "C 端顾客必须被拒（报工人/计件不对顾客开放）"

    def test_description_carries_trigger_prereq_counterexample(self, tool):
        desc = tool.description
        assert "【触发】" in desc and "下料" in desc
        assert "【前置】" in desc and "order_no" in desc
        assert "【反例】" in desc and "production_progress_query" in desc
        assert "READONLY" in desc

    def test_parameters_require_order_no(self, tool):
        params = tool.parameters
        assert params["properties"]["order_no"]["type"] == "string"
        assert params["required"] == ["order_no"]


class TestExecuteSuccess:
    """成功路径：透传 data + 冻结契约路径/参数 + LLM 友好摘要（数量口径来自工具返回）"""

    @patch("app.tools.production_worklog_query.get_admin_api_client")
    async def test_query_passes_through_frozen_contract(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(WORKLOG_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is True
        args, kwargs = mock_client.get.call_args
        assert args[0] == WORKLOG_PATH, "路径必须是冻结契约字面量（可静态归属端点）"
        assert kwargs["params"] == {"order_no": "ORD-20260917-0001"}
        assert kwargs["tenant_id"] == 1
        assert kwargs["user_id"] == "agent_001"
        # 数据逐字段透传（**不得**在工具层重算数量/金额 —— 数字的唯一来源是端点返回）
        assert result.data["operations"][0]["qualified_qty"] == 10.0
        assert result.data["operations"][0]["rework_qty"] == 2.0
        assert result.data["operations"][0]["group_name"] == "裁剪"
        assert result.data["operations"][0]["workers"] == ["王师傅"]
        assert result.data["work_logs"][0]["work_type"] == "rework"
        assert result.data["totals"]["piecework_amount"] == 4.0

    @patch("app.tools.production_worklog_query.get_admin_api_client")
    async def test_summary_is_grounded_in_returned_numbers(self, mock_get_client, tool, seller_context):
        """摘要必须由**端点返回的数字**拼出（合格/返工/报废 + 工序数），不得心算/编造。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(WORKLOG_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert "2" in result.summary          # 工序总数（2 道）
        assert "10" in result.summary         # 合格 10
        assert "返工" in result.summary and "报废" in result.summary
        assert "¥4.00" in result.summary      # 计件金额（端点返回的 4.0）

    @patch("app.tools.production_worklog_query.get_admin_api_client")
    async def test_empty_detail_is_not_an_error(self, mock_get_client, tool, seller_context):
        """无加工单/零报工（未开始态）⇒ success=true，摘要如实说「暂无」，不得编造进度。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(EMPTY_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is True
        assert "暂无" in result.summary


class TestExecuteFailure:
    """失败路径：不抛异常、success=False、必须给 suggestion（反幻觉引导）"""

    @patch("app.tools.production_worklog_query.get_admin_api_client")
    async def test_api_business_failure_maps_via_shared_point(
            self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "订单不存在"},
            "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="NOPE")

        assert result.success is False
        assert result.error == "订单不存在"
        assert result.suggestion, "失败必须给 suggestion 引导 LLM 修复"
        # 反幻觉：suggestion 必须禁止编造过程/数量
        assert "编造" in result.suggestion

    @patch("app.tools.production_worklog_query.get_admin_api_client")
    async def test_http_exception_is_caught(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is False
        assert result.suggestion
        assert "编造" in result.suggestion

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_missing_order_no(self, tool, seller_context, missing):
        result = await tool.execute(context=seller_context, order_no=missing)

        assert result.success is False
        assert result.error == "缺少订单号"
        assert "订单号" in result.message
        assert result.suggestion


class TestPermission:
    """权限：按权限码判定（C 端无码 ⇒ 拒；持码商户角色 ⇒ 放行）"""

    async def test_customer_execute_returns_permission_denied(self, tool, customer_context):
        result = await tool.execute(context=customer_context, order_no="ORD-20260917-0001")

        assert result.success is False
        assert result.error == "权限不足"
        assert result.suggestion

    def test_seller_roles_allowed(self, tool):
        """持 `order:list` 的商户角色（含 admin 通配）应可查过程明细。"""
        for role in ("admin", "operator", "customer_service", "sales", "finance"):
            perms = ["*"] if role == "admin" else list(SELLER_PERMISSIONS)
            ctx = ToolContext(
                tenant_id=1, user_id="u_001", session_id="s", role=role, permissions=perms,
            )
            assert tool.check_permission(ctx) is True, f"{role} 持 order:list，应可查过程明细"

    def test_role_without_the_code_is_denied(self, tool):
        """负向：真实商户角色但不持 `order:list` ⇒ 拒绝。"""
        ctx = ToolContext(
            tenant_id=1, user_id="u_002", session_id="s",
            role="product_manager", permissions=["product:list"],
        )
        assert tool.check_permission(ctx) is False
