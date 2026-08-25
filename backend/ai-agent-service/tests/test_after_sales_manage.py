"""after_sales_manage 工具 — 只读 action 确认豁免 + 契约回归测试

对应 app/tools/after_sales_manage.py 的 read_only_actions 声明。
回归背景：after_sales_manage 是 destructive 工具（含关闭/拒绝工单），
但 list/detail 是纯只读查询。此前被确认守卫一律拦截导致查询失败，
修复后只读 action 免确认。
"""
# case_ids: DF-008
import pytest

from app.graph.skills.base_skill import _requires_confirmation
from app.tools.after_sales_manage import AfterSalesManageTool, VALID_ACTIONS


@pytest.fixture(scope="module")
def tool():
    return AfterSalesManageTool()


class TestAfterSalesManageReadOnlyActions:
    """只读 action 声明与确认守卫行为"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查售后工单") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "ticket_id": "x"}, "查工单详情") is False

    def test_write_actions_still_require_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "create"}, "创建工单") is True
        assert _requires_confirmation(tool, {"action": "update_status"}, "关闭工单") is True

    def test_write_actions_pass_with_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "update_status"}, "确认关闭") is False
