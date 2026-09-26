# case_ids: AS-004, CU-003, HR-003, PG-013
"""准备型 `pre_clean` 的「未复位/失败」路径必须进折叠判据（issue #3797）。

## 病灶（同一件事、两条口径；首次尝试那一侧是**漏判**）

`check_preclean_not_applied` 旧判据是**裸前缀**（`str(m).startswith(_PRECLEAN_BAD_MARKERS)`），
而两处**准备型**失败路径的消息是散文、**不以稳定标记开头**：

| 类型 | "未应用/失败"消息 | 旧折叠判据 | 重试边界（子串判据） |
|---|---|---|---|
| `aftersales_ticket_prepare` | `未复位：库里没有工单 AS-…（栈缺 seed？…）` / `未复位工单 …（DB 不可达/失败: …）` | **否** | ✅ 是（含「未复位」） |
| `user_memories_clear` | `清理长期记忆失败（HTTP 500）…` | **否** | ✅ 是（含「失败」） |
| `employee_reactivate` | `pre_clean: 前置未应用: 员工 … 查询 3 次未命中` | ✅ 是 | ✅ 是 |

⇒ 首次尝试判「没这回事」（不折 `score`/`failures`），**重试时才判「前置不等价」**
—— 用例带着**假前置**跑完，绿了也**不可归因于 agent**（`migao-acceptance`「空跑」同族）。

## 修法（issue #3797 的改法②：**显式族判据** = 类型 + 前缀）

`_is_preclean_not_applied(entry)` 单点判定，两处消费（折叠侧 + 重试边界）：

1. 稳定标记前缀（`_PRECLEAN_BAD_MARKERS`，与类型无关）**恒认** —— #3781/#3783 的成果不退化；
2. 否则要求「消息**带类型** ∧ 该类型在 `_PRECLEAN_FAILURE_PREFIXES` 里登记了该前缀」
   —— 类型由 `_run_clean_specs` 随消息携带（`_CleanMsg`，`str` 子类 ⇒ 文本与落盘契约逐字不变）；
3. 类型未登记 / 消息不带类型（旧通道、单测直接喂字符串）⇒ **只认稳定标记**
   —— 不静默放宽（未知类型的散文不得被当成"未应用"）。

**键集是注册表**：必须恰好覆盖「全部非清理型 `pre` 动作」（未登记即红）——新增一个准备型/
复位族动作时，作者必须**显式选择**"有没有独立失败前缀"，不允许默认落到任何一边
（与 #3791 的 `_PRECLEAN_CLEANUP_TYPES` 对称）。

## 红证（每条都能红；回退修复 ⇒ 必红）

| 断言 | 红形态 |
|---|---|
| ① 旧判据对这些消息是**盲的** | 直接复算旧规则（`startswith(_PRECLEAN_BAD_MARKERS)`）⇒ 两条消息全部漏掉 |
| ② 新判据按**类型**收敛 | 把消息换成**清理型**类型（`employee_remove` 的删除失败文案）⇒ 不得被折（类型半边承重） |
| ③ 真·两栈态 | **正常 seed**（工单在位）⇒ 不折；**缺 seed**（查不到工单）⇒ 折 —— 走**真实**动作分支 |
| ④ `fold ⊆ retry` | 凡被折进结论的消息，重试边界也必须判「不等价」（两条口径不允许反向漂移） |

## ⚠️ 未做（如实登记，见 PR body）

issue #3797 的原始出口要求**一次真跑校准**（含正常 seed 与缺 seed 两种栈态）确认不会把既有绿跑
判成红。**本 PR 未做真跑**（成本纪律 / #4262：评测手动触发）——本文件用**确定性离线驱动**
（真实 `_run_pre_clean` + 注入式假 asyncpg/httpx 两个栈态）替代，**真跑校准登记为未验证**。
"""
import asyncio
import json
import re
import pytest
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import local_runner as lr  # noqa: E402

SEED_TICKET = "AS-20260914-9001"


# ── 假依赖（零网络、零真库；只实现被测动作真正用到的那几个方法）─────────────────

class _FakeAsyncpgConn:
    def __init__(self, row):
        self._row = row
        self.executed: list = []

    async def fetchrow(self, sql, *args):
        return self._row

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "OK"

    async def close(self):
        return None


def _fake_asyncpg(row):
    """假 `asyncpg` **模块**：`_reset_aftersales_ticket` 在函数体内 `import asyncpg`。"""
    conn = _FakeAsyncpgConn(row)
    mod = types.ModuleType("asyncpg")

    async def _connect(dsn, timeout=None):
        return conn

    mod.connect = _connect
    return mod, conn


class _FakeResp:
    def __init__(self, payload: bytes, status_code: int = 200):
        self.content, self.status_code = payload, status_code


class _FakeAsyncClient:
    def __init__(self, status_code: int):
        self._status, self.calls = status_code, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def delete(self, url, **kw):
        self.calls.append(url)
        return _FakeResp(json.dumps({"success": self._status < 300}).encode(), self._status)


def _fake_httpx(status_code: int):
    mod = types.ModuleType("httpx")
    client = _FakeAsyncClient(status_code)

    def _client(*a, **k):
        return client

    mod.AsyncClient = _client
    return mod, client


def _run_pre(spec: dict) -> list:
    """走**真实** `_run_clean_specs`（含 `_CleanMsg` 包装）跑一条 pre_clean 动作。"""
    return asyncio.run(lr._run_clean_specs("tok", [spec]))


def _old_prefix_judgement(msgs: list) -> list:
    """**回放修复前**的判据（裸前缀），用于红证①：证明旧规则对这些消息是盲的。"""
    return [str(m) for m in (msgs or []) if str(m).startswith(lr._PRECLEAN_BAD_MARKERS)]


class TestPreFixJudgementWasBlind:
    """**红证①**：两条散文失败消息在旧判据下**全部漏掉**（同一条消息，新旧判据结论相反）。"""

    TICKET_MSG = (f"未复位：库里没有工单 {SEED_TICKET}"
                  f"（栈缺 seed？见 fixtures/mibao_eval_seed.sql）")
    MEM_MSG = ("清理长期记忆失败（HTTP 500）"
               "—— 前置未生效：post_session 可能被上一跑的残留满足")

    def test_the_two_messages_carry_no_stable_marker(self):
        """前提自证：它们**确实**不以稳定标记开头（否则本红证是空断言）。"""
        for msg in (self.TICKET_MSG, self.MEM_MSG):
            assert not msg.startswith(lr._PRECLEAN_BAD_MARKERS), msg

    def test_old_rule_missed_them_and_new_rule_folds_them(self):
        typed = [lr._CleanMsg(self.TICKET_MSG, "aftersales_ticket_prepare"),
                 lr._CleanMsg(self.MEM_MSG, "user_memories_clear")]
        assert _old_prefix_judgement(typed) == [], (
            "旧判据竟然捞到了 —— 本 red proof 的前提不成立（先核对旧规则）")
        folded = lr.check_preclean_not_applied(typed)
        assert [str(m) for m in folded] == [self.TICKET_MSG, self.MEM_MSG], folded

    def test_untyped_message_still_needs_the_stable_marker(self):
        """**不放宽**：没有类型通道的散文（旧路径）仍只认稳定标记 ⇒ 不得凭空折进结论。"""
        assert lr.check_preclean_not_applied([self.TICKET_MSG, self.MEM_MSG]) == []
        assert lr.check_preclean_not_applied(
            [f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中"])


class TestFamilyPredicateIsTypeScoped:
    """**红证②**：判据按**类型**收敛 —— 清理型的"失败"文案不得被折（类型半边承重）。"""

    EMPLOYEE_REMOVE_FAIL = ("命中 2 个测试员工「王五」，其中 1 个删除失败（DELETE HTTP ≥300）"
                            "—— 现场已保留")

    def test_cleanup_type_failure_wording_is_not_folded(self):
        typed = [lr._CleanMsg(self.EMPLOYEE_REMOVE_FAIL, "employee_remove")]
        assert "失败" in self.EMPLOYEE_REMOVE_FAIL, "本红证要求该消息确实含「失败」二字"
        assert lr.check_preclean_not_applied(typed) == [], (
            "清理型的删除失败被折进了结论 —— 类型半边没起作用（判据退化成了"
            "「含失败就折」的宽松形态，会误伤 #3791 的良性 no-op 家族）")

    def test_same_wording_under_a_registered_type_would_fold(self):
        """反向自证：同一句话挂在**已登记**的类型上就会被折（证明上面的空结果是类型造成的）。"""
        typed = [lr._CleanMsg("清理长期记忆失败（HTTP 500）", "user_memories_clear")]
        assert len(lr.check_preclean_not_applied(typed)) == 1


class TestTwoStackStatesOffline:
    """**红证③**：真·两栈态（正常 seed / 缺 seed）走**真实动作分支**，零网络零真库。"""

    SPEC = {"type": "aftersales_ticket_prepare", "ticket_no": SEED_TICKET}

    def test_missing_seed_folds_into_the_conclusion(self, monkeypatch):
        mod, conn = _fake_asyncpg(row=None)          # 库里没有工单 = 栈缺 seed
        monkeypatch.setitem(sys.modules, "asyncpg", mod)
        msgs = _run_pre(self.SPEC)
        assert msgs and str(msgs[0]).startswith("未复位：库里没有工单"), msgs
        folded = lr.check_preclean_not_applied(msgs)
        assert [str(m) for m in folded] == [str(msgs[0])], (
            f"缺 seed 的工单准备没有折进结论（#3797 的原病灶）：{folded}")
        assert str(msgs[0]).startswith(lr._PRECONDITION_NOT_APPLIED) is False, (
            "本判据测的是**散文形态**被族判据捞到；若消息改用稳定标记，本文件应同步改口径")

    def test_normal_seed_is_not_flagged(self, monkeypatch):
        """**正常 seed 栈态**：工单在位 ⇒ 复位成功 ⇒ **不折**（不把既有绿跑判成红）。"""
        mod, conn = _fake_asyncpg(row={"id": "tkt_eval_as_9001"})
        monkeypatch.setitem(sys.modules, "asyncpg", mod)
        msgs = _run_pre(self.SPEC)
        assert msgs and str(msgs[0]).startswith("已复位工单"), msgs
        assert "未复位" not in str(msgs[0]) and "失败" not in str(msgs[0])
        assert lr.check_preclean_not_applied(msgs) == [], msgs
        assert lr._clean_msg_blocks_retry_equivalence(msgs[0]) is False, (
            "成功路径被重试边界判成「前置不等价」—— 会让每次重试都被标成不可归因")

    def test_db_unreachable_folds_into_the_conclusion(self, monkeypatch):
        mod = types.ModuleType("asyncpg")

        async def _boom(dsn, timeout=None):
            raise OSError("connection refused")

        mod.connect = _boom
        monkeypatch.setitem(sys.modules, "asyncpg", mod)
        msgs = _run_pre(self.SPEC)
        assert "DB 不可达/失败" in str(msgs[0]), msgs
        assert len(lr.check_preclean_not_applied(msgs)) == 1, msgs


class TestUserMemoriesClearIsFolded:
    """`user_memories_clear` 的失败 = 前置未生效（残留会满足 `post_session[user_memories]`）。"""

    SPEC = {"type": "user_memories_clear", "agent_type": "xiaobu"}

    def test_http_failure_folds(self, monkeypatch):
        mod, client = _fake_httpx(500)
        monkeypatch.setattr(lr, "httpx", mod)
        msgs = _run_pre(self.SPEC)
        assert client.calls and "/api/chat/memories" in client.calls[0], client.calls
        assert str(msgs[0]).startswith("清理长期记忆失败（HTTP 500）"), msgs
        assert len(lr.check_preclean_not_applied(msgs)) == 1, (
            f"长期记忆清理失败没有被折进结论（#3797 表第 2 行）：{msgs}")

    def test_http_success_is_not_flagged(self, monkeypatch):
        mod, _ = _fake_httpx(200)
        monkeypatch.setattr(lr, "httpx", mod)
        msgs = _run_pre(self.SPEC)
        assert str(msgs[0]).startswith("已清理长期记忆"), msgs
        assert lr.check_preclean_not_applied(msgs) == [], msgs

    def test_wording_does_not_deny_the_folding(self, monkeypatch):
        """**措辞与判定必须一致**：旧文案「不计入断言，仅提示…」与新判定直接冲突。"""
        mod, _ = _fake_httpx(500)
        monkeypatch.setattr(lr, "httpx", mod)
        msg = str(_run_pre(self.SPEC)[0])
        assert "不计入断言" not in msg, f"文案仍在否认折叠判定：{msg}"
        assert "不可归因于 agent" in msg, msg


class TestRegistryIsTotalAndExplicit:
    """**类级元守卫**：每个非清理型 `pre` 动作必须**显式登记**（未登记即红、条目须活着）。"""

    def test_keys_exactly_cover_the_prepare_side(self):
        prepare = lr._PRECLEAN_TYPES - lr._PRECLEAN_CLEANUP_TYPES
        registered = set(lr._PRECLEAN_FAILURE_PREFIXES)
        assert registered == set(prepare), (
            "准备型/复位族与前缀登记表**不同构**：\n"
            f"  未登记（新增类型必须先选族）: {sorted(set(prepare) - registered)}\n"
            f"  僵尸登记（类型已不存在）    : {sorted(registered - set(prepare))}")

    def test_no_entry_collides_with_the_cleanup_family(self):
        overlap = set(lr._PRECLEAN_FAILURE_PREFIXES) & lr._PRECLEAN_CLEANUP_TYPES
        assert overlap == set(), f"同一类型同时属于两族（语义相反）：{sorted(overlap)}"

    def test_every_registered_prefix_actually_folds(self):
        """**红证④**：登记的每一条前缀都必须真能折进结论（登记了却不生效 = 声明无消费）。"""
        for t, prefixes in lr._PRECLEAN_FAILURE_PREFIXES.items():
            for p in prefixes:
                msg = lr._CleanMsg(f"{p}（合成自注册表 {t}）", t)
                assert lr.check_preclean_not_applied([msg]) == [str(msg)], (t, p)

    def test_the_two_new_registrations_are_alive_in_the_case_library(self):
        """登记的类型必须在用例库里**有人用**（否则是僵尸登记 —— 同族：drift 台账口径）。"""
        used = set()
        for c in lr.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases")):
            for spec in (c.pre_clean or []):
                used.add(str((spec or {}).get("type") or ""))
        for t in ("aftersales_ticket_prepare",):
            assert t in used, f"{t} 已无用例声明 —— 登记条目成了僵尸（用例库: {sorted(used)}）"
        # AS-004 是本单判定影响面的现实来源（它在 cases 里声明该动作）
        as004 = {c.id: c for c in lr.load_cases_from_yaml(
            str(REPO_ROOT / ".github" / "cases"))}.get("AS-004")
        if as004 is None:
            pytest.fail("AS-004 不在用例库（本判据的前提不成立）")
        assert any(str((s or {}).get("type") or "") == "aftersales_ticket_prepare"
                   for s in (as004.pre_clean or [])), as004.pre_clean


class TestFoldIsSubsetOfRetry:
    """**红证④（口径不变式）**：被折进结论的，重试边界也必须判「不等价」。"""

    SAMPLES = [
        (f"未复位：库里没有工单 {SEED_TICKET}（栈缺 seed？）", "aftersales_ticket_prepare"),
        (f"未复位工单 {SEED_TICKET}（DB 不可达/失败: OSError: x）", "aftersales_ticket_prepare"),
        ("清理长期记忆失败（HTTP 500）", "user_memories_clear"),
        (f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中", "employee_reactivate"),
        (f"{lr._PRECLEAN_CONFIG_ERR}: 'bogus'（数据准备未执行）", "bogus"),
    ]

    def test_everything_folded_is_also_seen_by_the_retry_boundary(self):
        for text, t in self.SAMPLES:
            msg = lr._CleanMsg(text, t)
            folded = bool(lr.check_preclean_not_applied([msg]))
            retry = lr._clean_msg_blocks_retry_equivalence(msg)
            assert (not folded) or retry, f"折叠了但重试边界看不见（漏判方向漂移）：{text!r}"

    def test_benign_messages_are_neither_folded_nor_retry_blocking(self):
        """良性/幂等文案两侧都必须干净（#3791 的成果 + #3751 的措辞红线）。"""
        benign = [
            ("客户无「VIP2」标签，无需清理", "customer_tag_remove"),
            ("无 「王五」（手机号 13812345678）员工需清理（幂等）", "employee_remove"),
            ("「遮光窗帘」无重复（1 件），无需去重", "product_dedupe"),
            ("员工「王五」（手机号 13700137000）状态 active，无需恢复", "employee_reactivate"),
            (f"已复位工单 {SEED_TICKET} → pending（清空 closedAt/closeReason/internalNotes）",
             "aftersales_ticket_prepare"),
        ]
        for text, t in benign:
            msg = lr._CleanMsg(text, t)
            assert lr.check_preclean_not_applied([msg]) == [], text
            assert lr._clean_msg_blocks_retry_equivalence(msg) is False, text


class TestResidualGenericFailurePath:
    """**已登记的残余**（本单不动）：`_run_clean_specs` 的通用异常分支仍不折进结论。

    它与本单修的三条**同族**（散文、不以稳定标记开头），但泛化它需要真跑校准
    （偶发网络异常会从"一次重试"变成一条 `score=0`）⇒ 本单**只登记**。
    本类把现状**钉成事实**：若将来自动化它，这里必须同步改口径（判据会红）。
    """

    def test_generic_action_failure_is_not_folded_but_blocks_retry(self):
        msg = lr._CleanMsg("⚠️ pre_clean 失败: RuntimeError: boom", "customer_tag_remove")
        assert lr.check_preclean_not_applied([msg]) == [], (
            "通用异常分支被折进了结论 —— 若这是有意为之，请同时改这条登记与 PR 说明")
        assert lr._clean_msg_blocks_retry_equivalence(msg) is True, (
            "重试边界不再把夹具异常判成「前置不等价」—— 保护退化（比残余登记更严重）")

    def test_registry_docstring_registers_the_residual(self):
        src = Path(lr.__file__).read_text(encoding="utf-8")
        assert "残余（如实登记，不在本单射程）" in src, "残余登记被删掉了（读者会以为已覆盖）"
        assert re.search(r"pre_clean 失败", src), "通用失败文案不存在了 —— 请同步本登记"
