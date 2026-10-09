# case_ids: MC-067
"""黄金策**主动新手引导**（issue #5989 · P2）**行为面**判据 —— 真跑 `_handle_page_enter_request`。

## 与哪个判据分工（**不是重复**）

| 面 | 承载体 |
|---|---|
| **静态面**（分派顺序 / 无推送基础设施原语 / 依赖面不许引入 `page_registry` / 键闭集 / 文案无步骤词 / 判定本体必须被调用） | `tests/unit_ci_workflows/test_proactive_onboarding.py` |
| **判定本体**（纯函数：登记表 / 默认拒绝 / 裁剪 / 上限 / 可行动性） | 本文件 `TestDecisionBody`（`build_proactive_push` 真跑） |
| **入口行为**（会话守卫 / 频率上限落点 / 静默流的形状 / 不经 LLM） | 本文件 `TestEntryPoint` |
| **前端只递交、不判定** | `frontend/admin-web/tests/unit/store/chat-proactive-onboarding.test.ts` |

## 用户裁定（2026-10-02，逐字口径）

形态 = **A：对话区 + 首次进页触发** —— 「用户首次进入某个已登记页面时，黄金策在**对话区**主动发
一条**导航提示**」·**每页每会话最多 1 次** · **只推该角色可见的** · **未登记页面不推** ·
**只给导航不给步骤**。

## 明确边界（照实登记，不粉饰）

- 本文件**不判 LLM 行为**：主动提示**不经 LLM**（文案全部来自登记表）⇒ 没有可判的模型自由度；
- **不判前端是否真的在路由变化时调用**：那是 `frontend/admin-web/tests/unit/store/chat-proactive-onboarding.test.ts`
  的事（本文件只判服务端：**递了就必须按口径判**）；
- **子页面不推**是本包的**有意取舍**（严格按 `menu.ts` 菜单节点判定，`/orders/123` 这类非菜单路径
  ⇒ 静默），不是缺陷 —— 见 PR「未覆盖与风险」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.schemas import ChatSendRequest
from app.context import menu_navigator as nav
from app.utils.auth import UserIdentity
from tests.test_chat import _memory, _session

REPO_ROOT = Path(__file__).resolve().parents[3]

#: `data` 键闭集（与静态判据**同一份**口径：`tests/unit_ci_workflows/test_menu_navigator.py` 的
#: `ALLOWED_DATA_KEYS` 是 P1 工具面判据，主动推送的键更多（多 route / proactive）⇒ 这里显式列出）。
PROACTIVE_DATA_KEYS = frozenset(
    {"proactive", "featureId", "label", "route", "capabilities", "citation"}
)


def _merchant(permissions=("product:list",), role: str = "admin") -> UserIdentity:
    return UserIdentity(
        user_id="user_1", tenant_id=1, identity_type="account", role=role,
        permissions=list(permissions),
    )


def _enter(route: str, session_id: Optional[str] = "sess_1") -> ChatSendRequest:
    return ChatSendRequest(
        session_id=session_id,
        message=f"__PAGE_ENTER__|{json.dumps({'route': route})}",
    )


class _FakeStore:
    """`SessionStateStore` 的内存替身（**只**实现本功能用到的 load / commit）。"""

    def __init__(self, state: Optional[dict] = None, commit_ok: bool = True) -> None:
        self.state = state
        self.commit_ok = commit_ok
        self.commits: list[dict] = []

    async def load(self, session_id: str):
        return self.state

    async def commit(self, session_id: str, state: dict) -> bool:
        if not self.commit_ok:
            return False
        self.commits.append(state)
        self.state = state
        return True


async def _call(req: ChatSendRequest, user: UserIdentity, store: _FakeStore) -> tuple[str, Any]:
    """跑真入口，返回（SSE body 原文, store）。"""
    from app.api.chat import _handle_page_enter_request

    with patch("app.api.chat.SessionMemory",
               return_value=_memory(get_session=_session(id="sess_1", customer_id=user.user_id))), \
            patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
            patch("app.api.chat._save_message_or_report", new=AsyncMock(return_value="mid")) as saved:
        response = await _handle_page_enter_request(
            req, tenant_id=1, user_id=user.user_id, current_user=user,
        )
        body = "".join([chunk async for chunk in response.body_iterator])
    _call.last_saved = saved  # type: ignore[attr-defined]
    return body, store


def _text_of(body: str) -> str:
    """从 SSE 原文里取 `event: text` 的 content（没有 text 事件 ⇒ 空串）。"""
    out = []
    for line in body.splitlines():
        if line.startswith("data: ") and '"content"' in line:
            out.append(json.loads(line[len("data: "):])["content"])
    return "".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# 一、判定本体（纯函数，真跑 `build_proactive_push`）
# ══════════════════════════════════════════════════════════════════════════════


class TestDecisionBody:
    def test_criterion_1_per_page_per_session_once(self) -> None:
        """判据 1：**每页每会话最多 1 次** —— 已推过 ⇒ `already_pushed`（且不带 push）。"""
        first = nav.build_proactive_push("/products", ["product:list"])
        assert first.should_push is True
        assert first.push is not None
        again = nav.build_proactive_push(
            "/products", ["product:list"], already_pushed=[first.push.feature_id]
        )
        assert again.should_push is False
        assert again.reason == nav.PUSH_REASON_ALREADY_PUSHED
        assert again.push is None
        # 别的页面不受影响（「每页」各自计数）
        assert nav.build_proactive_push("/knowledge", ["knowledge:view"]).should_push is True

    def test_criterion_2_role_trim(self) -> None:
        """判据 2：**只推该角色可见的** —— 无权 ⇒ `not_visible`（签名里没有 role）。

        ⚠️ 2026-10-09（issue #6580）：宿主路径从 `/production/routings` 换成 `/production`
        —— 前者**已不再是菜单节点**（工艺配置菜单被收拢进「企业基础设置」，见下一条判据），
        对它的推送会被判 `unregistered`（另一条理由），拿它当 `not_visible` 的样本会**测错对象**。
        本判据判的是「已注册但没有该码 ⇒ 不推」，故取一个**仍在菜单里**的路径（生产看板 `/production`）。
        """
        denied = nav.build_proactive_push("/production", ["order:list"])
        assert denied.should_push is False
        assert denied.reason == nav.PUSH_REASON_NOT_VISIBLE
        # 客户端递交的 role 改成什么都一样（裁剪只看 permissions）
        for role in ("admin", "customer", "agent", "warehouse"):
            assert nav.build_proactive_push(
                "/production", ["order:list"]
            ).reason == nav.PUSH_REASON_NOT_VISIBLE, f"role={role!r} 竟拿到页面"
        # 无码节点（通知中心）全员可见
        assert nav.build_proactive_push("/notifications", []).should_push is True
        # 🔴 具名登记：两条**旧功能路径**已随菜单收拢退出导航表 ⇒ 推送理由必须是 `unregistered`
        # （不是 `not_visible`：导航表根本不再认识它们；功能本体在 `/settings` 的域里可达）
        for legacy in ("/production/routings", "/production/processing"):
            assert nav.build_proactive_push(
                legacy, ["production:view"]
            ).reason == nav.PUSH_REASON_UNREGISTERED, f"{legacy} 竟仍被导航表当作已注册路径"

    def test_criterion_3_unregistered_route_is_denied_by_default(self) -> None:
        """判据 3：**未登记页面不推** —— 未登记 / 脏形态 / 歧义一律静默。"""
        for route in (
            "/nope", "/orders/123", "/orders/new", "/knowledge/help",
            "orders", "", "/", None, 123,
            "/products/%E5%BC%A0", "/a/../b", "/a//b",
        ):
            verdict = nav.build_proactive_push(route, ["*"])
            assert verdict.should_push is False, f"{route!r} 竟被推送"
            assert verdict.reason in nav.PUSH_REASONS
            assert verdict.push is None

    def test_criterion_3b_query_string_and_fragment_normalize_to_the_page(self) -> None:
        """对照读数（防「未登记」判据被写宽）：查询串/片段**规范化后同一页** ⇒ 照常可推。"""
        for route in ("/products?tab=1", "/products#anchor", "/products/"):
            verdict = nav.build_proactive_push(route, ["product:list"])
            assert verdict.should_push is True, f"{route!r} 规范化后应当是可推的登记页面"
            assert verdict.push is not None and verdict.push.route == "/products"

    def test_criterion_4_no_steps_structure_and_wording(self) -> None:
        """判据 4：**只给导航不给步骤** —— 结构（键闭集，无 steps）+ 文案（无步骤词）。"""
        step_words = ("第一步", "第二步", "第三步", "步骤如下", "点击", "点一下", "先点",
                      "然后点", "最后点", "按下", "按钮", "输入框", "下拉框", "依次")
        for feature in nav.NAV_FEATURES:
            node = nav.nodes_for_feature(feature.feature_id)[0]
            verdict = nav.build_proactive_push(node.path, ["*"])
            assert verdict.should_push is True, f"{node.path} 应当可推（登记项齐全）"
            payload = verdict.push.to_data()
            assert set(payload) == PROACTIVE_DATA_KEYS, f"{node.path} 的 data 键多了/少了：{sorted(payload)}"
            assert "steps" not in json.dumps(payload, ensure_ascii=False)
            blob = verdict.push.render() + json.dumps(payload, ensure_ascii=False)
            hits = [w for w in step_words if w in blob]
            assert hits == [], f"{node.path} 的主动提示里出现步骤词 {hits}"
            assert "操作步骤不在本轮" in blob, f"{node.path} 缺少「不给步骤」的如实告知"

    def test_criterion_5_actionability(self) -> None:
        """判据 5：**可行动性** —— 「在哪一页」+「这页能做什么」必须都能给出，否则不发。"""
        verdict = nav.build_proactive_push("/shipments", ["order:list"])
        assert verdict.should_push is True
        text = verdict.push.render()
        # 🔴 先钉「两个字段都非空」（否则 `"" in text` **恒真** ⇒ 这条断言永远绿 = 空断言）
        assert verdict.push.label and verdict.push.route, "推送缺「在哪一页」的字段（空串不算给出）"
        assert verdict.push.label in text and verdict.push.route in text, "文案里没有「在哪一页」"
        assert nav.PROACTIVE_CAPABILITY_PREFIX in text, "文案里没有「这页能做什么」"
        assert verdict.push.capabilities, "capabilities 为空 ⇒ 这条推送不该发"
        assert set(verdict.push.to_data()["capabilities"]) == set(verdict.push.capabilities)

    def test_coverage_every_menu_node_has_exactly_one_feature(self) -> None:
        """类级守卫（现取）：`MENU_TREE` 每个导航节点必须**恰好**被一条登记项覆盖。

        没有它：新增一个菜单节点却忘了登记功能 ⇒ 那一页**永远不推**，而没有任何东西会红。
        """
        assert nav.route_feature_coverage_problems() == ()

    def test_signature_has_no_role(self) -> None:
        """越权面（结构化）：判定本体**拿不到** role ⇒ 客户端递交的 role 影响不了裁剪。"""
        import inspect

        params = set(inspect.signature(nav.build_proactive_push).parameters)
        assert params == {"raw_route", "permissions", "already_pushed"}, params


# ══════════════════════════════════════════════════════════════════════════════
# 二、入口行为（真跑 `_handle_page_enter_request`）
# ══════════════════════════════════════════════════════════════════════════════


class TestEntryPoint:
    @pytest.mark.asyncio
    async def test_first_entry_pushes_navigation_and_records_it(self) -> None:
        store = _FakeStore(state=None)
        body, store = await _call(_enter("/products"), _merchant(), store)
        text = _text_of(body)
        assert "商品管理" in text and "/products" in text, body
        assert nav.PROACTIVE_CAPABILITY_PREFIX in text
        assert "登记项 #products" in text
        assert "event: done" in body
        assert store.commits, "推送后必须记账（否则同一页面会被反复推）"
        assert store.state["onboarding_pushed_features"] == ["products"]

    @pytest.mark.asyncio
    async def test_second_entry_in_same_session_is_silent(self) -> None:
        """判据 1 的**入口级**读数：同会话第二次进同一页 ⇒ **一个字符都不发**。"""
        store = _FakeStore(state=None)
        _first, store = await _call(_enter("/products"), _merchant(), store)
        body, _ = await _call(_enter("/products"), _merchant(), store)
        assert _text_of(body) == "", f"第二次进页竟然又推了：{body}"
        assert "event: done" in body, "静默流也必须是合法 SSE（前端才不会卡住）"
        assert len(store.commits) == 1, "第二次不该再记账"

    @pytest.mark.asyncio
    async def test_other_session_still_gets_it(self) -> None:
        """「每页**每会话**」：另一个会话（`state=None`）照样收到。"""
        _b1, _s1 = await _call(_enter("/products"), _merchant(), _FakeStore(state=None))
        body, _ = await _call(_enter("/products"), _merchant(), _FakeStore(state=None))
        assert "商品管理" in _text_of(body)

    @pytest.mark.asyncio
    async def test_role_without_permission_gets_silent_stream(self) -> None:
        store = _FakeStore(state=None)
        body, store = await _call(_enter("/production/routings"), _merchant(["order:list"]), store)
        assert _text_of(body) == ""
        assert store.commits == [], "无权不该记账"

    @pytest.mark.asyncio
    async def test_unregistered_route_gets_silent_stream(self) -> None:
        store = _FakeStore(state=None)
        body, store = await _call(_enter("/definitely-not-a-page"), _merchant(["*"]), store)
        assert _text_of(body) == ""
        assert store.commits == []

    @pytest.mark.asyncio
    async def test_malformed_payload_is_silent_not_500(self) -> None:
        store = _FakeStore(state=None)
        from app.api.chat import PAGE_ENTER_PREFIX, _handle_page_enter_request

        for raw in ("", "not-json", '["a"]', '{"route": 123}'):
            req = ChatSendRequest(session_id="sess_1", message=PAGE_ENTER_PREFIX + raw)
            with patch("app.api.chat.SessionMemory",
                       return_value=_memory(get_session=_session(id="sess_1", customer_id="user_1"))), \
                    patch("app.memory.session_state_store.SessionStateStore", return_value=store):
                response = await _handle_page_enter_request(
                    req, tenant_id=1, user_id="user_1", current_user=_merchant(["*"]),
                )
                body = "".join([c async for c in response.body_iterator])
            assert _text_of(body) == "", f"畸形 payload 竟推了：{raw!r}"

    @pytest.mark.asyncio
    async def test_no_session_is_silent(self) -> None:
        """没有会话 ⇒ 没有对话区可推（**静默**，不建会话 —— 不能靠进页把会话灌满）。"""
        store = _FakeStore(state=None)
        body, _ = await _call(_enter("/products", session_id=None), _merchant(), store)
        assert _text_of(body) == ""
        assert store.commits == []

    @pytest.mark.asyncio
    async def test_closed_session_is_rejected_like_the_other_paths(self) -> None:
        from app.api.chat import _handle_page_enter_request

        with patch("app.api.chat.SessionMemory",
                   return_value=_memory(get_session=_session(id="sess_1", status="closed"))), \
                patch("app.memory.session_state_store.SessionStateStore",
                      return_value=_FakeStore(state=None)):
            with pytest.raises(HTTPException) as e:
                await _handle_page_enter_request(
                    _enter("/products"), tenant_id=1, user_id="user_1", current_user=_merchant(),
                )
        assert e.value.status_code == 409
        assert e.value.detail["error"]["code"] == "SESSION_CLOSED"

    @pytest.mark.asyncio
    async def test_commit_failure_means_no_push(self) -> None:
        """存储写失败 ⇒ **不发**（否则一次故障就退回「每次进页都推」）。"""
        store = _FakeStore(state=None, commit_ok=False)
        body, _ = await _call(_enter("/products"), _merchant(), store)
        assert _text_of(body) == ""
        assert store.commits == [], "写失败不该被当成记账成功"

    @pytest.mark.asyncio
    async def test_pushed_message_is_saved_into_history(self) -> None:
        """推送落进会话历史（用户重开会话时仍能看到这条导航）。"""
        store = _FakeStore(state=None)
        _body, _store = await _call(_enter("/knowledge"), _merchant(["knowledge:view"]), store)
        saved = _call.last_saved  # type: ignore[attr-defined]
        assert saved.await_count == 1, "主动提示应当落库一次（否则历史里没有它）"
        kwargs = saved.await_args.kwargs
        assert kwargs["role"] == "assistant"
        assert kwargs["source"] == "chat.proactive"
        assert "知识库" in kwargs["content"]

    @pytest.mark.asyncio
    async def test_does_not_touch_the_llm_path(self) -> None:
        """**不经 LLM**：入口既不调 `send_message`（Agent 路径），也不像族 4 那样注入上下文。"""
        store = _FakeStore(state=None)
        with patch("app.api.chat.send_message", new=AsyncMock()) as mock_send:
            await _call(_enter("/products"), _merchant(), store)
        mock_send.assert_not_awaited()
