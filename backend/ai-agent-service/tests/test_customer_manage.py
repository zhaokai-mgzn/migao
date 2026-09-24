"""CustomerManageTool 单元测试 — 客户档案 + 标签库查询（只读）。

B 端只读化（issue #5247）：customer_manage（客户档案 / 标签库） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
覆盖 list 脱敏/分页、detail 参数校验、标签库查询，
以及 destructive 工具只读 action 的确认豁免（DF-008）。
"""
# case_ids: DF-008, CU-001, CU-002, CU-003, CU-004, CU-008
import ast
import re
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills.base_skill import _requires_confirmation
from app.briefing.customer_profile import MAX_VIEW_ROWS
from app.tools import customer_manage as TOOL_MODULE
from app.tools.customer_manage import (
    CRAFT_MODES,
    PROFILE_VIEW_ENDPOINT,
    CustomerManageTool,
    VALID_ACTIONS,
)
# 声明与快照形态**同一个夹具来源**（不复制一份：字段名只在 #5362 的声明里写死一次）
from tests.test_briefing_customer_profile import declaration_from_java, leg_snapshot, sample_row

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTROLLER_JAVA = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller"
                   / "CustomerController.java")


def _method_string_literals(module_file, method_name: str) -> set:
    """某个方法体里出现的字符串字面量（AST 取值 ⇒ 注释里的举例不算）。"""
    tree = ast.parse(Path(module_file).read_text(encoding="utf8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            return {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    raise AssertionError(f"找不到方法 {method_name}（改名 ⇒ 判据失配 ⇒ 红，不静默跳过）")


@pytest.fixture
def tool():
    return CustomerManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


class TestCustomerReadOnlyConfirmation:
    """destructive 工具只读 action 的确认豁免（DF-008）"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail", "list_tags", "profile_view"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查客户列表") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "customer_id": "x"}, "查客户详情") is False

    def test_list_tags_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list_tags"}, "有哪些客户标签") is False

    # [RETIRED #5247] test_write_actions_still_require_confirm 已退休：客户写 action（update/add_tag/remove_tag）已从 B 端移除（B 端只读化）：写 action 不再存在，确认拦截断言无对象。


class TestCustomerPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="merge")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestCustomerList:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_defaults_and_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            page="2",
            size="5",
            keyword="张三",
            source_channel="wechat",
            vip_level="gold",
        )

        assert result.success is True
        assert result.data["customers"] == []
        assert result.data["total"] == 0
        assert result.data["page"] == 2
        assert result.data["size"] == 5

        call_kwargs = mock_client.get.call_args[1]
        params = call_kwargs["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["keyword"] == "张三"
        assert params["sourceChannel"] == "wechat"
        assert params["vipLevel"] == "gold"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_phone_masking(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "c1", "name": "张三", "phone": "13800138000", "sourceChannel": "wechat", "vipLevel": "gold"},
                    {"id": "c2", "name": "李四", "phone": "1234", "sourceChannel": None, "vipLevel": None},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        customers = result.data["customers"]
        # len>=11 → 前3+****+后4；否则原样
        assert customers[0]["phone"] == "138****8000"
        assert customers[1]["phone"] == "1234"
        assert "找到 2 个客户" in result.message

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_name_fallback_wechat_nickname(self, mock_get_client, tool, admin_tool_context, mock_client):
        """生产回归：admin-api 客户列表无 name 字段（返回 wechatNickname），
        米宝曾显示"姓名字段都为空"。必须回退到 wechatNickname/nickname。"""
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "c1", "phone": "13800138000", "wechatNickname": "张三"},
                    {"id": "c2", "phone": "13900000000", "name": "李四"},
                    {"id": "c3", "phone": "13700000000", "nickname": "王五"},
                ],
                "total": 3,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        customers = result.data["customers"]
        assert customers[0]["name"] == "张三"
        assert customers[1]["name"] == "李四"
        assert customers[2]["name"] == "王五"

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_empty_message(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        assert "未找到符合条件的客户" in result.message

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "服务不可用"


class TestCustomerDetail:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少客户 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        payload = {"id": "c1", "name": "张三", "profile": {}, "tags": [], "orders": [], "sessions": []}
        mock_client.get = AsyncMock(return_value={"success": True, "data": payload})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", customer_id="c1")
        assert result.success is True
        assert result.data == payload
        assert mock_client.get.call_args[0][0] == "/api/admin/customers/c1"


# [RETIRED #5247] TestCustomerUpdate（7 例） 已退休：客户档案 update（改资料/工艺画像/收货信息）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestCustomerTags（4 例） 已退休：客户标签增删（add_tag/remove_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


class TestCustomerTagLibrary:
    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_list_tags(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "t1", "name": "VIP"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_tags")
        assert result.success is True
        assert result.data["count"] == 1
        assert mock_client.get.call_args[0][0] == "/api/admin/customer-tags"

    # [RETIRED #5247] test_create_tag_missing_name 已退休：标签库建标签（create_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


class TestCustomerProfileView:
    """具名跨域视图 `customer_profile` 的**按需**消费入口（族 3 · 包 3，issue #5456）。

    视图语义的完整判据在 `tests/test_briefing_customer_profile.py`；本类只钉**工具面**三件事：
    ① 只读豁免与 action 白名单；② 端点字面量**三处同源**（调用点 == 模块常量 ==
    `CustomerController` 的 `@GetMapping`）；③ 披露纪律 —— 消息是模型的**唯一**输入源，
    无真值字段必须逐条点名并说清「未知 ≠ 0」（不说这句，模型会把 `null` 讲成「消费 0 元」）。
    """

    def test_action_is_read_only_and_confirm_exempt(self, tool):
        assert "profile_view" in VALID_ACTIONS
        assert "profile_view" in tool.read_only_actions
        assert _requires_confirmation(tool, {"action": "profile_view"}, "看一下客户画像") is False

    def test_endpoint_literal_is_pinned_three_ways(self):
        """契约里的技术字面量不许凭语义推测（§17.3）：调用点字面量 == 模块常量 == 控制器的映射"""
        literals = _method_string_literals(TOOL_MODULE.__file__, "_profile_view")
        mappings = set(re.findall(r'@GetMapping\("([^"]+)"\)',
                                  CONTROLLER_JAVA.read_text(encoding="utf8")))

        assert PROFILE_VIEW_ENDPOINT in literals, (
            "端点必须以**字面量**出现在调用点（静态归属机具只认调用点的字面量；写成模块常量会让本工具"
            "被判成「无 admin-api 调用点」）")
        assert PROFILE_VIEW_ENDPOINT in mappings, "该端点必须真的挂在 CustomerController 上"
        assert PROFILE_VIEW_ENDPOINT == "/api/admin/customers/profile-view"

    def test_permission_code_is_the_customer_page_code(self, tool):
        """与客户列表/详情同码（`customer:view`）⇒ 客户 PII 不越过客户页面的权限面（issue #5246）"""
        assert tool.required_permissions == ["customer:view"]

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_profile_view_discloses_unknown_is_not_zero(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """🔴 无真值字段逐条点名 + 明说「不是 0」—— 输入侧还带着 DB 默认值 0（不得放行）"""
        truth = declaration_from_java()
        snapshot = leg_snapshot(truth=truth, rows=[sample_row(truth, tag="a", leaked=0)])
        mock_client.get = AsyncMock(return_value={"success": True, "data": snapshot})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="profile_view")

        assert result.success is True
        assert mock_client.get.call_args[0][0] == PROFILE_VIEW_ENDPOINT
        assert mock_client.get.call_args[1]["params"] == {"limit": MAX_VIEW_ROWS}
        no_truth = result.data["no_truth_fields"]
        assert no_truth, "声明表里应当有无真值字段（否则本判据空跑）"
        missing = [name for name in no_truth if name not in result.message]
        assert missing == [], f"这些无真值字段没在消息里点名：{missing}"
        assert "不是 0" in result.message, "必须说清「未知」不是 0 —— 否则模型会讲成「消费 0 元」"
        assert {row[name] for row in result.data["rows"] for name in no_truth} == {None}, (
            "DB 默认值 0 不得出现在无真值字段上")

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_profile_view_discloses_missing_declaration(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        """快照没带 #5362 的声明 ⇒ 如实说明「没有真值判断依据」，且不产出任何字段（fail-closed）"""
        snapshot = leg_snapshot()
        del snapshot["field_truth"]
        mock_client.get = AsyncMock(return_value={"success": True, "data": snapshot})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="profile_view")

        assert result.success is True
        assert result.data["declaration"]["status"] == "not_wired"
        assert "真值声明" in result.message, result.message
        assert result.data["count"] == 0

    @patch("app.tools.customer_manage.get_admin_api_client")
    async def test_profile_view_failure_is_attributable(
            self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="profile_view")

        assert result.success is False
        assert result.error == "服务不可用"
        assert result.suggestion, "失败必须给可行动的下一步（不许静默）"

    # [RETIRED #5247] test_create_tag_success 已退休：标签库建标签（create_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_update_tag_missing_id 已退休：标签库改标签（update_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_update_tag_no_content 已退休：标签库改标签（update_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_update_tag_success 已退休：标签库改标签（update_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_delete_tag_missing_id 已退休：标签库删标签（delete_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_delete_tag_success 已退休：标签库删标签（delete_tag）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。
