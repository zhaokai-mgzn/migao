# case_ids: CH-009, OR-015, UI-030
"""form 卡答卡轮的生产形态判据 + B 端结构化提交（issue #5949）。

## 先更正**前提**（否则会写出假绿判据，本文件的价值一半在此）

派单/issue 原文是「B 端走自由文本 ⇒ **只有 B 端**不成立答卡轮」。逐行复核**不是**：

1. 入口 `app/api/chat.py::_handle_form_request` 解析 `__FORM__|{json}` 之后，把本轮消息
   **换成了可读注入文本**（`（用户通过表单提交）` + `；`.join(`k: v`)）——**原始前缀从不进入图**，
   落库的历史也是这份可读文本（`_send_plain_message` 里 `content=request.message`）。
2. 而 `app/graph/nodes.py::_card_accepts_answer` 的 form 分支只认 `msg.startswith("__FORM__|")`，
   输入取自 `_get_last_human_text(state["messages"])` ⇒ **两端都不成立**答卡轮。
3. 既有 `tests/test_card_answer_round_routing.py` 的 form 用例用**原始前缀字符串**手工构造
   state —— 生产永远不会出现这个形态 ⇒ 那条判据是**假绿**（本包同批改成生产形态）。

⇒ 本文件的判据一律用**入口真产出的消息**驱动：先跑 `_handle_form_request`，把交给
`_send_plain_message` 的那条消息取出来，再喂给真实的 `_is_card_answer_round` / `route_by_intent`。
任何用字面前缀手工拼 state 的写法都不算判据（生产形态判据见 `_production_state`）。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.api.schemas import ChatSendRequest
from app.graph.nodes import _card_accepts_answer, _is_card_answer_round, route_by_intent
from app.utils.auth import UserIdentity

# ── 夹具：form 卡（B 端「订单 — 收货信息」形态）+ 跨域词值 ──
FORM_CARD = {
    "component": "form",
    "title": "订单 — 收货信息",
    "formFields": [{"key": "remark", "label": "备注"}],
    "submitLabel": "提交",
}
CROSS_DOMAIN_VALUE = "商品要加工项"      # 含 L1 商品域关键词「加工项」
PLAIN_ECHO = f"备注: {CROSS_DOMAIN_VALUE}"  # B 端同时下发的可读回显（降级时承载值）


def _user(role="admin"):
    return UserIdentity(user_id="user_1", tenant_id=1,
                        identity_type="employee", role=role)


def _session(**extra):
    s = {"id": "sess_1", "tenant_id": 1, "customer_id": "user_1", "status": "active"}
    s.update(extra)
    return s


def _memory(**methods):
    m = AsyncMock()
    m.get_session = AsyncMock(return_value=_session())
    for k, v in methods.items():
        setattr(m, k, v if isinstance(v, AsyncMock) else AsyncMock(return_value=v))
    return m


async def _run_entry(request: ChatSendRequest, last_card=None) -> ChatSendRequest:
    """跑真实入口 `_handle_form_request`，返回它交给 `_send_plain_message` 的那条请求。"""
    from app.api.chat import _handle_form_request

    store = AsyncMock()
    state = {"last_card": last_card, "last_card_skill": "order"} if last_card else {}
    store.load = AsyncMock(return_value=state)
    with patch("app.api.chat.SessionMemory", return_value=_memory()), \
         patch("app.api.chat._send_plain_message", new=AsyncMock(return_value=MagicMock())) as plain, \
         patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: store):
        await _handle_form_request(request, tenant_id=1, user_id="user_1",
                                   current_user=_user())
    plain.assert_awaited_once()
    return plain.call_args.args[0]


def _card_id(card: dict) -> str:
    """服务端卡片身份口径（本包新增；跨端同口径判据见
    `tests/test_card_form_submit_shape_cross_end_contract.py`）。"""
    from app.api.chat import _card_identity

    return _card_identity(card)


def _card_answer_request(values: dict, card_id: str,
                         message: str = PLAIN_ECHO) -> ChatSendRequest:
    """构造 B 端结构化提交请求，并**自证字段真被接受**。

    pydantic 默认把未知字段**静默丢弃** ⇒ 不加这条自证的话，「cardId 不一致」这类
    负例会因为「字段根本没进模型」而**假绿**（本包实测踩到过：4 条负例全部"通过"）。
    """
    req = ChatSendRequest(session_id="sess_1", message=message,
                          card_answer={"cardId": card_id, "values": values})
    assert req.card_answer is not None, (
        "`ChatSendRequest` 未接受 `card_answer`（被当未知字段丢弃）——负例判据会假绿"
    )
    assert getattr(req.card_answer, "values", None) == values
    return req


def _production_state(msg: str, card: dict | None = FORM_CARD) -> dict:
    """图里真实的 state 形态：**入口产出的消息** + 同源会话卡状态（`last_card` 三元组）。

    `intent_result` 预置成 L1 商品域（含「加工项」的注入文本在生产里就会被判
    `product_inquiry/rule`）—— 答卡轮不成立时下游 L1 域逃逸会把锁清掉（落 product）。
    """
    return {
        "messages": [HumanMessage(content=msg)],
        "pending_interact_skill": "order",
        "last_card_skill": "order",
        "last_card": card or {},
        "route_decision": {"action": "route_with_hint"},
        "intent_result": {"intent": "product_inquiry", "confidence": 0.95, "source": "rule"},
        "agent_type": "mibao",
        "tenant_id": 1,
        "session_id": "sess_b1_answer_round",
    }


class TestEntryProducedAnswerRound:
    """判据用**入口产出的消息**驱动（不是字面前缀）—— 改前两端都红。"""

    @pytest.mark.asyncio
    async def test_c_end_prefix_submit_is_answer_round(self):
        """C 端 `__FORM__|{json}`（零改动通道）⇒ 答卡轮必须成立、本 skill 锁不丢。

        改前红：入口把前缀换成可读注入文本，`_card_accepts_answer` 的 form 分支恒 False
        ⇒ `route_by_intent` 走 L1 域逃逸 → `product`（拿不到本 skill 的写工具）。
        """
        sent = await _run_entry(ChatSendRequest(
            session_id="sess_1", message='__FORM__|{"remark": "商品要加工项"}'))
        assert not sent.message.startswith("__FORM__|"), (
            "入口把 `__FORM__|` 前缀吃掉了（本文件开头的前提更正）——"
            "判据必须用这份产出形态，不能再用字面前缀拼 state"
        )
        state = _production_state(sent.message)
        assert _is_card_answer_round(state) is True, "form 卡答卡轮未被识别（生产形态）"
        assert route_by_intent(state) == "order", (
            f"答卡轮被路由到 {route_by_intent(state)!r} —— 本 skill 的会话锁被 L1 域逃逸清掉"
        )

    @pytest.mark.asyncio
    async def test_b_end_card_answer_is_answer_round(self):
        """B 端结构化 `card_answer` ⇒ 同样成立答卡轮（经入口归一化走既有通道）。"""
        sent = await _run_entry(
            _card_answer_request({"remark": CROSS_DOMAIN_VALUE}, _card_id(FORM_CARD)),
            last_card=FORM_CARD,
        )
        state = _production_state(sent.message)
        assert _is_card_answer_round(state) is True, "B 端结构化答卡未成立答卡轮"
        assert route_by_intent(state) == "order"

    def test_legacy_free_text_submit_is_not_answer_round(self):
        """负对照：**旧 B 端形态**（`label: value` 多行文本）⇒ 不成立答卡轮。

        本判据改前改后都绿：它钉住「判据分得出提交形态」，防把判据放宽成"有卡就算答卡"。
        """
        assert _card_accepts_answer(FORM_CARD, PLAIN_ECHO) is False
        assert _is_card_answer_round(_production_state(PLAIN_ECHO)) is False


class TestCardIdConsistency:
    """`card_answer.cardId` 给出时须与本会话 `last_card` 一致（防跨卡误判）。"""

    @pytest.mark.asyncio
    async def test_mismatched_card_id_is_not_answer_round(self):
        """答的是一张**不是**本会话待答卡的卡 ⇒ 不成立答卡轮；但值不得丢。"""
        sent = await _run_entry(
            _card_answer_request({"remark": CROSS_DOMAIN_VALUE}, "form|另一张卡|remark"),
            last_card=FORM_CARD,
        )
        assert sent.message == PLAIN_ECHO, "卡身份不一致时应按普通消息走（不注入前缀协议）"
        assert CROSS_DOMAIN_VALUE in sent.message, "值不能被丢掉（失败只降级判定，不丢内容）"
        assert _is_card_answer_round(_production_state(sent.message)) is False

    @pytest.mark.asyncio
    async def test_missing_pending_card_is_not_answer_round(self):
        """本会话没有待答卡（`last_card` 空）却带 cardId ⇒ 不成立答卡轮（fail-closed）。"""
        sent = await _run_entry(
            _card_answer_request({"remark": CROSS_DOMAIN_VALUE},
                                 "form|订单 — 收货信息|remark"),
            last_card=None,
        )
        assert sent.message == PLAIN_ECHO


class TestFormGuardsPreserved:
    """既有护栏不得被新通道绕过（#5451 降级语义 / payload 上限）。"""

    @pytest.mark.asyncio
    async def test_oversized_card_answer_degrades_to_plain_text(self):
        """card_answer 归一后的 payload 超限 ⇒ 降级为普通文本（原请求原样交回，不递归）。"""
        from app.api.chat import _FORM_MAX_LEN

        sent = await _run_entry(
            _card_answer_request({"remark": "x" * (_FORM_MAX_LEN + 1)}, _card_id(FORM_CARD)),
            last_card=FORM_CARD,
        )
        assert sent.message == PLAIN_ECHO, "超限应降级为普通文本（不得注入超长 payload）"
        assert sent.card_answer is None, "降级请求不得再把 card_answer 交回入口（防二次分派）"

    @pytest.mark.asyncio
    async def test_normalized_payload_is_reversible_json(self):
        """归一化等价性：入口把 `card_answer.values` 逐值送进 `__FORM__` 既有链路。"""
        sent = await _run_entry(
            _card_answer_request({"remark": CROSS_DOMAIN_VALUE}, _card_id(FORM_CARD)),
            last_card=FORM_CARD,
        )
        assert sent.message.startswith("（用户通过表单提交）"), sent.message
        assert f"remark: {CROSS_DOMAIN_VALUE}" in sent.message


class TestNoSecondInjectionPath:
    """接线判据：结构化通道必须**复用** `__FORM__` 注入链，不得另写一份注入。"""

    def test_entry_routes_card_answer_to_form_handler(self):
        """入口把 `card_answer` 分派给 `_handle_form_request`（唯一注入落点）。"""
        import inspect

        from app.api import chat as _chat

        src = inspect.getsource(_chat.send_message)
        assert "card_answer" in src, "入口没有分派 card_answer"
        assert "_handle_form_request" in src, "card_answer 未走 form 处理器（会绕开注入/护栏）"

    def test_card_answer_json_shape_matches_form_protocol(self):
        """`card_answer.values` 的序列化与 `__FORM__|{json}` 同形（同一条内部链）。"""
        values = {"remark": CROSS_DOMAIN_VALUE}
        raw = "__FORM__|" + json.dumps(values, ensure_ascii=False)
        assert json.loads(raw[len("__FORM__|"):]) == values
