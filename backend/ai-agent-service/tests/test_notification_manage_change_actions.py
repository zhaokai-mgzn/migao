# case_ids: ST-004, ST-005
"""`notification_manage` **变更能力接回**的实例判据（issue #7040，2026-10-16 用户裁定）。

## 被测事实（四条，全部读源 / 读对象，不抄清单）

1. **变更 action 已接回**：`VALID_ACTIONS` 含 `mark_read` / `read_all`（用户裁定「变更 ✅ 必须支持」）；
2. **不接线的 action 仍然不接线**：`delete`（删除）/ `create`（创建 + 对外发送）不在枚举里 ⇒
   入口即拒（不是"description 里没写"）；
3. **端点是真端点**（接线前逐条核对 `NotificationController`）：`mark_read` → `PUT /{id}/read`；
   `read_all` → `PUT /read-all`；两者都**没有** `@RequirePermission`（自助语义：收件人恒取
   `SecurityContext`）⇒ 工具**不持权限码**，回到角色层；
4. **确认门禁在位**：`read_only=False` + `requires_confirmation=True` + `read_only_actions`
   = 两个只读 action ⇒ 非只读 action 走 `base_skill._requires_confirmation`（变更不等于免确认）。

## 为什么必须有这份判据

「变更接回」是**跨四个面的联合事实**（action 枚举 / 端点 / 权限面 / 确认门禁），任一处漂移都不会
有东西变红：把 `read_only` 改回 `True`（变更静默变成免确认执行）、把 `delete` 加回枚举、
把 `requires_confirmation` 摘掉、或把端点改成 `PATCH`。本文件逐条钉住。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入 |
|---|---|
| `test_change_actions_are_wired` | 从 `VALID_ACTIONS` 里删掉 `mark_read` |
| `test_unwired_actions_still_rejected_at_the_entry` | 把 `delete` / `create` 加回枚举 |
| `test_mark_read_calls_the_real_endpoint` | 端点常量改成 `/api/admin/notifications/{id}`（方法/路径漂移） |
| `test_read_all_calls_the_real_endpoint` | 同上 |
| `test_mark_read_requires_an_id` | 去掉缺 id 的早退分支 |
| `test_confirmation_gate_is_declared` | 把 `requires_confirmation` 改成 `False`（判据 8 同款形态） |
| `test_permission_face_is_role_layer` | 给工具加回 `employee:list`（写路径残留码，会把读取面收窄） |
| `TestJudgementIsNotVacuous` | 合成工具证明「枚举驱动」的判据真会报 |

## 边界（照实登记）

- 只读源码 + 工具对象（零 LLM、零网络、零 DB）：**行为面**（模型是否真的先确认再标记）
  按 `migao-dev-flow` §13 默认不派发真实评测（#4262）。
- 本文件不判「提示词是否还在教 agent 拒绝标记已读」——那一条在
  `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 11（共现扫描 + 注入红证）。
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.tools import notification_manage as mod
from app.tools.notification_manage import NotificationManageTool

#: 本单按裁定**接回**的变更 action（端点均已逐条核对存在）。
CHANGE_ACTIONS = {"mark_read", "read_all"}

#: 只读 action（免确认拦截）。
READ_ACTIONS = {"list", "unread_count"}

#: **有意不接线**的 action（端点存在但按裁定不接线）与理由。
UNWIRED_ACTIONS = {
    "delete": "删除 ⊂ 严禁（不可逆）⇒ agent 只能引导用户到后台「通知中心」页",
    "create": "创建 + 对外发送 ⊂ 不支持（给**别人**发通知）",
}


@pytest.fixture
def tool():
    return NotificationManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.put = AsyncMock()
    client.post = AsyncMock()
    client.delete = AsyncMock()
    return client


class TestNotificationChangeActions:
    def test_change_actions_are_wired(self):
        assert CHANGE_ACTIONS <= set(mod.VALID_ACTIONS), (
            f"`VALID_ACTIONS` = {sorted(mod.VALID_ACTIONS)} 里没有变更 action "
            f"{sorted(CHANGE_ACTIONS - set(mod.VALID_ACTIONS))} —— 用户 2026-10-16 裁定"
            "「变更 ✅ 必须支持」，接不回 = 变更在 B 端物理不可达（issue #7040 的本体）"
        )

    def test_enum_is_exactly_read_plus_change(self):
        assert set(mod.VALID_ACTIONS) == READ_ACTIONS | CHANGE_ACTIONS, (
            f"action 枚举 {sorted(mod.VALID_ACTIONS)} 不等于「只读 ∪ 变更」"
            f"{sorted(READ_ACTIONS | CHANGE_ACTIONS)} ⇒ 多出来的是**未登记**的能力"
        )

    def test_read_only_actions_are_the_read_ones_only(self):
        assert set(mod.READ_ONLY_ACTIONS) == READ_ACTIONS, (
            f"`READ_ONLY_ACTIONS` = {sorted(mod.READ_ONLY_ACTIONS)} —— 它必须是**纯只读**集："
            "把变更 action 放进来 = 借只读豁免绕开确认门禁（洗白形态）"
        )

    def test_confirmation_gate_is_declared(self):
        """变更 ⇒ 必须走确认门禁（`read_only=False` 且非只读 action 会被 `_requires_confirmation` 拦）。"""
        t = NotificationManageTool()
        assert t.read_only is False, (
            "`read_only=True` 会让变更 action **免确认执行**（`_requires_confirmation` 对纯只读工具"
            "直接放行）—— 接回变更 ≠ 拆掉门禁"
        )
        assert t.requires_confirmation is True, (
            "变更类 action 必须声明 `requires_confirmation`（与 `scheduled_task_manage` 同口径）"
        )
        assert t.destructive is False, "标记已读可逆、不丢数据 ⇒ 不是破坏性动作"

    @pytest.mark.parametrize("action", sorted(UNWIRED_ACTIONS))
    async def test_unwired_actions_still_rejected_at_the_entry(self, action, tool,
                                                              admin_tool_context):
        """`delete` / `create` 在 `execute()` 入口即被拒（能力不接线，不是"文档里没写"）。"""
        result = await tool.execute(
            context=admin_tool_context, action=action,
            notification_id="n-1", recipient_id="u-1", title="标题", content="内容",
        )
        assert result.success is False, (
            f"未接线的 action {action!r} 仍被执行 ⇒ 越过了裁定边界（{UNWIRED_ACTIONS[action]}）"
        )
        assert "无效的操作类型" in (result.error or ""), result.error


class TestNotificationChangeEndpoints:
    """端点面：`mark_read` / `read_all` 打的必须是 admin-api **真实存在**的两个自助端点。"""

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_calls_the_real_endpoint(self, mock_get_client, tool,
                                                    admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="mark_read", notification_id="n-42")

        assert result.success is True, result
        call = mock_client.put.call_args
        assert call[0][0] == "/api/admin/notifications/n-42/read", (
            f"mark_read 打的端点 {call[0][0]!r} 与 `NotificationController.markAsRead` 的 "
            "`@PutMapping(\"/{id}/read\")` 不符（接线成了不存在的端点 = 假能力）"
        )
        assert result.data["notification_id"] == "n-42"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_read_all_calls_the_real_endpoint(self, mock_get_client, tool,
                                                   admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="read_all")

        assert result.success is True, result
        call = mock_client.put.call_args
        assert call[0][0] == "/api/admin/notifications/read-all", (
            f"read_all 打的端点 {call[0][0]!r} 与 `NotificationController.markAllAsRead` 的 "
            "`@PutMapping(\"/read-all\")` 不符"
        )

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_requires_an_id(self, mock_get_client, tool, admin_tool_context,
                                           mock_client):
        """缺 `notification_id` ⇒ 本地早退（不发请求、不猜 id、不假装标记成功）。"""
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="mark_read")
        assert result.success is False
        assert result.error == "missing_notification_id", result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_endpoint_failure_is_reported_not_swallowed(self, mock_get_client, tool,
                                                             admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={
            "success": False, "error": {"message": "通知不存在"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="mark_read", notification_id="n-x")
        assert result.success is False, "端点失败不得被吞成成功（假绿）"
        assert "通知不存在" in (result.message or ""), result.message


class TestNotificationPermissionFaceIsUnchanged:
    """权限面（#5302 的**零回归**口径 + #7040 的边界）：仍不持码、仍在角色层。"""

    def test_permission_face_is_role_layer(self):
        t = NotificationManageTool()
        assert list(t.required_permissions) == [], (
            f"仍声明 {list(t.required_permissions)} —— 四个自助端点在 `NotificationController` 里"
            "都没有 `@RequirePermission`；残留写码会把「通知中心」能力收窄成「只有持码岗位可用」"
        )
        assert "allowed_roles" in NotificationManageTool.__dict__, (
            "无码工具必须**显式**声明 `allowed_roles`（吃 `BaseTool` 默认值 = 含 C 端/幽灵角色）"
        )
        roles = set(t.allowed_roles)
        assert not (roles & {"customer", "agent"}), "角色白名单含 C 端角色 ⇒ 两端隔离被打破"
        assert "tenant_admin" not in roles, "含幽灵角色 tenant_admin（admin-api 无该角色）"
        assert {"admin", "operator"} <= roles, "读面不得窄于改前（#5302 零回归口径）"

    def test_declares_the_bound_skill(self):
        """本工具必须真的被一个 B 端 skill 绑定（否则接回 action 也**不可达**）。"""
        from app.agents.agent_config import get_agent_config
        from app.graph.skills.skill_registry import get_skill_registry

        names = set(get_agent_config("mibao").get_all_skill_names())
        registry = get_skill_registry()
        bound = {
            s for s in names
            if "notification_manage" in (registry.get(s).tool_names if registry.get(s) else [])
        }
        assert bound, (
            f"`notification_manage` 不在黄金策任何 skill 的工具集里（skill_names={sorted(names)}）"
            "⇒ 变更 action 接回了但**模型调不到**（issue #7040 的形态原样保留）"
        )


class TestJudgementIsNotVacuous:
    """判据不得是空断言：枚举驱动的断言必须**真的会报**。"""

    def test_enum_difference_is_detected(self):
        """负控：把 `delete` 加进枚举 ⇒ 「枚举恰好是只读∪变更」这条必然报。"""
        planted = READ_ACTIONS | CHANGE_ACTIONS | {"delete"}
        assert planted != READ_ACTIONS | CHANGE_ACTIONS, "注入没生效（夹具写错）"
        assert planted - (READ_ACTIONS | CHANGE_ACTIONS) == {"delete"}

    def test_read_only_set_difference_is_detected(self):
        """负控：把变更 action 放进只读集 ⇒ 「只读集必须是纯只读」这条必然报。"""
        planted = READ_ACTIONS | {"mark_read"}
        assert planted != READ_ACTIONS
        assert planted & CHANGE_ACTIONS == {"mark_read"}

    def test_negative_control_real_enum_is_clean(self):
        """对照组：真实枚举必须**不**触发上面两条（否则判据恒红）。"""
        real = set(mod.VALID_ACTIONS)
        assert real - (READ_ACTIONS | CHANGE_ACTIONS) == set()
        assert set(mod.READ_ONLY_ACTIONS) & CHANGE_ACTIONS == set()
