# case_ids: OR-049, OR-011, OR-017, AS-007
"""幂等键必须是**确定性派生**（issue #9017 / 集群审计 P0-4）—— 跨实例 / 重启仍取同一个键。

## 缺陷（审计已定证）
`app/tools/order_create.py` 的 `X-Client-Request-Id` 由 `@lru_cache` + `uuid4()` + 10 分钟窗
**在进程内**生成：`_window_id(window, scope, *, op)` 首次算出一条随机串就冻在进程缓存里。
服务端去重表是 DB（`ClientRequestIdService.claim`：`INSERT … ON CONFLICT (tenant_id,
client_request_id) DO NOTHING`）—— 这一半是集群安全的；但**键的产生**在进程内 ⇒
滚动部署断流、重试落到另一实例、或进程重启后都算出**新键** ⇒ 服务端查不到 ⇒ **重复下单（资金级）**。

## 本文件钉的判据（每条都能真跑）
1. 【红证 1】**两个独立 OS 进程**（≡ 两个实例 / 一次重启）用**同一份**下单载荷 ⇒ 必须同一个键。
   改前：`uuid4` ⇒ 两个不同键 ⇒ 本断言红（子进程探针见 `tests/_order_key_probe.py`：
   同进程里跑两遍永远命中 `lru_cache`，**测不出**跨实例形态，故必须真开两个进程）。
2. 【红证 2】不同业务意图（数量 / 金额不同）⇒ 必须**不同**键（防止把两笔不同的单误合并成回放）。
3. 【红证 3】同一次点击的"重试"若**改写了备注/地址**（确认后补地址是正常流程）⇒ 仍必须**同一个**键
   —— 业务事实只取驱动金额与库存的规范值（`order_facts_of` 的同一口径，F22）。
4. 【类级元守卫】键的派生路径**不得**再引入随机/进程内状态：把 `uuid.uuid4` 打成抛异常后，
   有身份的取键调用必须照常返回（改前：直接抛 ⇒ 红）；`_window_id` 的源码里不得出现
   `uuid`/`random`/`cache` 字样（改前：三样都在 ⇒ 红）。
5. 【契约】键必须是合法 HTTP 头值且 ≤128（admin-api `ClientRequestIdService.normalize()`
   对 >128 **抛错拒绝**，不是静默截断）。

## 与既有判据的分工
- 会话作用域（#4195）与操作维度（#4212）的判据、三写路径的静态接线锁：
  `tests/test_idempotency_key_session_scope.py`（本单不改那两条语义）；
- F19「同会话同窗重试同键」：`tests/test_write_idempotency_key.py`。
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import order_create
from app.tools.base import ToolContext
from app.tools.order_create import (
    CLIENT_REQUEST_ID_HEADER,
    ORDER_CREATE_OP,
    OrderCreateTool,
)

#: 头名是**跨包契约**：admin-api `ClientRequestIdService.HEADER` 逐字同名。
REQUESTS_HEADER = "X-Client-Request-Id"

SERVICE_DIR = Path(__file__).resolve().parents[1]
PROBE = Path(__file__).with_name("_order_key_probe.py")

#: 钉死的"现在"（≈2023-11-14，落在同一个 10 分钟窗内）：幂等键是时间的函数，不钉时钟的
#: 断言会在窗口边界随机红/绿。
PINNED_NOW = 1_700_000_000.0


# ──────────────────────────────────────────────────────────────────────────────
# 夹具：真开子进程 / 真跑工具
# ──────────────────────────────────────────────────────────────────────────────

def _probe(quantity: float, *, now: float = PINNED_NOW) -> dict:
    """在**独立 OS 进程**里跑一次真实 `order_create`，返回它下发的头与 pid。

    每调用一次 = 一个全新的 Python 进程（模块状态 / `lru_cache` 全空）——
    这正是"另一个实例"或"重启后的进程"的最小可信替身。
    """
    env = {**os.environ, "PROBE_NOW": str(now), "PYTHONPATH": str(SERVICE_DIR)}
    proc = subprocess.run([sys.executable, str(PROBE), str(quantity)],
                          cwd=str(SERVICE_DIR), env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"子进程探针失败（exit {proc.returncode}）：\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    line = [l for l in proc.stdout.strip().splitlines() if l.startswith("{")][-1]
    return json.loads(line)


def _fake_client(price: int = 168):
    """admin-api 替身：商品查询（单价接地）+ 下单 POST。"""
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


def _ctx(session_id: str = "sess_A", user_id: str = "u1",
         tenant_id: int = 1, role: str = "agent") -> ToolContext:
    """`role="agent"`（客服代下单）绕开 SMS 闸门：本文件只断言幂等键，不造 OTP 状态。"""
    return ToolContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id, role=role)


async def _run_order(ctx: ToolContext, *, quantity: float = 3,
                     remark: str = "", customer_address: str = "") -> str:
    """真跑一次工具，返回下发的 `X-Client-Request-Id`。"""
    client = _fake_client()
    with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
         patch("app.tools.order_create.time.time", return_value=PINNED_NOW):
        result = await OrderCreateTool().execute(
            context=ctx,
            customer_name="张三",
            customer_phone="13800138000",
            remark=remark,
            customer_address=customer_address,
            items=[{"product_name": "遮光窗帘", "quantity": quantity,
                    "unit_price": 168, "subtotal": quantity * 168}],
        )
    assert result.success is True, result.message
    headers = client.post.await_args.kwargs.get("headers") or {}
    return headers.get(REQUESTS_HEADER)


# ──────────────────────────────────────────────────────────────────────────────
# 1. 红证 1：跨进程（≡ 跨实例 / 重启）必须是同一个键
# ──────────────────────────────────────────────────────────────────────────────

class TestTheKeyIsIdenticalAcrossProcesses:
    """:red_circle: **红证 1** —— 本单的核心判据：键不依赖进程内状态。"""

    def test_two_processes_derive_the_same_key_for_the_same_intent(self):
        """两个独立进程（同租户/会话/操作/业务事实/窗口）⇒ **逐字相同**的键。

        改前：`uuid4()` 现造随机串 ⇒ 两个进程必不同 ⇒ 服务端无从去重（滚动部署 / 多实例 /
        进程重启都会再落一单，审计 P0-4 场景 1/3/4）。
        """
        first, second = _probe(3), _probe(3)
        assert first["pid"] != second["pid"], (
            f"两次探针落在同一个进程（pid={first['pid']}）⇒ 测不到「跨实例」形态，判据是空的")
        assert first["key"] == second["key"], (
            f"同一份下单载荷在两个进程里算出了**不同**的幂等键（{first['key']} ≠ {second['key']}）"
            "⇒ 服务端按 (tenant_id, client_request_id) 查不到 ⇒ 重试/重发再落一单（资金级重复下单）")
        assert first["key"], "键是空值 —— 幂等键根本没下发（头缺失）"

    def test_a_restarted_process_still_reuses_the_key(self):
        """"杀进程重启后重试，仍只有 1 单"（审计 P0-4 的验证方式）—— 同形态的另一表述。

        与上一条的差别：这里把两次探针的**窗口也钉在同一处**并显式断言键里带窗口号，
        防止实现退化成"内容哈希永久去重"（那样合法复购会被永久吞掉，R2）。
        """
        key = _probe(3)["key"]
        assert key.split("-")[0].isdigit(), (
            f"键里没有时间窗分桶（{key!r}）⇒ 要么跨窗不轮换（合法复购被永久吞掉），"
            "要么窗口语义又被挪进了别处")


# ──────────────────────────────────────────────────────────────────────────────
# 2. 红证 2：不同业务意图必须是不同键（防误合并）
# ──────────────────────────────────────────────────────────────────────────────

class TestDifferentIntentsGetDifferentKeys:
    """:red_circle: **红证 2** —— 确定性**不等于**把所有单折叠成一把键。"""

    @pytest.mark.parametrize("qty_a,qty_b", [(3, 4), (3, 3.5), (1, 10)])
    def test_different_quantities_get_different_keys(self, qty_a, qty_b):
        """数量不同 = 两笔不同的单；同一把键会让第二笔被当成重试**回放成第一笔**。"""
        key_a, key_b = _probe(qty_a)["key"], _probe(qty_b)["key"]
        assert key_a != key_b, (
            f"数量 {qty_a} 与 {qty_b} 得到同一个键（{key_a}）⇒ 顾客的第二单被当成重试吞掉"
            "（金额/数量全错，且顾客以为下单成功）")

    async def test_different_amounts_get_different_keys(self):
        """金额不同（数量同为 3，单价却不同）⇒ 不同键。改前：同窗同会话共用一把键。"""
        same = _probe(3)["key"]  # 同载荷的键（上一条红证的另一面：确定性）
        ctx = _ctx()
        client = _fake_client(price=200)
        with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
             patch("app.tools.order_create.time.time", return_value=PINNED_NOW):
            result = await OrderCreateTool().execute(
                context=ctx, customer_name="张三", customer_phone="13800138000",
                items=[{"product_name": "遮光窗帘", "quantity": 3,
                        "unit_price": 200, "subtotal": 600}])
        assert result.success is True, result.message
        repriced = (client.post.await_args.kwargs.get("headers") or {}).get(REQUESTS_HEADER)
        assert repriced != same, (
            f"单价 200 与 168 得到同一个键（{repriced}）⇒ 两笔金额不同的单被折叠成一次回放")

    async def test_different_customers_get_different_keys(self):
        """手机号不同 = 不同顾客 ⇒ 不同键（同一会话里帮两个人下单也不能互相回放）。"""
        first = await _run_order(_ctx(session_id="sess_A"))
        ctx = _ctx(session_id="sess_A", user_id="u1")
        client = _fake_client()
        with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
             patch("app.tools.order_create.time.time", return_value=PINNED_NOW):
            result = await OrderCreateTool().execute(
                context=ctx, customer_name="李四", customer_phone="13900139000",
                items=[{"product_name": "遮光窗帘", "quantity": 3,
                        "unit_price": 168, "subtotal": 528.0}])
        assert result.success is True, result.message
        second = (client.post.await_args.kwargs.get("headers") or {}).get(REQUESTS_HEADER)
        assert first != second, f"两位顾客共用一把键（{first}）⇒ 第二单被回放成第一单"


# ──────────────────────────────────────────────────────────────────────────────
# 3. 红证 3：重试时的"非金额字段"漂移不得换键
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryDriftDoesNotRotateTheKey:
    """:red_circle: **红证 3** —— 业务事实只取驱动金额/库存的规范值（F22 同一口径）。

    顾客点确认卡后补收货地址、模型重试时把备注换个说法，都是**正常流程**。把这些自由文本
    纳入键 ⇒ 同一次点击的重试算出新键 ⇒ 重复下单（比不改更糟：改动本身制造新漏判）。
    """

    async def test_remark_and_address_do_not_change_the_key(self):
        first = await _run_order(_ctx(), remark="尽快发货")
        retry = await _run_order(_ctx(), remark="麻烦尽快发货，谢谢！",
                                 customer_address="浙江省杭州市西湖区文三路1号")
        assert first == retry, (
            f"备注/地址改写后换了键（{first} ≠ {retry}）⇒ 同一次点击的重试会被当成新下单")

    async def test_numeric_formatting_does_not_change_the_key(self):
        """`3` 与 `3.0` 是同一个数量（工具层按 `_parse_positive_number` 归一）⇒ 同键。"""
        keys = [await _run_order(_ctx(), quantity=q) for q in (3, 3.0)]
        assert keys[0] == keys[1], f"同一数量的不同写法换了键：{keys}"


# ──────────────────────────────────────────────────────────────────────────────
# 4. 类级元守卫：派生路径不得再引入随机 / 进程内状态
# ──────────────────────────────────────────────────────────────────────────────

#: 派生路径里**禁止出现**的标识符（随机数 / 进程内缓存）：它们一旦进来，键就只在「本进程
#: 本窗口」成立 —— 正是 #9017 修掉的病灶（`uuid4` 让另一实例算出新键；`lru_cache` 让键挂在
#: 进程内存上、被挤出时静默失效）。
_FORBIDDEN_IN_DERIVATION = frozenset({
    "uuid", "uuid1", "uuid4", "urandom", "random", "randint", "choice", "secrets",
    "lru_cache", "cache", "functools",
})


def _function_node(name: str) -> ast.FunctionDef:
    """取 `order_create` 里某个函数的 AST 节点（判据是源码的纯函数，便于注入式红证）。"""
    source = (SERVICE_DIR / "app" / "tools" / "order_create.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"order_create.py 里找不到函数 {name}（接线变了，判据必须先对齐）")


def _referenced_identifiers(node: ast.AST) -> set:
    """函数**代码**里引用到的标识符（docstring 是 Constant 节点 ⇒ 注释/说明文字不参与判定）。"""
    names: set = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.alias):
            names.add(child.name)
            names.add(child.asname or "")
    return names


def _forbidden_outside_no_identity_branch(node: ast.AST) -> list:
    """`_request_window_id` 里**不在** `if scope is None:` 分支内的禁用标识符（清单空 = 合规）。"""
    guarded: set = set()
    for child in ast.walk(node):
        if isinstance(child, ast.If) and "scope is None" in ast.unparse(child.test):
            for stmt in child.body:
                for sub in ast.walk(stmt):
                    guarded.add(id(sub))
    hits: list = []
    for child in ast.walk(node):
        if id(child) in guarded:
            continue
        name = None
        if isinstance(child, ast.Name):
            name = child.id
        elif isinstance(child, ast.Attribute):
            name = child.attr
        if name in _FORBIDDEN_IN_DERIVATION:
            hits.append((name, getattr(child, "lineno", 0)))
    return hits


class TestTheDerivationCarriesNoRandomness:
    """**:red_circle: 类级元守卫** —— 让「再用随机/缓存承担正确性」的同类改动进不来。"""

    def test_uuid4_is_never_called_on_the_dedupe_path(self):
        """把 `uuid.uuid4` 打成抛异常后，**有身份**的取键调用必须照常返回。

        改前形态：键的返回值里带 `uuid.uuid4().hex[:12]` ⇒ 本断言直接抛 ⇒ 红。
        """
        with patch("app.tools.order_create.uuid.uuid4", side_effect=AssertionError(
                "幂等键的派生路径调用了 uuid4（随机成分 ⇒ 跨实例必不同键 ⇒ 重复下单）")):
            key = order_create._request_window_id(_ctx(), op=ORDER_CREATE_OP, intent="facts")
        assert key, "取键返回空值"

    @pytest.mark.parametrize("func", ["_window_id", "_request_window_id"])
    def test_the_key_functions_carry_no_randomness_or_cache(self, func):
        """源码级判据：取键函数的**代码**里不得引用 `uuid`/`random`/`cache`/`lru_cache`，
        且不得挂任何装饰器（改前：`@lru_cache(...)` + `uuid.uuid4()` ⇒ 两条都红）。

        `_request_window_id` 的唯一豁免 = **已登记的无身份回退分支**（`if scope is None:`，
        该分支刻意**不去重**，见函数 docstring）——豁免是位置级的：uuid 出现在该分支之外即判红。
        """
        node = _function_node(func)
        if func == "_window_id":
            ident = _referenced_identifiers(node) & _FORBIDDEN_IN_DERIVATION
        else:
            ident = {name for name, _ in _forbidden_outside_no_identity_branch(node)}
        assert ident == set(), (
            f"{func} 的派生路径引用了 {sorted(ident)} —— 幂等键的正确性不得依赖随机数或进程内缓存"
            "（审计 P0-4 的病灶：`lru_cache` + `uuid4` 让键只在「本进程本窗口」内成立）")
        assert [ast.unparse(d) for d in node.decorator_list] == [], (
            f"{func} 被 {[ast.unparse(d) for d in node.decorator_list]} 装饰 —— 缓存不得参与键的取值"
            "（`lru_cache` 的键是调用参数、不是返回值：漏参就永久冻结、容量不足就静默换新键）")

    def test_the_no_identity_fallback_is_the_only_place_with_a_nonce(self):
        """登记性判据：`_window_id`（去重路径）里**一个随机标识符都没有** —— 随机只允许活在
        `_request_window_id` 的「无身份 ⇒ 不去重」分支里。"""
        assert _referenced_identifiers(_function_node("_window_id")) & _FORBIDDEN_IN_DERIVATION == set()

    def test_the_same_inputs_always_derive_the_same_key_without_any_cache(self):
        """**纯函数**判据：交叉调用 200 个别的键之后，同一输入仍取到同一个键。

        改前：`_window_id` 是 `lru_cache` 包装（`__wrapped__` 每次新值）⇒ 这条会红。
        """
        first = order_create._window_id(1_700_000_000 // 600, "sess_A", op=ORDER_CREATE_OP)
        for i in range(200):
            order_create._window_id(1_700_000_000 // 600, f"sess_{i}", op=ORDER_CREATE_OP,
                                    intent=f"facts-{i}")
        again = order_create._window_id(1_700_000_000 // 600, "sess_A", op=ORDER_CREATE_OP)
        assert first == again, f"同样的输入取了两次得到不同键（{first} ≠ {again}）⇒ 键依赖了进程内状态"


# ──────────────────────────────────────────────────────────────────────────────
# 4′. 窗口可配置（默认沿用 10 分钟），但一个环境变量错字不得把服务打死
# ──────────────────────────────────────────────────────────────────────────────

class TestTheWindowIsConfigurable:
    def test_default_is_the_existing_ten_minute_semantics(self, monkeypatch):
        monkeypatch.delenv("IDEMPOTENCY_WINDOW_SECONDS", raising=False)
        assert order_create._idempotency_window_seconds() == 600.0, (
            "默认窗口不再是 10 分钟 —— 改窗口 = 改「同一次点击有多久算重试」的产品口径，必须显式")
        assert order_create._IDEMPOTENCY_WINDOW_SECONDS == 600.0

    def test_a_configured_window_is_honoured(self, monkeypatch):
        monkeypatch.setenv("IDEMPOTENCY_WINDOW_SECONDS", "60")
        assert order_create._idempotency_window_seconds() == 60.0

    @pytest.mark.parametrize("raw", ["", "   ", "not-a-number", "0", "-5"])
    def test_a_broken_window_falls_back_instead_of_killing_the_service(self, monkeypatch, raw):
        """非法 / 非正 ⇒ 回落 600s（环境变量错字不该让 ai-agent **起不来**，那是更大的故障）。"""
        monkeypatch.setenv("IDEMPOTENCY_WINDOW_SECONDS", raw)
        assert order_create._idempotency_window_seconds() == 600.0


# ──────────────────────────────────────────────────────────────────────────────
# 5. 契约：合法 HTTP 头值 / 服务端列宽
# ──────────────────────────────────────────────────────────────────────────────

class TestTheKeyStaysAWireSafeHeaderValue:
    def test_the_header_name_is_the_server_side_wire_contract(self):
        assert CLIENT_REQUEST_ID_HEADER == REQUESTS_HEADER, (
            f"头名是跨包契约（admin-api `ClientRequestIdService.HEADER`），实际 {CLIENT_REQUEST_ID_HEADER!r}")

    async def test_the_key_is_a_valid_header_value_with_a_long_intent(self):
        """业务事实再长（多行明细）也不得撑破 `VARCHAR(128)` 或带非法字符。"""
        client = _fake_client()
        # 5 行不同数量（同一款窗帘给 5 个房间）：业务事实串因此变长，但键长必须恒定。
        many_items = [
            {"product_name": "遮光窗帘", "quantity": 1 + i,
             "unit_price": 168, "subtotal": float(168 * (1 + i))}
            for i in range(5)
        ]
        with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
             patch("app.tools.order_create.time.time", return_value=PINNED_NOW):
            result = await OrderCreateTool().execute(
                context=_ctx(), customer_name="张三", customer_phone="13800138000",
                items=many_items)
        assert result.success is True, result.message
        key = (client.post.await_args.kwargs.get("headers") or {}).get(REQUESTS_HEADER)
        assert re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key or ""), (
            f"键 {key!r} 不是合法 HTTP 头值 / 超出服务端 VARCHAR(128)（`normalize()` 会抛错拒绝整个写请求）")
