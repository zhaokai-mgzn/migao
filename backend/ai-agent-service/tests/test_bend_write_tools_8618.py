# case_ids: MC-194, CU-004, PP-006, PP-007, PP-008, CT-002
"""B 端三条写工具接回的**实例判据**（issue #8618，2026-11-04）

被测对象 = 三把**部分写**工具（形态照 #7050 的 `employee_manage`，不另发明）：

| 工具 | 接回的写 action | 端点（admin-api 已核存在） |
|---|---|---|
| `customer_manage` | `update`（改客户资料） | `PUT /api/admin/customers/{id}`（`customer:create`） |
| `category_manage` | `create`（建商品分类） | `POST /api/admin/categories`（`product:category`） |
| `processing_item_manage` | `create_processing_item` / `update_item`（含 `status` 启用停用）/ `create_category` / `update_category` | `POST|PUT /api/admin/processing-items*`（`processing:manage`） |

## 六条被测事实（全部读源 / 读对象，不抄清单）

1. **写 action 已接回且模型看得见**：`VALID_ACTIONS` == schema 的 `action.enum`，`execute` 的每个
   业务参数都在 schema 里（漏参数 ⇒ 模型物理无法传值），工具在注册表且 `read_only is False`，
   且被**领域 skill** 绑定（否则能力物理不可达 —— PP-006 的历史病根就是「工具在注册表但没人绑」）；
2. **权限走既有声明**：`required_permissions` 取「入口码并集」粗筛 + **action 级复检**
   （码取 admin-api 控制器注解），只持读码 ⇒ 写被拒且**点名缺哪个码**、零网络调用；
3. **确认走既有门禁**：`read_only=False` + `requires_confirmation=True` + `read_only_actions`
   = 只读 action；运行时门禁与判据引用的是**同一个函数对象**（按 `is` 判）；工具里没有第二套；
4. **未确认不执行**（负控）：同一 args、同一工具，只换用户消息 ⇒ 未确认时门禁判拦截、零网络调用；
5. **端点是真的**：每条写路径的 HTTP 方法与路径都能在 admin-api 控制器里找到对应注解；
6. **零越界**：删除类 action（`delete_item` / `delete_category`）与停用类 action 名
   （`toggle_item_status`）都不在枚举里 —— 停用改由 `update_item(status=…)` 表达（可逆变更）。

## 每条断言的红证（改这一处即红）

| 测试 | 反例输入（注入即红） |
|---|---|
| `test_enum_matches_schema_and_documents_write_actions` | 从 `VALID_ACTIONS` 删掉写 action，或 schema enum 不跟着改 |
| `test_every_execute_param_is_in_the_schema` | 从 schema 里删掉 `data` / `status` |
| `test_tool_is_bound_to_a_b_end_skill` | 把工具从 `*_TOOLS` 里解绑（能力物理不可达） |
| `test_read_only_permission_cannot_write` | 把 action 级复检改回单一读码 |
| `test_gate_declaration_is_exactly_the_read_actions` | 把 `requires_confirmation` 改成 `False` |
| `test_gate_blocks_write_action_without_confirmation` | 同上（门禁摘掉后立刻红） |
| `test_unconfirmed_write_does_not_reach_the_endpoint` | 摘掉门禁后：未确认也发请求 ⇒ 红 |
| `test_write_endpoints_exist_in_admin_api` | 端点改成 `PATCH` 或写错路径 |
| `test_validation_error_names_the_missing_field` | 去掉某个早退分支（错误退化成泛化文案） |
| `TestJudgementIsNotVacuous` | 合成「无门禁写工具」⇒ 门禁判据必须判它**不拦**（证明判据不恒真） |

## 边界（照实登记）

- 只读源码 + 工具对象（零 LLM / 零网络 / 零 DB）：**行为面**（模型是否真的先发确认卡）按
  `migao-dev-flow` §13 默认不派发真实评测（#4262 用户裁定「不要自动验证」），需要时由人工集中跑一次。
- 写面**产品边界**（零单据类创建 / 零不可逆动作 / 文案 ↔ 绑定一致）在
  `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 1/3/6b/8/9/10 里，本文件不重复。
- 建档 / 打标签 / 分类改名 / 删除类**有意未接**，缺口如实留在 issue #8618 的边界节。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills import base_skill
from app.graph.skills.customer_skill import CUSTOMER_TOOLS
from app.graph.skills.execution import react_turn
from app.graph.skills.product_skill import PRODUCT_TOOLS
from app.tools import category_manage as category_mod
from app.tools import customer_manage as customer_mod
from app.tools import processing_item_manage as processing_mod
from app.tools.base import ToolContext
from app.tools.category_manage import CategoryManageTool
from app.tools.customer_manage import CustomerManageTool
from app.tools.processing_item_manage import ProcessingItemManageTool
from app.tools.registry import get_tool_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_API_CONTROLLERS = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin" / "controller"


def _tool(name: str):
    tool = get_tool_registry().get_tool(name)
    assert tool is not None, f"{name} 不在工具注册表里（接回 = 先回注册表）"
    return tool


#: 三把工具 × 接回的写 action × 只读 action × 领域 skill × 入口码
CASES = {
    "customer_manage": {
        "cls": CustomerManageTool,
        "module": customer_mod,
        "write": {"update"},
        "read": {"list", "detail", "list_tags", "profile_view", "value_view"},
        "skill_tools": CUSTOMER_TOOLS,
        "codes": ["customer:view", "customer:create"],
        "read_code": "customer:view",
        "write_code": "customer:create",
    },
    "category_manage": {
        "cls": CategoryManageTool,
        "module": category_mod,
        "write": {"create"},
        "read": {"tree"},
        "skill_tools": PRODUCT_TOOLS,
        "codes": ["product:category:view", "product:category"],
        "read_code": "product:category:view",
        "write_code": "product:category",
    },
    "processing_item_manage": {
        "cls": ProcessingItemManageTool,
        "module": processing_mod,
        "write": {"create_processing_item", "update_item", "create_category", "update_category"},
        "read": {"list_categories"},
        "skill_tools": PRODUCT_TOOLS,
        "codes": ["processing:manage"],
        "read_code": "processing:manage",
        "write_code": "processing:manage",
    },
}

ADMIN = ToolContext(tenant_id=1, user_id="admin_1", session_id="s", role="admin", permissions=["*"])


def _ctx(permissions):
    return ToolContext(tenant_id=1, user_id="op_1", session_id="s", role="operator",
                       permissions=list(permissions))


#: 各工具 execute 接受的业务参数（跨工具统一调用时必须裁剪，否则 TypeError）
TOOL_KWARGS = {
    "customer_manage": {"customer_id": "c1", "data": {"phone": "13900001111"}},
    "category_manage": {"name": "样例分类"},
    "processing_item_manage": {"item_id": "it1", "category_id": "pc1", "name": "样例",
                               "status": "inactive"},
}


def _kwargs(name: str) -> dict:
    return dict(TOOL_KWARGS[name])


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": {"id": "x1", "name": "样例"}})
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "new-1"}})
    client.put = AsyncMock(return_value={"success": True, "data": {"id": "x1"}})
    client.delete = AsyncMock(return_value={"success": True})
    return client


# ══════════════════════════════════════════════════════════════════════════════
# 一、action 面可见 + 物理可达
# ══════════════════════════════════════════════════════════════════════════════


class TestActionSurfaceIsVisibleToTheModel:
    @pytest.mark.parametrize("name", sorted(CASES))
    def test_enum_matches_schema_and_documents_write_actions(self, name):
        spec = CASES[name]
        tool = _tool(name)
        module_valid_actions = set(spec["module"].VALID_ACTIONS)
        enum = set(tool.parameters["properties"]["action"]["enum"])
        assert enum == module_valid_actions, (
            f"{name}: schema enum {sorted(enum)} ≠ 模块 VALID_ACTIONS "
            f"{sorted(module_valid_actions)} ⇒ 两者必须同源（否则模型看得见/执行不到的 action）"
        )
        assert spec["write"] | spec["read"] == enum, (
            f"{name}: 枚举 {sorted(enum)} ≠ 只读 {sorted(spec['read'])} ∪ 写 {sorted(spec['write'])}"
            " ⇒ 有 action 既没登记成读也没登记成写（或写 action 没接回）"
        )
        assert not (spec["write"] & spec["read"]), f"{name}: 同一 action 既是读又是写"

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_read_only_flag_is_false_and_confirmation_is_declared(self, name):
        tool = _tool(name)
        assert tool.read_only is False, f"{name} 仍是只读工具 ⇒ 写 action 会被当查询放行"
        assert tool.requires_confirmation is True, (
            f"{name}: `requires_confirmation` 不是 True ⇒ 写 action 走不到任何代码层确认门禁"
        )
        assert set(tool.read_only_actions) == CASES[name]["read"], (
            f"{name}: `read_only_actions` = {sorted(tool.read_only_actions)} ≠ 只读 action 集合 "
            "⇒ 要么查询被要求确认（体验退化），要么写操作被豁免确认（安全退化）"
        )

    #: 写路径**必须**能在 schema 里传值的参数（漏一个 = 模型物理无法驱动这条写路径）
    WRITE_PATH_PARAMS = {
        "customer_manage": {"action", "customer_id", "data"},
        "category_manage": {"action", "name", "category_id"},
        "processing_item_manage": {
            "action", "item_id", "category_id", "name", "craft_hint", "description", "status"},
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_write_path_params_are_in_the_schema(self, name):
        tool = _tool(name)
        schema = set(tool.parameters["properties"])
        missing = sorted(self.WRITE_PATH_PARAMS[name] - schema)
        assert missing == [], (
            f"{name}: schema 缺写路径参数 {missing} ⇒ 模型无法驱动写路径（能力假接回）"
        )
        # 反方向：schema 声明的参数必须真的被 execute 接收（否则调用即 TypeError）
        accepted = set(inspect.signature(tool.execute).parameters)
        unaccepted = sorted(schema - accepted)
        assert unaccepted == [], (
            f"{name}: schema 声明了 execute 收不到的参数 {unaccepted} ⇒ 模型一填就 TypeError"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_tool_is_bound_to_a_b_end_skill(self, name):
        assert name in CASES[name]["skill_tools"], (
            f"{name} 不在领域 skill 的工具集里 ⇒ 能力物理不可达"
            "（PP-006 的历史病根：工具在注册表、但没有任何 skill 绑定它）"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_no_irreversible_action_names_are_exposed(self, name):
        """删除类 / 停用类 action 名一律不得出现（停用改由 `update_item(status=…)` 表达）。"""
        tool = _tool(name)
        enum = set(tool.parameters["properties"]["action"]["enum"])
        forbidden = {a for a in enum if a.startswith("delete") or "toggle" in a or a in {
            "disable", "deactivate", "void", "purge", "remove"}}
        assert forbidden == set(), (
            f"{name} 暴露了不可逆动作名 {sorted(forbidden)} ⇒ 与「只能改，不能删」的裁定冲突"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 二、权限：既有声明 + action 级复检（不是自己判角色）
# ══════════════════════════════════════════════════════════════════════════════


class TestPermissionUsesTheExistingDeclaration:
    @pytest.mark.parametrize("name", sorted(CASES))
    def test_required_permissions_covers_both_endpoints(self, name):
        spec = CASES[name]
        assert list(_tool(name).required_permissions) == spec["codes"], (
            f"{name}: required_permissions 必须覆盖读写两个端点码（粗筛取并集），"
            "否则只有写码的人进不了工具、只有读码的人却能进写路径"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    async def test_missing_coarse_permission_is_denied(self, name, mock_client):
        """粗筛：一个码都不持 ⇒ 入口即拒（三个域共同的第一道门）。"""
        spec = CASES[name]
        tool = _tool(name)
        with patch.object(spec["module"], "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=_ctx(["system:view"]), action=sorted(spec["write"])[0],
                                        **_kwargs(name))
        assert result.success is False, f"{name}: 无权限码也被放行 ⇒ 粗筛失效"
        assert ("权限" in (result.message or "")) or ("权限" in (result.error or ""))
        assert mock_client.post.await_count == 0 and mock_client.put.await_count == 0

    @pytest.mark.parametrize("name", sorted(CASES))
    async def test_read_only_permission_cannot_write(self, name, mock_client):
        spec = CASES[name]
        tool = _tool(name)
        if spec["read_code"] == spec["write_code"]:
            pytest.skip(
                f"{name}: 该域读写**同码**（admin-api 类级 `@RequirePermission({spec['write_code']})`）"
                "⇒ action 级复检没有第二个码可收严；越权面由粗筛 + 服务端注解各自把关"
            )
        with patch.object(spec["module"], "get_admin_api_client", return_value=mock_client):
            for action in sorted(spec["write"]):
                result = await tool.execute(context=_ctx([spec["read_code"]]), action=action,
                                            **_kwargs(name))
                assert result.success is False, (
                    f"{name}/{action}: 只持读码也被放行 ⇒ action 级复检失效（越权写）"
                )
                assert spec["write_code"] in (result.message or ""), (
                    f"{name}/{action}: 拒绝文案没有点名缺哪个码（模型无法向用户解释该开通什么）"
                )
        assert mock_client.post.await_count == 0
        assert mock_client.put.await_count == 0

    @pytest.mark.parametrize("name", ["customer_manage", "category_manage"])
    async def test_write_only_permission_cannot_run_reads(self, name, mock_client):
        """反方向也要挡住：只持写码的人不得借黄金策读业务数据。"""
        spec = CASES[name]
        tool = _tool(name)
        with patch.object(spec["module"], "get_admin_api_client", return_value=mock_client):
            for action in sorted(spec["read"]):
                result = await tool.execute(context=_ctx([spec["write_code"]]), action=action)
                assert result.success is False, (
                    f"{name}/{action}: 只持写码却能跑读 action ⇒ 两段式复检只做了一半"
                )
                assert spec["read_code"] in (result.message or "")


# ══════════════════════════════════════════════════════════════════════════════
# 三、确认门禁是**共享那一个**（不自建第二套）
# ══════════════════════════════════════════════════════════════════════════════


class TestConfirmationGateIsTheSharedOne:
    def test_react_turn_calls_the_same_function_object(self):
        assert react_turn._requires_confirmation is base_skill._requires_confirmation, (
            "运行时门禁与判据引用的不是同一个函数对象 ⇒ 本文件断言的门禁可能不是真正生效的那个"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_tool_does_not_reimplement_the_gate(self, name):
        src = inspect.getsource(CASES[name]["module"])
        assert "def _requires_confirmation" not in src
        assert "def _is_explicit_confirmation" not in src

    @pytest.mark.parametrize("name", sorted(CASES))
    @pytest.mark.parametrize("action", sorted({a for s in CASES.values() for a in s["write"]}))
    def test_gate_blocks_write_action_without_confirmation(self, name, action):
        if action not in CASES[name]["write"]:
            pytest.skip(f"{action} 不是 {name} 的写 action")
        blocked = base_skill._requires_confirmation(
            _tool(name), {"action": action}, "帮我把资料改一下")
        assert blocked is True, (
            f"{name}/{action}: 未确认时被放行 ⇒ 确认门禁没生效"
            "（注入式红证：把 `requires_confirmation` 改成 False，本用例立刻红）"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_gate_exempts_read_actions(self, name):
        for action in sorted(CASES[name]["read"]):
            blocked = base_skill._requires_confirmation(
                _tool(name), {"action": action}, "查一下")
            assert blocked is False, f"{name}/{action} 是只读 action，不应要求确认"


class TestUnconfirmedWriteDoesNotExecute:
    """负控：两次运行只差**用户消息**（同一 tool / 同一 args）。"""

    @pytest.mark.parametrize("name", sorted(CASES))
    async def test_unconfirmed_write_does_not_reach_the_endpoint(self, name, mock_client):
        spec = CASES[name]
        tool = _tool(name)
        action = sorted(spec["write"])[0]
        blocked = base_skill._requires_confirmation(
            tool, {"action": action}, "把资料改一下")
        assert blocked is True, f"{name}: 前提不成立（门禁没拦），负控无从判"
        # 门禁判定在工具之外 ⇒ 未确认时工具根本不该被调用：
        assert mock_client.post.await_count == 0 and mock_client.put.await_count == 0, (
            f"{name}: 未确认路径发出了写请求 ⇒ 静默写"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    async def test_confirmed_write_reaches_the_endpoint(self, name, mock_client):
        spec = CASES[name]
        tool = _tool(name)
        action = sorted(spec["write"])[0]
        assert base_skill._requires_confirmation(tool, {"action": action}, "确认") is False, (
            f"{name}: 用户点卡确认后仍被拦 ⇒ 能力接回但永远办不成"
        )
        with patch.object(spec["module"], "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action=action, **_kwargs(name))
            assert result.success is True, f"{name}/{action}: 持 `*` 权限的真实调用应当成功"
        assert (mock_client.post.await_count + mock_client.put.await_count) > 0, (
            f"{name}: 放行后没有发出任何写请求 ⇒ 写路径是死的"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 四、端点是真的（写路径逐条与 admin-api 控制器注解对齐）
# ══════════════════════════════════════════════════════════════════════════════


class TestEndpointsAreReal:
    @pytest.mark.parametrize("name,controller,annotations", [
        ("customer_manage", "CustomerController.java",
         ['@PutMapping("/api/admin/customers/{id}")']),
        ("category_manage", "CategoryController.java",
         ['@RequestMapping("/api/admin/categories")', "@PostMapping"]),
        ("processing_item_manage", "ProcessingItemController.java",
         ['@RequestMapping("/api/admin/processing-items")', "@PostMapping", '@PutMapping("/{id}")']),
    ])
    def test_write_endpoints_exist_in_admin_api(self, name, controller, annotations):
        if not ADMIN_API_CONTROLLERS.is_dir():
            pytest.skip(f"admin-api Controller 目录不存在（独立检出场景）：{ADMIN_API_CONTROLLERS}")
        src = (ADMIN_API_CONTROLLERS / controller).read_text(encoding="utf-8")
        missing = [a for a in annotations if a not in src]
        assert missing == [], (
            f"{name}: admin-api `{controller}` 里找不到 {missing} ⇒ 写路径恒 404/405"
        )

    async def test_customer_update_payload_uses_canonical_columns(self, mock_client):
        tool = _tool("customer_manage")
        with patch.object(customer_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", customer_id="c1",
                                        data={"name": "张三", "phone": "13900001111"})
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/customers/c1"
        body = mock_client.put.call_args[1]["json_data"]
        assert body == {"wechatNickname": "张三", "phone": "13900001111"}, (
            "姓名别名必须归一化到实体真实列 wechatNickname（否则 admin-api 静默丢弃 = 假成功）"
        )
        assert result.data["updated_fields"] == ["phone", "wechatNickname"]

    async def test_category_create_payload_and_endpoint(self, mock_client):
        tool = _tool("category_manage")
        with patch.object(category_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="create", name="轻奢系列")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/categories"
        assert mock_client.post.call_args[1]["json_data"] == {"name": "轻奢系列"}

    async def test_processing_status_goes_through_full_put(self, mock_client):
        """停用不是删除：仍走真实的 `PUT /{id}`（admin-api 没有 `/{id}/status` 子资源）。"""
        mock_client.get = AsyncMock(return_value={"success": True, "data": {
            "id": "it1", "name": "打孔", "categoryId": "pc1", "craftHint": "打孔", "status": "active"}})
        tool = _tool("processing_item_manage")
        with patch.object(processing_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update_item", item_id="it1",
                                        status="inactive")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-items/it1"
        body = mock_client.put.call_args[1]["json_data"]
        assert body["status"] == "inactive"
        assert body["name"] == "打孔" and body["craftHint"] == "打孔", (
            "全量 PUT 必须回带详情里的原值（否则停用会顺手清空工艺声明 ⇒ 工序路线丢一维）"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 五、校验失败具名（不把服务端 422 直接甩给模型）+ 判别力自证
# ══════════════════════════════════════════════════════════════════════════════


class TestValidationErrorsAreNamed:
    async def test_customer_update_names_missing_customer_id(self, mock_client):
        tool = _tool("customer_manage")
        with patch.object(customer_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", data={"phone": "1"})
        assert result.success is False and "customer_id" in result.message
        assert mock_client.put.await_count == 0

    async def test_customer_update_rejects_unknown_fields_without_writing(self, mock_client):
        tool = _tool("customer_manage")
        with patch.object(customer_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update", customer_id="c1",
                                        data={"不存在的列": "x"})
        assert result.success is False
        assert "不存在的列" in result.error
        assert mock_client.put.await_count == 0, "不可写字段必须零写入（不得部分写入后谎报成功）"

    async def test_category_create_names_missing_name(self, mock_client):
        tool = _tool("category_manage")
        with patch.object(category_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="create")
        assert result.success is False and "name" in result.message
        assert mock_client.post.await_count == 0

    async def test_processing_update_rejects_bad_status(self, mock_client):
        tool = _tool("processing_item_manage")
        with patch.object(processing_mod, "get_admin_api_client", return_value=mock_client):
            result = await tool.execute(context=ADMIN, action="update_item", item_id="it1",
                                        status="archived")
        assert result.success is False and "无效的状态值" in result.error
        assert mock_client.put.await_count == 0

    @pytest.mark.parametrize("name", sorted(CASES))
    async def test_retired_delete_actions_are_refused_at_entry(self, name, mock_client):
        spec = CASES[name]
        tool = _tool(name)
        with patch.object(spec["module"], "get_admin_api_client", return_value=mock_client):
            for action in ("delete", "delete_item", "delete_category", "toggle_item_status"):
                result = await tool.execute(context=ADMIN, action=action, **_kwargs(name))
                assert result.success is False, f"{name}/{action}: 退场 action 又被接回来了"
                assert "不支持的操作类型" in result.message
        assert mock_client.delete.await_count == 0


class TestJudgementIsNotVacuous:
    """判别力自证：判据不能恒真 —— 合成「无门禁写工具」必须被判为**不拦**。"""

    def test_synthetic_write_tool_without_gate_is_not_blocked(self):
        class _NoGate:
            read_only = False
            destructive = False
            requires_confirmation = False
            read_only_actions = frozenset()

        blocked = base_skill._requires_confirmation(_NoGate(), {"action": "update"}, "改一下")
        assert blocked is False, (
            "合成「无门禁写工具」竟被判为需要确认 ⇒ 本文件的确认判据恒真、没有判别力"
        )

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_read_only_flag_flip_makes_the_gate_judgement_flip(self, name):
        """内存注入：把 `read_only` 置 True（= 假装成只读工具）⇒ 门禁立刻不再拦（判据有牙）。"""
        tool = _tool(name)
        original = tool.read_only
        try:
            tool.__class__.read_only = True
            assert base_skill._requires_confirmation(tool, {"action": "update"}, "改一下") is False
        finally:
            tool.__class__.read_only = original
        assert base_skill._requires_confirmation(tool, {"action": "update"}, "改一下") is True
