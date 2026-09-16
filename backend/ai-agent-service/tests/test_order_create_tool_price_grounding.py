# case_ids: OR-014
"""order_create 工具级「单价接地」校验（fail-closed）——判定跑 34923425338（main 7d930e34）
B 端 OR-014 仍红的 L1 红证。

背景（run 34923425338，mibao 腿，判定跑）：
- R1 product_detail(price=168.0)（库价 168，全程 payload 都是 168）；
- R2 用户明确输入「米白 | 散剪 | 门幅 2.8m | ¥168/米」，agent 却回"商品库里这个规格的
  单价是 ¥150/米"；R5 agent 再称「库价确认为 ¥150/米」；
- R7 order_create(遮光窗帘×3@150, 仅商品名、无可见 productId/SKU 标识) 成功返回订单号
  ⇒ amount_verify[order_create](R7) 报「单价 150.0 ≠ 商品库 168.0」。

为什么改前拦不住（两处 fail-open 叠加）：
- ai-agent 闸门（base_skill 下单接地闸门）：B 端（order skill）**未接地**（grounded_product_detail
  未填充）时，`unit_price_grounding_error(items, {})` 库价未知 → 放行；
- 服务端守卫（OrderService.validateAgentItemUnitPrice）：明细**只有 product_name、无
  productId + skuCode/colorName** → 解析不到唯一 SKU → fail-open 不拦截 ⇒ 150 落库。

本测试钉住**工具层**的确定性兜底（零 LLM）：order_create 执行时**无论会话接地状态如何**，
在调用服务端之前按商品库解析库价（product_id/product_name → product.price 或所选 SKU 的
skus[].price），不一致 ⇒ 拦截并回填库价；解析不到唯一商品/无库价/规格匹配不到 ⇒
配置错误级拒绝（拒绝比放行安全，但给可行动话术）。
加工项 customPrice/processingItems 属加工费，**不入** unit_price 校验域。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.base import ToolContext
from app.tools.order_create import OrderCreateTool


# ── 夹具：模拟 admin-api 商品库（product_search → product_detail）──

def _search_response(name="遮光窗帘", pid="prod_eval_blackout", found=True):
    if not found:
        return {"success": True, "data": {"items": [], "total": 0}}
    return {"success": True, "data": {
        "items": [{"id": pid, "name": name, "basePrice": 168.0}], "total": 1}}


def _detail_response(name="遮光窗帘", pid="prod_eval_blackout", price=168.0, skus=None):
    if skus is None:
        skus = [
            {"id": f"{pid}-1", "skuCode": "EVAL-BLK-28-米白", "colorName": "米白",
             "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": price,
             "stock": 500, "status": "active"},
            {"id": f"{pid}-2", "skuCode": "EVAL-BLK-28-浅灰", "colorName": "浅灰",
             "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": price,
             "stock": 500, "status": "active"},
        ]
    return {"success": True, "data": {
        "id": pid, "name": name, "price": price, "basePrice": price,
        "skus": skus, "status": "on_sale"}}


def _run_execute(items, price=168.0, name="遮光窗帘", pid="prod_eval_blackout",
                 skus=None, search_found=True, role="agent"):
    """执行 OrderCreateTool.execute（mock admin-api 商品库 + 记录 POST 是否发生）。

    Returns:
        (result, post_called: bool, sent_payload: dict|None)
    """
    client = MagicMock()

    async def fake_get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):  # product_search
            return _search_response(name=name, pid=pid, found=search_found)
        return _detail_response(name=name, pid=pid, price=price, skus=skus)

    client.get = AsyncMock(side_effect=fake_get)
    sent = {}

    async def fake_post(path, json_data=None, **kwargs):
        sent["payload"] = json_data
        return {"success": True, "data": {"id": "o1", "orderNo": "ORD-2026-0001"}}

    client.post = AsyncMock(side_effect=fake_post)

    with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
         patch("app.tools.order_create.SMS_BYPASS_CODE", "123456"):
        tool = OrderCreateTool()
        result = asyncio.run(tool.execute(
            context=ToolContext(tenant_id=1, user_id="u1", session_id="s1", role=role),
            customer_name="张三", customer_phone="13800138000", items=items,
            sms_code="123456" if role == "customer" else None,
        ))
    return result, client.post.called, sent.get("payload")


def _item(name="遮光窗帘", unit_price=150.0, quantity=3, color=None, sku_code=None):
    item = {"product_name": name, "quantity": quantity,
            "unit_price": unit_price, "subtotal": round(unit_price * quantity, 2)}
    if color or sku_code:
        pinfo = {}
        if color:
            pinfo["colorName"] = color
        if sku_code:
            pinfo["skuCode"] = sku_code
        item["processing_info"] = pinfo
    return item


# ── ① 红证：仅商品名 + 编造单价 150（库价 168）→ 必须拦截并回填，POST 不得发生 ──

def test_name_only_fabricated_price_rejected_and_backfilled():
    """改前（main 7d930e34）：工具层无此校验 ⇒ order_create 直发 POST、150 落库
    （判定跑 R7 实拍）＝ 本断言红；改后：拦截 + 回填 168，POST 不调用。

    夹具按判定跑 trace 的**精确形状**构造：仅 product_name（无 product_id、
    无 processing_info 规格标识）——这正是服务端守卫 fail-open 跳过的那条路径。
    """
    result, post_called, _sent = _run_execute([_item("遮光窗帘", 150.0)])
    assert post_called is False, \
        f"仅商品名 + 编造单价 150（库价 168）必须被工具层拦截，不得触达服务端: post={post_called}"
    assert result.success is False
    assert "unit_price" in (result.error or ""), f"错误码应可归因: {result.error}"
    assert "168" in (result.message or ""), \
        f"拦截话术必须回填真实库价 168 供模型纠正: {result.message}"


def test_name_only_fabricated_price_also_rejected_with_product_id():
    """带 product_id 但单价仍错（150 ≠ 168）→ 同样拦截（product_id 不豁免错价）。"""
    item = _item("遮光窗帘", 150.0)
    item["product_id"] = "prod_eval_blackout"
    result, post_called, _sent = _run_execute([item])
    assert post_called is False, "带 product_id 的错价单同样必须拦截"
    assert "168" in (result.message or "")


# ── ② 反向守卫：合法 B 端直接下单（未走 product_detail、用正确库价）不受影响 ──

def test_name_only_library_price_passes():
    """仅商品名 + 正确库价 168（B 端直接下单的简单场景）→ 放行，POST 发生一次。"""
    result, post_called, sent = _run_execute([_item("遮光窗帘", 168.0)])
    assert post_called is True, f"正确库价不得被误拦: {result.error} {result.message}"
    assert result.success is True
    assert sent and sent["items"][0]["unitPrice"] == 168.0, f"payload 单价必须等于库价: {sent}"


def test_name_only_library_price_passes_customer_role():
    """C 端（customer 角色）正确库价 → 同样放行（C 端既有行为不变）。"""
    result, post_called, _sent = _run_execute([_item("遮光窗帘", 168.0)], role="customer")
    assert post_called is True and result.success is True


# ── ③ 库价变化必须跟随（不得写死 168）──

def test_library_price_change_follows():
    """库价 168→198：150 拒（回填 198）、198 放行。"""
    result, post_called, _sent = _run_execute([_item("遮光窗帘", 150.0)], price=198.0)
    assert post_called is False
    assert "198" in (result.message or ""), f"必须回填新库价 198: {result.message}"

    result2, post_called2, _sent2 = _run_execute([_item("遮光窗帘", 198.0)], price=198.0)
    assert post_called2 is True and result2.success is True


# ── ④ SKU 分色价场景：按所选 SKU 判，不误伤 ──

def test_sku_variant_price_matches_selected_sku():
    """商品有分色差价（米白 100 / 香槟金 130）→ 选香槟金 130 放行、115 拒并回填 130。"""
    skus = [
        {"id": "xy-1", "skuCode": "XY-01", "colorName": "米白",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 100.0, "stock": 10},
        {"id": "xy-2", "skuCode": "XY-02", "colorName": "香槟金",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 130.0, "stock": 10},
    ]
    ok_item = _item("分色价商品", 130.0, color="香槟金")
    result, post_called, _sent = _run_execute([ok_item], price=100.0, skus=skus,
                                              name="分色价商品")
    assert post_called is True and result.success is True, \
        f"所选 SKU（香槟金 130）必须放行: {result.error} {result.message}"

    bad_item = _item("分色价商品", 115.0, color="香槟金")
    result2, post_called2, _sent2 = _run_execute([bad_item], price=100.0, skus=skus,
                                                 name="分色价商品")
    assert post_called2 is False
    assert "130" in (result2.message or ""), f"必须回填所选 SKU 价 130: {result2.message}"


def test_sku_variant_without_spec_rejected_as_config_error():
    """分色价商品但下单未指定规格（无 colorName/skuCode）→ 无法确定库价 → 配置错误级拒绝。"""
    skus = [
        {"id": "xy-1", "skuCode": "XY-01", "colorName": "米白",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 100.0, "stock": 10},
        {"id": "xy-2", "skuCode": "XY-02", "colorName": "香槟金",
         "sellingMethod": "bulk_cut", "doorWidth": "2.8", "price": 130.0, "stock": 10},
    ]
    result, post_called, _sent = _run_execute(
        [_item("分色价商品", 130.0)], price=100.0, skus=skus, name="分色价商品")
    assert post_called is False, "未指定规格的分色价商品无法核对单价 → 必须拒绝"
    assert "规格" in (result.message or ""), \
        f"话术应说明需按规格确定库价: {result.message}"


# ── ⑤ 加工项 customPrice 不属于 unit_price 校验域 ──

def test_processing_item_custom_price_out_of_scope():
    """unit_price 与库价一致（168），加工项含 customPrice → 放行（加工费不入本校验域）。"""
    item = _item("遮光窗帘", 168.0, color="米白")
    item["processing_info"] = {
        "colorName": "米白",
        "processingFee": 24.0,
        "processingItems": [
            {"id": "pi-punch", "name": "打孔（罗马圈）", "unitPrice": 8.0,
             "quantity": 3, "unit": "米", "pricingMethod": "per_meter",
             "subtotal": 24.0, "customPrice": 8.0},
        ],
    }
    result, post_called, _sent = _run_execute([item])
    assert post_called is True and result.success is True, \
        f"加工项 customPrice 不得误入 unit_price 校验域: {result.error} {result.message}"


# ── ⑥ 解析不到唯一商品 → 拒绝（比放行安全）并给可行动话术 ──

def test_product_not_found_rejected_with_actionable_message():
    """商品库中按名称搜不到该商品 → 拒绝并引导 product_search/product_detail。"""
    result, post_called, _sent = _run_execute(
        [_item("库里不存在的商品", 100.0)], search_found=False)
    assert post_called is False, "商品库查不到 → 拒绝（fail-closed）"
    assert "product_search" in (result.message or "") or "product_detail" in (result.message or ""), \
        f"话术必须给出可执行下一步: {result.message}"
