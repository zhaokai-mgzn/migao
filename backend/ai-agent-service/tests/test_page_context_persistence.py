# case_ids: CH-047
"""页面上下文的**落库隔离**与**回放归一**（issue #7112）。

## 病根

`app/context/page_registry.py` 开篇自己写着「页面上下文是**元数据**，不是用户说的话」——
但注入形态（`render_page_context` 的信封）此前**原样落库**成 `role="user"` 的消息
（`app/api/chat.py::_handle_page_ctx_request` 把它塞进 `request.message`，由
`_send_plain_message` 写入会话历史）⇒ 切走再切回（`selectSession` → `GET /history`）时，
用户气泡里就是**整段内部提示**。同一份文本还喂给了会话自动标题与用户记忆抽取。

## 本文件判什么

| # | 判据 | 判据函数 |
|---|---|---|
| 1 | **落库的是用户原话**（信封只给 LLM 看本轮，不进历史） | `test_plain_chat_persists_user_question_not_envelope` |
| 2 | **入口把两者分开递交**（LLM 文本 ≠ 落库文本） | `test_entry_forwards_both_texts` |
| 3 | **旧行回放只剩问题**（读时归一，不改写历史） | `test_history_endpoint_strips_legacy_envelope` |
| 4 | **LLM 历史里也不再有过期页面提示**（旧行） | `test_agent_history_strips_legacy_envelope` |
| 5 | **剥离是渲染的逆**（登记表每条 route + 降级形态逐条往返） | `test_strip_is_inverse_of_render_for_every_route` |
| 6 | **负控：不吞用户内容**（不像信封就原样） | `test_strip_keeps_user_text_that_only_looks_like_envelope` |

判据 5 是**类级**的：它遍历 `PAGE_REGISTRY` 的**现取**登记面，任何一处渲染形态改动
（新增字段 / 改一句文案）而剥离没跟上 ⇒ 当场红，不依赖「记得同步改第二个地方」。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.schemas import ChatSendRequest
from app.context import page_registry as PR
from app.utils.auth import UserIdentity
from tests.test_chat import _memory, _session

QUESTION = "我想看下当前的生产风险"
#: 信封的开放标记（**判据取模块常量**：不在测试里另写一份字面量）。
OPEN = "黄金策正在用户当前页面上"

MERCHANT_PERMISSIONS = ("order:list", "order:detail", "product:list", "dashboard:view",
                        "production:list", "shipment:list", "stock:list")


def _merchant(permissions=MERCHANT_PERMISSIONS) -> UserIdentity:
    return UserIdentity(
        user_id="user_1", tenant_id=1, identity_type="account",
        role="admin", permissions=list(permissions),
    )


def _registered_context(route: str = "/production", entity_id: Optional[str] = None) -> PR.PageContext:
    ctx = PR.build_page_context(route, entity_id, role="admin", permissions=["*"])
    if not isinstance(ctx, PR.PageContext):  # 前提自证：登记表里没有这条 route ⇒ 靶子不存在
        raise AssertionError(f"前提自证失败：{route} 应当已登记（否则本判据的靶子不存在）")
    return ctx


def _legacy_envelope(route: str = "/production", entity_id: Optional[str] = None) -> str:
    """模拟**旧版本落库**的那一行：注入信封 + 用户原话。"""
    return PR.render_page_context(QUESTION, _registered_context(route, entity_id))


async def _captured_user_message(display_message: Optional[str] = None) -> dict:
    """跑一遍 `_send_plain_message`，返回它落库的 user 消息 kwargs（其余一切 mock 掉）。"""
    from app.api import chat as chat_api

    saved: list[dict] = []

    async def _save_message(**kwargs):
        saved.append(kwargs)
        return "msg_1"

    memory = _memory(get_session=_session())
    memory.save_message = AsyncMock(side_effect=_save_message)
    memory.get_history_by_tokens = AsyncMock(return_value=([], False))

    async def _no_events(**_kwargs):
        return
        yield  # pragma: no cover - 空流（本判据只关心落库那一侧）

    with patch.object(chat_api, "SessionMemory", lambda: memory), \
            patch.object(chat_api, "get_tool_registry", lambda: MagicMock()), \
            patch.object(chat_api, "get_agent", lambda *_a, **_k: MagicMock()), \
            patch.object(chat_api, "_get_user_nickname", AsyncMock(return_value=None)), \
            patch.object(chat_api, "_get_tenant_name", AsyncMock(return_value=None)), \
            patch.object(chat_api, "_agent_stream_to_sse", _no_events), \
            patch("app.agents.agent_router.get_agent_router",
                  lambda: MagicMock(route=lambda _u: "xiaobu")):
        response = await chat_api._send_plain_message(
            ChatSendRequest(session_id="sess_1", message=_legacy_envelope()),
            _merchant(),
            **({} if display_message is None else {"display_message": display_message}),
        )
        # 走完生成器 ⇒ 落库那一侧执行完（本判据不关心流内容，故只收集）
        collected = [chunk async for chunk in response.body_iterator]

    if not saved:  # 前提自证
        raise AssertionError("前提自证失败：`_send_plain_message` 一条 user 消息都没落库")
    return saved[0]


class TestEnvelopeNeverPersisted:
    """① 落库文本 ≠ 注入文本：信封不得成为用户消息。"""

    @pytest.mark.asyncio
    async def test_plain_chat_persists_user_question_not_envelope(self) -> None:
        saved = await _captured_user_message(display_message=QUESTION)
        assert saved["role"] == "user"
        assert saved["content"] == QUESTION, "落库的不是用户原话（信封进了会话历史）"
        assert OPEN not in saved["content"]

    @pytest.mark.asyncio
    async def test_entry_forwards_both_texts(self) -> None:
        """入口必须**同时**递交：LLM 本轮看得到信封，落库只拿原话。"""
        from app.api import chat as chat_api

        forwarded = MagicMock()

        async def _downstream(request, _user, **kwargs):
            forwarded(request.message, **kwargs)
            return MagicMock()

        with patch.object(chat_api, "_send_plain_message", _downstream), \
                patch.object(chat_api, "SessionMemory",
                             lambda: _memory(get_session=_session())):
            await chat_api._handle_page_ctx_request(
                ChatSendRequest(session_id="sess_1", message=QUESTION,
                                page_context={"route": "/production"}),
                tenant_id=1, user_id="user_1", current_user=_merchant(permissions=("*",)),
            )

        assert forwarded.call_count == 1, "入口没把请求交给普通文本路径"
        llm_text = forwarded.call_args.args[0]
        assert OPEN in llm_text and llm_text.endswith(QUESTION), "本轮 LLM 侧丢了页面上下文（功能退化）"
        assert forwarded.call_args.kwargs.get("display_message") == QUESTION, \
            "入口没把「用户原话」递交下去 ⇒ 落库仍会带上信封"


class TestReadBackNormalisation:
    """②③ 旧行回放：展示面与 LLM 历史都不再带信封。"""

    def test_strip_removes_envelope_with_and_without_entity(self) -> None:
        for entity_id in (None, "12345"):
            legacy = _legacy_envelope(entity_id=entity_id)
            assert legacy.endswith(QUESTION)
            assert PR.strip_page_context_envelope(legacy) == QUESTION, f"entity={entity_id}"

    def test_strip_removes_unknown_notice(self) -> None:
        legacy = PR.render_page_context(QUESTION, None)
        assert legacy == PR.PAGE_CONTEXT_UNKNOWN_NOTICE + QUESTION
        assert PR.strip_page_context_envelope(legacy) == QUESTION

    @pytest.mark.asyncio
    async def test_history_endpoint_strips_legacy_envelope(self) -> None:
        from app.api import chat as chat_api

        legacy = _legacy_envelope()
        memory = _memory(
            get_session=_session(),
            get_history=[{
                "id": "m1", "session_id": "sess_1", "role": "user",
                "content": legacy, "content_type": "text",
                "created_at": datetime(2026, 10, 17, 2, 41, tzinfo=timezone.utc),
            }],
        )
        with patch.object(chat_api, "SessionMemory", lambda: memory):
            resp = await chat_api.get_history("sess_1", limit=50, current_user=_merchant())

        messages = resp["data"]["messages"]
        assert messages[0]["content"] == QUESTION, "历史回放仍把页面上下文信封上屏"
        assert "docs/" not in messages[0]["content"], "内部文档路径泄漏到用户可见内容"

    def test_agent_history_strips_legacy_envelope(self) -> None:
        """旧行喂给模型时也要归一：否则一次进页之后**每一轮**都在暗示「用户还在那一页」。"""
        from app.api import chat as chat_api

        history = chat_api._convert_history_to_agent_format([
            {"role": "user", "content": _legacy_envelope()},
            {"role": "assistant", "content": "答"},
        ])
        assert history[0]["content"] == QUESTION
        assert history[1]["content"] == "答", "负控：助手消息不该被改写"

    def test_strip_is_inverse_of_render_for_every_route(self) -> None:
        """类级：登记表里**每条** route（现取）往返必须回到原话。"""
        routes = [e.route for e in PR.PAGE_REGISTRY if "*" not in e.route]
        assert routes, "前提自证失败：登记表为空 ⇒ 本判据没有靶子"
        for route in routes:
            for entity_id in (None, "12345"):
                rendered = PR.render_page_context(
                    QUESTION, PR.build_page_context(route, entity_id, role="admin", permissions=["*"]))
                assert PR.strip_page_context_envelope(rendered) == QUESTION, f"{route} entity={entity_id}"
        # 降级形态（未登记 / C 端 / 无权限）同一条口径
        assert PR.strip_page_context_envelope(PR.render_page_context(QUESTION, None)) == QUESTION

    def test_strip_keeps_user_text_that_only_looks_like_envelope(self) -> None:
        """负控：形态不完整 ⇒ **原样返回**（不吞用户内容）。"""
        cases = (
            QUESTION,
            "",
            # 以同样的句子开头，但不是我们渲染的信封（缺尾部提示 / 缺收尾括号）
            "（黄金策正在用户当前页面上：/production）这个页面是干嘛的？",
            # 正文中间出现（不是开头）⇒ 不动
            QUESTION + "（黄金策正在用户当前页面上：/production）",
        )
        for text in cases:
            assert PR.strip_page_context_envelope(text) == text, f"误伤用户内容：{text!r}"
