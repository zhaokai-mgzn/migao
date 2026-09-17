# case_ids: DF-017, HR-009, CH-001, DF-007
"""工具层权限拒绝的语义闭环（issue #4147：G1(a) / G1(b) / G2 / G10）— 常驻 L0/L2 守卫。

## 病灶形状（三条同源：**权限拒绝在工具层没有机器可读的身份**）

- **G1(a)** `validate_input` 的拒绝结果 `ToolResult(success=False, error="权限不足",
  message=None, suggestion=…)` 经 `_execute_tool_safe` 变成 `result_dict`
  （`message` 键**存在且值为 None`）⇒ `_self_correct_retry` 的
  `result_dict.get("message", result_dict.get("error", "执行失败"))` 拿到 **None**
  （`.get` 的默认值对「键存在、值为 None」不生效）⇒ 下一行 `error_msg[:80]`
  **TypeError: 'NoneType' object is not subscriptable**，且该行在函数的 `try` **之外**
  ⇒ 异常穿透到调用方，整轮对话被打断（真实身份 role=operator 实测复现）。
  判据必须落在**消费方**：任何工具都可能不给 `message`（不能靠"每个工具都规矩"）。
- **G1(b)** `ValidateInputTool.allowed_roles` 是**显式类体声明**（不是继承默认值），
  且只列 `["admin","agent","tenant_admin","customer"]` ⇒ 除 admin 外的**全部商户员工**
  （operator / product_manager / customer_service / sales / finance / 自定义岗位）调用
  一律「权限不足」。而本工具是**纯本地参数校验**（不读库、不写库、不调外部 API），
  双端（小布、米宝）都要用，真正的授权在**目标写工具自己的 `required_permissions`** 上。
- **G2** 工具层 `check_permission` 拒绝**从不带 `error_code`**（41 处
  `ToolResult(success=False, error="权限不足")` 里只有 2 处带码，且都在
  `admin_api_failure` 内）⇒ #4122 加的非重试闸门
  （`if result_dict.get("error_code") in NON_RETRYABLE_ERROR_CODES`）**恒不触发**：
  幂等工具（实测 14 个）仍进入 `_self_correct_retry` 的参数改写重放。
- **G10** `NON_RETRYABLE_ERROR_CODES` 里的认证类码（`AUTH_REQUIRED` / `AUTH_FAILED` /
  `UNAUTHORIZED`）被无条件换成「你的账号缺少权限，请管理员在管理后台开通」⇒
  把**服务令牌/登录态故障**误报成用户的权限问题。

## 本文件锁的不变式（每条都有反例输入）

1. `TestFailureTextIsNoneSafe` —— 失败文本取值 None 安全，且**同形兄弟点**（修正后失败
   的日志分支）一并锁住（只改一处 = 没改）；
2. `TestValidateInputGateIsNotARoleList` —— 显式声明的角色门禁不得是「手写角色清单」
   （商户角色码是**开放集合**，任何清单都必然漏掉自定义岗位）；同时证明通配**没有**
   泄漏到其它工具（角色层的粗筛语义原样保留）；
3. `TestDenialsCarryANonRetryableCode` —— **真注册表 × 真身份**：每个被工具级门禁拒绝的
   工具，交付给消费点的结果都带不可重试码（并有"非权限失败照旧可重试"的反向证据）；
4. `TestDenialSiteStaticLock` —— L0 静态锁：`app/tools/*.py` 里每个权限拒绝 ToolResult
   要么走共享构造点（带码），要么被共享盖章判据覆盖；两者都不是 ⇒ 红；
5. `TestAuthenticationFailuresAreNotPermissionGrantProblems` —— 认证类失败不得把基础设施
   故障说成"你的账号缺权限"（非认证的权限拒绝仍必须给开通路径）；
6. 判据自身**可红 + 不恒真**（静态锁有注入式红证；`"*"` 通配有越界红证）。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.graph.skills.base_skill import _execute_tool_safe, _self_correct_retry
from app.tools.base import (
    AUTHENTICATION_ERROR_CODES,
    NON_RETRYABLE_ERROR_CODES,
    PERMISSION_DENIED_CODE,
    BaseTool,
    ToolContext,
    ToolResult,
    admin_api_failure,
    permission_denied,
)
from app.tools.registry import get_tool_registry
from app.tools.validate_input import ValidateInputTool

SERVICE_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SERVICE_DIR / "app" / "tools"

OPERATOR = ToolContext(tenant_id=1, user_id="u-op", session_id="s-op", role="operator",
                       permissions=["order:list"])
CUSTOMER = ToolContext(tenant_id=1, user_id="u-c", session_id="s-c", role="customer",
                       permissions=[])
STATE = {"session_id": "s-op", "tenant_id": 1}


@pytest.fixture(autouse=True)
def _clear_read_only_tool_cache():
    """清空 `_execute_tool_safe` 的只读工具缓存（跨用例污染的已知形态，见 #4109 同款夹具）。"""
    _execute_tool_safe._cache = {}
    _execute_tool_safe._cache_lock = asyncio.Lock()
    yield
    _execute_tool_safe._cache = {}
    _execute_tool_safe._cache_lock = asyncio.Lock()


@pytest.fixture(autouse=True)
def _no_write_audit_network():
    """写审计落库是**admin-api 调用**（3s 上限、fail-open）：单测里必须挡掉，避免真连网。"""
    with patch("app.graph.skills.base_skill.audit_write_tool",
               new=AsyncMock(return_value=True)):
        yield


# ── 替身：把「工具级门禁拒绝 + 交付缺 message 的失败」这一形状固定下来 ──────────────

class _CodelessFailureTool(BaseTool):
    """**门禁放行**但交付 `message=None` 失败的替身（= G1(a) 的原始形状搬到消费方）。

    `allowed_roles` 含 `operator`（门禁放行）⇒ 不会被 G2 的共享盖章判据补码，
    因此这条路径落在"缺码 ⇒ 可重试"的 fail-safe 分支上，纯粹检验消费方 None 安全。
    """

    name = "fake_codeless_failure"
    description = "缺 message 的失败替身（门禁放行）"
    read_only = True
    idempotent = True
    allowed_roles = ["admin", "operator"]
    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=False,
            error="权限不足",
            message=None,
            suggestion="请改用当前账号有权限的操作，或请用户联系管理员开通权限后再校验",
        )


class _DeniedCodelessFailureTool(_CodelessFailureTool):
    """**门禁拒绝** + 缺 `message`：病灶的完整形状（parent 会话实测的那一条）。

    门禁判否 ⇒ 交付结果被共享盖章判据补 `PERMISSION_DENIED` ⇒ 重试被抑制；
    但 `error_msg` 的取值**发生在闸门之前**，所以 None 安全仍是这一路径的硬要求。
    """

    name = "fake_denied_codeless"
    description = "门禁拒绝 + 缺 message 的替身"
    allowed_roles = ["admin"]


class _AllowedFailingTool(BaseTool):
    """**放行**的工具，交付一个参数类失败（反向证据用：非权限失败必须照旧可重试）。"""

    name = "fake_allowed_failing"
    description = "放行 + 参数类失败的替身"
    read_only = True
    idempotent = True
    allowed_roles = ["operator"]
    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        if not kwargs.get("name"):
            return ToolResult(
                success=False,
                error="missing_required_args",
                message="缺少必填参数 name",
                suggestion="请补齐 name 后重试",
                missing_params=["name"],
            )
        return ToolResult(success=True, data={"ok": True}, message="成功")


class _CorrectedFailureTool(_DeniedCodelessFailureTool):
    """修正后的那次调用仍然失败（且同样缺 `message`）——锁 `_self_correct_retry` 的**兄弟点**。"""

    name = "fake_corrected_failure"
    allowed_roles = ["admin", "operator"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=False,
            error="权限不足",
            message=None,
            suggestion="请联系管理员开通权限",
        )


class _FakeLLM:
    """`suggestion_llm` 替身：返回"修正后的参数"JSON 并记录是否被调用。"""

    def __init__(self, payload: dict):
        self.temperature = 0.0
        self._payload = payload
        self.invoked: list[str] = []

    async def ainvoke(self, messages):
        self.invoked.append(messages[0].content if messages else "")
        return MagicMock(content=json.dumps(self._payload, ensure_ascii=False))


async def _retry(tool, tool_args: dict, result_dict: dict, ctx: ToolContext = OPERATOR) -> dict:
    """复刻调用点语义：返回**模型最终看到的工具结果 dict**（未重试时即原 dict）。"""
    original = dict(result_dict)
    outcome = await _self_correct_retry(
        tool, dict(tool_args), ctx, "test_skill", dict(original), ctx.session_id,
        ctx.tenant_id, dict(STATE),
    )
    return outcome[1] if outcome else original


# ════════════════════════════════════════════════════════════════════════════
# G1(a) 消费方 None 安全（判据落在消费方：任何工具都可能不给 message）
# ════════════════════════════════════════════════════════════════════════════

class TestFailureTextIsNoneSafe:
    """`message` 键存在但值为 None ⇒ 不得下标取值（`.get` 的默认值在这种形状下不生效）。"""

    async def test_none_message_denial_does_not_break_the_turn(self):
        """红证（改前）：`error_msg[:80]` 抛 `TypeError: 'NoneType' object is not
        subscriptable`，且该行在 `try` 之外 ⇒ 异常穿透整轮。"""
        tool = _CodelessFailureTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=llm):
            effective = await _retry(tool, {"name": ""}, {
                "success": False, "error": "权限不足", "message": None,
                "suggestion": "请改用当前账号有权限的操作，或请用户联系管理员开通权限后再校验",
            })
        # 缺码 ⇒ fail-safe 可重试（既有语义不变）；关键是**不抛异常**且重放真的发生
        assert tool.calls == [{"name": "修正后的名字"}], (
            f"缺码的失败必须照旧进入一次参数改写重放（实际 {tool.calls!r}）"
        )
        assert effective["success"] is False, "替身修正后仍失败 ⇒ 原样交回，不得崩"

    async def test_none_message_and_none_error_falls_back_to_a_default(self):
        """`message` / `error` 都为 None ⇒ 落到默认文案，而不是拿 None 去切片。"""
        tool = _CodelessFailureTool()
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=_FakeLLM({"name": "x"})), \
                patch("app.graph.skills.base_skill.logger") as logger:
            await _retry(tool, {"name": ""}, {
                "success": False, "error": None, "message": None,
                "suggestion": "请补齐参数后重试",
            })
        logged = " ".join(str(c) for c in logger.info.call_args_list)
        assert "执行失败" in logged, (
            f"message/error 都为空时必须回落到默认文案（而不是把 None 当错误文本）：{logged!r}"
        )
        assert tool.calls == [{"name": "x"}], "全都为空也必须能走完修正链（不得抛异常）"

    async def test_corrected_result_logging_branch_is_none_safe_too(self):
        """**同形兄弟点**：修正后仍失败时那条日志也做 `[:80]` 切片（只修一处 = 没修）。

        红证（改前）：该切片抛 TypeError → 被 `except` 吞掉 → 日志里出现
        `[self-correct] Exception: TypeError`，而「修正后仍失败」这条**业务告警丢失**
        （排障时看不到真实原因）。
        """
        tool = _CorrectedFailureTool()
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=_FakeLLM({"name": "修正后的名字"})), \
                patch("app.graph.skills.base_skill.logger") as logger:
            effective = await _retry(tool, {"name": ""}, {
                "success": False, "error": "查不到", "message": None,
                "suggestion": "请检查参数后重试",
            })
        warnings = " ".join(str(c) for c in logger.warning.call_args_list)
        errors = " ".join(str(c) for c in logger.error.call_args_list)
        assert "Auto-correct still failed" in warnings, (
            f"修正后仍失败必须留下业务告警（实际 warning={warnings!r}）"
        )
        assert "TypeError" not in errors, f"兄弟点仍在抛 TypeError（实际 error={errors!r}）"
        assert effective["success"] is False

    async def test_denied_tool_with_none_message_is_stamped_without_crashing(self):
        """病灶完整形状：**门禁拒绝 + message=None**（parent 会话实测的那一条）。

        改前：`error_msg[:80]` 抛 TypeError（且该行在 `try` 之外 ⇒ 穿透整轮）；
        改后：既不抛，又被共享盖章判据补上不可重试码（两条修复互不掩盖）。
        """
        tool = _DeniedCodelessFailureTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=llm) as factory:
            _, result_dict = await _execute_tool_safe(tool, {"name": ""}, OPERATOR, dict(STATE))
            effective = await _retry(tool, {"name": ""}, result_dict)
        assert result_dict["error_code"] == PERMISSION_DENIED_CODE
        assert factory.call_count == 0, "带码的拒绝必须抑制重放"
        assert effective["success"] is False, "失败仍要原样交回模型（不崩、不吞）"

    async def test_the_denial_source_no_longer_produces_a_none_message(self):
        """源头也补齐：任何门禁拒绝（含未来新增的）经共享出口后 message 都是可用文本。

        改前：`validate_input` 的拒绝是 `message=None` 的**源头** ⇒ 消费方必须自己防；
        改后源头走共享构造点（`permission_denied`）。两道都锁，任一道回退即红。
        """
        tool = ValidateInputTool()
        with patch.object(ValidateInputTool, "check_permission", return_value=False):
            _, result_dict = await _execute_tool_safe(
                tool, {"target_tool": "order_manage", "target_action": "cancel",
                       "params": {"order_id": "O-1"}},
                OPERATOR, dict(STATE),
            )
        assert result_dict["success"] is False
        assert result_dict["error_code"] == PERMISSION_DENIED_CODE
        for key in ("message", "error", "suggestion"):
            assert isinstance(result_dict[key], str) and result_dict[key].strip(), (
                f"拒绝出口的 {key} 必须是可用文本（实际 {result_dict[key]!r}）"
            )


# ════════════════════════════════════════════════════════════════════════════
# G1(b) validate_input 的角色门禁不得是「手写角色清单」
# ════════════════════════════════════════════════════════════════════════════

#: 商户员工角色码：**开放集合** —— 内置五岗（RBAC.md「岗位（实际生效）」）
#: + admin-api「角色管理」可创建的任意自定义码（`_to_agent_role` 明确保留原角色码）
_MERCHANT_ROLES = [
    "operator", "customer_service", "sales", "finance",          # 内置五岗（除 admin）
    "product_manager", "knowledge_editor",                        # 存量自定义码（已被其它工具写进清单）
    "warehouse_keeper", "after_sales_lead",                       # 任意自定义码（清单方案必然漏）
]


class TestValidateInputGateIsNotARoleList:

    def test_the_declaration_is_explicit_and_wildcard(self):
        """**显式类体声明**（不是继承 `BaseTool.allowed_roles` 默认值）且为通配。

        语出 `check_permission` 的契约：角色层是**粗筛**，商户角色码与 admin-api 必然漂移
        ⇒ 任何手写清单都会把持有权限码的员工判成「权限不足」（#4106 F4）。本工具是纯本地
        校验（无读库/写库/外部调用），双端都要用，故角色层对它不适用。
        """
        assert "allowed_roles" in ValidateInputTool.__dict__, (
            "必须是本类的显式声明（继承默认值会让『这份清单是判据』的错觉更难发现）"
        )
        assert set(ValidateInputTool.allowed_roles) == {"*"}

    @pytest.mark.parametrize("role", _MERCHANT_ROLES + ["admin", "customer", "agent",
                                                        "tenant_admin"])
    def test_no_role_is_falsely_denied(self, role):
        """红证（改前）：除 admin/agent/tenant_admin/customer 外**全部为 False**。"""
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                          permissions=["order:list"])
        assert ValidateInputTool().check_permission(ctx) is True, (
            f"role={role} 调用纯本地校验被假拒绝（改前 operator/sales/finance/自定义岗位全中）"
        )

    def test_c_end_confirmation_chain_still_works(self):
        """C 端（小布）依赖 `validate_input` 成功才落「已校验待执行」——通配不得把 C 端关掉。"""
        ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s1", role="customer")
        assert ValidateInputTool().check_permission(ctx) is True

    def test_wildcard_is_declared_by_exactly_one_pure_validator(self):
        """越界红证：`"*"` 只能出现在**纯本地校验类**工具上（当前唯一 = validate_input）。

        否则「通配」就成了给特权工具开后门的通用口令（审核时看不出来的提权面）。
        """
        registry = get_tool_registry()
        wildcard = [name for name in registry.get_tool_names()
                    if "*" in (registry.get_tool(name).allowed_roles or [])]
        assert wildcard == ["validate_input"], (
            f"声明角色通配的工具集合变了（实际 {wildcard!r}）—— 每个都必须单独评审"
        )
        tool = registry.get_tool("validate_input")
        assert tool.read_only is True, "通配只允许给只读工具"
        assert tool.required_permissions == [], "通配只允许给不声明权限码的工具"
        assets = [p.read_text(encoding="utf-8")
                  for p in sorted(TOOLS_DIR.glob("validate_input.py"))]
        assert assets, "validate_input 的源码必须可读（判据不得空转）"

    def test_the_role_layer_still_denies_elsewhere(self):
        """反向证据：通配**没有**泄漏到基类语义 —— 其它工具的角色粗筛原样生效。"""
        registry = get_tool_registry()
        customer_ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s1", role="customer",
                                   permissions=["*"])
        assert registry.get_tool("employee_manage").check_permission(customer_ctx) is False, (
            "B 端员工管理工具不得对 customer 放行（C 端硬闸不得被削弱）"
        )
        assert registry.get_tool("customer_order_query").check_permission(OPERATOR) is False, (
            "C 端专属工具的角色粗筛必须保留（B 端员工调用仍被拒）"
        )


# ════════════════════════════════════════════════════════════════════════════
# G2 工具层权限拒绝必须带不可重试码（真注册表 × 真身份）
# ════════════════════════════════════════════════════════════════════════════

_TYPE_SAMPLES = {"string": "x", "integer": 1, "number": 1.5, "boolean": True,
                 "array": ["x"], "object": {"x": 1}}
_UUIDISH = "11111111-1111-1111-1111-111111111111"


def _sample_args(tool) -> dict:
    """按工具**自己声明的** `parameters.required` 造一份满足入参契约的入参。

    枚举取首值、`*_ids` 取 UUID 形状（避免 `_auto_resolve_ids` 真去 admin-api 解析名字）。
    被拒绝的工具在门禁处即返回，因此这些参数**不会**真的打到下游。
    """
    params = tool.parameters or {}
    props = params.get("properties") or {}
    args: dict = {}
    for name in params.get("required") or []:
        schema = props.get(name) or {}
        if schema.get("enum"):
            args[name] = schema["enum"][0]
        elif name.endswith("_id") or name.endswith("_ids"):
            args[name] = _UUIDISH
        else:
            args[name] = _TYPE_SAMPLES.get(schema.get("type", "string"), "x")
        if name.endswith("_ids"):
            args[name] = [_UUIDISH]
    return args


async def _delivered_results_for_denied_tools(ctx: ToolContext) -> list[tuple[str, dict]]:
    """把**真注册表里每个被工具级门禁拒绝的工具**开一次（真共享入口），收集交付结果。"""
    registry = get_tool_registry()
    delivered: list[tuple[str, dict]] = []
    for name in sorted(registry.get_tool_names()):
        tool = registry.get_tool(name)
        gate = getattr(tool, "check_permission", None)
        if not callable(gate) or gate(ctx) is not False:
            continue
        args = _sample_args(tool)
        contract_failure = tool.validate_args(args)
        assert contract_failure is None, (
            f"{name}: 守卫自身的入参样本不满足契约（{contract_failure}）—— 样本生成器要跟上"
        )
        _, result_dict = await _execute_tool_safe(tool, dict(args), ctx, dict(STATE))
        delivered.append((name, result_dict))
    return delivered


class TestDenialsCarryANonRetryableCode:
    """改前：`result_dict["error_code"]` 为 None ⇒ #4122 的非重试闸门恒不触发。"""

    async def test_every_denied_tool_delivers_a_non_retryable_code(self):
        delivered = await _delivered_results_for_denied_tools(OPERATOR)
        assert len(delivered) >= 5, (
            f"厚度守卫：operator 身份应被多个工具拒绝（实际 {len(delivered)}）—— 判据疑似空转"
        )
        missing = [(name, rd.get("error_code")) for name, rd in delivered
                   if rd["success"] is False
                   and rd.get("error_code") not in NON_RETRYABLE_ERROR_CODES]
        assert missing == [], (
            f"工具层权限拒绝必须带不可重试码（否则进入参数改写重放）：{missing!r}"
        )

    async def test_c_end_denials_carry_the_code_too(self):
        """C 端（顾客）身份走的是 C 端硬闸/角色层，同样必须带码（两端不得只修一半）。"""
        delivered = await _delivered_results_for_denied_tools(CUSTOMER)
        assert len(delivered) >= 3, f"厚度守卫：customer 身份应被多个工具拒绝（实际 {len(delivered)}）"
        missing = [name for name, rd in delivered
                   if rd["success"] is False
                   and rd.get("error_code") not in NON_RETRYABLE_ERROR_CODES]
        assert missing == [], f"以下工具对顾客的拒绝缺不可重试码：{missing!r}"

    async def test_registry_execution_path_carries_the_code(self):
        """第二个共享入口：`ToolRegistry.execute_tool` 的拒绝同样必须带码。"""
        registry = get_tool_registry()
        result = await registry.execute_tool(
            "logistics_track", OPERATOR, order_id=_UUIDISH,
        )
        assert result.success is False
        assert result.error_code == PERMISSION_DENIED_CODE, (
            f"注册表拒绝必须带码（实际 {result.error_code!r}）"
        )

    async def test_denied_idempotent_tool_no_longer_enters_the_retry_replay(self):
        """病灶效果层：被拒绝的幂等工具**不得**再被参数改写重放（llm 一次都不许调）。"""
        tool = get_tool_registry().get_tool("logistics_track")
        llm = _FakeLLM({"order_id": _UUIDISH})
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=llm) as factory:
            _, result_dict = await _execute_tool_safe(
                tool, {"order_id": _UUIDISH}, OPERATOR, dict(STATE),
            )
            effective = await _retry(tool, {"order_id": _UUIDISH}, result_dict)
        assert result_dict["success"] is False
        assert result_dict["error_code"] in NON_RETRYABLE_ERROR_CODES
        assert factory.call_count == 0, "权限拒绝不得触发 suggestion_llm（重试入口必须关闭）"
        assert llm.invoked == [], "权限拒绝不得被改写成「参数问题」"
        assert effective["suggestion"], "失败与 suggestion 仍要原样交回模型决策"

    async def test_a_failing_double_is_not_stamped_when_the_gate_allows(self):
        """**不得过度收紧**：放行的工具交付参数类失败 ⇒ 不盖章、照旧进入自修复重放。"""
        tool = _AllowedFailingTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=llm) as factory:
            _, result_dict = await _execute_tool_safe(tool, {}, OPERATOR, dict(STATE))
            assert result_dict["error_code"] in (None, ""), (
                f"参数类失败不得被当成权限拒绝（实际 {result_dict['error_code']!r}）"
            )
            effective = await _retry(tool, {}, result_dict)
        assert factory.call_count == 1, "非权限失败必须保留既有自修复能力"
        assert effective["success"] is True

    async def test_validation_failure_on_a_denied_tool_still_reaches_the_retry_path(self):
        """入参契约失败（**不是**执行出来的失败）不在盖章范围内 ⇒ 仍可重试。

        这是「盖章只覆盖真的执行过的那条出口」的显式契约：缺参要靠模型补参，
        而不是被一句「没权限」顶掉（真正无权限时下一次调用会拿到带码的拒绝）。
        """
        tool = get_tool_registry().get_tool("logistics_track")
        llm = _FakeLLM({"order_id": _UUIDISH})
        with patch("app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                   return_value=llm) as factory:
            _, result_dict = await _execute_tool_safe(tool, {}, OPERATOR, dict(STATE))
            assert result_dict["error"] == "missing_required_args"
            await _retry(tool, {}, result_dict)
        assert factory.call_count == 1, "缺参失败必须照旧自修复（不得被权限语义吞掉）"

    def test_permission_denied_helper_is_the_single_construction_point(self):
        """共享构造点：拒绝结果自带不可重试码 + 可执行建议（与 `admin_api_failure` 同源文案）。"""
        result = permission_denied()
        assert result.success is False
        assert result.error_code == PERMISSION_DENIED_CODE
        assert "不要重试" in (result.suggestion or ""), (
            "共享构造点的默认建议必须可执行（否则拒绝又变成「稍后重试」套话）"
        )
        assert result.message, "共享构造点必须给出用户可见文案（G1(a) 的 None-message 源头）"


# ════════════════════════════════════════════════════════════════════════════
# G2 L0 静态锁：拒绝点要么带码、要么被共享盖章判据覆盖
# ════════════════════════════════════════════════════════════════════════════

def _callee(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _kwarg(node: ast.Call, key: str) -> ast.AST | None:
    for kw in node.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_permission_gate(stmt: ast.AST | None) -> bool:
    """`if not self.check_permission(context):` / `if not tool.check_permission(context):`"""
    if not isinstance(stmt, ast.If):
        return False
    test = stmt.test
    return (
        isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Call)
        and isinstance(test.operand.func, ast.Attribute)
        and test.operand.func.attr == "check_permission"
    )


def _body_containing(stmt: ast.AST, parents: dict) -> list:
    parent = parents.get(stmt)
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(parent, attr, None)
        if isinstance(block, list) and stmt in block:
            return block
    return []


def uncoded_permission_denials(source: str) -> list[int]:
    """返回「既没带 `error_code`、又不被共享盖章判据覆盖」的权限拒绝 ToolResult 行号。

    共享盖章判据（`_execute_tool_safe`）= **工具级 `check_permission` 门禁拒绝** ⇒ 该次执行
    交付的失败由共享入口补 `PERMISSION_DENIED`。因此「紧跟在门禁之后」的裸拒绝是合法的；
    action 级 / 归属级等**门禁之外**的拒绝必须自己走共享构造点（带码），否则消费点读不到码。
    """
    hits: list[int] = []
    tree = ast.parse(source)
    parents: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _callee(node) != "ToolResult":
            continue
        if _const_str(_kwarg(node, "error")) != "权限不足":
            continue
        if _const_str(_kwarg(node, "error_code")):   # 已走共享构造点
            continue
        ret = node
        while ret is not None and not isinstance(ret, ast.Return):
            ret = parents.get(ret)
        if ret is None or _is_shadowed_by_permission_gate(ret, parents):
            if ret is None:
                hits.append(node.lineno)
            continue                                  # 被共享盖章判据覆盖
        hits.append(node.lineno)
    return sorted(hits)


def _is_shadowed_by_permission_gate(ret: ast.AST, parents: dict) -> bool:
    """该 `return` 是否处在「工具级 `check_permission` 门禁判否」的出口上。

    两种 AST 形状都算（改前只认第一种，导致真门禁被误报）：
    ① `if not gate: return …`（return 是门禁 if 体的第一条语句）；
    ② `if not gate: <别的语句>` 之后紧跟的 `return …`（同一 block 的前一条语句是门禁）。
    逐层上溯：外层门禁同样算覆盖。
    """
    cur = ret
    while cur is not None:
        parent = parents.get(cur)
        if parent is None:
            return False
        block = _body_containing(cur, parents)
        if block:
            index = block.index(cur)
            if index > 0 and _is_permission_gate(block[index - 1]):
                return True
        if (isinstance(parent, ast.If) and _is_permission_gate(parent)
                and cur in parent.body):
            return True
        cur = parent
    return False


#: 注入式红证：门禁**之外**的裸拒绝（= 消费点读不到码的形状）
_SAMPLE_VIOLATION = '''
class T:
    async def execute(self, context, action):
        if context.role == "customer":
            return ToolResult(success=False, error="权限不足", message="x")
'''

#: 阴性对照：同一检查器对「门禁之后的裸拒绝」与「走共享构造点」都**不得**报
_SAMPLE_SHADOWED = '''
class T:
    async def execute(self, context):
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足", message="x")
'''

_SAMPLE_HELPER = '''
class T:
    async def execute(self, context, action):
        if context.role == "customer":
            return permission_denied(message="x")
'''


class TestDenialSiteStaticLock:
    """`app/tools/*.py` 全量扫描（含**其它包持有**的三个文件：它们由共享判据覆盖）。"""

    def test_checker_can_go_red_and_is_not_vacuous(self):
        assert uncoded_permission_denials(_SAMPLE_VIOLATION), "注入的裸拒绝必须被报出来"
        assert uncoded_permission_denials(_SAMPLE_SHADOWED) == [], (
            "门禁之后的拒绝由共享盖章判据覆盖，不得误报"
        )
        assert uncoded_permission_denials(_SAMPLE_HELPER) == [], (
            "走共享构造点（无 ToolResult 字面量）不得误报"
        )

    def test_no_uncoded_unshadowed_denial_sites_in_tools(self):
        files = sorted(TOOLS_DIR.glob("*.py"))
        assert len(files) >= 30, f"工具源码扫描疑似失效（只找到 {len(files)} 个文件）"
        violations: list[str] = []
        scanned = 0
        for path in files:
            source = path.read_text(encoding="utf-8")
            scanned += sum(1 for node in ast.walk(ast.parse(source))
                           if isinstance(node, ast.Call) and _callee(node) == "ToolResult"
                           and _const_str(_kwarg(node, "error")) == "权限不足")
            for lineno in uncoded_permission_denials(source):
                violations.append(f"{path.name}:{lineno}")
        assert scanned >= 30, f"厚度守卫：只扫到 {scanned} 个权限拒绝点 —— 判据疑似空转"
        assert violations == [], (
            "以下权限拒绝既没有 error_code、也不在工具级门禁之后 ⇒ 消费点读不到码（"
            "应改用 `app.tools.base.permission_denied(...)`）：" + ", ".join(violations)
        )


# ════════════════════════════════════════════════════════════════════════════
# G10 认证类失败不得报成「你的账号缺权限」
# ════════════════════════════════════════════════════════════════════════════

#: 权限**开通**路径（只在真的是授权问题时才允许出现）
_GRANT_PATH_MARKERS = ("「员工管理 → 编辑员工 → 权限」", "「角色管理 → 岗位权限」",
                       "开通后", "缺少执行该操作所需的", "为该账号")


class TestAuthenticationFailuresAreNotPermissionGrantProblems:

    def test_the_auth_codes_are_the_expected_three(self):
        assert AUTHENTICATION_ERROR_CODES == {"AUTH_REQUIRED", "AUTH_FAILED", "UNAUTHORIZED"}
        assert AUTHENTICATION_ERROR_CODES <= NON_RETRYABLE_ERROR_CODES, (
            "认证失败重试同样无用 ⇒ 必须仍是不可重试（只改文案，不改重试语义）"
        )

    @pytest.mark.parametrize("code", sorted(AUTHENTICATION_ERROR_CODES))
    def test_authentication_failure_points_at_session_or_token(self, code):
        result = admin_api_failure(
            {"success": False, "error": {"code": code, "message": "未认证"}},
            error="未认证", suggestion="请稍后重试，如持续失败请联系技术支持",
        )
        text = result.suggestion or ""
        assert result.error_code == code
        assert "不要重试" in text, f"{code}: 重试无用，必须明说（实际 {text!r}）"
        assert any(w in text for w in ("登录", "会话", "令牌")), (
            f"{code}: 必须指出这是登录态/会话/令牌（认证）问题（实际 {text!r}）"
        )
        for marker in _GRANT_PATH_MARKERS:
            assert marker not in text, (
                f"{code}: 认证故障不得说成「账号缺权限、去管理后台开通」（{marker!r} 出现在 {text!r}）"
            )
        assert "**不是**账号缺少权限" in text, (
            f"{code}: 必须明确指出这**不是**账号缺权限（否则模型仍会引导用户去开通）（实际 {text!r}）"
        )

    @pytest.mark.parametrize("code", ["PERMISSION_DENIED", "FORBIDDEN"])
    def test_real_permission_denials_keep_the_grant_path(self, code):
        """反向证据：授权类失败仍必须给开通路径（不得被 G10 的文案顺手删掉）。"""
        result = admin_api_failure(
            {"success": False, "error": {"code": code, "message": "权限不足"}},
        )
        text = result.suggestion or ""
        assert "管理员" in text and "开通" in text, f"{code}: 授权失败必须给开通路径（实际 {text!r}）"
        assert "权限" in text

    def test_auth_guidance_is_derived_from_the_code_not_the_caller(self):
        """调用方给的套话在认证分支同样必须被顶掉（与授权分支同口径）。"""
        result = admin_api_failure(
            {"success": False, "error": {"code": "UNAUTHORIZED", "message": "401"}},
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
        assert "请稍后重试" not in (result.suggestion or "")

    def test_permission_denied_helper_uses_the_permission_branch(self):
        """共享构造点用的是**授权**分支文案（工具层拒绝 = 真的缺权限，不是认证故障）。"""
        text = permission_denied().suggestion or ""
        assert "开通" in text and "管理员" in text
        assert "登录" not in text, "工具层拒绝是按角色/权限码判的，不得说成登录态问题"