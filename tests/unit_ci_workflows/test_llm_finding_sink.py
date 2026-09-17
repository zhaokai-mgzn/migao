# case_ids: OR-009, OR-011, DF-011
"""LLM 红例 → 确定性下沉台账的 L0 机械锁（用户裁定 4′，issue #4034 ← #4009）。

## 为什么需要这层锁

用户裁定：**每条 LLM 发现的红例都必须产出 ≥1 条确定性断言**（效果层用例断言或 L0 不变式），
结果记进台账并回填到发现它的 issue；**未下沉必须显式登记**（不得静默通过）；流程本身要有
**机械检查**回答「issue N 这条红例有确定性断言了吗？」。

这条流程最容易的退化形态，恰恰是**看起来在跑、其实什么都没拦**（`migao-acceptance`
「空断言：不会红的断言 = 空断言」的同一形态）：

* 台账条目写了 `sunk`，但用例里那个字段是**空的**（`must_succeed: []`）⇒ 断言空壳；
* 台账指的是**不存在的用例 ID** / 不存在的测试函数名 ⇒ 指向空气；
* 断言补了，但**用例 `merge_log` 没回填发现它的 issue** ⇒ 「记入用例库 + 回填」链断裂，
  下一个人无从追溯；
* 判据自己**fork 出一份效果层字段清单**（`.github/assertion_taxonomy.py` 是唯一判据源）
  ⇒ 两份清单必然漂移，静态放行 / 动态判红；
* `--all` / `--check-backfill` 在 `gh` 不可用时把「看不了」写成「全清」⇒ 假绿。

本文件把上面每一条都钉成**会红的**断言（每条判据都有注入式红证：构造缺陷夹具，
断言检查器**必报出**对应违规码），并锁定**真实台账**（seed 条目 `#4014` / `#3679`）
确实被判为已下沉 —— 即「引用 P5 下沉范例证明流程可操作」。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 3 条是**该锁直接保护的、已下沉的确定性断言载体**：
OR-009 / OR-011（台账 `#4014` 的 P5 下沉范例：`must_succeed` + `db_verify`）、
DF-011（台账 `#3679` 的 L0 不变式载体，其自然语义 data_checks 已下沉为
`backend/ai-agent-service/tests/unit/test_circuit_breaker.py` 的机器断言）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB_DIR = REPO_ROOT / ".github"
sys.path.insert(0, str(GITHUB_DIR))

import assertion_taxonomy as tax  # noqa: E402
import llm_sink_check as sink  # noqa: E402

LEDGER_PATH = GITHUB_DIR / "llm-finding-ledger.json"
SINK_SCRIPT = GITHUB_DIR / "llm_sink_check.py"
CB_TEST_FILE = "backend/ai-agent-service/tests/unit/test_circuit_breaker.py"


# ── 夹具：合成条目（与被测真值解耦；载荷形态逐条对应上文那五种退化）────────────

def _case(case_id: str, **over) -> dict:
    """一条**最小合法**的合成用例（真实效果层字段 + 回填 `#9001`）。"""
    base = {
        "id": case_id,
        "merge_log": "合成夹具；2026-09-17 校准（issue #9001）：补 must_succeed",
        "must_succeed": [{"tool": "order_create"}],
    }
    base.update(over)
    return base


def _sunk(issue: int = 9001, sinks: list | None = None, **over) -> dict:
    entry = {"issue": issue, "status": "sunk",
             "evidence": "合成夹具（红证用，不指向真实 issue）",
             "sinks": sinks if sinks is not None else [
                 {"kind": "case_assertion", "cases": ["XX-001"], "fields": ["must_succeed"]}]}
    entry.update(over)
    return entry


def _codes(violations: list) -> set:
    return {v.code for v in violations}


@pytest.fixture(scope="module")
def cases_by_id() -> dict:
    """真实用例库索引（与检查器同一入口：render_cases.load_case_dicts）。"""
    return sink.load_case_index()


@pytest.fixture(scope="module")
def ledger() -> dict:
    return sink.load_ledger()


# ══════════════════════════════════════════════════════════════════════════════
# 一、真实台账自检（离线、确定性、不联网）
# ══════════════════════════════════════════════════════════════════════════════

class TestRealLedgerSelftest:
    """真实台账必须过 `--selftest`（否则「流程可操作」只是声明）。"""

    def test_real_ledger_has_no_violations(self, ledger, cases_by_id):
        violations = sink.validate_ledger(ledger, cases_by_id)
        assert violations == [], (
            "真实台账自检未过：\n" + "\n".join(str(v) for v in violations))

    def test_selftest_cli_exits_zero_from_a_foreign_cwd(self, tmp_path):
        """CLI 从**别的 CWD** 跑也必须过 —— 路径只能由 `__file__` 推，不得依赖 CWD。"""
        proc = subprocess.run(
            [sys.executable, str(SINK_SCRIPT), "--selftest"],
            cwd=str(tmp_path), capture_output=True, text=True)
        assert proc.returncode == 0, (
            f"在 {tmp_path} 下跑 --selftest 退出码 {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        assert "台账自检通过" in proc.stdout

    def test_unimplemented_is_registered_honestly(self, ledger):
        """未机械化的部分必须**如实登记**（不得靠「写个恒真判断」把清单缩短）。"""
        items = ledger.get("unimplemented") or []
        assert len(items) >= 2, "unimplemented 至少要有两条：自动入账 + GitHub 侧回填"
        blob = "\n".join(str(i) for i in items)
        assert "入账" in blob, "必须登记「新红例自动入账未实装」"
        assert "gh" in blob, "必须登记「GitHub 侧回填核验依赖 gh/网络」"
        assert "3" in blob and "无法判定" in blob, (
            "必须写明 gh 不可用时返回 3（无法判定）而不是通过")


# ══════════════════════════════════════════════════════════════════════════════
# 二、变异红证：五种退化形态必须被判据报出（断言落在 violations 上，不是「没崩」）
# ══════════════════════════════════════════════════════════════════════════════

class TestMutationRejection:
    """注入式红证 —— 每条判据都要能红（不会红的判据 = 空判据）。"""

    def test_negative_control_wellformed_entry_passes(self, cases_by_id):
        """**负例证据**：合法条目必须零违规 —— 否则判据只是「永远红」的噪音。"""
        cases = {"XX-001": _case("XX-001")}
        assert sink.check_entry(_sunk(), cases) == []

    def test_a_sunk_field_declared_but_empty_is_rejected(self):
        """(a) 用例存在，但声明的效果层字段是**空壳**（`must_succeed: []`）⇒ 断言空壳。"""
        cases = {"XX-001": _case("XX-001", must_succeed=[])}
        codes = _codes(sink.check_entry(_sunk(), cases))
        assert "SINK-CASE-FIELD-EMPTY" in codes, (
            "空壳断言（must_succeed: []）必须被判红，否则台账可以把空断言登记成已下沉")
        assert "SINK-CASE-NO-EFFECT-ASSERTION" in codes

    def test_a2_sunk_field_absent_entirely_is_rejected(self):
        """(a′) 用例根本没声明那个字段（缺 key）⇒ 同上，不得因为「查询返回 None」放行。"""
        cases = {"XX-001": _case("XX-001", must_succeed=None)}
        assert "SINK-CASE-FIELD-EMPTY" in _codes(sink.check_entry(_sunk(), cases))

    def test_b_sunk_pointing_at_missing_case_is_rejected(self, cases_by_id):
        """(b) 指向**不存在的用例 ID** ⇒ 指向空气，必须判红。"""
        entry = _sunk(sinks=[{"kind": "case_assertion",
                              "cases": ["ZZ-999"], "fields": ["must_succeed"]}])
        assert "SINK-CASE-MISSING" in _codes(sink.check_entry(entry, cases_by_id))

    def test_c_sunk_without_merge_log_backfill_is_rejected(self, cases_by_id):
        """(c) 用例 `merge_log` 缺 `#<issue>` ⇒ **回填缺失**（追溯链断裂）。"""
        real = dict(cases_by_id["OR-011"])
        cases = {"OR-011": real}
        cases["OR-011"]["merge_log"] = "POC 下单闭环集成测试新增；此处刻意不含 issue 号"
        entry = _sunk(issue=4014, sinks=[{"kind": "case_assertion",
                                          "cases": ["OR-011"], "fields": ["must_succeed"]}])
        assert "SINK-CASE-NO-BACKFILL" in _codes(sink.check_entry(entry, cases))

    def test_c2_backfill_must_not_match_a_longer_issue_number(self, cases_by_id):
        """(c′) `#40140` 不算回填 `#4014`（朴素子串匹配会把邻居的号当自己的）。"""
        cases = {"OR-011": dict(cases_by_id["OR-011"])}
        cases["OR-011"]["merge_log"] = "校准（issue #40140）"
        entry = _sunk(issue=4014, sinks=[{"kind": "case_assertion",
                                          "cases": ["OR-011"], "fields": ["must_succeed"]}])
        assert "SINK-CASE-NO-BACKFILL" in _codes(sink.check_entry(entry, cases))

    def test_c3_non_effect_field_cannot_be_claimed_as_a_sink(self, cases_by_id):
        """(c″) 非效果层字段（`expectations` = 「调用了」）不构成下沉 —— 判据源必须生效。"""
        entry = _sunk(sinks=[{"kind": "case_assertion",
                              "cases": ["OR-011"], "fields": ["expectations"]}])
        assert "SINK-FIELD-NOT-EFFECT" in _codes(sink.check_entry(entry, cases_by_id))

    def test_d_unsunk_without_reason_is_rejected(self, cases_by_id):
        """(d) `unsunk` 缺 `reason` ⇒ 没登记清楚，必须判红。"""
        entry = {"issue": 9002, "status": "unsunk", "follow_up": 4009}
        assert "UNSUNK-NO-REASON" in _codes(sink.check_entry(entry, cases_by_id))

    def test_d2_unsunk_without_follow_up_is_rejected(self, cases_by_id):
        """(d′) `unsunk` 缺 `follow_up`（无跟踪单）⇒ 停在半路，必须判红。"""
        entry = {"issue": 9002, "status": "unsunk", "reason": "存量红例，尚未产出断言"}
        assert "UNSUNK-NO-FOLLOWUP" in _codes(sink.check_entry(entry, cases_by_id))

    def test_d3_unknown_status_is_rejected(self, cases_by_id):
        """(d″) 第三态（如 `pending`/`wontfix`）不得存在 —— 未下沉只有「显式登记」一个出口。"""
        assert "ENTRY-STATUS-INVALID" in _codes(
            sink.check_entry({"issue": 9003, "status": "pending"}, cases_by_id))

    def test_e_l0_test_name_that_does_not_exist_is_rejected(self, cases_by_id):
        """(e) `test_names` 里点名了一个**不存在**的测试函数 ⇒ 指向空气，必须判红。"""
        entry = _sunk(issue=3679, sinks=[{
            "kind": "l0_invariant", "cases": ["DF-011"], "test_file": CB_TEST_FILE,
            "test_names": ["test_definitely_not_in_this_file_xyz"]}])
        codes = _codes(sink.check_entry(entry, cases_by_id))
        assert "SINK-TEST-NAME-MISSING" in codes, (
            "不存在的测试函数名必须判红 —— 否则台账可以靠改名后的死引用「保持绿」")

    def test_e2_l0_test_file_that_does_not_exist_is_rejected(self, cases_by_id):
        """(e′) `test_file` 不存在 ⇒ 同上。"""
        entry = _sunk(issue=3679, sinks=[{
            "kind": "l0_invariant", "cases": ["DF-011"],
            "test_file": "backend/ai-agent-service/tests/unit/test_nope_xyz.py",
            "test_names": ["test_anything"]}])
        assert "SINK-TEST-FILE-MISSING" in _codes(sink.check_entry(entry, cases_by_id))

    def test_f_schema_gaps_are_rejected(self):
        """台账骨架：版本 / note / entries / unimplemented 缺任一即违规。"""
        bare = {"version": 2, "entries": [], "unimplemented": []}
        codes = _codes(sink.check_ledger_schema(bare))
        assert {"LEDGER-VERSION", "LEDGER-NO-NOTE",
                "LEDGER-NO-ENTRIES", "LEDGER-NO-UNIMPLEMENTED"} <= codes

    def test_f2_duplicate_issue_is_rejected(self):
        """同一 issue 重复登记 ⇒ 台账自相矛盾，必须判红。"""
        dup = {"version": 1, "note": "x", "unimplemented": ["y"],
               "entries": [{"issue": 9004, "status": "unsunk", "reason": "r", "follow_up": 1},
                           {"issue": 9004, "status": "sunk", "evidence": "e", "sinks": []}]}
        assert "LEDGER-DUP-ENTRY" in _codes(sink.check_ledger_schema(dup))


# ══════════════════════════════════════════════════════════════════════════════
# 三、退化护栏：判据源不得分叉 / 不得为空 / 三态不得假绿
# ══════════════════════════════════════════════════════════════════════════════

class TestDegenerateGuardRails:
    """防「检查器自己悄悄退化」—— 这层锁存在的另一半理由。"""

    def test_effect_fields_is_the_taxonomy_object_itself(self):
        """效果层字段清单必须是**同一个对象** —— 复制一份就等于埋下一次漂移。"""
        assert sink.EFFECT_FIELDS is tax.EFFECT_FIELDS, (
            "llm_sink_check 自己另列了一份效果层字段：判据必须直接 import "
            "assertion_taxonomy.EFFECT_FIELDS（两份清单必然漂移）")

    def test_effect_fields_is_not_empty(self):
        """空集会让「≥1 条确定性断言」的校验**恒不满足却处处通过**（门禁空壳）。"""
        assert len(tax.EFFECT_FIELDS) > 0
        assert "must_succeed" in tax.EFFECT_FIELDS, "must_succeed 必须仍属效果层"

    def test_effect_assertion_judgement_is_the_taxonomy_function(self):
        """「有没有效果层断言」的判据也只能有一份实现。"""
        assert sink.has_effect_assertion is tax.has_effect_assertion

    def test_exit_codes_follow_the_tri_state_convention(self):
        """0=OK / 1=违规 / 3=无法判定（同 .github/scripts/eval_slot_status.sh 的约定）。"""
        assert (sink.EXIT_OK, sink.EXIT_VIOLATION, sink.EXIT_UNKNOWN) == (0, 1, 3)

    def test_all_returns_unknown_when_gh_is_unusable(self, ledger, monkeypatch):
        """`gh` 不可用 ⇒ `--all` 必须给 3，**不得**把「看不了」当「全清」。"""
        monkeypatch.setattr(sink, "GH_RUNNER",
                            lambda args: (False, "gh 未安装（红证注入）"))
        code, lines, result = sink.mode_all(ledger)
        assert code == sink.EXIT_UNKNOWN == 3
        assert result["ok"] is False and result["exit_code"] == 3
        assert any("无法判定" in line for line in lines)
        assert not any("✅" in line for line in lines), (
            "gh 不可用时不得出现任何 ✅ —— 那就是把「核不了」报成「通过」")

    def test_issue_backfill_check_returns_unknown_when_gh_is_unusable(
            self, ledger, cases_by_id, monkeypatch):
        """`--issue N --check-backfill` 在 gh 不可用时同样是 3，而不是 0。"""
        monkeypatch.setattr(sink, "GH_RUNNER",
                            lambda args: (False, "gh 未安装（红证注入）"))
        code, lines, result = sink.mode_issue(ledger, cases_by_id, 4014,
                                              check_backfill=True)
        assert code == sink.EXIT_UNKNOWN == 3
        assert result["sunk"] is True and result["backfill"] is None

    def test_open_unregistered_issue_is_reported_as_missing(self, ledger, monkeypatch):
        """机械问答的另一半：`--all` 必须把**未登记**的 open LLM 红例报成退出码 1。"""
        monkeypatch.setattr(sink, "GH_RUNNER", lambda args: (True, json.dumps(
            [{"number": 999001, "title": "[Post-Deploy] 部署后回归失败 — 2099-01-01"}])))
        code, lines, result = sink.mode_all(ledger)
        assert code == sink.EXIT_VIOLATION == 1
        assert result["unregistered"] == [999001]
        assert any("未登记" in line for line in lines)


# ══════════════════════════════════════════════════════════════════════════════
# 四、真实 seed 条目：流程在**真实数据**上可操作（引用 P5 下沉范例 #4014 / #3679）
# ══════════════════════════════════════════════════════════════════════════════

class TestSeedEntriesProveFlowIsOperable:
    """走一遍真实台账：`--issue 4014` / `--issue 3679` 必须给「已下沉且断言非空」。"""

    @pytest.mark.parametrize("issue", [4014, 3679])
    def test_seed_entry_is_present_and_verified_sunk(self, ledger, cases_by_id, issue):
        entry = sink.entry_for(ledger, issue) or {}
        assert entry.get("issue") == issue, f"台账缺少 seed 条目 #{issue}"
        assert entry.get("status") == "sunk"
        assert sink.check_entry(entry, cases_by_id) == []

    def test_real_ledger_check_is_not_vacuous(self, ledger, cases_by_id):
        """真实数据上的判据同样要有牙：把 OR-011 的 `must_succeed` 掏空 ⇒ 必报空壳违规。

        （没有这条，「真实台账零违规」可能只是判据在真实数据上恒真。）
        """
        weakened = dict(cases_by_id)
        weakened["OR-011"] = dict(cases_by_id["OR-011"], must_succeed=[])
        codes = _codes(sink.validate_ledger(ledger, weakened))
        assert "SINK-CASE-FIELD-EMPTY" in codes, (
            "真实台账 + 空壳断言竟然零违规 —— 判据在真实数据上空转了")

    @pytest.mark.parametrize("issue", [4014, 3679])
    def test_cli_answers_zero_for_seed_entry(self, ledger, cases_by_id, issue):
        """CLI 层同样给 0（离线档）—— 这是「问题有答案」的最小证据。"""
        code, lines, result = sink.mode_issue(ledger, cases_by_id, issue)
        assert code == sink.EXIT_OK == 0
        assert result["sunk"] is True and result["violations"] == []
        assert any("已下沉且断言非空" in line for line in lines)

    def test_p5_fixture_4014_carries_both_case_assertion_sinks(self, ledger, cases_by_id):
        """P5 范例（#4014）：`must_succeed`×3 条用例 + `db_verify`@OR-011 两条下沉都要在。"""
        entry = sink.entry_for(ledger, 4014)
        kinds = {(s.get("kind"), tuple(s.get("fields") or []), tuple(s.get("cases") or []))
                 for s in entry["sinks"]}
        assert ("case_assertion", ("must_succeed",),
                ("OR-009", "OR-010", "OR-011")) in kinds
        assert ("case_assertion", ("db_verify",), ("OR-011",)) in kinds
        # 且用例侧的断言确实非空（不只看台账的声明）
        for case_id in ("OR-009", "OR-010", "OR-011"):
            assert tax.has_effect_assertion(cases_by_id[case_id]), (
                f"{case_id} 丢了效果层断言 —— P5 的下沉被回退了")
        assert cases_by_id["OR-011"].get("db_verify"), "OR-011 的 db_verify 被回退了"

    def test_l0_fixture_3679_names_tests_that_really_exist(self, ledger, cases_by_id):
        """#3679（DF-011）：点名的测试函数必须**真的存在**，且用例侧回填 `#3679`。"""
        entry = sink.entry_for(ledger, 3679)
        sink_spec = entry["sinks"][0]
        assert sink_spec["kind"] == "l0_invariant"
        assert sink_spec["cases"] == ["DF-011"]
        text = (REPO_ROOT / sink_spec["test_file"]).read_text(encoding="utf-8")
        for name in sink_spec["test_names"]:
            assert f"def {name}(" in text, f"{sink_spec['test_file']} 里没有 def {name}("
        assert "404" in " ".join(sink_spec["test_names"]), (
            "DF-011 的前提否证（404 不计入熔断）必须留在下沉清单里")
        assert "#3679" in cases_by_id["DF-011"]["merge_log"]