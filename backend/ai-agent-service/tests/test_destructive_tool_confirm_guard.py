"""破坏性写操作的确认守卫 — 回归测试

修复背景：写操作 confirm 铁律此前只在 Prompt 文本层，代码层无强制。
提示注入（RAG 文档/模型幻觉）可诱导 LLM 直接调用不可逆的 destructive 工具。

修复后：destructive=True 的工具执行前，当前轮用户消息必须是明确确认，
否则拦截并引导 LLM 先展示确认卡片。核心判断抽为 _is_explicit_confirmation。
"""
# case_ids: DF-008
from app.graph.skills.base_skill import _is_explicit_confirmation, _requires_confirmation


class TestIsExplicitConfirmation:
    def test_short_confirm_word(self):
        assert _is_explicit_confirmation("确认") is True

    def test_contextual_confirm_value(self):
        # confirm 卡片回传的 confirmValue，如"确认取消订单123"
        assert _is_explicit_confirmation("确认取消订单123456") is True

    def test_confirm_yes_variant(self):
        assert _is_explicit_confirmation("好的") is True
        assert _is_explicit_confirmation("OK") is True

    def test_plain_query_is_not_confirmation(self):
        assert _is_explicit_confirmation("查一下我的订单") is False

    def test_cancel_command_is_not_confirmation(self):
        # 用户主动"帮我取消订单"是请求，不是对确认卡片的确认
        assert _is_explicit_confirmation("帮我取消所有订单") is False

    def test_empty_message_is_not_confirmation(self):
        assert _is_explicit_confirmation("") is False
        assert _is_explicit_confirmation(None) is False

    def test_long_message_with_confirm_substring_is_rejected(self):
        # 长篇消息夹带"确认"字样不应被误判为确认，避免注入/误放行
        long_msg = "这是一条很长很长的用户消息，里面提到了确认一下这个字眼，但实际上并不是用户在点击确认卡片"
        assert _is_explicit_confirmation(long_msg) is False


class TestRequiresConfirmation:
    """_requires_confirmation：destructive 工具的只读 action 免确认（本次修复）。

    回归背景：customer/employee/role/category 等 destructive 工具含删除能力，
    但 list/detail/tree 等 action 是纯只读查询。此前只要 destructive=True 就
    强制确认，导致"查客户列表"这类只读查询被 confirmation_required 拦截，
    E2E Real 持续失败。修复后：action ∈ read_only_actions 时豁免确认。
    """

    @staticmethod
    def _make_tool(destructive=True, read_only_actions=()):
        return type("FakeTool", (), {
            "destructive": destructive,
            "read_only_actions": frozenset(read_only_actions),
        })()

    def test_destructive_write_action_without_confirm(self):
        t = self._make_tool()
        assert _requires_confirmation(t, {"action": "delete"}, "帮我删除客户") is True

    def test_destructive_write_action_with_confirm(self):
        t = self._make_tool()
        assert _requires_confirmation(t, {"action": "delete"}, "确认删除") is False

    def test_destructive_read_action_is_exempt(self):
        # 核心修复行为：list/detail 只读 action 不要求确认
        t = self._make_tool(read_only_actions={"list", "detail"})
        assert _requires_confirmation(t, {"action": "list"}, "查客户列表") is False
        assert _requires_confirmation(t, {"action": "detail"}, "查客户详情") is False

    def test_destructive_action_not_in_read_only_still_requires(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"action": "update"}, "帮我改一下") is True

    def test_destructive_missing_action_requires(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {}, "查一下") is True

    def test_non_destructive_tool_never_requires(self):
        t = self._make_tool(destructive=False)
        assert _requires_confirmation(t, {"action": "delete"}, "删除") is False


class TestReadOnlyActionsContract:
    """契约：destructive 工具的 read_only_actions 必须是 VALID_ACTIONS 子集。

    防止声明笔误（如把写 action 误标为只读，导致破坏性操作被豁免确认）。
    """

    def test_read_only_actions_are_valid_actions(self):
        import importlib

        from app.tools.registry import get_tool_registry

        tools = get_tool_registry().get_all_tools()
        destructive = [t for t in tools if getattr(t, "destructive", False)]
        assert destructive, "应存在 destructive 工具"
        for tool in destructive:
            # VALID_ACTIONS 是各工具模块级常量（非类属性），从模块取
            mod = importlib.import_module(tool.__module__)
            valid = set(getattr(mod, "VALID_ACTIONS", set()))
            roa = set(getattr(tool, "read_only_actions", set()))
            assert roa <= valid, (
                f"{tool.name} read_only_actions {roa} 超出 VALID_ACTIONS {valid}"
            )
