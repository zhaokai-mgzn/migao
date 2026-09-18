# case_ids: OR-029, OR-014, OR-017, AS-007, CH-010
"""issue #4013（P4 包）红证：死契约 / 文档-代码契约 / 常量单点（4 条）。

A2 `ToolResult.terminal` **死契约**：字段在 `app/tools/base.py` 声明、4 处赋值
   （`order_create` / `aftersale_create` / `human_handoff` ×2），但
   `_execute_tool_safe` 构造 `result_dict` 时**没有传递** ⇒ 消费点
   `result_dict.get("terminal")` 恒 None ⇒ `reset_domain`（全仓唯一调用点）**永不触发**
   —— "声明了字段但无人消费"的静默失效形态（R5 点名的形状）。
   判据形态（结构性，不靠抽查某个工具）：**`ToolResult` 声明字段 ⊆ `result_dict` 键**。
A9 确认词表与 prompt **矛盾**：`references/base/principles.md` 把「执行」列为确认示例，
   而代码 `_CONFIRM_EXACT` / `_CONFIRM_PREFIX` 都不含它（影响受确认门禁管辖的写工具）。
   判据形态：**md 列举的确认词 ⊆ 代码放行的确认词**（契约测试，非抽查）。
A10 `CUSTOMER_ONLY_ROLES` **两处定义**（`api/chat.py` 的 set + `tools/base.py` 的 frozenset）
   + 注释声称"chat.py 复用本常量"（假注释）⇒ 判据：**同一对象**（`is`）。
A11 加工项裸「不用」不在 `_PROC_DECLINE_MARKERS`，而 4 个 prompt 都承诺它
   ⇒ 顾客只说「不用」被判成"未拒绝"，兜底把 confirm 卡**改写成加工项卡**、重问一遍。
   判据形态：**prompt 承诺的拒绝词 ⊆ 代码拒绝词表** + 行为面（兜底不再改写）。

R2 负例（每处行为改动都配）：见各 `test_r2_negative_*` / `test_*_not_*`。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.tools.base import BaseTool, ToolContext, ToolResult

REFERENCES = Path(__file__).resolve().parents[1] / "app/graph/skills/references"


def _read_ref(rel: str) -> str:
    return (REFERENCES / rel).read_text(encoding="utf-8")


# ═══════════════════════════════════════
# A2 — ToolResult.terminal 死契约
# ═══════════════════════════════════════

class _StubWriteTool(BaseTool):
    """P4 红证用假写工具：终态语义由构造参数控制（不依赖任何真实业务工具）。"""

    name = "p4_stub_write"
    description = "P4 红证用假写工具（terminal 由构造参数控制）"
    read_only = False
    parameters = {"type": "object", "properties": {}}

    def __init__(self, terminal: bool = True):
        self._terminal = terminal
        super().__init__()

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={"ok": True}, terminal=self._terminal)


def _ctx() -> ToolContext:
    return ToolContext(tenant_id=1, user_id="u1", session_id="sess_p4", role="customer")


def _state(session_id: str = "sess_p4", **overrides) -> dict:
    state = {
        "messages": [HumanMessage(content="确认下单")],
        "tenant_id": 1,
        "user_id": "u1",
        "session_id": session_id,
        "role": "customer",
        "entities": {},
        "final_answer": "",
    }
    state.update(overrides)
    return state


class TestTerminalContract:
    """`_execute_tool_safe` 必须把 `ToolResult` 的字段原样带进 `result_dict`。"""

    async def test_terminal_true_reaches_result_dict(self):
        from app.graph.skills.base_skill import _execute_tool_safe

        _, result_dict = await _execute_tool_safe(
            _StubWriteTool(terminal=True), {}, _ctx(), _state())
        assert result_dict.get("terminal") is True, (
            "terminal 未进入 result_dict ⇒ 消费点 result_dict.get('terminal') 恒 None "
            "⇒ reset_domain 永不触发（死契约）"
        )

    async def test_terminal_defaults_false_not_missing(self):
        from app.graph.skills.base_skill import _execute_tool_safe

        _, result_dict = await _execute_tool_safe(
            _StubWriteTool(terminal=False), {}, _ctx(), _state())
        assert result_dict.get("terminal") is False, (
            "非终态工具必须显式带 terminal=False（键缺失会让消费点与'字段默认值'两个口径分叉）"
        )

    async def test_every_declared_tool_result_field_is_propagated(self):
        """机制判据：新增 `ToolResult` 字段必须同时进入 `result_dict`（防再犯同类死契约）。"""
        from app.graph.skills.base_skill import _execute_tool_safe

        declared = set(ToolResult.model_fields)
        _, result_dict = await _execute_tool_safe(
            _StubWriteTool(terminal=True), {}, _ctx(), _state())
        missing = sorted(declared - set(result_dict))
        assert not missing, f"ToolResult 声明但 _execute_tool_safe 未传递的字段：{missing}"


class TestTerminalResetsDomain:
    """消费点接线：终态写工具成功后必须 `reset_domain`（负例：非终态不重置）。"""

    def _run(self, *, terminal: bool):
        import asyncio

        from app.graph.skills.base_skill import execute_skill

        tool = _StubWriteTool(terminal=terminal)
        reset_calls = []
        mgr = MagicMock()
        mgr.reset_domain = MagicMock(
            side_effect=lambda sid, skill: reset_calls.append((sid, skill)))
        mgr.record_tool_result = MagicMock()
        mgr.save = AsyncMock()
        store = MagicMock()
        store.load = AsyncMock(return_value={})
        store.commit = AsyncMock()

        with patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
             patch("app.memory.context_manager.get_context_manager", return_value=mgr):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool.name else None
            registry.get_all_tools.return_value = [tool]
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool.name, "args": {}, "id": "p4_call_1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "已为您完成"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            asyncio.run(execute_skill(
                state=_state(),
                skill_name="customer_aftersales",
                tool_names=[tool.name],
                system_prompt="你是小布的售后客服",
            ))
        return reset_calls

    def test_terminal_true_resets_domain(self):
        assert self._run(terminal=True) == [("sess_p4", "customer_aftersales")], (
            "终态写工具成功但 reset_domain 未被调用 —— 草稿/待确认状态残留到下一轮"
        )

    def test_r2_negative_terminal_false_does_not_reset_domain(self):
        """R2 负例：非终态工具成功**不得**重置域上下文（原本合法的既有行为不得被改）。"""
        assert self._run(terminal=False) == []


# ═══════════════════════════════════════
# A9 — 确认词：prompt 与代码同口径
# ═══════════════════════════════════════

class TestConfirmVocabularyContract:
    """`principles.md` 列举的确认词必须全部能被代码门禁放行。"""

    def _listed_confirm_words(self) -> list:
        line = next(l for l in _read_ref("base/principles.md").splitlines()
                    if "用户明确表示同意" in l)
        return re.findall(r"[\"“]([^\"”]+)[\"”]", line)

    def test_prompt_confirm_words_all_accepted_by_code(self):
        from app.graph.skills.base_skill import _is_explicit_confirmation

        words = self._listed_confirm_words()
        assert words, "未从 principles.md 解析出确认词示例（契约测试失效 = 空断言）"
        rejected = [w for w in words if not _is_explicit_confirmation(w)]
        assert not rejected, (
            f"principles.md 承诺的确认词被代码门禁拒绝：{rejected} —— "
            f"prompt 说算确认、代码说不算，顾客照 prompt 回话会被拦在写操作之外"
        )

    def test_r2_negative_action_wording_is_not_confirmation(self):
        """R2 负例：夹带动作词的消息**不算**确认（`PROMPT-rules.md` 的注入防护不得被削弱）。

        选"删 md 示例"而非"给代码加『执行』"就是为守住这条：确认词只能是
        **对确认卡/对预览的答复**，不能是"直接执行"这类指令措辞。
        """
        from app.graph.skills.base_skill import _is_explicit_confirmation

        for text in ("直接执行", "立刻执行", "帮我直接执行下单", "执行创建商品"):
            assert _is_explicit_confirmation(text) is False, (
                f"注入式动作措辞被当成确认放行：{text!r}（门禁被削弱）")

    def test_r2_negative_legit_confirmation_still_accepted(self):
        """R2 负例的另一半：合法确认（含卡片回传值）仍必须放行。"""
        from app.graph.skills.base_skill import _is_card_confirm_value, _is_explicit_confirmation

        for text in ("确认", "好的", "可以", "确认无误", "ok", "是"):
            assert _is_explicit_confirmation(text) is True, text
        card_value = "确认创建商品：遮光窗帘 米白 3米 ¥474"
        assert _is_card_confirm_value(card_value, card_value) is True


# ═══════════════════════════════════════
# A10 — CUSTOMER_ONLY_ROLES 单点化
# ═══════════════════════════════════════

class TestCustomerOnlyRolesSingleSource:
    def test_single_definition_object_identity(self):
        import app.api.chat as chat
        import app.tools.base as tools_base

        assert chat.CUSTOMER_ONLY_ROLES is tools_base.CUSTOMER_ONLY_ROLES, (
            "CUSTOMER_ONLY_ROLES 仍是两处独立定义（同值不同对象）—— "
            "两份口径会各自漂移，而注释却声称 chat.py 复用 tools.base"
        )

    def test_value_unchanged(self):
        from app.tools.base import CUSTOMER_ONLY_ROLES

        assert set(CUSTOMER_ONLY_ROLES) == {"customer", "agent"}
        # frozenset：口径常量不得被就地改写
        assert isinstance(CUSTOMER_ONLY_ROLES, frozenset)

    def test_r2_negative_merchant_roles_not_folded(self):
        """R2 负例：商户员工角色（含 admin-api 自定义角色码）不得被折叠成 customer。"""
        from app.api.chat import _to_agent_role
        from app.tools.base import CUSTOMER_ONLY_ROLES

        for role in sorted(CUSTOMER_ONLY_ROLES):
            assert _to_agent_role(role) == "customer", role
        for role in ("admin", "tenant_admin", "custom_role_x"):
            assert _to_agent_role(role) == role, role


# ═══════════════════════════════════════
# A11 — 加工项裸「不用」
# ═══════════════════════════════════════

def _promised_decline_words() -> list:
    """从 prompts/*.md 里提取「用户…说"X"（/"Y"）才跳过」承诺的拒绝词。"""
    words = []
    for md in sorted((REFERENCES / "prompts").glob("*.md")):
        text = md.read_text(encoding="utf-8")
        for m in re.finditer(r"说[\"“]([^\"”]+)[\"”](?:/[\"“]([^\"”]+)[\"”])?才跳过", text):
            words.extend(g for g in m.groups() if g)
    return words


class TestProcessingDeclineVocabulary:
    def test_bare_bunot_is_decline(self):
        from app.graph.skills.base_skill import (
            _last_user_declined_processing,
            _user_already_answered_processing,
        )

        msgs = [HumanMessage(content="不用")]
        assert _last_user_declined_processing(msgs) is True, "裸「不用」未判为拒绝"
        msgs_with_catalog = [
            ToolMessage(content='{"success": true, "data": {"items": '
                                '[{"id": "pi1", "name": "打孔", "unit_price": 8.0}]}}',
                        tool_call_id="d1", name="processing_item_query"),
            HumanMessage(content="不用"),
        ]
        assert _user_already_answered_processing(msgs_with_catalog) is True

    def test_prompt_promised_decline_words_all_accepted(self):
        """机制判据：prompt 承诺的拒绝词 ⊆ 代码拒绝词表（防同类漂移再犯）。"""
        from app.graph.skills.base_skill import _PROC_DECLINE_MARKERS

        promised = _promised_decline_words()
        assert promised, "未从 prompts/*.md 解析出承诺的拒绝词（契约测试失效 = 空断言）"
        missing = sorted({w for w in promised
                          if not any(k in w for k in _PROC_DECLINE_MARKERS)})
        assert not missing, (
            f"prompt 承诺的拒绝词不在 _PROC_DECLINE_MARKERS：{missing} —— "
            f"顾客照 prompt 回话会被判成'未拒绝'，兜底把 confirm 卡改写成加工项卡重问一遍"
        )

    def test_bare_bunot_stops_confirm_card_rewrite(self):
        """行为面：顾客只说「不用」⇒ confirm 卡**不得**被改写成加工项卡（不重问）。"""
        from app.graph.skills.base_skill import _plan_processing_items_rewrite

        confirm = ({"name": "interact", "args": {}, "id": "x"},
                   '{"success": true, "data": {"component": "confirm", "fields": []}}',
                   {"success": True, "data": {"component": "confirm", "fields": []}})
        catalog = ToolMessage(
            content='{"success": true, "data": {"items": '
                    '[{"id": "pi1", "name": "打孔", "unit_price": 8.0, "unit": "米"}]}}',
            tool_call_id="d1", name="processing_item_query")
        assert _plan_processing_items_rewrite(
            [confirm], [HumanMessage(content="帮我下单"), catalog, HumanMessage(content="不用")]
        ) is None, "顾客说了「不用」仍被改写成加工项卡 = 同一件事问第二遍"

    def test_r2_negative_non_decline_still_rewrites(self):
        """R2 负例：**没有**拒绝的用户消息 ⇒ 兜底仍照常改写（扩词不得吞掉正常流程）。"""
        from app.graph.skills.base_skill import _plan_processing_items_rewrite

        confirm = ({"name": "interact", "args": {}, "id": "x"},
                   '{"success": true, "data": {"component": "confirm", "fields": []}}',
                   {"success": True, "data": {"component": "confirm", "fields": []}})
        catalog = ToolMessage(
            content='{"success": true, "data": {"items": '
                    '[{"id": "pi1", "name": "打孔", "unit_price": 8.0, "unit": "米"}]}}',
            tool_call_id="d1", name="processing_item_query")
        assert _plan_processing_items_rewrite(
            [confirm], [catalog, HumanMessage(content="确认下单")]
        ) is not None, "未拒绝的顾客被跳过询问加工项（扩词吞掉了正常流程）"

    def test_r2_negative_cancel_semantics_kept(self):
        """R2 负例：「不用了」的**取消**语义不得被本次扩词吞掉（#4013 提示的相邻语义）。"""
        from app.graph.skills.base_skill import _is_cancel_message

        assert _is_cancel_message("不用了") is True
        assert _is_cancel_message("不用") is False, (
            "裸「不用」不是放弃在办流程 —— 它是「不要加工项」的拒绝答复"
        )