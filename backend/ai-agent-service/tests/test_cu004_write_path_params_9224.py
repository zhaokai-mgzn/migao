# case_ids: CU-004
"""CU-004 的写路径判据：`data` 参数在共享执行入口被解包丢掉（issue #9224）。

## 现取证据（run 45979067843 的 `eval-summary-mibao.json`，逐字）

```text
R2 you=确认：客户=张三（当前手机号 138****8000）；…
   tools=validate_input,customer_manage,customer_manage
   failed=customer_manage{action=update}!缺少更新数据,customer_manage{action=update}!缺少更新数据
   args=customer_manage{},customer_manage{}
call_args=… customer_manage{"action":"update","customer_id":"cust_eval_zhangsan",
                            "data":{"phone":"139****1111"}} …
WRITE_NOT_PERSISTED: 客户「13900001111」不在库里（本用例写出的新号）而种子号「13800138000」仍在
```

## 两处读数的口径必须先厘清（否则会去修错的那一跳）

1. **`data` 不是空的**。轨迹里的 `args=customer_manage{}` 是 runner 的**写工具专属压缩**
   （`tests/agent_eval/local_runner.py::_compact_write_args` 只渲染 items / 金额 / 验证码字段，
   `customer_manage` 的 `data` 不在其中 ⇒ 渲染成 `{}`）。真正的丢参发生在
   `app/graph/skills/base_skill.py::_execute_tool_safe` 的「MiniMax 把参数包在 `data` 键下」兜底：
   它**无条件**解包 ⇒ `{action, customer_id, data:{phone}}` 变成 `{phone, action, customer_id}`
   ⇒ `data` 归 `None` ⇒ 工具报「缺少更新数据」；拆出来的那个 `phone` 又被 `**kwargs` 静默吞掉
   ⇒ **写调用一次都没到 HTTP 层**，库里当然没有新号（`WRITE_NOT_PERSISTED`）。
2. **`139****1111` 是 runner 的日志脱敏，不是模型写了掩码**：同一段渲染把 R1 的
   `keyword:"13800138000"` 也打成 `138****8000`，而那一跳**真的查到了**客户
   （`data=customer_manage(customers=1 total=1 …)`）—— 掩码串搜不到客户，只有真号能命中
   （实现见 `tests/agent_eval/local_runner.py::_arg_scalar` → `_mask_pii_in_arg_text`）。

## 本文件钉三条（每条都能单独变红）

| # | 判据 | 变红的形态 |
|---|---|---|
| A | 声明了 `data` 参数的写工具，执行时**必须原样收到** `data` | 恢复无条件解包 ⇒ 工具收到 `data=None` |
| B | **没声明** `data` 的工具仍要解包（MiniMax 兜底不能被 A 一起删掉） | 把解包整段删除 ⇒ 参数一个都不落地 |
| C | `validate_input(params=…)` 里的**掩码形态**号码不得原样流进写路径 | 掩码原样留在 `params` ⇒ 点卡后的代码收口照着它写 |
"""
import asyncio
from unittest.mock import MagicMock, patch


from app.graph.skills.base_skill import _execute_tool_safe
from app.graph.skills.injection_blocks import _masked_phone_write_block
from app.tools.base import BaseTool, ToolContext, ToolResult

#: CU-004 现场的目标客户（独立栈种子客户）
CUSTOMER_ID = "cust_eval_zhangsan"
#: 种子号（`pre_clean` 的复位目标 = 库里本来就有的号）
OLD_PHONE = "13800138000"
#: 顾客本轮要求改成的**新号**（真值；`data.phone` 必须是它）
NEW_PHONE = "13900001111"
#: 新号的掩码形态（模型若从被脱敏的历史里抄值，拿到的就是它）
NEW_PHONE_MASK = "139****1111"


class _CustomerLikeTool(BaseTool):
    """与 `app/tools/customer_manage.py` 同形的写工具替身：`data` 是**业务参数**。

    唯一被替身化的是「真的打 HTTP」；`parameters`（声明了 `data` 属性）与 `execute` 的
    形参表都逐字对齐真工具 —— 判据要测的正是「schema 声明了 data ⇒ 不许解包」这条。
    """

    name = "customer_manage"
    description = "替身：声明 data 参数的写工具（对齐 app/tools/customer_manage.py）"
    read_only = False
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "update"]},
            "customer_id": {"type": "string"},
            "data": {"type": "object"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.calls = []

    async def execute(self, context, action, customer_id=None, data=None, **kwargs):
        self.calls.append({"action": action, "customer_id": customer_id,
                           "data": data, "extra": dict(kwargs)})
        return ToolResult(success=True, data={"customer_id": customer_id})


class _WrappedOnlyTool(BaseTool):
    """**没有** `data` 参数的工具（MiniMax 包裹形态的合法目标，如 `order_create` 一族）。"""

    name = "order_create"
    description = "替身：没有 data 参数的工具"
    read_only = False
    parameters = {
        "type": "object",
        "properties": {"product_name": {"type": "string"}, "quantity": {"type": "number"}},
        "required": [],
    }

    def __init__(self):
        self.calls = []

    async def execute(self, context, product_name=None, quantity=None, **kwargs):
        self.calls.append({"product_name": product_name, "quantity": quantity,
                           "extra": dict(kwargs)})
        return ToolResult(success=True)


def _ctx() -> ToolContext:
    return ToolContext(tenant_id=1, user_id="u-eval", role="admin", permissions=["*"])


def _state() -> dict:
    return {"session_id": "", "tenant_id": 1}


# ── A. 点卡后重放的写调用：`data` 必须原样到达工具 ─────────────────────────────
def test_nested_data_reaches_the_tool_intact():
    """CU-004 的 R2：`customer_manage(action=update, data={phone: 新号})` 必须带着 `data` 执行。

    红证：把 `_unwrap_wrapped_data` 的解包条件退回「无条件」（或删掉 `data` 声明判断）⇒
    这里收到 `data=None` + `extra={"phone": 新号}` ⇒ 工具报「缺少更新数据」。
    """
    tool = _CustomerLikeTool()
    args = {"action": "update", "customer_id": CUSTOMER_ID, "data": {"phone": NEW_PHONE}}

    asyncio.run(_execute_tool_safe(tool, dict(args), _ctx(), _state()))

    assert tool.calls == [{"action": "update", "customer_id": CUSTOMER_ID,
                           "data": {"phone": NEW_PHONE}, "extra": {}}], (
        "点卡后的写调用把 validate_input 校验过的 data 丢了：工具收到的 data="
        f"{tool.calls[0]['data']!r}、top-level 多余参数={tool.calls[0]['extra']!r}"
    )


# ── B. MiniMax 包裹形态仍要解包（不能为了修 A 把兜底删掉）─────────────────────
def test_minimax_wrapped_args_are_still_unwrapped_for_tools_without_data_param():
    """**没声明** `data` 的工具：`{"data": {…全部参数…}}` 仍要摊平成真实参数。

    红证：把解包整段删掉（"为了不丢 data，干脆不解包"）⇒ 这里一个参数都收不到。
    """
    tool = _WrappedOnlyTool()
    args = {"data": {"product_name": "遮光窗帘", "quantity": 3}}

    asyncio.run(_execute_tool_safe(tool, dict(args), _ctx(), _state()))

    assert tool.calls == [{"product_name": "遮光窗帘", "quantity": 3, "extra": {}}]


# ── C. `validate_input` 的 `params` = 写参数：掩码号不得原样流进写路径 ─────────
def test_masked_phone_in_validation_params_is_rewritten_to_the_real_number():
    """`validate_input(params.data.phone)` 是掩码时，必须就地改写成顾客给的**真号**。

    为什么这条在写路径上：`params` 会被落进 `pending_validated_input`，点卡后的代码收口
    （`app/graph/skills/execution/finalize_turn.py` 的确认-执行链）直接照它执行 ⇒
    掩码一旦进账，写的就是掩码。

    红证：把 `_masked_phone_write_block` 的改写分支去掉（或让 `block_unresolvable=False`
    仍然拦截/放行不改写）⇒ `params.data.phone` 仍是 `139****1111`。
    """
    from langchain_core.messages import HumanMessage

    args = {"target_tool": "customer_manage", "target_action": "update",
            "params": {"customer_id": CUSTOMER_ID, "data": {"phone": NEW_PHONE_MASK}}}
    # R1 的顾客消息（真号在这里）＝真值来源；R2 的消息是卡值（只含掩码）⇒ 只能靠会话里认出来
    state = {"role": "admin",
             "messages": [HumanMessage(content=f"张三（手机号 {OLD_PHONE}）的手机号改成 {NEW_PHONE}")]}

    class _EmptyStore:
        async def load(self, session_id):
            return {}

    with patch("app.memory.session_state_store.SessionStateStore", return_value=_EmptyStore()):
        out = asyncio.run(_masked_phone_write_block(
            "validate_input", args, {"name": "validate_input", "args": args},
            "sess-cu004", "customer", "", state, block_unresolvable=False))

    assert out is None, "校验参数不是写工具，不该被拦死（只许就地改写真号）"
    assert args["params"]["data"]["phone"] == NEW_PHONE


def test_validation_params_already_real_are_left_untouched():
    """幂等边界：已经是真号 ⇒ 一个字节都不动（否则会把合法调用改坏）。"""
    args = {"target_tool": "customer_manage", "target_action": "update",
            "params": {"customer_id": CUSTOMER_ID, "data": {"phone": NEW_PHONE}}}

    out = asyncio.run(_masked_phone_write_block(
        "validate_input", args, {"name": "validate_input", "args": args},
        "", "customer", "", {"role": "admin"}, block_unresolvable=False))

    assert out is None
    assert args["params"]["data"]["phone"] == NEW_PHONE


# ── D. 真工具 + 假 admin-api：写请求的 body 必须带新号（不是掩码、不是旧号）────
def test_customer_manage_update_puts_the_new_phone_in_the_request_body():
    """端到端（Python 侧）：`data` 必须一路走到 `PUT /api/admin/customers/{id}` 的 body。

    这一跳是「参数 → 网络请求」的唯一收口：`data` 丢了就退回 `缺少更新数据`，
    掩码进去就写掩码 —— 两种都在这里具名报出来。
    """
    from app.tools.customer_manage import CustomerManageTool

    sent = {}

    class _FakeClient:
        async def put(self, path, json_data=None, tenant_id=None, user_id=None):
            sent.update(path=path, json_data=json_data, tenant_id=tenant_id, user_id=user_id)
            return {"success": True, "data": {"id": CUSTOMER_ID, "phone": NEW_PHONE}}

    tool = CustomerManageTool()
    args = {"action": "update", "customer_id": CUSTOMER_ID, "data": {"phone": NEW_PHONE}}
    with patch("app.tools.customer_manage.get_admin_api_client", return_value=_FakeClient()):
        result_str, result_dict = asyncio.run(
            _execute_tool_safe(tool, dict(args), _ctx(), _state()))

    assert result_dict["success"] is True, result_str
    assert sent["path"] == f"/api/admin/customers/{CUSTOMER_ID}"
    assert sent["json_data"] == {"phone": NEW_PHONE}


# ── E. 接线判据：门禁 7 必须真的把 `validate_input` 纳入射程 ─────────────────
def _gate_source(src: str, gate_name: str) -> str:
    """取 `_run_one_tool` 里某个门禁闭包的源码文本（fail-closed：找不到就报错）。"""
    import ast

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == gate_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"门禁 {gate_name} 不存在（fail-closed，不静默通过）")


def test_gate_seven_covers_validate_input_params():
    """接线：门禁 7 的 `read_only` 早退**不得**无条件跳过 `validate_input`。

    为什么必须有这条：C 段测的是守卫**本体**，而「门禁到底有没有把它用在 validate_input 上」
    是另一件事 —— 只改本体、不改接线时 C 段全绿，缺陷原封不动（`validate_input` 是只读工具，
    旧实现整段跳过它）。红证：删掉 `and not _validation_params` / 删掉 `block_unresolvable=`
    实参 ⇒ 本条具名红。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "app" / "graph" / "skills" / "execution" / "react_turn.py").read_text(encoding="utf-8")
    gate = _gate_source(src, "_gate_masked_phone_write")

    assert 'str(tool_name) == "validate_input"' in gate, "门禁 7 没认出 validate_input 这个目标"
    assert "and not _validation_params" in gate, (
        "门禁 7 的 read_only 早退又变成无条件了 ⇒ validate_input 的掩码参数没人管")
    assert "block_unresolvable=not _validation_params" in gate, (
        "门禁 7 没给 validate_input 传「只改写不拦」的开关 ⇒ 校验会被掩码守卫拦死")
