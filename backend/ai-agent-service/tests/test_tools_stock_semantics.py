"""库存口径单点来源：低库存阈值（#3783）+ 商品库存唯一权威（#4038）

## 商品库存的唯一权威 = **SKU 级**（`product_skus.stock`，issue #4038）

依据（DB 实测 2026-09-18，云 dev，复现命令见 #4038）：

  · 同一商品两个数字：`products.stock` 与 SKU 汇总在 **311/497** 个商品上不一致；
  · 「有 SKU 的 351 个商品里 **299 个商品级恒为 0**」——而 SKU 合计可以很大，
    如实测商品 `2699系列雪尼尔窗帘面料`：商品级 **0** / SKU 合计 **9599**；
  · 仓库既有真值 `.github/templates/product-sku-stock.yml`：
    「商品库存 = 所有 SKU 库存求和（`products.stock` 常为 0，以 SKU 汇总为准）」；
  · 扣减（订单流程）、低库存口径、列表排序、详情/列表返回的 `stock` **全部已按 SKU 级**。

⇒ 商品级 `products.stock` 是**派生冗余列（非权威）**，工具层不得各自采信；
`stock_semantics.product_stock_summary()` 是工具层商品库存数字的**唯一入口**。

---

「低库存」阈值口径：单点来源一致性 + 上界语义（issue #3783）

修复前（`origin/main` @ f9cb59d7）同一个「低库存」在 AI 工具层有**三处互不相同**的口径：

  · `product_search.py`：`LOW_STOCK_THRESHOLD = 100`（与后台 #1396 同源，工具文案「库存≤100」）
  · `inventory_manage.py` schema：`"default": 10` + 文案「默认 10」（LLM 据此调用）
  · `inventory_manage.py::_low_stock_alert`：形参默认 `100`（与**同文件** schema 自相矛盾）

⇒ 同一句「低库存」问话，两条工具路径（以及同一工具的不同调用路径）会给出两个数字，
而两者都自称「低库存」。

产品裁定（issue #3783）：权威口径 = **100**（与后台 Dashboard 卡片 / DailyBriefing /
admin-web 商品列表同源，见 #1396），单点来源 = `app/tools/stock_semantics.py`；
工具对 LLM 可见的 schema 描述 / `default` **必须由该来源生成**（不允许工具里另写字面量）。

守卫强度：`test_no_bare_threshold_literal_in_tools` 是防「两套变三套」的硬守卫 ——
两个工具模块里**不允许**再出现裸整数字面量 `10` / `100`。
"""
# case_ids: PR-003, PR-004, PR-006

import ast
import inspect
import pathlib
import re
from unittest.mock import AsyncMock, patch

from app.tools.inventory_manage import InventoryManageTool
from app.tools.product_search import ProductSearchTool, STOCK_STATUS_TO_STOCK_BELOW

TOOLS_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "tools"
TOOL_MODULES = ("product_search.py", "inventory_manage.py")
# #4038：取**商品库存数字**的两个工具模块（都走 GET /api/admin/products/{id}，响应含 `skus`）。
# `product_search.py` 不在内 —— 它走列表接口、响应里没有 `skus` 明细，无法本地重算
# （后端已按契约 `data.stock = SUM(data.skus[].stock)` 给聚合值）。
AUTHORITY_TOOL_MODULES = ("product_detail.py", "inventory_manage.py")

# 产品裁定的权威口径（issue #3783 / #1396）。**故意写成绝对值**：若有人把全栈口径
# 一起改成别的数，本断言必须红，逼迫口径变更走显式评审（而不是靠改常量顺手漂移）。
AUTHORITATIVE_LOW_STOCK = 100
# 上界语义：含上界（≤，非 <）。依据 = admin-api 两条 SQL 均为 `ps.stock <= 阈值`
# （`ProductMapper.findLowStockByColor` 与 `ProductService` 的 `stockBelow`），
# Dashboard 卡片文案同样是「库存 ≤ 100」。
AUTHORITATIVE_OPERATOR = "≤"


def _shared():
    """单点来源模块（#3783 收敛后存在；修复前不存在 ⇒ 本文件必红）。"""
    from app.tools import stock_semantics

    return stock_semantics


class TestSingleSourceOfTruth:
    """三处口径必须全部等于**同一个**来源常量。"""

    def test_authoritative_value_is_100(self):
        assert _shared().LOW_STOCK_THRESHOLD == AUTHORITATIVE_LOW_STOCK

    def test_product_search_mapping_uses_authoritative_threshold(self):
        assert STOCK_STATUS_TO_STOCK_BELOW["low_stock"] == AUTHORITATIVE_LOW_STOCK

    def test_inventory_schema_default_is_authoritative(self):
        schema = InventoryManageTool.parameters["properties"]["threshold"]
        assert schema["default"] == AUTHORITATIVE_LOW_STOCK

    def test_inventory_schema_is_generated_by_shared_source(self):
        """schema（描述 + default）必须由单点来源生成，而不是工具里另写一份字面量。"""
        assert (
            InventoryManageTool.parameters["properties"]["threshold"]
            == _shared().low_stock_alert_threshold_schema()
        )

    def test_inventory_runtime_defaults_are_authoritative(self):
        """调用链入口 `execute` 与实现 `_low_stock_alert` 的默认值必须同值。"""
        for fn in (InventoryManageTool.execute, InventoryManageTool._low_stock_alert):
            default = inspect.signature(fn).parameters["threshold"].default
            assert default == AUTHORITATIVE_LOW_STOCK, (
                f"{fn.__qualname__} 的 threshold 默认值 = {default}，"
                f"与权威口径 {AUTHORITATIVE_LOW_STOCK} 不一致"
            )

    def test_llm_visible_texts_state_authoritative_threshold(self):
        """LLM 能读到的 description / 参数说明里的数字必须等于权威口径。"""
        phrase = f"库存{AUTHORITATIVE_OPERATOR}{AUTHORITATIVE_LOW_STOCK}"

        assert phrase in ProductSearchTool.description
        assert phrase in ProductSearchTool.parameters["properties"]["stock_status"]["description"]

        # 修复前这里写的是「默认 10」——三处口径里唯一被 LLM 直接读到的那处
        threshold_desc = InventoryManageTool.parameters["properties"]["threshold"]["description"]
        declared_default = re.search(r"默认\s*(\d+)", threshold_desc)
        assert declared_default, f"schema 文案未声明默认值：{threshold_desc!r}"
        assert int(declared_default.group(1)) == AUTHORITATIVE_LOW_STOCK, (
            f"LLM 读到的 schema 文案默认值 = {declared_default.group(1)}，"
            f"与权威口径 {AUTHORITATIVE_LOW_STOCK} 不一致"
        )

    def test_no_bare_threshold_literal_in_tools(self):
        """防「两套变三套」：两个工具模块内不得再出现裸字面量 10 / 100。

        阈值只能来自单点来源模块（`stock_semantics`），否则迟早再分裂出第 N 套口径。
        """
        offenders = []
        for name in TOOL_MODULES:
            tree = ast.parse((TOOLS_DIR / name).read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, int)
                    and not isinstance(node.value, bool)
                    and node.value in (10, 100)
                ):
                    offenders.append(f"{name}:{node.lineno} 裸字面量 {node.value}")
        assert not offenders, "工具模块内仍有裸阈值字面量：" + "; ".join(offenders)


class TestProductStockAuthority:
    """商品库存的唯一权威 = SKU 级（issue #4038）。

    红证（改前 @ origin/main）：`stock_semantics` 只有低库存阈值、**没有**商品库存口径
    ⇒ 各工具自行拼装：`product_detail.py` 直读后端 `data["stock"]`、
    `inventory_manage.py` 用 `data.get("stock", 0)` 兜底 **0**（「无 SKU 记录」被谎报成「没货」）。
    """

    def test_authority_is_sku(self):
        """权威方向必须显式钉死，且不是商品级。"""
        assert _shared().STOCK_AUTHORITY == "sku"

    def test_summary_follows_sku_sum(self):
        summary = _shared().product_stock_summary([{"stock": 9000}, {"stock": 599}])
        assert summary["stock"] == 9599
        assert summary["stock_source"] == "sku_sum"

    def test_summary_no_sku_is_unknown_not_zero(self):
        """无 SKU 记录 ⇒ `None`（无法确认），**不得**是 0（会被读成「没货」）。"""
        for empty in ([], None):
            summary = _shared().product_stock_summary(empty)
            assert summary["stock"] is None, f"skus={empty!r} 被谎报成 {summary['stock']!r}"
            assert summary["stock_source"] == "no_sku"

    def test_summary_tolerates_missing_stock_value(self):
        """单个 SKU 缺 stock 键按 0 计（不抛异常），但整体仍按 SKU 权威求和。"""
        assert _shared().product_stock_summary([{"id": "s1"}, {"stock": 7}])["stock"] == 7

    def test_no_sku_note_never_claims_zero_or_out_of_stock(self):
        """用户可见文案不得出现「库存 0 / 没货」这类会被当真的事实断言。"""
        note = _shared().no_sku_stock_note("测试帘")
        assert "测试帘" in note
        assert "尚未维护 SKU" in note
        assert "库存 0" not in note and "没货" not in note and "缺货" not in note

    def test_tool_modules_take_stock_from_single_source(self):
        """硬守卫（防「两套变三套」的商品库存版）：两个工具模块必须经单点来源取商品库存。

        ① 正向：必须出现 `product_stock_summary(`；
        ② 反向：不得再出现直读**后端商品级聚合**的形态 `data.get("stock")` / `data["stock"]`
           （改前 `product_detail.py` 与 `inventory_manage.py` 各有一处 —— 前者报给 LLM，
           后者用 `, 0` 兜底把「无 SKU 记录」谎报成「没货」）。

        用 AST 而非文本扫描：**注释里提到这两个形态不算违规**（本文件的意图是扫代码）。
        范围仅限裸名 `data`：`resp_data.get("stock")` 是 agent 库存端点的读回校验，
        该端点的契约本身就是「返回 SKU 汇总值」（见 `AgentProductController` 注释），不在本守卫范围。
        """
        for name in AUTHORITY_TOOL_MODULES:
            src = (TOOLS_DIR / name).read_text(encoding="utf-8")
            assert "product_stock_summary(" in src, (
                f"{name} 未通过 stock_semantics.product_stock_summary 取商品库存"
            )

            offenders = []
            for node in ast.walk(ast.parse(src)):
                target = None
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "data"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    target = node.args[0].value
                elif (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "data"
                    and isinstance(node.slice, ast.Constant)
                ):
                    target = node.slice.value
                if target == "stock":
                    offenders.append(f"{name}:{node.lineno}")

            assert not offenders, (
                "仍在直读后端的商品级聚合 stock（" + "; ".join(offenders) + "）—— "
                "商品库存的唯一权威是 SKU 级，见 issue #4038"
            )


class TestUpperBoundInclusive:
    """阈值语义：**含上界**（≤，非 <）。"""

    def test_operator_is_inclusive(self):
        assert _shared().LOW_STOCK_OPERATOR == AUTHORITATIVE_OPERATOR
        assert _shared().LOW_STOCK_OPERATOR != "<"
        assert _shared().low_stock_phrase() == f"库存{AUTHORITATIVE_OPERATOR}{AUTHORITATIVE_LOW_STOCK}"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_runtime_message_uses_inclusive_wording(self, mock_get_client, admin_tool_context):
        """运行期文案必须与后端 SQL 的「≤」一致，不得写成「低于」（严格小于）。

        修复前：`没有 SKU 库存低于 100 的商品` —— 与后端 `stock <= 100` 矛盾
        （stock==100 的 SKU 明明会被返回）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        tool = InventoryManageTool()
        result = await tool.execute(context=admin_tool_context, action="low_stock_alert")

        assert result.success is True
        assert f"库存{AUTHORITATIVE_OPERATOR}{AUTHORITATIVE_LOW_STOCK}" in result.message
        assert "低于" not in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_threshold_passed_through_without_off_by_one(self, mock_get_client, admin_tool_context):
        """不得用 `threshold - 1` 去模拟「严格小于」：阈值原样透传（上界含由后端 SQL 保证）。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        tool = InventoryManageTool()
        await tool.execute(context=admin_tool_context, action="low_stock_alert")
        assert mock_client.get.call_args.kwargs["params"]["threshold"] == AUTHORITATIVE_LOW_STOCK

        await tool.execute(context=admin_tool_context, action="low_stock_alert", threshold=7)
        assert mock_client.get.call_args.kwargs["params"]["threshold"] == 7

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_sends_inclusive_stock_below(self, mock_get_client, sample_tool_context):
        """product_search 的 low_stock 也必须走同一权威口径（后端 stockBelow 上界含）。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        tool = ProductSearchTool()
        await tool.execute(context=sample_tool_context, keyword="窗帘", stock_status="low_stock")

        assert mock_client.get.call_args.kwargs["params"]["stockBelow"] == AUTHORITATIVE_LOW_STOCK

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_rejection_message_states_authoritative_threshold(
        self, mock_get_client, sample_tool_context
    ):
        """词表外取值的拒绝提示（LLM 可见）也必须用权威口径措辞。"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        tool = ProductSearchTool()
        result = await tool.execute(context=sample_tool_context, keyword="窗帘", stock_status="in_stock")

        assert result.success is False
        assert f"库存{AUTHORITATIVE_OPERATOR}{AUTHORITATIVE_LOW_STOCK}" in (result.suggestion or "")
