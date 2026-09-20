# case_ids: MC-012
"""#4825 的兜底判据与结构锁（L0，离线、零 LLM、秒级）。

背景（**实测**，不是照抄 issue 文本）
------------------------------------
`#4804` 的修法（`flaky_ledger.py approve` 批准被 `GITHUB_TOKEN` 抑制的台账 PR run）
**是 `.github/workflows/flaky-triage.yml` 的一个步骤** ⇒ 该 workflow 一停，台账就**静默**停在
`chore/flaky-ledger` 分支上（本 workflow 不参与 required 集合，台账停在分支上不会让任何 PR 变红）。
本文件锁「##4825 的独立兜底」以及**它必须不削弱既有护栏**。

锁五件事（每条的**反向注入**都会让本文件红）
--------------------------------------------
1. **判据是状态级、不是事件级**：`ledger_drift(main, branch)` 必须从**内容**判「分支领先 main」
   （= 已记账却没落 main），与条目顺序无关，且不会把「main 有分支没有」读成正常；
2. **兜底独立于 `flaky-triage.yml`**：触发面**不含** `workflow_run`（同触发面 = 同一个单点），
   且必须有独立入口（`schedule` + `workflow_dispatch` + `pull_request`）；
3. **复用 #4804 的实现、不复制规则**：必须调 `flaky_ledger.py ledger-drift` / `approve`
   （同脚本同参数），`--head-branch` 收敛越权面，`::error::` + `exit 1` fail-closed；
4. **绝不静默降级**：无漂移 ⇒ 零动作；判据「无法判定」⇒ `exit 3` 且 `set -o pipefail` 必须在
   （否则被 `tee` 吞掉 ⇒ 静默 no-op）；有漂移却**没有 open PR** ⇒ 红；兜底后仍 0 check、
   已无待批准 run 且分支陈旧 ⇒ 红；`contents: read`（**不写**台账、**不建 PR** ⇒ 不引入第二个作者）；
5. **既有护栏未被削弱**（逐条锚点 + 注入式红证）：`#4804` 的 approve 步骤仍在**且取 `origin/main`
   的脚本副本**（步骤④ 已把工作区切到台账分支 ⇒ 跑 `.github/scripts/…` 是**分支的旧副本**，实测
   `invalid choice: 'approve'` ⇒ 台账永远落不到 main = 死锁）；`#4717` 的「只标注不自动放行」
   （`gh pr merge … --disable-auto` + 双标签）与台账「只追加 + 幂等」（`git diff --quiet`）一字未动。

红证卫生（照 `migao-dev-flow` §19.1 元规则 ③）：判据读的是**文件内容**（不是 mtime/size），
注入走 `str.replace` 的**内容变异** ⇒ 无缓存可污染（纯文本，不 import 变异体）。
"""
import importlib.util
import json
import re
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPT_PATH = SCRIPTS / "flaky_ledger.py"
TRIAGE_PATH = WORKFLOWS / "flaky-triage.yml"
RECONCILE_PATH = WORKFLOWS / "flaky-ledger-reconcile.yml"

REAL_SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")
REAL_TRIAGE = TRIAGE_PATH.read_text(encoding="utf-8")
REAL_RECONCILE = RECONCILE_PATH.read_text(encoding="utf-8")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mutant(source: str, name: str):
    """把**内容变异**后的脚本源码当模块加载（红证用：判据读内容，免疫 `.pyc` 缓存）。"""
    namespace = {"__name__": name, "__file__": str(SCRIPT_PATH)}
    exec(compile(source, f"<mutant:{name}>", "exec"), namespace)
    return types.SimpleNamespace(**namespace)


FL = _load(SCRIPT_PATH, "migao_flaky_ledger_reconcile")


# ── 夹具：台账条目（只用 `entry_key` 需要的三个字段；形状与真实台账一致） ──────────

def entry(workflow="PR Check", run_id=900001, job="mini-app typecheck + unit tests"):
    return {"workflow": workflow, "run_id": run_id, "job": job,
            "kind": "flaky", "status": "open"}


KEY_A = "PR Check/900001/mini-app typecheck + unit tests"
KEY_B = "Mini-App CI/900002/mini-app typecheck + unit tests"


def ledger(*rows):
    return {"version": 1, "entries": list(rows)}


# ── 判据本体：`ledger_drift`（纯函数，注入变异体后复用同一路径 ⇒ 红证是真的） ───────

def drift_violations(judge) -> list:
    """**判据的本体**（空 = 合规）。`judge` 可以是真模块的函数、也可以是变异体/退化实现。"""
    bad = []

    ahead = judge(ledger(), ledger(entry()))
    if ahead.get("ahead") != [KEY_A]:
        bad.append(f"分支领先 main 时 ahead 必须**逐字列出**未落仓的幂等键，实际 {ahead.get('ahead')!r}")
    if ahead.get("behind") != []:
        bad.append("分支领先 main 时 behind 必须为空（台账只追加 ⇒ main 恒为分支的子集）")
    if ahead.get("main_total") != 0 or ahead.get("branch_total") != 1:
        bad.append(f"条数必须**现取**（期望 main_total=0 / branch_total=1），"
                   f"实际 {ahead.get('main_total')!r}/{ahead.get('branch_total')!r}")

    same = judge(ledger(entry()), ledger(entry()))
    if same.get("ahead") or same.get("behind"):
        bad.append(f"main 与分支一致时必须零漂移（否则兜底在已同步时反复动作），实际 {same!r}")

    diverged = judge(ledger(entry()), ledger())
    if diverged.get("behind") != [KEY_A] or diverged.get("ahead") != []:
        bad.append("main 有分支没有的条目 ⇒ 必须报 behind（台账只追加语义被破坏 = 分叉），"
                   f"实际 {diverged!r}")

    # 顺序无关（拿「列表下标」比对的实现会在这里红）
    unordered = judge(ledger(entry(run_id=1), entry(run_id=2)),
                      ledger(entry(run_id=2), entry(run_id=1)))
    if unordered.get("ahead") or unordered.get("behind"):
        bad.append(f"判据必须与条目顺序无关，实际 {unordered!r}")
    return bad


class TestDriftJudge:
    def test_real_judge_is_clean(self):
        assert drift_violations(FL.ledger_drift) == []

    def test_empty_input_is_not_silently_green(self):
        """退化/空判据不许判绿（否则本文件的守卫会静默空跑）。"""
        assert drift_violations(lambda m, b: {"ahead": [], "behind": [],
                                              "main_total": 0, "branch_total": 0}) != []

    def test_red_proof_always_no_drift(self):
        """红证：把 `ahead` 的差集改成「恒空」（= 永远认为已同步）⇒ 判据必须红。"""
        mutant_src = REAL_SCRIPT.replace("branch_keys - main_keys", "main_keys", 1)
        assert mutant_src != REAL_SCRIPT, "注入锚点失效（先修本测试）"
        assert drift_violations(_load_mutant(mutant_src, "m_flaky_flat").ledger_drift) != []

    def test_red_proof_ahead_behind_swapped(self):
        """红证：把 ahead/behind 的差集对调 ⇒ 判据必须红（方向错了会把分叉当漂移/反之）。"""
        mutant_src = REAL_SCRIPT.replace(
            '"ahead": sorted(_key_str(k) for k in branch_keys - main_keys)',
            '"ahead": sorted(_key_str(k) for k in main_keys - branch_keys)', 1)
        assert mutant_src != REAL_SCRIPT, "注入锚点失效（先修本测试）"
        assert drift_violations(_load_mutant(mutant_src, "m_flaky_swap").ledger_drift) != []

    def test_red_proof_totals_degrade_to_zero(self):
        """红证：把条数写死成 0（不现取）⇒ 判据必须红（硬编码计数会随追加腐烂）。"""
        mutant_src = REAL_SCRIPT.replace('"branch_total": len(branch_keys)',
                                         '"branch_total": 0', 1)
        assert mutant_src != REAL_SCRIPT, "注入锚点失效（先修本测试）"
        assert drift_violations(_load_mutant(mutant_src, "m_flaky_zero").ledger_drift) != []


# ── CLI：`ledger-drift`（离线可复跑；三态退出码） ────────────────────────────────

class TestDriftCli:
    def _run(self, tmp_path, main_rows, branch_rows, branch_file=True):
        main_f = tmp_path / "main.json"
        main_f.write_text(json.dumps(ledger(*main_rows)), encoding="utf-8")
        branch_f = tmp_path / "branch.json"
        branch_f.write_text(json.dumps(ledger(*branch_rows)), encoding="utf-8")
        out = tmp_path / "gh_output"
        out.write_text("", encoding="utf-8")
        argv = ["ledger-drift", "--main-file", str(main_f), "--gh-output", str(out)]
        if branch_file:
            argv += ["--branch-file", str(branch_f)]
        rc = FL.main(argv)
        return rc, out.read_text(encoding="utf-8")

    def test_drift_is_reported_and_wired_to_gh_output(self, tmp_path):
        rc, text = self._run(tmp_path, [], [entry()])
        assert rc == 0, text
        for expected in ("drift=1", "ahead=1", "behind=0", "state=drift"):
            assert expected in text, f"缺 `{expected}`（下游 if 依赖它）：{text!r}"

    def test_in_sync_is_a_clean_no_op(self, tmp_path):
        rc, text = self._run(tmp_path, [entry()], [entry()])
        assert rc == 0, text
        assert "drift=0" in text and "ahead=0" in text and "state=in-sync" in text, text

    def test_divergence_is_reported(self, tmp_path):
        rc, text = self._run(tmp_path, [entry()], [])
        assert rc == 0, text
        assert "drift=0" in text and "behind=1" in text, text

    def test_unreadable_branch_is_undeterminable_not_green(self, tmp_path):
        """**「未跑」必须长得像「未跑」**：读不到分支台账 ⇒ 三态 `3`，不许当「无漂移」。"""
        main_f = tmp_path / "main.json"
        main_f.write_text(json.dumps(ledger()), encoding="utf-8")
        rc = FL.main(["ledger-drift", "--main-file", str(main_f),
                      "--branch-file", str(tmp_path / "missing.json")])
        assert rc == 3, f"无法判定时必须退 3（0 = 会被读成「已同步」），实际 {rc}"


# ── 兜底 workflow 的结构锁 ──────────────────────────────────────────────────────

def _step_text(step) -> str:
    parts = [step.get("run") or "", str((step.get("with") or {}).get("script") or "")]
    env = step.get("env")
    if isinstance(env, dict):
        parts.extend(str(v) for v in env.values())
    return "\n".join(parts)


def _triggers(wf) -> dict:
    return wf.get("on") or wf.get(True) or {}


def audit_reconcile(src: str) -> list:
    """兜底 workflow 结构判据（空 = 合规）。纯函数，注入变异体后复用同一路径。"""
    bad = []
    try:
        wf = yaml.safe_load(src) or {}
    except yaml.YAMLError as exc:
        return [f"workflow YAML 解析失败：{exc}"]

    trig = _triggers(wf)
    # ① 独立兜底：触发面**不许**与 flaky-triage.yml 同源（同源 = 同一个单点，兜底失效）
    if "workflow_run" in trig:
        bad.append("兜底**不许**用 `workflow_run` 触发（那是 flaky-triage.yml 的触发面 ⇒ 同一个单点）")
    for need in ("schedule", "workflow_dispatch", "pull_request"):
        if need not in trig:
            bad.append(f"触发面缺 `{need}`（兜底要独立于 flaky-triage.yml：定时 + 手动 + 近实时）")
    crons = [s.get("cron") for s in (trig.get("schedule") or []) if isinstance(s, dict)]
    if not any(c and re.match(r"^\*/[0-9]+ ", c) for c in crons):
        bad.append(f"schedule 必须是分钟级兜底（`*/N`），实际 {crons}")

    # ② 权限面：approve 需要 actions: write；台账**只读**（不写、不 push、不建 PR）
    perms = {k: str(v).lower() for k, v in (wf.get("permissions") or {}).items()}
    if perms.get("actions") != "write":
        bad.append("permissions.actions 必须 write（approve 被抑制的 run；缺它 ⇒ 403 ⇒ 台账无 check = 静默失效）")
    if perms.get("contents") != "read":
        bad.append("permissions.contents 必须是 **read**（兜底不写台账、不 push、不建 PR ⇒ 不引入第二个作者）")
    if perms.get("pull-requests") != "write":
        bad.append("permissions.pull-requests 必须 write（读台账 PR / arm auto-merge）")

    job = (wf.get("jobs") or {}).get("reconcile") or {}
    steps = job.get("steps") or []
    if not steps:
        return bad + ["reconcile job 没有 steps ⇒ 本守卫会静默空跑（先修 workflow）"]

    for i, step in enumerate(steps):
        if step.get("continue-on-error") not in (None, False):
            bad.append(f"step[{i}] 用了 continue-on-error ⇒ 等于把失败改成通过（红线）")
        extra = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", _step_text(step))) - {"GITHUB_TOKEN"}
        if extra:
            bad.append(f"step[{i}] 引用了 GITHUB_TOKEN 之外的 secrets {sorted(extra)}（红线：不许新增 secret）")

    # ③ 判据必须来自**同一实现**（同脚本同参数，不复制规则），且失败不许被 `tee` 吞掉
    #    ⚠️ 排除引导期的 `--help` 探测步骤：那不是对账判定（否则 `drift_steps[0]` 会指错步骤）。
    drift_steps = [s for s in steps
                   if "flaky_ledger.py ledger-drift" in _step_text(s)
                   and "ledger-drift --help" not in _step_text(s)]
    if not drift_steps:
        bad.append("没有调用 `flaky_ledger.py ledger-drift` 的步骤 ⇒ 兜底判据根本不会被调用")
    else:
        txt = "\n".join(_step_text(s) for s in drift_steps)
        if "drift" not in str(drift_steps[0].get("id") or ""):
            bad.append("判定步骤必须有 `id: drift*`（下游 `if:` 依赖它的输出）")
        if "|" in txt and not re.search(r"(?m)^\s*set\s+-o\s+pipefail\s*$", txt):
            bad.append("判定步骤接了管道却无 `set -o pipefail`（**命令行形态**）⇒ 判据失败（含 exit 3）"
                       "被 `tee` 吞掉、`drift` 输出为空 ⇒ 静默 no-op（红线）")

    # ④ 无漂移 ⇒ 零动作；有漂移 ⇒ 走修复（两分支都必须存在，否则兜底会空转/反复动作）
    ifs = [str(s.get("if") or "") for s in steps]
    if not any(re.search(r"steps\.drift\.outputs\.drift\s*!=\s*'1'", t) for t in ifs):
        bad.append("缺「无漂移 ⇒ 零动作」分支（`if: steps.drift.outputs.drift != '1'`）")
    if not any(re.search(r"steps\.drift\.outputs\.drift\s*==\s*'1'", t) for t in ifs):
        bad.append("缺「有漂移 ⇒ 补 approve + 补 arm」分支（`if: steps.drift.outputs.drift == '1'`）")

    # ④b 引导期：判据/动作都取 **main** 的脚本，而本兜底随 PR 落地 ⇒ PR 未合并时 main 上还没有
    #     `ledger-drift`（实测：首次运行 exit 2「invalid choice: 'ledger-drift'」）。
    #     该形态必须**显式跳过 + 告警**（跳过 ≠ 通过）；且**每个依赖 drift 输出的步骤**都必须
    #     以「引导期就绪」为前置 —— 否则 `drift` 输出为空会让 `drift != '1'` 为真，
    #     于是打印「✅ 台账已与 main 同步」= **假绿**（本单要治的形态同族）。
    pre = [s for s in steps if "ledger-drift --help" in _step_text(s)]
    if not pre or "preflight" not in str(pre[0].get("id") or ""):
        bad.append("缺「引导期」preflight 步骤（`ledger-drift --help` + `id: preflight*`）")
    # ⚠️ **只认命令行形态**（`echo "::warning::`）—— 本步骤的**注释**里恰好写着 `` `::warning::` ``
    #    （说明用），子串判据会被自己的说明文案骗绿。这是本仓库第 4 次踩「提及 ≠ 调用」
    #    （前三次：`--disable-auto` / `autoMergeRequest` / `head_branch=`）。
    elif not re.search(r'(?m)^\s*echo\s+"::warning::', _step_text(pre[0])):
        bad.append("preflight 在「main 还没有判据子命令」时必须 `::warning::`（跳过 ≠ 通过，红线）")
    for i, t in enumerate(ifs):
        if "steps.drift." in t and "steps.preflight.outputs.ready == '1'" not in t:
            bad.append(f"step[{i}] 依赖 drift 输出却没以「引导期就绪」为前置 ⇒ 引导期会打印"
                       f"「✅ 已与 main 同步」= **假绿**（红线）")

    # ⑤ 复用 #4804 的 approve 实现（不复制规则），并保留越权面收敛与 fail-closed
    approve_steps = [s for s in steps if re.search(r"flaky_ledger\.py\s+approve\b", _step_text(s))]
    if not approve_steps:
        bad.append("没有调用 `flaky_ledger.py approve` 的步骤 ⇒ 兜底不复用 #4804 的实现（会与它打架/复制规则）")
    else:
        atxt = "\n".join(_step_text(s) for s in approve_steps)
        if "--head-branch" not in atxt:
            bad.append("兜底 approve 未限定 `--head-branch` ⇒ 可能误批准别人的 run（越权面）")
        if "::error::" not in atxt or "exit 1" not in atxt:
            bad.append("兜底 approve 缺 `::error::` + `exit 1` 的 fail-closed 出口 ⇒ 批准失败会静默"
                       "（台账没 check 却像已放行）（红线）")

    # ⑥ 不静默：无 open PR / 兜底后仍无 check / 分叉 —— 三条都要有可观测信号
    repair = "\n".join(_step_text(s) for s in steps if "ledger-drift" not in _step_text(s))
    if not re.search(r"gh pr list\b[^\n]*--head", repair):
        bad.append("没有 `gh pr list … --head` 找台账 PR ⇒ 无法判定「有没有路径把台账推上 main」")
    if not re.search(r"::error::[^\n]*open PR", repair):
        bad.append("「分支领先 main 却**没有 open PR**」没有 fail-closed 出口（红线：这正是静默停在分支上的形态）")
    if "STALE_MINUTES" not in repair:
        bad.append("缺陈旧阈值 `STALE_MINUTES` ⇒ 无法区分「approve 的异步窗口」与「兜底没生效」")
    if not re.search(r"::error::[^\n]*STALE_MINUTES", repair):
        bad.append("缺「兜底后仍 0 check 且分支陈旧 ⇒ 红」的出口（红线：兜底失败必须可观测）")
    if not (re.search(r'\[ "\$CHECKS" = "0" \]', repair)
            and re.search(r'\[ "\$PENDING" = "0" \]', repair)):
        bad.append("陈旧判据必须同时要求「0 个 check」与「无待批准 run」（否则 approve 的异步窗口会假红）")
    if not re.search(r"::error::[^\n]*分叉", repair):
        bad.append("「main 有分支没有的条目（分叉）」没有可观测信号")
    # ⑦ 不引入第二个作者：兜底**绝不**建 PR、绝不推分支、绝不写台账
    if re.search(r"(?m)^\s*gh pr create\b", repair):
        bad.append("兜底**不许**调 `gh pr create`（建 PR 是 flaky-triage.yml 的职责 ⇒ 两个作者会打架）")
    if re.search(r"(?m)^\s*git push\b", "\n".join(_step_text(s) for s in steps)):
        bad.append("兜底**不许** `git push`（台账只由 flaky-triage.yml 追加 ⇒ 避免与它分叉）")

    # ⑧ 不与 flaky-triage.yml 抢并发组（同组会互相排队/取消）
    group = str((wf.get("concurrency") or {}).get("group") or "")
    if not group or group == "flaky-triage-ledger":
        bad.append(f"concurrency.group 必须独立于 flaky-triage.yml（实际 {group!r}）")
    return bad


class TestReconcileWorkflowStructure:
    def test_real_workflow_is_clean(self):
        assert audit_reconcile(REAL_RECONCILE) == []

    def test_empty_input_is_not_silently_green(self):
        assert audit_reconcile("") != [], "空输入判绿 ⇒ 守卫会静默空跑"

    def test_branch_name_has_a_single_source(self):
        """台账分支名必须与脚本常量同源（写死两份 ⇒ 兜底会对账到一个不存在的分支）。"""
        wf = yaml.safe_load(REAL_RECONCILE) or {}
        env = ((wf.get("jobs") or {}).get("reconcile") or {}).get("env") or {}
        assert env.get("LEDGER_BRANCH") == FL.LEDGER_BRANCH, (
            f"workflow 的 LEDGER_BRANCH={env.get('LEDGER_BRANCH')!r} 与 "
            f"flaky_ledger.LEDGER_BRANCH={FL.LEDGER_BRANCH!r} 不一致")
        assert '"$LEDGER_BRANCH"' in REAL_RECONCILE, "步骤必须引用 `$LEDGER_BRANCH`（不复制字面量）"

    def test_trigger_faces_do_not_overlap_triage(self):
        """两个 workflow 的触发面必须**不相交** —— 否则兜底与主路径同生共死（同一个单点）。"""
        triage = _triggers(yaml.safe_load(REAL_TRIAGE) or {})
        recon = _triggers(yaml.safe_load(REAL_RECONCILE) or {})
        assert set(triage) & set(recon) == set(), (
            f"触发面重叠 {sorted(set(triage) & set(recon))} ⇒ 兜底不是独立的")


class TestReconcileWorkflowRedProofs:
    """注入式红证：每条结构守卫都必须能红（不会红的断言 = 空断言）。"""

    def test_inject_same_trigger_face(self):
        mutated = REAL_RECONCILE.replace(
            "on:\n  pull_request:", "on:\n  workflow_run:\n    types: [completed]\n  pull_request:", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("workflow_run" in v for v in audit_reconcile(mutated))

    def test_inject_dropping_schedule(self):
        mutated = REAL_RECONCILE.replace(
            "  schedule:\n    - cron: '*/20 * * * *'\n", "", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("schedule" in v for v in audit_reconcile(mutated))

    def test_inject_write_access_to_ledger(self):
        """把 `contents: read` 放大成 write ⇒ 兜底会变成第二个「台账作者」⇒ 必红。"""
        mutated = REAL_RECONCILE.replace("  contents: read", "  contents: write", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("contents" in v for v in audit_reconcile(mutated))

    def test_inject_dropping_actions_write(self):
        mutated = REAL_RECONCILE.replace("  actions: write", "  actions: read", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("actions" in v for v in audit_reconcile(mutated))

    def test_inject_removing_pipefail(self):
        """摘掉 `set -o pipefail` ⇒ 判据失败被 `tee` 吞掉 ⇒ 静默 no-op ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace("          set -o pipefail\n", "", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("pipefail" in v for v in audit_reconcile(mutated))

    def test_inject_removing_no_drift_branch(self):
        """摘掉「无漂移 ⇒ 零动作」分支 ⇒ 兜底会在已同步时反复动作 ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(
            "        if: steps.preflight.outputs.ready == '1' && "
            "steps.drift.outputs.drift != '1'\n", "        if: false\n", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("零动作" in v for v in audit_reconcile(mutated))

    def test_inject_removing_no_open_pr_fail_closed(self):
        """摘掉「没有 open PR ⇒ 红」⇒ 台账静默停在分支上（本单要治的形态）⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(
            'echo "::error::台账分支领先 main（${AHEAD} 条未落仓）却**没有 open PR** '
            '⇒ 无任何路径把它推上 main（台账停在分支上）。可行动：重跑 flaky-triage.yml'
            '（由它补建台账 PR）"\n            exit 1',
            'echo "⚠️ 没有 open PR"\n            exit 0', 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        violations = audit_reconcile(mutated)
        assert any("open PR" in v for v in violations), violations

    def test_inject_removing_stale_check_exit(self):
        """摘掉「兜底后仍 0 check 且陈旧 ⇒ 红」⇒ 兜底失败又变回静默 ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(
            'echo "::error::兜底已发出但台账 PR 仍 **0 个 check**、已无待批准 run、'
            '且分支 HEAD 已 ${AGE} 分钟（≥${STALE_MINUTES}）⇒ 台账仍落不到 main（不再静默）"\n'
            '            exit 1',
            'echo "⚠️ 兜底可能没生效"', 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        violations = audit_reconcile(mutated)
        assert any("陈旧" in v for v in violations), violations

    def test_inject_weakening_the_stale_condition(self):
        """陈旧判据少掉「无待批准 run」⇒ approve 的异步窗口会假红 ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(' && [ "$PENDING" = "0" ]', "", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        violations = audit_reconcile(mutated)
        assert any("假红" in v for v in violations), violations

    def test_inject_creating_the_pr_here(self):
        """兜底自己建 PR ⇒ 两个作者对同一分支打架 ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(
            "          # ② 找台账 PR",
            "          gh pr create --base main --head \"$LEDGER_BRANCH\" --title x --body y\n"
            "          # ② 找台账 PR", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("gh pr create" in v for v in audit_reconcile(mutated))

    def test_inject_continue_on_error(self):
        mutated = REAL_RECONCILE.replace(
            "      - name: 台账自检（fail-closed：台账不合规就不参与对账）",
            "      - name: 台账自检\n        continue-on-error: true", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("continue-on-error" in v for v in audit_reconcile(mutated))

    def test_inject_extra_secret(self):
        mutated = REAL_RECONCILE.replace("secrets.GITHUB_TOKEN", "secrets.FLAKY_PAT", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("FLAKY_PAT" in v for v in audit_reconcile(mutated))

    def test_inject_shared_concurrency_group(self):
        mutated = REAL_RECONCILE.replace("  group: flaky-ledger-reconcile",
                                         "  group: flaky-triage-ledger", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        assert any("concurrency" in v for v in audit_reconcile(mutated))

    def test_inject_removing_preflight_guard(self):
        """摘掉某步的「引导期就绪」前置 ⇒ 引导期 `drift` 输出为空 ⇒ 会打印「✅ 已同步」= 假绿 ⇒ 必红。"""
        mutated = REAL_RECONCILE.replace("steps.preflight.outputs.ready == '1' && ", "", 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        violations = audit_reconcile(mutated)
        assert any("假绿" in v for v in violations), violations

    def test_inject_removing_preflight_warning(self):
        """引导期不告警（静默跳过）⇒ 必红。"""
        mutated = REAL_RECONCILE.replace(
            'echo "::warning::main 的 flaky_ledger.py 还没有 \\`ledger-drift\\` 子命令'
            '（引导期：本兜底随 PR 落地，main 尚未包含它）⇒ 本轮**跳过**（跳过 ≠ 通过）"',
            'echo "跳过本轮"', 1)
        assert mutated != REAL_RECONCILE, "注入锚点失效（先修本测试）"
        violations = audit_reconcile(mutated)
        assert any("跳过 ≠ 通过" in v for v in violations), violations


# ── 既有护栏未被削弱（逐条锚点 + 注入式红证） ────────────────────────────────────

def audit_triage_guardrails(src: str) -> list:
    """`flaky-triage.yml` 的护栏锚点（空 = 未被削弱）。本单只**加兜底**，不许动它们。"""
    bad = []
    try:
        wf = yaml.safe_load(src) or {}
    except yaml.YAMLError as exc:
        return [f"triage workflow YAML 解析失败：{exc}"]
    steps = ((wf.get("jobs") or {}).get("triage") or {}).get("steps") or []
    if not steps:
        return ["triage job 没有 steps ⇒ 锚点会静默空跑（先修 workflow）"]

    # ① #4804：approve 被抑制 run 的唯一通路必须还在
    all_txt = "\n".join(_step_text(s) for s in steps)
    approve = [s for s in steps if re.search(r"flaky_ledger\.py\s+approve\b", _step_text(s))]
    if not approve:
        bad.append("① 丢了 `flaky_ledger.py approve` 步骤 ⇒ 台账 PR 的 run 永远 `action_required`"
                   "（零 check）⇒ 台账落不到 main（#4804 红线）")
    else:
        txt = "\n".join(_step_text(s) for s in approve)
        # **#4825 实测的树问题**：步骤④ 已把工作区切到台账分支 ⇒ 跑 `.github/scripts/flaky_ledger.py`
        # 拿到的是**分支的旧副本**（无 approve 子命令）⇒ 必须显式从 `origin/main` 取副本并用它。
        if not re.search(r"git show\s+origin/main:\.github/scripts/flaky_ledger\.py", all_txt):
            bad.append("① 没有任何步骤从 `origin/main` 取脚本副本 ⇒ 步骤④ 之后跑的是台账分支的"
                       "旧副本（实测 `invalid choice: 'approve'`）⇒ 台账永远落不到 main（#4825 红线）")
        # **只认命令行形态**（`python3 .github/scripts/…`）：注释里提到路径不算调用
        # （本仓库「提及 ≠ 调用」已踩三次：`--disable-auto` / `autoMergeRequest` / `head_branch=`）。
        if re.search(r"python3\s+\.github/scripts/flaky_ledger\.py\s+approve", txt):
            bad.append("① approve 仍在跑**工作区**（此时 = 台账分支）里的脚本副本 ⇒ 生产上是死代码"
                       "（实测 `invalid choice: 'approve'`）（#4825 红线）")
        if not re.search(r"python3\s+\S*flaky_ledger\.py\s+approve", txt):
            bad.append("① approve 未以 `python3 …flaky_ledger.py approve` 形态调用（守卫会失效）")
        for anchor in ("--head-branch", "::error::", "branch=$BRANCH"):
            if anchor not in txt:
                bad.append(f"① approve 的护栏锚点 `{anchor}` 丢失")
        if re.search(r"[?&]head_branch=", txt):
            bad.append("① approve 出现了 `&head_branch=`（API 静默忽略该参数名 ⇒ 读数指向全仓）")

    # ② #4717：只标注不自动放行
    flaky = [s for s in steps if "mark_flaky" in str(s.get("if") or "")]
    if not flaky:
        bad.append("② 丢了 `mark_flaky` 步骤 ⇒ 「只标注不自动放行」无处落地（#4717 红线）")
    else:
        ftxt = "\n".join(_step_text(s) for s in flaky)
        if not re.search(r"gh pr merge\b[^\n]*--disable-auto", ftxt):
            bad.append("② 丢了 `gh pr merge … --disable-auto`（**调用形态**）⇒ 已 arm 的 auto-merge "
                       "拦不住 = 自动放行（红线）")
        for label in (FL.FLAKY_LABEL, FL.BLOCK_LABEL):
            if f'--add-label "{label}"' not in ftxt:
                bad.append(f"② 丢了 `--add-label \"{label}\"` ⇒ 标注不可见（红线）")

    # ③ 台账只追加 + 幂等（兜底**不**碰台账写路径，故这两条必须原样在）
    led = [s for s in steps if "flaky_ledger.py append" in _step_text(s)]
    if not led or "git diff --quiet" not in "\n".join(_step_text(s) for s in led):
        bad.append("③ 丢了台账 `git diff --quiet` 幂等闸 ⇒ 同一次失败可能重复记账（只追加/幂等红线）")
    return bad


class TestExistingGuardrailsIntact:
    def test_no_guardrail_was_weakened(self):
        assert audit_triage_guardrails(REAL_TRIAGE) == []

    def test_empty_input_is_not_silently_green(self):
        assert audit_triage_guardrails("") != [], "空输入判绿 ⇒ 锚点会静默空跑"

    def test_red_proof_disarm_auto_merge_removed(self):
        """摘掉 `--disable-auto`（**调用形态**）⇒ 自动放行 ⇒ 必红。

        ⚠️ 同一 run 块的**提示文案**里仍留着 `--disable-auto` 字样 —— 判据只认调用形态，
        故「摘掉真命令」必须红（这正是「提及 ≠ 调用」的现场，见 #4717 守卫同款教训）。
        """
        mutated = REAL_TRIAGE.replace('gh pr merge "$PR_NUMBER" --disable-auto',
                                      'gh pr merge "$PR_NUMBER"', 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        assert 'echo "ℹ️ --disable-auto' in mutated, "夹具前提变了（先修本测试）"
        assert any("--disable-auto" in v for v in audit_triage_guardrails(mutated))

    def test_red_proof_block_label_removed(self):
        mutated = REAL_TRIAGE.replace(
            f'          gh pr edit "$PR_NUMBER" --add-label "{FL.BLOCK_LABEL}"'
            f' --repo "$GITHUB_REPOSITORY"\n', "", 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        assert any(FL.BLOCK_LABEL in v for v in audit_triage_guardrails(mutated))

    def test_red_proof_idempotency_gate_removed(self):
        mutated = REAL_TRIAGE.replace("          if git diff --quiet -- .github/flaky-ledger.json; then",
                                      "          if false; then", 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        assert any("幂等闸" in v for v in audit_triage_guardrails(mutated))

    def test_red_proof_main_copy_reverted_to_branch_copy(self):
        """把脚本副本的来源改掉（不再取 `origin/main`）⇒ 回到「跑台账分支旧副本」的死锁 ⇒ 必红。"""
        mutated = REAL_TRIAGE.replace(
            "git show origin/main:.github/scripts/flaky_ledger.py",
            "git show origin/chore-flaky-ledger:.github/scripts/flaky_ledger.py", 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        violations = audit_triage_guardrails(mutated)
        assert any("origin/main" in v for v in violations), violations

    def test_red_proof_approve_runs_the_workspace_copy(self):
        """把 approve 改回跑**工作区**里的脚本（= 台账分支旧副本）⇒ 死锁复发 ⇒ 必红。"""
        mutated = REAL_TRIAGE.replace("python3 /tmp/flaky_ledger.py approve",
                                      "python3 .github/scripts/flaky_ledger.py approve", 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        violations = audit_triage_guardrails(mutated)
        assert any("工作区" in v for v in violations), violations

    def test_red_proof_head_branch_removed(self):
        mutated = REAL_TRIAGE.replace('--head-branch "$BRANCH"', "", 1)
        assert mutated != REAL_TRIAGE, "注入锚点失效（先修本测试）"
        assert any("--head-branch" in v for v in audit_triage_guardrails(mutated))
