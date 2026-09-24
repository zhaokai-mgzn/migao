# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态。）
"""#5075 的「判据拆分 + 动作自洽」（L0，离线、零 LLM、秒级；**行为级**红证）。

被测对象 = `.github/workflows/flaky-ledger-reconcile.yml` 的
「有漂移 ⇒ 补 approve（复用 #4804 的实现）+ 补 arm auto-merge」这一步。
本文件把这一步**真的跑起来**（PATH 里塞一个 `gh` 桩 + 一个只写 `pending.json` 的
`flaky_ledger.py` 桩），而不是只对文本做正则 —— 因为本单要治的形态恰恰是
「**读数与动作不自洽**」（summary 写 `autoMerge=armed`，而 `enablePullRequestAutoMerge`
其实被 integration 权限拒绝了），只有执行才能证明判据真的按**回读的读数**分支。

四条判据（每条都能被**单独**注入变红，见 `TestEachCriterionCanBeInjectedRed`）：
  ① 分支**真冲突**（`mergeStateStatus=DIRTY` / `mergeable=CONFLICTING`）⇒ 红，报出 dirty + rebase 路径；
  ② check **被抑制**（0 check ∧ 无待批准 run ∧ 陈旧）⇒ 红，报出 0 check —— 与 ① 是**两条**判据
     （GitHub 不为冲突 PR 运行 `pull_request` workflow ⇒ 冲突必然伴随 check=0，混成一条红时真因读不出来）；
  ③ 补 arm 失败 ∧ 回读 `autoMerge≠armed` ⇒ 红（不再被 `|| echo 非致命` 吞成「已 arm」）；
  ④ 补 arm 失败 ∧ 回读 `autoMerge=armed`（已由别处 arm）⇒ 只 `::warning::`：非致命，但**不静默**。

红证卫生（照 `migao-dev-flow` §19.1 元规则 ③）：判据读的是**文件内容**（不是 mtime/size），
注入走**内容变异**（`str.replace` 后重新解析 YAML）⇒ 无缓存可污染。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WF = REPO_ROOT / ".github" / "workflows" / "flaky-ledger-reconcile.yml"
SRC = WF.read_text(encoding="utf-8")

REPAIR_PREFIX = "有漂移 ⇒"

# ── 桩：只回答被测步骤会问的问题；其余一律 exit 1（**不假装成功**）────────────────
GH_STUB = r"""#!/usr/bin/env bash
field=""
for ((i = 1; i <= $#; i++)); do
  if [ "${!i}" = "--json" ]; then j=$((i + 1)); field="${!j}"; fi
done
case "${1:-} ${2:-}" in
  "pr list") printf '%s' "${STUB_PR:-}" ;;
  "pr merge") printf '%s\n' "${STUB_ARM_OUT:-}"; exit "${STUB_ARM_RC:-0}" ;;
  "pr view")
    case "$field" in
      state) printf '%s' "${STUB_PR_STATE:-OPEN}" ;;
      mergeStateStatus) printf '%s' "${STUB_MERGE_STATE:-CLEAN}" ;;
      mergeable) printf '%s' "${STUB_MERGEABLE:-MERGEABLE}" ;;
      autoMergeRequest) printf '%s' "${STUB_AUTO_MERGE:-armed}" ;;
      *) echo "stub: unexpected --json $field" >&2; exit 1 ;;
    esac ;;
  "pr checks") printf '%s' "${STUB_CHECKS:-0}" ;;
  *) echo "stub: unexpected args: $*" >&2; exit 1 ;;
esac
"""

# 只实现「把 approve 结果写成空列表」+「把 ledger-drift 的 ahead 写成 N 条」——被测步骤只读
# 它们的**条数**（= 待批准 run 数 / 复核后的 ahead 条数）。
LEDGER_STUB = r"""import json
import os
import pathlib
import sys

out = None
for i, a in enumerate(sys.argv):
    if a == "--json-out":
        out = sys.argv[i + 1]
if out:
    if "ledger-drift" in sys.argv:
        n = int(os.environ.get("STUB_RECHECK_AHEAD", "0"))
        payload = {"ahead": [f"w/{i}/j" for i in range(n)], "behind": []}
    else:
        payload = []
    pathlib.Path(out).write_text(json.dumps(payload), encoding="utf-8")
"""


def repair_run(src: str) -> str:
    """取出「有漂移 ⇒ …」步骤的 `run`（被测脚本本体）。"""
    wf = yaml.safe_load(src) or {}
    for step in (wf.get("jobs") or {}).get("reconcile", {}).get("steps", []):
        if str(step.get("name") or "").startswith(REPAIR_PREFIX):
            return str(step.get("run") or "")
    raise AssertionError("找不到「有漂移 ⇒ …」步骤 ⇒ 本守卫的定位方式已失效（先修本测试）")


def _script(src: str, ahead: int, age: int) -> str:
    """把 GitHub 表达式替换成常量（桩只跑判据分支，不跑 actions 运行时）。"""
    out = repair_run(src)
    out = out.replace("${{ steps.drift.outputs.ahead }}", str(ahead))
    out = out.replace("${{ steps.drift.outputs.age_minutes }}", str(age))
    assert "${{" not in out, "步骤里还有未替换的表达式 ⇒ 桩跑的不是真脚本（先修本测试）"
    return out


def run_repair(tmp_path: Path, src: str = SRC, *, ahead: int = 4, age: int = 448,
               pr: str = "5093", merge_state: str = "CLEAN", mergeable: str = "MERGEABLE",
               auto_merge: str = "armed", arm_rc: int = 0, arm_out: str = "",
               checks: int = 3, recheck_ahead: int = 0):
    """把该步骤**真的执行一遍**（`bash -e`，与 GitHub 的默认 shell 形态一致）。

    `recheck_ahead` = 报红前那次**复核**（`ledger-drift` 实时重算）读到的 ahead 条数（#5310）。
    """
    work = tmp_path / "repo"
    (work / ".github" / "scripts").mkdir(parents=True, exist_ok=True)
    (work / ".github" / "scripts" / "flaky_ledger.py").write_text(LEDGER_STUB, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "PATH": f"{bindir}{os.pathsep}{env.get('PATH', '')}",
        "GH_TOKEN": "stub",
        "GITHUB_REPOSITORY": "owner/repo",
        "LEDGER_BRANCH": "chore/flaky-ledger",
        "STALE_MINUTES": "15",
        "GITHUB_OUTPUT": str(tmp_path / "gh-output.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "gh-summary.md"),
        "STUB_PR": pr,
        "STUB_MERGE_STATE": merge_state,
        "STUB_MERGEABLE": mergeable,
        "STUB_AUTO_MERGE": auto_merge,
        "STUB_ARM_RC": str(arm_rc),
        "STUB_ARM_OUT": arm_out,
        "STUB_CHECKS": str(checks),
        "STUB_RECHECK_AHEAD": str(recheck_ahead),
    })
    return subprocess.run(["bash", "-e", "-c", _script(src, ahead, age)],
                          cwd=work, env=env, capture_output=True, text=True)


# ── 判据本体（行为级） ─────────────────────────────────────────────────────────

def test_conflict_is_red_and_reports_dirty(tmp_path):
    """① 真冲突 ⇒ 红，且报出 dirty（不是「0 个 check」那条文案）。"""
    p = run_repair(tmp_path, merge_state="DIRTY", mergeable="CONFLICTING", checks=0)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "真冲突" in p.stdout
    assert "mergeable_state=DIRTY" in p.stdout
    assert "git rebase origin/main" in p.stdout, "冲突必须给可行动出口（rebase 路径）"


def test_conflict_is_not_reported_as_suppressed(tmp_path):
    """①/② 可区分：冲突形态走的是**冲突**判据，不是「0 个 check 且陈旧」那条。"""
    p = run_repair(tmp_path, merge_state="DIRTY", mergeable="CONFLICTING", checks=0)
    assert "兜底已发出但台账 PR 仍" not in p.stdout, "两种病因又被混成同一条红了"


def test_suppressed_check_is_red_and_reports_zero_check(tmp_path):
    """② check 被抑制（非冲突）⇒ 红，且报出 0 个 check。"""
    p = run_repair(tmp_path, merge_state="CLEAN", auto_merge="armed", checks=0)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "0 个 check" in p.stdout
    assert "真冲突" not in p.stdout, "非冲突形态不该走冲突判据"


def test_arm_failure_without_armed_is_red(tmp_path):
    """③ 补 arm 失败 ∧ 回读未 arm ⇒ 红（读数与动作自洽）。"""
    p = run_repair(tmp_path, auto_merge="none", arm_rc=1,
                   arm_out="GraphQL: Resource not accessible by integration")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "补 arm auto-merge 失败" in p.stdout
    assert "autoMerge=none" in p.stdout


def test_arm_failure_but_already_armed_warns_without_failing(tmp_path):
    """④ 补 arm 失败 ∧ 回读已 arm（已由别处 arm）⇒ 告警，不判红、也不静默。"""
    p = run_repair(tmp_path, auto_merge="armed", arm_rc=1,
                   arm_out="GraphQL: Resource not accessible by integration")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "::warning::" in p.stdout
    assert "autoMerge=armed" in p.stdout


def test_healthy_round_is_green_and_reports_arm_rc(tmp_path):
    """健康轮：arm 成功、有 check ⇒ 绿；读数里必须带 arm 退出码（读数与动作同源）。"""
    p = run_repair(tmp_path, arm_rc=0, checks=7)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "arm rc=0" in p.stdout


def test_old_swallow_form_is_gone():
    """③ 的**反向**判据：旧的「arm 失败 ⇒ 非致命」吞法必须已不存在（否则读数与动作不自洽）。"""
    assert "非致命，由下一轮对账复核" not in SRC
    assert "ARM_RC" in repair_run(SRC)


# ── #5310：判据不许跨时刻读数 / 无事可做不得报错 / 出口必须真可行动（判据级红证） ──────

ZERO_ACTION_GUARD = (
    '          if [ "${AHEAD:-0}" = "0" ]; then\n'
    '            echo "::notice::✅ 台账已与 main 收敛（ahead=0）—— 兜底零动作'
    '（#5310：判据与 PR 查询不许跨时刻读数）"\n'
    "            exit 0\n"
    "          fi\n"
)


def test_zero_ahead_is_zero_action_and_never_the_no_pr_error(tmp_path):
    """#5310 判据②：`ahead == 0` ⇒ **零动作**（与「无漂移 ⇒ 零动作」同一条），**不许**报错。"""
    p = run_repair(tmp_path, ahead=0, pr="")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "::notice::" in p.stdout and "零动作" in p.stdout, p.stdout
    assert "::error::" not in p.stdout, p.stdout


def test_red_proof_zero_ahead_guard_removed_goes_red(tmp_path):
    """**红证**（判据②）：把这道闸摘掉 ⇒ 同一输入（`ahead=0` ∧ 无 PR）走到「无 PR ⇒ error」。

    这正是**旧形态**：判据拿的是一个跨时刻读数，于是「无事可做」被读成「领先却无 PR」的假红。
    """
    mutated = SRC.replace(ZERO_ACTION_GUARD, "", 1)
    assert mutated != SRC, "注入锚点失效（先修本测试）"
    # 复核读到 ahead=7（= 判据与 PR 查询之间**没有**收敛）⇒ 挡住它的只有「零动作」这道闸。
    base = run_repair(tmp_path / "base", SRC, ahead=0, pr="", recheck_ahead=7)
    assert base.returncode == 0, base.stdout + base.stderr
    injected = run_repair(tmp_path / "inj", mutated, ahead=0, pr="", recheck_ahead=7)
    assert injected.returncode == 1, "摘掉零动作闸后本该（按旧形态）假红，实际仍绿"
    assert "没有 open PR" in injected.stdout, injected.stdout


def test_truly_behind_and_truly_no_pr_is_still_red_with_a_real_exit(tmp_path):
    """#5310 判据③④：**真**落后 + **真**无 PR ⇒ 仍必须红（不放宽本意），且出口**真的可行动**。"""
    p = run_repair(tmp_path, ahead=7, pr="", recheck_ahead=7)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "gh pr create --base main --head" in p.stdout, "报错没给能改变结果的真出口"
    assert "不改变结果" in p.stdout, "没说明旧出口（重跑 flaky-triage.yml）为何无效"


def test_converged_inside_the_window_is_not_red(tmp_path):
    """判据①收尾复核：判据与 PR 查询跨的那个**秒级**窗口内已收敛 ⇒ 零动作（不假红）。"""
    p = run_repair(tmp_path, ahead=3, pr="", recheck_ahead=0)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "复核 ahead=0" in p.stdout, p.stdout


def test_red_proof_recheck_removed_reintroduces_false_red(tmp_path):
    """**红证**（判据①）：把「报红前复核一次」摘掉 ⇒ 收敛在窗口内的场景又变假红。"""
    mutated = SRC.replace(
        '            if [ "$RECHECK_RC" = "0" ] && [ "$RECHECK_AHEAD" = "0" ]; then\n'
        '              echo "::notice::✅ 复核 ahead=0 —— 台账已在窗口内落仓'
        '（#5310：判据与 PR 查询不许跨时刻读数）⇒ 零动作，不判红"\n'
        "              exit 0\n"
        "            fi\n", "", 1)
    assert mutated != SRC, "注入锚点失效（先修本测试）"
    base = run_repair(tmp_path / "base", SRC, ahead=3, pr="", recheck_ahead=0)
    assert base.returncode == 0, base.stdout + base.stderr
    injected = run_repair(tmp_path / "inj", mutated, ahead=3, pr="", recheck_ahead=0)
    assert injected.returncode == 1, "摘掉复核后本该假红，实际仍绿"


def test_unactionable_exit_text_is_gone():
    """判据③的**反向**判据：旧的不可行动出口不许留在文案里（否则会被再贴回来）。"""
    assert "可行动：重跑 flaky-triage.yml（由它补建台账 PR）" not in SRC


# ── 每条判据都能被**单独**注入变红 ──────────────────────────────────────────────

CRITERIA = [
    # 每个场景只让**一条**判据能红（冲突那条把 age 压到阈值下，否则打掉冲突判据后
    # ⑤-C「0 check ∧ 陈旧」仍会红 —— 那样就证明不了「这条判据独立可判」）。
    ("conflict_split",
     'if [ "$MERGE_STATE" = "DIRTY" ] || [ "$MERGEABLE" = "CONFLICTING" ]; then', "if false; then",
     {"merge_state": "DIRTY", "mergeable": "CONFLICTING", "checks": 0, "age": 0}),
    ("suppressed_check",
     'if [ "$CHECKS" = "0" ] && [ "$PENDING" = "0" ] && [ "${AGE:-0}" -ge "$STALE_MINUTES" ]; then',
     "if false; then",
     {"merge_state": "CLEAN", "checks": 0}),
    ("arm_not_swallowed",
     'if [ "$ARM_RC" != "0" ] && [ "$AUTO_MERGE" != "armed" ]; then', "if false; then",
     {"auto_merge": "none", "arm_rc": 1}),
    ("readback_not_hardcoded",
     'AUTO_MERGE=$(gh pr view "$PR" --json autoMergeRequest',
     'AUTO_MERGE=$(echo armed) # gh pr view "$PR" --json autoMergeRequest',
     {"auto_merge": "none", "arm_rc": 1}),
]


def test_each_criterion_can_be_injected_red(tmp_path):
    """把某条判据**单独**打掉 ⇒ 对应场景从「红」变「绿」= 该判据确实是让它红的那一条。"""
    for i, (label, old, new, scn) in enumerate(CRITERIA):
        mutated = SRC.replace(old, new, 1)
        assert mutated != SRC, f"{label}：注入锚点失效（先修本测试）"
        base = run_repair(tmp_path / f"base{i}", SRC, **scn)
        assert base.returncode == 1, f"{label}：基线场景本该判红，实际 rc={base.returncode}\n{base.stdout}"
        injected = run_repair(tmp_path / f"inj{i}", mutated, **scn)
        assert injected.returncode == 0, (
            f"{label}：打掉该判据后仍判红 ⇒ 这条判据不是独立可判的\n{injected.stdout}")
