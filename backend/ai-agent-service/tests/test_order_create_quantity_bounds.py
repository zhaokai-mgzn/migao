"""order_create 明细数值校验 — 数量/单价/小计的正数闸门（issue #3586）

缺陷：`items[].quantity` 只检查「字段存在」，**不检查正负** → 负数量可落库。
证据链：
- 工具侧 `int(item["quantity"])` 直转，schema 只声明 `"type": "integer"`（无下限）；
- 下游 `OrderService.createOrder` 不做正负判断 → `unitPrice × 负数` 算出**负金额**落库，
  且「需求量 ≤ 库存」对负需求恒真 → 库存校验被绕过；
- Agent 路径的 admin-api 入参（`AgentOrderCreateRequest.AgentOrderItem`）**无 Bean Validation**，
  表单路径 `OrderCreateRequest` 的 `@Positive` 不覆盖它 → 后端不会拦。

本测试锁三层（L2 值语义 + L1 schema 契约 + L0 静态不变式）：
1. 负数量/0 数量 → **本地拒绝且未发生 HTTP 调用**（fail-fast）；
2. 合法输入（正整数、带单位「3米」、字符串数字、单价小数）→ 仍然通过（防过严）；
3. 拒绝路径必须带**可行动** suggestion；
4. 静态不变式：所有写工具的**必填数值参数**都必须声明下限（防第 N 次复发）。
"""
# case_ids: OR-024, OR-016
import importlib
import inspect
import pkgutil

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import BaseTool, ToolContext
from app.tools.order_create import OrderCreateTool


# ── 静态不变式豁免清单（每条必须注明归属任务包，禁止沉默扩张）──
# 扫描规则：写工具（read_only=False）schema 里 **required 且 type ∈ {integer, number}**
# 的叶子参数，必须声明 `minimum` 或 `exclusiveMinimum`（JSON Schema 下限关键字）。
# 豁免即「已知缺口」，修掉后**必须从本清单删除**（否则测试会提醒你清单已过期）。
NUMERIC_BOUND_EXEMPTIONS = {
    # 归属：W 包（商品域），本包（#3586）不改该文件 → 只报告
    "sku_update.price": "商品改价：price 无数值下限声明（负数价格可提交，属同类缺口，归 W 包）",
}

_NUMERIC_TYPES = {"integer", "number"}


def _iter_write_tool_classes():
    """遍历 app.tools 下所有**写工具**（read_only=False）的类"""
    import app.tools as tools_pkg

    for modinfo in pkgutil.iter_modules(tools_pkg.__path__):
        if modinfo.name.startswith("__"):
            continue
        try:
            mod = importlib.import_module(f"app.tools.{modinfo.name}")
        except Exception:
            continue
        for _, obj in vars(mod).items():
            if not inspect.isclass(obj) or obj.__module__ != mod.__name__:
                continue
            if not issubclass(obj, BaseTool):
                continue
            if not isinstance(getattr(obj, "name", None), str) or not obj.name:
                continue
            if getattr(obj, "read_only", False):
                continue
            yield obj


def _walk_required_numeric(tool_name: str, node, path: str = ""):
    """递归收集 schema 中「必填 + 数值型」的叶子参数 → [(fqn, type, has_bound)]"""
    found = []
    if not isinstance(node, dict):
        return found
    props = node.get("properties") or {}
    required = set(node.get("required") or [])
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        here = f"{path}{key}"
        if spec.get("type") in _NUMERIC_TYPES and key in required:
            has_bound = spec.get("minimum") is not None or spec.get("exclusiveMinimum") is not None
            found.append((f"{tool_name}.{here}", spec.get("type"), has_bound))
        if spec.get("type") == "object":
            found += _walk_required_numeric(tool_name, spec, f"{here}.")
        if spec.get("type") == "array" and isinstance(spec.get("items"), dict):
            found += _walk_required_numeric(tool_name, spec["items"], f"{here}[].")
    return found


def test_write_tool_required_numeric_params_declare_lower_bound():
    """L0 静态不变式（issue #3586）：写工具必填数值参数必须声明下限。

    这是本包「防第 N 次复发」的关键：数量/金额类参数漏了下限，是**结构性**缺陷
    （不依赖真实 LLM 探测即可判定），必须在 L0 秒级拦住，而不是等评测把负数订单落进库再发现。
    范围收敛说明：只守「必填 + 数值型」叶子 —— 可选数值字段（如 width/height/top_n）
    语义各异（部分确实允许 0 或不适用），硬套下限会误伤，故不纳入硬门禁。
    """
    offenders = []
    for cls in _iter_write_tool_classes():
        for fqn, _type, has_bound in _walk_required_numeric(cls.name, getattr(cls, "parameters", {}) or {}):
            if not has_bound and fqn not in NUMERIC_BOUND_EXEMPTIONS:
                offenders.append(fqn)
    assert offenders == [], (
        "以下写工具的**必填数值参数**没有声明数值下限（应加 minimum / exclusiveMinimum）：\n  - "
        + "\n  - ".join(sorted(offenders))
        + "\n若确认是已知缺口且归属别的任务包，请加入 NUMERIC_BOUND_EXEMPTIONS 并注明归属。"
    )


def test_scan_actually_sees_order_create_numeric_params():
    """不变式哨兵：扫描器必须真的扫到 order_create 的数量/单价/小计。

    防「扫描器空转 → 不变式恒绿」（同类事故先例：validate_input 规则表分层读错导致校验全空转）。
    """
    seen = set()
    for cls in _iter_write_tool_classes():
        for fqn, _type, _has in _walk_required_numeric(cls.name, getattr(cls, "parameters", {}) or {}):
            seen.add(fqn)
    assert "order_create.items[].quantity" in seen
    assert "order_create.items[].unit_price" in seen
    assert "order_create.items[].subtotal" in seen


def test_order_create_schema_declares_quantity_and_price_bounds():
    """L1 契约：order_create 的 schema 必须声明数量/单价/小计下限（LLM 侧在同一处看到约束）"""
    item_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"]
    assert item_props["quantity"].get("exclusiveMinimum") == 0
    assert item_props["unit_price"].get("exclusiveMinimum") == 0
    assert item_props["subtotal"].get("minimum") == 0


@pytest.fixture
def tool():
    return OrderCreateTool()


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")


def _items(**overrides):
    base = {
        "product_name": "遮光窗帘",
        "quantity": 3,
        "unit_price": 168.0,
        "subtotal": 504.0,
    }
    base.update(overrides)
    return [base]


class TestOrderCreateQuantityBounds:
    """数量：必须为正整数（拒绝负数/0/小数），且在 HTTP 之前拒绝"""

    @pytest.mark.parametrize("bad_qty", [-1, -3, 0, "-1", "-3米", "-2.5"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_non_positive_quantity_rejected_without_http_call(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """负数量/0 被本地拒绝，且**未发生任何 HTTP 调用**（fail-fast，不白跑一轮）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=bad_qty),
        )

        assert result.success is False
        assert "数量" in result.error
        # 关键：HTTP 未发生（get_admin_api_client 甚至不该被取用）
        mock_client.post.assert_not_called()
        mock_get_client.assert_not_called()

    @pytest.mark.parametrize("bad_qty", [-1, 0])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_rejection_suggestion_is_actionable(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """拒绝路径必须给出**可行动** suggestion：说明应改成什么值、为什么不能是负数"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=bad_qty),
        )

        suggestion = result.suggestion or ""
        assert suggestion, "拒绝路径必须带 suggestion（否则 LLM 无法自愈）"
        # 可行动 = 指明正确取值形态 + 说明负数为什么不行（不是「参数错误」这类空话）
        assert "正整数" in suggestion
        if bad_qty < 0:
            assert "金额变成负数" in (result.message or "") or "负数" in suggestion
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("bad_qty", [-1, -3, 0])
    async def test_negative_quantity_not_normalized_into_payload(
        self, bad_qty, tool, agent_ctx
    ):
        """负数数量绝不能以任何形式进入请求体（防「校验放行 + 负值透传」半修）"""
        with patch("app.tools.order_create.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            await tool.execute(
                context=agent_ctx,
                customer_name="张三",
                customer_phone="13800138000",
                items=_items(quantity=bad_qty),
            )
            assert mock_client.post.await_count == 0

    @pytest.mark.parametrize("bad_qty,expect_kw", [
        (2.5, "整数"),
        ("2.5米", "整数"),
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_fractional_quantity_rejected_not_truncated(
        self, mock_get_client, bad_qty, expect_kw, tool, agent_ctx
    ):
        """小数数量必须**拒绝**而不是静默截断（int(2.5)=2 → 少收钱/少发货）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=bad_qty),
        )

        assert result.success is False, "2.5 米被静默截断成 2 米会让顾客少收货/商家少收钱"
        assert expect_kw in (result.error + (result.message or ""))
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("bad_qty", ["abc", "", True, float("nan"), float("inf")])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_unparseable_quantity_rejected_with_suggestion(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """非数字/布尔/NaN 不是「正数」——必须本地拒绝并给可行动提示"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=bad_qty),
        )

        assert result.success is False
        assert "数量" in result.error
        assert result.suggestion, "不可解析的数量也必须给可行动 suggestion"
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_none_quantity_rejected_as_missing_field(self, mock_get_client, tool, agent_ctx):
        """quantity=None 走「必填字段缺失」分支（等价阻断，且不产生 HTTP）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=None),
        )

        assert result.success is False
        assert "quantity" in result.error
        mock_client.post.assert_not_called()


class TestOrderCreateAmountBounds:
    """金额：单价/小计非负，单价必须 > 0"""

    @pytest.mark.parametrize("bad_price", [-1, -0.01, "-168"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_negative_unit_price_rejected(self, mock_get_client, bad_price, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(unit_price=bad_price, subtotal=0.0),
        )

        assert result.success is False
        assert "单价" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_zero_unit_price_rejected(self, mock_get_client, tool, agent_ctx):
        """0 元单价：后端 `@Positive` 必拒 → 工具侧提前拒绝，避免白跑一轮"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(unit_price=0, subtotal=0.0),
        )

        assert result.success is False
        assert "单价" in result.error and "大于 0" in (result.error + (result.message or ""))
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_negative_subtotal_rejected(self, mock_get_client, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(subtotal=-504.0),
        )

        assert result.success is False
        assert "小计" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_subtotal_below_quantity_times_price_rejected(self, mock_get_client, tool, agent_ctx):
        """小计 < 数量×单价 → 金额自相矛盾（少收钱），必须拒绝"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=3, unit_price=168.0, subtotal=100.0),
        )

        assert result.success is False
        assert "小计" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()


class TestOrderCreateValidInputsStillPass:
    """防过严：合法输入必须照旧通过（含带单位「3米」与字符串数字）"""

    @pytest.mark.parametrize("quantity,unit_price,subtotal", [
        (3, 168.0, 504.0),            # 标准整数
        ("3", 168.0, 504.0),          # 字符串数字（LLM/表单常见）
        ("3米", 168.0, 504.0),        # 带单位的口语输入：3 米 → 3（参数语义，不得拦）
        (" 10 米 ", "168.00元", 1680.0),  # 带空格/货币单位
        (1, 0.5, 0.5),                # 最小合法量与小数单价
        (3, 168.0, 552.0),            # 小计含加工费（> 数量×单价，OR-014 口径）
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_valid_quantity_forms_pass(
        self, mock_get_client, quantity, unit_price, subtotal, tool, agent_ctx
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3586", "orderNo": "ORD-3586"}}
        )
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=quantity, unit_price=unit_price, subtotal=subtotal),
        )

        assert result.success is True, f"合法输入被误拦：{quantity=} {unit_price=} {subtotal=} → {result.error}"
        assert mock_client.post.await_count == 1, "合法输入必须真的发出请求（不得因校验过严而阻断）"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_unit_suffixed_quantity_sent_as_integer(
        self, mock_get_client, tool, agent_ctx
    ):
        """「3米」→ 请求体 quantity=3（int），不得把「3米」原样发给 Java Integer"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3586", "orderNo": "ORD-3586"}}
        )
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[{
                "product_name": "遮光窗帘",
                "quantity": "3米",
                "unit_price": "¥168.00",
                "subtotal": "504",
            }],
        )

        assert result.success is True
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["quantity"] == 3
        assert sent["items"][0]["unitPrice"] == 168.0
        assert sent["items"][0]["subtotal"] == 504.0

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_second_line_bounds_checked_too(self, mock_get_client, tool, agent_ctx):
        """多行明细：第 2 行的负数也要拦下（防只校验首行）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[
                {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0},
                {"product_name": "北欧风窗帘", "quantity": -2, "unit_price": 99.0, "subtotal": -198.0},
            ],
        )

        assert result.success is False
        assert "第 2 项" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_bounds_checked_before_sms_verification(self, mock_get_client, tool):
        """customer 角色：数值校验必须在 SMS 验证**之前**（不因验证码问题掩盖参数错误，
        也不产生 Redis 往返）"""
        ctx = ToolContext(tenant_id=1, user_id="user_001", session_id="s", role="customer")
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        with patch("app.tools.order_create.OrderCreateTool._verify_sms_code", new=AsyncMock()) as m_verify:
            result = await tool.execute(
                context=ctx,
                customer_name="张三",
                customer_phone="13800138000",
                sms_code="123456",
                items=_items(quantity=-1),
            )
            assert result.success is False
            assert "数量" in result.error
            m_verify.assert_not_called()
        mock_client.post.assert_not_called()
