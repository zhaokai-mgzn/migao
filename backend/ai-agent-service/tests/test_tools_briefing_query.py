"""
经营日报查询 Tool 测试 —— 只读契约 + 权限面 + **端点归属**（issue #5247 B 端只读化）

本文件是 `app/tools/briefing_query.py` 的**同名单测**（`.github/growth_gate.py` 对每个
tool 模块要求 `tests/test_tools_<name>.py`）。断言分三面：

1. **声明面**：`read_only is True` / `destructive is False` / `required_permissions`
   逐字等于端点生效码 —— 后者是「Agent 能力 ≡ 页面权限」（issue #5246 守则）在**工具粒度**的锚点，
   权限码写错时这一条会红，而不是等到运行时被 admin-api 403；
2. **权限面**：无权限 ⇒ 拒绝**且不发请求**（`assert_not_called`）；有权限 ⇒ 命中它**声称**的端点；
3. **失败面**：后端 `success=false` 与客户端抛异常都必须落成**可归因**的 `ToolResult`，
   不得让异常穿透到图节点。

⚠️ 这些断言会红吗：把 `read_only` 改 False、把权限码改别的、去掉 `check_permission` 早返回、
把端点换成别的路径、把 `except` 里的返回改成 `raise` —— 逐一都会红（每条断言都盯着一个**会变的**真值）。
"""
# case_ids: DA-008, DA-009, DA-010, DA-014, DA-018
import json
from pathlib import Path

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.briefing_query import (
    SNAPSHOT_ENDPOINT,
    TODAY_ENDPOINT,
    VALUED_VIEWS,
    BriefingQueryTool,
)
from app.tools.base import ToolContext

ENDPOINT = "/api/admin/briefing/today"
PERMISSION = "dashboard:view"

#: 后端控制器源码（端点字面量的真值：Python 侧声明的路径必须真的在 Java 里 —— §17.3「不许凭语义推测」）
CONTROLLER_SRC = (Path(__file__).resolve().parents[3]
                  / "backend/admin-api/src/main/java/com/migao/admin/controller/BriefingController.java")

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])
SAMPLE = {"date": "2026-09-24", "orderCount": 3, "revenue": 1280.0}


class TestDeclaration:
    """声明面：只读 + 权限码与端点同码"""

    def test_is_declared_read_only(self):
        tool = BriefingQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_required_permission_equals_endpoint_code(self):
        """权限码必须逐字等于 `BriefingController` GET 的生效码（#5246 的同一口径）"""
        assert BriefingQueryTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        """工具名是 skill 绑定与判据的键，改名会静默解绑"""
        assert BriefingQueryTool().name == "briefing_query"

    def test_default_path_needs_no_required_parameters(self):
        """默认路径（当日简报）**无必填参数**；`view` 是可选的**白名单**参数（issue #5369）

        原判据「固定无参数」随族 3 包 2 的按需视图改判 —— 强度不降：默认路径的行为仍由
        既有断言逐字承担（无 view ⇒ 只打 `/today`；消息主体「今日经营日报如下」不变）。
        """
        parameters = BriefingQueryTool().parameters
        assert parameters["required"] == []
        assert set(parameters["properties"]) == {"view"}
        assert parameters["properties"]["view"]["enum"] == list(VALUED_VIEWS) == ["product_health"]


class TestPermissionGate:

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        """无权限 ⇒ 拒绝，且**不得**发出请求（越权与假拒绝都从这条路进来）"""
        result = await BriefingQueryTool().execute(context=DENIED)
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_allowed_hits_the_declared_endpoint(self, mock_get_client):
        """有权限 ⇒ 命中**它声称的那个端点**（端点归属的机械证据）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is True
        paths = [c.args[0] if c.args else c.kwargs.get("path")
                 for c in client.get.call_args_list]
        assert paths == [ENDPOINT], paths

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        """多租户隔离：租户头必须来自 context，不得硬编码"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        await BriefingQueryTool().execute(context=ALLOWED)

        kwargs = client.get.call_args_list[0].kwargs
        assert kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        """后端 `success=false` ⇒ 失败结果里带**后端原文**，便于用户与排查者定位"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "简报尚未生成"}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert "简报尚未生成" in (result.message or "")

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        """客户端抛异常 ⇒ 落成 `tool_execution_failed`，不得穿透到图节点"""
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert result.error == "tool_execution_failed"


PROACTIVE_BIZ_DATE = "2026-09-22"
PROACTIVE_SNAPSHOT = {
    "biz_date": PROACTIVE_BIZ_DATE,
    "orders": [
        # 当天异常：成交价 700 < 成本 1000
        {"order_no": "SO-TODAY", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-22T09:00:00+08:00", "shipped_at": None,
         "sale_amount": 700.0, "cost_amount": 1000.0},
        # **历史**异常：同一条规则，但事件发生在 09-01
        {"order_no": "SO-HISTORY", "status": "completed", "customer_id": "C-9",
         "created_at": "2026-09-01T09:00:00+08:00", "shipped_at": "2026-09-02T09:00:00+08:00",
         "sale_amount": 100.0, "cost_amount": 300.0},
    ],
    "skus": [],
    "returns": [],
    "price_changes": [],
}


class TestProactiveDailyFindings:
    """主动发现（族 1 · 包 1，issue #5322）：日报只放**当天异常**，无快照不猜。

    引擎侧的确定性 / 三件套 / 注入式红证 / 阈值边界判据见 `tests/test_briefing_proactive.py`；
    本类只钉**集成面**：工具把 `sourceSnapshot` 喂给引擎、并把结果并进日报返回。
    """

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_today_anomalies_are_surfaced(self, mock_get_client):
        """当天异常 ⇒ 进 `data.proactive`，且消息里点出条数（用户才知道要往下看）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": PROACTIVE_BIZ_DATE, "sourceSnapshot": PROACTIVE_SNAPSHOT,
                     "content": {"summary": "昨日经营平稳"}}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is True
        assert [f["rule_id"] for f in result.data["proactive"]] == ["below_cost_price"]
        assert "SO-TODAY" in json.dumps(result.data["proactive"], ensure_ascii=False)
        assert "1 项当天异常" in (result.message or "")
        assert result.data["content"] == {"summary": "昨日经营平稳"}   # 日报主体不被改动

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_historical_anomaly_does_not_reach_the_daily_view(self, mock_get_client):
        """**历史异常**（同规则、09-01 的事件）⇒ 不得出现在日报里（日报要窄）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": PROACTIVE_BIZ_DATE, "sourceSnapshot": PROACTIVE_SNAPSHOT}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert "SO-HISTORY" not in json.dumps(result.data["proactive"], ensure_ascii=False)

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_without_snapshot_there_is_no_proactive_section(self, mock_get_client):
        """后端未给快照（旧数据 / 未生成）⇒ 空集合：不得报错，也不得编造异常"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is True
        assert result.data["proactive"] == []
        # 🔴 #5358：无快照 ⇒ 五条规则**一条都没接线**，消息必须如实说明（见 TestNotWiredDisclosure）；
        # 这句主体文案保持不变（不因未接线而改写日报主体）。
        assert (result.message or "").startswith("今日经营日报如下")


#: 未接线的两条能力（`RULES[].rule_name` 原文）—— 消息里必须逐条点名
UNWIRED_NAMES = ("低于成本价的订单", "改价幅度超阈值")

#: 装配后的快照（与 admin-api `aggregateSnapshot` 同形）：三条规则接线、两条接不通；
#: 且**当天一条都没命中** —— 正是「空命中」最容易被读成「今天一切正常」的那一种。
UNWIRED_SNAPSHOT = {
    "biz_date": "2026-09-22",
    "row_fields": {
        "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at", "sale_amount"],
        "skus": ["sku_id", "product_id", "product_name", "stock"],
        "returns": ["return_no", "customer_id", "product_id", "returned_at", "amount"],
    },
    "orders": [],
    "skus": [],
    "returns": [],
}


def _assert_honest_about_unwired(message, names=UNWIRED_NAMES):
    """**判据本体**（#5358 判据 4）：`not_wired` 时必须如实说明「尚未接入」，**禁止**「今日无异常」类表述。

    这是 deterministic 面（工具消息），LLM 的自由措辞不在本断言范围内 —— 消息是它唯一的输入源，
    消息里没有的兜底，模型编不出来。
    """
    for name in names:
        assert name in message, f"未接线能力「{name}」未如实说明"
    assert "尚未接入" in message, "未接线必须有「尚未接入」的明确措辞"
    for forbidden in ("今日无异常", "无异常", "一切正常", "没有异常", "未发现异常", "暂无异常"):
        assert forbidden not in message, f"未接线时出现了「{forbidden}」类表述（会把空命中读成没问题）"
    return True


#: 行数组被上限**截断**的快照（`row_truncated` 显式登记）：本次检查过，但**不完整** ——
#: 空命中同样不得被读成「没问题」。
TRUNCATED_SNAPSHOT = dict(UNWIRED_SNAPSHOT, row_meta={
    "orders": {"limit": 500, "count": 500, "truncated": True},
    "skus": {"limit": 500, "count": 0, "truncated": False},
    "returns": {"limit": 500, "count": 0, "truncated": False},
})

#: 当天**真有** 3 项异常、但 `max_findings=2`（租户配置）把日报截成 2 条的快照。
LIMITED_SNAPSHOT = {
    "biz_date": "2026-09-22",
    "config": {"max_findings": 2},
    "row_fields": UNWIRED_SNAPSHOT["row_fields"],
    "row_meta": {
        "orders": {"limit": 500, "count": 1, "truncated": False},
        "skus": {"limit": 500, "count": 2, "truncated": False},
        "returns": {"limit": 500, "count": 3, "truncated": False},
    },
    "orders": [{"order_no": "SO-1", "status": "confirmed", "customer_id": "C-1",
                "created_at": "2026-09-12T10:00:00+08:00", "shipped_at": None,
                "sale_amount": 1200.0}],
    "skus": [{"sku_id": "SKU-1", "product_id": "P-1", "product_name": "雪尼尔-米白", "stock": 20.0},
             {"sku_id": "SKU-2", "product_id": "P-2", "product_name": "棉麻-灰", "stock": 30.0}],
    "returns": [{"return_no": f"RT-{n}", "customer_id": "C-1", "product_id": "P-9",
                 "returned_at": f"2026-09-{day}T10:00:00+08:00", "amount": 100.0}
                for n, day in ((1, 18), (2, 20), (3, 22))],
}


#: 按需视图的数据面：`GET /api/admin/briefing/snapshot` 的确定性装配结果（与 admin-api 同形）
VIEW_SNAPSHOT = {
    "row_fields": {
        "skus": ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"],
        "returns": ["return_no", "customer_id", "product_id", "returned_at", "amount"],
        "product_return_stats": ["product_id", "return_tickets", "order_lines"],
    },
    "row_meta": {
        "skus": {"limit": 500, "count": 2, "truncated": False},
        "returns": {"limit": 500, "count": 1, "truncated": False},
        "product_return_stats": {"limit": 500, "count": 1, "truncated": False},
    },
    "skus": [
        {"sku_id": "SKU-1", "product_id": "P-1", "product_name": "雪尼尔-米白",
         "stock": 20.5, "sales_count": 120.0, "price": 168.0, "avg_cost": 100.0},
        # 🔴 存量不回填成本：该行**成本未知** ⇒ 毛利未知（不是 0）
        {"sku_id": "SKU-2", "product_id": "P-1", "product_name": "雪尼尔-米白",
         "stock": 0.0, "sales_count": 30.5, "price": 168.0, "avg_cost": None},
    ],
    "returns": [{"return_no": "RT-1", "customer_id": "C-1", "product_id": "P-1",
                 "returned_at": "2026-09-22T10:00:00+08:00", "amount": 100.0}],
    "product_return_stats": [{"product_id": "P-1", "return_tickets": 1, "order_lines": 4}],
}


class TestOnDemandProductHealthView:
    """族 3 · 包 2（issue #5369）：具名视图 `product_health` 的**按需**消费入口。

    与日报（主动消费，族 1）**同一份内核快照** —— 本类只钉消费面三件事：

    ① 走**确定性快照端点**（零 LLM、不依赖当日简报是否已生成）；
    ② 白名单之外的 view 一律拒绝且**不发请求**（越权/编造参数从这条路进来）；
    ③ 消息如实说明：**成本未知 ≠ 毛利 0**、未接线 / 不完整逐字段点名（消息是模型唯一输入源）。
    """

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_view_hits_the_deterministic_snapshot_endpoint(self, mock_get_client):
        """按需视图走 `/snapshot`（不是 `/today`）：租户来自 context，行是 SKU 级权威列"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": VIEW_SNAPSHOT})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED, view="product_health")

        assert result.success is True
        paths = [c.args[0] if c.args else c.kwargs.get("path")
                 for c in client.get.call_args_list]
        assert paths == [SNAPSHOT_ENDPOINT] == ["/api/admin/briefing/snapshot"], paths
        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id

        assert result.data["view"] == "product_health"      # 视图标识（字符串 id）
        assert result.data["tenant_id"] == ALLOWED.tenant_id
        assert [row["sku_id"] for row in result.data["rows"]] == ["SKU-1", "SKU-2"]
        first = result.data["rows"][0]
        assert first["gross_margin"] == 68.0
        assert first["stock"] == 20.5
        assert first["sales_count"] == 120.0
        assert first["low_stock"] is True
        assert first["return_rate"] == 0.25

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_unknown_cost_is_disclosed_as_unknown_not_zero(self, mock_get_client):
        """🔴 判据 2 的消费面：成本未知必须说成「未知」，消息里不得出现「毛利 0」类断言"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": VIEW_SNAPSHOT})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED, view="product_health")
        message = result.message or ""

        assert result.data["rows"][1]["gross_margin"] is None
        assert result.data["unknown_cost_rows"] == 1
        assert "成本未知" in message, message
        assert "无法给出" in message, message
        for forbidden in ("毛利 0", "毛利为 0", "成本为 0", "毛利 0.0", "一切正常"):
            assert forbidden not in message, f"消息出现「{forbidden}」（把未知说成了 0/没问题）"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_not_wired_fields_are_disclosed(self, mock_get_client):
        """装配层没给 `skus` ⇒ 逐字段点名「未接线」，且不得改写成「均为 0」"""
        snapshot = dict(VIEW_SNAPSHOT)
        snapshot["row_fields"] = {k: v for k, v in VIEW_SNAPSHOT["row_fields"].items()
                                  if k != "skus"}
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": snapshot})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED, view="product_health")
        message = result.message or ""

        assert result.success is True
        assert result.data["fields"]["stock"]["status"] == "not_wired"
        assert result.data["fields"]["return_rate"]["status"] == "wired"
        assert "未接线" in message, message
        for label in ("销量", "库存", "成本毛利"):
            assert label in message, f"未接线字段「{label}」未被点名"
        # 反例：把「没有数据」说成「就是 0」的**断言式**表述一律不得出现
        # （消息里「请勿理解为均为 0」是有意为之的否定式披露，不在反例之列）
        for forbidden in ("一切正常", "库存为 0", "库存 0", "销量为 0", "毛利为 0"):
            assert forbidden not in message, f"消息出现「{forbidden}」"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_invalid_view_is_rejected_without_request(self, mock_get_client):
        """白名单之外（如尚未交付的 `customer_profile`）⇒ 拒绝 + 不发请求（不猜、不降级）"""
        result = await BriefingQueryTool().execute(context=ALLOWED, view="customer_profile")

        assert result.success is False
        assert "product_health" in (result.message or "")
        assert "customer_profile" in (result.error or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_view_respects_the_permission_gate(self, mock_get_client):
        """权限面与默认路径同一关口：无权限 ⇒ 拒绝且不发请求"""
        result = await BriefingQueryTool().execute(context=DENIED, view="product_health")

        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_default_path_still_hits_today(self, mock_get_client):
        """缺省（不传 view）⇒ 仍旧是当日简报端点：新能力不得悄悄改掉老路径"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        paths = [c.args[0] if c.args else c.kwargs.get("path")
                 for c in client.get.call_args_list]
        assert paths == [ENDPOINT] == [TODAY_ENDPOINT], paths
        # 默认路径的 data 不得多出视图键（加数组/字段 = 隐式扩大所有消费方的输入，§17.3）
        assert "view" not in result.data

    def test_endpoint_literals_match_the_backend_controller(self):
        """端点字面量必须真的在 Java 控制器里（不许凭语义推测 —— §17.3 ⑤）"""
        java = CONTROLLER_SRC.read_text(encoding="utf-8")

        assert '@GetMapping("/snapshot")' in java
        assert '@GetMapping("/today")' in java
        assert SNAPSHOT_ENDPOINT == "/api/admin/briefing/snapshot"
        assert TODAY_ENDPOINT == "/api/admin/briefing/today"


class TestNotWiredDisclosure:
    """#5358 判据 4：未接线的能力如实说明，不得用「今日无异常」覆盖。

    对照判据（会红吗）：把工具消息里「尚未接入」那段删掉 ⇒ 本类第 1 条必红（见两条注入式红证）；
    把状态判定改回「命中为空即正常」⇒ 禁用词判据与点名判据都会红。
    """

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_message_discloses_not_wired_capabilities(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": UNWIRED_SNAPSHOT}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        # 当天确实 0 条命中 —— 若没有披露，这句话就是「今天一切正常」
        assert result.data["proactive"] == []
        assert _assert_honest_about_unwired(result.message or "") is True

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_status_reaches_the_caller(self, mock_get_client):
        """逐规则状态必须进 `data`（不然「两种空可分」只活在服务端，调用方还是分不出来）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": UNWIRED_SNAPSHOT}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        status = result.data["proactive_status"]
        assert status["price_change_over"]["status"] == "not_wired"
        assert status["low_stock"]["status"] == "wired"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_all_wired_snapshot_gets_no_disclosure(self, mock_get_client):
        """全部接线时**不得**出现未接线措辞（否则披露会因为「总是出现」而失去信息量）"""
        wired = dict(
            UNWIRED_SNAPSHOT,
            row_fields={**UNWIRED_SNAPSHOT["row_fields"],
                        "orders": UNWIRED_SNAPSHOT["row_fields"]["orders"] + ["cost_amount"],
                        "price_changes": ["change_no", "order_no", "product_id",
                                          "original_price", "new_price", "changed_at"]},
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": wired}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert "尚未接入" not in (result.message or "")
        assert result.message == "今日经营日报如下"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_red_proof_missing_disclosure_fails_the_judgement(self, mock_get_client):
        """**注入式红证**：把某条未接线能力的名字从消息里抹掉 ⇒ 判据必红（不是空断言）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": UNWIRED_SNAPSHOT}})
        mock_get_client.return_value = client
        result = await BriefingQueryTool().execute(context=ALLOWED)

        stripped = (result.message or "").replace(UNWIRED_NAMES[0], "")
        assert stripped != (result.message or ""), "被抹掉的名字原本就不在消息里 ⇒ 本红证是空跑"
        with pytest.raises(AssertionError):
            _assert_honest_about_unwired(stripped)

    def test_red_proof_forbidden_text_judgement_is_load_bearing(self):
        """**注入式红证**：消息里出现「今日无异常」类表述 ⇒ 判据必红"""
        with pytest.raises(AssertionError):
            _assert_honest_about_unwired(
                f"以下能力尚未接入本次扫描：{'、'.join(UNWIRED_NAMES)}（今日无异常）")


class TestIncompleteDisclosure:
    """判据 7（「有界不许变成静默少报」）：**本次不完整**与**条数被截断**都必须显式。

    对照判据（会红吗）：把 `row_meta` 抹掉 ⇒ 不完整披露判据必红；把真实条数改回被截断的条数
    ⇒ 条数判据必红（两条都是「少报」形态）。
    """

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_truncated_rows_are_disclosed_as_incomplete(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": TRUNCATED_SNAPSHOT}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        message = result.message or ""
        assert "本次数据不完整" in message, "截断必须显式说出来（有界不许变成静默少报）"
        assert "超 N 天未发货" in message, "点名的必须是**哪条**规则不完整"
        for forbidden in ("今日无异常", "无异常", "一切正常", "未发现异常"):
            assert forbidden not in message
        assert result.data["proactive_status"]["unshipped_overdue"]["status"] == "incomplete"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_red_proof_truncation_disclosure_is_load_bearing(self, mock_get_client):
        """**注入式红证**：抹掉 `row_meta`（= 装作没截断）⇒ 上一条判据必红"""
        plain = {key: value for key, value in TRUNCATED_SNAPSHOT.items() if key != "row_meta"}
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True, "data": {"bizDate": "2026-09-22", "sourceSnapshot": plain}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        with pytest.raises(AssertionError):
            assert "本次数据不完整" in (result.message or "")

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_capped_daily_list_states_the_true_total(self, mock_get_client):
        """日报条数被 `max_findings` 截断 ⇒ 消息必须点出**真实条数**（3 项，不是 2 项）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": "2026-09-22", "sourceSnapshot": LIMITED_SNAPSHOT}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        message = result.message or ""
        assert len(result.data["proactive"]) == 2, "日报条数上限生效（max_findings=2）"
        assert "另有 2 项当天异常待处理" in message
        assert "当天共 3 项" in message, "被截断的条数必须点出真实总数"

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_red_proof_missing_total_is_load_bearing(self, mock_get_client):
        """**注入式红证**：把真实条数改回被截断的条数（= 少报）⇒ 判据必红"""
        message = "今日经营日报如下，另有 2 项当天异常待处理"
        with pytest.raises(AssertionError):
            assert "当天共 3 项" in message
