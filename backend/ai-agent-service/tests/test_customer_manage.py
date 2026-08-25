"""customer_manage 工具 — 只读 action 确认豁免 + 契约回归测试

对应 app/tools/customer_manage.py 的 read_only_actions 声明。
回归背景：customer_manage 是 destructive 工具（含删除客户/标签），
但 list/detail/list_tags 是纯只读查询。此前被确认守卫一律拦截，
导致「查客户列表」在 E2E Real 中失败。修复后只读 action 免确认。
"""
# case_ids: DF-008
import pytest

from app.graph.skills.base_skill import _requires_confirmation
from app.tools.customer_manage import CustomerManageTool, VALID_ACTIONS


@pytest.fixture(scope="module")
def tool():
    return CustomerManageTool()


class TestCustomerManageReadOnlyActions:
    """只读 action 声明与确认守卫行为"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail", "list_tags"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查客户列表") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "customer_id": "x"}, "查客户详情") is False

    def test_list_tags_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list_tags"}, "有哪些客户标签") is False

    def test_write_actions_still_require_confirm(self, tool):
        # 写/破坏性 action 不在豁免集，仍需用户确认
        assert _requires_confirmation(tool, {"action": "update"}, "帮我改客户信息") is True
        assert _requires_confirmation(tool, {"action": "add_tag"}, "给客户打标签") is True
        assert _requires_confirmation(tool, {"action": "delete_tag"}, "删除标签") is True

    def test_write_actions_pass_with_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "update"}, "确认更新") is False
        assert _requires_confirmation(tool, {"action": "delete_tag"}, "确认删除") is False
