"""InventoryManageTool `material_shortage` action 单元测试（issue #6280 冻结契约 v1）。

⚠️ 本文件声明 `case_ids: DA-022`，该用例条目由**并行的 Java 包**在 `.github/cases/data.yml` 创建；
若门禁报「DA-022 不存在」属**预期**（写入时条目尚未落地），不得由本包自建条目（同改一文件会撞车）。

本文件钉的是**工具面**（视图语义在 admin-api 侧 Java 纯函数，Python 不重算预测）：
- `material_shortage` 只读 ⇒ 在 `VALID_ACTIONS` 且 `read_only_actions`；
- **未知 action ⇒ 无效操作类型（不猜）**；**不传 action ⇒ 旧行为逐字不变**；
- 🔴 **fail-closed**：端点取数失败 ⇒ 明确失败 + 点名 `product:list` + 可行动建议；
  **不得**把空列表冒充「没有缺料」（「没查」与「没问题」必须可分）、**不得**返回半截数据当完整；
- 🔴 **披露纪律**：`rate_per_week` / `exhaust_date` 报 `not_wired`（预测层未启用）必须用人话说出
  （真实历史深度 N 周 < 要求 8 周），不得静默省略、不得把 null 说成 0；`no_truth_fields` 逐条点名；
- 🔴 **未知 ≠ 0**：`demand_qty = null` 原样透出为未知，不得渲染成 0、不得说成「没有需求」。
"""
# case_ids: DA-022
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import inventory_manage as TOOL_MODULE
from app.tools.inventory_manage import (
    MATERIAL_SHORTAGE_ENDPOINT,
    MATERIAL_SHORTAGE_LIMIT,
    MATERIAL_SHORTAGE_STATUSES,
    InventoryManageTool,
    VALID_ACTIONS,
)

# 与 Java 侧端点的**有效动作**逐字对应（`GET /api/admin/materials/shortage`；契约 v1）
_EXPECTED_ENDPOINT = "/api/admin/materials/shortage"
_EXPECTED_STATUSES = "confirmed,producing"


@pytest.fixture
def tool():
    return InventoryManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    return client


#: 冻结契约 v1 的响应样例：刻意**同时**含三处最容易假绿落点 ——
#: ① 单位不可比行（`demand_qty = null`，不是 0）② 预测层未启用（`rate_per_week` /
#: `exhaust_date` = `not_wired` + `history_depth.sufficient = false`）③ `short` 档
#: （缺口确定、紧迫性未知）。
VIEW = {
    "view": "material_shortage",
    "tenant_id": 1,
    "as_of": "2026-10-04",
    "basis": {"demand": "未完成订单行用量（products.unit='米'）",
              "supply": "Σ product_skus.stock GROUP BY product_id",
              "risk_band": "safe/blocked/critical/soon/short/unknown"},
    "fields": {
        "demand_qty": {"status": "incomplete", "reason": "2 行单位不可比（products.unit ≠ 米）",
                       "source": "orders.status × order_items",
                       "truth": "has_truth", "note": "未完成订单行用量合计", "label": "需求量"},
        "stock_meters": {"status": "wired", "reason": None, "source": "product_skus.stock",
                         "truth": "has_truth", "note": "SKU 级权威库存现算", "label": "库存"},
        "gap_meters": {"status": "wired", "reason": None, "source": "demand − stock",
                       "truth": "has_truth", "note": "负 = 有余量", "label": "缺口"},
        "risk_band": {"status": "wired", "reason": None, "source": "gap + 交期",
                      "truth": "has_truth", "note": "六档风险", "label": "风险分层"},
        "rate_per_week": {"status": "not_wired", "reason": "预测层未启用", "source": "台账周桶",
                          "truth": "has_truth", "note": "周消耗速率", "label": "周耗用速率"},
        "exhaust_date": {"status": "not_wired", "reason": "预测层未启用", "source": "台账周桶",
                         "truth": "has_truth", "note": "耗尽日", "label": "预计耗尽日"},
    },
    "rows": [
        {"product_id": "p-crit", "product_name": "雪尼尔-A", "demand_qty": 300.0, "demand_lines": 4,
         "order_count": 3, "stock_meters": 100.0, "gap_meters": 200.0, "risk_band": "critical",
         "days_to_deadline": 2, "earliest_required_delivery_date": "2026-10-06",
         "rate_per_week": None, "exhaust_date": None, "unwired": ["rate_per_week", "exhaust_date"]},
        {"product_id": "p-short", "product_name": "棉麻-B", "demand_qty": 80.0, "demand_lines": 2,
         "order_count": 1, "stock_meters": 10.0, "gap_meters": 70.0, "risk_band": "short",
         "days_to_deadline": None, "earliest_required_delivery_date": None,
         "rate_per_week": None, "exhaust_date": None, "unwired": ["rate_per_week", "exhaust_date"]},
        {"product_id": "p-unk", "product_name": "挂钩-C", "demand_qty": None, "demand_lines": 2,
         "order_count": 2, "stock_meters": None, "gap_meters": None, "risk_band": "unknown",
         "days_to_deadline": None, "earliest_required_delivery_date": None,
         "rate_per_week": None, "exhaust_date": None, "unwired": ["rate_per_week", "exhaust_date"]},
    ],
    "count": 3,
    "rows_total": 3,
    "truncated": False,
    "no_truth_fields": [],
    "has_truth_fields": [],
    "band_counts": {"blocked": 0, "critical": 1, "soon": 0, "short": 1, "safe": 0, "unknown": 1},
    "non_comparable": {"lines": 2, "products": 1},
    "history_depth": {"weeks": 2, "required_weeks": 8, "sufficient": False,
                      "reason": "真实台账周桶深度 2 周 < 要求 8 周"},
}


def _ok(view=None):
    return {"success": True, "data": VIEW if view is None else view}


def _wire(mock_get_client, mock_client, response):
    mock_client.get = AsyncMock(return_value=response)
    mock_get_client.return_value = mock_client


class TestActionWiring:
    """判据 1 / 7 / 8：action 登记、只读免确认、schema 与 description 形态。"""

    def test_action_is_registered_read_only_and_documented(self, tool):
        assert "material_shortage" in VALID_ACTIONS
        assert "material_shortage" in tool.read_only_actions, "只读 ⇒ 免确认拦截"
        assert "material_shortage" in tool.parameters["properties"]["action"]["enum"]
        assert "material_shortage" in tool.description
        # 权限码沿用库存域读码（契约 v1：与库存台账/批次看板/低库存同码）
        assert tool.required_permissions == ["product:list"]

    def test_description_follows_repo_format_and_keeps_low_stock_alert_alive(self, tool):
        """description 四段式齐全；反例说清何时**不该**用它；⛔ 不得宣告 `low_stock_alert` 已废弃。"""
        for marker in ("【触发】", "【参数】", "【反例】", "【标注】"):
            assert marker in tool.description, f"description 缺 {marker} 段"
        assert "inventory_manage" in tool.description  # 反例里点名本工具其它 action
        assert "low_stock_alert" in tool.description
        assert "query" in tool.description
        # 行为变更不在本包范围：不得出现「已废弃 / 已下线 / 不再支持」这类宣告
        for banned in ("已废弃", "已下线", "不再支持", "deprecated"):
            assert banned not in tool.description, f"description 不得宣告 {banned}"

    def test_endpoint_literals_are_pinned_to_the_frozen_contract(self):
        """契约技术字面量不许凭语义推测（§17.3）：常量 == 调用点实参字面量 == 契约 v1。"""
        assert MATERIAL_SHORTAGE_ENDPOINT == _EXPECTED_ENDPOINT
        assert MATERIAL_SHORTAGE_STATUSES == _EXPECTED_STATUSES
        assert MATERIAL_SHORTAGE_LIMIT == 50

        source = Path(TOOL_MODULE.__file__).read_text(encoding="utf8")
        body = source[source.index("async def _material_shortage("):]
        assert f'"{_EXPECTED_ENDPOINT}"' in body, (
            "端点必须以**字面量**出现在调用点（静态归属机具只认调用点的字面量）")
        assert f'"statuses": "{_EXPECTED_STATUSES}"' in body or \
               f'"statuses": MATERIAL_SHORTAGE_STATUSES' in body, "statuses 取数参数必须显式"
        assert f'"limit": {MATERIAL_SHORTAGE_LIMIT}' in body or \
               f'"limit": MATERIAL_SHORTAGE_LIMIT' in body, "limit 取数参数必须显式"


class TestOldBehaviorUnchanged:
    """判据 2：新 action **不得**改动旧行为（默认值 / 未知 action 两支逐字不变）。"""

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_action_stays_required_and_query_is_unchanged(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """🔴 旧契约：`action` **必填**（无默认值）。新 action 不得顺手给它加默认值 ——
        那会把「漏传 action」从**明确报错**改成「猜一个 query」（§17.3：不许凭语义推测）。"""
        import inspect

        assert inspect.signature(InventoryManageTool.execute).parameters["action"].default \
            is inspect.Parameter.empty, "action 必须保持必填（加默认值 = 猜）"
        assert tool.parameters["required"] == ["action"]

        mock_client.get = AsyncMock(return_value={"success": True, "data": {
            "name": "雪尼尔", "status": "on_sale", "skus": [{"stock": 100}]}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-1")

        assert result.success is True
        assert mock_client.get.call_args.args[0] == "/api/admin/products/prod-1"
        assert "100" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_low_stock_alert_unchanged(self, mock_get_client, tool,
                                             admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="low_stock_alert")

        assert result.success is True
        assert mock_client.get.call_args.args[0] == "/api/admin/products/low-stock-by-color"

    async def test_unknown_action_is_rejected_and_not_guessed(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="nope")

        assert result.success is False
        assert "无效的操作类型" in result.error
        assert "query" in result.message and "low_stock_alert" in result.message
        assert result.suggestion


class TestFailClosed:
    """判据 3：取数失败 ⇒ 明确失败 + 点名权限码 + 可行动建议；**不得**空列表冒充「没有缺料」。"""

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_fetch_failure_is_fail_closed_and_names_the_permission(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        _wire(mock_get_client, mock_client,
              {"success": False, "error": {"code": "PERMISSION_DENIED",
                                           "message": "缺少权限 product:list"}})

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        assert result.success is False
        assert "product:list" in result.message
        assert "fail-closed" in result.message
        assert result.suggestion
        assert result.data is None, "失败不得返回半截数据"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_endpoint_exception_is_fail_closed(self, mock_get_client, tool,
                                                     admin_tool_context, mock_client):
        mock_client.get = AsyncMock(side_effect=TimeoutError("read timed out"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        assert result.success is False
        assert "product:list" in result.message
        assert "TimeoutError" in result.message, "失败必须可归因到具体面"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_empty_rows_are_not_reported_as_no_shortage_unless_shape_is_intact(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """🔴「没查」与「没问题」可分：`success=True` + 空 rows ⇒ 才允许说「没有缺料」。"""
        empty = dict(VIEW, rows=[], count=0, rows_total=0,
                     band_counts={k: 0 for k in ("blocked", "critical", "soon", "short",
                                                 "safe", "unknown")},
                     non_comparable={"lines": 0, "products": 0})
        _wire(mock_get_client, mock_client, _ok(empty))

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        assert result.success is True
        assert "没有" in result.message and "缺料" in result.message
        # 即便「没有缺料」，预测层未启用也必须照说（否则空结果会被读成「一切正常」）
        assert "预测层未启用" in result.message
        assert "不是 0" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_unrecognized_shape_is_fail_closed_not_empty(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """🔴 形态不可识别（如后端换了键名）⇒ 失败，**不得**当成「rows 为空 = 没有缺料」。"""
        _wire(mock_get_client, mock_client, _ok({"view": "material_shortage", "count": 0}))

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        assert result.success is False
        assert result.data is None, "形态不认识时不得返回半截数据"
        assert "形态不可识别" in result.message
        assert "无法判定有无缺料" in result.message
        # 「没有缺料」只允许作为**警告引用**出现（「当前没有缺料」），不得是陈述句结论
        assert "「没有缺料」" in result.message
        assert "「当前没有缺料」" in result.message
        assert result.suggestion


class TestDisclosure:
    """判据 4 / 5 / 6：披露纪律 —— 「未知 ≠ 0」、预测层未启用要说人话、六档可解释。"""

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_prediction_layer_absence_is_spoken_in_plain_words(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        _wire(mock_get_client, mock_client, _ok())

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        assert result.data["rows"][0]["rate_per_week"] is None
        assert "预测层未启用" in result.message
        assert "2 周" in result.message and "8 周" in result.message, (
            "必须用人话说出真实历史深度与要求深度（否则只是把 null 静默省略）")
        assert "rate_per_week" in result.message and "exhaust_date" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_no_truth_fields_are_named_one_by_one(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        view = dict(VIEW, no_truth_fields=["rate_per_week", "exhaust_date"],
                    fields=dict(VIEW["fields"], rate_per_week={
                        "status": "not_wired", "reason": "预测层未启用", "source": "台账周桶",
                        "truth": "no_truth", "note": "周消耗速率", "label": "周耗用速率"}))
        _wire(mock_get_client, mock_client, _ok(view))

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        for name in ("rate_per_week", "exhaust_date"):
            assert name in result.message, f"{name} 没在消息里点名"
        assert "不是 0" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_unknown_demand_is_not_rendered_as_zero(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """🔴 单位不可比行：`demand_qty` 原样为 `null`（不是 0），且不说成「没有需求」。"""
        _wire(mock_get_client, mock_client, _ok())

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        unknown_row = [r for r in result.data["rows"] if r["risk_band"] == "unknown"][0]
        assert unknown_row["demand_qty"] is None
        assert "单位不可比" in result.message
        assert "2 行" in result.message and "1 个商品" in result.message, (
            "non_comparable.lines / products 两个计数必须出现在面向 LLM 的文本里（可归因）")
        assert "未知" in result.message
        assert "不是 0" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_risk_bands_are_explained_and_short_is_not_merged_into_critical(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        _wire(mock_get_client, mock_client, _ok())

        result = await tool.execute(context=admin_tool_context, action="material_shortage")

        for band in ("blocked", "critical", "soon", "short", "safe", "unknown"):
            assert band in result.message, f"{band} 档没被人话解释"
        assert "缺口确定、紧迫性未知" in result.message, (
            "🔴 `short` = 缺口确定、紧迫性未知，必须单列说明（不得与 critical 混说）")
        # 混说 = 把 short 描述成 time-critical；"缺口确定、紧迫性未知" 这段必须独立于 critical 的措辞
        assert "critical" not in result.message.split("缺口确定、紧迫性未知")[1].split("。")[0]
