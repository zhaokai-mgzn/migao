# case_ids: MC-012
"""#5960 交付的两条判据（L0，离线、零 LLM、秒级）—— 本文件只锁 `.github/scripts/flaky_ledger.py`
与 `.github/workflows/flaky-triage.yml` 的结构/行为，**不碰任何产品面**。

为什么单独立一个文件（而不是塞进 `test_flaky_triage.py`）：那个文件已经 1750+ 行，而本单的
**取数面**（失败 job 的**日志**）是本仓**新开**的一条面 —— 它有自己的判据、自己的红证、
自己的真实语料。两个文件都声明同一个 CI 域用例 MC-012（**不新建用例族、不改 `.github/cases/**`**）。

病灶（逐字取自 issue #5960 的现取读数）
--------------------------------------
`Flaky Triage` 判了 `flaky/rerun-green`（一条真 flaky 被放行），而：
  · 台账里**不记录失败的是哪条测试** —— `attempt_facts()[...]["assertion"]` 的自动路径恒为 `None`
    （GitHub 的 jobs API 只给**步骤名**）⇒ 按测试名 grep 台账 **0 命中**；
  · 普通 `kind=flaky` **不落跟踪单**（只有 `suspect-window-deterministic` 强制跟踪）
    ⇒ `follow_up` 永远是 `null` ⇒ 「以后没人知道它放过什么」。

本文件锁四件事（每条的**反向变异**都会让本文件红）
------------------------------------------------
1. **失败测试身份进台账**：从**失败 job 的日志**里机械提取 pytest node id
   （`FAILED <node id> - …`），剥掉 CI 的**时间戳前缀**与 **ANSI 转义**；
   写进**独立字段** `failing_tests` —— **不碰** `attempts[].assertion`（那是 `attest` 的凭据面：
   `classify_both_red()` 靠它判 `deterministic`，而 `ledger_violations()` 又要求 deterministic
   带 `attested_evidence` ⇒ 把机械取数塞进去等于**无凭据的归因**）。
2. **「判了 flaky 却没登记」= 红**：判了 flaky / 窗口型疑似 ⇒ 条目必须带跟踪单
   （`FOLLOW_UP_REQUIRED_KINDS`），读侧（`ledger_violations`）与写侧（`append` 的
   `new_entry_tracking_violations`）**双向 fail-closed**；
   workflow 侧「落跟踪单」步骤**两类共用**（此前只对 `mark_suspect`）。
3. **约束不回溯存量**：存量条目（无 `requires_follow_up` 标志）**不判违规** ——
   否则台账在落地当天就整条链 fail-closed（存量 191 条 flaky 全都没有 `follow_up`，**现取**）。
4. **不降门禁**：不新增 secret / 不改 required 集合 / 不新增 schedule（本文件的 workflow 判据）。

红证卫生（照 §19.1 元规则③）
------------------------------
每条判据都配一条**注入式红证**：把坏形态注回 ⇒ 必须红。注入走**内容变异**
（`str.replace` 真实源码 / 真实 workflow 文本）或**行为注入**（改参数），
判据读的是内容与行为，**不读 mtime/size**。
"""
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flaky-triage.yml"
LEDGER_PATH = REPO_ROOT / ".github" / "flaky-ledger.json"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger_5960")
REAL_WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
REAL_SCRIPT_SOURCE = (SCRIPTS / "flaky_ledger.py").read_text(encoding="utf-8")

#: 🔴 **真实日志取样**（来源 = issue #5960 点名的 run `36951282049` attempt 1 的
#: `ci workflow helper unit tests` job，job id `110664565633`；取法见本文件末尾的
#: `real_log()` 的可复制命令）—— **逐字**保留 GitHub 的行首时间戳前缀（7 位小数）
#: 与真实的 ANSI 转义（`\x1b[36;1m` 在时间戳**之后**：实测 ANSI 不在行首，故「先剥 ANSI
#: 再剥时间戳」的顺序无关，但**两件都要做**）。
REAL_FAILURE_LINE = (
    "2026-10-02T01:37:49.7209574Z FAILED "
    "tests/unit_ci_workflows/test_redproof_harness_gate.py::TestLegTriState::"
    "test_real_leg_is_green_with_the_real_tools - AssertionError: 真实机具下前提自检必须全绿："
)
REAL_FAILING_TEST = (
    "tests/unit_ci_workflows/test_redproof_harness_gate.py::TestLegTriState::"
    "test_real_leg_is_green_with_the_real_tools"
)


def real_log() -> str:
    """真实日志语料（**可离线复算**）：真取一份 CI 日志、只留 `FAILED` 上下文。

    复算命令（**只读网络，不写任何状态**）：
        gh api repos/zhaokai-mgzn/migao/actions/jobs/110664565633/logs \\
            --allow-escape-sequences | grep -a 'FAILED tests/'

    ⚠️ 语义与 `REAL_FAILURE_LINE` 一致（离线时用那份逐字取样；取到真日志时用真的）。
    """
    return (
        "2026-10-02T01:30:56.0751397Z \x1b[36;1m# 判据源与 tests/unit ...\x1b[0m\n"
        "2026-10-02T01:37:49.7208828Z =========================== short test summary info ============================\n"
        f"{REAL_FAILURE_LINE}\n"
        "2026-10-02T01:37:49.7334934Z   LEG_RC=1\n"
        "2026-10-02T01:37:49.8002356Z 1 failed, 5946 passed, 10 skipped, 444 warnings in 453.30s (0:07:33)\n"
    )


# ── 判据 1：失败测试身份（日志 → node id）─────────────────────────────────────


class TestFailingTestExtraction:
    """失败测试身份的**提取判据**（纯函数，红证：注回「不剥前缀/ANSI」的坏形态 ⇒ 必红）。"""

    def test_real_log_yields_the_real_failing_node_id(self):
        """真语料：`FAILED …` 那行必须被提取成 **node id**（不含错误文本、不含时间戳/ANSI）。"""
        got = FL.extract_failing_tests(real_log())
        assert got == [REAL_FAILING_TEST], got
        # 反向判据：**不许**把断言文本 / 时间戳 / ANSI 带进来（那些是人读的，不是可复算的身份）
        assert "-" not in got[0] and "AssertionError" not in got[0]
        assert not re.search(r"\d{4}-\d{2}-\d{2}T", got[0]), got[0]

    def test_ansi_and_prefix_are_both_stripped(self):
        """ANSI 可以在**任何位置**（实测在时间戳之后）⇒ 两种形态都要认得。"""
        for line in (
            "2026-10-02T01:37:49.7Z FAILED a/b.py::T::test_x - E\n",
            "2026-10-02T01:37:49.7Z \x1b[31mFAILED a/b.py::T::test_x - E\x1b[0m\n",
            "\x1b[36;1m2026-10-02T01:37:49.7Z\x1b[0m FAILED a/b.py::T::test_x\n",
        ):
            assert FL.extract_failing_tests(line) == ["a/b.py::T::test_x"], line

    def test_multiple_failures_are_deduped_and_ordered(self):
        log = (
            "2026-10-02T00:00:00.1Z ===== short test summary info =====\n"
            "2026-10-02T00:00:00.2Z FAILED x/y.py::A::test_1 - E\n"
            "2026-10-02T00:00:00.3Z FAILED x/z.py::B::test_2 - E\n"
            "2026-10-02T00:00:00.4Z FAILED x/y.py::A::test_1 - E\n"
        )
        assert FL.extract_failing_tests(log) == ["x/y.py::A::test_1", "x/z.py::B::test_2"]

    def test_only_the_short_summary_section_is_scanned(self):
        """**回显守卫**：段头之前正文里的 `FAILED …` **不算**（嵌套 pytest 回显的形态）。"""
        log = (
            "2026-10-02T00:00:00.1Z FAILED tests/echoed.py::T::test_echo - E\n"
            "2026-10-02T00:00:00.2Z ===== short test summary info =====\n"
            "2026-10-02T00:00:00.3Z FAILED tests/real.py::T::test_real - E\n"
        )
        assert FL.extract_failing_tests(log) == ["tests/real.py::T::test_real"]

    def test_empty_and_non_pytest_logs_have_no_false_hits(self):
        assert FL.extract_failing_tests("") == []
        assert FL.extract_failing_tests(None) == []
        assert FL.extract_failing_tests("npm ERR! 失败\nERROR tests/x.py::t - boom\n") == []
        # 缩进的引用（日志正文里贴的报告）**不算** —— 只认行首的 `FAILED `（`^\s*` 之内）
        assert FL.extract_failing_tests("  见 FALLBACK FAILED tests/x.py::t\n") == []

    def test_output_is_capped(self):
        log = "short test summary info\n" + "\n".join(
            f"FAILED tests/m.py::T::test_{i} - E" for i in range(FL.MAX_FAILING_TESTS + 30))
        assert len(FL.extract_failing_tests(log)) == FL.MAX_FAILING_TESTS


class TestFailingTestExtractionRedProofs:
    """注入式红证：把「不剥 ANSI / 不剥时间戳 / 不认段头」的坏形态注回 ⇒ 必红。"""

    @staticmethod
    def _mutant(old: str, new: str, name: str):
        mutated = REAL_SCRIPT_SOURCE.replace(old, new, 1)
        assert mutated != REAL_SCRIPT_SOURCE, f"注入锚点失效（先修本测试）：{name}"
        namespace = {"__name__": name, "__file__": str(SCRIPTS / "flaky_ledger.py")}
        exec(compile(mutated, f"<mutant:{name}>", "exec"), namespace)
        return namespace

    def test_red_proof_without_ansi_stripping(self):
        """掐掉 ANSI 剥离 ⇒ 真实日志行**必须**提取失败（error 文本里的转义把 `-` 判据弄脏）。"""
        ns = self._mutant(
            'def strip_log_prefix(line: str) -> str:\n'
            '    """剥掉 GitHub 日志的**行首时间戳前缀**与 **ANSI 转义**（其余逐字保留）。"""\n'
            '    return LOG_LINE_PREFIX_RE.sub("", ANSI_ESCAPE_RE.sub("", line))',
            'def strip_log_prefix(line: str) -> str:\n'
            '    return LOG_LINE_PREFIX_RE.sub("", line)', "m_no_ansi")
        bad = ns["extract_failing_tests"](
            "2026-10-02T01:37:49.7Z \x1b[31mFAILED a/b.py::T::test_x - E\x1b[0m\n")
        assert bad == [], f"不剥 ANSI 却仍提取到 {bad!r} ⇒ 这条红证是空断言"

    def test_red_proof_without_prefix_stripping(self):
        """掐掉时间戳前缀剥离 ⇒ 行首不再是 `FAILED` ⇒ 真语料**必须**提取为空。"""
        ns = self._mutant(
            'def strip_log_prefix(line: str) -> str:\n'
            '    """剥掉 GitHub 日志的**行首时间戳前缀**与 **ANSI 转义**（其余逐字保留）。"""\n'
            '    return LOG_LINE_PREFIX_RE.sub("", ANSI_ESCAPE_RE.sub("", line))',
            'def strip_log_prefix(line: str) -> str:\n'
            '    return ANSI_ESCAPE_RE.sub("", line)', "m_no_prefix")
        assert ns["extract_failing_tests"](real_log()) == [], "不剥前缀却仍命中 ⇒ 红证是空断言"

    def test_red_proof_scanning_the_whole_log(self):
        """允许扫全文 ⇒ 正文里的**回显**会被当成失败 ⇒ 「只认段头之后」这条判据必红。"""
        ns = self._mutant("    start = 0\n", "    start = 0\n    lines = lines  # noqa\n", "m_noop")
        assert ns["extract_failing_tests"]("") == []  # 变异体仍可用（前提自证）
        # 真正的注入：把「段头定位」摘掉（`start` 恒 0）⇒ 回显行进来了
        mutated = REAL_SCRIPT_SOURCE.replace(
            "    for i, line in enumerate(lines):\n"
            "        if PYTEST_SHORT_SUMMARY_MARKER in line:\n"
            "            start = i + 1\n"
            "            break\n",
            "    start = 0\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        namespace = {"__name__": "m_whole_log", "__file__": str(SCRIPTS / "flaky_ledger.py")}
        exec(compile(mutated, "<mutant:m_whole_log>", "exec"), namespace)
        log = ("FAILED tests/echoed.py::T::test_echo - E\n"
               "short test summary info\n"
               "FAILED tests/real.py::T::test_real - E\n")
        assert namespace["extract_failing_tests"](log) == [
            "tests/echoed.py::T::test_echo", "tests/real.py::T::test_real"], "回显守卫被摘掉却没红"


# ── 判据 1b：取数面（条目 ← 日志）────────────────────────────────────────────


def _flaky_entry(run_id=990001, job="ci workflow helper unit tests", attempt=1):
    """一条**生产形态**的 flaky 条目（`FL.build_entries` 出的形状 + 模拟落单后的 follow_up）。"""
    entry = {
        "workflow": "PR Check", "job": job, "run_id": run_id, "run_attempt": 2,
        "run_url": f"https://x/{run_id}", "pr": 5943, "head_sha": "a" * 40,
        "head_branch": "fix/x", "first_failure_step": "Run ci workflow helper tests",
        "rerun_result": "success", "kind": "flaky",
        "attempts": [{"attempt": attempt, "job": job, "step": "Run ci workflow helper tests",
                      "assertion": None, "timestamp": "2026-10-02T01:37:52Z"}],
        "observed_at": "2026-10-02T01:46:10Z",
        "reason": FL.KIND_REASON["flaky"], "remedy": FL.KIND_REMEDY["flaky"],
        "status": "open", "follow_up": 5960,
        FL.REQUIRES_FOLLOW_UP_FIELD: True, FL.FAILING_TESTS_FIELD: [],
    }
    return entry


class TestCollectFailingTests:
    """取数面：`(run_id, 失败那次尝试, job name)` → 日志 → 条目的 `failing_tests`。"""

    def test_maps_entries_to_logs_and_shares_one_fetch_per_key(self):
        entries = [_flaky_entry(run_id=1), _flaky_entry(run_id=1, job="another job"),
                   _flaky_entry(run_id=2)]
        jobs = {
            (1, 1): [{"id": 11, "name": "ci workflow helper unit tests"},
                     {"id": 12, "name": "another job"}],
            (2, 1): [{"id": 21, "name": "ci workflow helper unit tests"}],
        }
        seen = []

        def fetch_jobs(repo, run_id, attempt):
            return jobs[(run_id, attempt)]

        def fetch_log(repo, jid):
            seen.append(jid)
            return real_log()

        info = FL.collect_failing_tests(entries, "o/r", fetch_jobs=fetch_jobs, fetch_log=fetch_log)
        assert info["mapped"] == 3 and info["unresolved"] == 0 and info["failed"] == [], info
        assert all(e[FL.FAILING_TESTS_FIELD] == [REAL_FAILING_TEST] for e in entries), entries
        assert seen == [11, 12, 21], f"日志拉取没有按 (run, attempt, job) 去重：{seen}"

    def test_attempt_facts_decide_which_log_is_fetched(self):
        """条目 `attempts[k].attempt` 就是**失败那次尝试** —— 取数必须用它（不是 run_attempt）。"""
        entry = _flaky_entry(attempt=1)
        entry["run_attempt"] = 2
        asked = []

        def fetch_jobs(repo, run_id, attempt):
            asked.append(attempt)
            return [{"id": 7, "name": entry["job"]}]

        FL.collect_failing_tests([entry], "o/r", fetch_jobs=fetch_jobs,
                                 fetch_log=lambda repo, jid: real_log())
        assert asked == [1], asked

    def test_unfetchable_log_is_recorded_not_silently_empty(self):
        """拉不到 ⇒ **不写**字段（空 = 「没取到」）、计数进 `unresolved` + `failed`（可见）。"""
        entries = [_flaky_entry()]
        info = FL.collect_failing_tests(
            entries, "o/r",
            fetch_jobs=lambda repo, rid, att: (_ for _ in ()).throw(RuntimeError("job 已被清理")),
            fetch_log=lambda repo, jid: "")
        assert info["unresolved"] == 1 and info["mapped"] == 0, info
        assert "job 已被清理" in info["failed"][0]["why"], info
        assert entries[0][FL.FAILING_TESTS_FIELD] == [], "取不到时不许编一个值"

    def test_fetch_cap_is_enforced_and_visible(self):
        entries = [_flaky_entry(run_id=i) for i in range(FL.MAX_LOG_FETCHES + 2)]
        calls = []

        def fetch_jobs(repo, run_id, attempt):
            calls.append(run_id)
            return [{"id": run_id, "name": entries[0]["job"]}]

        info = FL.collect_failing_tests([dict(e) for e in entries], "o/r",
                                        fetch_jobs=fetch_jobs,
                                        fetch_log=lambda repo, jid: real_log())
        assert len(calls) == FL.MAX_LOG_FETCHES, calls
        assert info["unresolved"] == 2 and any("上限" in row["why"] for row in info["failed"]), info


class TestCollectFailingTestsCli:
    """CLI 三态：读不到条目文件 ⇒ 退 1（未跑 ≠ 通过）；正常 ⇒ 原地重写 + 可见读数。"""

    def test_read_failure_is_fail_closed(self, tmp_path, capsys):
        assert FL.main([FL.COLLECT_FAILING_TESTS_COMMAND, "--repo", "o/r",
                        "--entries", str(tmp_path / "nope.json")]) == 1
        assert "未跑 ≠ 通过" in capsys.readouterr().err

    def test_writes_back_and_reports_unresolved(self, tmp_path, capsys, monkeypatch):
        path = tmp_path / "entries.json"
        path.write_text(json.dumps([_flaky_entry()]), encoding="utf-8")
        monkeypatch.setattr(FL, "fetch_attempt_jobs",
                            lambda repo, rid, att: [{"id": 11, "name": _flaky_entry()["job"]}])
        monkeypatch.setattr(FL, "fetch_job_log", lambda repo, jid: real_log())
        assert FL.main([FL.COLLECT_FAILING_TESTS_COMMAND, "--repo", "o/r",
                        "--entries", str(path)]) == 0
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved[0][FL.FAILING_TESTS_FIELD] == [REAL_FAILING_TEST], saved[0]
        out = capsys.readouterr().out
        assert "失败测试身份" in out and "未取到 0 条" in out, out

    def test_empty_entry_list_is_zero_action(self, tmp_path, capsys):
        path = tmp_path / "entries.json"
        path.write_text("[]", encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        assert FL.main([FL.COLLECT_FAILING_TESTS_COMMAND, "--repo", "o/r",
                        "--entries", str(path)]) == 0
        assert path.read_text(encoding="utf-8") == before, "零动作却改了文件"
        assert "零动作" in capsys.readouterr().out


# ── 判据 2：判了 flaky ⇒ 必须登记修复路径（读侧 + 写侧）──────────────────────


class TestTrackingIsMandatory:
    def test_generated_entries_declare_the_requirement(self):
        """`build_entries` 对 flaky / 窗口型疑似**必须**写 `requires_follow_up=True`（新条目形状）。"""
        entry = _flaky_entry()
        assert entry[FL.REQUIRES_FOLLOW_UP_FIELD] is True
        assert FL.requires_follow_up(entry) is True
        assert set(FL.FOLLOW_UP_REQUIRED_KINDS) == {"flaky", FL.SUSPECT_WINDOW_KIND}
        # 生产路径（真 `build_entries`）也要带它 —— 上面那条是手搓夹具，这里钉住真源头
        decision = FL.decide({"run": {"name": "PR Check", "event": "pull_request",
                                      "conclusion": "success", "run_attempt": 2,
                                      "id": 1, "head_branch": "b", "head_sha": "s",
                                      "html_url": "u", "pull_requests": [{"number": 1}],
                                      "updated_at": "2026-10-02T00:00:00Z"},
                              "jobs": [],
                              "prior_jobs": [{"name": "j", "conclusion": "failure",
                                              "completed_at": "2026-10-02T00:00:00Z",
                                              "steps": [{"name": "Run unit tests",
                                                         "conclusion": "failure",
                                                         "completed_at": "2026-10-02T00:00:00Z"}]}]})
        assert decision["entries"], decision
        generated = decision["entries"][0]
        assert generated[FL.REQUIRES_FOLLOW_UP_FIELD] is True, generated
        assert generated[FL.FAILING_TESTS_FIELD] == [], generated
        assert generated["follow_up"] is None, "跟踪单号仍由 `triage-follow-up` 注入"
        # **fail-closed 的实证**：刚落库的条目（还没落单）**就是**一条违规 —— 那正是本单的形态
        assert FL.tracking_violations([(0, generated)]), generated

    def test_flag_and_follow_up_missing_are_both_violations(self, tmp_path, capsys):
        """**读侧**：带标志却没跟踪单 ⇒ 违规（`ledger_violations`）。
        **写侧**：`append` 必须**非零退出**且台账**一字未改**。"""
        ledger = {"version": 2, "note": "", "_schema": {}, "entries": []}
        entry = dict(_flaky_entry(), follow_up=None)
        bad = FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [entry]})
        assert any("没有登记修复路径" in b for b in bad), bad
        path = tmp_path / "l.json"
        path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        entries = tmp_path / "e.json"
        entries.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        assert FL.main(["append", "--ledger", str(path), "--entries", str(entries)]) == 1
        assert path.read_text(encoding="utf-8") == before, "拒绝路径却改了台账（不许静默半成品）"
        assert "#5960" in capsys.readouterr().err
        # 注入单号之后 ⇒ 两个判据都过（**出口真可行动**）
        ok = dict(entry, follow_up=5960)
        assert FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [ok]}) == []
        entries.write_text(json.dumps([ok], ensure_ascii=False), encoding="utf-8")
        assert FL.main(["append", "--ledger", str(path), "--entries", str(entries)]) == 0
        assert len(FL.load_ledger(path)["entries"]) == 1

    def test_append_rejects_a_new_entry_that_drops_the_flag(self, tmp_path, capsys):
        """**形状闸**：新条目**没有标志** ⇒ `append` 当场拒收（「不写标志」不是绕过路径）。"""
        path = tmp_path / "l.json"
        path.write_text('{"version": 2, "note": "", "_schema": {}, "entries": []}',
                        encoding="utf-8")
        entry = _flaky_entry()
        entry.pop(FL.REQUIRES_FOLLOW_UP_FIELD)
        entries = tmp_path / "e.json"
        entries.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        assert FL.main(["append", "--ledger", str(path), "--entries", str(entries)]) == 1
        assert FL.load_ledger(path)["entries"] == [], "被拒的条目却进了台账"
        assert "requires_follow_up" in capsys.readouterr().err

    def test_idempotent_replay_of_an_existing_entry_is_not_blocked(self, tmp_path):
        """**幂等路径不追债**：键已在台账里 ⇒ 重复 append 是空操作，不因新判据被拒。"""
        legacy = dict(_flaky_entry(), follow_up=None)
        legacy.pop(FL.REQUIRES_FOLLOW_UP_FIELD)
        path = tmp_path / "l.json"
        path.write_text(json.dumps({"version": 2, "note": "", "_schema": {},
                                    "entries": [legacy]}, ensure_ascii=False), encoding="utf-8")
        entries = tmp_path / "e.json"
        entries.write_text(json.dumps([legacy], ensure_ascii=False), encoding="utf-8")
        assert FL.main(["append", "--ledger", str(path), "--entries", str(entries)]) == 0
        assert len(FL.load_ledger(path)["entries"]) == 1

    def test_real_ledger_has_no_legacy_violation_added(self):
        """🔴 **约束不回溯存量**：工作区那份台账（= `origin/main` 的副本）必须零违规。

        存量条目**没有** `requires_follow_up` 标志（**现取**：`origin/main` 上 `kind=flaky` **10** 条、
        191 条里其余为旧口径 `confirmed_failure`）⇒ 回溯式判据会让台账在落地当天就整条链
        fail-closed。本用例把「不许回溯」钉住。
        """
        ledger = FL.load_ledger(LEDGER_PATH)
        assert FL.ledger_violations(ledger) == []
        legacy_flaky = [e for e in ledger["entries"]
                        if e.get("kind") == "flaky" and not e.get(FL.REQUIRES_FOLLOW_UP_FIELD)]
        assert legacy_flaky, "语料前提变了（存量 flaky 条目一条都没有？先修本测试）"
        # 台账是**只追加的公开数据** ⇒ 本判据只断言「不回溯」，不对存量内容打包票
        # （存量里已有 10 条带 `follow_up` 的历史条目 —— 那是**人工回填**的，不是本判据的产物）。
        assert all(FL.requires_follow_up(e) is False for e in legacy_flaky)
        assert all(m == "" for m in FL.ledger_violations(ledger) if "5960" in m)

    def test_legacy_entries_are_still_visible_as_debt(self):
        """缺口**可见**（不是被藏起来）：存量 flaky 无 `follow_up` ⇒ `reconcile` 的 `new_events` 报。"""
        legacy = dict(_flaky_entry(), follow_up=None)
        legacy.pop(FL.REQUIRES_FOLLOW_UP_FIELD)
        rows = FL.reconcile({"entries": [legacy]})["new_events"]
        assert len(rows) == 1 and "follow_up" in rows[0]["why"], rows


class TestTrackingGateRedProofs:
    """注入式红证：摘掉读侧 / 写侧任一条 ⇒ 本文件的判据必须红。"""

    def test_red_proof_read_side_check_removed(self):
        """摘掉**读侧**跟踪闸（`tracking_violations` 的「带标志必须有跟踪单」）⇒ 必须不再判红。

        ⚠️ **锚必须唯一**（本文件第一版就踩了）：`new_entry_tracking_violations` 里有一句
        形状**完全相同**的 `if entry.get("kind") not in FOLLOW_UP_REQUIRED_KINDS: continue`，
        且它**在文件中出现得更早** ⇒ 首版锚命中的是**那个**函数 ⇒ 读侧判据其实没被摘掉，
        红证恒绿（= 空断言）。⇒ 改用只在 `tracking_violations` 里出现的那两句做锚。
        """
        mutated = REAL_SCRIPT_SOURCE.replace(
            '        if entry.get(REQUIRES_FOLLOW_UP_FIELD) is not True:\n'
            '            continue\n'
            '        if entry.get("kind") not in FOLLOW_UP_REQUIRED_KINDS:\n'
            '            continue\n',
            '        if True:\n'
            '            continue\n', 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        namespace = {"__name__": "m_no_read_gate", "__file__": str(SCRIPTS / "flaky_ledger.py")}
        exec(compile(mutated, "<mutant:m_no_read_gate>", "exec"), namespace)
        # **前提自证**（注入真的落到了 `tracking_violations` 上）：该函数此时必须恒返回空
        probe = dict(_flaky_entry(), follow_up=None)
        assert probe[FL.REQUIRES_FOLLOW_UP_FIELD] is True
        assert namespace["tracking_violations"]([(0, probe)]) == [], "注入没落在读侧判据上（锚失配）"
        assert namespace["ledger_violations"]({"version": 2, "note": "", "_schema": {},
                                               "entries": [probe]}) == [], (
            "摘掉读侧判据后 `ledger_violations` 仍判红 ⇒ 红证打在别处")
        # 反向对照：未变异体的 **真判据** 对同一条目必须判红（否则上面那条是空断言）
        assert FL.tracking_violations([(0, probe)]), "真判据对本条目判绿 ⇒ 本用例没有判别力"

    def test_red_proof_write_side_shape_gate_removed(self, tmp_path, capsys):
        """摘掉写侧形状闸 ⇒ 「不带标志的新条目」被静默收下 ⇒ 本文件那条用例必红。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            "        bad_new = new_entry_tracking_violations(fresh)\n"
            "        if bad_new:\n",
            "        bad_new = []\n        if bad_new:\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        namespace = {"__name__": "m_no_write_gate", "__file__": str(SCRIPTS / "flaky_ledger.py")}
        exec(compile(mutated, "<mutant:m_no_write_gate>", "exec"), namespace)
        path = tmp_path / "l.json"
        path.write_text('{"version": 2, "note": "", "_schema": {}, "entries": []}',
                        encoding="utf-8")
        entry = _flaky_entry()
        entry.pop(FL.REQUIRES_FOLLOW_UP_FIELD)
        entries = tmp_path / "e.json"
        entries.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        rc = namespace["main"](["append", "--ledger", str(path), "--entries", str(entries)])
        capsys.readouterr()
        assert rc == 0 and len(json.loads(path.read_text(encoding="utf-8"))["entries"]) == 1, (
            "摘掉形状闸后仍被拒 ⇒ 本红证是空断言")

    def test_red_proof_requirement_kinds_narrowed_back_to_suspect_only(self):
        """把目标集合收窄回「只窗口型」（= #5960 的病根本身）⇒ flaky 条目不再被判违规。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            'FOLLOW_UP_REQUIRED_KINDS = ("flaky", SUSPECT_WINDOW_KIND)',
            'FOLLOW_UP_REQUIRED_KINDS = (SUSPECT_WINDOW_KIND,)', 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        namespace = {"__name__": "m_narrow", "__file__": str(SCRIPTS / "flaky_ledger.py")}
        exec(compile(mutated, "<mutant:m_narrow>", "exec"), namespace)
        entry = dict(_flaky_entry(), follow_up=None)
        bad = namespace["ledger_violations"]({"version": 2, "note": "", "_schema": {},
                                              "entries": [entry]})
        assert bad == [], f"收窄目标集合后仍判红 ⇒ 红证没打在点子上：{bad}"


# ── 判据 3：workflow 侧的接线（判据对了，动作也要对）──────────────────────────


def _steps(src: str) -> list:
    wf = yaml.safe_load(src) or {}
    return ((wf.get("jobs") or {}).get("triage") or {}).get("steps") or []


def _text(step) -> str:
    step = step or {}
    return "\n".join([str(step.get("name") or ""), str(step.get("if") or ""),
                      str(step.get("run") or ""), str(step.get("uses") or "")])


def collect_workflow_violations(src: str) -> list:
    """workflow 侧的**结构判据**（空 = 合规）。纯函数，注入变异体后复用同一路径。"""
    bad = []
    steps = _steps(src)
    if not steps:
        return ["triage job 没有 steps ⇒ 本守卫会静默空跑（先修 workflow）"]

    # ① #5960：条目里必须带**失败测试身份** —— 取数步骤必须在 `append` 之前
    collect = [i for i, s in enumerate(steps)
               if f"flaky_ledger.py {FL.COLLECT_FAILING_TESTS_COMMAND}" in _text(s)]
    if not collect:
        bad.append(f"没有调用 `flaky_ledger.py {FL.COLLECT_FAILING_TESTS_COMMAND}` 的步骤 ⇒ "
                   f"台账**不记录失败的是哪条测试**（#5960 判据①的实体动作）")
    else:
        text = "\n".join(_text(steps[i]) for i in collect)
        if "/tmp/flaky-entries.json" not in text:
            bad.append(f"{FL.COLLECT_FAILING_TESTS_COMMAND} 未写到 `decide` 的条目文件 "
                       f"（`/tmp/flaky-entries.json`）⇒ 取到的东西进不了台账")
        append_at = [i for i, s in enumerate(steps) if "flaky_ledger.py append" in _text(s)]
        if append_at and min(collect) > min(append_at):
            bad.append("取数步骤排在 `append` **之后** ⇒ 台账里不会带 `failing_tests`（顺序即正确性）")

    # ② #5960 判据②：落地跟踪单的步骤必须**两类共用**（此前只认 mark_suspect ⇒ 这就是病根）
    follow_steps = [i for i, s in enumerate(steps) if "triage-follow-up" in _text(s)]
    if not follow_steps:
        bad.append("没有调用 `flaky_ledger.py triage-follow-up` 的步骤 ⇒ "
                   "「判了 flaky 必须登记修复路径」没有实体动作")
    else:
        text = "\n".join(_text(steps[i]) for i in follow_steps)
        # 「两类共用」的机械形态 = 该步骤**不被 `mark_suspect` 独占**（#5960 的病根是它只对
        # mark_suspect 跑）。判据看的是**步骤的 if 条件**，不是文案。
        only_suspect = [i for i in follow_steps
                        if "mark_suspect" in str(steps[i].get("if") or "")
                        and "mark_flaky" not in str(steps[i].get("if") or "")]
        if len(only_suspect) == len(follow_steps):
            bad.append("落地跟踪单的步骤**只对 `mark_suspect` 跑** ⇒ 普通 `kind=flaky` 不会落单"
                       "（#5960 的病根本身）⇒ 必须两类共用（或干脆不设 `if:`，由脚本按 kind 判）")
        if "::error::" not in text:
            bad.append("落单步骤没有 `::error::` fail-closed 出口 ⇒ 落不出单会**静默继续**"
                       "（而 `append` 随后 fail-closed ⇒ 现场只剩一条难读的红）")

    # ③ 不降门禁（与 test_flaky_triage.py 同口径的**最小**复核：本文件只守 #5960 的面）
    perms = (yaml.safe_load(src) or {}).get("permissions") or {}
    for scope in ("actions", "contents", "pull-requests", "issues"):
        if str(perms.get(scope) or "").lower() != "write":
            bad.append(f"permissions.{scope} 必须 write（缺它 ⇒ 对应动作静默 403）")
    body = "\n".join(_text(s) for s in steps)
    if re.search(r"secrets\.(?!GITHUB_TOKEN)", body):
        bad.append("引用了 GITHUB_TOKEN 之外的 secret（红线：不新增 secret）")
    if "schedule" in (yaml.safe_load(src) or {}).get("on", {}) or []:
        bad.append("本 workflow 出现 schedule/cron（红线：铁律 10 不新增 schedule）")
    return bad


class TestWorkflowWiring:
    def test_real_workflow_is_clean(self):
        assert collect_workflow_violations(REAL_WORKFLOW) == []

    def test_empty_input_is_not_silently_green(self):
        assert collect_workflow_violations("") != [], "空输入判绿 ⇒ 守卫会静默空跑"

    def test_mark_flaky_still_disarms_auto_merge(self):
        """**不降门禁**（对照读数）：#5960 只加「落单」，`mark_flaky` 的「不许自动放行」一字未动。"""
        body = "\n".join(_text(s) for s in _steps(REAL_WORKFLOW)
                         if "mark_flaky" in str(s.get("if") or ""))
        assert re.search(r"gh pr merge\b[^\n]*--disable-auto", body)
        assert f'--add-label "{FL.BLOCK_LABEL}"' in body
        assert f'--add-label "{FL.FLAKY_LABEL}"' in body


class TestWorkflowWiringRedProofs:
    """注入式红证：三种坏形态各自必须判红（在内存里构造，不碰磁盘）。"""

    @staticmethod
    def _mutate(break_collect=False, collect_after_append=False, narrow_follow_up=False) -> str:
        wf = yaml.safe_load(REAL_WORKFLOW)
        steps = wf["jobs"]["triage"]["steps"]
        if break_collect:
            for s in steps:
                if f"flaky_ledger.py {FL.COLLECT_FAILING_TESTS_COMMAND}" in _text(s):
                    s["run"] = str(s["run"]).replace(FL.COLLECT_FAILING_TESTS_COMMAND,
                                                     "no-such-subcommand")
        if collect_after_append:
            idx = [i for i, s in enumerate(steps)
                   if f"flaky_ledger.py {FL.COLLECT_FAILING_TESTS_COMMAND}" in _text(s)]
            moved = steps.pop(idx[0])
            steps.append(moved)
        if narrow_follow_up:
            for s in steps:
                if "triage-follow-up" in _text(s):
                    s["if"] = "steps.decide.outputs.action == 'mark_suspect'"
        return yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)

    def test_harness_really_changes_the_text(self):
        for kwargs in ({"break_collect": True}, {"collect_after_append": True},
                       {"narrow_follow_up": True}):
            assert self._mutate(**kwargs) != REAL_WORKFLOW, f"变异没生效：{kwargs}"

    def test_red_proof_removing_the_collect_step(self):
        bad = collect_workflow_violations(self._mutate(break_collect=True))
        assert any(FL.COLLECT_FAILING_TESTS_COMMAND in b for b in bad), bad

    def test_red_proof_collect_step_moved_after_append(self):
        bad = collect_workflow_violations(self._mutate(collect_after_append=True))
        assert any("顺序即正确性" in b for b in bad), bad

    def test_red_proof_follow_up_narrowed_back_to_suspect_only(self):
        bad = collect_workflow_violations(self._mutate(narrow_follow_up=True))
        assert any("只对 `mark_suspect` 跑" in b for b in bad), bad

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**（照 §19.1 元规则③）：只改注释/文案 ⇒ **不红**（守卫不吃自己的说明）。"""
        mutated = REAL_WORKFLOW.replace("# ── ③b #5960", "# ── ③b（#5960 说明文字改了）", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert collect_workflow_violations(mutated) == []


class TestCommentShowsFailingTests:
    """人读面：PR 评论必须写出**失败的测试**（否则「放过什么」在唯一的人读面上仍不可见）。"""

    def _decision(self):
        entry = _flaky_entry()
        entry[FL.FAILING_TESTS_FIELD] = [REAL_FAILING_TEST]
        return {"action": "mark_flaky", "kind": "flaky", "pr": 5943, "attempt": 2,
                "reason": "第二次绿 ⇒ flaky", "entries": [entry]}

    def test_comment_names_the_failing_test(self):
        text = FL.render_comment(self._decision())
        assert REAL_FAILING_TEST in text, text

    def test_comment_says_so_when_it_could_not_be_fetched(self):
        entry = _flaky_entry()
        entry.pop(FL.FAILING_TESTS_FIELD)
        decision = self._decision()
        decision["entries"] = [entry]
        text = FL.render_comment(decision)
        assert "未取到" in text, "取不到时必须**如实说出**（不许静默成「没有测试名」）"


class TestShippedLedgerBackwardCompatibility:
    """向后兼容（**现取**读数，不写死条数）：老条目缺两个新字段 ⇒ 既不违规、也不被改写。"""

    def test_missing_new_fields_is_not_a_violation(self):
        entry = _flaky_entry()
        for field in (FL.FAILING_TESTS_FIELD, FL.REQUIRES_FOLLOW_UP_FIELD):
            entry.pop(field)
        assert FL.ledger_violations({"version": 2, "note": "", "_schema": {},
                                     "entries": [entry]}) == []

    def test_violations_of_the_shipped_ledger_do_not_mention_5960(self):
        ledger = FL.load_ledger(LEDGER_PATH)
        messages = [m for m in FL.ledger_violations(ledger) if "5960" in m]
        assert messages == [], f"新判据回溯了存量条目：{messages[:3]}"

    def test_append_does_not_rewrite_existing_entries(self):
        """「只追加」在**新字段**这一层也成立：既有条目一字不改（deepcopy 对照）。"""
        ledger = FL.load_ledger(LEDGER_PATH)
        before = copy.deepcopy(ledger["entries"])
        fresh = dict(_flaky_entry(run_id=999999))
        FL.append_entries(ledger, [fresh])
        assert ledger["entries"][:len(before)] == before, "既有条目被改写（只追加被破坏）"
