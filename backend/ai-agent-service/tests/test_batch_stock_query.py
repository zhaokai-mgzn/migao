# case_ids: PR-100, PR-101, PR-102
"""批次 / 省料只读工具（issue #5188）—— 口径同源 + 权限对齐 + 只读无副作用。

## 本文件钉的四条判据（每条都带能单独变红的红证）

1. **工具真能查**（判据 1）：`batches` / `distribution` / `saving_board` / `saving_trend`
   四个动作都能拿到**服务端真实读数**（改前：`app/tools/` 里零批次工具 ⇒ 红）。
2. 🔴 **口径同源，不另算一份**（判据 2）：省料度量的每一个值都**逐值等于**
   `GET /api/admin/batch-stock/saving-board` 的读数 —— 工具只做**透传**。
   红证 = `TestSavingSameSource.test_naive_client_side_recompute_drifts`：
   夹具刻意取「逐行取整再求和 ≠ 整段求和再取整」的账（差 0.01），
   任何在 agent 侧重算的实现都会拿到 24.67 而读面是 24.68 ⇒ **必红**。
3. **权限对齐**（判据 3）：工具声明的权限码与 `StockBatchController` 各端点上的
   `@RequirePermission` **逐字一致**（解析 Java 源码真值，不手抄）。
4. **只读无副作用**（判据 4）：工具源码里**没有任何**写调用（`post/put/patch/delete`）；
   红证 = 往源码文本里注入一处 `client.patch(` ⇒ 判据报红。

「快用尽」的档位**不自己定**：`nearly_used_up=True` 回的行集必须**恰好等于**服务端
`distribution` 的第一档（`le_0_2`）—— 同夹具同断言（`test_nearly_used_up_equals_server_first_bucket`）。

零真实网络：`get_admin_api_client` 全部 mock；零真实 LLM。
"""
from __future__ import annotations

import ast
import inspect
import json
import re
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.batch_stock_query import BatchStockQueryTool

# tests/ → ai-agent-service/ → backend/ → 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROLLER = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
    / "admin" / "controller" / "StockBatchController.java"
)
_SERVICE = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
    / "admin" / "service" / "StockBatchConsumptionService.java"
)

# ── 服务端读面夹具（**与 admin-api 的 DTO 逐字段一致**；工具必须原样透传） ──────────
#: 批次余量（9 行）：余量 0.2 / −0.3 / 0.1 ⇒ 落服务端第一档（3 个）；其余按档分布。
#: 负余量（超扣）**也在第一档**（`BatchStockViews.Distribution` 的档位口径），
#: 故「快用尽」不许用 `onlyAvailable` 过滤掉它。
BATCHES = [
    {"batchId": 1, "batchNo": "PC-20260901-0001", "productId": "prod-1", "skuId": 11,
     "skuCode": "C-01", "inboundNo": "IN-20260901-01", "dyeLot": "A12",
     "receivedDate": "2026-09-01", "unitCost": 8.5,
     "inboundMeters": 10.0, "consumedMeters": 9.8, "remainingMeters": 0.2},
    {"batchId": 2, "batchNo": "PC-20260902-0002", "productId": "prod-1", "skuId": 11,
     "skuCode": "C-01", "inboundNo": "IN-20260902-01", "dyeLot": "A13",
     "receivedDate": "2026-09-02", "unitCost": 8.5,
     "inboundMeters": 10.0, "consumedMeters": 10.3, "remainingMeters": -0.3},
    {"batchId": 3, "batchNo": "PC-20260903-0003", "productId": "prod-1", "skuId": 12,
     "skuCode": "C-02", "inboundNo": "IN-20260903-01", "dyeLot": "B07",
     "receivedDate": "2026-09-03", "unitCost": 9.0,
     "inboundMeters": 12.0, "consumedMeters": 11.9, "remainingMeters": 0.1},
    {"batchId": 4, "batchNo": "PC-20260904-0004", "productId": "prod-1", "skuId": 12,
     "skuCode": "C-02", "inboundNo": "IN-20260904-01", "dyeLot": "B08",
     "receivedDate": "2026-09-04", "unitCost": 9.0,
     "inboundMeters": 12.0, "consumedMeters": 11.6, "remainingMeters": 0.4},
    {"batchId": 5, "batchNo": "PC-20260905-0005", "productId": "prod-1", "skuId": 12,
     "skuCode": "C-02", "inboundNo": "IN-20260905-01", "dyeLot": "B09",
     "receivedDate": "2026-09-05", "unitCost": 9.0,
     "inboundMeters": 12.0, "consumedMeters": 11.5, "remainingMeters": 0.5},
    {"batchId": 6, "batchNo": "PC-20260906-0006", "productId": "prod-1", "skuId": 13,
     "skuCode": "C-03", "inboundNo": "IN-20260906-01", "dyeLot": "C01",
     "receivedDate": "2026-09-06", "unitCost": 7.2,
     "inboundMeters": 20.0, "consumedMeters": 19.1, "remainingMeters": 0.9},
    {"batchId": 7, "batchNo": "PC-20260907-0007", "productId": "prod-1", "skuId": 13,
     "skuCode": "C-03", "inboundNo": "IN-20260907-01", "dyeLot": "C02",
     "receivedDate": "2026-09-07", "unitCost": 7.2,
     "inboundMeters": 20.0, "consumedMeters": 19.0, "remainingMeters": 1.0},
    {"batchId": 8, "batchNo": "PC-20260908-0008", "productId": "prod-1", "skuId": 13,
     "skuCode": "C-03", "inboundNo": "IN-20260908-01", "dyeLot": "C03",
     "receivedDate": "2026-09-08", "unitCost": 7.2,
     "inboundMeters": 20.0, "consumedMeters": 18.5, "remainingMeters": 1.5},
    {"batchId": 9, "batchNo": "PC-20260909-0009", "productId": "prod-1", "skuId": 13,
     "skuCode": "C-03", "inboundNo": "IN-20260909-01", "dyeLot": "C04",
     "receivedDate": "2026-09-09", "unitCost": 7.2,
     "inboundMeters": 20.0, "consumedMeters": 18.0, "remainingMeters": 2.0},
]

#: 剩余量分布（四档；与 BATCHES 的分档计数一致：3 / 2 / 2 / 2）
DISTRIBUTION = {
    "totalBatches": 9,
    "buckets": [
        {"key": "le_0_2", "label": "≤0.2 米", "batchCount": 3, "share": 0.3333},
        {"key": "b0_2_0_5", "label": "0.2~0.5 米", "batchCount": 2, "share": 0.2222},
        {"key": "b0_5_1", "label": "0.5~1 米", "batchCount": 2, "share": 0.2222},
        {"key": "gt_1", "label": ">1 米", "batchCount": 2, "share": 0.2222},
    ],
}

#: 省料看板（L2/L3 读面；issue #5159）。**刻意取「逐行取整再求和 ≠ 整段求和再取整」的账**：
#: `formulaMeters − plannedMeters = 40.00 − 15.33 = 24.67`，而逐行 `ROUND(…,2)` 再求和 = **24.68**。
#: 这正是「在 agent 侧重算 ⇒ 与读面差几分钱」的真实形态（判据 2 的红证夹具）。
BOARD = {
    "granularity": "month",
    "timezone": "Asia/Shanghai",
    "cohorts": [
        {"cohort": "purchase", "cohortLabel": "切换后（采购入库）", "opening": False,
         "batchCount": 7, "le0_2Count": 3, "le0_2Share": 0.4286, "remainingMeters": 4.8,
         "savedMeters": 24.68, "savedAmount": 113.45, "lineCount": 2, "unknownCostLines": 0,
         "buckets": DISTRIBUTION["buckets"]},
        {"cohort": "opening", "cohortLabel": "存量导入（切换前历史包袱）", "opening": True,
         "batchCount": 2, "le0_2Count": 0, "le0_2Share": None, "remainingMeters": None,
         "savedMeters": None, "savedAmount": None, "lineCount": 0, "unknownCostLines": 0,
         "buckets": []},
        {"cohort": "unknown", "cohortLabel": "来源未知", "opening": False,
         "batchCount": 0, "le0_2Count": 0, "le0_2Share": None, "remainingMeters": None,
         "savedMeters": None, "savedAmount": None, "lineCount": 0, "unknownCostLines": 0,
         "buckets": []},
    ],
    "batchGroups": [],
    "savedGroups": [
        {"period": "2026-09", "cohort": "purchase", "cohortLabel": "切换后（采购入库）",
         "opening": False, "materialKey": "prod-1|C-01", "productId": "prod-1",
         "skuCode": "C-01", "formulaMeters": 40.00, "plannedMeters": 15.33,
         "savedMeters": 24.68, "savedAmount": 113.45, "lineCount": 2, "unknownCostLines": 0},
    ],
    "total": {"formulaMeters": 40.00, "plannedMeters": 15.33, "savedMeters": 24.68,
              "savedAmount": 113.45, "lineCount": 2, "unknownCostLines": 0,
              "batchCount": 9, "le0_2Count": 3, "le0_2Share": 0.3333},
}

#: 省料趋势（L3）
TREND = {
    "granularity": "month",
    "timezone": "Asia/Shanghai",
    "points": [
        {"period": "2026-09", "purchasedMeters": 120.0, "openingMeters": 300.0,
         "consumedMeters": 100.0, "outputAreaM2": 50.0, "metersPerM2": 2.0, "outputLines": 8},
    ],
    "purchasedTotalMeters": 120.0,
    "consumedTotalMeters": 100.0,
    "openingTotalMeters": 300.0,
}

#: 无数据的看板（服务端口径：`lineCount == 0` ⇒ 合计/比率为 `null`，**不是 0**）
BOARD_EMPTY = {
    "granularity": "month",
    "timezone": "Asia/Shanghai",
    "cohorts": [
        {"cohort": c, "cohortLabel": lbl, "opening": c == "opening", "batchCount": 0,
         "le0_2Count": 0, "le0_2Share": None, "remainingMeters": None, "savedMeters": None,
         "savedAmount": None, "lineCount": 0, "unknownCostLines": 0, "buckets": []}
        for c, lbl in (("purchase", "切换后（采购入库）"),
                       ("opening", "存量导入（切换前历史包袱）"),
                       ("unknown", "来源未知"))
    ],
    "batchGroups": [],
    "savedGroups": [],
    "total": {"formulaMeters": None, "plannedMeters": None, "savedMeters": None,
              "savedAmount": None, "lineCount": 0, "unknownCostLines": 0,
              "batchCount": 0, "le0_2Count": 0, "le0_2Share": None},
}

DISTRIBUTION_EMPTY = {
    "totalBatches": 0,
    "buckets": [
        {"key": "le_0_2", "label": "≤0.2 米", "batchCount": 0, "share": 0},
        {"key": "b0_2_0_5", "label": "0.2~0.5 米", "batchCount": 0, "share": 0},
        {"key": "b0_5_1", "label": "0.5~1 米", "batchCount": 0, "share": 0},
        {"key": "gt_1", "label": ">1 米", "batchCount": 0, "share": 0},
    ],
}

TREND_EMPTY = {"granularity": "month", "timezone": "Asia/Shanghai", "points": [],
               "purchasedTotalMeters": None, "consumedTotalMeters": None,
               "openingTotalMeters": None}


@pytest.fixture
def tool():
    return BatchStockQueryTool()


@pytest.fixture
def seller_context():
    """商户员工（米宝）：持有批次读面所需权限码 `product:list`"""
    return ToolContext(tenant_id=7, user_id="agent_007", session_id="sess_bs_1",
                       role="operator", permissions=["product:list"])


def _stub(payload, captured: list | None = None):
    """把 admin-api 的 GET 打成固定响应；`captured` 收调用参数（断言端点与 query 参数）"""
    client = AsyncMock()

    async def _get(path, **kwargs):
        if captured is not None:
            captured.append((path, kwargs))
        return {"success": True, "data": payload}

    client.get = AsyncMock(side_effect=_get)
    return patch("app.tools.batch_stock_query.get_admin_api_client", return_value=client)


def _tool_source() -> str:
    return Path(inspect.getfile(BatchStockQueryTool)).read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：权限对齐（解析 admin-api 源码真值，不手抄）
# ══════════════════════════════════════════════════════════════════════════

#: `@RequirePermission("码")` 紧跟 `@GetMapping("/路径")`（Controller 的实际书写形态）
_ENDPOINT_PERM_RE = re.compile(
    r'@RequirePermission\("([^"]+)"\)\s*(?:@\w+(?:\([^)]*\))?\s*)*@GetMapping\("([^"]+)"\)'
)
_TOOL_PATH_RE = re.compile(r'"(/api/admin/batch-stock/[a-z-]+)"')


def _endpoint_permissions(src: str) -> dict[str, str]:
    """Java 源码 → {端点相对路径: 权限码}（真值来自 `@RequirePermission` 标注）"""
    return {path: code for code, path in _ENDPOINT_PERM_RE.findall(src)}


class TestPermissionAlignment:
    """判据 3：工具权限码与它调用的 admin-api 端点**逐字一致**"""

    #: 本单接的四个读面（一个 action 对一个端点）；控制器上另有 reconcile / candidates /
    #: consumptions 三个端点属别的能力面，不在本单射程（**有意不接**，不是漏接线）。
    COVERED = ("/batches", "/distribution", "/saving-board", "/saving-trend")

    def test_controller_permissions_are_parsed(self):
        """前置自断言：解析器真能读到 7 个端点（否则下面的子集断言会真空通过）"""
        perms = _endpoint_permissions(_CONTROLLER.read_text(encoding="utf-8"))
        assert len(perms) == 7, f"端点解析数不符（解析器坏了 ⇒ 判据空跑）：{perms}"
        assert set(perms.values()) == {"product:list"}

    def test_tool_permission_code_equals_endpoint_permission_verbatim(self, tool):
        perms = _endpoint_permissions(_CONTROLLER.read_text(encoding="utf-8"))
        assert tool.required_permissions == ["product:list"]
        # 逐字相等：工具接的每个端点，其服务端权限码必须就是工具声明的那个码
        for path in self.COVERED:
            assert perms[path] in tool.required_permissions, path

    def test_tool_calls_exactly_those_endpoints(self, tool):
        """工具调的端点 = 本单该接的四个（少调/多调/写错路径/接上别的端点都红）"""
        perms = _endpoint_permissions(_CONTROLLER.read_text(encoding="utf-8"))
        prefix = "/api/admin/batch-stock"
        got = set(_TOOL_PATH_RE.findall(_tool_source()))
        # ① 无幽灵端点（每个调用点都必须真在 Controller 上）
        assert got <= {f"{prefix}{p}" for p in perms}, f"调了控制器上不存在的端点：{got}"
        # ② 不漏接线（四个 action 各自一个端点）
        assert got == {f"{prefix}{p}" for p in self.COVERED}

    def test_permission_drift_is_detected(self):
        """红证：把 Java 侧一个端点的码改掉 ⇒ 上面的「逐字相等」判据必须报红"""
        src = _CONTROLLER.read_text(encoding="utf-8")
        drifted = src.replace('@RequirePermission("product:list")\n    @GetMapping("/batches")',
                              '@RequirePermission("product:manage")\n    @GetMapping("/batches")', 1)
        assert drifted != src, "注入点未命中 —— 红证失效"
        perms = _endpoint_permissions(drifted)
        assert perms["/batches"] == "product:manage"
        assert perms["/batches"] not in ["product:list"]

    def test_permission_code_is_the_gate(self, tool):
        """持有码 ⇒ 放行；不持有 ⇒ 拒绝（工具层与 admin-api 403 同口径）"""
        holder = ToolContext(tenant_id=7, user_id="u1", role="operator",
                             permissions=["product:list", "order:list"])
        assert tool.check_permission(holder) is True
        loser = ToolContext(tenant_id=7, user_id="u2", role="operator",
                            permissions=["order:list"])
        assert tool.check_permission(loser) is False
        wildcard = ToolContext(tenant_id=7, user_id="u3", role="admin", permissions=["*"])
        assert tool.check_permission(wildcard) is True

    def test_customer_is_hard_blocked(self, tool):
        """C 端硬闸：批次成本/省料金额是内部口径，`customer` 一律不可达（纵深防御）"""
        customer = ToolContext(tenant_id=7, user_id="c1", role="customer", permissions=["*"])
        assert tool.check_permission(customer) is False


class TestMetadataContract:
    """元数据：只读标注 + LLM 触发/前置/反例/标注齐备"""

    def test_read_only_metadata(self, tool):
        assert tool.name == "batch_stock_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True
        # 声明了权限码的工具不得再声明角色白名单（假门禁，`tests/test_tool_permission_codes.py` 静态锁）
        assert "allowed_roles" not in vars(type(tool))

    def test_description_carries_trigger_prereq_counterexample(self, tool):
        desc = tool.description
        assert "【触发】" in desc and "批次" in desc and "省料" in desc
        assert "【前置】" in desc
        assert "【反例】" in desc and "inventory_manage" in desc
        assert "READONLY" in desc

    def test_schema_actions(self, tool):
        props = tool.parameters["properties"]
        assert tool.parameters["required"] == ["action"]
        assert set(props["action"]["enum"]) == {
            "batches", "distribution", "saving_board", "saving_trend"}


# ══════════════════════════════════════════════════════════════════════════
# 判据 1：四类查询都能拿到真实读数
# ══════════════════════════════════════════════════════════════════════════

class TestReadings:
    async def test_batches_returns_server_rows_verbatim(self, tool, seller_context):
        captured: list = []
        with _stub([dict(r) for r in BATCHES], captured):
            result = await tool.execute(context=seller_context, action="batches",
                                       product_id="prod-1")
        assert result.success is True
        path, kwargs = captured[0]
        assert path == "/api/admin/batch-stock/batches"
        assert kwargs["params"] == {"productId": "prod-1"}
        assert kwargs["tenant_id"] == 7 and kwargs["user_id"] == "agent_007"
        # 逐行原样（不重算余量、不改字段名）
        assert result.data["batches"] == BATCHES
        assert result.data["batch_count"] == 9
        assert result.data["truncated"] is False
        assert "9" in result.message

    async def test_batch_no_filter(self, tool, seller_context):
        with _stub([dict(r) for r in BATCHES]):
            result = await tool.execute(context=seller_context, action="batches",
                                        batch_no="PC-20260903-0003")
        assert [b["batchNo"] for b in result.data["batches"]] == ["PC-20260903-0003"]

    async def test_dye_lot_filter(self, tool, seller_context):
        with _stub([dict(r) for r in BATCHES]):
            result = await tool.execute(context=seller_context, action="batches",
                                        dye_lot="b07")
        assert [b["dyeLot"] for b in result.data["batches"]] == ["B07"]

    async def test_distribution_four_buckets_verbatim(self, tool, seller_context):
        with _stub(json.loads(json.dumps(DISTRIBUTION))):
            result = await tool.execute(context=seller_context, action="distribution")
        assert result.data["buckets"] == DISTRIBUTION["buckets"]
        assert result.data["totalBatches"] == 9
        # 档位文案取自服务端 label（不自己写数字）
        assert "≤0.2 米" in result.message

    async def test_saving_board_verbatim(self, tool, seller_context):
        with _stub(json.loads(json.dumps(BOARD))):
            result = await tool.execute(context=seller_context, action="saving_board")
        assert result.data["cohorts"] == BOARD["cohorts"]
        assert result.data["total"] == BOARD["total"]
        # 来源组标签取自服务端（存量单列）；合计逐值回述
        assert "存量导入" in result.message and "24.68" in result.message

    async def test_saving_trend_verbatim(self, tool, seller_context):
        captured: list = []
        with _stub(json.loads(json.dumps(TREND)), captured):
            result = await tool.execute(context=seller_context, action="saving_trend",
                                        granularity="month")
        assert captured[0][1]["params"] == {"granularity": "month"}
        assert result.data["points"] == TREND["points"]
        assert result.data["purchasedTotalMeters"] == 120.0
        assert result.data["openingTotalMeters"] == 300.0


# ══════════════════════════════════════════════════════════════════════════
# 🔴 判据 2：口径同源 —— 省料度量逐值等于读面（不另算一份）
# ══════════════════════════════════════════════════════════════════════════

class TestSavingSameSource:
    async def test_saved_metrics_equal_read_face_value_by_value(self, tool, seller_context):
        """逐值相等：工具回的每个省料数字 == `saving-board` 读面的那个数字"""
        with _stub(json.loads(json.dumps(BOARD))):
            result = await tool.execute(context=seller_context, action="saving_board")
        got, face = result.data, BOARD
        for key in ("savedMeters", "savedAmount", "formulaMeters", "plannedMeters",
                    "lineCount", "unknownCostLines"):
            assert Decimal(str(got["total"][key])) == Decimal(str(face["total"][key])), key
        for i, cohort in enumerate(face["cohorts"]):
            for key in ("savedMeters", "savedAmount", "le0_2Share", "remainingMeters",
                        "le0_2Count", "lineCount", "unknownCostLines"):
                assert got["cohorts"][i][key] == cohort[key], (i, key)
        for i, grp in enumerate(face["savedGroups"]):
            for key in ("savedMeters", "savedAmount", "formulaMeters", "plannedMeters"):
                assert (Decimal(str(got["savedGroups"][i][key]))
                        == Decimal(str(grp[key]))), (i, key)

    def test_naive_client_side_recompute_drifts(self):
        """**红证**：在 agent 侧重算这份夹具 ⇒ 与读面**不等**（差 0.01）⇒ 判据 2 会红。

        读面口径 = 逐行 `ROUND(…, 2)` 再求和（V119 落账值）；朴素重算 =
        `Σformula − Σplanned` 再取整。夹具刻意让两者不同（`#5159` 的 `SavedGroup` 注释
        点名了这个差几分的形态）⇒ 任何「agent 自己算」的实现都过不了上面那条逐值相等。
        """
        naive = Decimal(str(BOARD["total"]["formulaMeters"])) - Decimal(
            str(BOARD["total"]["plannedMeters"]))
        read_face = Decimal(str(BOARD["total"]["savedMeters"]))
        assert naive == Decimal("24.67")
        assert read_face == Decimal("24.68")
        assert naive != read_face, "夹具退化成「重算 == 读面」⇒ 判据 2 变空断言"

    def test_saving_metrics_are_not_recomputed_from_lines(self, tool, seller_context):
        """工具源码里**没有**把 formula/planned 相减的构造（防回归的重算形态）"""
        src = _tool_source()
        assert "formulaMeters -" not in src and "formula_meters -" not in src
        assert "- plannedMeters" not in src and "- planned_meters" not in src


# ══════════════════════════════════════════════════════════════════════════
# 「快用尽」档位同源（不自己定档）
# ══════════════════════════════════════════════════════════════════════════

class TestNearlyUsedUpBucket:
    async def test_nearly_used_up_equals_server_first_bucket(self, tool, seller_context):
        """同夹具：工具 `nearly_used_up=True` 的行集 == 服务端 `distribution` 第一档的行集"""
        with _stub([dict(r) for r in BATCHES]):
            result = await tool.execute(context=seller_context, action="batches",
                                        nearly_used_up=True)
        got_numbers = {b["batchNo"] for b in result.data["batches"]}
        count = DISTRIBUTION["buckets"][0]["batchCount"]
        by_bucket = {r["batchNo"] for r in BATCHES if float(r["remainingMeters"]) <= 0.2}
        assert len(got_numbers) == count == 3
        assert got_numbers == by_bucket

    async def test_nearly_used_up_does_not_drop_negative_remaining(self, tool, seller_context):
        """负余量（超扣）**也在第一档** —— 不许用 `onlyAvailable` 把它过滤掉（口径漂移）"""
        captured: list = []
        with _stub([dict(r) for r in BATCHES], captured):
            result = await tool.execute(context=seller_context, action="batches",
                                        nearly_used_up=True)
        assert "onlyAvailable" not in captured[0][1]["params"]
        assert any(float(b["remainingMeters"]) < 0 for b in result.data["batches"])

    def test_threshold_matches_backend_constant(self):
        """阈值单点来源与服务端 `LE_0_2` **逐字一致**（改了任一侧 ⇒ 红）"""
        from app.tools.stock_semantics import BATCH_NEARLY_USED_UP_METERS

        m = re.search(r'LE_0_2\s*=\s*new BigDecimal\("([0-9.]+)"\)',
                      _SERVICE.read_text(encoding="utf-8"))
        assert m, "服务端常量解析失败（解析器坏了 ⇒ 判据空跑）"
        assert BATCH_NEARLY_USED_UP_METERS == Decimal(m.group(1))
        # 红证：漂移必须能被这条判据识别
        assert Decimal("0.3") != Decimal(m.group(1))

    def test_no_bare_bucket_literal_in_tool(self):
        """工具里不得出现裸档位字面量（第二份会漂的口径）——AST 硬守卫 + 红证"""
        def offenders(src: str) -> list[str]:
            bad = []
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    if repr(node.value) in {"0.2", "0.5"}:
                        bad.append(repr(node.value))
            return bad

        src = _tool_source()
        assert offenders(src) == []
        # 红证：注入一处裸字面量 ⇒ 判据必须报出（证判据非恒真）
        injected = src + "\n_BARE = 0.2\n"
        assert offenders(injected) == ["0.2"]


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：只读无副作用
# ══════════════════════════════════════════════════════════════════════════

_WRITE_CALL_RE = re.compile(r"\.\s*(post|put|patch|delete)\s*\(")


class TestReadOnlyNoSideEffects:
    def test_tool_source_has_no_write_call(self):
        src = _tool_source()
        assert _WRITE_CALL_RE.findall(src) == [], "只读工具里出现写调用"

    def test_injected_write_call_is_caught(self):
        """红证：注入一处写调用 ⇒ 上面那条判据必须能认出（证判据非恒真）"""
        src = _tool_source()
        assert "client.get(" in src
        injected = src.replace("client.get(", "client.patch(", 1)
        assert _WRITE_CALL_RE.findall(injected) == ["patch"]
        assert _WRITE_CALL_RE.findall(src) != _WRITE_CALL_RE.findall(injected)

    async def test_execute_never_issues_write_verb(self, tool, seller_context):
        """运行期：四个 action 跑一遍，客户端只被 `get` 调用过"""
        for action, payload in (("batches", [dict(r) for r in BATCHES]),
                                ("distribution", DISTRIBUTION),
                                ("saving_board", BOARD),
                                ("saving_trend", TREND)):
            client = AsyncMock()
            client.get = AsyncMock(return_value={"success": True, "data": payload})
            with patch("app.tools.batch_stock_query.get_admin_api_client",
                       return_value=client):
                result = await tool.execute(context=seller_context, action=action)
            assert result.success is True
            for verb in ("post", "put", "patch", "delete"):
                getattr(client, verb).assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：空数据不冒充 0
# ══════════════════════════════════════════════════════════════════════════

class TestEmptyDataIsNotZero:
    async def test_batches_empty(self, tool, seller_context):
        with _stub([]):
            result = await tool.execute(context=seller_context, action="batches",
                                        product_id="prod-1")
        assert result.success is True
        assert result.data["batches"] == []
        assert "无数据" in result.message

    async def test_distribution_empty(self, tool, seller_context):
        with _stub(json.loads(json.dumps(DISTRIBUTION_EMPTY))):
            result = await tool.execute(context=seller_context, action="distribution")
        assert "无数据" in result.message
        # 计数 0 是事实（保留），但不得把「读不出」说成 0
        assert result.data["totalBatches"] == 0

    async def test_saving_board_null_metrics_stay_null(self, tool, seller_context):
        with _stub(json.loads(json.dumps(BOARD_EMPTY))):
            result = await tool.execute(context=seller_context, action="saving_board")
        assert "无数据" in result.message
        assert result.data["total"]["savedMeters"] is None
        assert result.data["total"]["savedAmount"] is None
        assert result.data["total"]["le0_2Share"] is None
        assert result.data["cohorts"][0]["savedMeters"] is None

    async def test_saving_trend_empty(self, tool, seller_context):
        with _stub(json.loads(json.dumps(TREND_EMPTY))):
            result = await tool.execute(context=seller_context, action="saving_trend")
        assert "无数据" in result.message
        assert result.data["purchasedTotalMeters"] is None
        assert result.data["openingTotalMeters"] is None

    async def test_ratio_none_never_rendered_as_zero(self, tool, seller_context):
        """`le0_2Share=None` ⇒ 文案里不得出现「0%」（0% 会被读成「没有浪费」）"""
        with _stub(json.loads(json.dumps(BOARD_EMPTY))):
            result = await tool.execute(context=seller_context, action="saving_board")
        assert "0%" not in result.message and "0.0%" not in result.message


# ══════════════════════════════════════════════════════════════════════════
# 失败路径：一律走共享映射点（`admin_api_failure`），如实告知、不编数
# ══════════════════════════════════════════════════════════════════════════

class TestFailurePaths:
    async def test_invalid_action(self, tool, seller_context):
        result = await tool.execute(context=seller_context, action="nope")
        assert result.success is False
        assert "action" in (result.suggestion or "") or "操作类型" in result.message

    async def test_admin_api_403_maps_to_permission_denied(self, tool, seller_context):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "PERMISSION_DENIED", "message": "需要权限: product:list"},
        })
        with patch("app.tools.batch_stock_query.get_admin_api_client", return_value=client):
            result = await tool.execute(context=seller_context, action="saving_board")
        assert result.success is False
        assert result.error_code == "PERMISSION_DENIED"
        assert "product:list" in (result.suggestion or "")

    async def test_network_exception_is_honest(self, tool, seller_context):
        """链路异常 ⇒ 如实失败，**不编一个 0 出来**（summary/data 都不得带假读数）"""
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("app.tools.batch_stock_query.get_admin_api_client", return_value=client):
            result = await tool.execute(context=seller_context, action="distribution")
        assert result.success is False
        assert result.data is None and result.summary is None
        assert result.error == "tool_execution_failed"
