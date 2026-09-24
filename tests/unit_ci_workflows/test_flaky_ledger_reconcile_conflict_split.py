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

import json
import os
import subprocess
import sys
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


# ══════════════════════════════════════════════════════════════════════════════
# #5301 判据②：台账分支的失败 job 必须有**自动重跑**路径（行为级；真的调 `gh run rerun`）
# ══════════════════════════════════════════════════════════════════════════════
#
# 为什么必须**执行**、不能只做正则：本单的判据是「兜底能**重跑并记账**」，而「重跑」是**动作** ——
# 只有把这一步真的跑起来（PATH 里塞 `gh` 桩、桩把每次 argv 逐条记下来）才能证明：
#   ① **真的**调了 `gh run rerun <id> --failed`（命令 + 参数逐字）；
#   ② **上限 1 次**（事实源 = GitHub 的 `run_attempt`：已重跑过 ⇒ 一次也不再重跑）；
#   ③ 只作用于**台账分支**（`branch=chore/flaky-ledger` 筛选 + 纯函数里的硬过滤，别的分支一次不碰）；
#   ④ **退回现状（去掉重跑）⇒ 判据必红**（红证：同一夹具下 `gh run rerun` 调用数 1 → 0）。
# 被测脚本本体 = 仓库里**真的** `flaky_ledger.py`（拷进工作目录；红证 = 拷**变异体**）⇒
# 「上限」「作用域」这类判据是在**真实现**上验证的，而不是对桩断言（对桩断言 = 空断言）。

REPO_SCRIPT = REPO_ROOT / ".github" / "scripts" / "flaky_ledger.py"
REAL_LEDGER_SCRIPT = REPO_SCRIPT.read_text(encoding="utf-8")
RERUN_STEP_PREFIX = "台账失败 job 兜底重跑"
TIP = "f265e0cc9a1b2c3d4e5f60718293a4b5c6d7e8f9"

#: `gh` 桩：只回答被测步骤会问的问题，并**把每次 argv 逐条记进 `$STUB_LOG`**（不假装成功）。
GH_API_STUB = r'''#!{python}
import json
import os
import sys

argv = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv, ensure_ascii=False) + "\n")


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


if argv[:2] == ["run", "rerun"]:
    sys.exit(int(os.environ.get("STUB_RERUN_RC", "0")))

if argv[:1] == ["api"]:
    path = argv[-1]
    if "/actions/runs?" in path:
        emit([{{"workflow_runs": json.loads(os.environ.get("STUB_RUNS", "[]"))}}])
    if path.endswith("/jobs"):
        rid = path.split("/actions/runs/")[-1].split("/")[0]
        jobs = json.loads(os.environ.get("STUB_JOBS", "{{}}"))
        emit([{{"jobs": jobs.get(rid, [])}}])
    if "/actions/runs/" in path:
        rid = path.rsplit("/", 1)[-1]
        emit([{{"id": int(rid), "run_attempt": int(os.environ.get("STUB_ATTEMPT_AFTER", "2"))}}])
    if "/branches/" in path:
        emit([{{"name": os.environ.get("LEDGER_BRANCH", ""),
                "commit": {{"sha": os.environ.get("STUB_TIP", "")}}}}])

print("stub: unexpected args: " + repr(argv), file=sys.stderr)
sys.exit(1)
'''


def rerun_step_body(src: str = SRC) -> str:
    """取出「台账失败 job 兜底重跑」步骤的 `run`（= 被测脚本本体）。"""
    wf = yaml.safe_load(src) or {}
    for step in (wf.get("jobs") or {}).get("reconcile", {}).get("steps", []):
        if str(step.get("name") or "").startswith(RERUN_STEP_PREFIX):
            return str(step.get("run") or "")
    raise AssertionError("找不到「台账失败 job 兜底重跑」步骤 ⇒ 本守卫的定位方式已失效（先修本测试）")


def gh_run(rid, *, branch="chore/flaky-ledger", sha=TIP, attempt=1, conclusion="failure",
           name="PR Check", event="pull_request"):
    """`/actions/runs` 列表项的**真实形状**（只列被测步骤会用到的字段）。"""
    return {"id": rid, "name": name, "head_branch": branch, "head_sha": sha, "event": event,
            "conclusion": conclusion, "run_attempt": attempt, "status": "completed"}


def failed_job(name="ci workflow helper unit tests"):
    return {"name": name, "conclusion": "failure"}


class RerunRound:
    """一次「兜底重跑步骤」的执行结果 + `gh` 调用台账。"""

    def __init__(self, proc, log: str, summary: str):
        self.returncode = proc.returncode
        self.stdout = proc.stdout + proc.stderr
        self.log = log
        self.summary = summary

    @property
    def calls(self):
        return [json.loads(ln) for ln in
                Path(self.log).read_text(encoding="utf-8").splitlines() if ln.strip()]

    @property
    def reruns(self):
        return [c for c in self.calls if c[:2] == ["run", "rerun"]]

    def rerun_ids(self):
        return [c[2] for c in self.reruns]


def run_rerun(tmp_path: Path, *, src: str = SRC, script: str | None = None,
              runs=(), jobs=None, tip: str = TIP, attempt_after: int = 2, rerun_rc: int = 0):
    """把「兜底重跑」步骤**真的执行一遍**（`bash -e`，与 GitHub 默认 shell 同形态）。

    `script` = 工作目录里那份 `flaky_ledger.py` 的内容（缺省 = 仓库**真**脚本；红证传**变异体**）。
    """
    work = tmp_path / "repo"
    (work / ".github" / "scripts").mkdir(parents=True, exist_ok=True)
    (work / ".github" / "scripts" / "flaky_ledger.py").write_text(
        REAL_LEDGER_SCRIPT if script is None else script, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(GH_API_STUB.format(python=sys.executable), encoding="utf-8")
    gh.chmod(0o755)
    # 步骤正文用的是字面 `python3`（与生产一致）⇒ 桩一个 `python3` 指向本解释器（不依赖宿主 PATH）
    py3 = bindir / "python3"
    if not py3.exists():
        py3.symlink_to(sys.executable)
    log = tmp_path / "gh-calls.jsonl"
    log.write_text("", encoding="utf-8")
    summary = tmp_path / "gh-summary.md"
    summary.write_text("", encoding="utf-8")
    out = tmp_path / "gh-output.txt"
    out.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "PATH": f"{bindir}{os.pathsep}{env.get('PATH', '')}",
        "GH_TOKEN": "stub",
        "GITHUB_REPOSITORY": "owner/repo",
        "LEDGER_BRANCH": "chore/flaky-ledger",
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "STUB_LOG": str(log),
        "STUB_RUNS": json.dumps(list(runs), ensure_ascii=False),
        "STUB_JOBS": json.dumps({str(k): v for k, v in (jobs or {}).items()}, ensure_ascii=False),
        "STUB_TIP": tip,
        "STUB_ATTEMPT_AFTER": str(attempt_after),
        "STUB_RERUN_RC": str(rerun_rc),
    })
    proc = subprocess.run(["bash", "-e", "-c", rerun_step_body(src)],
                          cwd=work, env=env, capture_output=True, text=True)
    return RerunRound(proc, str(log), str(summary))


# ── 判据本体（行为级）：真的重跑 / 上限 1 次 / 只作用于台账分支 / 如实记账 ──────────

def test_first_failure_really_reruns_the_failed_job(tmp_path):
    """判据②：台账分支上首次失败的 run ⇒ **真的**调 `gh run rerun <id> --failed`（恰好一次）。"""
    st = run_rerun(tmp_path, runs=[gh_run(35943682164)], jobs={35943682164: [failed_job()]})
    assert st.returncode == 0, st.stdout
    assert st.reruns == [["run", "rerun", "35943682164", "--failed", "--repo", "owner/repo"]], st.reruns
    assert "上限 1 次" in st.stdout, st.stdout
    assert "35943682164" in st.stdout and "run_attempt" in st.stdout, "重跑结果必须**回读**并如实记账"
    summary = Path(st.summary).read_text(encoding="utf-8")
    assert "35943682164" in summary, f"记账没落进 job summary：{summary!r}"


def test_scope_is_the_ledger_branch_only(tmp_path):
    """判据④：筛选条件必须是**台账分支** —— 别的分支的失败 run 一次也不许重跑。"""
    st = run_rerun(tmp_path, runs=[gh_run(1, branch="fix/5301-other"), gh_run(2)],
                   jobs={1: [failed_job()], 2: [failed_job()]})
    assert st.returncode == 0, st.stdout
    assert st.rerun_ids() == ["2"], st.reruns
    urls = [c[-1] for c in st.calls if c[:1] == ["api"] and "/actions/runs?" in c[-1]]
    assert any("branch=chore/flaky-ledger" in u for u in urls), urls


def test_cap_is_one_rerun_then_it_is_human_only(tmp_path):
    """判据③：上限 **1 次** —— `run_attempt≥2`（已重跑过）⇒ 一次也不再重跑，且必须报红 + 给人工出口。"""
    st = run_rerun(tmp_path, runs=[gh_run(3, attempt=2)], jobs={3: [failed_job()]})
    assert st.reruns == [], st.reruns
    assert st.returncode == 1, st.stdout
    assert "已重跑过" in st.stdout and "人工出口" in st.stdout, st.stdout


def test_stale_push_is_not_rerun(tmp_path):
    """只救**分支 tip** 的 run：陈旧 push 的 run 重跑对「PR 能否合并」零贡献，却真烧 CI 分钟。"""
    st = run_rerun(tmp_path, runs=[gh_run(4, sha="0" * 40)], jobs={4: [failed_job()]})
    assert st.reruns == [], st.reruns
    assert st.returncode == 0, st.stdout


def test_run_without_failed_jobs_is_not_rerun(tmp_path):
    """`conclusion=failure` 但**没有任何失败 job**（workflow 级失败）⇒ 无 job 可重跑（与 `decide()` 同口径）。"""
    st = run_rerun(tmp_path, runs=[gh_run(5)], jobs={5: [{"name": "x", "conclusion": "success"}]})
    assert st.reruns == [], st.reruns
    assert "workflow 级失败" in st.stdout, st.stdout


def test_unresolvable_tip_is_red_not_silently_green(tmp_path):
    """三态：确定不了分支 tip ⇒ CLI 退 **3**、workflow 步骤必须**红**（未跑 ≠ 通过），一次也不重跑。"""
    st = run_rerun(tmp_path, runs=[gh_run(6)], jobs={6: [failed_job()]}, tip="")
    assert st.reruns == [], st.reruns
    assert st.returncode == 1, st.stdout
    assert "退 3" in st.stdout, st.stdout


def test_rerun_failure_is_fail_closed(tmp_path):
    """动作失败（配额/权限/run 状态）⇒ **红**（不许静默 —— 否则「兜底没生效」会装成「没有失败」）。"""
    st = run_rerun(tmp_path, runs=[gh_run(7)], jobs={7: [failed_job()]}, rerun_rc=1)
    assert st.returncode == 1, st.stdout
    assert "::error::" in st.stdout, st.stdout


# ── 红证：判据必须会红（不会红的断言 = 空断言） ────────────────────────────────────

def test_red_proof_removing_the_rerun_is_detected(tmp_path):
    """**红证**（判据②）：退回现状（摘掉重跑调用）⇒ 同一夹具下一次 `gh run rerun` 都没有 ⇒ 判据必红。"""
    mutated = SRC.replace('          python3 .github/scripts/flaky_ledger.py rerun-failed \\\n',
                          '          true \\\n', 1)
    assert mutated != SRC, "注入锚点失效（先修本测试）"
    base = run_rerun(tmp_path / "base", runs=[gh_run(11)], jobs={11: [failed_job()]})
    assert base.rerun_ids() == ["11"], base.reruns
    injected = run_rerun(tmp_path / "inj", src=mutated, runs=[gh_run(11)], jobs={11: [failed_job()]})
    assert injected.rerun_ids() == [], "摘掉重跑后本该不再调用 `gh run rerun`"


def test_red_proof_unlimited_rerun_injection(tmp_path):
    """**红证**（判据③）：打掉 `run_attempt` 上限（= 允许无限重跑）⇒ 已重跑过的 run 又被重跑。"""
    mutant_script = REAL_LEDGER_SCRIPT.replace(
        '(out["rerun"] if entry["attempt"] <= max_reruns else out["exhausted"])',
        '(out["rerun"] if entry["attempt"] >= 0 else out["exhausted"])', 1)
    assert mutant_script != REAL_LEDGER_SCRIPT, "注入锚点失效（先修本测试）"
    runs, jobs = [gh_run(12, attempt=2)], {12: [failed_job()]}
    base = run_rerun(tmp_path / "base", runs=runs, jobs=jobs)
    assert base.rerun_ids() == [], base.reruns
    injected = run_rerun(tmp_path / "inj", script=mutant_script, runs=runs, jobs=jobs)
    assert injected.rerun_ids() == ["12"], "打掉上限后本该重复重跑（⇒ 上限判据确有判别力）"


def test_red_proof_scope_widened_touches_other_branches(tmp_path):
    """**红证**（判据④）：打掉 `head_branch` 硬过滤（= 放宽到别的分支）⇒ 别的分支的 run 被重跑。"""
    mutant_script = REAL_LEDGER_SCRIPT.replace(
        '        if str(run.get("head_branch") or "") != head_branch:\n', '        if False:\n', 1)
    assert mutant_script != REAL_LEDGER_SCRIPT, "注入锚点失效（先修本测试）"
    runs, jobs = [gh_run(13, branch="fix/5301-other")], {13: [failed_job()]}
    base = run_rerun(tmp_path / "base", runs=runs, jobs=jobs)
    assert base.rerun_ids() == [], base.reruns
    injected = run_rerun(tmp_path / "inj", script=mutant_script, runs=runs, jobs=jobs)
    assert injected.rerun_ids() == ["13"], "放宽作用域后本该重跑别的分支的 run"
