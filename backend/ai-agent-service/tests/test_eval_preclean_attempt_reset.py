# case_ids: AS-004, HR-003, CU-003
"""重试前置等价性：`pre_clean` 必须在**每一次尝试之前**复位（issue #3751）。

背景（**假红发生器**，run 34849029334 / SHA 929732b4 实证）：
  · 第 1 次尝试：AS-004 把 seed 工单 `tkt_eval_as_9001`（AS-20260914-9001）关掉了，
    但没带 `reason` ⇒ 首跑失败（真缺陷，由 PR #3746 修）。
  · 第 2 次尝试（新 session 重试）：该工单**已经是 closed** ⇒ agent **合理地**不再关闭
    （末次 trace 原文：「这条工单不用再关了——AS-20260914-9001 当前已经是「已关闭」状态」）
    ⇒ 重试**必红**，且两次失败成因不同 ⇒ 指纹漂移 ⇒ 旧口径判 `unstable` 而**放行**。
  机制：`_run_one_case` 的重试分支**直接 `run_case` 重跑，从不重跑 `pre_clean`** ——
  于是「第 2 次尝试的前置 = 第 1 次尝试的产物」。

本组锁定四件事（各自都有红证）：
  1. **attempt 边界复位**：重试前必须再跑一次 `pre_clean`；事件序列必须是
     复位→尝试→复位→尝试（**改前必红**：只有一次复位）；
  2. **红线：不抹本次产物** —— 断言跑完之后**不得**再有复位（复位只发生在尝试开始之前）；
  3. **按用例 opt-in** —— 没声明 `pre_clean` 的用例整跑零复位；
  4. **复位语义**：`aftersales_ticket_prepare` 必须复位**被用例点名的**工单
     （而非只保证"栈里存在 pending 工单"），且必须清空关闭留痕（只回状态不清留痕
     = `db_verify` 的 `expect_fields_nonempty[closedAt, closeReason]` 被首跑残留满足 → 假绿）；
     复位不可用时必须在产物里**机器可见**（`PRECONDITION_NOT_RESTORED`）——
     那种情况下重试结论不可归因于 agent。
"""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_preclean_reset", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


def _case(cid="RESET-001", pre_clean=None, tags=None):
    return lr.EvalCase(
        id=cid, title="t", skill=lr.Skill.GENERAL, difficulty=lr.Difficulty.NORMAL,
        user_inputs=["hi"], expectations=[], data_checks=[],
        pre_clean=pre_clean or [], tags=tags or [],
    )


def _attempt_result(score: float, sid: str = "s1") -> dict:
    return {
        "case_id": "RESET-001", "score": score, "rounds": 1, "tool_calls": [],
        "round_trace": [], "passed": 0, "total": 1, "failed": [],
        "final_session_id": sid, "last_error": None, "final_text": "",
    }


class _Harness:
    """跑 `run_suite`，把「复位 / 尝试 / 断言」事件按发生顺序记下来。

    事件序列是本组最关键的判据：它同时锁住
      ① 复位发生在**每一次尝试之前**（改前只有一次 → 必红）；
      ② **断言跑完之后没有复位**（红线：不抹本次产物）。
    """

    OK_MSG = "已复位工单 AS-20260914-9001 → pending（清空 closedAt/closeReason）"

    def __init__(self, scores, pre_clean_msgs=None, retry_msgs=None, reset_raises=False):
        self.scores = list(scores)
        self.events = []
        # 首跑前的 pre_clean 消息 / **重试前复位**的消息分开（两次调用的返回各取各的）
        self.pre_clean_msgs = list(pre_clean_msgs) if pre_clean_msgs else [self.OK_MSG]
        self.retry_msgs = list(retry_msgs) if retry_msgs else [self.OK_MSG]
        self.reset_raises = reset_raises
        self.pre_clean_calls = 0

    def install(self, monkeypatch, tmp_path=None):
        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_run_case(case, token, session_id):
            self.events.append("attempt")
            score = self.scores.pop(0) if self.scores else 0.0
            return _attempt_result(score, session_id)

        async def fake_close_and_verify(case, token, r, session_id):
            self.events.append("verify")     # 断言（含 post_session）在此发生

        async def fake_end_session(*a, **k):
            return None

        async def fake_pre_clean(token, spec):
            self.events.append("reset")
            if self.reset_raises:
                raise RuntimeError("db down")
            pool = self.pre_clean_msgs if self.pre_clean_calls == 0 else self.retry_msgs
            self.pre_clean_calls += 1
            return pool.pop(0) if pool else self.OK_MSG

        monkeypatch.setattr(lr, "login", fake_login)
        monkeypatch.setattr(lr, "get_or_create_session", fake_sess)
        monkeypatch.setattr(lr, "run_case", fake_run_case)
        monkeypatch.setattr(lr, "_close_and_verify_session", fake_close_and_verify)
        monkeypatch.setattr(lr, "_run_pre_clean", fake_pre_clean)
        monkeypatch.setattr(lr, "_end_session", fake_end_session)
        # 台账落盘改到 tmp（否则 classify 路径会往 CWD 写 agent-eval-flakes.json）
        if tmp_path is not None:
            monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "flakes.json"))

    @staticmethod
    def run(cases, classify=True, concurrency=1):
        return asyncio.run(lr.run_suite(cases, "t", classify=classify, concurrency=concurrency))


class TestRetryRerunsPreClean:
    """① attempt 边界复位（改前必红的判据在这里）。"""

    def test_reset_runs_before_every_attempt(self, monkeypatch, tmp_path):
        """失败→重试：复位必须跑**两次**（首跑前 + 重试前），且每次都在尝试之前。

        改前（本 PR 之前）事件序列 = `reset, attempt, verify, attempt, verify` ——
        第 2 次尝试前**没有** reset ⇒ 本用例红。
        """
        h = _Harness(scores=[0.0, 1.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])

        resets = [i for i, e in enumerate(h.events) if e == "reset"]
        attempts = [i for i, e in enumerate(h.events) if e == "attempt"]
        if len(resets) != 2 or len(attempts) != 2:
            pytest.fail(f"复位/尝试次数不对（重试前必须复位）：events={h.events}")
        if not (resets[0] < attempts[0] and resets[1] < attempts[1]):
            pytest.fail(f"复位必须发生在每一次尝试**之前**：events={h.events}")
        if h.events[-1] != "verify":
            pytest.fail(f"最后一次事件必须是本次尝试的断言，不得是复位：events={h.events}")

    def test_reset_runs_before_retry_in_no_classify_mode(self, monkeypatch, tmp_path):
        """`--no-classify` 兼容模式同样要复位（两条重试路径同一语义）。"""
        h = _Harness(scores=[0.0, 1.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])], classify=False)
        if h.events.count("reset") != 2:
            pytest.fail(f"兼容模式下重试前也必须复位：events={h.events}")

    def test_reset_runs_before_retry_with_concurrency(self, monkeypatch, tmp_path):
        """并发道同样成立：复位不能因并发路径被漏掉，也不能把读位整条用例持住。

        并发门下复位要拿 `gate.writer()`，而尝试持 `gate.reader()`；若读位仍整条用例持有，
        `writer` 会一直等 `readers == 0` ⇒ **死锁**（本用例会挂住 → pytest timeout 兜底）。
        """
        h = _Harness(scores=[0.0, 1.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}]), _case(cid="RESET-002")],
              concurrency=2)
        if h.events.count("reset") != 2:
            pytest.fail(f"并发道下重试前必须复位：events={h.events}")


class TestNoResetAfterAssertions:
    """② 红线：复位只发生在尝试**开始之前**，绝不抹本次尝试的产物。"""

    def test_passing_case_is_not_reset_afterwards(self, monkeypatch, tmp_path):
        """首跑即通过的用例：复位只允许有一次（尝试前），**不得**在断言之后再清一次。

        这是本任务的红线守卫 —— 若有人把复位挪到"用例跑完顺手清理"，本用例必红：
        那样会把本次尝试的真实产物（关闭态/留痕）抹掉，把真失败洗成绿。
        """
        h = _Harness(scores=[1.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])
        if h.events.count("reset") != 1:
            pytest.fail(f"通过用例只应在尝试前复位一次：events={h.events}")
        if h.events != ["reset", "attempt", "verify"]:
            pytest.fail(f"事件序列异常（不得在断言后复位）：events={h.events}")

    def test_failed_case_keeps_first_attempt_artifacts_for_evidence(self, monkeypatch, tmp_path):
        """两次都失败：复位不得出现在任何一次尝试的断言**之后**（除了下一次尝试之前）。

        失败用例的产物是归因证据（首跑指纹/逐轮轨迹），"顺手清理"会毁掉证据链。
        """
        h = _Harness(scores=[0.0, 0.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])
        if h.events != ["reset", "attempt", "verify", "reset", "attempt", "verify"]:
            pytest.fail(f"事件序列必须严格是 复位→尝试→断言 ×2：events={h.events}")


class TestOptIn:
    """③ 按用例 opt-in（issue #3751 裁定条件 3）：没声明 pre_clean 的用例不复位。"""

    def test_case_without_pre_clean_never_resets(self, monkeypatch, tmp_path):
        """没声明 `pre_clean` 的用例：整跑不得发生任何复位（全局复位会伤别的用例的状态）。"""
        h = _Harness(scores=[0.0, 1.0])
        h.install(monkeypatch, tmp_path)
        h.run([_case(pre_clean=None)])
        if h.events.count("reset") != 0:
            pytest.fail(f"未声明 pre_clean 的用例不应被复位：events={h.events}")


class TestPreconditionVisibility:
    """④ 复位失败必须机器可见，且结论不可归因于 agent（裁定条件 2）。"""

    @staticmethod
    def _result_for(results, cid="RESET-001"):
        got = [r for r in results if r.get("case_id") == cid]
        if not got:
            pytest.fail(f"用例结果缺失：{results}")
        return got[0]

    def test_reset_failure_marks_precondition_not_restored(self, monkeypatch, tmp_path):
        h = _Harness(scores=[0.0, 1.0],
                     retry_msgs=["未复位（DB 不可达/失败: OSError: conn refused）"])
        h.install(monkeypatch, tmp_path)
        results = h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])

        marker = str(self._result_for(results).get("precondition") or "")
        if not marker.startswith("PRECONDITION_NOT_RESTORED"):
            pytest.fail(f"复位失败必须带机器可见标记，实际：{marker!r}")

        # 产物（summary JSON）里同样可见 —— 判定/归因脚本据此排除"行为回归"
        sum_path = tmp_path / "summary.json"
        lr.write_summary_json(str(sum_path), "t", "", results)
        payload = json.loads(sum_path.read_text(encoding="utf-8"))
        rows = [c for c in payload["cases"] if c["id"] == "RESET-001"]
        if not rows or "precondition" not in rows[0]:
            pytest.fail(f"summary 条目缺 precondition：{rows}")
        if not str(rows[0]["precondition"]).startswith("PRECONDITION_NOT_RESTORED"):
            pytest.fail(f"summary 的 precondition 内容不对：{rows[0]}")

    def test_reset_exception_does_not_crash_and_is_marked(self, monkeypatch, tmp_path):
        """复位抛异常：不中断评测（环境问题不该伪装成用例失败），但标记照旧可见。"""
        h = _Harness(scores=[0.0, 1.0], reset_raises=True)
        h.install(monkeypatch, tmp_path)
        results = h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])
        marker = str(self._result_for(results).get("precondition") or "")
        if not marker.startswith("PRECONDITION_NOT_RESTORED"):
            pytest.fail(f"复位异常也必须带标记：{marker!r}")

    def test_successful_reset_leaves_no_marker(self, monkeypatch, tmp_path):
        """复位成功：不得挂标记（否则标记失去判别力 → 每次都"不可归因"）。"""
        h = _Harness(scores=[0.0, 1.0])
        h.install(monkeypatch, tmp_path)
        results = h.run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])])
        marker = self._result_for(results).get("precondition")
        if marker:
            pytest.fail(f"复位成功不该有标记：{marker!r}")


# ── 复位语义（`aftersales_ticket_prepare`）：复位被点名的工单 + 清空关闭留痕 ──

class _FakeConn:
    """假 asyncpg 连接：记录每条 SQL 与参数（不需要真库 → 确定性、零依赖）。"""

    _UNSET = object()

    def __init__(self, row=_UNSET, log=None):
        # row=None 也是合法输入（模拟"工单不存在" → fetchrow 返回 None）
        self.row = {"id": "tkt_eval_as_9001"} if row is self._UNSET else row
        self.log = log if log is not None else []
        self.closed = False

    async def fetchrow(self, sql, *params):
        self.log.append(("update", sql, params))
        return self.row

    async def execute(self, sql, *params):
        self.log.append(("execute", sql, params))
        return "DELETE 1"

    async def close(self):
        self.closed = True


def _install_fake_asyncpg(monkeypatch, conn, log):
    async def fake_connect(dsn, timeout=None):
        log.append(("connect", dsn, timeout))
        return conn

    mod = types.ModuleType("asyncpg")
    mod.connect = fake_connect
    monkeypatch.setitem(sys.modules, "asyncpg", mod)


def _stmt(log, kind):
    return " ".join(e[1] for e in log if e[0] == kind).lower()


class TestAftersalesTicketPrepareResetsNamedTicket:
    """`aftersales_ticket_prepare` = **复位被点名的工单**，不是"有 pending 就算"。

    改前必红：旧实现只 `GET /api/admin/after-sales` 看有没有 pending，有就
    `return "已有 N 张 pending 工单"` —— 从头到尾**没碰**被点名的工单（本组用例的
    fake 连接一次都不会被调用，且消息里没有"已复位"）。
    """

    def test_resets_named_seed_ticket(self, monkeypatch):
        log = []
        conn = _FakeConn(log=log)
        _install_fake_asyncpg(monkeypatch, conn, log)

        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))

        if "已复位" not in msg or lr._SEED_AFTERSALES_TICKET_NO not in msg:
            pytest.fail(f"必须复位并写明被点名的工单（旧实现返回『已有 N 张 pending 工单』）：{msg!r}")
        updates = [e for e in log if e[0] == "update"]
        if len(updates) != 1 or updates[0][2] != (lr._SEED_AFTERSALES_TICKET_NO,):
            pytest.fail(f"必须对**被点名的那张**工单执行一次复位 UPDATE：{log}")
        if not conn.closed:
            pytest.fail("连接必须关闭（否则评测栈连接泄漏）")

    def test_reset_clears_closed_state(self, monkeypatch):
        """复位必须**清空关闭留痕**。

        只把状态回 pending、留着 closedAt/closeReason，会让 `db_verify[after_sales_ticket]` 的
        `expect_fields_nonempty: [closedAt, closeReason]` + `expect_close_reason_contains`
        被**首跑残留**满足 → 重试即使什么都没写也可能过那条核对器（假绿）。
        """
        log = []
        _install_fake_asyncpg(monkeypatch, _FakeConn(log=log), log)
        asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))

        sql = _stmt(log, "update")
        for must in ("status = 'pending'", "closed_at = null", "close_reason = null",
                     "internal_notes = null"):
            if must not in sql:
                pytest.fail(f"复位 SQL 缺 {must!r}（只回状态不清留痕 = db_verify 假绿）：{sql}")

    def test_reset_keeps_seed_baseline_timeline_row(self, monkeypatch):
        """时间线复位必须**保留 seed 基线那条**（`action='created'`，seed 唯一插入的一行）。

        判据（裁定条件 4）：seed 只插 'created'，其余动作按定义都是评测跑出来的 ⇒
        `action <> 'created'` 就是"只清首次尝试的产物、不动基线"的判据。
        """
        log = []
        _install_fake_asyncpg(monkeypatch, _FakeConn(log=log), log)
        asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))

        deletes = [e for e in log if e[0] == "execute" and "delete" in str(e[1]).lower()]
        if len(deletes) != 1:
            pytest.fail(f"应当只有一条时间线复位 DELETE：{log}")
        sql = _stmt(log, "execute")
        if "action <> 'created'" not in sql.replace('"', "'"):
            pytest.fail(f"时间线复位必须保留 seed 基线行（action <> 'created'）：{sql}")
        if deletes[0][2] != ("tkt_eval_as_9001",):
            pytest.fail(f"时间线复位必须按被复位工单的 id 限定：{deletes[0][2]}")

    def test_reset_never_deletes_or_rekeys_the_ticket_row(self, monkeypatch):
        """复位**绝不删行**、也不动标识列：基线行（id/tenant_id/ticket_no/order_id…）原样。

        （WHERE 子句里的 `tenant_id`/`ticket_no` 是限定条件，只检查 SET 子句。）
        """
        log = []
        _install_fake_asyncpg(monkeypatch, _FakeConn(log=log), log)
        asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))

        sql = _stmt(log, "update")
        if "delete from after_sales_tickets" in sql or "insert into after_sales_tickets" in sql:
            pytest.fail(f"复位不得删/重建工单行（基线行必须保留）：{sql}")
        set_clause = sql.split(" set ", 1)[1].split(" where ", 1)[0] if " set " in sql else ""
        if not set_clause:
            pytest.fail(f"复位 SQL 形状异常（缺 SET）：{sql}")
        for col in ("id", "tenant_id", "ticket_no", "order_id", "ticket_type", "created_at"):
            if f"{col} =" in set_clause:
                pytest.fail(f"复位不得改写基线列 {col}（SET 子句：{set_clause}）")

    def test_ticket_no_can_be_overridden_by_case_spec(self, monkeypatch):
        """用例可通过 `ticket_no` 点名别的工单（默认 = seed 工单）。"""
        log = []
        _install_fake_asyncpg(monkeypatch, _FakeConn(log=log), log)
        asyncio.run(lr._run_pre_clean(
            "tok", {"type": "aftersales_ticket_prepare", "ticket_no": "AS-20990101-0001"}))
        updates = [e for e in log if e[0] == "update"]
        if updates[0][2] != ("AS-20990101-0001",):
            pytest.fail(f"ticket_no 覆盖未生效：{updates[0][2]}")

    def test_unavailable_db_is_reported_not_silent(self, monkeypatch):
        """复位不可用（asyncpg 缺失）必须**如实报出**并提示"重试前置可能不等价"。

        为什么这条必须存在：静默降级会让"数据层没复位"与"能力缺陷"在报告里同形
        （#3511 的归因盲区），也让 `PRECONDITION_NOT_RESTORED` 标记永远不出现。
        """
        monkeypatch.setitem(sys.modules, "asyncpg", None)
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))
        if "未复位" not in msg:
            pytest.fail(f"不可用时必须报『未复位』：{msg!r}")
        if "不等价" not in msg:
            pytest.fail(f"必须提示重试前置可能不等价（否则无人知道该结论不可归因）：{msg!r}")

    def test_seed_ticket_missing_is_reported(self, monkeypatch):
        """栈里没有这张工单（seed 没装）：如实报出，**不**静默兜底建一张随机工单。"""
        log = []
        _install_fake_asyncpg(monkeypatch, _FakeConn(row=None, log=log), log)
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "aftersales_ticket_prepare"}))
        if "未复位" not in msg or "没有工单" not in msg:
            pytest.fail(f"缺 seed 工单必须报出来：{msg!r}")
        if "已创建" in msg:
            pytest.fail(f"不得回落成「创建一张测试工单」（用例点名的是特定工单）：{msg!r}")
