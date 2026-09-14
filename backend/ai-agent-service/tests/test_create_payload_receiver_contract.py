"""
新建类写工具的 payload 键 ↔ admin-api 接收端读取点契约（建角色 / 建员工 / 建售后工单）
# case_ids: HR-005, HR-002, AS-007

① 契约层（docs/testing/interaction-verification.md「① 契约层」）：确定性、零 LLM、零网络。
方向与 `test_tool_field_name_contract.py`（DTO 字段名）一致，补的是**Map 形接收端**
（`@RequestBody Map<String, Object> body`）与 **create 侧真实 payload** 两条覆盖面。

背景（issue #3605，门禁误报复核）：跨模块 payload 契约门禁（PR #3598）的「射程外清单」
报告 `POST /api/admin/roles` 与 `POST /api/admin/users`（create 侧）**整条 payload 无人接收**。
用该门禁自带扫描器逐键复核后结论是**误报**：
- `AdminRoleController.createRole` 读 `name`/`code`/`description`/`permissionIds`（`:82-86`），
  四个键全部传给 `RoleService.createRole`（`:89`）并落库（`RoleService:445-457`）；
- `AdminUserController.createUser` 读 `phone`/`password`/`name`/`roleIds`（`:94-108`），
  `roleIds` → `getRoleById` 解析 role code + `assignRoleToUser` 写 `user_roles`（`:158-166`）。
真实缺陷只有 `after_sales_manage.py` 下发的 `"source": "agent"`：`AgentAfterSalesCreateRequest`
无该字段 → Spring 默认忽略未知属性 → 静默丢弃；且来源由服务端固化（`AfterSalesTicketService`
在 `createTicket` 内 `ticket.setSource("agent")`，两个创建入口都经过它）⇒ 客户端不该指定。

本文件做两件事：
1. **锁**（防误报再次误导 + 防真回归）：把「建角色 / 建员工 create 侧」的
   `payload 键 ⊆ 接收端读取点` 变成机器可验证的不变式；
2. **红→绿**：`after_sales_manage` create 的 payload 键 ⊆ `AgentAfterSalesCreateRequest`
   已声明字段 —— 删除 `source` 前必红，删除后绿。

解析器**复用**既有两套口径（不造第四套）：
- Java 接收类型字段：`tests/test_tool_field_name_contract.py::_receiver_fields_from_java`（#3562 口径）；
- `@RequestBody Map` handler 读取点：`tests/test_employee_field_consumption_contract.py::_read_keys/_method_body`。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

# 单一事实源复用：既有跨端契约测试的解析器（同正则 / 同口径）
from tests.test_employee_field_consumption_contract import _method_body, _read_keys
from tests.test_tool_field_name_contract import _receiver_fields_from_java

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JAVA_CONTROLLER = _REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller"
_JAVA_SERVICE = _REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service"


def _handler_body(java_file: Path, signature: str) -> str:
    """提取 Controller/Service 方法体（复用 #3550 口径的 `_method_body`）。"""
    assert java_file.is_file(), f"找不到 admin-api 源码: {java_file}"
    return _method_body(java_file.read_text(encoding="utf-8"), signature)


def _dropped_keys(payload: dict, consumed: frozenset[str] | set[str], receiver: str) -> list[str]:
    return sorted(k for k in payload if k not in consumed)


# ── 建角色（POST /api/admin/roles）——门禁误报的机器化反证 + 防回归 ────────────


async def test_role_manage_create_payload_keys_are_read_by_create_role(admin_tool_context):
    """role_manage(create) 实际下发的 4 个键，`createRole` 必须逐个读取（issue #3605）。

    修复前（门禁误报）：报告称整条 payload 无人接收；实测接收端 4 个键全读。
    """
    from app.tools.role_manage import RoleManageTool

    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "role-new"}})

    with patch("app.tools.role_manage.get_admin_api_client", return_value=client):
        result = await RoleManageTool().execute(
            context=admin_tool_context,
            action="create",
            name="库管",
            code="stock_keeper",
            description="负责商品管理",
            permission_ids=["perm-1", "perm-2"],
        )

    assert result.success is True, f"{result.error} / {result.message}"
    assert client.post.call_args.args[0] == "/api/admin/roles"

    payload = client.post.call_args.kwargs["json_data"]
    # payload 必须四个键都在（少一个 = 建角色信息不完整，属另一类真缺陷）
    assert set(payload) == {"name", "code", "description", "permissionIds"}, payload

    consumed = _read_keys(
        _handler_body(_JAVA_CONTROLLER / "AdminRoleController.java",
                      "public ApiResponse<Role> createRole(")
    )
    dropped = _dropped_keys(payload, consumed, "AdminRoleController.createRole")
    assert not dropped, (
        f"role_manage(create) 下发 {dropped}，但 AdminRoleController.createRole 未读取 —— "
        f"Spring 对 Map body 不存在的键静默忽略 + HTTP 200『角色已创建』= 假成功。"
        f"接收端实际读取的键：{sorted(consumed)}"
    )


# ── 建员工（POST /api/admin/users，create 侧）——同族误报反证 + 防回归 ─────────


async def test_employee_manage_create_payload_keys_are_read_by_create_user(admin_tool_context):
    """employee_manage(create) 实际下发的 4 个键，`createUser` 必须逐个读取（issue #3605）。

    #3561 只补了 update 侧；本条覆盖 create 侧（同族漏网面复核结论：create 侧本就读取）。
    """
    from app.tools.employee_manage import EmployeeManageTool

    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "user-new"}})

    with patch("app.tools.employee_manage.get_admin_api_client", return_value=client):
        result = await EmployeeManageTool().execute(
            context=admin_tool_context,
            action="create",
            phone="13900000002",
            password="init-pass-123",
            name="张三",
            role_ids=["role-manager"],
        )

    assert result.success is True, f"{result.error} / {result.message}"
    assert client.post.call_args.args[0] == "/api/admin/users"

    payload = client.post.call_args.kwargs["json_data"]
    assert set(payload) == {"phone", "password", "name", "roleIds"}, payload

    consumed = _read_keys(
        _handler_body(_JAVA_CONTROLLER / "AdminUserController.java",
                      "public ApiResponse<User> createUser(")
    )
    dropped = _dropped_keys(payload, consumed, "AdminUserController.createUser")
    assert not dropped, (
        f"employee_manage(create) 下发 {dropped}，但 AdminUserController.createUser 未读取 —— "
        f"静默忽略 + HTTP 200『创建成功』= 假成功（issue #3550 同族）。"
        f"接收端实际读取的键：{sorted(consumed)}"
    )


# ── 建售后工单（POST /api/admin/agent/after-sales）——真缺陷（红→绿） ──────────


async def test_after_sales_manage_create_payload_keys_are_declared_in_agent_dto(admin_tool_context):
    """after_sales_manage(create) 下发的每个键必须在 `AgentAfterSalesCreateRequest` 中声明。

    修复前（issue #3605 真缺陷）：payload 含 `"source": "agent"`，DTO 无该字段 →
    Spring 默认 `FAIL_ON_UNKNOWN_PROPERTIES=false` → 静默丢弃、HTTP 200、工具 success=True。
    """
    from app.tools.after_sales_manage import AfterSalesManageTool

    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "t-new"}})

    with patch("app.tools.after_sales_manage.get_admin_api_client", return_value=client):
        result = await AfterSalesManageTool().execute(
            context=admin_tool_context,
            action="create",
            order_id="ORD-20250425-001",
            ticket_type="refund",
            reason="尺寸不符要求退款",
            priority="urgent",
            images=["https://example.com/evidence.jpg"],
            refund_amount=199.0,
        )

    assert result.success is True, f"{result.error} / {result.message}"
    assert client.post.call_args.args[0] == "/api/admin/agent/after-sales"

    payload = client.post.call_args.kwargs["json_data"]
    # 业务内容必须落在已声明字段上（禁止「多发一个别名字段」凑数）
    assert payload["description"] == "尺寸不符要求退款"

    declared = _receiver_fields_from_java("AgentAfterSalesCreateRequest")
    dropped = _dropped_keys(payload, declared, "AgentAfterSalesCreateRequest")
    assert not dropped, (
        f"after_sales_manage(create) 下发 {dropped}，但 AgentAfterSalesCreateRequest 未声明 —— "
        f"Spring 静默丢弃该键（HTTP 200 + 工具 success=True）。"
        f"DTO 已声明字段：{sorted(declared)}。"
        f"若该键确需客户端指定，请先在 DTO 补字段并接线落库；"
        f"若来源类信息由服务端决定，则删除该键（不得新增别名）。"
    )


def test_agent_ticket_source_is_assigned_by_server_not_client():
    """删除客户端 `source` 键是无损的：工单来源由服务端固化（issue #3605 定性 (iii)）。

    两个创建入口（表单 `createTicket` 与 Agent BFF `createTicketForAgent`）都委托到
    `AfterSalesTicketService.createTicket`，来源在该方法体内赋值 —— 因此客户端键既无效
    （DTO 无字段）又多余。本断言防止「服务端赋值被删 + 客户端键也被删」→ source 变 null。
    """
    body = _handler_body(_JAVA_SERVICE / "AfterSalesTicketService.java",
                         "public AfterSalesDetailResponse createTicket(")
    assert 'ticket.setSource("agent")' in body, (
        "AfterSalesTicketService.createTicket 不再固化 source —— 客户端已不下发该键，"
        "工单来源会变成 null（如确需客户端可指定，必须先在 AgentAfterSalesCreateRequest 补字段）"
    )

    agent_body = _handler_body(_JAVA_SERVICE / "AfterSalesTicketService.java",
                               "public AfterSalesDetailResponse createTicketForAgent(")
    assert "createTicket(" in agent_body, (
        "createTicketForAgent 不再委托 createTicket → 上述服务端固化断言对 Agent 入口失效"
    )
