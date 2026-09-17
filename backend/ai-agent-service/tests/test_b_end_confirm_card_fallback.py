# case_ids: PR-007, PR-016
"""B 端写操作被确认门禁拦截后，代码兜底**补发确认卡**（issue #3882）。

背景：`base_skill.py` 8.3b 的补卡兜底（issue #3445 家族）只对
`skill_name == "customer_order"`（C 端）生效 —— 模型没发确认卡就写单被
`confirmation_required_no_card` 拦下时，C 端会在收尾把确认卡 XML 补进回复文本；
B 端 skill（product/general 等）没有这条兜底 ⇒ agent 只文本声称「确认卡已发出 👆」，
实际客户侧无卡可点、只能打字（GitHub issue #3882）。

本 PR 两处改动（TDD 红证）：
① 补卡兜底的 skill 限制放宽为**所有 skill**（C 端既有行为不回归；B 端写技能从此也有兜底）；
② `confirm_card_fields` 加**通用兜底**：订单字段提取为空时，把 args 中除控制键
   （action/operation/op/target_tool/target_action/params/component/title）之外的
   键值对转成 fields —— 否则 B 端写参数（如 product_manage.action=toggle_status、
   processing_item_manage.action=delete_item）会产出空字段 ⇒ 空卡发不出去
   （`build_confirm_interact_xml` 对空 fields 直接返回 ""，见其文档字符串）。

保持的既有约束（#3414）：**只补卡、不放行写**（写仍等顾客点卡后由门禁放行）；
本轮已由工具路径发过确认卡时**不补第二张**（`_confirm_card_seen(new_messages)`）。

测试基建沿用 `tests/test_graph_skills.py::TestConfirmationGateNoCardRepro` 的
配方（本地驱动确认门禁，零 LLM 真实调用）：mock LLM 返回「先写后文本」的回复序列，
registry 只挂真实的 B 端写工具 + interact，`_execute_tool_safe` 用假实现记录调用。
"""
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from app.api.chat import _parse_interact_xml          # noqa: E402
from app.graph.skills.base_skill import (             # noqa: E402
    _confirm_card_fields_hint,
    confirm_card_fields,
    confirm_value_for_fields,
    execute_skill,
)
from app.tools.interact import InteractTool            # noqa: E402
from app.tools.product_manage import ProductManageTool  # noqa: E402
from app.tools.processing_item_manage import ProcessingItemManageTool  # noqa: E402


def _make_state(**overrides):
    state = {
        "messages": [HumanMessage(content="测试消息")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_b3882",
        "role": "admin",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


class _Store:
    """跨 execute_skill 调用共享的 SessionStateStore 替身（模拟同一会话）。"""

    def __init__(self, shared: dict):
        self._shared = shared

    async def load(self, sid):
        return dict(self._shared)

    async def commit(self, sid, full):
        self._shared.clear()
        self._shared.update(full or {})
        return True

    async def clear(self, sid):
        return True


def _run(last_user_msg: str, *, tool_name: str = "product_manage",
         tool_args: dict | None = None, skill_name: str = "product",
         store_state: dict | None = None, model_calls_card: bool = False,
         final_text: str = "好的，我先把操作卡片发给您"):
    """驱动一次 B 端 execute_skill：模型直接调写工具（被确认门禁拦）→ 收尾文本。"""
    tool_args = dict(tool_args or {})
    executed: list = []

    async def fake_execute(tool, args, ctx, state):
        executed.append(tool.name)
        if tool.name == "interact":
            # 与真实 InteractTool 同形的返回（confirm 分支见 app/tools/interact.py）
            _fields = args.get("fields") or []
            _data = {"component": "confirm", "title": args.get("title"),
                     "fields": _fields,
                     "confirmValue": confirm_value_for_fields(_fields)}
            _payload = {"success": True, "data": _data}
            return json.dumps(_payload, ensure_ascii=False), _payload
        return (json.dumps({"success": True, "data": {}}),
                {"success": True, "data": {}})

    _shared: dict = {} if store_state is None else store_state
    store = _Store(_shared)

    history = [HumanMessage(content="把这条商品下架/加工项删掉"),
               HumanMessage(content=last_user_msg)]

    if tool_name == "product_manage":
        tool = ProductManageTool()
    else:
        tool = ProcessingItemManageTool()

    call = MagicMock(spec=AIMessage)
    call.content = ""
    call.tool_calls = [{"name": tool_name, "args": tool_args, "id": "t1"}]
    final = MagicMock(spec=AIMessage)
    final.content = final_text
    final.tool_calls = []
    # 模型被拦之后**自己调 interact(confirm) 发卡**（重复卡形态，issue #3445）
    card_call = MagicMock(spec=AIMessage)
    card_call.content = ""
    card_call.tool_calls = [{
        "name": "interact",
        "args": {"component": "confirm", "title": "请确认操作",
                 "fields": [{"label": "商品ID", "value": tool_args.get("product_id")
                             or tool_args.get("item_id") or "p1"}]},
        "id": "t2",
    }]
    _side = [call, card_call, final] if model_calls_card else [call, final]

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: store), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        # 写工具 + interact 都必须可用（interact 缺席时门禁走别的分支，与线上不符）
        registry.get_tool.side_effect = lambda n: (
            tool if n == tool_name else (InteractTool() if n == "interact" else None))
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=_side)
        get_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        out = asyncio.run(execute_skill(
            state=_make_state(messages=history),
            skill_name=skill_name,
            tool_names=[tool_name],
            system_prompt="你是米宝（B 端商品助手），写操作必须先展示确认卡并取得用户确认。",
        ))
    return out, executed


# ── ① 正向：B 端写工具被确认门禁拦下且模型没发卡 → 收尾由代码补发确认卡 ──

def test_product_manage_blocked_no_card_appends_confirm_card():
    """下架商品（product_manage toggle_status）被拦后必须补发可解析的确认卡。

    红证（改前）：B 端 skill 不在 `skill_name == "customer_order"` 白名单
    ⇒ 收尾不补卡，客户侧无卡可点（issue #3882 的缺陷形态）。
    """
    out, executed = _run(
        "把这款窗帘下架",
        tool_args={"action": "toggle_status", "product_id": "prod_a1b2c3d4",
                   "status": "off_sale"},
    )
    blob = str(out)
    assert "confirmation_required_no_card" in blob, f"门禁未按预期拦下：{blob[:300]}"
    assert "product_manage" not in executed, "被拦下的写调用不得真的执行（#3414）"

    answer = out["final_answer"]
    assert "<interact>" in answer, f"B 端被拦写操作没有补发确认卡：{answer[:200]!r}"
    payload = _parse_interact_xml(answer[answer.index("<interact>"):])
    assert payload and payload.get("component") == "confirm", (
        f"补的卡解析不出来：{payload!r}")
    fields = payload.get("fields") or []
    assert fields, "B 端写参数必须产出非空 fields —— 空卡发不出去"
    labels = [f.get("label") for f in fields]
    assert "action" not in labels, "控制键 action 不得作为卡片字段回显"
    assert payload.get("confirmValue") == confirm_value_for_fields(fields), (
        "补发卡的 confirmValue 与 interact 工具口径不一致 → 顾客点了卡也过不了门禁")


def test_processing_item_delete_blocked_appends_confirm_card():
    """删加工项（processing_item_manage delete_item）同样必须补卡。"""
    out, executed = _run(
        "把这个加工项删掉",
        tool_name="processing_item_manage",
        tool_args={"action": "delete_item", "item_id": "pi_001"},
    )
    blob = str(out)
    assert "confirmation_required_no_card" in blob, f"门禁未按预期拦下：{blob[:300]}"
    assert "processing_item_manage" not in executed
    answer = out["final_answer"]
    assert "<interact>" in answer, f"删加工项被拦后没有补发确认卡：{answer[:200]!r}"
    payload = _parse_interact_xml(answer[answer.index("<interact>"):])
    fields = payload.get("fields") or []
    assert fields, "删加工项的参数必须产出非空卡片字段"
    assert payload.get("confirmValue") == confirm_value_for_fields(fields)


def test_click_on_code_appended_card_releases_write():
    """顾客点了**代码补发的那张卡** → 写必须被放行（卡不能是死的）。

    第一轮：模型没发卡就写 → 被拦 + 代码补卡 + confirmValue 落库；
    第二轮：客户按协议回传该 confirmValue → 门禁放行、写真的执行。
    """
    tool_args = {"action": "toggle_status", "product_id": "prod_a1b2c3d4",
                 "status": "off_sale"}
    shared: dict = {}
    out1, executed1 = _run("把这款窗帘下架", tool_args=tool_args, store_state=shared)
    answer = str(out1["final_answer"])
    assert "<interact>" in answer, f"第一轮没有补卡：{answer[:200]!r}"
    payload = _parse_interact_xml(answer[answer.index("<interact>"):])
    cv = str(payload.get("confirmValue") or "")
    assert cv, "补的卡没有 confirmValue"
    assert shared.get("last_confirm_value") == cv, (
        "补发的卡没把 confirmValue 落库 —— 顾客点了也过不了门禁（卡是死的）")
    assert shared.get("last_confirm_skill") == "product", (
        f"发卡 skill 未落库：{shared.get('last_confirm_skill')!r}")
    assert "product_manage" not in executed1, "被拦的写不得执行"

    out2, executed2 = _run(cv, tool_args=tool_args, store_state=shared)
    assert "confirmation_required" not in str(out2), (
        "顾客点了代码补发的卡，门禁仍判「未确认」")
    assert "product_manage" in executed2, "点卡之后写操作没有被放行执行"


def test_no_second_card_when_model_emitted_card_via_tool():
    """模型被拦后**自己调 interact(confirm)** 发了卡 → 收尾**不得再补**一张。

    与 C 端同型（issue #3445 重复卡）：本轮 `new_messages` 里已有确认卡
    （`interact` 工具路径发射），代码兜底必须让位。
    """
    out, executed = _run(
        "把这款窗帘下架",
        tool_args={"action": "toggle_status", "product_id": "prod_a1b2c3d4",
                   "status": "off_sale"},
        model_calls_card=True,
    )
    assert "interact" in executed, (
        f"用例前提不成立：模型没有真的调到 interact 发卡（executed={executed}）")
    answer = str(out["final_answer"])
    assert "<interact>" not in answer, (
        "本轮 interact 工具已发过确认卡，收尾又追加了一张 → 客户看到两张重复卡"
        f"（issue #3445）：{answer[:300]!r}")


def test_general_agent_skill_also_gets_fallback():
    """兜底 skill（general_agent → skill_name=general）同样生效（B 端最宽兜底面）。"""
    out, executed = _run(
        "把这款窗帘下架",
        tool_args={"action": "toggle_status", "product_id": "prod_a1b2c3d4",
                   "status": "off_sale"},
        skill_name="general",
    )
    assert "confirmation_required_no_card" in str(out)
    assert "product_manage" not in executed
    assert "<interact>" in out["final_answer"], (
        f"general skill 被拦写操作没有补发确认卡：{out['final_answer'][:200]!r}")


# ── ② confirm_card_fields 通用兜底（B 端写参数 → 非空字段）──

class TestConfirmCardFieldsGenericFallback:
    def test_toggle_status_args_produce_fields(self):
        fields = confirm_card_fields(
            {"action": "toggle_status", "product_id": "prod_a1b2c3d4",
             "status": "off_sale"})
        assert fields, "B 端写参数必须产出非空卡片字段"
        labels = {f.get("label") for f in fields}
        assert "action" not in labels, "控制键 action 不得作为字段"
        # 关键键必须出现（客户需要知道「对哪个商品、改成什么状态」）
        assert any("商品" in str(l) for l in labels), f"缺商品标识：{labels}"
        assert "状态" in labels, f"缺状态字段：{labels}"
        assert confirm_value_for_fields(fields), "字段非空时 confirmValue 必须非空"

    def test_delete_item_args_produce_fields(self):
        fields = confirm_card_fields({"action": "delete_item", "item_id": "pi_001"})
        assert fields, "delete_item 参数必须产出非空字段"
        labels = {f.get("label") for f in fields}
        assert "action" not in labels
        assert any("加工项" in str(l) for l in labels), f"缺加工项标识：{labels}"

    def test_control_keys_never_become_fields(self):
        fields = confirm_card_fields({
            "action": "create", "operation": "x", "op": "y",
            "target_tool": "product_manage", "target_action": "create",
            "params": {"a": 1}, "component": "confirm", "title": "t",
            "name": "夏日清风窗帘",
        })
        labels = {f.get("label") for f in fields}
        assert "名称" in labels, "业务键必须保留（name → 名称）"
        assert not (labels & {"action", "operation", "op", "target_tool",
                              "target_action", "params", "component", "title"}), (
            f"控制键泄漏进卡片字段：{labels}")

    def test_c_end_order_args_unchanged(self):
        """C 端订单参数走既有订单字段提取，**既有标签与顺序不变**（issue #4037 校准）。

        issue #4037 / F22 起，订单类参数**额外**带上金额字段（单价/小计/合计）——
        改前投影只有 商品/数量，卡上写多少钱完全由模型自由发挥，于是
        「卡上 ¥498、落库 ¥133.80」无人发现（全系统无一处校验两者一致）。
        校准范围**仅限新增**：既有五个字段必须**逐字逐序**保留（缺任一都是回归）。
        """
        fields = confirm_card_fields({
            "items": [{"product_name": "遮光窗帘", "quantity": 3,
                       "unit_price": 168, "subtotal": 504.0}],
            "customer_name": "张三", "customer_phone": "13800138000",
            "customer_address": "浙江省杭州市",
        })
        labels = [f["label"] for f in fields]
        assert labels[:5] == ["商品", "数量", "收货人", "手机号", "地址"], (
            f"C 端既有订单字段被改动/换序（金额字段只许**追加在末尾**）：{fields}")
        assert {"单价", "小计", "合计"} <= set(labels), (
            f"F22：确认卡投影缺金额事实（卡上的钱仍然无从核对）：{fields}")

    def test_order_args_without_money_stay_money_free(self):
        """R2 负例：没有金额可算的写参数（如只传商品名）**不得**凭空造出金额字段。"""
        fields = confirm_card_fields({"items": [{"product_name": "遮光窗帘"}]})
        labels = [f["label"] for f in fields]
        assert "合计" not in labels and "单价" not in labels, (
            f"无金额可算却造出金额字段（会让顾客看到凭空的钱）：{fields}")

    def test_only_control_keys_produce_no_fields(self):
        assert confirm_card_fields({}) == []
        assert confirm_card_fields({"action": "toggle_status"}) == []

    def test_nested_values_stringified(self):
        fields = confirm_card_fields({"name": "窗帘", "colors": ["米白", "雾灰"]})
        assert fields, "非标量值也必须产出字段"
        by_label = {f["label"]: f["value"] for f in fields}
        assert "米白" in str(by_label.get("颜色") or by_label.get("colors") or ""), (
            f"数组值未正确回显：{fields}")


# ── ③ 门禁话术同步增强（_confirm_card_fields_hint 复用同一字段源）──

def test_gate_hint_includes_generic_fields_for_b_end_args():
    hint = _confirm_card_fields_hint(
        {"action": "delete_item", "item_id": "pi_001"})
    assert hint, "B 端被拦时话术必须给出卡片字段骨架"
    assert "建议卡片 fields=" in hint
    assert "pi_001" in hint, "骨架里没有被拦调用自己传过的值"
