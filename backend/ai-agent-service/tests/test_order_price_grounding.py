# case_ids: OR-014, OR-029
"""B 端下单「单价接地」校验 + 建品「确认-执行」收口（run 34916256903 归因）。

背景（run 34916256903，mibao 腿）：
- OR-014：规格选择卡呈现「米白 ¥150/米 或 浅灰 ¥168」，而商品库（prod_eval_blackout
  遮光窗帘）单价 168.0 且**无分色差价**（seed 里 SKU price = base_price）
  ⇒ 米白 150 是 LLM 编造的分色价；用户选「米白｜散剪｜2.8米｜¥150/米」→ order_create
  落 unit_price=150.0 → amount_verify[order_create] 报「单价 150.0 ≠ 商品库 168.0」。
- PR-016：B 端建品用户 R7 回传确认卡值，模型调 product_search 宣称「✅ 商品已创建成功！」
  而 product_manage(action=create) 从未执行（首跑指纹 no_success(product_manage)）；
  重试轮 R4/R5/R6 三张同事实 confirm 卡不收敛（确认死循环）。

既有防线只覆盖 C 端：`customer_order` 的下单接地闸门只要求「查过 product_detail」，
**不校验单价一致性**；B 端（order）连查详情的闸门都没有 ⇒ 编造的分色价一路落库。
8.4「确认-执行收口」只对 C 端（customer 角色）生效 ⇒ B 端建品确认后无任何代码兜底。

本测试钉住**产品层**的确定性修复（零 LLM）：
① 规格卡/确认/落单的单价必须来自商品库（`product_detail` 的 price 或 skus[].price）；
② 库中无分色差价时，分色价不得编造 —— 校验按**商品库唯一价**判；
③ 反向守卫：库价变了（如 198）也必须跟随，不得写死 168；
④ B 端建品确认后必须收敛 —— 要么执行写操作，要么发**不同**的卡说明缺什么；
   同一事实的 confirm 卡不得重复发（确认一次 → 执行 create）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from app.graph.skills.base_skill import (
    unit_price_grounding_error,
    _b_create_flow_confirm_eligible,
    execute_skill,
)

_UNSET = object()

# ── 商品库真值夹具（与评测 seed 同构：SKU price = base_price，无分色差价）──
_GROUNDED_NO_VARIANT = {
    "product_id": "prod_eval_blackout",
    "name": "遮光窗帘",
    "price": 168.0,
    "skus": [
        {"color_name": "米白", "sku_code": "EVAL-BLK-28-米白", "price": 168.0},
        {"color_name": "浅灰", "sku_code": "EVAL-BLK-28-浅灰", "price": 168.0},
    ],
}

_GROUNDED_VARIANT = {
    "product_id": "prod_xy",
    "name": "分色价商品",
    "price": 100.0,
    "skus": [
        {"color_name": "米白", "sku_code": "XY-01", "price": 100.0},
        {"color_name": "香槟金", "sku_code": "XY-02", "price": 130.0},
    ],
}


def _item(name, price, color=None, sku_code=None):
    pinfo = {}
    if color:
        pinfo["colorName"] = color
    if sku_code:
        pinfo["skuCode"] = sku_code
    item = {"product_name": name, "quantity": 3, "unit_price": price, "subtotal": price * 3}
    if pinfo:
        item["processing_info"] = pinfo
    return item


# ── ① 编造分色价（无分色差价时）必须被抓 ──

def test_fabricated_variant_price_rejected():
    """红证：库价 168（SKU 同价 168），agent 报「米白 150」→ 必须判错。

    改前（main 形态）：base_skill 没有这个校验函数 ⇒ 本测试 import 即失败 = 红；
    改后：150 ≠ 168 ⇒ 报「单价 ≠ 商品库价 168.0」。
    """
    err = unit_price_grounding_error(
        [_item("遮光窗帘", 150.0, color="米白")], _GROUNDED_NO_VARIANT)
    assert err, "编造的分色价（150 ≠ 库价 168）必须被抓"
    assert "168" in err, f"错误信息必须回填真实库价，供模型纠正: {err}"


def test_library_price_passes():
    """库价 168 → 放行（单价 === 库价，无拦截信息返回）。"""
    out = unit_price_grounding_error(
        [_item("遮光窗帘", 168.0, color="米白")], _GROUNDED_NO_VARIANT)
    assert not out, f"库价一致必须放行（无拦截信息）: {out}"


# ── ② 反向守卫：库价变了必须跟随（不得写死 168）──

def test_price_change_follows_library():
    """库价 198（改价后重新查详情）→ 150 拒、198 放行。"""
    grounded_198 = dict(_GROUNDED_NO_VARIANT, price=198.0)
    grounded_198["skus"] = [
        {"color_name": "米白", "sku_code": "EVAL-BLK-28-米白", "price": 198.0},
        {"color_name": "浅灰", "sku_code": "EVAL-BLK-28-浅灰", "price": 198.0},
    ]
    err = unit_price_grounding_error([_item("遮光窗帘", 150.0)], grounded_198)
    assert err, "库价 198 时 150 必须被判错（不得写死 168）"
    out2 = unit_price_grounding_error([_item("遮光窗帘", 198.0)], grounded_198)
    assert not out2, f"库价 198 时 198 必须放行（无拦截信息）: {out2}"


# ── ③ 商品确有分色/规格概念：SKU 有独立价时按所选 SKU 判 ──

def test_real_variant_price_matches_selected_sku():
    """SKU 有分色价（米白 100 / 香槟金 130）→ 按所选 SKU 判，不误伤。"""
    assert not unit_price_grounding_error(
        [_item("分色价商品", 100.0, color="米白")], _GROUNDED_VARIANT), \
        "米白 SKU 价 100 必须放行"
    assert not unit_price_grounding_error(
        [_item("分色价商品", 130.0, color="香槟金")], _GROUNDED_VARIANT), \
        "香槟金 SKU 价 130 必须放行"
    err = unit_price_grounding_error(
        [_item("分色价商品", 115.0, color="香槟金")], _GROUNDED_VARIANT)
    assert err and "130" in err, "所选 SKU 价 130，报 115 必须被抓并回填 SKU 价"


def test_variant_price_without_sku_match_falls_back_to_product_price():
    """选了库里没有的颜色（编造）→ 按商品 price 兜底判（防编造）。"""
    out = unit_price_grounding_error(
        [_item("分色价商品", 100.0, color="米黄（库里无此色）")], _GROUNDED_VARIANT)
    # 与商品 price 一致 → 放行（无 SKU 匹配时不误伤，库价=商品价）
    assert not out, f"库中无此 SKU 颜色、且单价===商品价 → 必须放行: {out}"


# ── ④ 无法接地（没查过详情/商品不匹配）→ 不误拦 ──

def test_no_grounded_detail_no_verdict():
    assert not unit_price_grounding_error([_item("别的商品", 1.0)], None), \
        "未接地（grounded 为 None）必须放行"
    assert not unit_price_grounding_error([_item("别的商品", 1.0)], {}), \
        "未接地（grounded 为空 dict）必须放行"


# ── ⑤ B 端建品「确认后必须收敛」判据（PR-016 同族根因的红证底座）──

def test_b_create_confirm_eligible_truth_table():
    """B 端建品确认收口的判据（纯函数）：pending=product_manage/create + 已确认 → 可收口。

    红证：改前 8.4 收口被 `_is_customer_role(state)` 挡住（B 端永不收口）；
    改后此判据为 True ⇒ 8.4 扩展接线后可执行 product_manage。
    反向守卫：未确认 / 无 pending / target 非建品 → False（不得把"确认后必执行"
    写死成"永不确认"）。
    """
    pending = {"target_tool": "product_manage", "target_action": "create", "params": {}}
    assert _b_create_flow_confirm_eligible(pending, confirmed=True) is True
    assert _b_create_flow_confirm_eligible(pending, confirmed=False) is False, \
        "未确认不得代执行（安全性质）"
    assert _b_create_flow_confirm_eligible(None, confirmed=True) is False, \
        "无已校验待执行写（缺关键信息）→ 不得收口"
    assert _b_create_flow_confirm_eligible(
        {"target_tool": "product_manage", "target_action": "update", "params": {}},
        confirmed=True) is False, "非 create（更新/停用等其它流程）不在此收口范围"
    # issue #3976（OR-029）：B 端 `order_create` 也纳入确认-执行收口 —— 线上实证
    # sess_202d55d49a254a10：确认卡点击后模型空头承诺「请稍候，我这就提交」、订单永不落库；
    # B 端 admin/agent 角色下单无需 sms_code（order_create.py 安全规则），收口安全性成立。
    assert _b_create_flow_confirm_eligible(
        {"target_tool": "order_create", "target_action": "create", "params": {}},
        confirmed=True) is True, "B 端 order_create 确认后必须可代码收口（issue #3976）"
    assert _b_create_flow_confirm_eligible(
        {"target_tool": "order_create", "target_action": "update", "params": {}},
        confirmed=True) is False, "order_create 非 create 流程不在收口范围"


# ── ⑥ B 端建品「确认-执行」收口接线（8.4 扩展的端到端红证）──

def _run_b_create_closure(user_msg, llm_reply, role="admin",
                          pending=_UNSET, store_extra=None, model_calls_write=False,
                          write_tool="product_manage", confirm_value=None):
    """执行 B 端建品/下单确认轮的 execute_skill（role=admin, skill=product）。

    与 C 端收口测试同构（TestConfirmClosureCodeSide._run），mock 掉
    _execute_tool_safe，记录写工具是否被代码收口执行。
    pending=_UNSET → 用默认建品 pending；pending=None → **无** pending；
    write_tool → 收口目标写工具（product_manage=建品 / order_create=下单，#3976）；
    confirm_value → 会话最近确认卡的 confirmValue（None → 建品默认卡值）。
    """
    import json as _json

    seen = {"calls": []}
    default_confirm = "确认：价格=¥100；分类=窗帘布艺；商品名称=E2E建品流程样品帘"
    full = {"last_confirm_value": confirm_value or default_confirm}
    if pending is _UNSET:
        full["pending_validated_input"] = {
            "target_tool": "product_manage", "target_action": "create",
            "params": {"name": "E2E建品流程样品帘", "price": 100.0,
                       "category_id": "cat_eval_curtain"}}
    elif pending is not None:
        full["pending_validated_input"] = pending
    full.update(store_extra or {})

    async def fake_execute(tool, a, ctx, state):
        seen["calls"].append((getattr(tool, "name", str(tool)), a))
        return (_json.dumps({"success": True, "data": {"id": "p1", "name": "E2E建品流程样品帘"},
                             "message": "商品创建成功！"}),
                {"success": True, "data": {"id": "p1", "name": "E2E建品流程样品帘"},
                 "message": "商品创建成功！"})

    class _Store:
        async def load(self, sid):
            return dict(full)

        async def commit(self, sid, f):
            full.clear(); full.update(f)

    with patch("app.memory.session_memory.SessionMemory"), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
         patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: _Store()):
        tool = MagicMock()
        tool.name = write_tool
        tool.read_only = False
        tool.destructive = True
        tool.requires_confirmation = True
        tool.parameters = {"type": "object", "properties": {"action": {"type": "string"}}}
        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        registry.get_tool.side_effect = lambda n: tool if n == write_tool else None
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        msgs = []
        if model_calls_write:
            from langchain_core.messages import AIMessage
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": write_tool, "args": {"action": "create"}, "id": "c1"}]
            msgs.append(call)
        final = MagicMock(spec=object)
        final.content = llm_reply
        final.tool_calls = []
        msgs.append(final)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=msgs)
        get_llm.return_value = llm
        state = {"session_id": "sess_b_create", "tenant_id": 1, "user_id": "u1",
                 "role": role, "messages": [HumanMessage(content=user_msg)],
                 "current_skill": "product"}
        res = asyncio.run(execute_skill(
            state=state, skill_name="product",
            tool_names=[write_tool, "interact", "validate_input"],
            system_prompt="p"))
    return res, seen, full


def test_b_create_confirmed_but_model_idles_closes_to_execute():
    """红证（接线）：B 端建品，用户已确认、模型只回话不执行 → 代码必须执行 product_manage。

    改前（main 形态）：8.4 收口被 `_is_customer_role(state)` 挡住（role=admin 非 customer）
    ⇒ product_manage 不会被代码执行（PR-016 首跑实拍：R7 确认后调 product_search 谎称成功）。
    改后：`_b_create_flow_confirm_eligible` 放行收口 ⇒ 代码执行 product_manage(action=create)。
    """
    res, seen, full = _run_b_create_closure(
        "确认：价格=¥100；分类=窗帘布艺；商品名称=E2E建品流程样品帘",
        "好的，商品已创建成功！")
    assert any(
        c[0] == "product_manage" and c[1].get("action") == "create"
        for c in seen["calls"]
    ), f"用户已确认但模型不执行 → 代码必须收口执行 product_manage（PR-016 根因）; calls={seen['calls']}"


def test_b_create_not_confirmed_no_closure():
    """反向守卫：用户**未确认**（继续补充信息/提新需求）→ 不得代执行写操作。"""
    _res, seen, _full = _run_b_create_closure(
        "颜色米白色，货号 TEST-002",  # 补充信息，非确认
        "好的，已记下颜色和货号")
    assert seen["calls"] == [], f"未确认不得执行 product_manage（安全性质）: {seen['calls']}"


def test_b_create_no_pending_no_closure():
    """反向守卫：没有已校验待执行写（缺关键信息）→ 不收口，模型可发（不同）卡。"""
    _res, seen, _full = _run_b_create_closure(
        "确认创建",
        "好的，正在为您创建",
        pending=None)
    assert seen["calls"] == [], f"无 pending（validate_input 未通过/缺失）不得收口: {seen['calls']}"


def test_b_create_model_already_wrote_no_double_execution():
    """反向守卫：模型本轮自己已调 product_manage → 代码不得重复执行（防双写）。"""
    _res, seen, _full = _run_b_create_closure(
        "确认：价格=¥100；分类=窗帘布艺；商品名称=E2E建品流程样品帘",
        "好的",
        model_calls_write=True)
    # 模型已写 1 次成功（pending 随成功清除）→ 收口不得追加第 2 次
    assert len(seen["calls"]) == 1, \
        f"模型已调写工具 → 代码不得重复执行（应恰 1 次，不得 2 次）: {seen['calls']}"


def test_b_order_confirmed_but_model_idles_closes_to_execute():
    """红证（接线，issue #3976 / OR-029）：B 端**下单**，用户已确认、模型只回话不执行
    → 代码必须收口执行 order_create。

    线上实证（sess_202d55d49a254a10）：product skill 内确认卡点击后，模型空头承诺
    「已转到订单流程为您落单…请稍候，我这就提交」而 order_create 从未执行（先被
    tool_not_found 拦、随后 relock 兜底但模型不再动手）→ orders 表无新单。
    8.4 收口扩展覆盖 B 端 order_create（admin 角色无需 sms_code，安全性成立）后，
    即使模型不动手，代码也会真实落单。
    """
    pending = {
        "target_tool": "order_create", "target_action": "create",
        "params": {"customer_name": "张三", "customer_phone": "13800138000",
                   "items": [{"product_name": "2699系列雪尼尔窗帘面料",
                              "quantity": 10, "unit_price": 23.8, "subtotal": 238}]},
    }
    # confirmValue 逐字对齐 `.github/cases/order.yml` 的 OR-029 罐头输入（issue #4015 夹具对齐后）。
    confirm_value = (
        "确认：加工项=纳米圈打孔 ¥8/米、韩式波浪折边 ¥12/米、高温定型 ¥10/米（按 10 米计 ¥300）；"
        "商品=2699系列雪尼尔窗帘面料；客户=张三（13800138000）· 已有客户；数量=10 米；"
        "规格=2699-03暖米色 · 散剪 · 2.8米；面料单价=¥23.8/米（面料小计 ¥238）；"
        "预估合计=约 ¥538（以系统结算为准）"
    )
    _res, seen, _full = _run_b_create_closure(
        confirm_value,
        "已转到订单流程为您落单，请稍候。",
        pending=pending,
        write_tool="order_create",
        confirm_value=confirm_value)
    assert any(
        c[0] == "order_create" and c[1].get("action") == "create"
        for c in seen["calls"]
    ), f"B 端订单确认后模型不动手 → 代码必须收口执行 order_create（issue #3976）; calls={seen['calls']}"


def test_b_order_not_confirmed_no_closure():
    """反向守卫（issue #3976）：B 端下单**未确认** → 不得代执行 order_create。"""
    pending = {
        "target_tool": "order_create", "target_action": "create",
        "params": {"customer_name": "张三", "customer_phone": "13800138000",
                   "items": [{"product_name": "2699系列雪尼尔窗帘面料",
                              "quantity": 10, "unit_price": 23.8, "subtotal": 238}]},
    }
    _res, seen, _full = _run_b_create_closure(
        "改成 5 米吧",  # 变更数量，非确认
        "好的，已改为 5 米。",
        pending=pending,
        write_tool="order_create")
    assert seen["calls"] == [], f"未确认不得执行 order_create（安全性质）: {seen['calls']}"


# ── ⑦ B 端 order skill「已接地 → 单价必须来自库」接线（OR-014 形态）──

def _run_b_order_create(items, grounded):
    """执行 B 端 order skill 的 order_create 轮（role=admin, skill=order）。

    模拟 OR-014 形态：本会话**已查过** product_detail（grounded 含库价 168），
    模型落单 unit_price=150（编造的分色价）→ 单价接地校验必须拦截。
    """
    import json as _json

    seen = {"calls": []}
    full = {"grounded_product_detail": grounded}
    full["last_confirm_value"] = "确认：加工项=无；单价=¥150/米；商品=遮光窗帘"

    async def fake_execute(tool, a, ctx, state):
        seen["calls"].append((getattr(tool, "name", str(tool)), a))
        return (_json.dumps({"success": True, "data": {"id": "o1", "orderNo": "2026X"},
                             "message": "订单创建成功"}),
                {"success": True, "data": {"id": "o1", "orderNo": "2026X"},
                 "message": "订单创建成功"})

    class _Store:
        async def load(self, sid):
            return dict(full)

        async def commit(self, sid, f):
            full.clear(); full.update(f)

    with patch("app.memory.session_memory.SessionMemory"), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
         patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: _Store()):
        tool = MagicMock()
        tool.name = "order_create"
        tool.read_only = False
        tool.destructive = False
        tool.requires_confirmation = True
        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        registry.get_tool.side_effect = lambda n: tool if n == "order_create" else None
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        msgs = []
        call = MagicMock(spec=object)
        call.content = ""
        call.tool_calls = [{"name": "order_create", "args": dict(items), "id": "c1"}]
        msgs.append(call)
        final = MagicMock(spec=object)
        final.content = "✅ 订单已创建成功"
        final.tool_calls = []
        msgs.append(final)
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=msgs)
        get_llm.return_value = llm
        state = {"session_id": "sess_b_order", "tenant_id": 1, "user_id": "u1",
                 "role": "admin", "messages": [HumanMessage(content="确认下单")],
                 "current_skill": "order"}
        res = asyncio.run(execute_skill(
            state=state, skill_name="order",
            tool_names=["order_create"], system_prompt="p"))
    return res, seen, full


def test_b_order_fabricated_variant_price_blocked():
    """接线红证：B 端已查过详情（库价 168），落单 150 → order_create 被单价校验拦截。

    改前（main 形态）：闸门只覆盖 customer_order ⇒ B 端 order_create 不校验单价，
    150 一路落库（OR-014 实拍）；改后：拦截且回填库价。
    """
    items = {"items": [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 150.0,
                        "subtotal": 450.0,
                        "processing_info": {"colorName": "米白"}}]}
    _res, seen, _full = _run_b_order_create(items, _GROUNDED_NO_VARIANT)
    assert seen["calls"] == [], \
        f"B 端落单编造分色价（150 ≠ 库价 168）必须被拦截: {seen['calls']}"


def test_b_order_library_price_passes():
    """接线：B 端落单单价 === 库价（168）→ 放行。"""
    items = {"items": [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                        "subtotal": 504.0,
                        "processing_info": {"colorName": "米白"}}]}
    _res, seen, _full = _run_b_order_create(items, _GROUNDED_NO_VARIANT)
    assert len(seen["calls"]) == 1, f"库价 168 应放行: {seen['calls']}"
