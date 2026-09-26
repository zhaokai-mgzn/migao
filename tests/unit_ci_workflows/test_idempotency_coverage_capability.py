# case_ids: OR-049, OR-050, AS-010
"""幂等的**行为层覆盖能力**（issue #4074）：`retry_same_session` + 两个幂等 `db_verify` fetch。

## 缺口是什么（为什么必须补的是"能力"而不是"再多写一条断言"）

`orders` / `after_sales_tickets` 上**没有** `client_request_id` 列（去重键在基础设施表
`client_request_keys`，见 `backend/admin-api/src/main/resources/db/migration-archive/V50__create_client_request_keys.sql`），
所以「同键重试没有产生第二张单据」这件事**只有两条路**能判：

1. **制造一次真实的同键重试**（同会话内把同一次逻辑写请求再发一遍）——而 runner 原先
   **结构上做不到**：它自带的失败重试走 `get_or_create_session(..., prefer_new=True)`
   （换会话 ⇒ 换键 ⇒ 恰好绕过被测的那一格，issue #4195 的核验评论逐字点名）；
2. **把两次写调用的产出放在一起判**（张数 / 是否回放 / 是否同一会话）——原 `db_verify`
   的每个 fetch 都只取 `_first_successful_data`（**首个**成功调用）⇒ 看不见第二次。

本文件钉住 ①②两条能力的**接线与判别力**（零 LLM、零网络、零 DB —— #4262）。

## 本文件钉住什么

| # | 判据 | 红证方向（注入即红，见 PR body 的红证表） |
|---|---|---|
| 1 | `retry_same_session` 真被消费：两轮写调用发在**同一会话** | 抹掉 `run_case` 的 `__retry__` 分支 ⇒ 只发 1 轮 ⇒ 只 1 次成功 |
| 2 | **可达性下界**：`must_succeed[min_successes: 2]` 在"模型没真重发"时判红 | 把 `min_successes` 从白名单/判定里去掉 ⇒ 该格变绿（假绿） |
| 3 | `db_verify[order_by_client_request_id]` 三条一起判（同会话 / 有回放 / 张数） | 去掉任一条 ⇒ 对应的坏形态不再判红 |
| 4 | 声明形态 fail-closed（`calls<2` / `max<calls` / 未知键 / 非 dict） | 去掉检查 ⇒ 恒红或恒绿的用例静默通过 |
| 5 | 三条新用例真的**装载得进来**（YAML → `EvalCase`，声明不丢） | 该回归是"声明只在 yml 里、CI 走另一条路径"的同款假绿 |

## 与既有守卫的分工（不复制第二份口径）

- 断言**配置形状**（缺 `expect_rows` / `expect_replayed` 非 bool）由
  `tests/unit_ci_workflows/test_assertion_specs_wellformed.py` 的 `SUPPORTED_DB_FETCH`
  与形状判据在 PR 阶段左移；本文件只钉**运行期**的 fail-closed（配置非法不得空转通过）。
- 轮次声明形态的**通用**判据（控制轮写成 JSON 字符串）仍在 `check_control_turns_declared`，
  本文件不复制。
"""
import asyncio
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 runner；无 httpx 时用替身（CI 的 helper job 只装 pytest+pyyaml，见 `eval_case_filter` 的由来）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()
import render_cases  # noqa: E402
from eval_cases import Difficulty, EvalCase, Skill  # noqa: E402

SID = "sess_stub_4074"
ORDER_NO = "EVAL-IDEM-ORD-9001"
TICKET_NO = "AS-20260926-9001"
TENANT_ORDER_ID = "a1b2c3d4-e5f6-4a7b-8c9d-000000000001"


# ── 假栈：产品侧**幂等行为**的忠实模型（同会话第二次写请求 ⇒ 回放首次结果）────────────
class _IdempotentStack:
    """模型的是**产品真实行为**（不是为测试编的行为）：
    服务端按 `(tenant_id, client_request_id)` 原子占位（`INSERT … ON CONFLICT DO NOTHING`），
    同键第二次到达 ⇒ 不再执行，回放首次结果并把 `replayed=true` 写进 payload
    （`backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java`）。

    `retry=0` 建模**模型没有真的重发**（只口头说"已提交成功"）—— 这是本单要判红的形态，
    不是"另一个产品的行为"。
    """

    def __init__(self, tool="order_create", retries=1):
        self.tool = tool
        self.retries = retries            # 允许"重发"的轮数（= 假栈会被诱导发出的写请求数）
        self.writes = 0
        self.sent = []
        self.sessions_used = []
        self.replayed = []

    #: 会触发写请求的话术（顾客点单 / 转述"提交失败请重试"要求重发）。
    #: ⚠️ **空文本不触发**：这一格是"声明无消费"的红证前提 —— 若 runner 不消费
    #: `retry_same_session`（把它当普通 dict 轮 ⇒ 发出空文本），模型**不会**凭空再写一次。
    TRIGGERS = ("下单", "提交", "重试", "再试")

    async def send_message(self, token, session_id, message, images=None, **_kw):
        self.sent.append(message)
        self.sessions_used.append(session_id)
        asked = any(t in str(message) for t in self.TRIGGERS)
        if asked and (self.writes == 0 or self.writes <= self.retries):
            return self._write_round(message, images)
        return self._round(message, images, final_text="这笔已经提交过了，无需重复提交")

    def _write_round(self, message, images):
        self.writes += 1
        is_replay = self.writes > 1                    # 同键 ⇒ 第二次起是回放
        self.replayed.append(is_replay)
        data = self._payload(is_replay)
        return self._round(message, images, final_text="已为您提交", data=data)

    def _payload(self, is_replay):
        if self.tool == "order_create":
            data = {"id": ORDER_NO, "orderNo": ORDER_NO, "customerName": "张三"}
        else:
            data = {"id": TICKET_NO, "ticketNo": TICKET_NO, "ticketType": "refund",
                    "orderId": TENANT_ORDER_ID, "status": "pending"}
        if is_replay:
            data["replayed"] = True
        return data

    def _round(self, message, images, final_text, data=None):
        calls = [{"name": self.tool, "args": {"action": "create"}}] if data else []
        results = [{"tool": self.tool, "result": {"success": True, "data": data}}] if data else []
        return {"user_message": message, "images": images or [], "tool_calls": calls,
                "tool_results": results, "interactive": [], "final_text": final_text,
                "error": None, "streamed": True, "done": True}


async def _no_case_issues(token, case):
    """`check_debug_user_precondition` 的替身（它会发 HTTP；本文件零网络）。"""
    return []


def _use_stack(monkeypatch, stack):
    monkeypatch.setattr(lr, "send_message", stack.send_message)
    monkeypatch.setattr(lr, "check_debug_user_precondition", _no_case_issues)
    monkeypatch.setattr(lr, "ROUND_SLEEP", 0)
    return stack


def _case(user_inputs, must_succeed=None, db_verify=None, output_verify=None,
          expectations=None):
    return EvalCase(
        id="STUB-4074", title="同会话同键重试（stub 驱动）", skill=Skill.GENERAL,
        difficulty=Difficulty.EDGE,
        user_inputs=list(user_inputs),
        expectations=(expectations if expectations is not None else ["order_create"]),
        data_checks=[],
        must_succeed=list(must_succeed or []),
        db_verify=list(db_verify or []),
        output_verify=list(output_verify or []),
    )


def _retry_turn(tool="order_create", calls=2, mx=3, fallback="刚才没提交成功，你再提交一次"):
    return {"retry_same_session": {"tool": tool, "calls": calls, "max": mx},
            "fallback": fallback}


def _trace(calls, tool="order_create"):
    """合成轨迹：`calls = [(round, session_epoch, ok, data), …]` → runner 的逐轮结果形状。"""
    rounds = {}
    for rnd, epoch, ok, data in calls:
        r = rounds.setdefault(rnd, {"__round": rnd, "__session_epoch": epoch,
                                   "tool_calls": [], "tool_results": []})
        r["tool_calls"].append({"name": tool, "args": {"action": "create"}})
        r["tool_results"].append({"tool": tool, "result": {"success": ok, "data": data}})
    return [rounds[k] for k in sorted(rounds)]


def _same_order(n, replayed_from=1, ref=ORDER_NO):
    """n 次成功调用都指向**同一张**单据；第 `replayed_from` 次起带 `replayed=true`。

    这就是同键重试的**正确产出**（首次创建 + 之后回放同一张）——
    与 `_two_orders`（换新键 ⇒ 真的落了两张）是两种必须能分辨的形态。
    """
    return [(i + 1, 0, True,
             dict({"id": ref, "orderNo": ref}, **({"replayed": True} if i >= replayed_from else {})))
            for i in range(n)]


def _two_orders():
    """两次成功调用指向**两张不同**的单据、且都不是回放（重复落库的形态）。"""
    return [(1, 0, True, {"id": ORDER_NO + "-A", "orderNo": ORDER_NO + "-A"}),
            (2, 0, True, {"id": ORDER_NO + "-B", "orderNo": ORDER_NO + "-B"})]


# ── ① 能力被消费：两轮写调用发在**同一会话** ────────────────────────────────────
class TestRetrySameSessionIsConsumed:
    def test_two_writes_land_in_the_same_session(self, monkeypatch):
        """幂等键 = f(窗, **会话**, 操作) ⇒ 「同会话」是这一格成立的前提，必须可机器核对。"""
        stack = _use_stack(monkeypatch, _IdempotentStack(retries=1))
        case = _case(user_inputs=["帮我下单，遮光窗帘 3 米", _retry_turn()],
                     must_succeed=[{"tool": "order_create", "min_successes": 2}])
        run = asyncio.run(lr.run_case(case, "", SID))

        assert stack.sessions_used == [SID, SID], "两次写调用必须落在同一个会话（否则键必然不同）"
        assert run["session_breaks"] == 0
        assert stack.writes == 2
        assert stack.replayed == [False, True], "第二次必须是回放（服务端同键去重）"
        assert run["score"] == 1.0

    def test_the_stop_condition_stops_at_the_declared_call_count(self, monkeypatch):
        """停条件 = 成功 ≥ `calls` 次：跑通即提前结束，不把 `max` 轮吃满（成本可见）。"""
        stack = _use_stack(monkeypatch, _IdempotentStack(retries=1))
        case = _case(user_inputs=["帮我下单", _retry_turn(calls=2, mx=5)],
                     must_succeed=[{"tool": "order_create", "min_successes": 2}])
        asyncio.run(lr.run_case(case, "", SID))
        assert stack.writes == 2
        assert len(stack.sent) == 2, "展开 5 轮但只发了 2 轮（达标的余下轮次被停条件跳过）"

    def test_the_declaration_is_not_a_plain_text_turn(self, monkeypatch):
        """声明轮**不得**被当成普通文本轮发出去（那是"声明无消费"的形态）。"""
        stack = _use_stack(monkeypatch, _IdempotentStack(retries=1))
        case = _case(user_inputs=["帮我下单", _retry_turn(fallback="再提交一次")],
                     must_succeed=[{"tool": "order_create", "min_successes": 2}])
        asyncio.run(lr.run_case(case, "", SID))
        assert stack.sent[1] == "再提交一次", "无待答卡时应发 fallback 文本（不是 JSON 字面量）"
        assert "retry_same_session" not in stack.sent[1]


# ── ② 可达性：能力没被触发 ⇒ 判红（不是绿）────────────────────────────────────
class TestReachabilityIsRedWhenNeverExercised:
    def test_a_retry_that_never_happens_is_a_failure(self, monkeypatch):
        """模型只回一句"已提交成功"、没有第二次写调用 ⇒ `min_successes: 2` 判红。

        这是本单的**可达性判据**：去掉 `min_successes` 的判定，本格会静默变绿 ——
        而那时"幂等"这件事**根本没有被测**（幂等断言没有对象可判）。
        """
        stack = _use_stack(monkeypatch, _IdempotentStack(retries=0))
        case = _case(user_inputs=["帮我下单", _retry_turn()],
                     must_succeed=[{"tool": "order_create", "min_successes": 2}])
        run = asyncio.run(lr.run_case(case, "", SID))
        assert stack.writes == 1
        assert run["score"] < 1.0
        msgs = [str(f[0]) for f in run["failed"]]
        assert any("成功 1 次 < 要求 2 次" in m for m in msgs), msgs

    def test_a_consumer_removed_declaration_would_go_red(self, monkeypatch):
        """把声明轮换成等价的**普通文本轮**（= runner 不消费它）⇒ 本用例必须变红。

        注入的是"消费端不在"的形态（`user_inputs` 里没有 `retry_same_session`），
        断言的是同一件事：**没有第二次写调用就没有绿**。
        """
        stack = _use_stack(monkeypatch, _IdempotentStack(retries=0))
        case = _case(user_inputs=["帮我下单", "刚才没提交成功，你再提交一次"],
                     must_succeed=[{"tool": "order_create", "min_successes": 2}])
        run = asyncio.run(lr.run_case(case, "", SID))
        assert stack.writes == 1
        assert run["score"] < 1.0

    def test_check_must_succeed_reports_the_count_gap_verbatim(self):
        """纯函数面：`min_successes` 只差一次时，原文必须能分辨"没重发"与"一次都没成"。"""
        results = _trace([(1, 0, True, {"orderNo": ORDER_NO})])
        issues = lr.check_must_succeed(results, [{"tool": "order_create", "min_successes": 2}])
        assert len(issues) == 1
        assert "成功 1 次 < 要求 2 次" in issues[0]
        # 与"一次都没成"分族（两条原文不同 ⇒ 归因不混）
        none_ok = lr.check_must_succeed(results, [{"tool": "order_create"}])
        assert none_ok == []

    def test_min_successes_shape_is_fail_closed(self):
        """形态非法（0 / 负数 / 字符串 / 布尔）⇒ 判红，不静默退回 1。"""
        results = _trace([(1, 0, True, {"orderNo": ORDER_NO})])
        for bad in (0, -1, "2", True):
            issues = lr.check_must_succeed(
                results, [{"tool": "order_create", "min_successes": bad}])
            assert len(issues) == 1, bad
            assert "min_successes" in issues[0], bad


# ── ③ 落库断言：三条一起判（同会话 / 有回放 / 张数）────────────────────────────
class TestIdempotencyDbVerifyFetch:
    def _patch_readback(self, monkeypatch):
        async def _ok(token, ref):
            return {"data": {"id": ref}}

        monkeypatch.setattr(lr, "_fetch_order_detail", _ok)
        monkeypatch.setattr(lr, "_fetch_ticket_detail", _ok)

    def _check(self, spec, results):
        return asyncio.run(lr.check_db_verify("", [spec], results))

    def test_same_key_replay_passes(self, monkeypatch):
        self._patch_readback(monkeypatch)
        issue = self._check({"fetch": "order_by_client_request_id", "source": "order_create",
                             "expect_rows": 1, "expect_replayed": True},
                            _trace(_same_order(2)))
        assert issue == []

    def test_a_second_order_is_caught(self, monkeypatch):
        """**正主**：两次成功调用指向两张不同的单据 ⇒ 违规（重复下单/重复建单）。"""
        self._patch_readback(monkeypatch)
        issue = self._check({"fetch": "order_by_client_request_id", "source": "order_create",
                             "expect_rows": 1, "expect_replayed": True},
                            _trace(_two_orders()))
        assert any("≠ 期望 1 张" in m for m in issue), issue

    def test_a_missing_retry_is_caught(self, monkeypatch):
        """压根没重试（只 1 次成功调用）⇒ 违规，不静默通过。"""
        self._patch_readback(monkeypatch)
        issue = self._check({"fetch": "order_by_client_request_id", "source": "order_create",
                             "expect_rows": 1, "expect_replayed": True},
                            _trace(_same_order(1)))
        assert any("没有任何一次回放" in m for m in issue), issue

    def test_a_cross_session_retry_is_caught(self, monkeypatch):
        """跨会话的"重试"证明不了同键（键的会话维度）⇒ 违规，且原文点明不可归因。"""
        self._patch_readback(monkeypatch)
        rows = [(1, 0, True, {"id": ORDER_NO, "orderNo": ORDER_NO}),
                (2, 1, True, {"id": ORDER_NO, "orderNo": ORDER_NO, "replayed": True})]
        issue = self._check({"fetch": "order_by_client_request_id", "source": "order_create",
                             "expect_rows": 1, "expect_replayed": True},
                            _trace(rows))
        assert any("跨了" in m for m in issue), issue

    def test_the_legal_repeat_negative_case_shape(self, monkeypatch):
        """负例形状（`expect_rows: 2` + `expect_replayed: false`）：两笔都是新建才通过。

        当前内容维度缺失 ⇒ 第二笔会被回放吞掉，本格**判红**（= 那条残留的机器证据）。
        """
        self._patch_readback(monkeypatch)
        spec = {"fetch": "order_by_client_request_id", "source": "order_create",
                "expect_rows": 2, "expect_replayed": False}
        assert self._check(spec, _trace(_two_orders())) == []
        swallowed = self._check(spec, _trace(_same_order(2)))
        assert any("回放" in m for m in swallowed), swallowed

    def test_after_sales_uses_the_same_predicate(self, monkeypatch):
        """售后路径与订单路径**共用一份**判定（服务端也共用 `ClientRequestIdService`）。"""
        self._patch_readback(monkeypatch)
        spec = {"fetch": "after_sales_by_client_request_id", "source": "aftersale_create",
                "expect_rows": 1, "expect_replayed": True}
        ticket = [(1, 0, True, {"ticketNo": TICKET_NO, "id": TICKET_NO}),
                  (2, 0, True, {"ticketNo": TICKET_NO, "id": TICKET_NO, "replayed": True})]
        assert self._check(spec, _trace(ticket, tool="aftersale_create")) == []
        broken = self._check(spec, _trace(
            [(1, 0, True, {"ticketNo": TICKET_NO, "id": TICKET_NO}),
             (2, 0, True, {"ticketNo": TICKET_NO + "-2", "id": TICKET_NO + "-2"})],
            tool="aftersale_create"))
        assert any("≠ 期望 1 张" in m or "没有任何一次回放" in m for m in broken), broken

    def test_config_errors_do_not_turn_into_silent_passes(self, monkeypatch):
        """运行期 fail-closed：缺 `expect_rows` / `expect_replayed` ⇒ 判失败，不空转通过。"""
        self._patch_readback(monkeypatch)
        missing_rows = self._check({"fetch": "order_by_client_request_id",
                                    "expect_replayed": True}, _trace(_same_order(1)))
        assert any("expect_rows" in m for m in missing_rows), missing_rows
        bad_flag = self._check({"fetch": "order_by_client_request_id", "expect_rows": 1,
                                "expect_replayed": "true"}, _trace(_same_order(1)))
        assert any("expect_replayed" in m for m in bad_flag), bad_flag
        no_calls = self._check({"fetch": "order_by_client_request_id", "expect_rows": 1,
                                "expect_replayed": True}, [])
        assert any("找不到" in m for m in no_calls), no_calls


# ── ④ 声明形态 fail-closed ────────────────────────────────────────────────────
class TestRetryDeclarationIsFailClosed:
    def test_good_shape_passes(self):
        assert lr.check_retry_same_session_declared(
            ["帮我下单", _retry_turn()]) == []

    def test_bad_shapes_are_reported(self):
        bad = [
            {"retry_same_session": "order_create"},                       # 非 dict ⇒ 展不开
            {"retry_same_session": {"calls": 2}},                         # 缺 tool
            {"retry_same_session": {"tool": "order_create", "calls": 1}},  # <2 就不是重试
            {"retry_same_session": {"tool": "order_create", "calls": 9}},  # 超展开上限
            {"retry_same_session": {"tool": "order_create", "calls": 3, "max": 2}},  # 永不可满足
            {"retry_same_session": {"tool": "order_create", "calls": 2, "times": 2}},  # 未知键
        ]
        for spec in bad:
            issues = lr.check_retry_same_session_declared([spec])
            assert len(issues) == 1, spec
        assert lr.check_retry_same_session_declared(
            [{"retry_same_session": {"tool": "order_create", "calls": 2, "max": 2}}]) == []

    def test_the_control_turn_key_table_covers_it(self):
        """控制轮写成 **JSON 字符串**时必须被抓到（`_CONTROL_TURN_KEYS` 漏登记 = 静默失效）。"""
        issues = lr.check_control_turns_declared(
            ['{"retry_same_session": {"tool": "order_create", "calls": 2}}'])
        assert len(issues) == 1
        assert "retry_same_session" in issues[0]


# ── ⑤ 三条用例真的装载得进来（声明不丢）────────────────────────────────────────
class TestTheCasesAreWiredEndToEnd:
    IDS = ("OR-049", "OR-050", "AS-010")

    def _by_id(self):
        return {c["id"]: c for c in render_cases.load_case_dicts(
            str(REPO_ROOT / ".github" / "cases"))}

    def test_the_three_cases_exist_with_the_expected_assertions(self):
        by_id = self._by_id()
        for cid in self.IDS:
            assert cid in by_id, cid
        or_049 = by_id["OR-049"]
        retry_turns = [m for m in or_049["user_inputs"]
                       if isinstance(m, dict) and m.get("retry_same_session")]
        assert len(retry_turns) == 1
        assert retry_turns[0]["retry_same_session"] == {"tool": "order_create", "calls": 2, "max": 3}
        assert or_049["must_succeed"] == [{"tool": "order_create", "min_successes": 2}]
        assert or_049["db_verify"] == [{"fetch": "order_by_client_request_id",
                                       "source": "order_create",
                                       "expect_rows": 1, "expect_replayed": True}]
        assert or_049["output_verify"] == [{"tool": "order_create", "last": True,
                                            "expect": {"replayed": True}}]
        assert by_id["OR-050"]["db_verify"] == [{"fetch": "order_by_client_request_id",
                                                 "source": "order_create",
                                                 "expect_rows": 2,
                                                 "expect_replayed": False}]
        as_010 = by_id["AS-010"]
        assert as_010["db_verify"] == [{"fetch": "after_sales_by_client_request_id",
                                        "source": "aftersale_create",
                                        "expect_rows": 1, "expect_replayed": True}]
        assert as_010["persona"] == "xiaobu", "aftersale_create 是 C 端工具（B 端只读）"

    def test_the_ci_yaml_loader_carries_the_declaration(self, monkeypatch):
        """**CI 走的是 YAML 装载路径**（`--cases .github/cases`）⇒ 漏映射 = 声明在 CI 上消失。

        本仓已记载多次同款假绿（`debug_user` / `output_verify` / `auto_fill` / `pre_turns`）。
        本文件驱动**真实装载体**（只替换它的数据源），声明轮逐值比对。
        """
        synthetic = {"id": "STUB-Y", "title": "t", "tier": "normal", "_domain": "order",
                     "user_inputs": ["帮我下单", _retry_turn()], "expectations": []}
        monkeypatch.setattr(render_cases, "load_case_dicts", lambda _d: [dict(synthetic)])
        loaded = lr.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
        assert [c.user_inputs for c in loaded] == [["帮我下单", _retry_turn()]]

    def test_every_library_case_passes_the_declaration_guard(self):
        """类级元守卫：**全库现取条数**逐条过判据 ⇒ 新判据一条都不误伤。"""
        import eval_cases
        assert len(eval_cases.ALL_CASES) > 0, "生成物零条 ⇒ 判据在空转（不许拿空集当通过）"
        offenders = [c.id for c in eval_cases.ALL_CASES
                     if lr.check_retry_same_session_declared(list(c.user_inputs or []))]
        assert offenders == [], offenders
