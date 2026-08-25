"""base_skill 确认守卫 — 只读 action 豁免回归测试

对应 app/graph/skills/base_skill.py 的 _requires_confirmation。
回归背景：destructive 工具（customer/employee/role/category 等）的
list/detail/tree 纯只读 action 此前也被强制确认，导致 E2E Real
查询类用例持续失败。修复后 action ∈ read_only_actions 时豁免确认。
"""
# case_ids: DF-008
from app.graph.skills.base_skill import _requires_confirmation


class TestRequiresConfirmationReadActions:
    """destructive 工具的只读 action 免确认（核心修复行为）"""

    @staticmethod
    def _make_tool(destructive=True, read_only_actions=()):
        return type("FakeTool", (), {
            "destructive": destructive,
            "read_only_actions": frozenset(read_only_actions),
        })()

    def test_read_action_exempt_for_destructive_tool(self):
        t = self._make_tool(read_only_actions={"list", "detail", "tree"})
        assert _requires_confirmation(t, {"action": "list"}, "查客户列表") is False
        assert _requires_confirmation(t, {"action": "detail"}, "查客户详情") is False
        assert _requires_confirmation(t, {"action": "tree"}, "看看分类") is False

    def test_write_action_still_requires_without_confirm(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"action": "update"}, "帮我改一下") is True
        assert _requires_confirmation(t, {"action": "delete"}, "帮我删除") is True

    def test_write_action_passes_with_confirm(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"action": "delete"}, "确认删除") is False

    def test_non_destructive_tool_never_requires(self):
        t = self._make_tool(destructive=False)
        assert _requires_confirmation(t, {"action": "delete"}, "删除") is False

    def test_operation_param_alias_supported(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"operation": "list"}, "查一下") is False

    def test_missing_action_defaults_to_confirm_required(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {}, "查一下") is True
