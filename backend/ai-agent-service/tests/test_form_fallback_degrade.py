# case_ids: CH-009
"""`__FORM__` 的回退必须是「降级」而不是「重来」（issue #5451）。

**复现（修前，实测）**：payload 非法 ⇒ `_handle_form_request` 把**原文**交回入口
`send_message` ⇒ 入口再按 `__FORM__|` 前缀分派回它自己 ⇒ **互递归**：
进入处理器 **328 次**后 `RecursionError`；`session_id` 为空时同一形态还**建了 328 个会话**
（回退不携带已解析的 session_id）。

三层判据（各自独立会红）：
1. **运行时实例 + 结构**：非法 payload ⇒ **确定终点**（不递归），且**分派入口只被进入 1 次**、
   出口是**另一个入口** `_send_plain_message`（「降级」= 换入口；「重来」= 再进分派入口）；
2. **类级元守卫（源码 AST）**：入口的每条分派分支**未登记即红**；**任何前缀处理器都不得
   把本处理器自己的 request 交回分派入口**（回退必须改变状态或换入口）；降级终点
   `_send_plain_message` **自身不含前缀分派**（否则降级点又变成新的分派点）；
3. **对照**：合法 payload 照旧注入上下文、不回退。
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.api.chat as chat
from app.api.chat import _FORM_MAX_LEN
from app.api.schemas import ChatSendRequest
from app.utils.auth import UserIdentity

_CHAT_PY = Path(chat.__file__)
_SRC = _CHAT_PY.read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


# ═══════════════════════════════════════════════
# 共用：假件与「入口被进入几次」的探针
# ═══════════════════════════════════════════════

def _user():
    return UserIdentity(user_id="user_1", tenant_id=1, identity_type="wechat_mini", role="customer")


def _session(session_id="sess_1", status="active"):
    return {
        "id": session_id, "tenant_id": 1, "customer_id": "user_1",
        "title": "t", "status": status,
        "created_at": "2026-06-20T10:00:00Z", "updated_at": "2026-06-20T10:00:00Z",
    }


class _FakeMemory:
    """内存假件：记录 `create_session` 次数（回退是否重复建会话的可数读数）。"""

    def __init__(self):
        self.created = 0

    async def get_session(self, session_id):
        return _session(session_id)

    async def create_session(self, **kw):
        self.created += 1
        return f"sess_new_{self.created}"

    def __getattr__(self, _name):
        async def _noop(*_a, **_kw):
            return None
        return _noop


async def _dispatch(message, session_id="sess_1"):
    """真实走一遍**入口分派**（不 mock `send_message` —— mock 掉它正是旧测试掩盖递归的原因）。

    只把 `SessionMemory` 与 agent 依赖换成假件；对 `send_message`（分派入口）与
    `_send_plain_message`（降级入口）各插一层**计数探针**。
    """
    fake_mem = _FakeMemory()
    entries, plain_calls = [], []
    real_send = chat.send_message
    real_plain = getattr(chat, "_send_plain_message", None)

    async def probed_send(request, current_user):
        entries.append(request)
        return await real_send(request, current_user)

    async def probed_plain(request, current_user):
        plain_calls.append(request)
        return await real_plain(request, current_user)

    router = MagicMock()
    router.route.return_value = "xiaobu"

    patchers = [
        patch.object(chat, "SessionMemory", lambda *a, **kw: fake_mem),
        patch.object(chat, "get_tool_registry", MagicMock()),
        patch.object(chat, "get_agent", MagicMock()),
        patch.object(chat, "send_message", probed_send),
        patch("app.agents.agent_router.get_agent_router", MagicMock(return_value=router)),
    ]
    if real_plain is not None:
        patchers.append(patch.object(chat, "_send_plain_message", probed_plain))
    for p in patchers:
        p.start()
    try:
        resp = await probed_send(
            ChatSendRequest(session_id=session_id, message=message), _user(),
        )
    except RecursionError as e:  # pragma: no cover - 修前形态（红）
        raise AssertionError(
            f"回退路径自递归：分派入口被进入 {len(entries)} 次后 RecursionError；"
            f"降级入口被调用 {len(plain_calls)} 次；建会话 {fake_mem.created} 个"
        ) from e
    finally:
        for p in patchers:
            p.stop()
    return SimpleNamespace(entries=entries, plain_calls=plain_calls,
                           created=fake_mem.created, response=resp)


_ILLEGAL_PAYLOADS = {
    "非法 JSON": "__FORM__|not-json",
    "非对象 payload": '__FORM__|["a","b"]',
    "超限 payload": "__FORM__|" + "x" * (_FORM_MAX_LEN + 1),
}
_LEGAL = '__FORM__|{"customer_name":"张三","customer_phone":"13800138000"}'


# ═══════════════════════════════════════════════
# 1. 运行时：非法 payload ⇒ 确定终点 + 换入口（降级）
# ═══════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_ILLEGAL_PAYLOADS))
async def test_illegal_payload_reaches_deterministic_terminal(label):
    """非法 payload ⇒ 不递归；分派入口**只进 1 次**；出口是降级入口（不是再进分派入口）。"""
    out = await _dispatch(_ILLEGAL_PAYLOADS[label])

    assert len(out.entries) == 1, (
        f"[{label}] 分派入口被进入 {len(out.entries)} 次 —— 回退把原文交回了同一个入口（应为 1）"
    )
    assert len(out.plain_calls) == 1, (
        f"[{label}] 降级入口 `_send_plain_message` 被调用 {len(out.plain_calls)} 次（应为 1）"
    )
    assert out.response.status_code == 200 and out.response.media_type == "text/event-stream", (
        f"[{label}] 没走到普通文本路径的响应（status={getattr(out.response, 'status_code', None)}，"
        f"media_type={getattr(out.response, 'media_type', None)}）"
    )


@pytest.mark.asyncio
async def test_illegal_payload_new_session_creates_one_session():
    """新会话 + 非法 payload ⇒ **只建 1 个会话**（旧形态：328 层递归 ⇒ 328 个会话）。"""
    out = await _dispatch("__FORM__|not-json", session_id=None)

    assert out.created == 1, f"建了 {out.created} 个会话（应为 1：回退需携带已解析的 session_id）"
    assert len(out.entries) == 1, f"分派入口被进入 {len(out.entries)} 次（应为 1）"


@pytest.mark.asyncio
async def test_legal_payload_still_injects_and_lands_on_plain_entry():
    """对照：合法 payload 照旧注入上下文、不回退（且同样不重进分派入口）。"""
    out = await _dispatch(_LEGAL)

    assert len(out.entries) == 1, f"合法路径重进了分派入口 {len(out.entries)} 次"
    assert len(out.plain_calls) == 1, f"合法路径未落到普通文本入口（{len(out.plain_calls)} 次）"
    injected = out.plain_calls[0].message
    assert injected.startswith("（用户通过表单提交）"), injected
    assert "customer_name: 张三" in injected, injected
    assert "customer_phone: 13800138000" in injected, injected


# ═══════════════════════════════════════════════
# 2. 类级元守卫（源码 AST）：让「回退交回同一入口」这一类进不来
# ═══════════════════════════════════════════════

# 入口分派的分支登记表：**新增分派分支而不登记 ⇒ 红**（`dispatched == registered` 双向相等）
EXIT_POLICY = {
    # 处理器                     出口策略
    "_handle_page_request": "plain-entry-only",     # 不得调用分派入口
    "_handle_form_request": "plain-entry-only",     # 不得调用分派入口（回退即降级到普通入口）
    "_handle_page_ctx_request": "changed-handoff",  # 可交接，但**不得**交回本处理器自己的 request
}
_PREFIX_LITERALS = ("__PAGE__|", "__FORM__|")
_PAGE_CTX_BRANCH = "page_context is not None"


def _func_node(tree, name):
    """取顶层 async def 的 AST 节点。

    **坐标自证**（§23 G7）：取不到 ⇒ 判据坐标已失效（函数改名/被搬走），**当场炸**，
    绝不静默跳过 —— 否则「判据还在跑」与「判据其实什么都没看」不可区分。
    """
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(
        f"判据坐标失效：{_CHAT_PY.name} 顶层没有 async def {name}（改名/移走 ⇒ 先修判据，再谈结论）"
    )


def _src_of(name):
    return ast.get_source_segment(_SRC, _func_node(_TREE, name))


def _called_names(node):
    return {
        c.func.id for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    }


def _request_param_name(node):
    return node.args.args[0].arg


def _own_request_passthroughs(node):
    """把**本处理器自己的 request** 交回分派入口 `send_message` 的调用行号。

    形态判据（= issue #5451 的病灶）：「退回去重来」的出口若不改变状态，
    入口会按同一个前缀再分派一次 ⇒ 死循环。允许的出口只有两类：
    **换入口**（`_send_plain_message`）或**换状态**（交出的 request 是重建的）。
    """
    request_param = _request_param_name(node)
    hits = []
    for c in ast.walk(node):
        if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)):
            continue
        if c.func.id != "send_message" or not c.args:
            continue
        first = c.args[0]
        if isinstance(first, ast.Name) and first.id == request_param:
            hits.append(c.lineno)
    return hits


def test_every_dispatched_handler_is_registered():
    """入口实际分派到的处理器集合必须**恰好等于**登记表（未登记即红 / 死登记即红）。"""
    sender = _func_node(_TREE, "send_message")
    all_handlers = {
        n.name for n in _TREE.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith("_handle_") and n.name.endswith("_request")
    }
    dispatched = _called_names(sender) & all_handlers

    assert dispatched == set(EXIT_POLICY), (
        f"入口分派集合 {sorted(dispatched)} != 登记表 {sorted(EXIT_POLICY)} —— "
        f"新增分派分支必须同批在 EXIT_POLICY 登记出口策略（未登记即红）"
    )


def test_dispatcher_still_carries_every_prefix_branch():
    """分派分支的字面量必须仍在入口里（防「悄悄摘掉分支」而非改出口）。"""
    sender_src = _src_of("send_message")
    for prefix in _PREFIX_LITERALS:
        assert f'startswith("{prefix}")' in sender_src, f"入口不再按 {prefix} 前缀分派"
    assert _PAGE_CTX_BRANCH in sender_src, "入口不再有页面上下文分支"


def test_no_handler_hands_its_own_request_back_to_dispatcher():
    """**任何**前缀处理器都不得把原文交回分派入口（本单的类级锁）。"""
    offenders = {}
    for handler in EXIT_POLICY:
        node = _func_node(_TREE, handler)
        lines = _own_request_passthroughs(node)
        if lines:
            offenders[handler] = lines

    assert offenders == {}, (
        f"这些处理器把原文交回了分派入口 {offenders} —— 出口不改变状态 ⇒ 入口按同一前缀再分派 ⇒ 递归"
    )


def test_form_handler_exit_is_the_plain_entry_only():
    """`__FORM__` 处理器的出口只能是降级入口（结构上不得出现对分派入口的调用）。"""
    node = _func_node(_TREE, "_handle_form_request")
    called = _called_names(node)

    assert "send_message" not in called, "`_handle_form_request` 仍在调用分派入口 `send_message`"
    assert "_send_plain_message" in called, "`_handle_form_request` 的出口不是降级入口 `_send_plain_message`"


def test_degrade_entry_itself_has_no_prefix_dispatch():
    """降级终点 `_send_plain_message` 自身不含前缀分派（否则降级点又成了新的分派点）。"""
    src = _src_of("_send_plain_message")

    for prefix in _PREFIX_LITERALS:
        assert f'startswith("{prefix}")' not in src, f"降级终点里出现了 {prefix} 前缀分派"
    assert _PAGE_CTX_BRANCH not in src, "降级终点里出现了页面上下文分派"
    assert "send_message(" not in src, "降级终点里出现了对分派入口的调用"


def test_passthrough_checker_flags_the_reproduced_shape():
    """**判据自身的红证（前提自证）**：把修前的原文喂给同一个 checker ⇒ 必须报违规。

    没有这条，「checker 永不报违规」与「真的没有违规」在读数上不可区分（空断言）。
    """
    pre_fix = '''
async def _handle_form_request(request, tenant_id, user_id, current_user):
    if len(request.message) > 2048:
        return await send_message(request, current_user)
    return await send_message(request, current_user)
'''
    broken_node = _func_node(ast.parse(pre_fix), "_handle_form_request")
    law_abiding_node = _func_node(ast.parse('''
async def _handle_form_request(request, tenant_id, user_id, current_user):
    return await _send_plain_message(injected_request, current_user)
'''), "_handle_form_request")

    assert len(_own_request_passthroughs(broken_node)) == 2, "checker 漏报修前形态（红证无效）"
    assert _own_request_passthroughs(law_abiding_node) == [], "checker 误报合规形态"
    # 非空跑：checker 在**真源码**上确实跑过（同一函数、同一入口）
    assert _own_request_passthroughs(_func_node(_TREE, "_handle_form_request")) == []


def test_coordinate_self_check_fails_loudly_when_the_guarded_function_moves():
    """坐标自证（§23 G7）：被守卫的函数改名/移走 ⇒ 判据**当场炸**，不是静默 0 命中放行。"""
    with pytest.raises(AssertionError, match="判据坐标失效"):
        _func_node(_TREE, "_handle_no_such_request")

    # 活着的坐标必须真的取到源码（不是空串/None 也能"通过"）
    assert _src_of("_handle_form_request").lstrip().startswith("async def _handle_form_request("), (
        "取到的源码片段与函数不符 ⇒ 静态层其实什么都没看"
    )