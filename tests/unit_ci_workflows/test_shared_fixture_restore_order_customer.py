# case_ids: OR-007, CU-004, DF-015
"""复位族第二批（issue #4992）的**可判定性**守卫：`order_status_restore` / `customer_profile_restore`。

## 病灶（issue #4992 引用的两处「弱证据」登记）

| 用例 | 写动作 | 首跑之后的世界 | #4992 前的自清理 |
|---|---|---|---|
| `OR-007` | `order_manage(cancel)` 取消 `EVAL-MB-ORD-0002` | 该订单进**终态** `cancelled` | 只能 `namespaces`（弱证据） |
| `CU-004` | `customer_manage(update)` 改手机号 `13800138000→13900001111` | 按种子号**定位不到**该客户 | 只能 `namespaces`（弱证据） |

两处注释都写着「真正的强修法是新增 `<X>_restore` 复位动作（新 type ⇒ 独立 issue）」——
本文件锁的就是那两条动作的**行为**（不是"声明存在"）。

## 与既有守卫的分工（R1：不重复造门）

| 守卫 | 管什么 |
|---|---|
| `tests/unit_ci_workflows/test_eval_preclean_registry.py` | 类型登记表 ↔ 实现分支 ↔ 阶段声明（静态） |
| `tests/unit_ci_workflows/test_shared_fixture_write_restore.py` | **商品夹具属性**的写方必须声明复位（静态）+ 商品复位动作的真实分支 |
| **本文件**（#4992） | **订单状态 / 客户档案**两条复位动作的真实分支：复位真的生效 / 幂等 / **失败可见** |

## 判据（每条都有注入式红证；红证不依赖真实用例库）

1. **复位真的生效**：脏值 ⇒ 动作把值改回给定值（走真实代码路径，零网络 / 零 LLM）。
2. **幂等**：目标当前值已等于复位值 ⇒ 成功返回且**不发写请求**（连跑两遍净效果相同）。
3. **失败可见**（fail-closed，`_clean_not_applied` 的稳定标记 ⇒ 进 `restore_failures` → 阻塞）：
   复位目标缺失 / **复位值缺失** / 值非法 / 写失败 / **回读不符**（2xx ≠ 值已落地，#3807）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。"""
    sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件里的 HTTP 一律走 `_FakeHttpx`")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()

SEED_ORDER_NO = "EVAL-MB-ORD-0002"
SEED_ORDER_STATUS = "confirmed"
SEED_CUSTOMER_PHONE = "13800138000"
SEED_CUSTOMER_NAME = "张三"

ORDER_SPEC = {"type": "order_status_restore",
              "order_no": SEED_ORDER_NO, "status": SEED_ORDER_STATUS}
PROFILE_SPEC = {"type": "customer_profile_restore",
                "customer_keyword": SEED_CUSTOMER_PHONE, "phone": SEED_CUSTOMER_PHONE}


def _all_cases() -> list:
    out = []
    for f in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in doc.get("cases") or []:
            c = dict(c)
            c["__file"] = f.name
            out.append(c)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 一、零网络替身：内存订单库（asyncpg）+ 内存客户库（httpx）
# ══════════════════════════════════════════════════════════════════════════════

class _FakeConn:
    """`asyncpg.Connection` 的最小替身：只认 `_restore_order_status` 用到的那三条 SQL 形态。

    `fail` 是失败注入口（连接层抛错 ⇒ 覆盖「DB 不可达」那一格）。
    `ignore_writes` 是**静默空转**注入口（UPDATE 返回命中但**不落地** ⇒ 只有回读校验抓得到）。
    """

    def __init__(self, orders: dict, calls: list, fail: bool = False, ignore_writes: bool = False):
        self.orders = orders
        self.calls = calls
        self.fail = fail
        self.ignore_writes = ignore_writes

    async def fetchrow(self, sql: str, *args):
        self.calls.append((" ".join(str(sql).split()), args))
        if self.fail:
            raise RuntimeError("注入的 DB 故障")
        if "UPDATE" in sql:
            order_no, want = args[0], args[1]
            if order_no not in self.orders:
                return None
            if not self.ignore_writes:
                self.orders[order_no] = want
            return {"id": f"id-{order_no}"}
        # SELECT status ...
        if args and args[0] in self.orders:
            return {"status": self.orders[args[0]]}
        return None

    async def fetch(self, sql: str, *args):
        self.calls.append((" ".join(str(sql).split()), args))
        return []

    async def close(self):
        return None


class _FakeAsyncpg:
    """`asyncpg` 模块替身（零 DB）：`connect()` 返回 `_FakeConn`。"""

    def __init__(self, orders: dict, calls: list, fail: bool = False, ignore_writes: bool = False):
        self.orders = orders
        self.calls = calls
        self.fail = fail
        self.ignore_writes = ignore_writes

    async def connect(self, *a, **k):        # noqa: N802 —— 与 asyncpg 同名
        return _FakeConn(self.orders, self.calls, self.fail, self.ignore_writes)


def _install_db(monkeypatch, orders=None, **kw) -> tuple:
    """装上 `asyncpg` 替身；返回 `(内存订单库, 调用流水)`。"""
    orders = orders if orders is not None else {SEED_ORDER_NO: SEED_ORDER_STATUS}
    calls: list = []
    monkeypatch.setitem(sys.modules, "asyncpg", _FakeAsyncpg(orders, calls, **kw))
    return orders, calls


class _Resp:
    def __init__(self, payload=None, status_code: int = 200):
        # `_safe_json` 读 `.content`（不是 `.json()`），照它的口径造
        self.content = json.dumps(payload if payload is not None else {}).encode("utf-8")
        self.status_code = status_code


class _CustomerBook:
    """内存客户库（形状照抄 admin-api：列表 `data.items[]` / 详情 `data.profile`）。"""

    def __init__(self, customers=None):
        self.customers = customers if customers is not None else [
            {"id": "cust_eval_zhangsan", "phone": SEED_CUSTOMER_PHONE,
             "wechatNickname": SEED_CUSTOMER_NAME},
        ]
        self.calls: list = []
        self.fail_keys: set = set()
        self.ignore_writes = False

    def by_id(self, cid):
        return next((c for c in self.customers if c["id"] == cid), None)

    def phone(self, cid="cust_eval_zhangsan"):
        return (self.by_id(cid) or {}).get("phone")

    def list_matching(self, keyword: str) -> list:
        kw = str(keyword or "")
        return [c for c in self.customers
                if kw and (kw == c["id"] or kw == str(c.get("phone") or ""))]

    def update(self, cid: str, body: dict) -> bool:
        c = self.by_id(cid)
        if not c:
            return False
        if self.ignore_writes:
            return True
        for k, v in (body or {}).items():
            if v:
                c[k] = v
        return True

    def should_fail(self, method: str, path: str) -> bool:
        return any(m == method and sub in path for m, sub in self.fail_keys)


class _FakeClient:
    def __init__(self, book: _CustomerBook):
        self.book = book

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @staticmethod
    def _path(url) -> str:
        return urlparse(str(url)).path

    async def _handle(self, method: str, url, kw: dict):
        path = self._path(url)
        self.book.calls.append((method, path))
        if self.book.should_fail(method, path):
            return _Resp({}, 500)
        if method == "GET" and path == "/api/admin/customers":
            kwd = str((kw.get("params") or {}).get("keyword") or "")
            return _Resp({"data": {"items": self.book.list_matching(kwd)}})
        if method == "GET" and path.startswith("/api/admin/customers/"):
            cid = path.rstrip("/").rsplit("/", 1)[-1]
            c = self.book.by_id(cid)
            return _Resp({"data": {"id": cid, "profile": c}}, 200 if c else 404)
        if method == "PUT" and path.startswith("/api/admin/customers/"):
            cid = path.rstrip("/").rsplit("/", 1)[-1]
            ok = self.book.update(cid, kw.get("json") or {})
            return _Resp({"data": {}}, 200 if ok else 404)
        return _Resp({}, 404)

    async def get(self, url, **kw):
        return await self._handle("GET", url, kw)

    async def put(self, url, **kw):
        return await self._handle("PUT", url, kw)

    async def post(self, url, **kw):
        return await self._handle("POST", url, kw)

    async def patch(self, url, **kw):
        return await self._handle("PATCH", url, kw)

    async def delete(self, url, **kw):
        return await self._handle("DELETE", url, kw)


class _FakeHttpx:
    """`httpx` 模块替身（零网络）：只提供 runner 用到的 `AsyncClient`。"""

    def __init__(self, book: _CustomerBook):
        self.book = book

    def AsyncClient(self, *a, **k):          # noqa: N802 —— 与 httpx 同名
        return _FakeClient(self.book)


def _run(spec, phase="post"):
    return asyncio.run(lr._run_post_clean("tok", spec) if phase == "post"
                       else lr._run_pre_clean("tok", spec))


def _bad(msg) -> bool:
    """该消息是否会被折进结论（`pre` / `post` 两侧任一）—— 判据用**真实折叠器**，不另写一份。"""
    return bool(lr.check_postclean_not_applied([msg]) or lr.check_preclean_not_applied([msg]))


# ══════════════════════════════════════════════════════════════════════════════
# 二、登记表（静态）：两条动作都在 `_CLEAN_TYPES` 里、都声明 `pre` + `post`
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    NEW_TYPES = ("order_status_restore", "customer_profile_restore")

    def test_both_types_are_registered_for_both_phases(self):
        for t in self.NEW_TYPES:
            meta = lr._CLEAN_TYPES.get(t)
            assert meta, f"{t} 不在 _CLEAN_TYPES 里（声明了没人实现的 type）"
            assert set(meta.get("phases") or ()) == {"pre", "post"}, (
                f"{t} 必须 `pre` + `post` 两侧都能跑（issue #4992 的硬要求）：{meta}")
            assert t in lr._PRECLEAN_TYPES and t in lr._POSTCLEAN_TYPES, meta

    def test_new_types_are_not_in_the_cleanup_family(self):
        """复位族**禁止**落进清理族：目标不存在必须进结论（清理族的"良性 no-op"语义不适用）。"""
        for t in self.NEW_TYPES:
            assert t not in lr._PRECLEAN_CLEANUP_TYPES, (
                f"{t} 被归进清理族 ⇒ 「目标不存在」会被降级成良性 no-op（#4075 的静默复发）")

    def test_new_types_declare_no_product_attr(self):
        """`attr` 留空是**有意**的：订单/客户不是商品夹具属性，编一个会让写面表判「无对应写方」。"""
        for t in self.NEW_TYPES:
            assert lr._CLEAN_TYPES[t]["attr"] == "", lr._CLEAN_TYPES[t]

    def test_or007_and_cu004_declare_the_real_restore(self):
        """**本单的病灶用例**必须声明真复位（`pre` 或 `post` 任一）—— 而不是退回弱证据。"""
        by = {c["id"]: c for c in _all_cases()}
        want = {"OR-007": "order_status_restore", "CU-004": "customer_profile_restore"}
        for cid, t in want.items():
            declared = {str((s or {}).get("type") or "")
                        for f in ("pre_clean", "post_clean")
                        for s in (by[cid].get(f) or [])}
            assert t in declared, f"{cid} 没有声明 {t}（自清理退回弱证据）：{declared}"
            assert not (by[cid].get("namespaces") or []), (
                f"{cid} 仍留着 `namespaces` 弱证据 ⇒ 不再需要的声明就是死账（issue #4992 硬要求）")

    def test_case_library_does_not_use_undeclared_restore_values(self):
        """用例库声明的两条复位动作必须带齐**定位键 + 复位值**（缺一 ⇒ 运行期必红，配置错误）。

        这是"声明层"的红证：动作本身的 fail-closed 由下面第三/四节证明。
        """
        by = {c["id"]: c for c in _all_cases()}
        for cid in ("OR-007", "CU-004"):
            for field in ("pre_clean", "post_clean"):
                for spec in (by[cid].get(field) or []):
                    t = str((spec or {}).get("type") or "")
                    if t == "order_status_restore":
                        assert spec.get("order_no"), f"{cid}.{field} 缺 order_no：{spec}"
                        assert spec.get("status"), f"{cid}.{field} 缺 status：{spec}"
                    elif t == "customer_profile_restore":
                        assert spec.get("customer_keyword"), f"{cid}.{field} 缺 customer_keyword：{spec}"
                        assert spec.get("phone"), f"{cid}.{field} 缺 phone：{spec}"


# ══════════════════════════════════════════════════════════════════════════════
# 三、`order_status_restore` 的真实分支
# ══════════════════════════════════════════════════════════════════════════════

class TestOrderStatusRestore:
    def test_restores_the_order_status(self, monkeypatch):
        """**走真实分支**：OR-007 首跑把订单取消成 `cancelled`（终态）⇒ 复位回种子值。"""
        orders, calls = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        msg = _run(ORDER_SPEC)
        assert orders[SEED_ORDER_NO] == SEED_ORDER_STATUS, f"复位没生效：{orders} / msg={msg!r}"
        assert any("UPDATE" in sql for sql, _ in calls), calls
        assert not _bad(msg), msg
        assert "回读一致" in msg, msg

    def test_is_idempotent(self, monkeypatch):
        """**幂等**：本就是种子值 ⇒ 成功，且**不发** UPDATE（连跑两遍净效果相同）。"""
        orders, calls = _install_db(monkeypatch)
        msg = _run(ORDER_SPEC)
        assert orders[SEED_ORDER_NO] == SEED_ORDER_STATUS
        assert not any("UPDATE" in sql for sql, _ in calls), f"幂等时不该发写请求：{calls}"
        assert not _bad(msg), msg
        assert "本就" in msg, f"幂等路径的文案必须点明「本就等于目标值」：{msg!r}"

    def test_two_consecutive_runs_end_at_the_same_state(self, monkeypatch):
        """**可重复执行**（issue #4992 的验收判据①）：连跑两遍 ⇒ 净效果相同。"""
        orders, _ = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        _run(ORDER_SPEC)
        after_first = orders[SEED_ORDER_NO]
        _run(ORDER_SPEC)
        assert after_first == orders[SEED_ORDER_NO] == SEED_ORDER_STATUS

    def test_missing_order_is_visible(self, monkeypatch):
        """**红证（复位目标缺失）**：点名的订单不在库里 ⇒ 稳定标记 ⇒ 进结论。"""
        _install_db(monkeypatch, {})
        msg = _run(ORDER_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert _bad(msg), "目标缺失没有被折进结论（静默）"

    def test_missing_status_is_visible(self, monkeypatch):
        """**红证（复位值缺失）**：spec 缺 `status` ⇒ 稳定标记 ⇒ 进结论（不许猜默认值）。"""
        _install_db(monkeypatch)
        msg = _run({"type": "order_status_restore", "order_no": SEED_ORDER_NO})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "缺 `status`" in msg, msg
        assert _bad(msg)

    def test_missing_order_no_is_visible(self, monkeypatch):
        """**红证（定位键缺失）**：spec 缺 `order_no` ⇒ 稳定标记 ⇒ 进结论。"""
        _install_db(monkeypatch)
        msg = _run({"type": "order_status_restore", "status": SEED_ORDER_STATUS})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "缺 `order_no`" in msg, msg

    def test_invalid_status_value_is_visible(self, monkeypatch):
        """**红证（值非法）**：状态机不认的值必须在**写库之前**红（写进去只会更脏）。"""
        orders, calls = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        msg = _run({**ORDER_SPEC, "status": "shipping"})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert orders[SEED_ORDER_NO] == "cancelled", "非法值竟然被写进库了"
        assert not any("UPDATE" in sql for sql, _ in calls), calls

    def test_db_unreachable_is_visible(self, monkeypatch):
        """**红证（DB 不可达）**：连接/查询抛错 ⇒ 稳定标记（不是静默跳过）。"""
        _install_db(monkeypatch, fail=True)
        msg = _run(ORDER_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "DB 不可达" in msg, msg

    def test_silent_noop_is_caught_by_the_readback(self, monkeypatch):
        """**本仓库踩过的形态**（#3807）：UPDATE 命中但**值没落地** ⇒ 必须被回读抓住。"""
        orders, _ = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"}, ignore_writes=True)
        msg = _run(ORDER_SPEC)
        assert orders[SEED_ORDER_NO] == "cancelled", "替身没按注入语义工作（测试自身失效）"
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), f"静默空转被当成成功：{msg!r}"
        assert "未生效" in msg, msg

    def test_pre_phase_failure_lands_in_the_pre_channel(self, monkeypatch):
        """阶段化归因：`pre` 的失败走 `_PRECONDITION_NOT_APPLIED`（不是 post 的标记）。"""
        _install_db(monkeypatch, {})
        msg = _run(ORDER_SPEC, phase="pre")
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED), msg
        assert lr.check_preclean_not_applied([msg]) == [msg]

    def test_success_wording_avoids_the_reset_failure_wording(self, monkeypatch):
        """措辞红线（#3751）：成功路径不得含「未复位」/「失败」（`_reset_for_retry` 据此判不等价）。"""
        _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        msg = _run(ORDER_SPEC)
        assert "未复位" not in msg and "失败" not in msg, msg


# ══════════════════════════════════════════════════════════════════════════════
# 四、`customer_profile_restore` 的真实分支
# ══════════════════════════════════════════════════════════════════════════════

def _install_book(monkeypatch, book: _CustomerBook) -> _CustomerBook:
    monkeypatch.setattr(lr, "httpx", _FakeHttpx(book))
    return book


class TestCustomerProfileRestore:
    def test_restores_the_written_phone(self, monkeypatch):
        """**走真实分支**：CU-004 写出的 `13900001111` ⇒ 复位回种子号（含回读校验）。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        msg = _run({**PROFILE_SPEC, "customer_keyword": "13900001111"})
        assert book.phone() == SEED_CUSTOMER_PHONE, f"复位没生效：{book.phone()} / msg={msg!r}"
        assert ("PUT", "/api/admin/customers/cust_eval_zhangsan") in book.calls, book.calls
        assert not _bad(msg), msg
        assert "回读一致" in msg, msg

    def test_is_idempotent(self, monkeypatch):
        """**幂等**：本就是种子值 ⇒ 成功，且**不发** PUT。"""
        book = _install_book(monkeypatch, _CustomerBook())
        msg = _run(PROFILE_SPEC)
        assert not [c for c in book.calls if c[0] == "PUT"], f"幂等时不该发写请求：{book.calls}"
        assert not _bad(msg), msg
        assert "本就" in msg, msg

    def test_two_consecutive_runs_end_at_the_same_state(self, monkeypatch):
        """**可重复执行**（验收判据①）：写脏 → 复位 → 再复位 ⇒ 净效果相同。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        _run({**PROFILE_SPEC, "customer_keyword": "13900001111"})
        after_first = book.phone()
        _run(PROFILE_SPEC)
        assert after_first == book.phone() == SEED_CUSTOMER_PHONE

    def test_restores_the_name_when_given(self, monkeypatch):
        """可选 `name`（= `wechatNickname` 列）：给了就一起复位（与工具别名口径同一份）。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["wechatNickname"] = "李四"
        msg = _run({**PROFILE_SPEC, "name": SEED_CUSTOMER_NAME})
        assert book.by_id("cust_eval_zhangsan")["wechatNickname"] == SEED_CUSTOMER_NAME, msg
        assert not _bad(msg), msg

    def test_missing_target_is_visible(self, monkeypatch):
        """**红证（复位目标缺失）**：按定位键查不到客户 ⇒ 稳定标记 ⇒ 进结论。"""
        _install_book(monkeypatch, _CustomerBook(customers=[]))
        msg = _run(PROFILE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "不存在" in msg, msg
        assert _bad(msg)

    def test_missing_phone_value_is_visible(self, monkeypatch):
        """**红证（复位值缺失）**：spec 缺 `phone` ⇒ 稳定标记（不许静默 no-op）。"""
        book = _install_book(monkeypatch, _CustomerBook())
        msg = _run({"type": "customer_profile_restore", "customer_keyword": SEED_CUSTOMER_PHONE})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "缺 `phone`" in msg, msg
        assert not [c for c in book.calls if c[0] == "PUT"], "缺复位值时不该发写请求"

    def test_missing_keyword_is_visible(self, monkeypatch):
        """**红证（定位键缺失）**：spec 缺 `customer_keyword` ⇒ 稳定标记。"""
        _install_book(monkeypatch, _CustomerBook())
        msg = _run({"type": "customer_profile_restore", "phone": SEED_CUSTOMER_PHONE})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "缺 `customer_keyword`" in msg, msg

    def test_ambiguous_target_is_visible(self, monkeypatch):
        """**失败可见**：同一手机号命中多位 ⇒ 不瞎改（fail-closed，且消息里给出修法）。"""
        book = _install_book(monkeypatch, _CustomerBook(customers=[
            {"id": "c1", "phone": SEED_CUSTOMER_PHONE, "wechatNickname": "张三"},
            {"id": "c2", "phone": SEED_CUSTOMER_PHONE, "wechatNickname": "张三"},
        ]))
        msg = _run(PROFILE_SPEC)
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "不唯一" in msg, msg
        assert not [c for c in book.calls if c[0] == "PUT"], "目标不唯一时不该写"

    def test_write_failure_is_visible(self, monkeypatch):
        """**失败可见**：写端点 500 ⇒ 标记进结论（不是静默）。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        book.fail_keys.add(("PUT", "/api/admin/customers/"))
        msg = _run({**PROFILE_SPEC, "customer_keyword": "13900001111"})
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), msg
        assert "500" in msg, msg

    def test_silent_noop_is_caught_by_the_readback(self, monkeypatch):
        """写 2xx 但**值没落地**（#3807 的静默空转形态）⇒ 必须被回读抓住。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        book.ignore_writes = True
        msg = _run({**PROFILE_SPEC, "customer_keyword": "13900001111"})
        assert book.phone() == "13900001111", "替身没按注入语义工作（测试自身失效）"
        assert msg.startswith(lr._POSTCLEAN_NOT_APPLIED), f"2xx 但值未落地被当成成功：{msg!r}"
        assert "未生效" in msg, msg

    def test_pre_phase_failure_lands_in_the_pre_channel(self, monkeypatch):
        """阶段化归因：`pre` 的失败走 `_PRECONDITION_NOT_APPLIED`。"""
        _install_book(monkeypatch, _CustomerBook(customers=[]))
        msg = _run(PROFILE_SPEC, phase="pre")
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED), msg
        assert lr.check_preclean_not_applied([msg]) == [msg]

    def test_success_wording_avoids_the_reset_failure_wording(self, monkeypatch):
        """措辞红线（#3751）：成功路径不得含「未复位」/「失败」。"""
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        msg = _run({**PROFILE_SPEC, "customer_keyword": "13900001111"})
        assert "未复位" not in msg and "失败" not in msg, msg


# ══════════════════════════════════════════════════════════════════════════════
# 五、结论层：复位失败**阻塞**（不是一行日志）—— 两条动作都走同一条通道
# ══════════════════════════════════════════════════════════════════════════════

class TestRestoreFailureReachesTheVerdict:
    def test_completion_verdict_blocks_on_order_restore_failure(self, monkeypatch):
        """**红证**：订单复位失败 ⇒ 结论阻塞（`restore_failures`），**即使用例本身满分**。"""
        _install_db(monkeypatch, {})
        msg = _run(ORDER_SPEC)
        v = lr.completion_verdict(
            [{"case_id": "OR-007", "score": 1.0, "classification": "pass", "restore": [msg]}], ())
        assert v["ok"] is False, f"复位失败没让结论失败（静默）：{v}"
        assert v["restore_failures"] == ["OR-007"], v

    def test_completion_verdict_blocks_on_profile_restore_failure(self, monkeypatch):
        """**红证**：客户档案复位失败 ⇒ 结论阻塞。"""
        _install_book(monkeypatch, _CustomerBook(customers=[]))
        msg = _run(PROFILE_SPEC)
        v = lr.completion_verdict(
            [{"case_id": "CU-004", "score": 1.0, "classification": "pass", "restore": [msg]}], ())
        assert v["ok"] is False, v
        assert v["restore_failures"] == ["CU-004"], v

    def test_success_does_not_block(self, monkeypatch):
        """负例：复位成功（无标记）⇒ **不得**阻塞（否则判据变成恒红）。"""
        _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        msg = _run(ORDER_SPEC)
        v = lr.completion_verdict(
            [{"case_id": "OR-007", "score": 1.0, "classification": "pass", "restore": [msg]}], ())
        assert v["ok"] is True and v["restore_failures"] == [], v


# ══════════════════════════════════════════════════════════════════════════════
# 六、端到端接线：`_run_clean_specs` 真的会跑这两条动作（`pre` 与 `post` 两侧）
# ══════════════════════════════════════════════════════════════════════════════

class TestWiringThroughRunCleanSpecs:
    def test_post_phase_restores_both_fixtures(self, monkeypatch):
        """两条动作都在 `post` 阶段被 `_run_clean_specs` 调度（声明有消费）。"""
        orders, _ = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        msgs = asyncio.run(lr._run_clean_specs(
            "tok", [ORDER_SPEC, {**PROFILE_SPEC, "customer_keyword": "13900001111"}], "post"))
        assert orders[SEED_ORDER_NO] == SEED_ORDER_STATUS, msgs
        assert book.phone() == SEED_CUSTOMER_PHONE, msgs
        assert lr.check_postclean_not_applied(msgs) == [], msgs

    def test_pre_phase_restores_both_fixtures(self, monkeypatch):
        """`pre` 阶段同样可跑（issue #4992 要求两条都登记 `pre` + `post`）。"""
        orders, _ = _install_db(monkeypatch, {SEED_ORDER_NO: "cancelled"})
        book = _install_book(monkeypatch, _CustomerBook())
        book.by_id("cust_eval_zhangsan")["phone"] = "13900001111"
        msgs = asyncio.run(lr._run_clean_specs(
            "tok", [ORDER_SPEC, {**PROFILE_SPEC, "customer_keyword": "13900001111"}], "pre"))
        assert orders[SEED_ORDER_NO] == SEED_ORDER_STATUS, msgs
        assert book.phone() == SEED_CUSTOMER_PHONE, msgs
        assert lr.check_preclean_not_applied(msgs) == [], msgs

    def test_pre_only_type_declared_in_post_is_a_config_error(self):
        """阶段声明是**硬约束**：`pre` 专属类型在 `post` 里声明 ⇒ 配置错误（不是静默执行）。"""
        msg = asyncio.run(lr._run_post_clean("tok", {"type": "employee_remove",
                                                     "employee_name": "王五"}))
        assert msg.startswith(lr._POSTCLEAN_CONFIG_ERR), msg
