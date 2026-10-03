"""ProcessingOrderQueryTool 单元测试 — 加工单查询（issue #3340）+ 生产交付风险视图（issue #6217 / V2）。

`delivery_risk`（族 3 · 包 4）的**视图语义**判据在 `tests/test_briefing_delivery_risk.py`；
本文件钉它的**工具面**：两条既有端点的字面量归属、跨单取数的有界与并发、
单张进度失败 ⇒ 「未知」（**不是**「没有卡点」）、无真值字段的具名披露、失败可归因。
"""
# case_ids: PG-011, PG-068
import re
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.briefing.delivery_risk import NO_TRUTH_REASONS as RISK_NO_TRUTH_REASONS
from app.tools import processing_order_query as TOOL_MODULE
from app.tools.processing_order_query import (
    DELIVERY_RISK_ORDERS_ENDPOINT,
    DELIVERY_RISK_PROGRESS_ENDPOINT,
    DELIVERY_RISK_PROGRESS_LIMIT,
    ProcessingOrderQueryTool,
    VALID_ACTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

ORDERS = [
    {"processingOrderNo": "JG-1", "orderNo": "ORD-1", "customerName": "张三",
     "processor": "李师傅", "expectedDeliveryDate": "2026-10-05", "status": "in_processing"},
    {"processingOrderNo": "JG-2", "orderNo": "ORD-2", "customerName": "李四",
     "processor": "王师傅", "expectedDeliveryDate": None, "status": "issued"},
]
PROGRESS = {
    "ORD-1": {"order_no": "ORD-1", "expected_delivery_date": "2026-10-05",
              "current_operation": "裁剪", "pending_operations": ["裁剪", "缝制"],
              "total_operations": 10, "done_operations": 4, "progress_percent": 40.0},
}


@pytest.fixture
def tool():
    return ProcessingOrderQueryTool()


@pytest.fixture
def mock_client():
    """与其它工具测试同款：`AsyncMock` 的 `get` 由各用例按端点喂（本文件自带一份，
    不从别处 import —— 判据依赖跨文件夹具会让「谁改了夹具」这件事失去归属）。"""
    client = AsyncMock()
    client.get = AsyncMock()
    return client


class TestQuery:
    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_query_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": [
                {"id": "po-1", "processingOrderNo": "JG-20260912-0001", "orderNo": "ORD-1",
                 "customerName": "张三", "processor": "朝阳加工厂",
                 "expectedDeliveryDate": "2026-09-20", "status": "issued", "printCount": 0},
                {"id": "po-2", "processingOrderNo": "JG-20260912-0002", "orderNo": "ORD-2",
                 "customerName": "李四", "processor": None,
                 "expectedDeliveryDate": None, "status": "generated", "printCount": 0},
            ],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, keyword="JG-20260912", status="issued")

        assert result.success is True
        assert "2 个加工单" in result.message
        call_args = mock_client.get.call_args
        assert "processing-orders" in call_args[0][0]
        params = call_args.kwargs.get("params", {})
        assert params.get("keyword") == "JG-20260912"
        assert params.get("status") == "issued"
        # 状态中文映射
        rows = result.data["list"]
        assert rows[0]["statusText"] == "已发加工"
        assert rows[1]["statusText"] == "已生成"

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_query_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, keyword="JG-不存在")

        assert result.success is True
        assert "未找到加工单" in result.message

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        result = await tool.execute(context=unauthorized_tool_context)
        assert result.success is False
        assert "没有权限" in result.message


class TestDeliveryRiskAction:
    """具名跨域视图 `delivery_risk` 的按需消费入口（issue #6217 / V2）。

    🔴 本类的承重判据：**「单张进度取不到」必须是「未知」，不是「没有卡着的工序」**
    （后者会把一张可能卡了三周的加工单报成「进度正常」）。
    """

    def _wire(self, mock_client, *, orders=None, progress=None, orders_failure=False,
              progress_failure=False):
        table = PROGRESS if progress is None else progress
        listed = ORDERS if orders is None else orders

        async def _get(endpoint, **kwargs):
            if endpoint.endswith("processing-orders"):
                if orders_failure:
                    return {"success": False, "error": {"message": "无权限"}}
                return {"success": True, "data": listed}
            order_no = kwargs.get("params", {}).get("order_no")
            if progress_failure or order_no not in table:
                return {"success": False, "error": {"message": "该单进度读不到"}}
            return {"success": True, "data": [table[order_no]]}

        mock_client.get = AsyncMock(side_effect=_get)

    def test_action_is_read_only_and_valid(self, tool):
        assert "delivery_risk" in VALID_ACTIONS
        assert "delivery_risk" in tool.read_only_actions
        assert "delivery_risk" in tool.description
        assert "delivery_risk" in tool.parameters["properties"]["action"]["enum"]

    def test_endpoint_literals_are_pinned_against_the_controllers(self):
        """契约里的技术字面量不许凭语义推测（§17.3）：调用点字面量 == 模块常量 == 控制器映射"""
        # 字面量落在 `_fetch` 的 `client.get(...)` 实参位置（`_delivery_risk` 只传端点常量）
        source = Path(TOOL_MODULE.__file__).read_text(encoding="utf8")
        body = source[source.index("async def _fetch("):source.index("def _assemble(")]
        mappings = set()
        for name in ("ProcessingOrderController.java", "agent/AgentProductionController.java"):
            controller = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller" / name)
            text = controller.read_text(encoding="utf8")
            # 类级 `@RequestMapping("/api/admin/...")` + 方法级 `@GetMapping` 两段拼出真路径
            # （只看方法级会把 `…/production` + `/progress` 读成两个不存在的端点）
            prefix = re.search(r'@RequestMapping\("([^"]+)"\)', text).group(1).rstrip("/")
            mappings |= {f"{prefix}{path}" for path in
                         re.findall(r'@GetMapping\("([^"]*)"\)', text)}
            mappings.add(prefix)

        assert f'"{DELIVERY_RISK_ORDERS_ENDPOINT}"' in body, (
            "端点必须以**字面量**出现在调用点（静态归属机具只认调用点的字面量）")
        assert f'"{DELIVERY_RISK_PROGRESS_ENDPOINT}"' in body
        for endpoint in (DELIVERY_RISK_ORDERS_ENDPOINT, DELIVERY_RISK_PROGRESS_ENDPOINT):
            assert endpoint in mappings, f"{endpoint} 必须真的挂在 admin-api 的控制器上"
        assert DELIVERY_RISK_PROGRESS_ENDPOINT.endswith("/agent/production/progress")

    def test_permission_code_is_the_production_read_code(self, tool):
        assert tool.required_permissions == ["production:view"]

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_view_aggregates_across_orders(self, mock_get_client, tool, admin_tool_context,
                                                 mock_client):
        self._wire(mock_client)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delivery_risk")

        assert result.success is True
        assert result.data["view"] == "delivery_risk"
        assert result.data["stuck_top"][0] == {"operation": "裁剪", "order_count": 1}
        assert "裁剪（1 单）" in result.message
        rows = {row["processing_order_no"]: row for row in result.data["rows"]}
        assert rows["JG-1"]["pending_count"] == 2
        assert rows["JG-1"]["risk_band"] in ("overdue", "critical", "soon", "safe")
        # 没填交期的单 ⇒ 风险**未知**（不是「不紧急」），且消息里点名分层未知
        assert rows["JG-2"]["risk_band"] == "unknown"
        assert "交期未知" in result.message

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_list_failure_is_fail_closed_and_attributable(self, mock_get_client, tool,
                                                                admin_tool_context, mock_client):
        self._wire(mock_client, orders_failure=True)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delivery_risk")

        assert result.success is False
        assert result.error == "cross_domain_fetch_failed"
        assert "production:view" in result.message
        assert "fail-closed" in result.message
        assert result.suggestion

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_single_progress_failure_is_unknown_not_empty(self, mock_get_client, tool,
                                                                admin_tool_context, mock_client):
        """🔴 单张进度取不到 ⇒ `pending_operations=None` + 点名 —— **不得**填 `[]`（=没有卡点）"""
        self._wire(mock_client, progress_failure=True)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delivery_risk")

        assert result.success is True
        row = result.data["rows"][0]
        assert row["pending_operations"] is None
        assert row["stuck_operation"] is None
        assert row["unwired"], "该单的卡点必须被标为未接线（未知）"
        assert result.data["stuck_top"] == []
        assert result.data["missing_progress"] == len(ORDERS)
        assert "没取到逐单工序进度" in result.message
        assert "没有卡着的工序" in result.message

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_no_truth_fields_are_disclosed_with_reasons(self, mock_get_client, tool,
                                                              admin_tool_context, mock_client):
        self._wire(mock_client)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delivery_risk")

        assert result.data["no_truth_fields"], "声明无真值的字段必须被披露（否则本判据空跑）"
        assert set(result.data["no_truth_fields"]) == set(RISK_NO_TRUTH_REASONS)
        for name in result.data["no_truth_fields"]:
            assert name in result.message, f"{name} 没在消息里点名"
        assert "不是 0" in result.message
        assert {row[name] for row in result.data["rows"] for name in RISK_NO_TRUTH_REASONS} == {None}

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_progress_calls_are_bounded(self, mock_get_client, tool, admin_tool_context,
                                              mock_client):
        """逐单进度取数**有界**（一条调用对应一张单 ⇒ 不设上限会把一个回合变成 N 次串行 HTTP）"""
        many = [{"processingOrderNo": f"JG-{i}", "orderNo": f"ORD-{i}", "customerName": "客户",
                 "processor": None, "expectedDeliveryDate": "2026-10-05", "status": "issued"}
                for i in range(DELIVERY_RISK_PROGRESS_LIMIT + 20)]
        self._wire(mock_client, orders=many, progress={})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delivery_risk")

        progress_calls = [call for call in mock_client.get.call_args_list
                          if call.args[0].endswith("/production/progress")]
        assert len(progress_calls) == DELIVERY_RISK_PROGRESS_LIMIT
        assert result.data["row_meta"]["production_progress"]["truncated"] is True
        assert result.success is True

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_query_action_still_defaults(self, mock_get_client, tool, admin_tool_context,
                                               mock_client):
        """回归：不传 action 仍是旧的 query 行为（默认值不许被新 action 改掉）"""
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, keyword="JG-x")

        assert result.success is True
        assert "未找到加工单" in result.message
        assert mock_client.get.call_args.args[0] == DELIVERY_RISK_ORDERS_ENDPOINT

    async def test_invalid_action_is_rejected(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="nope")

        assert result.success is False
        assert "无效的操作类型" in result.error
