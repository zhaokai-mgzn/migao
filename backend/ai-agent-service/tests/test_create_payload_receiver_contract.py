"""
新建类写工具的 payload 键 ↔ admin-api 接收端读取点契约（建角色 / 建员工 / 建售后工单）

B 端只读化（issue #5247）：role_manage / employee_manage / after_sales_manage（建角色 / 建员工 / 建售后工单） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
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

本文件原本做两件事（**第 1 条与第 2 条的 create 侧用例已随 B 端只读化退休，见文件内
[RETIRED #5247] 标记**）：
1. ~~**锁**：把「建角色 / 建员工 create 侧」的 `payload 键 ⊆ 接收端读取点` 变成不变式~~
   —— role_manage / employee_manage 的 create action 已从 B 端移除，工具不再下发 create payload；
2. ~~**红→绿**：`after_sales_manage` create 的 payload 键 ⊆ `AgentAfterSalesCreateRequest`~~
   —— 同因退休。
**仍生效**：服务端侧不变量（来源由 `AfterSalesTicketService.createTicket` 写库、不得硬编码）——
该断言的对象是 admin-api 源码，不依赖 B 端建单工具是否存在。

解析器**复用**既有两套口径（不造第四套）：
- Java 接收类型字段：`tests/test_tool_field_name_contract.py::_receiver_fields_from_java`（#3562 口径）；
- `@RequestBody Map` handler 读取点：`tests/test_employee_field_consumption_contract.py::_read_keys/_method_body`。
"""
from __future__ import annotations

from pathlib import Path

# 单一事实源复用：既有跨端契约测试的解析器（同正则 / 同口径）
# （`_read_keys` / `_receiver_fields_from_java` 的调用方是本次退休的三条 create 侧用例，
#   故不再导入；重新登记 create 侧契约时按 test_tool_field_name_contract 文件头的方式接回）
from tests.test_employee_field_consumption_contract import _method_body

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


# [RETIRED #5247] test_role_manage_create_payload_keys_are_read_by_create_role 已退休：建角色（role_manage create）已从 B 端移除（B 端只读化）：create 侧 payload 不再存在，接收端读取点断言无对象。


# ── 建员工（POST /api/admin/users，create 侧）——同族误报反证 + 防回归 ─────────


# [RETIRED #5247] test_employee_manage_create_payload_keys_are_read_by_create_user 已退休：建员工（employee_manage create）已从 B 端移除（B 端只读化）：create 侧 payload 不再存在，接收端读取点断言无对象。


# ── 建售后工单（POST /api/admin/agent/after-sales）——真缺陷（红→绿） ──────────


# [RETIRED #5247] test_after_sales_manage_create_payload_keys_are_declared_in_agent_dto 已退休：建售后工单（after_sales_manage create）已从 B 端移除（B 端只读化）：create 侧 payload 不再存在，DTO 声明断言无对象。


def test_agent_ticket_source_is_assigned_by_server_not_client():
    """客户端 `source` 键被删除是无损的：来源**始终由服务端**在 `createTicket` 内写库。

    issue #3605 定性 (iii)：客户端键既无效（DTO 无字段 → Spring 静默丢弃）又多余。
    issue #3686 更新：原断言锁的字面量 `setSource("agent")` 本身就是要修的 bug
    （无条件硬编码 ⇒ C 端顾客工单被误标 agent、DDL DEFAULT 'customer' 成死默认）；
    现在服务端按**真实来源**写值（customer/agent/merchant，由入口/请求头决定）。

    本断言的**不变量**（两条，与 #3605 的目标一致，且不再锁死具体取值）：
    1. `createTicket` 方法体内**必然**调用 `ticket.setSource(...)` —— 防止「服务端赋值被删
       + 客户端键也被删」→ source 变 null；
    2. 该赋值**不是硬编码字面量**（`setSource("agent")` 形态已复现为 bug）—— 防止回退到
       无条件硬编码。
    """
    # 定位 4 参重载（真正的建单实现体）：3 参重载只做委托，不写 source
    body = _handler_body(_JAVA_SERVICE / "AfterSalesTicketService.java",
                         "public AfterSalesDetailResponse createTicket(AfterSalesCreateRequest request, Long tenantId, String operator,")
    assert "ticket.setSource(" in body, (
        "AfterSalesTicketService.createTicket 不再写 source —— 客户端已不下发该键，"
        "工单来源会变成 null（如确需客户端可指定，必须先在 AgentAfterSalesCreateRequest 补字段）"
    )
    assert 'setSource("agent")' not in body and "setSource(SOURCE_AGENT)" not in body, (
        "AfterSalesTicketService.createTicket 又出现**无条件硬编码**来源（issue #3686 回归）："
        "C 端顾客工单会被误标 agent。来源必须按入口/声明值解析（resolveSource）。"
    )

    agent_body = _handler_body(_JAVA_SERVICE / "AfterSalesTicketService.java",
                               "public AfterSalesDetailResponse createTicketForAgent(")
    assert "createTicket(" in agent_body, (
        "createTicketForAgent 不再委托 createTicket → 上述服务端写来源断言对 Agent 入口失效"
    )
