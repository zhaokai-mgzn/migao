# case_ids: AG-011
"""定时任务（用户「预约」）工具判据 —— issue #6486 包 2。

钉的是**工具面**（服务端那半边由包 1 的 JUnit 判据钉住）：

1. **action 面是闭集**：`{create, list, cancel}` —— 多一个写 action 进来就是能力扩面（须重走 A 档裁定）；
2. **A 档声明齐全**：`read_only=False` + `requires_confirmation=True` + `idempotent=True`
   + `destructive=False`（前者是 A 档要求②，后三条是 A 档入册口径）；
3. **只有 `list` 免确认**：`read_only_actions={"list"}` —— 写 action 不得被挪进来「洗白」；
4. **角色层显式声明**：三个端点无权限码（自助语义）⇒ 工具不持码、回到角色层，
   且 `allowed_roles` **必须显式**（不吃 `BaseTool` 默认值 —— 默认值含 C 端角色与幽灵角色）；
5. **三件套 fail-closed 在**本地**就拦**：缺 `criterion` / `action_label` / `action_url` /
   `fire_at` / `task_type` 任一 ⇒ 返回 `missing_arguments`，**在发 HTTP 之前**就返回
   （本组用例不 mock HTTP —— 一旦实现把校验挪到调用之后，用例会因真发请求而失败）。
"""

import pytest

from app.tools.base import ToolContext
from app.tools.scheduled_task_manage import (
    READ_ONLY_ACTIONS,
    VALID_ACTIONS,
    ScheduledTaskManageTool,
)


def _ctx(role: str = "admin", permissions=None) -> ToolContext:
    return ToolContext(
        tenant_id=20,
        user_id="u-1",
        session_id="sess-6486",
        role=role,
        permissions=permissions if permissions is not None else ["*"],
    )


def _valid_create_kwargs() -> dict:
    return {
        "action": "create",
        "fire_at": "2026-10-10T09:00:00+08:00",
        "task_type": "follow_up",
        "criterion": "你说过：等王总回复后再跟进张先生",
        "action_label": "去跟进张先生",
        "action_url": "/customers?keyword=张先生",
    }


class TestDeclaration:
    """① 声明面（判据：A 档四条 + 角色层）。"""

    def test_action_surface_is_closed(self):
        assert VALID_ACTIONS == {"create", "list", "cancel"}

    def test_parameters_enum_matches_valid_actions(self):
        enum = ScheduledTaskManageTool.parameters["properties"]["action"]["enum"]
        assert set(enum) == VALID_ACTIONS
        assert ScheduledTaskManageTool.parameters["required"] == ["action"]

    def test_a_tier_flags(self):
        tool = ScheduledTaskManageTool()
        assert tool.read_only is False, "A 档可逆写：read_only 必须是 False"
        assert tool.requires_confirmation is True, "A 档要求②：写操作必须有确认门禁"
        assert tool.destructive is False
        assert tool.idempotent is True, "A 档口径：幂等 ⇒ 重放安全（服务端 dedup_key）"

    def test_only_list_is_read_only_action(self):
        assert READ_ONLY_ACTIONS == {"list"}
        assert set(ScheduledTaskManageTool.read_only_actions) == {"list"}

    def test_allowed_roles_are_explicit_and_b_side_only(self):
        # 自助语义 ⇒ 不持权限码、回到角色层；必须显式声明，且不得含 C 端 / 幽灵角色
        assert ScheduledTaskManageTool.allowed_roles == ["admin", "operator"]
        for ghost in ("customer", "agent", "tenant_admin", "worker", "guest"):
            assert ghost not in ScheduledTaskManageTool.allowed_roles

    def test_trio_fields_are_declared(self):
        props = ScheduledTaskManageTool.parameters["properties"]
        for field in ("fire_at", "task_type", "criterion", "action_label", "action_url"):
            assert field in props, f"三件套相关字段 `{field}` 必须在 parameters 里声明"


class TestFailClosed:
    """② 本地 fail-closed（不 mock HTTP：一旦校验被挪到调用之后，本组会因真发请求而失败）。"""

    @pytest.mark.asyncio
    async def test_unknown_action_rejected(self):
        result = await ScheduledTaskManageTool().execute(_ctx(), action="update")
        assert result.success is False
        assert "update" in (result.error or "")

    @pytest.mark.asyncio
    async def test_permission_denied_for_unlisted_role(self):
        result = await ScheduledTaskManageTool().execute(_ctx(role="guest"), action="list")
        assert result.success is False
        assert "权限" in (result.message or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "missing",
        ["fire_at", "task_type", "criterion", "action_label", "action_url"],
    )
    async def test_missing_field_rejected_before_http(self, missing):
        kwargs = _valid_create_kwargs()
        kwargs.pop(missing)
        result = await ScheduledTaskManageTool().execute(_ctx(), **kwargs)
        assert result.success is False
        assert result.error == "missing_arguments", (
            f"缺 `{missing}` 必须在**本地**就被拒（在发 HTTP 之前）——"
            f" 实测 error={result.error!r}"
        )
        assert missing in (result.message or "")

    @pytest.mark.asyncio
    async def test_blank_string_counts_as_missing(self):
        kwargs = _valid_create_kwargs()
        kwargs["criterion"] = "   "
        result = await ScheduledTaskManageTool().execute(_ctx(), **kwargs)
        assert result.success is False
        assert result.error == "missing_arguments"

    @pytest.mark.asyncio
    async def test_cancel_without_task_id_rejected(self):
        result = await ScheduledTaskManageTool().execute(_ctx(), action="cancel")
        assert result.success is False
        assert result.error == "missing_arguments"
        assert "task_id" in (result.message or "")
