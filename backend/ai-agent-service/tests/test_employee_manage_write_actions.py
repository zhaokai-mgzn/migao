# case_ids: MC-158
"""员工账号「创建 / 变更」接回 B 端的**实例判据**（issue #7050，2026-10-16 用户裁定「能力边界 终版」）

## 被测事实（六条，全部读源 / 读对象，不抄清单）

1. **写 action 已接回且模型看得见**：`VALID_ACTIONS` 与 schema 的 `action.enum` 同时含
   `create` / `update`，且 `execute` 的每个业务参数都在 schema 里（漏参数 ⇒ 模型无法调用）；
2. **权限走既有声明**（`required_permissions` 粗筛 + action 级复检，码取 admin-api
   `AdminUserController` 的 `@RequirePermission`）—— 不是自己判角色；
3. **确认走既有门禁**：`read_only=False` + `requires_confirmation=True` + `read_only_actions`
   = 只读 action ⇒ 写 action 由 `base_skill._requires_confirmation` 拦，且 `react_turn`
   调用的**就是同一个函数对象**（本文件按 `is` 判同源）；
4. **未确认不执行**（负控）：同一个真实门禁函数在「没确认」时返回拦截、在「点卡确认」时放行，
   两次之间**只有用户消息不同** ⇒ 写路径的网络调用只在放行后发生；
5. **端点是真的**：`create` → `POST /api/admin/users`；`update` → `PUT /api/admin/users/{id}`；
6. **零越界**：`delete` / `toggle_status` / `reset_password` 不在枚举里（入口即拒，且话术引导后台）。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入（注入即红） |
|---|---|
| `test_enum_is_exactly_read_plus_write` | 从 `VALID_ACTIONS` / enum 里删掉 `create` |
| `test_every_execute_param_is_in_the_schema` | 从 schema 里删掉 `phone` / `password` / `role_ids` |
| `test_tool_is_reachable_from_the_staff_skill` | 从 `STAFF_TOOLS` 解绑 `employee_manage`（能力物理不可达） |
| `test_read_only_permission_cannot_create` | 把 action 级复检改回单一读码（只持 `employee:list` 也能建号） |
| `test_requires_confirmation_flag_is_declared` | 把 `requires_confirmation` 改成 `False` ⇒ 写操作无门禁 |
| `test_gate_blocks_write_action_without_confirmation` | 同上（门禁摘掉后这条立刻红） |
| `test_unconfirmed_write_does_not_reach_the_endpoint` | 摘掉门禁后再跑：未确认也发出 `POST` ⇒ 红 |
| `test_create_endpoint_and_payload` | 端点改成 `PATCH` / 字段名改成 `role_ids`（服务端不认） |
| `test_validation_error_names_the_missing_field` | 去掉某个早退分支（错误退化成服务端 422 泛化文案） |
| `TestJudgementIsNotVacuous` | 合成「无门禁写工具」⇒ 门禁判据必须判它**不拦**（证明判据不恒真） |

## 边界（照实登记）

- 只读源码 + 工具对象（零 LLM / 零网络 / 零 DB）：**行为面**（模型是否真的先发确认卡）按
  `migao-dev-flow` §13 默认不派发真实评测（#4262 用户裁定「不要自动验证」）。
- 本文件不判「prompt 是否还在教 agent 拒绝建号」——那一条在
  `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 6（文案 ↔ 绑定）与
  `tests/test_prompt_snapshots.py`（prompt 快照）里。
- 岗位（角色）/ 客户 / 标签 / 分类 / 加工项五个域**本单未做**，缺口留在 issue #7050。
"""

from __future__ import annotations

import inspect

import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills import base_skill
from app.graph.skills.execution import react_turn
from app.graph.skills.staff_skill import STAFF_SKILL_CONFIG
from app.tools import employee_manage as mod
from app.tools.base import ToolContext
from app.tools.employee_manage import EmployeeManageTool
from app.tools.registry import get_tool_registry

#: 本单按裁定**接回**的写 action（端点均已逐条核对存在）。
WRITE_ACTIONS = {"create", "update"}

#: 只读 action（免确认拦截）。
READ_ACTIONS = {"list", "detail"}

#: **有意不接线**的 action 与理由（端点存在，但按 2026-10-16 终版边界不接）。
UNWIRED_ACTIONS = {
    "delete": "删除 ⊂ 严禁（不可逆）⇒ 只引导商家到后台「组织管理 → 员工管理」",
    "toggle_status": "停用/启用（离职）⊂ 严禁（不可逆）⇒ 同上",
    "reset_password": "重置密码 = 登录凭据面（安全边界）⇒ 本单不接，见 issue #7050 逐条判",
}

ADMIN = ToolContext(tenant_id=1, user_id="admin_1", session_id="s", role="admin", permissions=["*"])
LIST_ONLY = ToolContext(
    tenant_id=1, user_id="op_1", session_id="s", role="operator", permissions=["employee:list"])
WRITE_ONLY = ToolContext(
    tenant_id=1, user_id="op_2", session_id="s", role="operator", permissions=["employee:create"])
NO_PERM = ToolContext(
    tenant_id=1, user_id="viewer_1", session_id="s", role="operator", permissions=["system:view"])


@pytest.fixture
def tool():
    return EmployeeManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "u-1"}})
    client.put = AsyncMock(return_value={"success": True, "data": {"id": "u-1"}})
    client.delete = AsyncMock(return_value={"success": True, "data": {}})
    return client


def _schema(tool) -> dict:
    return tool.get_schema()["function"]["parameters"]


class TestActionSurfaceIsVisibleToTheModel:
    """判据 ①：新 action 在 registry/schema 里可见且参数完整。"""

    def test_enum_is_exactly_read_plus_write(self):
        assert set(mod.VALID_ACTIONS) == READ_ACTIONS | WRITE_ACTIONS, (
            f"`VALID_ACTIONS` = {sorted(mod.VALID_ACTIONS)} 不等于「只读 ∪ 写」"
            f"{sorted(READ_ACTIONS | WRITE_ACTIONS)} ⇒ 多出来的是**未登记**的能力 / "
            "缺的是接不回的写能力（issue #7050 的本体）"
        )

    def test_schema_enum_matches_the_action_truth(self, tool):
        enum = _schema(tool)["properties"]["action"]["enum"]
        assert set(enum) == set(mod.VALID_ACTIONS), (
            f"schema 的 action 枚举 {sorted(enum)} 与 `VALID_ACTIONS` "
            f"{sorted(mod.VALID_ACTIONS)} 不一致 ⇒ 模型看到的与实现不承认的**不是同一个集合**"
        )

    def test_registry_returns_a_write_tool(self):
        registered = get_tool_registry().get_tool("employee_manage")
        assert "employee_manage" in {t.name for t in get_tool_registry().get_all_tools()}, (
            "注册表里没有 employee_manage ⇒ 任何 skill 都调不到它")
        assert getattr(registered, "read_only", True) is False, (
            "注册表里的 employee_manage 仍是只读 ⇒ 写 action 即使存在也会被 `_requires_confirmation` "
            "跳过（只读工具永不要求确认）"
        )

    def test_tool_is_reachable_from_the_staff_skill(self):
        assert "employee_manage" in tuple(STAFF_SKILL_CONFIG.tool_names), (
            "staff skill 没有绑定 employee_manage ⇒ 工具存在但**物理不可达**"
            "（issue #7050 判据 5 的同款形态）"
        )

    def test_every_execute_param_is_in_the_schema(self, tool):
        """漏参数 ⇒ 模型无法调用（判据 ① 的另一半，机械现取）。"""
        params = inspect.signature(EmployeeManageTool.execute).parameters
        declared = set(_schema(tool)["properties"])
        missing = {
            name for name in params
            if name not in {"self", "context", "kwargs"} and name not in declared
        }
        assert not missing, (
            f"`execute` 声明了 {sorted(missing)}，但 schema 里没有这些字段 ⇒ "
            "模型无法传（或只能瞎猜），写操作会在参数校验处永远失败"
        )

    def test_required_write_fields_are_documented(self, tool):
        props = _schema(tool)["properties"]
        for field in ("name", "phone", "password", "role", "role_ids", "avatar", "user_id"):
            assert field in props, f"schema 缺字段 {field}（create/update 的必需面）"
        assert "action" in _schema(tool)["required"]


class TestPermissionUsesTheExistingDeclaration:
    """判据 ②（权限那一半）：码取 admin-api 注解，不自己判角色。"""

    def test_required_permissions_covers_both_endpoints(self):
        assert set(EmployeeManageTool.required_permissions) == {"employee:list", "employee:create"}, (
            "`required_permissions` 必须与 `AdminUserController` 的端点注解对齐："
            "类级/读端点 `employee:list`、`POST` 与 `PUT` 端点 `employee:create`"
        )

    async def test_missing_coarse_permission_is_denied(self, tool):
        result = await tool.execute(context=NO_PERM, action="list")
        assert result.success is False and "权限" in result.error

    async def test_read_only_permission_cannot_create(self, tool, mock_client):
        """只持读码的员工不得借黄金策建号（action 级复检的核心）。"""
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(
                context=LIST_ONLY, action="create",
                name="王五", phone="13812345678", password="Abc123456", role="agent",
            )
        assert result.success is False, "只持 `employee:list` 也建号成功 ⇒ 读码冒充写码"
        assert "employee:create" in result.message, (
            f"拒绝文案没具名缺哪个码（现取 message={result.message!r}）⇒ 用户不知道该开哪项权限"
        )
        mock_client.post.assert_not_awaited()

    async def test_write_permission_cannot_query(self, tool, mock_client):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=WRITE_ONLY, action="list")
        assert result.success is False and "employee:list" in result.message


class TestConfirmationGateIsTheSharedOne:
    """判据 ②（确认那一半）：走 `base_skill._requires_confirmation`，不自建第二套。"""

    def test_react_turn_calls_the_same_function_object(self):
        assert react_turn._requires_confirmation is base_skill._requires_confirmation, (
            "运行时门禁与判据引用的不是同一个函数对象 ⇒ 本文件断言的门禁可能不是真正生效的那个"
        )

    def test_tool_does_not_reimplement_the_gate(self):
        src = inspect.getsource(mod)
        assert "def _requires_confirmation" not in src and "def _is_explicit_confirmation" not in src, (
            "工具里出现自建的确认判定 ⇒ 第二套口径（本仓纪律：确认只有 base_skill 一处）"
        )

    def test_gate_declaration_is_exactly_the_read_actions(self, tool):
        assert tool.read_only is False
        assert tool.requires_confirmation is True, (
            "`requires_confirmation` 不是 True ⇒ 写 action 走不到任何代码层确认门禁"
            "（这正是本次接回最危险的形态）"
        )
        assert set(tool.read_only_actions) == READ_ACTIONS, (
            f"`read_only_actions` = {sorted(tool.read_only_actions)} ≠ 只读 action 集合 ⇒ "
            "要么查询被要求确认（体验退化），要么写操作被豁免确认（安全退化）"
        )

    @pytest.mark.parametrize("action", sorted(WRITE_ACTIONS))
    def test_gate_blocks_write_action_without_confirmation(self, tool, action):
        blocked = base_skill._requires_confirmation(tool, {"action": action}, "帮我建个客服账号")
        assert blocked is True, (
            f"{action} 在用户没确认时被放行 ⇒ 确认门禁没生效（注入式红证：把 "
            "`requires_confirmation` 改成 False，本用例立刻红）"
        )

    @pytest.mark.parametrize("action", sorted(WRITE_ACTIONS))
    def test_gate_passes_after_card_confirmation(self, tool, action):
        blocked = base_skill._requires_confirmation(tool, {"action": action}, "确认创建员工王五")
        assert blocked is False, (
            f"{action} 在用户点卡确认后仍被拦 ⇒ 写能力接回但永远办不成"
        )

    @pytest.mark.parametrize("action", sorted(READ_ACTIONS))
    def test_gate_exempts_read_actions(self, tool, action):
        blocked = base_skill._requires_confirmation(tool, {"action": action}, "查一下有哪些员工")
        assert blocked is False, f"{action} 是只读 action，不应要求确认"


class TestUnconfirmedWriteDoesNotExecute:
    """判据 ③：未确认时不执行（负控）。两次运行只差**用户消息**。"""

    async def test_unconfirmed_write_does_not_reach_the_endpoint(self, tool, mock_client):
        args = {"action": "create", "name": "王五", "phone": "13812345678",
                "password": "Abc123456", "role": "agent"}
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            outcome = await _attempt_write(tool, ADMIN, args, "新来一个客服王五，帮他开个账号")
        assert outcome["blocked"] is True, "没确认却被放行"
        assert outcome["result"] is None, "被拦截的调用仍然执行了工具"
        mock_client.post.assert_not_awaited()

    async def test_confirmed_write_does_reach_the_endpoint(self, tool, mock_client):
        args = {"action": "create", "name": "王五", "phone": "13812345678",
                "password": "Abc123456", "role": "agent"}
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            outcome = await _attempt_write(tool, ADMIN, args, "确认创建员工王五")
        assert outcome["blocked"] is False, "点卡确认后仍被拦 ⇒ 写能力办不成"
        assert outcome["result"] is not None and outcome["result"].success is True
        mock_client.post.assert_awaited_once()


class TestEndpointsAreReal:
    """判据：写端点逐字对齐 admin-api（路径 + 方法 + payload 字段名）。"""

    async def test_create_endpoint_and_payload(self, tool, mock_client):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(
                context=ADMIN, action="create", name="王五",
                phone="13812345678", password="Abc123456", role_ids=["role-1"],
            )
        assert result.success is True
        mock_client.post.assert_awaited_once()
        _, kwargs = mock_client.post.call_args
        assert mock_client.post.call_args.args[0] == "/api/admin/users", (
            "create 的端点不是 admin-api 的 `POST /api/admin/users`"
        )
        assert kwargs["json_data"] == {
            "name": "王五", "phone": "13812345678", "password": "Abc123456",
            "roleIds": ["role-1"],
        }, f"payload 字段名与 admin-api 契约不符（现取 {kwargs['json_data']}）"

    async def test_update_endpoint_and_payload(self, tool, mock_client):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", user_id="u-9", name="王五")
        assert result.success is True
        mock_client.put.assert_awaited_once()
        assert mock_client.put.call_args.args[0] == "/api/admin/users/u-9", (
            "update 的端点不是 admin-api 的 `PUT /api/admin/users/{id}`"
        )
        assert mock_client.put.call_args.kwargs["json_data"] == {"name": "王五"}

    @pytest.mark.parametrize("action", sorted(UNWIRED_ACTIONS))
    async def test_unwired_actions_are_rejected_at_the_entry(self, tool, mock_client, action):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action=action, user_id="u-9")
        assert result.success is False and "无效的操作类型" in result.error, (
            f"{action} 能被调用 ⇒ 越界（{UNWIRED_ACTIONS[action]}）"
        )
        assert "后台" in result.message, "拒绝文案没给「去哪办」⇒ 用户被卡住"
        mock_client.delete.assert_not_awaited()


class TestValidationErrorsAreNamed:
    """判据 ④：校验失败给**具名**错误（哪个字段、该填什么），且不打网络。"""

    @pytest.mark.parametrize(
        "kwargs,field,token",
        [
            ({"phone": "13812345678", "password": "A1", "role": "agent"}, "name", "姓名"),
            ({"name": "王五", "password": "A1", "role": "agent"}, "phone", "手机号"),
            ({"name": "王五", "phone": "13812345678", "role": "agent"}, "password", "初始密码"),
            ({"name": "王五", "phone": "13812345678", "password": "A1"}, "role", "岗位"),
        ],
    )
    async def test_create_error_names_the_missing_field(
        self, tool, mock_client, kwargs, field, token
    ):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="create", **kwargs)
        assert result.success is False
        assert token in result.message, (
            f"create 缺 {field} 的报错没具名（现取 message={result.message!r}）⇒ 模型只能瞎猜"
        )
        assert field in result.suggestion, (
            f"建议里没给要补的字段名 `{field}`（现取 suggestion={result.suggestion!r}）⇒ 用户不知道该做什么"
        )
        mock_client.post.assert_not_awaited()

    async def test_update_error_names_user_id(self, tool, mock_client):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", name="王五")
        assert result.success is False and "user_id" in result.suggestion
        mock_client.put.assert_not_awaited()

    async def test_update_without_changes_is_rejected(self, tool, mock_client):
        with patch("app.tools.employee_manage.get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", user_id="u-9")
        assert result.success is False and "变更内容" in result.error
        assert "name" in result.message, "没列出可改字段 ⇒ 模型不知道能改什么"
        mock_client.put.assert_not_awaited()


class TestJudgementIsNotVacuous:
    """判据 ⑤（判别力自证）：摘掉门禁 / 删掉 action ⇒ 对应判据必须红。"""

    def test_gate_assertion_notices_a_missing_declaration(self, monkeypatch, tool):
        monkeypatch.setattr(EmployeeManageTool, "requires_confirmation", False)
        blocked = base_skill._requires_confirmation(tool, {"action": "create"}, "帮我建个账号")
        assert blocked is False, (
            "把 `requires_confirmation` 摘掉后门禁仍判「拦」⇒ 上一组判据是恒真断言（空判据）"
        )

    def test_gate_assertion_notices_read_only_tool(self, monkeypatch, tool):
        monkeypatch.setattr(EmployeeManageTool, "read_only", True)
        blocked = base_skill._requires_confirmation(tool, {"action": "create"}, "帮我建个账号")
        assert blocked is False, "只读工具本应永不要求确认 —— 判据若仍判「拦」，说明它没读工具真值"

    def test_enum_assertion_notices_a_dropped_action(self):
        assert _wired_actions(mod.VALID_ACTIONS) == WRITE_ACTIONS, (
            f"接回的写 action 现取 {sorted(_wired_actions(mod.VALID_ACTIONS))} ≠ {sorted(WRITE_ACTIONS)}"
        )
        assert _wired_actions(mod.VALID_ACTIONS - {"create"}) != WRITE_ACTIONS, (
            "注入「删掉 create」后判据仍认为写面完整 ⇒ 枚举判据不具判别力（空断言）"
        )


# ── 小工具 ────────────────────────────────────────────────────────────────────

def _wired_actions(actions) -> set:
    """「写 action」= 枚举 − 只读 action（判据 ① 的**唯一**口径，注入式红证也用它）。"""
    return set(actions) - READ_ACTIONS


async def _attempt_write(tool, context, args, user_msg):
    """按运行时的**真实门禁**跑一次写调用（门禁判拦截 ⇒ 不执行工具）。

    这里的门禁判定**只来自** `base_skill._requires_confirmation`（`react_turn` 用的同一个
    函数对象，见 `test_react_turn_calls_the_same_function_object`）；两级结果同时返回，
    负控判据靠 `blocked` 与「端点是否被调用」两读数共同成立。
    """
    if base_skill._requires_confirmation(tool, args, user_msg):
        return {"blocked": True, "result": None}
    return {"blocked": False, "result": await tool.execute(context=context, **args)}
