"""商品库「单价接地」判据（零 LLM 纯函数）—— **中性层**（issue #4057 S7）。

## 为什么单独成模块（不是放在 skill 层）

这三个函数是**下单单价 vs 商品库价**的确定性判据，**两侧都在用**：

    skill 层（`app/graph/skills/execution/react_turn.py` → `base_skill` 的再导出）
        会话接地快照（`grounded_product_detail`）到手时先判一次；
    工具层（`app/tools/order_create.py`）
        执行前按商品库复核（fail-closed 兜底，不依赖会话状态）。

改前函数定义在 `app/graph/skills/base_skill.py`（skill 层私有符号），工具层用
**函数级反向 import** `from app.graph.skills.base_skill import …` 去取 ⇒ 分层倒置：
叶子模块（tools）依赖上层编排模块（graph.skills）的私有实现。搬到 `app/utils/` 后两边都
向下依赖同一个中性模块（`app/utils/**` 不 import 任何上层模块 ⇒ 不成环、不反向）。

## 判据/接线（回归守卫）

- `app/graph/skills/base_skill.py` **再导出**同名符号（`execution/react_turn.py` 顶层
  `from app.graph.skills.base_skill import …, unit_price_grounding_error, …` 仍可用）；
- `app/tools/order_create.py` 只 import 本模块，**不得**再出现
  `from app.graph.skills.base_skill import`；
- 守卫：`tests/test_utils_sku_price.py`（静态层间判据 + 同名符号同一对象）。

⚠️ 本模块**只被移动、未被改写**：函数体逐字来自 `base_skill.py`（issue #4057 S7 硬约束
「逐字搬迁不改算法」），故连函数内注释里的历史 issue 号一并保留。
"""

from typing import Optional

# ── 下单「单价接地」校验（issue OR-014，run 34916256903 / 判定跑 34923425338 归因）──
# 实证：B 端（mibao）下单，规格选择卡呈现「米白 ¥150/米 或 浅灰 ¥168」——商品库
# （prod_eval_blackout）单价 168.0 且 seed 里 SKU price = base_price（**无分色差价**）
# ⇒ 米白 150 是 LLM 编造的分色价；用户选「米白｜散剪｜2.8米｜¥150/米」→ order_create
# 落 unit_price=150.0 → 订单按错价成交（amount_verify[order_create] 抓「150 ≠ 168」）。
# 本函数是**产品层**确定性兜底（零 LLM）：单价必须以商品库为准 ——
#   · 库中无分色差价（SKU 同价）⇒ 任何分色价 ≠ 库价即拦截（禁止编造分色价）；
#   · SKU 有独立价 ⇒ 按所选 SKU（processing_info.colorName/skuCode）匹配判；
#   · 商品库价以 `grounded_product_detail`（本会话最近一次成功的 product_detail）为准，
#     库价变化（如改价 198）自然跟随 —— **不得写死任何具体金额**。
# ⚠️ 本函数依赖会话接地快照：C 端（customer_order）由闸门保证「未查详情不下单」，
#    而 B 端（order）未接地时快照为空 → 本函数放行（判据见函数 docstring「未接地不做
#    金额判定」）。B 端这条路径的 fail-closed 兜底在 **order_create 工具层**
#    （`_reject_unit_price_not_grounded`，判定跑 34923425338 红证）：无论接地状态如何，
#    执行前直接按商品库解析库价，不一致即拦截回填 —— 本函数与工具层是**两层防线**，
#    工具层不依赖会话状态（单测见 tests/test_order_create_tool_price_grounding.py）。
_PRICE_TOLERANCE = 0.01


def _match_sku_price(grounded: dict, item: dict) -> Optional[float]:
    """按 item 的规格信息（processing_info.colorName/skuCode）匹配 SKU 库价。

    无 SKU 匹配时返回 None（由调用方决定按商品价兜底还是放行）。"""
    if not isinstance(grounded, dict):
        return None
    skus = grounded.get("skus") or []
    if not skus:
        return None
    pinfo = item.get("processing_info") or {}
    if not isinstance(pinfo, dict):
        return None
    color = str(pinfo.get("colorName") or "").strip()
    code = str(pinfo.get("skuCode") or "").strip()
    if not color and not code:
        return None
    for sku in skus:
        if not isinstance(sku, dict):
            continue
        if code and str(sku.get("sku_code") or "") == code:
            return _to_float(sku.get("price"))
        if color and str(sku.get("color_name") or "") == color:
            return _to_float(sku.get("price"))
    return None


def _to_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _library_unit_price_grounded(grounded: dict, unit_price) -> bool:
    """`unit_price` 是否存在于商品库（商品级 price 或任一 SKU 价），容差同 `_PRICE_TOLERANCE`。

    issue #4011：改前工具层闸门在「商品有多个不同 SKU 价、item 未指定规格」时直接
    fail-closed，把「规格无从唯一确定」误判成「单价编造」，连正确库价（@168）也拒
    ⇒ OR-014 首跑 13 次 order_create 无一成功。本判据只回答「这个价是否来自商品库」：
    是 ⇒ 不是编造（规格维度交服务端 `validateAgentItemUnitPrice` 按 SKU 复核 / 人工确认）；
    否 ⇒ 编造价，照旧拦截并回填（#3875/#3879 原意图不变）。
    """
    if not isinstance(grounded, dict):
        return False
    want = _to_float(unit_price)
    if want is None:
        return False
    candidates = [_to_float(grounded.get("price"))]
    for sku in grounded.get("skus") or []:
        if isinstance(sku, dict):
            candidates.append(_to_float(sku.get("price")))
    return any(c is not None and abs(want - c) <= _PRICE_TOLERANCE for c in candidates)


def unit_price_grounding_error(items: list, grounded_detail) -> Optional[str]:
    """下单明细单价 vs 商品库价的接地校验（零 LLM 纯函数）。

    Args:
        items: order_create 的 items 列表（[{product_name, quantity, unit_price,
               processing_info:{colorName,skuCode}}]）
        grounded_detail: 本会话最近一次成功 product_detail 的接地快照
               （{product_id, name, price, skus:[{color_name, sku_code, price}]}）；
               None/{} 表示未接地（不做单价判定，防误拦）。

    Returns:
        单价与库价不一致时返回**可行动**的错误描述（含库价，供模型纠正）；
        一致 / 无法接地 / 商品不匹配 → None。

    判据（事实驱动，区分「规格维度」与「单价」）：
      · 单价来自库（商品 price 或所选 SKU 的 price）；加工费来自加工项（不入此判据）；
      · 无分色差价 ⇒ 分色价编造即拦截；有分色差价 ⇒ 按所选 SKU 判（不把规格选择弄坏）；
      · **未声明规格**的行：单价只要存在于商品库（商品 price 或任一 SKU 价）就不判死
        （issue #4011：改前按商品级价兜底会把其它 SKU 的真实价判成编造 ⇒ 死锁）；
        不在库价集合内才是编造 ⇒ 拦截并回填。
    """
    if not items or not isinstance(grounded_detail, dict):
        return None
    g_price = _to_float(grounded_detail.get("price"))
    g_name = str(grounded_detail.get("name") or "")
    g_id = str(grounded_detail.get("product_id") or "")
    if g_price is None:
        return None  # 库价未知 → 不做金额判定（宁可放行，不误伤）
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = str(item.get("product_name") or "")
        pid = str(item.get("product_id") or "")
        # 只核对**能确定是本接地商品**的行（名称或 ID 匹配）
        if pid and g_id and pid != g_id:
            continue
        if name and g_name and name != g_name:
            continue
        if not pid and not name:
            continue
        up = _to_float(item.get("unit_price"))
        if up is None:
            continue
        sku_price = _match_sku_price(grounded_detail, item)
        lib_price = sku_price if sku_price is not None else g_price
        if abs(up - lib_price) <= _PRICE_TOLERANCE:
            continue
        # 「未声明规格」的行不该被按商品级价兜底判死（issue #4011）：
        # 没有规格标识时 lib_price 退化成商品级 price，会把**确实来自商品库其它 SKU** 的价
        # （如分色价商品 米白100/香槟金130 报 130）判成“编造” —— 这正是 OR-014 首跑
        # 13 次 order_create 无一成功的死锁形态（连正确库价也被拒）。
        # 边界收紧为「该价是否存在于商品库」：存在 ⇒ 不是编造（规格维度交服务端按 SKU 复核 /
        # 人工确认）；不存在 ⇒ 编造价，照旧拦截并回填（#3875/#3879 原意图不变）。
        # ⚠️ 声明了规格却匹配不到 SKU 的行**不走**此豁免（保持既有兜底判据）。
        pinfo = item.get("processing_info")
        has_spec = isinstance(pinfo, dict) and bool(
            pinfo.get("colorName") or pinfo.get("skuCode"))
        if not has_spec and _library_unit_price_grounded(grounded_detail, up):
            continue
        color_hint = ""
        if isinstance(pinfo, dict) and str(pinfo.get("colorName") or ""):
            color_hint = f"（规格 {pinfo.get('colorName')}）"
        return (
            f"商品明细第 {i + 1} 项「{name}」单价 {up} ≠ 商品库价 {lib_price}{color_hint} —— "
            f"单价必须以商品库为准（product_detail 的 price / 所选 SKU 的 skus[].price），"
            f"**禁止编造分色/规格价**；库中无分色差价时所有颜色同价。"
            f"请把该行 unit_price 改为 {lib_price}（subtotal 同步 = 数量×单价）后重新下单。"
        )
    return None