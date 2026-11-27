# case_ids: HR-009,HR-010
"""`employee_manage(action=create)` 的**两层拒绝**必须可区分（issue #9220 —— HR-009 的假绿根因）。

## 病灶（逐字）

`HR-009` 与 `HR-010` 的输入同为「帮我开个客服账号」（不带岗位码）⇒ 模型自选 `role: agent`。
本用例的身份**只有** `employee:list`（`debug_permissions`）⇒ 同一个 `create` 有两种拒绝：

| 拒绝层 | 触发条件 | 码 | 是否触达服务端 |
|---|---|---|---|
| **工具层**（`app/tools/base.py::permission_denied`） | 缺 `employee:create` | `PERMISSION_DENIED` | **否**（零 HTTP） |
| **服务层**（`UserService.assertAssignableRoleAndPermissions`） | `role` ∈ `FORBIDDEN_USER_ROLES` | `VALIDATION_ERROR`（422） | 是 |

`HR-009` 的 `must_fail` 若只写「create 一次都不得成功」，**两种拒绝同形** ⇒ 用例要钉的
「缺权限被拒」可能**整条没被执行**却仍然判绿（身份一旦回落通配 `*`，走的正是第二条）。

## 本文件锁什么（零 LLM、确定性；三条各带内容级断言）

1. 缺 `employee:create` ⇒ **工具层**拒绝：`error_code == "PERMISSION_DENIED"`、消息点名缺的权限码、
   且 **`client.post` 零调用**（服务端的保留角色校验**根本没被触达**）⇒ 两层**可区分**，
   故 HR-009 的断言可以（也应该）收严成具名码，而不是登记「不可区分」。
2. 持 `employee:create` + `role=agent` ⇒ **服务层** 422：`error_code == "VALIDATION_ERROR"`、
   消息含「系统保留角色」、请求体 `role` 逐字是 `agent`（证明它真的走到了服务端）。
3. `role=customer_service`（可分配岗位）⇒ **成功**，且下发的 `role` 逐字是 `customer_service`
   （HR-010 的正向对照前提：岗位码值级不断链）。

## 红证（本单实测）

把第 1 条的 `permissions` 换成 `["employee:create"]` ⇒ `error_code` 变 `VALIDATION_ERROR` 且
`client.post` 被调用一次 ⇒ 断言 1 具名红（两侧差异就是「拒绝理由」本身，不是措辞）。
把 `role` 换回不存在的岗位码 ⇒ 第 2/3 条的请求体值级断言红。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.employee_manage import EmployeeManageTool

CREATE_PAYLOAD = {
    "name": "李四",
    "phone": "13800009999",
    "password": "Test123456",
}

RESERVED_ROLE_REJECTION = {
    "success": False,
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "角色 agent 为系统保留角色，禁止在员工管理中分配",
    },
}


def _admin_context(permissions):
    """评测身份（`role=admin` + `X-Debug-Permissions` 受限码），与 HR-009/HR-010 的服务端口径同源。"""
    return ToolContext(
        tenant_id=1, user_id="eval_hr009", session_id="sess_hr009",
        role="admin", permissions=list(permissions),
    )


def _client(post_response):
    client = AsyncMock()
    client.post = AsyncMock(return_value=post_response)
    return client


class TestTwoLayerDenialIsDistinguishable:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_missing_create_permission_is_denied_at_the_tool_layer(self, mock_get_client):
        """HR-009 的身份：缺 `employee:create` ⇒ 工具层具名 `PERMISSION_DENIED`，**零 HTTP**。"""
        client = _client(RESERVED_ROLE_REJECTION)
        mock_get_client.return_value = client

        result = await EmployeeManageTool().execute(
            context=_admin_context(["employee:list"]),
            action="create", role="agent", **CREATE_PAYLOAD,
        )

        assert result.success is False
        assert result.error_code == "PERMISSION_DENIED"
        assert result.error_code != "VALIDATION_ERROR"
        assert "缺少权限：employee:create" in result.message
        # 承重的一条：服务端（保留角色校验所在的那一层）**根本没被调用**
        assert client.post.await_count == 0

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_create_holder_reaches_reserved_role_validation_with_its_own_code(self, mock_get_client):
        """持 `employee:create` + 保留角色 ⇒ **服务层** 422，码是 `VALIDATION_ERROR`（另一种拒绝）。"""
        client = _client(RESERVED_ROLE_REJECTION)
        mock_get_client.return_value = client

        result = await EmployeeManageTool().execute(
            context=_admin_context(["employee:create"]),
            action="create", role="agent", **CREATE_PAYLOAD,
        )

        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"
        assert result.error_code != "PERMISSION_DENIED"
        assert "系统保留角色" in result.error
        assert client.post.await_count == 1
        assert client.post.call_args.kwargs["json_data"]["role"] == "agent"
        assert client.post.call_args.args[0] == "/api/admin/users"

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_assignable_role_code_is_passed_through_and_succeeds(self, mock_get_client):
        """HR-010 的正向对照前提：可分配岗位码（`customer_service`）原样下发 ⇒ 成功。"""
        client = _client({"success": True, "data": {"id": 9}})
        mock_get_client.return_value = client

        result = await EmployeeManageTool().execute(
            context=_admin_context(["employee:create"]),
            action="create", role="customer_service", **CREATE_PAYLOAD,
        )

        assert result.success is True
        assert result.error_code is None
        assert client.post.call_args.kwargs["json_data"] == {
            **CREATE_PAYLOAD, "role": "customer_service",
        }
