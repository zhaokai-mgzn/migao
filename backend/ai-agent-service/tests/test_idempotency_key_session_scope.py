# case_ids: OR-011, OR-017
"""幂等键必须按**会话**分段（issue #4195，P0 跨会话串单）—— 红证先行。

## 缺陷（值级 + 代码级两重证据）
判定 run `35295494688`（@`d5bca241`）：mibao 腿的 `OR-011` / `OR-014`（两次调用）/ `OR-028`
**都拿到同一张单**（`order_create(replayed=True orderNo=20260918485580004 customerName=张三
customerPhone=13812345678)`），而该单逐字是 **`OR-010` 的 user_inputs**；
xiaobu 腿 `OR-017` / `OR-018` / `OR-019` 同样都拿到别人的单（期望 498/850/704，实测 408/528）。
代码级：`order_create.py` 里 `_window_id(window)` 是**模块级 `lru_cache`、缓存键只有窗口号**
⇒ 同一进程 10 分钟窗内**所有会话的所有写请求共用一个 `X-Client-Request-Id`**，而服务端按
`(tenant_id, clientRequestId)` 去重（admin-api `ClientRequestIdService.claim`）⇒ 第 2 位顾客的
下单被当成第 1 位的重试**回放**：串单，并把**别人的订单号/姓名/手机号**播报给顾客（资金/信任级）。
引入者 = `5c94a315`（#4072 的 F19/F22）；三个调用点：`order_create` / `aftersale_create` /
`human_handoff`（后两者 `from app.tools.order_create import _request_window_id`）。

## 本文件的两条红证 + 一把接线锁（判据各自都能红，见末两个 class）
1. 【红证 1】两个**不同 `session_id`** 的 `ToolContext` ⇒ 键必须**不同**（改前：进程全局 ⇒ 同键）；
2. 【红证 2】**同一** `ToolContext` + 同一窗口 ⇒ 键必须**相同** —— F19 语义
   （「订单已落库但客户端报失败 ⇒ 模型重试 ⇒ 服务端仍只落一单」）不得被这次修复破坏；
3. 【接线锁】三个调用点都必须把本会话的 `ToolContext` 递进**同一入口**（静态判据 + 处方副本红证
   + 经真实工具的端到端头断言）。

## 本单**不**解决（如实登记，见 #4195 第五节）
同一会话 10 分钟窗内的**两笔不同订单**（合法复购）仍会被当成重试吞掉 —— 需按归一化订单事实
指纹（`order_facts_of`，F22 已存在）收窄；把"重试去重"与"内容去重"一次改完会同时动两处语义。
"""
from __future__ import annotations

import ast
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import order_create
from app.tools.aftersale_create import AftersaleCreateTool
from app.tools.base import ToolContext
from app.tools.human_handoff import HumanHandoffTool
from app.tools.order_create import OrderCreateTool

#: 头名是**跨包契约**：admin-api `ClientRequestIdService.HEADER` 逐字同名（改名 = 静默失去去重）。
#: 这里写**字面量**而不是 import 常量：import 会跟着改名一起漂，断言就抓不到契约被破坏。
REQUESTS_HEADER = "X-Client-Request-Id"

SERVICE_DIR = Path(__file__).resolve().parents[1]
APP_DIR = SERVICE_DIR / "app"
KEY_ENTRY = "_request_window_id"
KEY_HELPERS = ("_window_id", "_request_window_id")
#: 三条写路径（每个文件**恰好 1 处**调用入口）：少一处 = 该写路径没有幂等键。
WRITE_PATHS = ("tools/order_create.py", "tools/aftersale_create.py", "tools/human_handoff.py")

#: 钉死的"现在"（1_700_000_000 ≈ 2023-11-14）：幂等键是时间的函数，不钉时钟的断言会在
#: 窗口边界随机红/绿（`_IDEMPOTENCY_WINDOW_SECONDS = 600`，两个断言之间跨窗即假红）。
_NOW = 1_700_000_000.0
_WINDOW = int(_NOW // 600)


def _at(ts: float = _NOW):
    """把 `order_create` 里的"现在"钉在某个重试窗内（该模块只用 `time.time()` 算窗口号）。"""
    return patch("app.tools.order_create.time.time", return_value=ts)


def _ctx(session_id: Optional[str], user_id: str = "u1", tenant_id: int = 1,
         role: str = "customer") -> ToolContext:
    """会话上下文（`role="agent"` 时 `order_create` 不走 SMS 验证码闸门，见 `_order_key`）。"""
    return ToolContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id, role=role)


def _keys_of(*contexts: ToolContext) -> list:
    """在**同一个窗口**里为每个 context 各取一次键（差异只可能来自作用域）。"""
    with _at():
        return [order_create._request_window_id(ctx) for ctx in contexts]


@pytest.fixture(autouse=True)
def _fresh_window_cache():
    """每个用例从空缓存开始：`(窗口, 作用域)` 进缓存键 ⇒ 跨用例残留会让"同键/异键"断言失真。"""
    order_create._window_id.cache_clear()
    yield
    order_create._window_id.cache_clear()


# ──────────────────────────────────────────────────────────────────────────────
# ① 键的作用域：会话（两条红证都在这里）
# ──────────────────────────────────────────────────────────────────────────────

class TestKeyIsScopedToTheSession:
    """`:red_circle:` **红证 1** / `:large_blue_circle:` **红证 2** —— 本单的核心判据。"""

    def test_different_sessions_get_different_keys(self):
        """:red_circle: 【红证 1】两个不同 `session_id` ⇒ 键必须不同。

        改前形态（`_window_id` 缓存键只有窗口号）：同进程同窗内**所有会话共用一个键**
        ⇒ 服务端把 B 的下单当成 A 的重试回放（run `35295494688`：4 条用例都拿到同一张单）。
        """
        key_a, key_b = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_B", "u2"))
        assert key_a != key_b, (
            f"两个不同会话拿到同一个幂等键（{key_a}）⇒ 服务端会把 B 的下单当 A 的重试"
            "**回放别人的订单**（订单号/姓名/手机号全错，资金/信任级）")

    def test_same_user_in_two_sessions_gets_two_keys(self):
        """同一顾客的**两个会话**也必须是两把键 —— 作用域判据只认会话，不认"同一个进程"。"""
        key_1, key_2 = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_B", "u1"))
        assert key_1 != key_2, (
            f"同一顾客的两个会话共用一把键（{key_1}）⇒ 第二个会话的第一单会被当成"
            "第一个会话的重试吞掉（顾客以为下单成功，其实拿的是旧单）")

    def test_three_sessions_in_one_window_get_three_keys(self):
        """run 里的形态是"多条用例一起拿到同一张单" —— 这里是它的最小复现（3 会话 ⇒ 3 键）。"""
        keys = _keys_of(*[_ctx(f"sess_{i}", f"u{i}") for i in range(3)])
        assert len(set(keys)) == 3, f"同窗内 3 个会话只得到 {len(set(keys))} 把键：{keys}"

    def test_same_session_retry_reuses_the_key(self):
        """:large_blue_circle: 【红证 2】同一会话 + 同一窗口 ⇒ 键必须**相同**（F19 语义不变）。

        生产上每一轮都会**重建** `ToolContext`（`chat.py` 按请求构造）⇒ 键必须按**内容**
        （session_id）相等，而不是按对象身份：否则「落库了但报失败」后的模型重试会取到新键
        ⇒ 服务端无从去重 ⇒ 重复下单（F19 治的正是这个）。
        """
        first, retry = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_A", "u1"))
        assert first == retry, (
            f"同一会话的重试拿到不同键（{first} ≠ {retry}）⇒ 服务端去重失效，"
            "「订单已落库但客户端报失败」后的重试会**重复落单**（F19 被这次改动破坏）")

    def test_key_rotates_across_windows_for_the_same_session(self):
        """跨窗必须换新键（R2）：顾客**真的想再下一单**时不能被当成重试吞掉。"""
        ctx = _ctx("sess_A", "u1")
        with _at():
            now_key = order_create._request_window_id(ctx)
        with _at(_NOW + 600 * 2):
            later_key = order_create._request_window_id(ctx)
        assert now_key != later_key, (
            f"跨窗仍是同一把键（{now_key}）⇒ 10 分钟后顾客的合法复购全被当成重试回放")

    def test_key_follows_the_session_not_the_user_row(self):
        """键认**会话**：同一 `session_id` 下 user_id 漂移（匿名→登录/身份补全）不得换键。

        作用域首选 `session_id`（重试的单位是会话），`user_id` 只在会话号缺失时兜底
        —— 否则「落库了但报失败」的重试在身份变化后会被判成新请求，F19 又破。
        """
        before, after = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_A", "u2"))
        assert before == after, (
            f"同一会话内 user_id 变化换了键（{before} ≠ {after}）⇒ 重试被当成新下单")

    def test_session_missing_falls_back_to_user_id(self):
        """会话号缺失 ⇒ 回退 `user_id`：回退口径必须**稳定**（同人同窗同键）且**按人隔离**。"""
        again, other_user = _keys_of(_ctx(None, "u1"), _ctx(None, "u2"))
        same_user = _keys_of(_ctx(None, "u1"))[0]
        assert same_user == again, (
            f"session_id 缺失时回退键不稳定（{same_user} ≠ {again}）⇒ 重试 = 重复落单")
        assert again != other_user, (
            f"session_id 缺失时两个不同 user_id 共用一把键（{again}）⇒ 又跨会话串单")

    def test_no_identity_is_registered_as_the_explicit_fallback(self):
        """缺身份 ⇒ 作用域登记为"无" —— **显式回退**，不是悄悄退回进程全局键。"""
        scopes = [order_create._idempotency_scope(None),
                  order_create._idempotency_scope(_ctx(None, ""))]
        assert scopes == [None, None], (
            f"无身份的作用域是 {scopes}（期望 [None, None]）—— 退回一个可被复用的全局作用域"
            "就是把 #4195 的 P0 又装回去")

    def test_no_identity_never_shares_a_key(self):
        """无身份时的回退口径 = **不去重**（每次一个新键），且与任何身份键都不相同。"""
        first, second, identity_key = _keys_of(
            None, None, _ctx("sess_A", "u1"))
        assert first != second, (
            f"无身份的两次调用共用一把键（{first}）⇒ 正是「进程全局」的旧行为（#4195 的病灶）")
        assert len({first, second, identity_key}) == 3, (
            f"无身份的键撞上了某个会话的键：{[first, second, identity_key]}")


class TestKeyStaysAWireSafeHeaderValue:
    """键要进 HTTP 头 + 服务端 `client_request_keys.client_request_id VARCHAR(128)`。"""

    def test_the_header_name_is_the_server_side_wire_contract(self):
        assert order_create.CLIENT_REQUEST_ID_HEADER == REQUESTS_HEADER, (
            f"头名是跨包契约（admin-api `ClientRequestIdService.HEADER`），"
            f"实际 {order_create.CLIENT_REQUEST_ID_HEADER!r} —— 改名即静默失去去重")

    @pytest.mark.parametrize("hostile", [
        "sess_0123456789abcdef",   # 生产形态（`SessionMemory._generate_session_id` → `sess_<16hex>`）
        "会话 一/二",               # 非 ASCII + 空格 + 斜杠：直接进头会抛 Invalid header value
        'a"b;c',                   # 引号/分号：头注入形态
        "x" * 200,                 # 超长：服务端列为 VARCHAR(128)
    ])
    def test_key_is_a_valid_header_value_for_hostile_session_ids(self, hostile):
        key = _keys_of(_ctx(hostile, "u1"))[0]
        assert re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key), (
            f"session_id={hostile!r} 时键是 {key!r} —— 不是合法的 HTTP 头值/超出服务端列宽")
        assert len(key) <= 128, f"键长 {len(key)} 超过服务端 VARCHAR(128)"

    def test_scopes_differing_only_by_punctuation_do_not_collide(self):
        """朴素做法（把非法字符替换成 `-`）会把这三种写法折叠成**同一把键** ⇒ 又跨会话共用。"""
        keys = _keys_of(*[_ctx(s, "u1") for s in ("a-b", "a/b", "a b")])
        assert len(set(keys)) == 3, (
            f"只差一个标点的会话号被折叠成同一把键：{keys} —— 清洗式实现会引入跨会话串单")


class TestF19SurvivesConcurrency:
    """作用域进缓存键后，条目数 ≈ 一个窗口内的活跃会话数 —— 容量不足会**静默**毁掉 F19。"""

    @staticmethod
    def _keys_stay_stable(key_of, window: int, scopes: list) -> bool:
        """同窗内先取一轮（制造多作用域），再回取第一个 —— 值必须没变（= 没被挤出缓存）。"""
        first = {s: key_of(window, s) for s in scopes}
        return key_of(window, scopes[0]) == first[scopes[0]]

    def test_many_sessions_in_one_window_keep_their_keys(self):
        scopes = [f"sess_{i:03d}" for i in range(64)]
        assert self._keys_stay_stable(order_create._window_id, _WINDOW, scopes), (
            "同窗内 64 个会话把先前的条目挤出缓存 ⇒ 重试取到**新键** ⇒ 服务端无从去重"
            "（F19 在并发下静默失效，而单线程小规模测试看不出来）")

    def test_the_stability_predicate_can_go_red_on_a_small_cache(self):
        """:red_circle: 判据自身可红：容量退回 8（改动前的 `maxsize`）⇒ 同一判据必须报「不稳定」。"""
        tiny = lru_cache(maxsize=8)(order_create._window_id.__wrapped__)
        assert self._keys_stay_stable(tiny, _WINDOW, [f"sess_{i:03d}" for i in range(64)]) is False, (
            "小容量缓存下判据仍然「稳定」 ⇒ 上一条断言是空的（它抓不到缓存挤出的形态）")


# ──────────────────────────────────────────────────────────────────────────────
# ② 端到端：三个写路径经真实工具下发的头（红证 1 的端到端形态）
# ──────────────────────────────────────────────────────────────────────────────

def _order_items():
    return [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168, "subtotal": 528.0}]


def _agent_client(price: int = 168):
    """admin-api 替身：商品查询（算料）+ 下单 POST。"""
    client = AsyncMock()

    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": "p1", "name": "遮光窗帘"}], "total": 1}}
        return {"success": True, "data": {
            "id": "p1", "name": "遮光窗帘", "price": price, "basePrice": price,
            "skus": [{"id": "p1-1", "skuCode": "SKU-1", "colorName": "米白", "price": price}]}}

    client.get = AsyncMock(side_effect=_get)
    client.post = AsyncMock(return_value={
        "success": True, "data": {"id": "order-1", "orderNo": "ORD-1", "totalAmount": 528.0}})
    return client


class TestWritePathsSendTheSessionScopedKey:
    """静态接线锁的运行时孪生：**经真实工具**看头（两条会话 ⇒ 两个头；同会话重试 ⇒ 同一个头）。

    ⚠️ 头缺失时两条断言都取到 `None`：`None == None` ⇒ "同会话"那条绿、`None != None` 为假
    ⇒ "两会话"那条红 —— 故"整条幂等键被摘掉"这个改动跑不掉（无需额外的存在性断言）。
    """

    @staticmethod
    async def _order_key(ctx: ToolContext) -> Optional[str]:
        # `role="agent"`（客服代下单）刻意绕开 SMS 验证码闸门：本文件只断言幂等键，
        # 走验证码路径要额外造 OTP 状态，会把"键的作用域"这条判据的噪声放大。
        client = _agent_client()
        with patch("app.tools.order_create.get_admin_api_client", return_value=client):
            result = await OrderCreateTool().execute(
                context=ctx, customer_name="张三", customer_phone="13800138000",
                items=_order_items())
        assert result.success is True, result.message
        return (client.post.await_args.kwargs.get("headers") or {}).get(REQUESTS_HEADER)

    @staticmethod
    async def _aftersale_key(ctx: ToolContext) -> Optional[str]:
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "o1", "orderNo": "ORD-1"}]}})
        client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "t1", "ticketNo": "AS-1"}})
        with patch("app.tools.aftersale_create.get_admin_api_client", return_value=client):
            result = await AftersaleCreateTool().execute(
                context=ctx, order_id="ORD-1", ticket_type="refund", reason="色差")
        assert result.success is True, result.message
        return (client.post.await_args.kwargs.get("headers") or {}).get(REQUESTS_HEADER)

    @staticmethod
    async def _handoff_key(ctx: ToolContext) -> Optional[str]:
        client = AsyncMock()
        client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "t1", "ticketNo": "AS-9"}})
        with patch("app.tools.human_handoff.get_admin_api_client", return_value=client), \
             patch.object(HumanHandoffTool, "_notify_admins",
                          AsyncMock(return_value={"delivered": 1, "error": ""})), \
             patch("app.tools.human_handoff._load_ai_context",
                   AsyncMock(return_value={"summary": "", "messages": []})):
            result = await HumanHandoffTool().execute(context=ctx, reason="顾客要求转人工")
        assert result.success is True, result.message
        # ⚠️ 必须取**首个** POST：转人工后续还会打「通知管理员」「创建人工会话」两个 POST
        return (client.post.await_args_list[0].kwargs.get("headers") or {}).get(REQUESTS_HEADER)

    async def test_order_create_sends_two_keys_for_two_sessions(self):
        with _at():
            key_a = await self._order_key(_ctx("sess_A", "u1", role="agent"))
            key_b = await self._order_key(_ctx("sess_B", "u2", role="agent"))
        assert key_a != key_b, (
            f"下单：两个会话下发了同一个幂等键（{key_a}）⇒ 第二单被回放成第一单")

    async def test_order_create_reuses_the_key_on_retry_in_one_session(self):
        with _at():
            ctx = _ctx("sess_A", "u1", role="agent")
            first = await self._order_key(ctx)
            retry = await self._order_key(ctx)
        assert first == retry, (
            f"下单：同一会话的重试换了键（{first} ≠ {retry}）⇒ 「已落库但报失败」后重试会重复落单")

    async def test_aftersale_create_sends_two_keys_for_two_sessions(self):
        with _at():
            key_a = await self._aftersale_key(_ctx("sess_A", "u1"))
            key_b = await self._aftersale_key(_ctx("sess_B", "u2"))
        assert key_a != key_b, (
            f"售后建单：两个会话下发了同一个幂等键（{key_a}）⇒ 第二张工单被回放成第一张")

    async def test_human_handoff_sends_two_keys_for_two_sessions(self):
        with _at():
            key_a = await self._handoff_key(_ctx("sess_A", "u1"))
            key_b = await self._handoff_key(_ctx("sess_B", "u2"))
        assert key_a != key_b, (
            f"转人工建单：两个会话下发了同一个幂等键（{key_a}）⇒ 第二张工单被回放成第一张")


# ──────────────────────────────────────────────────────────────────────────────
# ③ 接线锁（静态）：判据 = 源码文本的纯函数
# ──────────────────────────────────────────────────────────────────────────────

def app_sources() -> dict:
    """`app/**/*.py` 的源码映射（纯函数输入 ⇒ 注入处方副本即可做红证）。"""
    return {str(p.relative_to(APP_DIR)): p.read_text(encoding="utf-8")
            for p in sorted(APP_DIR.rglob("*.py"))}


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def key_calls(source: str) -> list:
    """源码里 `_request_window_id(...)` 的调用节点。"""
    return [n for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and _callee(n) == KEY_ENTRY]


def wiring_gaps(sources: dict) -> list:
    """接线缺口清单（**空 = 接线成立**）：每个调用点都递了本会话的 `context`，且三条写路径都在册。"""
    gaps: list = []
    for rel in WRITE_PATHS:
        source = sources.get(rel)
        if source is None:
            gaps.append(f"{rel}: 源码缺失 —— 判据的真相源消失（fail-closed）")
            continue
        found = key_calls(source)
        if len(found) != 1:
            gaps.append(
                f"{rel}: `{KEY_ENTRY}` 调用点 {len(found)} 处（期望恰好 1 处）"
                " —— 少了 = 该写路径没有幂等键；多了 = 幂等键口径分裂")
    for rel, source in sorted(sources.items()):
        for call in key_calls(source):
            handed = [ast.unparse(a) for a in call.args]
            if handed != ["context"]:
                gaps.append(
                    f"{rel}:{call.lineno}: `{KEY_ENTRY}` 的实参是 {handed or '（无）'}"
                    "（期望 [`context`]）—— 幂等键必须由**本会话的 ToolContext**决定")
    return gaps


def helper_definition_sites(sources: dict) -> list:
    """`_window_id` / `_request_window_id` 的**定义点**（口径必须单点：第二份实现会各自漂移）。"""
    sites: list = []
    for rel, source in sorted(sources.items()):
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in KEY_HELPERS:
                sites.append(f"{rel}:{node.lineno}:{node.name}")
    return sites


class TestCallSitesGoThroughOneEntryPoint:
    """接线锁：三个调用点都走**同一入口**，且入口**只定义一次**（不新增第二份口径）。"""

    def test_the_sources_are_real(self):
        """fail-closed：读不到源文件 ⇒ 判据空转，宁可红。"""
        sources = app_sources()
        assert len(sources) > 50, f"只读到 {len(sources)} 个 app 源文件 —— 判据会空转（fail-closed）"
        missing = [rel for rel in WRITE_PATHS if rel not in sources]
        assert missing == [], f"三条写路径没读全，缺 {missing}"

    def test_every_call_site_hands_in_the_session_context(self):
        gaps = wiring_gaps(app_sources())
        assert gaps == [], ("接线断了：\n  " + "\n  ".join(gaps)
                            + "\n\n修法：三个调用点都写 `_request_window_id(context)`")

    def test_the_entry_point_has_exactly_one_implementation(self):
        sites = helper_definition_sites(app_sources())
        modules = sorted({s.split(":")[0] for s in sites})
        assert modules == ["tools/order_create.py"], (
            f"幂等键出现第二份实现：{sites} —— 三个调用点必须走同一入口（口径分裂 ⇒ 各自漂移）")
        assert len(sites) == len(KEY_HELPERS), (
            f"幂等键的定义点数量变了（期望 {len(KEY_HELPERS)} 个 = {KEY_HELPERS}）：{sites}")


class TestWiringLockCanGoRed:
    """**:red_circle: 判据自身可红** —— 处方注入源码映射（判据是源码文本的纯函数 ⇒ 注入副本
    ≡ 注入真文件，却零写入归属他人的文件；手法同 `test_self_correct_retry_wiring_lock.py`）。"""

    @staticmethod
    def _mutated(rel: str, old: str, new: str) -> dict:
        sources = app_sources()
        source = sources[rel]
        assert source.count(old) == 1, (
            f"处方锚点 {old!r} 在 {rel} 里出现 {source.count(old)} 次（期望 1 次）"
            " —— 接入点变了，红证夹具必须先对齐（否则是空跑）")
        sources[rel] = source.replace(old, new)
        return sources

    def test_unmutated_sources_pass(self):
        """阴性负例：真源码必须**零缺口**（防恒红 —— 判据不能对真源码也喊狼）。"""
        assert wiring_gaps(app_sources()) == []

    def test_dropping_the_context_argument_is_caught(self):
        gaps = wiring_gaps(self._mutated("tools/human_handoff.py",
                                         f"{KEY_ENTRY}(context)", f"{KEY_ENTRY}()"))
        assert len(gaps) == 1 and "实参" in gaps[0], f"不传 context 未被报出（判据是空的）：{gaps}"

    def test_removing_the_idempotency_header_is_caught(self):
        gaps = wiring_gaps(self._mutated(
            "tools/aftersale_create.py",
            f"CLIENT_REQUEST_ID_HEADER: {KEY_ENTRY}(context),", ""))
        assert any("调用点 0 处" in g for g in gaps), f"整条幂等键被摘掉却未报出：{gaps}"

    def test_missing_source_file_is_caught(self):
        sources = app_sources()
        sources.pop("tools/order_create.py")
        assert any("源码缺失" in g for g in wiring_gaps(sources)), (
            f"真相源消失却静默通过（fail-closed 破了）：{wiring_gaps(sources)}")

    def test_a_second_implementation_is_caught(self):
        sources = self._mutated(
            "tools/aftersale_create.py", "class AftersaleCreateTool",
            f"def {KEY_ENTRY}(context):\n    return 'second-opinion'\n\n\nclass AftersaleCreateTool")
        modules = sorted({s.split(":")[0] for s in helper_definition_sites(sources)})
        assert modules == ["tools/aftersale_create.py", "tools/order_create.py"], (
            f"第二份幂等键实现未被报出：{modules}")


class TestTheTwoRedProofsCanGoRed:
    """**:red_circle: 红证 1/2 的判据自身可红**：把被测行为改坏，`_keys_of` 必须报出改前形态。"""

    def test_the_scope_predicate_reports_the_old_process_global_behaviour(self, monkeypatch):
        """处方 = 改前口径（作用域**进程全局**）⇒ 两个会话必同键（红证 1 因此会红）。"""
        monkeypatch.setattr(order_create, "_idempotency_scope",
                            lambda _context: "process-global")
        key_a, key_b = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_B", "u2"))
        assert key_a == key_b, (
            "处方（进程全局作用域）下两会话竟然仍不同键 ⇒ 红证 1 抓的不是这个形态，判据是空的")

    def test_the_retry_predicate_reports_a_key_that_stops_being_cached(self, monkeypatch):
        """处方 = 去掉缓存（每次新键，等价于"不去重"）⇒ 同一会话的重试必不同键（红证 2 因此会红）。"""
        monkeypatch.setattr(order_create, "_window_id",
                            lambda window, scope: f"{window}-{uuid.uuid4().hex[:12]}")
        first, retry = _keys_of(_ctx("sess_A", "u1"), _ctx("sess_A", "u1"))
        assert first != retry, (
            "处方（每次新键）下同会话重试竟然仍同键 ⇒ 红证 2 抓的不是这个形态，判据是空的")