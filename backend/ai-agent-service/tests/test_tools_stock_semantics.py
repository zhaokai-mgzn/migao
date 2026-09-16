"""「低库存」阈值口径：单点来源一致性 + 上界语义（issue #3783）

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
# case_ids: PR-006

import ast
import inspect
import pathlib
import re
from unittest.mock import AsyncMock, patch

from app.tools.inventory_manage import InventoryManageTool
from app.tools.product_search import ProductSearchTool, STOCK_STATUS_TO_STOCK_BELOW

TOOLS_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "tools"
TOOL_MODULES = ("product_search.py", "inventory_manage.py")

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
