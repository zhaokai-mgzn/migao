"""order_create 明细参数闸门 — 数量/单价/小计/尺寸/加工费/枚举（issue #3586 + #3622）

缺陷（#3586）：`items[].quantity` 只检查「字段存在」，**不检查正负** → 负数量可落库。
证据链：
- 工具侧 `int(item["quantity"])` 直转，schema 只声明 `"type": "integer"`（无下限）
  （issue #3666 已把数量放宽为 `"type": "number"` + 服务端 DECIMAL(10,2)，小数合法）；
- 下游 `OrderService.createOrder` 不做正负判断 → `unitPrice × 负数` 算出**负金额**落库，
  且「需求量 ≤ 库存」对负需求恒真 → 库存校验被绕过；
- Agent 路径的 admin-api 入参（`AgentOrderCreateRequest.AgentOrderItem`）**无 Bean Validation**，
  表单路径 `OrderCreateRequest` 的 `@Positive` 不覆盖它 → 后端不会拦。

同族残留（#3622，同一文件同一范式扩展）：
- `items[].width`/`height` 无下限 → 负尺寸 → per_area **负面积**；
- `items[].processing_info.processingFee` 无下限 → 负加工费拉低总额；
- `processing_info.processingItems[].quantity`/`unitPrice`/`subtotal` **运行期无闸门**
  → `sumProcessingFee`（OrderService:807-829 = Σ unitPrice×quantity）算出**负加工费**；
- `sellingMethod`/`pricingMethod` 无枚举 → 拼写变体（"散剪"、"per_piece"）静默落库
  （后端 OrderService:1435 按**字面**比较 SKU.selling_method → 静默不匹配）；
- `items[].product_name` 只判存在不判非空 → `""` 可通过。

本测试锁三层（L2 值语义 + L1 schema 契约 + L0 静态不变式）：
1. 负数量/0 数量/负尺寸/负加工费/非法枚举 → **本地拒绝且未发生 HTTP 调用**（fail-fast）；
2. 合法输入（正整数、带单位「3米」、字符串数字、单价小数、per_area 小数加工数量、
   canonical 枚举值）→ 仍然通过（防过严）；
3. 拒绝路径必须带**可行动** suggestion（说明应改成什么值 / 合法枚举）；
4. 静态不变式：写工具的金额/数量/尺寸数值参数必须声明下限、枚举型参数必须声明 `enum`
   （防第 N 次复发，两条锁各带哨兵）。

同族残留（issue #3682，`items[].quantity` 下限从「>0」收紧为「≥1」）：
- #3666 把数量放宽为**可为小数的正数**（per_area 的 8.4 ㎡ 必须保真），但 `>0` 同时放行了
  **<1 的小数**（如 0.5 米）——而服务端 `OrderService` 对 `BigDecimal quantity` 取整数部分
  （`:1051` 库存校验 / `:1408` `deductStock` / `:1409` `increaseSalesCount`）：
  0.5 → `needed=0` 校验恒通过、`deductStock(0)` 不减库存、销量 +0 →
  **订单成交但库存/销量零变动，且无任何告警**（账实不符）。
- 旧实现（`quantity` 为 Integer + `_reject_quantity` 拒绝非整数）在**下单前**就挡回 0.5
  并给可行动提示，故这是 #3666 放宽后**新可达**的静默漏扣，不是「回归」。
- 裁定（issue #3682 方案 A）：agent 路径的**订单数量**下限 = 1，与 admin-web 表单
  `orders/new/page.tsx:1081` 的 `min={1}` 同口径；**小数仍合法**（2.5 米 / 8.4 ㎡）。
- 边界：`processingInfo.processingItems[].quantity`（加工数量）**不设该下限**——它不驱动
  库存/销量，且 per_area 的面积可以合法 <1 ㎡（设 ≥1 会误伤小面积加工单，见本文件
  `TestOrderCreateParamGuardSchemaContract.test_processing_item_bounds_declared`）。
"""
# case_ids: OR-024, OR-016, OR-028, OR-015
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
    # 归属：W 包（商品域，product_*.py 文件所有权），本包（#3622）不改这些文件 → 只报告
    "sku_update.price": "商品改价：price 无数值下限声明（负数价格可提交，属同类缺口，归 W 包）",
    "product_manage.price": "建品 price 无数值下限声明（负数价格可提交，归 W 包 product_*.py）",
    "product_update.price": "改品 price 无数值下限声明（负数价格可提交，归 W 包 product_*.py）",
    # 归属：AC 包（加工项域，processing_item_manage.py 文件所有权），本包禁改 → 只报告
    "processing_item_manage.price": "建/改加工项 price 无数值下限声明（归 AC 包）",
    "processing_item_manage.quantity": "加工项 quantity 无数值下限声明（归 AC 包）",
}

# ── 枚举型参数豁免清单（#3622 新增同源锁）──
# 扫描规则：写工具 schema 里**字段名**属于枚举语义注册表的参数，必须声明非空 `enum`。
# 为什么用「字段名注册表」而不是「required + enum」：enum 型参数**没声明 enum 时无法
# 从 schema 反推它是枚举**（信息缺失），而本次缺口（sellingMethod/pricingMethod）
# 都是**可选嵌套**参数 —— 用 required 过滤会让锁对缺口完全空转（假锁）。
ENUM_DECLARATION_EXEMPTIONS = {
    "sku_update.selling_method": (
        "归属 #3616/#3621（门幅/售卖方式口径包）：该包可能选别名归一化而非拒绝，"
        "为避免两包对同一字段给出相反契约，本包只报告不改"
    ),
}

# ── 语义注册表（#3622）──
# 金额/数量/尺寸类字段名：一旦为负，直接污染金额/库存/面积数学 → 必须声明下限（含**可选**字段）。
_MONEY_QTY_SIZE_FIELD_NAMES = {
    "quantity", "unit_price", "unitPrice", "subtotal",
    "processingFee", "price", "amount", "width", "height",
}
# 枚举型字段名：拼写变体会静默落库（后端按字面比较/落 JSONB）→ 必须声明 `enum`。
_ENUM_FIELD_NAMES = {"sellingMethod", "selling_method", "pricingMethod", "pricing_method"}

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


def _walk_params(tool_name: str, node, path: str = ""):
    """递归收集 schema 中**所有**叶子参数 → [(fqn, leaf_name, spec, required)]

    单一遍历入口：三条不变式（必填数值下限 / 金额尺寸下限 / 枚举声明）共用，
    避免多套扫描器各扫各的（#3586 先例：分层读取不一致 → 校验全空转）。
    """
    found = []
    if not isinstance(node, dict):
        return found
    props = node.get("properties") or {}
    required = set(node.get("required") or [])
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        here = f"{path}{key}"
        found.append((f"{tool_name}.{here}", key, spec, key in required))
        if spec.get("type") == "object":
            found += _walk_params(tool_name, spec, f"{here}.")
        if spec.get("type") == "array" and isinstance(spec.get("items"), dict):
            found += _walk_params(tool_name, spec["items"], f"{here}[].")
    return found


def _iter_all_params():
    """遍历所有写工具的全部叶子参数 → [(fqn, leaf_name, spec, required)]"""
    for cls in _iter_write_tool_classes():
        yield from _walk_params(cls.name, getattr(cls, "parameters", {}) or {})


def _has_lower_bound(spec: dict) -> bool:
    return spec.get("minimum") is not None or spec.get("exclusiveMinimum") is not None


def _walk_required_numeric(tool_name: str, node, path: str = ""):
    """递归收集 schema 中「必填 + 数值型」的叶子参数 → [(fqn, type, has_bound)]"""
    return [
        (fqn, spec.get("type"), _has_lower_bound(spec))
        for fqn, _leaf, spec, required in _walk_params(tool_name, node, path)
        if required and spec.get("type") in _NUMERIC_TYPES
    ]


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


# ══════════════════════════════════════════════════════════════════════════
# L0 静态不变式（#3622）：把本包修的字段纳入覆盖面 —— 两条锁 + 两条哨兵
# ══════════════════════════════════════════════════════════════════════════

def test_write_tool_money_and_size_numeric_params_declare_lower_bound():
    """L0 静态不变式（#3622）：写工具的**金额/数量/尺寸类**数值参数（含可选）必须声明下限。

    为什么在 #3586 那条锁之外再要一条：原锁只守「必填 + 数值型」叶子，而本次修的四类
    缺口恰好全是**可选嵌套**参数（width/height、processingFee、processingItems[].*）——
    用 required 过滤会让锁对本包缺口完全空转（假锁）。故按**字段语义注册表**扫描。

    范围说明：注册表只收「负数会直接污染金额/库存/面积数学」的字段名；其余可选数值字段
    （top_n / page / delay 等）语义各异，硬套下限会误伤，仍不进本锁。
    """
    offenders = []
    for fqn, leaf, spec, _required in _iter_all_params():
        if leaf in _MONEY_QTY_SIZE_FIELD_NAMES and spec.get("type") in _NUMERIC_TYPES:
            if not _has_lower_bound(spec) and fqn not in NUMERIC_BOUND_EXEMPTIONS:
                offenders.append(fqn)
    assert offenders == [], (
        "以下写工具的**金额/数量/尺寸类数值参数**没有声明数值下限（应加 minimum / exclusiveMinimum）：\n  - "
        + "\n  - ".join(sorted(offenders))
        + "\n若确认是已知缺口且归属别的任务包，请加入 NUMERIC_BOUND_EXEMPTIONS 并注明归属。"
    )


def test_write_tool_enum_semantic_params_declare_enum():
    """L0 静态不变式（#3622）：写工具的**枚举型参数**必须在 schema 里声明 `enum`。

    为什么必须有：枚举值拼写变体（"散剪"/"bulkCut"/"per_piece"）会**静默落库**——后端
    `OrderService:1435` 按字面比较 SKU.selling_method → 静默不匹配 → 库存/销量静默丢失；
    LLM 侧在 schema 里也看不到合法值。这是**结构性**缺陷（不依赖真实 LLM 探测即可判定），
    必须在 L0 秒级拦住。

    为什么不用 required 过滤：`enum` 未声明时无法从 schema 反推「它本该是枚举」，而本次
    缺口（sellingMethod/pricingMethod）都是**可选嵌套**参数 —— required 过滤 = 锁空转。
    """
    offenders = []
    for fqn, leaf, spec, _required in _iter_all_params():
        if leaf not in _ENUM_FIELD_NAMES:
            continue
        enum = spec.get("enum")
        declared = isinstance(enum, list) and bool(enum)
        if not declared and fqn not in ENUM_DECLARATION_EXEMPTIONS:
            offenders.append(fqn)
    assert offenders == [], (
        "以下写工具的**枚举型参数**没有声明 `enum`（拼写变体会静默落库）：\n  - "
        + "\n  - ".join(sorted(offenders))
        + "\n若确认是已知缺口且归属别的任务包，请加入 ENUM_DECLARATION_EXEMPTIONS 并注明归属。"
    )


def test_enum_declarations_are_non_empty_string_lists():
    """`enum` 声明本身必须有效：非空字符串列表（防 `enum: []` / `enum: [None]` 式空转声明）"""
    for fqn, _leaf, spec, _required in _iter_all_params():
        if "enum" not in spec:
            continue
        enum = spec["enum"]
        assert isinstance(enum, list) and enum, f"{fqn} 的 enum 必须是非空列表"
        assert all(isinstance(v, str) and v for v in enum), f"{fqn} 的 enum 项必须是非空字符串"


def test_scan_actually_sees_order_create_processing_and_size_params():
    """哨兵（金额/尺寸下限锁）：扫描器必须真的扫到本包修的**可选嵌套**字段。

    防「扫描器空转 → 不变式恒绿」（#3586 同类先例：规则表分层读错 → 校验全空转）。
    """
    seen = {fqn for fqn, _leaf, _spec, _required in _iter_all_params()}
    for fqn in (
        "order_create.items[].width",
        "order_create.items[].height",
        "order_create.items[].processing_info.processingFee",
        "order_create.items[].processing_info.processingItems[].quantity",
        "order_create.items[].processing_info.processingItems[].unitPrice",
        "order_create.items[].processing_info.processingItems[].subtotal",
    ):
        assert fqn in seen, f"扫描器没扫到 {fqn}（锁可能空转）"


def test_scan_actually_sees_order_create_enum_params():
    """哨兵（枚举锁）：扫描器必须真的扫到 sellingMethod/pricingMethod"""
    seen = {fqn for fqn, _leaf, _spec, _required in _iter_all_params()}
    assert "order_create.items[].processing_info.sellingMethod" in seen
    assert "order_create.items[].processing_info.processingItems[].pricingMethod" in seen


def test_exemptions_reference_existing_params():
    """豁免清单不得指向不存在的参数（防拼错 fqn 的「假豁免」把真缺口盖住）"""
    seen = {fqn for fqn, _leaf, _spec, _required in _iter_all_params()}
    for fqn in NUMERIC_BOUND_EXEMPTIONS:
        assert fqn in seen, f"NUMERIC_BOUND_EXEMPTIONS 里的 {fqn} 不存在（清单已过期/拼错）"
    for fqn in ENUM_DECLARATION_EXEMPTIONS:
        assert fqn in seen, f"ENUM_DECLARATION_EXEMPTIONS 里的 {fqn} 不存在（清单已过期/拼错）"


def test_order_create_schema_declares_quantity_and_price_bounds():
    """L1 契约：order_create 的 schema 必须声明数量/单价/小计下限（LLM 侧在同一处看到约束）

    quantity（issue #3682）：下限是 `minimum: 1`（不是 `exclusiveMinimum: 0`）——
    <1 的数量会静默漏扣库存/销量（服务端取整数部分 = 0），故与 admin-web 的 `min={1}` 同口径。
    """
    item_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"]
    assert item_props["quantity"].get("minimum") == 1
    assert "exclusiveMinimum" not in item_props["quantity"]
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


def _with_library(client, price=168.0, name="遮光窗帘", pid="p1"):
    """给 mock client 装上商品库 GET（order_create 单价接地校验用）。

    `_reject_unit_price_not_grounded` 会在 POST 前按商品名查库价；既有成功路径测试
    的 mock 只有 .post，必须补 .get（否则查库失败 → fail-closed 拒绝）。
    """
    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": pid, "name": name}], "total": 1}}
        return {"success": True, "data": {
            "id": pid, "name": name, "price": price, "basePrice": price,
            "skus": [{"id": f"{pid}-1", "skuCode": "SKU-1", "colorName": "米白",
                      "price": price, "stock": 1}],
        }}
    client.get = AsyncMock(side_effect=_get)
    return client


class TestOrderCreateQuantityBounds:
    """数量：必须 ≥ 1（拒绝负数/0/<1），且**允许小数**（2.5 米 / 8.4 ㎡），HTTP 之前拒绝

    issue #3682 方案 A：下限 1（旧口径 >0 会放行 0.5 → 服务端取整成 0 → 静默漏扣库存/销量）。
    """

    @pytest.mark.parametrize("bad_qty", [-1, -3, 0, "-1", "-3米", "-2.5", 0.5, 0.99, "0.5米", 0.01])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_below_min_quantity_rejected_without_http_call(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """负数/0/**<1 的小数**被本地拒绝，且**未发生任何 HTTP 调用**（fail-fast，不白跑一轮）"""
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

    @pytest.mark.parametrize("bad_qty", [0.5, 0.99, "0.5米", -1, 0])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_below_min_quantity_message_is_actionable(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """<1 的拒绝必须说明**为什么**（库存/销量按整件计 → 0.5 会零扣减）与**改成什么**
        （「不少于 1 米/件」）——否则 LLM 只会原样重试同一份参数。"""
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
        # 可行动 = 指明正确取值下限（不是「参数错误」这类空话）
        assert "不少于 1" in suggestion or "≥ 1" in suggestion or ">= 1" in suggestion, (
            f"suggestion 必须给出数量下限（当前：{suggestion}）"
        )
        # 说明影响：<1 会静默漏扣库存/销量（这是本 issue 的缺陷本体）
        blob = f"{result.message or ''}{suggestion}"
        assert "库存" in blob and ("销量" in blob or "漏扣" in blob), (
            f"<1 的拒绝必须说清影响（库存/销量零变动），当前：{blob}"
        )
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("bad_qty", [0.5, 0.99, 0.01])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_sub_one_quantity_never_sent_to_server(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """<1 的数量绝不能以任何形式进入请求体（防「校验放行 + 0.5 透传」半修：
        服务端 `intValue()` 会把它当成 0 件 → 扣 0 库存、销量 +0）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=bad_qty),
        )

        assert result.success is False
        assert mock_client.post.await_count == 0

    @pytest.mark.parametrize("bad_qty", [-1, 0, 0.5])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_rejection_suggestion_is_actionable(
        self, mock_get_client, bad_qty, tool, agent_ctx
    ):
        """拒绝路径必须给出**可行动** suggestion：说明应改成什么值、为什么不行"""
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
        # issue #3682：口径从「正数」（>0）收紧为「不少于 1」（小数量仍合法）
        assert "不少于 1" in suggestion or "≥ 1" in suggestion or ">= 1" in suggestion
        if bad_qty < 0:
            assert "金额变成负数" in (result.message or "") or "负数" in suggestion
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("bad_qty", [-1, -3, 0, 0.5])
    async def test_negative_quantity_not_normalized_into_payload(
        self, bad_qty, tool, agent_ctx
    ):
        """越界数量绝不能以任何形式进入请求体（防「校验放行 + 负值/<1 透传」半修）"""
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

    @pytest.mark.parametrize("qty,expected", [
        (2.5, 2.5),
        ("2.5米", 2.5),
        (8.4, 8.4),
        ("8.4", 8.4),
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_fractional_quantity_preserved_not_truncated(
        self, mock_get_client, qty, expected, tool, agent_ctx
    ):
        """小数数量必须**保真透传**，不得拒绝也不得截断（issue #3666）。

        口径：per_meter=米数（2.5 米）、per_area=宽×高（2.8×3=8.4 ㎡）。
        旧行为（拒绝小数 + 服务端 Integer 截断）会让 8.4 ㎡ 落成 8 ㎡ →
        30 元/㎡ 的刺绣工艺从 252.00 元变 240.00 元 = **少收 12.00 元**。
        """
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3666", "orderNo": "ORD-3666"}}
        )
        _with_library(mock_client, 100.0, name="刺绣窗帘", pid="p2")
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[{
                "product_name": "刺绣窗帘",
                "quantity": qty,
                "unit_price": 100.0,
                "subtotal": 840.0,
            }],
        )

        assert result.success is True, f"小数数量被误拦：{qty} → {result.error} {(result.message or '')}"
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["quantity"] == pytest.approx(expected), (
            f"数量必须保真透传（{qty} → {expected}），不得截断成 {int(expected)}"
        )

    @pytest.mark.parametrize("qty,expected", [
        (1, 1),                       # 下限值本身：1 是合法的最小订单数量
        (1.0, 1.0),
        ("1米", 1),
        (1.5, 1.5),                   # 下限之上的小数照旧合法
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_minimum_quantity_one_is_valid(
        self, mock_get_client, qty, expected, tool, agent_ctx
    ):
        """下限 1 **不得误伤**：数量 1 / 1.5 必须照常下单（闸门不是「把订单挡在门外」）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3682", "orderNo": "ORD-3682"}}
        )
        _with_library(mock_client, 168.0)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(quantity=qty),
        )

        assert result.success is True, f"下限值被误拦：{qty} → {result.error} {(result.message or '')}"
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["quantity"] == pytest.approx(expected)

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_per_area_case_or028_fabric_3m_with_8_4_sqm_processing_still_passes(
        self, mock_get_client, tool, agent_ctx
    ):
        """**OR-028 防误伤证据**：面料 3 米（items[].quantity=3）+ 刺绣 per_area 8.4 ㎡
        （processingItems[].quantity=8.4，加工费 30×8.4=252.00）。

        这是「两条 quantity 口径不同」的实拍形态：
        - `items[].quantity` = 面料米数 3（≥1，受本发明约束）；
        - `processingItems[].quantity` = 面积 8.4 ㎡（**不设 ≥1 下限**，且必须保真不截断 —— 
          截断成 8 会少收 12.00 元）。
        若有人把 processingItems 也设成 minimum 1，本测试仍绿（8.4≥1）；真正防误伤的是下一条
        `test_small_per_area_below_one_sqm_still_passes`（0.72 ㎡）。
        """
        mock_client = _ok_client(mock_get_client, price=23.80, name="2699系列雪尼尔窗帘面料")
        pinfo = {
            "colorName": "2699-03暖米色",
            "sellingMethod": "bulk_cut",
            "doorWidth": "2.8米",
            "processingItems": [_processing_item(
                id="pi-embroidery", name="刺绣工艺", unitPrice=30.0, quantity=8.4,
                unit="㎡", pricingMethod="per_area", subtotal=252.0)],
            "processingFee": 252.0,
        }

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[{
                "product_name": "2699系列雪尼尔窗帘面料",
                "quantity": 3,
                "unit_price": 23.80,
                "subtotal": 323.40,   # 71.40 面料 + 252.00 加工费
                "width": 2.8,
                "height": 3.0,
                "processing_info": pinfo,
            }],
        )

        assert result.success is True, f"OR-028 形态被误拦：{result.error} {(result.message or '')}"
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["quantity"] == pytest.approx(3)
        assert sent["items"][0]["processingInfo"]["processingItems"][0]["quantity"] \
            == pytest.approx(8.4), "加工项面积 8.4 ㎡ 必须保真（截断成 8 → 少收 12.00 元）"
        assert sent["items"][0]["processingInfo"]["processingFee"] == pytest.approx(252.0)

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_small_per_area_below_one_sqm_still_passes(
        self, mock_get_client, tool, agent_ctx
    ):
        """**裁定边界（防误伤）**：`processingItems[].quantity` **不设 ≥1 下限**。

        理由：加工数量**不驱动库存/销量**（只进 `Σ unitPrice×quantity` 的加工费数学），
        而 per_area 的面积可以合法小于 1 ㎡（如 0.8m × 0.9m = 0.72 ㎡）。
        若给它也设 `minimum: 1`，这类小面积加工单会被硬拒 = 误伤。
        本测试锁住「0.72 ㎡ 加工项照旧下单且金额保真」，防止后人「顺手统一下限」。
        """
        mock_client = _ok_client(mock_get_client)
        pinfo = {
            "colorName": "米白色",
            "sellingMethod": "bulk_cut",
            "processingItems": [_processing_item(
                id="pi-embroidery", name="刺绣工艺", unitPrice=30.0, quantity=0.72,
                unit="㎡", pricingMethod="per_area", subtotal=21.60)],
            "processingFee": 21.60,
        }

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[{
                "product_name": "遮光窗帘",
                "quantity": 1,
                "unit_price": 168.0,
                "subtotal": 189.60,   # 168.00 面料 + 21.60 加工费
                "processing_info": pinfo,
            }],
        )

        assert result.success is True, (
            f"小面积（<1 ㎡）加工项被误拦 —— processingItems 不该有 ≥1 下限：{result.error}"
        )
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["processingInfo"]["processingItems"][0]["quantity"] \
            == pytest.approx(0.72)
        assert sent["items"][0]["processingInfo"]["processingFee"] == pytest.approx(21.60)

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
        # 单价接地校验：库价 mock 与各参数的 unit_price 对齐（0.5 那档是「最小合法量+小数单价」）
        _with_library(mock_client, OrderCreateTool._parse_positive_number(unit_price))
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
        """「3米」→ 请求体 quantity=3（数值），不得把「3米」原样发给服务端 BigDecimal"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3586", "orderNo": "ORD-3586"}}
        )
        _with_library(mock_client, 168.0)
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


# ═══════════════════════════════════════════════════════════════════════════
# #3622 同族残留：尺寸 / 加工费 / 加工项 / 枚举 / 商品名（同一闸门扩展）
# ═══════════════════════════════════════════════════════════════════════════

def _processing_item(**overrides):
    entry = {
        "id": "pi-1", "name": "打孔", "unitPrice": 8.0, "quantity": 3,
        "unit": "米", "pricingMethod": "per_meter", "subtotal": 24.0,
    }
    entry.update(overrides)
    return entry


def _items_with_processing(**processing_info_overrides):
    """单行明细 + processing_info（默认合法：bulk_cut + 打孔 8×3）"""
    pinfo = {
        "colorName": "米白色",
        "sellingMethod": "bulk_cut",
        "doorWidth": "2.8米",
        "processingItems": [_processing_item()],
        "processingFee": 24.0,
    }
    pinfo.update(processing_info_overrides)
    return [{
        "product_name": "遮光窗帘",
        "quantity": 3,
        "unit_price": 168.0,
        "subtotal": 528.0,   # 504 面料 + 24 加工费（OR-014 口径：不要求严格等于数量×单价）
        "processing_info": pinfo,
    }]


def _ok_client(mock_get_client, price=168.0, name="遮光窗帘"):
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value={"success": True, "data": {"id": "ORD-3622", "orderNo": "ORD-3622"}}
    )
    _with_library(mock_client, price=price, name=name)
    mock_get_client.return_value = mock_client
    return mock_client


class TestOrderCreateDimensionBounds:
    """items[].width / height：可选的尺寸字段必须非负（负尺寸 → per_area 负面积）"""

    @pytest.mark.parametrize("field,label", [("width", "宽度"), ("height", "高度")])
    @pytest.mark.parametrize("bad", [-1, -0.5, "-2.8米"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_negative_dimension_rejected_without_http(
        self, mock_get_client, field, label, bad, tool, agent_ctx
    ):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(**{field: bad}),
        )

        assert result.success is False, f"{field}={bad} 是负尺寸，必须本地拒绝（负面积/负尺寸落库）"
        assert label in result.error
        assert result.suggestion, "拒绝路径必须带可行动 suggestion"
        assert "负数" in (result.message or "") or "负数" in result.suggestion
        mock_client.post.assert_not_called()
        mock_get_client.assert_not_called()

    @pytest.mark.parametrize("field", ["width", "height"])
    @pytest.mark.parametrize("bad", ["abc", "宽2.8", ""])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_unparsable_dimension_rejected(
        self, mock_get_client, field, bad, tool, agent_ctx
    ):
        """非数值尺寸注定被 Java BigDecimal 拒 → 本地 fail-fast 并给可行动提示"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=_items(**{field: bad}),
        )

        assert result.success is False
        assert result.suggestion
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_absent_dimension_still_passes(self, mock_get_client, tool, agent_ctx):
        """可选字段不传 → 不拦（防过严）"""
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items(),
        )

        assert result.success is True, f"可选尺寸字段缺失不应被拦：{result.error}"
        assert mock_client.post.await_count == 1

    @pytest.mark.parametrize("field,value,expected", [
        ("width", 2.8, 2.8),
        ("width", "2.8米", 2.8),       # 带单位口语输入 → 落成数值（与 quantity「3米」同口径）
        ("height", " 2.0 米 ", 2.0),
        ("width", 0, 0.0),             # 0 尺寸不构成负面积，放行（schema minimum: 0）
        ("height", 3, 3.0),
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_legal_dimension_passes_and_is_normalized(
        self, mock_get_client, field, value, expected, tool, agent_ctx
    ):
        """合法尺寸（含带单位）必须放行，且落到请求体的是**数值**（Java BigDecimal 可直接解析）"""
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items(**{field: value}),
        )

        assert result.success is True, f"合法尺寸被误拦：{field}={value} → {result.error}"
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0][field] == expected


class TestOrderCreateProcessingFeeAndItemBounds:
    """processing_info.processingFee / processingItems[].quantity|unitPrice|subtotal 非负闸门

    为什么这层最要紧：服务端 `OrderService.sumProcessingFee()`（:824-829）=
    Σ `unitPrice × quantity`（`extractProcessingItems` :807-811 就是这两个字段相乘）
    —— 任一为负 → **负加工费**直接加进 `totalAmount` 落库（第 417 行）。
    """

    @pytest.mark.parametrize("bad_fee", [-1, -24.0, "-24"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_negative_processing_fee_rejected(self, mock_get_client, bad_fee, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(processingFee=bad_fee),
        )

        assert result.success is False
        assert "加工费" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_unparsable_processing_fee_rejected(self, mock_get_client, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(processingFee="二十四"),
        )

        assert result.success is False
        assert "加工费" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("patch_item", [
        {"quantity": -3},
        {"unitPrice": -8},
        {"quantity": -1, "unitPrice": -2},
        {"subtotal": -24},
        {"quantity": "-3米"},
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_negative_processing_item_value_rejected(
        self, mock_get_client, patch_item, tool, agent_ctx
    ):
        """加工项数量/单价/小计为负 → 负加工费 → 本地拒绝（运行期闸门原先完全缺位）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(processingItems=[_processing_item(**patch_item)]),
        )

        assert result.success is False, f"加工项 {patch_item} 为负必须拒绝"
        assert "加工项" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("patch_item", [
        {"quantity": "abc"},
        {"unitPrice": "八元"},
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_unparsable_processing_item_value_rejected(
        self, mock_get_client, patch_item, tool, agent_ctx
    ):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(processingItems=[_processing_item(**patch_item)]),
        )

        assert result.success is False
        assert "加工项" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("pinfo_overrides,label", [
        ({"processingFee": 0.0}, "0 加工费（顾客不要加工项）"),
        ({"processingItems": [_processing_item(quantity=8.4, subtotal=67.2)], "processingFee": 67.2},
         "per_area 小数加工数量 8.4（#3521 实测形态）"),
        ({"processingItems": [_processing_item(unitPrice=0.0, subtotal=0.0)], "processingFee": 0.0},
         "0 元加工项（赠品/免费项）"),
        ({"processingItems": []}, "无加工项明细（老形态）"),
        ({"sellingMethod": "full_roll"}, "整卷售卖方式"),
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_legal_processing_values_still_pass(
        self, mock_get_client, pinfo_overrides, label, tool, agent_ctx
    ):
        """防过严：合法加工口径必须照旧通过（0 费用、小数数量、免费项、老形态）"""
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(**pinfo_overrides),
        )

        assert result.success is True, f"{label} 被误拦：{result.error}"
        assert mock_client.post.await_count == 1

    @pytest.mark.parametrize("bad_entry", ["不是对象", ["列表"], 123, None])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_malformed_processing_item_entry_rejected(
        self, mock_get_client, bad_entry, tool, agent_ctx
    ):
        """加工项元素不是对象 → 后端解析不出金额（静默丢加工费）→ 本地拒绝"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(processingItems=[bad_entry]),
        )

        assert result.success is False
        assert "加工项" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_processing_info_as_json_string_not_silently_misjudged(
        self, mock_get_client, tool, agent_ctx
    ):
        """processing_info 是 JSON 字符串（老形态）→ 不误报（放行交给服务端解析）"""
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items(processing_info='{"colorName":"白色","sellingMethod":"bulk_cut"}'),
        )

        assert result.success is True, f"JSON 字符串形态被误拦：{result.error}"


class TestOrderCreateEnumGuards:
    """sellingMethod / pricingMethod 枚举闸门（拼写变体静默落库）

    后端口径（单一事实源）：
    - `sellingMethod`：`ProductSku.selling_method` = bulk_cut(散剪) / full_roll(整卷)；
      `OrderService:1435` 按**字面** eq 匹配 SKU → 变体静默不匹配（库存/销量静默丢失）。
    - `pricingMethod`：`ProcessingItemService:298` 只认 per_meter/per_set/fixed/per_area
      （per_piece 按个不支持，issue #3005）。
    """

    @pytest.mark.parametrize("bad", ["散剪", "整卷", "bulkCut", "bulk-cut", "BULK_CUT", "按米", "2.8米"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_invalid_selling_method_rejected(self, mock_get_client, bad, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(sellingMethod=bad),
        )

        assert result.success is False, f"售卖方式 {bad!r} 不是合法枚举，必须本地拒绝"
        assert "售卖方式" in result.error
        assert "bulk_cut" in result.suggestion and "full_roll" in result.suggestion, (
            "suggestion 必须点名合法枚举值（LLM 才能自愈）"
        )
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("good", ["bulk_cut", "full_roll"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_canonical_selling_method_passes(self, mock_get_client, good, tool, agent_ctx):
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(sellingMethod=good),
        )

        assert result.success is True, f"合法售卖方式 {good} 被误拦：{result.error}"
        sent = mock_client.post.await_args.kwargs["json_data"]
        assert sent["items"][0]["processingInfo"]["sellingMethod"] == good

    @pytest.mark.parametrize("bad", ["per_piece", "perMeter", "per-meter", "按米", "perM", "", "平方米"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_invalid_pricing_method_rejected(self, mock_get_client, bad, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(
                processingItems=[_processing_item(pricingMethod=bad)],
            ),
        )

        assert result.success is False, f"计价方式 {bad!r} 不是合法枚举，必须本地拒绝"
        assert "计价方式" in result.error
        for legal in ("per_meter", "per_set", "fixed", "per_area"):
            assert legal in result.suggestion, f"suggestion 必须点名 {legal}"
        mock_client.post.assert_not_called()

    @pytest.mark.parametrize("good", ["per_meter", "per_set", "fixed", "per_area"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_canonical_pricing_method_passes(self, mock_get_client, good, tool, agent_ctx):
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(
                processingItems=[_processing_item(pricingMethod=good)],
            ),
        )

        assert result.success is True, f"合法计价方式 {good} 被误拦：{result.error}"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_absent_enum_fields_still_pass(self, mock_get_client, tool, agent_ctx):
        """售卖方式/计价方式是可选的（单 SKU 商品不一定有）→ 缺失不拦"""
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items_with_processing(sellingMethod=None),
        )

        assert result.success is True, f"未传售卖方式被误拦：{result.error}"


class TestOrderCreateProductNameGuard:
    """items[].product_name：必须非空（原先只判存在 → \"\" 可通过）"""

    @pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_blank_product_name_rejected(self, mock_get_client, bad, tool, agent_ctx):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items(product_name=bad),
        )

        assert result.success is False, f"商品名称 {bad!r} 是空串，不得下单"
        assert "商品名称" in result.error
        assert result.suggestion
        mock_client.post.assert_not_called()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_normal_product_name_still_passes(self, mock_get_client, tool, agent_ctx):
        mock_client = _ok_client(mock_get_client)

        result = await tool.execute(
            context=agent_ctx, customer_name="张三", customer_phone="13800138000",
            items=_items(),
        )

        assert result.success is True
        assert mock_client.post.await_count == 1


class TestOrderCreateParamGuardsOrdering:
    """顺序铁律（#3586 建立、#3622 一致）：确定性校验必须排在 SMS 之前"""

    @pytest.mark.parametrize("items,keyword", [
        (_items(width=-1), "宽度"),
        (_items_with_processing(processingFee=-1), "加工费"),
        (_items_with_processing(sellingMethod="散剪"), "售卖方式"),
        (_items(product_name=""), "商品名称"),
    ])
    @patch("app.tools.order_create.get_admin_api_client")
    async def test_guards_run_before_sms_verification(
        self, mock_get_client, items, keyword, tool
    ):
        ctx = ToolContext(tenant_id=1, user_id="user_001", session_id="s", role="customer")
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        with patch("app.tools.order_create.OrderCreateTool._verify_sms_code", new=AsyncMock()) as m_verify:
            result = await tool.execute(
                context=ctx, customer_name="张三", customer_phone="13800138000",
                sms_code="123456", items=items,
            )
            assert result.success is False
            assert keyword in result.error
            m_verify.assert_not_called()
        mock_client.post.assert_not_called()


class TestOrderCreateParamGuardSchemaContract:
    """L1 契约：schema 必须声明本包各闸门（LLM 侧在同一处看到约束）"""

    def test_item_dimension_bounds_declared(self):
        item_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"]
        assert item_props["width"]["minimum"] == 0
        assert item_props["height"]["minimum"] == 0

    def test_item_product_name_min_length_declared(self):
        item_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"]
        assert item_props["product_name"].get("minLength") == 1

    def test_processing_fee_bound_declared(self):
        pi_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"][
            "processing_info"]["properties"]
        assert pi_props["processingFee"]["minimum"] == 0

    def test_processing_item_bounds_declared(self):
        pi_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"][
            "processing_info"]["properties"]
        entry_props = pi_props["processingItems"]["items"]["properties"]
        assert entry_props["quantity"]["minimum"] == 0
        assert entry_props["unitPrice"]["minimum"] == 0
        assert entry_props["subtotal"]["minimum"] == 0

    def test_enum_declarations(self):
        pi_props = OrderCreateTool.parameters["properties"]["items"]["items"]["properties"][
            "processing_info"]["properties"]
        assert pi_props["sellingMethod"]["enum"] == ["bulk_cut", "full_roll"]
        entry_props = pi_props["processingItems"]["items"]["properties"]
        assert entry_props["pricingMethod"]["enum"] == [
            "per_meter", "per_set", "fixed", "per_area"]
