# case_ids: OR-014, OR-015
"""issue #4011（P2 包）A1+A4 红证：

    A1 · order_create 契约撒谎（线上实证的死锁）—— 商品有 >1 个不同 SKU 价、且 item 未带
        `processing_info.colorName` / `skuCode` 时，`_reject_unit_price_not_grounded`
        **直接 fail-closed 拒绝**（连正确的商品库价也拒），而 `items.required` 只声明
        `[product_name, quantity, unit_price, subtotal]`、工具描述也没说“多规格价时必须指定规格”
        ⇒ LLM 从 schema 无从得知 ⇒ 死锁。
        线上实证：OR-014 首跑 11 轮 / **13 次 order_create 调用无一成功**，错误码全
        `unit_price_not_grounded`，**连 @168（正确的商品库价）也被拒**；
        run 35071344830 首跑指纹 `no_success(order_create)`。
    A4 · `validate_input` 假绿 —— 工具已注册但该 action 无校验规则时返回
        `ToolResult(success=True, data={"validated": True, "skipped": True})` ⇒ 模型读到
        “校验通过”继续执行（还会把 `pending_validated_input` 落账 → 下一轮被注入
        “直接调用写工具…不要再发确认卡”的执行提示）。

改前红（每条断言都在 main 上跑过并复现）：
- A1：`test_multi_sku_without_spec_deadlocks_*` —— 改前 `success=False` +
  `unit_price_not_grounded`（合法价 130 / 库价 168 全被拒）。
- A4：`test_unruled_action_is_not_false_green` —— 改前 `success=True` + `skipped=True`。

改后绿 + **负例（R2 硬约束）**：原本合法的输入必须仍然通过 ——
`test_negative_*` 三条：多规格价 + 正确价 + 带 colorName 的下单、库价一致的下单、
已注册写工具的真参数校验，改后一律照常成功。

判据边界（A1 必须保持的原意图，#3875/#3879）：**防编造分色价** ——
库价 168 却报「米白 150」仍必须被拦并回填库价；只是“库价无从确定”不再等于“拒绝一切”。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.order_create import OrderCreateTool
from app.tools.validate_input import ValidateInputTool


# ══════════════════════════════════════════════════════════════════════════
# A1 · order_create 多规格价死锁
# ══════════════════════════════════════════════════════════════════════════

# 分色价夹具：商品级 price=100，SKU 米白 100 / 香槟金 130（>1 个不同 SKU 价）
_SKUS_VARIANT = [
    {"id": "xy-1", "skuCode": "XY-01", "colorName": "米白",
     "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 100.0, "stock": 10},
    {"id": "xy-2", "skuCode": "XY-02", "colorName": "香槟金",
     "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 130.0, "stock": 10},
]


def _detail(name, pid, price, skus):
    return {"success": True, "data": {
        "id": pid, "name": name, "price": price, "basePrice": price,
        "skus": skus, "status": "on_sale"}}


def _run_execute(items, price=168.0, name="遮光窗帘", pid="prod_eval_blackout",
                 skus=None, role="agent"):
    """执行 OrderCreateTool.execute（mock 商品库；记录 POST 是否发生）。

    Returns: (result, post_called)
    """
    client = MagicMock()

    async def fake_get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):  # product_search
            return {"success": True, "data": {
                "items": [{"id": pid, "name": name, "basePrice": price}], "total": 1}}
        return _detail(name, pid, price, skus)

    client.get = AsyncMock(side_effect=fake_get)
    client.post = AsyncMock(return_value={
        "success": True, "data": {"id": "o1", "orderNo": "ORD-2026-0001"}})

    with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
         patch("app.tools.order_create.SMS_BYPASS_CODE", "123456"):
        tool = OrderCreateTool()
        result = asyncio.run(tool.execute(
            context=ToolContext(tenant_id=1, user_id="u1", session_id="s1", role=role),
            customer_name="张三", customer_phone="13800138000", items=items,
        ))
    return result, client.post.called


def _item(name, unit_price, quantity=3, color=None, sku_code=None):
    item = {"product_name": name, "quantity": quantity, "unit_price": unit_price,
            "subtotal": round(unit_price * quantity, 2)}
    if color or sku_code:
        pinfo = {}
        if color:
            pinfo["colorName"] = color
        if sku_code:
            pinfo["skuCode"] = sku_code
        item["processing_info"] = pinfo
    return item


def test_multi_sku_library_price_without_spec_not_deadlocked():
    """A1 红证（改前红）：商品有 2 个不同 SKU 价（100/130）、item 未带规格、
    单价 = **商品库真实价 130**（= 香槟金 SKU 价）→ 改前 100% 被拒（死锁）。

    改后：该单价在商品库中存在 ⇒ 不是“契约撒谎”而是“库价无从唯一确定”，按库价放行
    （服务端 `validateAgentItemUnitPrice` 会按 SKU 复核），不再把正确价一起拒掉。
    """
    result, post_called = _run_execute(
        [_item("分色价商品", 130.0)], price=100.0, skus=_SKUS_VARIANT, name="分色价商品")
    assert post_called is True, (
        f"库中真实存在的单价 130 不得被拒（改前 13 次 order_create 无一成功的死锁形态）: "
        f"{result.error} {result.message}"
    )
    assert result.success is True, f"{result.error} {result.message}"


def test_multi_sku_product_level_price_without_spec_not_deadlocked():
    """A1 红证（线上实证的同一形态）：单价 = **商品级库价 168**、item 未带规格 → 改前被拒。

    这是 OR-014 首跑「连 @168 也被拒」的复现：商品级 price 就是商品库价，
    分色差价存在只说明“规格未知”，不说明“单价编造”。
    """
    skus = [
        {"id": "b-1", "skuCode": "B-01", "colorName": "米白",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 168.0, "stock": 10},
        {"id": "b-2", "skuCode": "B-02", "colorName": "浅灰",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 198.0, "stock": 10},
    ]
    result, post_called = _run_execute(
        [_item("分色价商品", 168.0)], price=168.0, skus=skus, name="分色价商品")
    assert post_called is True, (
        f"商品级库价 168 必须放行（线上 13 次调用连它也被拒）: {result.error} {result.message}")
    assert result.success is True


def test_multi_sku_fabricated_price_still_rejected_with_library_prices():
    """原意图守卫（#3875/#3879）：库价集合 {100,130}，报 115（编造）→ 必须拦 + 回填可行动价。

    改后拒绝话术必须**列出全部库价**（否则模型仍无从自愈 → 换一种死锁）。
    """
    result, post_called = _run_execute(
        [_item("分色价商品", 115.0)], price=100.0, skus=_SKUS_VARIANT, name="分色价商品")
    assert post_called is False, "编造价 115 不在库价集合 {100,130} 中 → 必须拦截"
    assert result.success is False
    assert "unit_price" in (result.error or ""), f"错误码应可归因: {result.error}"
    msg = result.message or ""
    assert "100" in msg and "130" in msg, f"必须回填全部库价供模型自愈: {msg}"
    assert result.suggestion, "fail-closed 分支必须带 suggestion（R5 禁止新静默失效形态）"


def test_multi_sku_unmatched_color_still_rejected():
    """原意图守卫：选了库里没有的颜色 + 编造价 → 仍拦截（按商品级价兜底判，不误放）。"""
    result, post_called = _run_execute(
        [_item("分色价商品", 115.0, color="米黄")], price=100.0, skus=_SKUS_VARIANT,
        name="分色价商品")
    assert post_called is False, "选了库中不存在的颜色且价不符 → 必须拦截"
    assert result.success is False


def test_multi_sku_matched_sku_price_change_follows():
    """原意图守卫：按所选 SKU 判且不写死价 —— 香槟金 130 放行、报 120 拒并回填 130。"""
    ok, ok_posted = _run_execute(
        [_item("分色价商品", 130.0, color="香槟金")], price=100.0, skus=_SKUS_VARIANT,
        name="分色价商品")
    assert ok_posted is True and ok.success is True, f"{ok.error} {ok.message}"

    bad, bad_posted = _run_execute(
        [_item("分色价商品", 120.0, color="香槟金")], price=100.0, skus=_SKUS_VARIANT,
        name="分色价商品")
    assert bad_posted is False and bad.success is False
    assert "130" in (bad.message or ""), f"必须回填所选 SKU 价 130: {bad.message}"


# ── 负例（R2 硬约束）：原本合法的输入改后仍必须通过 ──

def test_negative_correct_spec_and_price_order_still_passes():
    """负例 ①：**多规格价 + 正确价 + 带 colorName** —— 这条本次事故里从未被验证过。

    （#3875/#3879 只测了“错价被拦”，没测“对价通过”，所以单价闸门把正确价也拒了。）
    """
    result, post_called = _run_execute(
        [_item("分色价商品", 100.0, color="米白")], price=100.0, skus=_SKUS_VARIANT,
        name="分色价商品")
    assert post_called is True, f"正确规格+正确价必须通过: {result.error} {result.message}"
    assert result.success is True


def test_negative_sku_code_only_spec_still_passes():
    """负例 ②：只给 skuCode（不给 colorName）指定规格 —— 同样必须通过。"""
    result, post_called = _run_execute(
        [_item("分色价商品", 130.0, sku_code="XY-02")], price=100.0, skus=_SKUS_VARIANT,
        name="分色价商品")
    assert post_called is True and result.success is True, f"{result.error} {result.message}"


def test_negative_uniform_sku_price_order_still_passes():
    """负例 ③：所有 SKU 同价（无分色差价）的常规下单 —— 不因本次改动受任何影响。"""
    skus = [
        {"id": "u-1", "skuCode": "U-01", "colorName": "米白",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 168.0, "stock": 10},
        {"id": "u-2", "skuCode": "U-02", "colorName": "浅灰",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 168.0, "stock": 10},
    ]
    result, post_called = _run_execute([_item("遮光窗帘", 168.0)], price=168.0, skus=skus)
    assert post_called is True and result.success is True, f"{result.error} {result.message}"


def test_schema_declares_multi_sku_spec_requirement():
    """A1 契约面（issue #4011 方案 a）：schema / 工具描述必须让 LLM**看得见**规格要求。

    改前红：`items.required` 只有 [product_name, quantity, unit_price, subtotal]、
    描述里也没有“多规格价时必须指定规格” ⇒ 模型无从知道运行时会被 fail-closed 拒绝。
    """
    tool = OrderCreateTool()
    item_schema = tool.parameters["properties"]["items"]["items"]
    pinfo_desc = item_schema["properties"]["processing_info"]["description"]
    assert "SKU 价" in pinfo_desc and "必填" in pinfo_desc, (
        f"processing_info 描述必须声明“多规格价时必须指定规格”: {pinfo_desc}")
    assert "colorName" in pinfo_desc and "skuCode" in pinfo_desc
    desc = tool.description
    assert "规格必填" in desc and "SKU 价" in desc, (
        "工具描述必须声明多规格价时的规格必填，否则 LLM 仍无从知道（契约撒谎）")
    # 规格标识不得为空串（空串 = 等于没指定）
    assert item_schema["properties"]["processing_info"]["properties"]["colorName"].get("minLength") == 1
    assert item_schema["properties"]["processing_info"]["properties"]["skuCode"].get("minLength") == 1


# ══════════════════════════════════════════════════════════════════════════
# A4 · validate_input 无规则 ⇒ 不得假绿
# ══════════════════════════════════════════════════════════════════════════

# issue #4011 A4 点名的缺口（工具已注册、该 action 无规则）+ 补齐后必须通过的**合法参数**。
# 参数一律按各工具实现的真实必填（不是照抄契约 DTO）—— 假参数会掩盖“规则对不对”。
_GAP_ACTIONS = [
    ("product_manage", "toggle_status", {"product_id": "p1", "status": "off_sale"}),
    ("customer_manage", "remove_tag", {"customer_id": "c1", "tag_id": "t1"}),
    ("customer_manage", "create_tag", {"name": "重点客户"}),
    ("customer_manage", "update_tag", {"tag_id": "t1", "name": "VIP 客户"}),
    ("customer_manage", "delete_tag", {"tag_id": "t1"}),
    ("employee_manage", "update", {"user_id": "u1", "name": "李四"}),
    ("employee_manage", "delete", {"user_id": "u1"}),
    ("employee_manage", "reset_password", {"user_id": "u1"}),
    ("employee_manage", "toggle_status", {"user_id": "u1", "status": "disabled"}),
    ("processing_item_manage", "toggle_item_status", {"item_id": "i1", "status": "inactive"}),
    ("processing_item_manage", "create_category", {"name": "刺绣工艺"}),
    ("processing_item_manage", "update_category", {"category_id": "pc1", "name": "刺绣工艺"}),
    ("processing_item_manage", "delete_category", {"category_id": "pc1"}),
    # 本次全量审计补出的同族缺口（issue #4011 正文未列）：工单状态变更
    ("after_sales_manage", "update_status", {"ticket_id": "t1", "status": "processing"}),
]

# 故意不补规则、也**不该**补的路径（真·无规则 ⇒ 必须失败且带 suggestion，不得假绿）。
# ⚠️ params 必须**非空**：空 dict 会先在 `execute` 顶部的「缺少参数」守卫处短路，
#    到的不是被测的「无规则」分支（早期版本用 {} 踩过这个坑 → 断言测错了对象）。
_NEVER_VALIDATED = [
    ("human_handoff", "human_handoff",
     {"reason": "客户要求转人工"}),                        # 入参全可选（reason/description/summary）
    ("inventory_manage", "query", {"keyword": "窗帘"}),    # 查询 action
    ("category_manage", "tree", {"__probe__": 1}),         # 查询 action
]


@pytest.fixture
def tool():
    return ValidateInputTool()


@pytest.fixture
def admin_ctx():
    return ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="tenant_admin")


@pytest.mark.parametrize("target_tool,target_action,params", _GAP_ACTIONS)
def test_gap_action_no_longer_skipped_and_legal_params_pass(tool, admin_ctx, target_tool,
                                                           target_action, params):
    """A4 红证 + 负例（改前红）：改前这些 action 无规则 ⇒ `success=True, skipped=True` 假绿。

    改后要同时满足两件事：
      ① 真跑了校验（`validated=True` 且**无** `skipped`）—— 这是“假绿已消除”的判据；
      ② 合法参数**仍然通过** —— R2 负例：补齐规则不得把原本合法的写路径拦掉。
    """
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool=target_tool, target_action=target_action,
        params=params,
    ))
    assert result.data.get("skipped") is not True, (
        f"{target_tool}.{target_action} 不得返回 skipped 假绿: {result.data}")
    assert result.success is True, (
        f"{target_tool}.{target_action} 合法参数被拦（假红）: {result.message}")
    assert result.data.get("validated") is True


@pytest.mark.parametrize("target_tool,target_action,params", _GAP_ACTIONS)
def test_gap_action_missing_required_is_rejected_with_suggestion(tool, admin_ctx,
                                                                target_tool, target_action,
                                                                params):
    """A4 红证（改前红，第二形态）：空参数下改前**照样**返回 `skipped` 假绿。

    改后：缺必填 ⇒ 失败 + `suggestion`（R5：新增 fail-closed 分支必须带 suggestion，
    否则 `_self_correct_retry` 无从启动）。
    """
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool=target_tool, target_action=target_action,
        params={"__absent__": 1},
    ))
    assert result.success is False, (
        f"{target_tool}.{target_action} 缺必填必须失败（改前假绿）: {result.data} {result.message}")
    assert result.suggestion, f"{target_tool}.{target_action} 失败必须带 suggestion: {result}"


def test_no_rule_path_is_rejected_with_suggestion(tool, admin_ctx):
    """A4 红证（改前红）：真·无规则的 action 改前返回 `success=True + skipped=True`。

    改后：`success=True` **只允许**表示“真跑了校验并通过” —— 没跑就是失败 +
    suggestion（模型据此知道「别把它当校验通过」，且 `base_skill` 不会据此落
    `pending_validated_input` 执行授权）。
    """
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool="inventory_manage", target_action="low_stock_alert",
        params={"threshold": 10},
    ))
    assert result.data is None or result.data.get("skipped") is not True, \
        f"不得返回 skipped 假绿: {result.data}"
    assert result.success is False, (
        f"未跑校验却报 success=True（模型据此继续执行）: {result.data} {result.message}")
    assert result.suggestion, f"fail-closed 分支必须带 suggestion: {result}"


@pytest.mark.parametrize("target_tool,target_action,params", _NEVER_VALIDATED)
def test_never_validated_paths_are_not_false_green(tool, admin_ctx, target_tool,
                                                  target_action, params):
    """A4 「并非所有操作都有规则」的诚实信号：只读/全可选参数的工具也不得报“校验通过”。

    判据 = `success=True` 只允许出现在**真跑了校验**（`data.validated=True` 且无 skipped）；
    `success=False` 必须带 suggestion（否则模型只看到“失败”不知下一步）。
    """
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool=target_tool, target_action=target_action,
        params=params,
    ))
    data = result.data or {}
    ran = result.success is True and data.get("validated") is True \
        and data.get("skipped") is not True
    assert result.success is False or ran, (
        f"{target_tool}.{target_action} 报成功却没真跑校验（假绿）: {result.data} {result.message}")
    if result.success is False:
        assert result.suggestion, f"{target_tool}.{target_action} 失败必须带 suggestion: {result}"


def test_unknown_tool_still_rejected(tool, admin_ctx):
    """既有行为不变（负例）：未知工具仍是失败（且带可行动 suggestion）。"""
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool="unknown_tool", target_action="whatever",
        params={"foo": "bar"},
    ))
    assert result.success is False
    assert result.suggestion


# ── 负例（R2）：已注册写工具的真参数校验改后仍必须通过 ──

@pytest.mark.parametrize("target_tool,target_action,params", [
    ("order_create", "create", {
        "customer_name": "张三", "customer_phone": "13800138000",
        "items": [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                   "subtotal": 504.0}]}),
    ("product_manage", "toggle_status", {"product_id": "p1", "status": "off_sale"}),
    ("customer_manage", "add_tag", {"customer_id": "c1", "tag_id": "t1"}),
    ("employee_manage", "toggle_status", {"user_id": "u1", "status": "disabled"}),
    ("processing_item_manage", "toggle_item_status",
     {"item_id": "i1", "status": "inactive"}),
    ("category_manage", "create", {"name": "窗帘"}),
])
def test_negative_legal_write_params_still_validate(tool, admin_ctx, target_tool,
                                                    target_action, params):
    """负例 ④：补齐规则后，合法写参数仍返回 success + validated=True（不打断既有流程）。"""
    result = asyncio.run(tool.execute(
        context=admin_ctx, target_tool=target_tool, target_action=target_action,
        params=params,
    ))
    assert result.success is True, f"{target_tool}.{target_action} 合法参数被拦: {result.message}"
    assert result.data.get("validated") is True
    assert result.data.get("skipped") is not True