# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   `test_mechanism_liveness.py` / `test_flaky_ledger_reconcile.py` 的同款声明与
#   `.github/cases/misc.yml` 的 MC-012 登记。**本 PR 不新建用例族、不改 `.github/cases/**`**。）
r"""`Flaky Ledger Reconcile` 自身的健康值守（issue #5960 ③）。

## 病（**实测**，不是推断）

`.github/workflows/flaky-ledger-reconcile.yml` **不在 required 集合** ⇒ 它判红**不拦任何合并**，
**也没有任何东西会因此报警** —— 「记录 flake 的那条腿自己坏了，没人知道」。现取读数（2026-10-02）：

```
$ gh run list --workflow=flaky-ledger-reconcile.yml -L 30 \
    --json databaseId,conclusion,status,createdAt,event,headBranch
2026-10-02T02:38:14Z pull_request failure         36956544614
2026-10-02T02:33:09Z pull_request failure         36956153995
2026-10-02T02:03:09Z pull_request failure         36953815649
2026-10-02T01:48:11Z pull_request action_required 36952665492
2026-10-02T01:46:16Z pull_request failure         36952519546
```

同期的既有两条存活判据**都不裁这一格**：`mechanism_liveness.yml` 的 `watchdog` 腿裁
「**跑了却没出声**」，`scripts/drift_audit.py::check_heartbeat()` 裁「**调度存在**」。

## 本文件的判据（两层）

| 层 | 测什么 | 回归时会怎么红 |
|---|---|---|
| **行为面** | `scripts/flaky_ledger_reconcile_health.py::classify` / `streak_of_reds`（**纯函数**，吃 run 列表返回结论） | 把「连续 N 条真红」判成通过 / 把「无法判定」降级成通过 / 把审批门控算成红 ⇒ 具名夹具失败 |
| **接线面** | 该脚本真的接在 `.github/workflows/flaky-ledger-reconcile.yml` 的**最后一步**上（`always()`、`--issue`、`--live`） | 摘掉接线 / 把补刀步骤变成「只写 job summary」/ 去掉机械开单 ⇒ 接线判据红 |

⚠️ **`--live` 的真网络路径**（`gh run list` + `gh api …/jobs` + `gh issue create/comment/close`）
**未在判据里跑**（它依赖 `gh` 与远端状态，且会真建单）—— **注入式红证见 PR body**，
本文件只覆盖「把网络结果喂给纯函数」的那一半（§19.1 边界登记）。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WF = REPO_ROOT / ".github" / "workflows" / "flaky-ledger-reconcile.yml"
HEALTH = REPO_ROOT / "scripts" / "flaky_ledger_reconcile_health.py"


def _load():
    spec = importlib.util.spec_from_file_location("flaky_ledger_reconcile_health", HEALTH)
    assert spec and spec.loader, f"装载不了判据本体：{HEALTH}"
    mod = importlib.util.module_from_spec(spec)
    # ⚠️ 必须**先注册进 `sys.modules` 再 exec**：`@dataclass` 在 exec 期间会查
    # `sys.modules[cls.__module__]`（未注册 ⇒ `AttributeError: 'NoneType' object has no attribute
    # '__dict__'`，收集期直接 ERROR）。
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


HL = _load()
WF_STEPS = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["reconcile"]["steps"]


def _failure(rid: int) -> dict:
    return {"databaseId": rid, "conclusion": "failure"}


def _success(rid: int) -> dict:
    return {"databaseId": rid, "conclusion": "success"}


def _gated(rid: int) -> dict:
    """审批门控：`action_required` **零 job**（GitHub 根本没给台账分支的 robot 推送创建 job）。"""
    return {"databaseId": rid, "conclusion": "action_required", "jobCount": 0}


# ══════════════════════════════════════════════════════════════════════════
# 行为面：三态 + 连续/偶发的区分
# ══════════════════════════════════════════════════════════════════════════
def test_consecutive_failures_reach_the_threshold_and_speak_up():
    """连续 N 条真红（N = 阈值）⇒ `broken`（**出声**）。"""
    s = HL.streak_of_reds([_failure(3), _failure(2), _failure(1), _success(0)], threshold=3)
    assert s.verdict == "broken", f"连续 3 条真红必须判 broken，实测 {s.verdict}"
    assert s.streak == 3 and [r["run"] for r in s.decided] == [3, 2, 1], (
        f"连续红的 run 列表必须**可归因**（新→旧），实测 {s.decided}"
    )


def test_a_single_flake_is_not_a_breakage():
    """**一次偶发红不算坏了**（本单要治的反面就是告警疲劳）。"""
    s = HL.streak_of_reds([_failure(1), _success(0)], threshold=4)
    assert s.verdict == "healthy", f"偶发一次红不得判 broken，实测 {s.verdict}"


def test_latest_green_resets_even_after_a_long_red_run():
    """最近一次已完成 run 是绿 ⇒ healthy（**哪怕**更早有一长串红）。"""
    s = HL.streak_of_reds([_success(9)] + [_failure(i) for i in range(8, 0, -1)], threshold=4)
    assert s.verdict == "healthy" and s.streak == 0, f"绿必须打断连续红，实测 {s.verdict}/{s.streak}"


def test_gated_approval_runs_are_not_counted_as_failures():
    """审批门控（`action_required` **零 job**）⇒ **不算红**。

    实测依据（可复制）：`gh api repos/{owner}/{repo}/actions/runs/<id>/jobs --jq .total_count`
    → `36952665492` = **0**、`36947111932` = **0**（action_required），而真失败 `36956153995` /
    `36947893768` = **1**。不区分 ⇒ 台账分支每开一次 PR 就伪造一段「连续红」。
    """
    s = HL.streak_of_reds([_gated(3), _gated(2), _failure(1)], threshold=2)
    assert s.verdict == "healthy", f"审批门控不得算红，实测 {s.verdict}（streak={s.streak}）"
    # ⚠️ `gated` 只数**走到的那一条**（门控是 `not-red` ⇒ 它**打断**连续红 ⇒ 游标就停在这里，
    # 与「绿打断连续红」同一条规则）。这里断言的是「门控被**识别**并作为读数报出来」，
    # 不是「窗口里所有门控都被数一遍」。
    assert s.gated >= 1, f"门控条数必须作为读数报出来，实测 gated={s.gated}"
    assert s.streak == 0, f"门控不得计入连续红，实测 streak={s.streak}"


def test_action_required_with_jobs_is_a_failure():
    """`action_required` **有 job** ⇒ **算红**（不得被门控规则豁免）。"""
    runs = [{"databaseId": 1, "conclusion": "action_required", "jobCount": 1},
            {"databaseId": 2, "conclusion": "action_required", "jobCount": 1}]
    assert HL.streak_of_reds(runs, threshold=2).verdict == "broken"


def test_unknown_job_face_fails_closed_to_red():
    """`action_required` 的 job 面**取不到** ⇒ fail-closed **算红**（不静默豁免）。"""
    assert HL.classify("action_required", None) == HL.RED


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "timed_out", "stale"])
def test_non_terminal_conclusions_are_not_results(conclusion):
    """取消 / 跳过 / 超时**不是结果** ⇒ 既不算红也不算绿，**且不计入连续红**。"""
    assert HL.classify(conclusion, None) == HL.NOT_RED, f"{conclusion} 不得算红"
    s = HL.streak_of_reds([{"databaseId": 1, "conclusion": conclusion}, _failure(2), _failure(3)],
                          threshold=2)
    assert s.verdict == "healthy" and s.streak == 0, (
        f"「不是结果」必须打断连续红（否则取消的 run 会伪造连续红），实测 {s.verdict}/{s.streak}"
    )


def test_undecidable_is_not_a_pass():
    """**三态不许降级**：结论读不到 / 窗口空 ⇒ `unknown`，**不得当通过**。"""
    s = HL.streak_of_reds([{"databaseId": 1, "conclusion": None}, _failure(2)], threshold=2)
    assert s.verdict == "unknown", f"读不到结论必须 unknown，实测 {s.verdict}"
    empty = HL.streak_of_reds([], threshold=4)
    assert empty.verdict == "unknown", f"空窗口必须 unknown（不是 healthy），实测 {empty.verdict}"
    assert HL.EXIT["unknown"] == 3, "unknown 的退出码必须是 3（不得当 0 读）"
    assert HL.EXIT["broken"] == 1 and HL.EXIT["healthy"] == 0


def test_unknown_new_failure_shape_defaults_to_red():
    """白名单式「只有 failure 算红」会让**新**坏形态静默溜过 ⇒ 未识别的终态结论默认算红。"""
    assert HL.classify("startup_failure", None) == HL.RED
    assert HL.classify("some-future-bad-state", None) == HL.RED


def test_threshold_is_read_from_the_data_not_hardcoded():
    """阈值**现取**：同一序列在 N=3 下 `broken`、N=4 下 `healthy`（证明它真读了阈值）。"""
    runs = [_failure(i) for i in (3, 2, 1)]
    assert HL.streak_of_reds(runs, threshold=3).verdict == "broken"
    assert HL.streak_of_reds(runs, threshold=4).verdict == "healthy"


def test_offline_fixtures_self_test_is_green():
    """判据本体自带的 13 条夹具（含注回坏形态）⇒ **必绿**（CI 里也跑这一步）。"""
    proc = subprocess.run([sys.executable, str(HEALTH), "--self-test"],
                          capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, f"自证失败：\n{proc.stdout}\n{proc.stderr}"
    assert "自证通过" in proc.stdout


# ══════════════════════════════════════════════════════════════════════════
# 反向对照（**注入式红证**；非空断言的自证）
# ══════════════════════════════════════════════════════════════════════════
def test_red_proof_downgrade_broken_to_healthy_is_caught(monkeypatch):
    """**注入 ①**：把「连续 N 条真红 ⇒ broken」**反转**成 healthy ⇒ 夹具**必红**。

    （这就是「连续失败不再出声」那条坏形态；本判据若退化成绿，这一条会指出来。）
    """
    monkeypatch.setattr(HL, "streak_of_reds",
                        lambda runs, *, threshold=4, job_count=None: HL.Streak(verdict="healthy"))
    bad = []
    for name, runs, threshold, want in HL.SELF_TESTS:
        if HL.streak_of_reds(runs, threshold=threshold).verdict != want:
            bad.append(name)
    assert any("连续 N 条真红" in name for name in bad), (
        f"注入「连续红不再出声」后必须至少命中那条夹具，实测未命中：{bad}"
    )


def test_red_proof_downgrade_unknown_to_pass_is_caught():
    """**注入 ②**：把「无法判定 ⇒ unknown」**降级**成 healthy ⇒ `--self-test` **必非零**。

    做法：临时把「空窗口」那条夹具挪到一条地图上，把 unknown 期望改成 healthy ——
    判据本体返回 unknown 而期望 healthy ⇒ 自证失败。**不改文件名**（tmp_path 副本）。
    """
    src = HEALTH.read_text(encoding="utf-8")
    mutant = src.replace(
        '("空窗口 ⇒ unknown（**不得当通过**）", [], 4, "unknown"),',
        '("空窗口 ⇒ unknown（**不得当通过**）", [], 4, "healthy"),',
        1,
    )
    assert mutant != src, "注入未生效（夹具锚点没命中）⇒ 红证不成立"
    proc = subprocess.run([sys.executable, "-c",
                           mutant.replace("if __name__ == \"__main__\":", "if False:")
                           + "\nimport sys; sys.exit(self_test())"],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, (
        f"把 unknown 降级成 healthy 后自证**仍然通过** ⇒ 三态语义没有承载体：\n{proc.stdout}"
    )


def test_red_proof_gated_run_counted_as_failure_is_caught():
    """**注入 ③**：把审批门控算成红 ⇒ 门控夹具**必红**（防「台账分支每开一次 PR 就伪造连续红」）。"""
    assert HL.classify("action_required", 0) == HL.NOT_RED, (
        "门控必须是 not-red；若这里变红，说明有人把「零 job 的 action_required」算成了失败"
    )
    s = HL.streak_of_reds([_gated(1), _gated(2)], threshold=2)
    assert s.verdict != "broken", f"两条门控 run 不得凑成 broken，实测 {s.verdict}"


# ══════════════════════════════════════════════════════════════════════════
# 接线面（§28.2：判据本体绿 ≠ 接线在）
# ══════════════════════════════════════════════════════════════════════════
def _health_steps() -> list[dict]:
    return [s for s in WF_STEPS if isinstance(s.get("run"), str)
            and "flaky_ledger_reconcile_health.py" in s["run"]]


def test_health_criterion_is_wired_into_the_reconcile_workflow():
    """**接线判据**：判据本体必须真的被 reconcile 腿调用（不是只存在于仓里）。"""
    steps = _health_steps()
    assert len(steps) == 1, f"健康判据必须**恰好**接一步，实测 {len(steps)}"
    run = steps[0]["run"]
    assert "--check" in run and "--live" in run, f"接线步必须真跑判据本体：{run[:200]}"
    assert "--issue" in run, (
        "**出声必须是机械的**：接线步必须带 `--issue`（自己开/续/清单），"
        "只写 job summary 等人看不构成本单要的值守面"
    )


def test_health_step_runs_even_when_the_mechanism_is_red():
    """上游判红时值守面**照跑**（否则「机制坏了」时值守面自己也不跑）。"""
    cond = "".join(str(s.get("if") or "") for s in _health_steps()).replace(" ", "")
    assert cond == "always()", f"接线步的 `if:` 必须是 `always()`，实测 {cond!r}"


def test_health_step_is_the_last_step_and_is_the_liveness_reading_site():
    """它**恰好是 job 的最后一步**，且**恰好**是 `mechanism-liveness` 的存活读数面。

    为什么二者只能同一步（**结构约束**，不是偏好）：`mechanism_liveness.py` 的判据 1 要求
    读数步（`emit flaky-ledger-reconcile`）是 job 的**最后一步**且**独立一步**（注解有 per-step
    上限）⇒ 在后面再加一个独立读数步就会判红；而本步用了 `always()` ⇒ 它本身就是合格的读数面。
    """
    assert WF_STEPS[-1] in _health_steps(), (
        f"读数/值守步必须是 job 的最后一步，实测最后一步 = {WF_STEPS[-1].get('name')!r}"
    )
    assert WF_STEPS[-1]["run"].count("emit flaky-ledger-reconcile") == 1, (
        "最后一步必须**恰好一次**发射 `mech=flaky-ledger-reconcile` 的存活读数"
    )


def test_health_step_does_not_change_the_mechanism_verdict():
    """**判红不许改机制结论**：接线步必须 `exit 0`（读数/开单是报告面，不是门禁）。"""
    run = _health_steps()[0]["run"]
    assert run.rstrip().endswith("exit 0"), (
        "接线步必须由 `exit 0` 收尾（否则它会把机制自己的结论覆盖成它的判定）"
    )
    assert "::error::" not in run, (
        "值守面不许打 `::error::` —— 它只报告（issue 才是出声面），否则会与机制自身的红混在一起"
    )


def test_health_step_does_not_introduce_a_new_cron():
    """**不新增 schedule/cron**（铁律 10）：触发面必须与 origin/main 逐字相同（本包只加步骤）。"""
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    crons = [c["cron"] for c in (doc.get(True) or doc.get("on") or {}).get("schedule") or []]
    assert crons == ["*/20 * * * *"], f"本包不得改 / 不得新增 cron，实测 {crons}"


def test_health_step_keeps_the_tracking_issue_title_searchable():
    """值守单标题必须是**机器可检索**的稳定片段（否则「续单」会退化成「每轮开新单」）。"""
    tags = [s for s in WF_STEPS if isinstance(s.get("name"), str) and "自身健康" in s["name"]]
    assert len(tags) == 1, f"值守步必须唯一，实测 {len(tags)}"
    assert HL.ISSUE_TAG.startswith("[") and HL.ISSUE_TAG.endswith("]"), HL.ISSUE_TAG
    assert "issue #5960" in HL.ISSUE_TITLE, HL.ISSUE_TITLE
    # 清零判据必须**在脚本里**（机械清），不许只写在 issue 正文里等人
    assert HL.EXIT["healthy"] == 0 and "clear_issue" in HEALTH.read_text(encoding="utf-8")


def test_self_test_fixtures_cover_both_injected_failure_families():
    """夹具表必须**同时**含「连续红」与「三态降级」两族（否则红证只覆盖一半）。"""
    names = " | ".join(name for name, *_ in HL.SELF_TESTS)
    for needle in ("连续 N 条真红", "unknown", "门控"):
        assert needle in names, f"夹具表缺 `{needle}` 这一族：{names}"
    assert len(HL.SELF_TESTS) >= 13, f"夹具过少（判定面可能被削）：{len(HL.SELF_TESTS)}"


def test_json_report_exposes_the_evidence_for_recomputation():
    """`--check --json` 的字段必须够复算（verdict / streak / threshold / gated / streak_max）。"""
    runs = REPO_ROOT / ".github" / "flaky-ledger.json"  # 仅取一个已存在的仓内 JSON 作 `--runs-file` 形状样板
    assert runs.exists()
    src = HEALTH.read_text(encoding="utf-8")
    for key in ("verdict", "streak", "threshold", "window", "gated", "undecided", "streak_max"):
        assert f'"{key}"' in src, f"`--check --json` 必须报出 `{key}`（复算与阈值取法都靠它）"
    # 离线复算入口必须存在（真网络腿之外的确定性通道）
    proc = subprocess.run([sys.executable, str(HEALTH), "--help"],
                          capture_output=True, text=True, timeout=60)
    assert "--runs-file" in proc.stdout and "--self-test" in proc.stdout, proc.stdout
