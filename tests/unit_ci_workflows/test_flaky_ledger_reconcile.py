# case_ids: MC-012, MC-195
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
   （否则被 `tee` 吞掉 ⇒ 静默 no-op）；有漂移却**没有 open PR** ⇒ **机械补建**（#8628：幂等，
   建不出来才红）；兜底后仍 0 check、已无待批准 run 且分支陈旧 ⇒ 红；
   `contents: read`（**不写**台账内容 ⇒ 不引入第二个作者；#8628 的建 PR 是唯一例外，
   且自建的 PR **不 arm**）；
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

import pytest
import yaml

from unit_ci_workflows.injection import inject

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


def _code_lines(text: str) -> str:
    """只保留**命令行形态**（剔除整行注释）—— 本仓「提及 ≠ 调用」纪律（已踩四次）：
    判据读注释里的字面量会被自己的说明文案骗绿/骗红。"""
    return "\n".join(ln for ln in (text or "").splitlines() if not ln.lstrip().startswith("#"))


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
    #    ⚠️ 定位方式 = **`id: drift*`**（不是「文本里含 `flaky_ledger.py ledger-drift`」）：
    #    #5310 起，**修复步骤自己也调** `ledger-drift`（报红前用同一实时读法**复核一次**）⇒
    #    旧的文本启发式会把两个步骤混在一起，`drift_steps[0]` 与「接管道必须有 pipefail」
    #    都指错对象。定位失效 ⇒ 显式违规（**不许**静默空跑）。
    judge = [s for s in steps if str(s.get("id") or "").startswith("drift")]
    if not judge:
        bad.append("没有 `id: drift*` 的判定步骤 ⇒ 没有调用 `flaky_ledger.py ledger-drift` 的步骤"
                   "（兜底判据根本不会被调用；下游 `if:` 也失去依赖）")
    else:
        # ⚠️ 排除引导期的 `--help` 探测步骤：那不是对账判定。
        drift_steps = [s for s in judge if "ledger-drift --help" not in _step_text(s)]
        if not drift_steps:
            bad.append("判定步骤（`id: drift*`）里没有调用 `flaky_ledger.py ledger-drift` 的步骤"
                       " ⇒ 兜底判据根本不会被调用")
        else:
            txt = _code_lines(_step_text(drift_steps[0]))
            if "flaky_ledger.py ledger-drift" not in txt:
                bad.append("判定步骤（`id: drift*`）里没有调用 `flaky_ledger.py ledger-drift` 的步骤"
                           " ⇒ 兜底判据根本不会被调用")
            if "|" in txt and not re.search(r"(?m)^\s*set\s+-o\s+pipefail\s*$", txt):
                bad.append("判定步骤接了管道却无 `set -o pipefail`（**命令行形态**）⇒ 判据失败（含 exit 3）"
                           "被 `tee` 吞掉、`drift` 输出为空 ⇒ 静默 no-op（红线）")
            # ⑨ #5310 **类级元守卫**：判据不许**跨时刻 / 跨面拼接**。
            #    类别形态 = 本 workflow 在**实时**查询外部状态（`gh pr list`），而判定侧读的是
            #    另一个时刻/另一个面的读数（job 启动时的**检出快照**）⇒ 台账 PR 恰在窗口内合并
            #    就得到「领先却无 PR」的**假红**（实测 run 35951257498：启动 03:23:37、报错
            #    03:23:55，PR #5139 在 03:23:46 合并；报「24 条未落仓」= 分支 72 − 旧快照 main 48，
            #    真实 key 差 = ahead 0 / behind 0）。**这条拦的是类别**：下一个人换一种快照读法
            #    （摘掉 `--main-live`、或再挂一个 `--main-file`）都会红，而不只是钉某一处写法。
            #    ⚠️ 判据读**命令行形态**（`_code_lines`）—— 本步骤的注释里恰好写着「旧口径 =
            #    `--main-file`」（说明用），子串判据会被自己的说明文案骗红。
            live_pr = any(re.search(r"gh pr list\b", _code_lines(_step_text(s))) for s in steps)
            if live_pr:
                if "--main-live" not in txt or "--repo" not in txt:
                    bad.append("#5310 类级元守卫（跨时刻读数）：本 workflow 在**实时**查询 PR，"
                               "而 drift 判定的 main 侧不是实时读（缺 `--main-live`/`--repo`）"
                               "⇒ 判据跨了两个时刻（快照 vs 实时）")
                if re.search(r"--main-file\b", txt):
                    bad.append("#5310 类级元守卫（跨时刻读数）：drift 判定同时挂了 `--main-file`"
                               "（检出快照）⇒ 一半快照一半实时")

    # ④ 无漂移 ⇒ 零动作；有漂移 ⇒ 走修复（两分支都必须存在，否则兜底会空转/反复动作）
    #    ⚠️ 「有漂移 ⇒ …」这一半的定位方式 = **步骤名**（同 ⑥ 的既有口径）：#5301 起还有**第二个**
    #    步骤以「有漂移」为前置（兜底重跑）⇒ 旧的「全步骤文本扫描」会被那一步**遮挡**（把修复步骤
    #    那个闸摘掉也照样通过 = 空断言，实测被本单的新步骤命中）。
    repair_if = [str(s.get("if") or "") for s in steps
                 if str(s.get("name") or "").startswith("有漂移 ⇒")]
    ifs = [str(s.get("if") or "") for s in steps]
    if not any(re.search(r"steps\.drift\.outputs\.drift\s*==\s*'1'", t) for t in repair_if):
        bad.append("缺「有漂移 ⇒ 补 approve + 补 arm」分支（`if: steps.drift.outputs.drift == '1'`）")
    if not any(re.search(r"steps\.drift\.outputs\.drift\s*!=\s*'1'", t) for t in ifs):
        bad.append("缺「无漂移 ⇒ 零动作」分支（`if: steps.drift.outputs.drift != '1'`）")

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
        # ⚠️ 判据必须**绑定到 approve 这条命令本身**：同一步骤里还有别的 fail-closed 出口
        #    （读不到 pending.json / 没有 open PR / 陈旧）⇒ 只看「文本里存在 `::error::` + `exit 1`」
        #    会被它们**骗绿** —— 摘掉 approve 自己的出口也照样通过 = **空断言**（反向红证
        #    `approve_without_fail_closed` 就是钉这个）。故要求 `|| { … }` 落在 approve 命令的
        #    3 行以内，再在**紧随其后**的块里找出口。
        m = re.search(r"flaky_ledger\.py\s+approve(?:[^\n]*\n){0,2}[^\n]*\|\|\s*\{", atxt)
        if not m:
            bad.append("兜底 approve 缺 `|| { … }` 的 fail-closed 出口 ⇒ 批准失败会静默"
                       "（台账没 check 却像已放行）（红线）")
        else:
            tail = atxt[m.end():m.end() + 400]
            if "::error::" not in tail or "exit 1" not in tail:
                bad.append("兜底 approve 的 fail-closed 出口缺 `::error::` 或 `exit 1`（红线）")

    # ⑥ 不静默：无 open PR / 兜底后仍无 check / 分叉 —— 三条都要有可观测信号
    #    ⚠️ 定位方式 = **步骤名**（`有漂移 ⇒` / `分叉告警`），不是「文本里不含 `ledger-drift`」：
    #    #5310 起修复步骤自己也调 `ledger-drift`（判据收尾复核）⇒ 旧启发式会把它**整段排除**
    #    ⇒ ⑥⑦ 全部空跑 = **空断言**。找不到这些步骤 ⇒ 显式违规（定位失效必须红，不许静默）。
    repair_steps = [s for s in steps
                    if str(s.get("name") or "").startswith(("有漂移 ⇒", "分叉告警"))]
    missing = [p for p in ("有漂移 ⇒", "分叉告警")
               if not any(str(s.get("name") or "").startswith(p) for s in steps)]
    if missing:
        bad.append(f"找不到「有漂移 ⇒ …」/「分叉告警」步骤（缺 {missing}）⇒ ⑥⑦ 的定位失效"
                   "（本守卫会静默空跑，先修 workflow/本测试）")
    repair = "\n".join(_step_text(s) for s in repair_steps)
    # ⚠️ 判据读**命令行形态**（剔除整行注释）：本步骤的注释里也写着 `ensure-pr` /
    #    `flaky-ledger-autopr`（说明用）⇒ 子串判据会被自己的说明文案骗绿（本仓「提及 ≠ 调用」）。
    rcode = _code_lines(repair)
    if not re.search(r"gh pr list\b[^\n]*--head", repair):
        bad.append("没有 `gh pr list … --head` 找台账 PR ⇒ 无法判定「有没有路径把台账推上 main」")
    # ⑬ #8628：**台账领先 main 却没有任何 open PR** ⇒ **机械补建**（幂等），而不是判红。
    #    病（实测两次）：旧口径把「没有 PR」判红（「建 PR 是 flaky-triage.yml 的职责」），而
    #    flaky-triage.yml **只在有新的终态事件时**才补建 PR ⇒ 该状态下没有任何路径把台账推上 main
    #    ⇒ 腿在**每一个** PR 上报红，只能靠人**手工开 PR**压住（#8604 / #8612 两次）。
    #    ⚠️ 判据只认**调用形态**（`^\s*python3 …flaky_ledger.py ensure-pr`）：同一步骤的注释里
    #    也写着 `ensure-pr`（说明用）—— 子串判据会被自己的说明文案喂绿（本仓「提及 ≠ 调用」）。
    ensure_steps = [s for s in steps
                    if re.search(r"(?m)^\s*python3\s+\S*flaky_ledger\.py\s+ensure-pr\b",
                                 _code_lines(_step_text(s)))]
    if not ensure_steps:
        bad.append("#8628：没有任何步骤调 `flaky_ledger.py ensure-pr` ⇒ 台账领先却没 PR 时又回到"
                   "「判红 / 靠人手动开 PR」= 本单要治的形态（调用形态判据）")
    else:
        etxt = _step_text(ensure_steps[0])
        ecode = _code_lines(etxt)
        # ⚠️ 作用域判据必须**只看 ensure-pr 那几行**：同一步骤里还有 `ledger-drift --branch
        #    "$LEDGER_BRANCH"`（复核）⇒ 全步骤子串判据会把「ensure-pr 没绑分支」判绿（空断言）。
        mcall = re.search(r"(?m)^\s*python3\s+\S*flaky_ledger\.py\s+ensure-pr\b(?:[^\n]*\n){0,2}",
                          ecode)
        seg = mcall.group(0) if mcall else ""
        for flag, why in (('--repo "$GITHUB_REPOSITORY"',
                           "未把仓库显式绑到本次 run（可能对别的仓建 PR）"),
                          ('--branch "$LEDGER_BRANCH"',
                           "未把 head 显式绑到台账分支（作用域越权）")):
            if flag not in seg:
                bad.append(f"#8628：`ensure-pr` {why}（缺 `{flag}`）")
        # 幂等（顺序即安全顺序）：补建必须挂在「**没有** open PR」这个闸**之后**。
        if '[ -z "$PR" ]' not in ecode:
            bad.append("#8628：`ensure-pr` 必须挂在「没有 open PR」分支里（已有 open PR ⇒ 零动作）")
        elif ecode.index("flaky_ledger.py ensure-pr") < ecode.index('[ -z "$PR" ]'):
            bad.append("#8628：`ensure-pr` 出现在「没有 open PR」闸**之前** ⇒ 已有 PR 时也会建"
                       "（幂等被破坏 = 每轮重复建 PR）")
        # 建不出来 ⇒ 必须**响**（一行可行动出口），不许被读成「无事可做」。
        # 两条出口**分开判**：只说「有 `::error::`」会被另一条出口骗绿（本仓已踩多次的同款空断言）。
        fail_line = [ln for ln in ecode.splitlines() if "补建 PR 失败" in ln]
        if not fail_line or "::error::" not in fail_line[0] or "exit 1" not in fail_line[0]:
            bad.append("#8628：`ensure-pr` **建 PR 失败**的那条出口必须 `::error::` + `exit 1`"
                       "（一条可行动的行；否则失败被读成「无事可做」= 静默，红线）")
        und_line = [ln for ln in ecode.splitlines() if "ensure-pr 退 3" in ln]
        if not und_line or "::error::" not in und_line[0]:
            bad.append("#8628：`ensure-pr` 的**无法判定**（退 3）缺 `::error::` 出口 ⇒ 未跑会被读成通过")
        if not re.search(r"::error::[^\n]*gh pr create --base", etxt):
            bad.append("#8628：建 PR 失败的错误文案必须带**可复制出口**（`gh pr create --base …`）"
                       "—— 出口必须真的可行动")
    # ⑭ #8628：**不许自开自合** —— 本腿自己建的 PR（body 带标记）不 arm；且绝不用 `--admin`。
    all_steps_txt = "\n".join(_step_text(s) for s in steps)
    if re.search(r"gh\s+pr\s+merge\b[^\n]*--admin", _code_lines(all_steps_txt)):
        bad.append("红线：workflow 里出现 `gh pr merge --admin`（绕过必需检查；#8628 明令禁止）")
    # ⚠️ 判据认**分支臂形态**（`*flaky-ledger-autopr*)`），不是「文本里出现过这个字面量」——
    #    后者会被 ARM_LINE 的说明文案喂绿（摘掉分支照样通过 = 空断言）。
    if not re.search(r"(?m)^\s*\*flaky-ledger-autopr\*\)\s*$", rcode):
        bad.append("#8628：本腿自建的 PR 必须按 `flaky-ledger-autopr` 标记**跳过 arm**"
                   "（自己开 + 自己 arm = 自开自合；人要能看见并复核）")
    elif not re.search(r'(?m)^\s*echo\s+"::notice::[^\n]*(不 arm|跳过)', repair):
        bad.append("#8628：跳过 arm 时必须 `::notice::` 出声（不许静默跳过 —— 跳过 ≠ 通过）")
    # ⑪ #5307 可见性：**台账分支**的欠账必须落在某个消费面（job summary + `::error::`）。
    #    类别形态 = 「判据判红但没有任何人看」（这条 required 测试在台账分支上恒红约 40 小时，
    #    而不在 required 集合 + `flaky-triage` 按自指守卫跳过该分支 + 本兜底原先只补 approve/arm）。
    #    ⚠️ 判据只认**调用形态**（`^\s*python3 … reconcile --branch`）：同一步骤的引导期 `::warning::`
    #    文案里恰好也写着 `reconcile --branch`（说明用）—— 子串判据会被自己的文案喂绿（本仓已踩五次）。
    debt = [s for s in steps
            if re.search(r"(?m)^\s*python3\s+\S*flaky_ledger\.py\s+reconcile\s+--branch\b",
                         _code_lines(_step_text(s)))]
    if not debt:
        bad.append("#5307 可见性：没有任何步骤对账**台账分支**的欠账（`reconcile --branch`）"
                   "⇒ 台账分支的确定性失败仍无消费面")
    else:
        dtxt = _step_text(debt[0])
        if not re.search(r"::error::[^\n]*欠账", dtxt):
            bad.append("#5307 可见性：欠账步骤缺 `::error::`（红得不可归因）")
        if "GITHUB_STEP_SUMMARY" not in dtxt:
            bad.append("#5307 可见性：欠账清单没写进 job summary（人看不到清单与回填命令）")
    # ⑫ #5301 判据②：**台账分支不许留白** —— 台账分支上的失败 job 必须有**自动重跑**路径。
    #    类别形态 = 「分支上的失败 job 没有任何自动重跑路径，只能人工救」：
    #    `flaky-triage.yml` 的 `decide()` 按**自指守卫**逐字判 `head_branch == LEDGER_BRANCH` ⇒ skip
    #    （防自指递归）⇒ 那条路**结构上**不救它；而本兜底原先只补 approve/arm、不读失败原因更不重跑
    #    ⇒ 台账 PR 撞一次确定性失败就停摆（**实测** 4 次尝试同形失败、约 40 小时无人救）。
    #    ⚠️ **可见 ≠ 有救援**（#5307 只做了可见性）⇒ 本条判的是「有救援」。
    #    ⚠️ 判据只认**调用形态**（同 ⑪）：本步骤的注释里也写着 `rerun-failed`（说明用）——
    #    子串判据会被自己的说明文案喂绿（本仓「提及 ≠ 调用」已踩多次）。
    rerun_steps = [s for s in steps
                   if re.search(r"(?m)^\s*python3\s+\S*flaky_ledger\.py\s+rerun-failed\b",
                                _code_lines(_step_text(s)))]
    if not rerun_steps:
        bad.append("#5301 判据②：没有任何步骤重跑台账分支的失败 job（`rerun-failed` 调用形态）"
                   "⇒ 台账分支的确定性失败仍**只能人工救**（判据② 不许留白）")
    else:
        rtxt = _step_text(rerun_steps[0])
        rcode = _code_lines(rtxt)
        if '--branch "$LEDGER_BRANCH"' not in rcode:
            bad.append('#5301 判据④：兜底重跑未把作用域绑到 `--branch "$LEDGER_BRANCH"`（命令行形态）'
                       "⇒ 可能重跑**别的分支**的 run（作用域越权）")
        if "GITHUB_STEP_SUMMARY" not in rcode:
            bad.append("#5301 判据②：兜底重跑的**记账**没落进 job summary ⇒「重跑了哪个 job / 结果如何」不可见")
        if not re.search(r"::error::[^\n]*退 3", rtxt):
            bad.append("#5301 判据②：兜底重跑缺「**无法判定**（退 3）⇒ 红」的出口 ⇒ 未跑会被读成通过")
        if not re.search(r"::error::[^\n]*无人救", rtxt):
            bad.append("#5301 判据②：兜底重跑的动作失败缺 fail-closed 出口（`::error::` 无人救）"
                       "⇒ 重跑没发出去也不红 = 静默")
        if "rerun-failed --help" not in rcode or not re.search(r'(?m)^\s*echo\s+"::warning::', rtxt):
            bad.append("#5301 判据②：缺引导期探测（`rerun-failed --help` + `::warning::`）⇒ main 还没有"
                       "该子命令时 argparse 退 2 会被读成「兜底失败」= 假红（同 `ledger-drift` 既有形态）")
        if not re.search(r"steps\.drift\.outputs\.drift\s*==\s*'1'",
                         str(rerun_steps[0].get("if") or "")):
            bad.append("#5301 判据②：兜底重跑没以「**有漂移**」为前置 ⇒ 台账已同步时仍会白烧 CI 分钟"
                       "（与既有两处「无事可做 ⇒ 零动作」同口径）")
    # ⚠️ 阈值判据读 **job env**（不是「文本里提到过 STALE_MINUTES」）：后者会被报错文案里的
    #    `${STALE_MINUTES}` 自己骗绿 —— 把阈值定义删掉也照样通过 = 空断言。
    stale = str((job.get("env") or {}).get("STALE_MINUTES") or "")
    if not stale.isdigit() or int(stale) <= 0:
        bad.append(f"job env 缺正整数 `STALE_MINUTES`（实际 {stale!r}）⇒ 无法区分「approve 的异步"
                   f"窗口」与「兜底没生效」")
    if not re.search(r"::error::[^\n]*STALE_MINUTES", repair):
        bad.append("缺「兜底后仍 0 check 且分支陈旧 ⇒ 红」的出口（红线：兜底失败必须可观测）")
    if not (re.search(r'\[ "\$CHECKS" = "0" \]', repair)
            and re.search(r'\[ "\$PENDING" = "0" \]', repair)):
        bad.append("陈旧判据必须同时要求「0 个 check」与「无待批准 run」（否则 approve 的异步窗口会假红）")
    if not re.search(r"::error::[^\n]*分叉", repair):
        bad.append("「main 有分支没有的条目（分叉）」没有可观测信号")
    # ⑦ 不引入第二个**台账内容**作者：兜底绝不推分支、绝不写台账；
    #    建 PR 只许走**唯一实现**（`ensure-pr`）—— 内联 `gh pr create` 会让文案与幂等逻辑出现第二份，
    #    且判据没法在不建真 PR 的前提下断言「到底调没调」（#8628）。
    if re.search(r"(?m)^\s*gh pr create\b", _code_lines(repair)):
        bad.append("#8628：建 PR 必须走唯一实现 `flaky_ledger.py ensure-pr`；"
                   "workflow 里**不许**内联 `gh pr create`（文案/幂等规则会漂成两份）")
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

    def test_autopr_marker_has_a_single_source(self):
        """#8628：workflow 按标记跳过 arm，而标记常量在脚本里 —— 两处必须同值（否则永不跳过）。"""
        bad = []
        if FL.AUTOPR_TOKEN not in FL.AUTOPR_MARKER:
            bad.append("AUTOPR_MARKER 必须由 AUTOPR_TOKEN 拼出（单一事实源）")
        if f"*{FL.AUTOPR_TOKEN}*)" not in REAL_RECONCILE:
            bad.append(f"workflow 没有按脚本的 AUTOPR_TOKEN（{FL.AUTOPR_TOKEN!r}）分支 ⇒ "
                       f"本腿自建的 PR 仍会被 arm（自开自合）")
        if FL.AUTOPR_TITLE not in REAL_TRIAGE:
            bad.append(f"建 PR 的标题必须与唯一既有文案同源（flaky-triage.yml 里没有 "
                       f"{FL.AUTOPR_TITLE!r}）⇒ 会漂成两份")
        assert bad == []

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

    def test_inject_removing_the_autopr_call(self):
        """#8628：摘掉 `ensure-pr` 调用 ⇒ 台账领先却没 PR 时又回到「判红 / 靠人手动开」⇒ 必红。"""
        mutated = inject(
            REAL_RECONCILE,
            "            python3 .github/scripts/flaky_ledger.py ensure-pr \\\n", "",
            where=".github/workflows/flaky-ledger-reconcile.yml")
        violations = audit_reconcile(mutated)
        assert any("ensure-pr" in v for v in violations), violations

    def test_inject_removing_the_autopr_failure_exit(self):
        """#8628：把「建 PR 失败 ⇒ 红」的出口摘掉（改成不痛不痒的 echo）⇒ 静默通过 ⇒ 必红。"""
        mutated = inject(
            REAL_RECONCILE,
            "              *) echo \"::error::台账领先 main 却**补建 PR 失败**"
            "（ensure-pr 退 ${ENSURE_RC}）⇒ 台账仍停在分支上、main 不增长；"
            "明细见上方 ⛔ 行。可复制出口：gh pr create --base main --head $LEDGER_BRANCH "
            "--title 'chore(ci): flaky 台账滚动追加' --repo $GITHUB_REPOSITORY\"; exit 1 ;;",
            '              *) echo "⚠️ 补建失败"; exit 0 ;;', where=".github/workflows/flaky-ledger-reconcile.yml")
        violations = audit_reconcile(mutated)
        assert any("建 PR 失败" in v for v in violations), violations

    def test_inject_arming_the_autopr_pr(self):
        """#8628 红线：摘掉「自建 PR 不 arm」的标记分支 ⇒ **自己开 + 自己 arm** = 自开自合 ⇒ 必红。"""
        mutated = inject(REAL_RECONCILE, "            *flaky-ledger-autopr*)\n",
                         "            *NO_SUCH_MARKER*)\n", where=".github/workflows/flaky-ledger-reconcile.yml")
        violations = audit_reconcile(mutated)
        assert any("flaky-ledger-autopr" in v for v in violations), violations

    def test_inject_admin_merge(self):
        """#8628 红线：出现 `gh pr merge --admin`（绕过必需检查）⇒ 必红。"""
        mutated = inject(REAL_RECONCILE,
                         'ARM_OUT=$(gh pr merge "$PR" --auto --squash',
                         'ARM_OUT=$(gh pr merge "$PR" --admin --auto --squash', where=".github/workflows/flaky-ledger-reconcile.yml")
        violations = audit_reconcile(mutated)
        assert any("--admin" in v for v in violations), violations

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


# ── 逐条判据的反向红证（#4825 验收判据：**每条判据都要会红**；不会红的判据 = 空断言） ────
#
# 上面的 class 各带若干条红证，但「覆盖率」本身就是本单的验收判据 ⇒ 这里用**表驱动**把
# `audit_reconcile` / `audit_triage_guardrails` 的**每条违规出口**都钉一遍：一条判据一个变异，
# 注入后必须命中该条（`expected` = 判据文案里的**稳定片段**，不是整句 —— 文案可以改，判据不许丢）。
# 红证卫生（§19.1 元规则 ③）：判据读**内容**，每行注入前先自证 `mutated != src`（锚点漂了就红）。

def _mutate(src: str, old: str, new: str = "", count: int = 1) -> str:
    mutated = src.replace(old, new, count)
    assert mutated != src, f"注入锚点失效（先修本测试）：{old!r}"
    return mutated


RECONCILE_RED_PROOFS = [
    ("no_pull_request_trigger", "on:\n  pull_request:", "on:\n  x_pull_request:", "缺 `pull_request`"),
    ("no_workflow_dispatch", "  workflow_dispatch:\n", "", "缺 `workflow_dispatch`"),
    ("cron_not_minute_level", "*/20 * * * *", "0 3 * * 1", "分钟级兜底"),
    ("pull_requests_permission_downgraded", "  pull-requests: write", "  pull-requests: read",
     "pull-requests 必须 write"),
    ("judge_step_id_renamed", "\n        id: drift\n", "\n        id: judge\n", "`id: drift*`"),
    ("judge_invocation_renamed", "flaky_ledger.py ledger-drift \\\n",
     "flaky_ledger.py judge-drift \\\n", "没有调用 `flaky_ledger.py ledger-drift` 的步骤"),
    ("no_drift_repair_branch",
     "        if: steps.preflight.outputs.ready == '1' && steps.drift.outputs.drift == '1'\n",
     "        if: false\n", "有漂移"),
    ("no_preflight_probe",
     "if python3 .github/scripts/flaky_ledger.py ledger-drift --help >/dev/null 2>&1; then",
     "if true; then", "缺「引导期」preflight 步骤"),
    ("no_approve_reuse", "flaky_ledger.py approve \\\n", "flaky_ledger.py approve_old \\\n",
     "没有调用 `flaky_ledger.py approve` 的步骤"),
    ("approve_without_head_branch", '--head-branch "$LEDGER_BRANCH"', '--any-branch "$LEDGER_BRANCH"',
     "未限定 `--head-branch`"),
    ("approve_without_fail_closed",
     '            --json-out /tmp/pending.json || {\n'
     '            echo "::error::兜底 approve 失败 ⇒ 台账 PR 仍无 check、main 不增长'
     '（fail-closed，不静默）"; exit 1; }',
     '            --json-out /tmp/pending.json', "fail-closed 出口"),
    ("no_pr_lookup_by_head", 'PR=$(gh pr list --head "$LEDGER_BRANCH" --state open --json number',
     'PR=$(gh pr list --state open --json number', "`gh pr list … --head`"),
    ("stale_threshold_env_removed", "      STALE_MINUTES: '15'\n", "", "STALE_MINUTES"),
    ("divergence_signal_removed", 'echo "::error::台账分叉：', 'echo "⚠️ 台账分叉：', "分叉"),
    ("fallback_pushes_branch", "          # ② 找台账 PR",
     "          git push origin HEAD:main\n          # ② 找台账 PR", "`git push`"),
    # ── #5310：两条**类级元守卫**各自的红证（把实现退回「拼接」形态 ⇒ 必红）──────────────
    ("repair_step_renamed", "      - name: 有漂移 ⇒ 补 approve", "      - name: 修复步骤",
     "找不到「有漂移 ⇒"),
    ("main_side_not_live",
     '            --branch "$LEDGER_BRANCH" --main-live --repo "$GITHUB_REPOSITORY" \\\n'
     '            --gh-output "$GITHUB_OUTPUT"',
     '            --branch "$LEDGER_BRANCH" \\\n            --gh-output "$GITHUB_OUTPUT"',
     "类级元守卫（跨时刻读数）"),
    ("main_side_snapshot_spliced_in",
     '            --branch "$LEDGER_BRANCH" --main-live --repo "$GITHUB_REPOSITORY" \\\n'
     '            --gh-output "$GITHUB_OUTPUT"',
     '            --main-file .github/flaky-ledger.json --branch "$LEDGER_BRANCH" --main-live '
     '--repo "$GITHUB_REPOSITORY" \\\n            --gh-output "$GITHUB_OUTPUT"',
     "一半快照一半实时"),
    # ── #8628：建 PR 的唯一实现 / 幂等 / 失败要响 / 不许自开自合 ───────────────────
    ("ensure_pr_call_removed",
     '            python3 .github/scripts/flaky_ledger.py ensure-pr \\\n',
     '', "#8628：没有任何步骤调 `flaky_ledger.py ensure-pr`"),
    ("ensure_pr_head_unbound",
     '              --repo "$GITHUB_REPOSITORY" --branch "$LEDGER_BRANCH" \\\n'
     '              --json-out /tmp/ensure-pr.json',
     '              --repo "$GITHUB_REPOSITORY" --branch "$GITHUB_HEAD_REF" \\\n'
     '              --json-out /tmp/ensure-pr.json',
     "#8628：`ensure-pr` 未把 head 显式绑到台账分支"),
    ("ensure_pr_before_absence_gate",
     '          PR=$(gh pr list --head "$LEDGER_BRANCH" --state open --json number \\\n',
     '          python3 .github/scripts/flaky_ledger.py ensure-pr --repo x --branch y\n'
     '          PR=$(gh pr list --head "$LEDGER_BRANCH" --state open --json number \\\n',
     "#8628：`ensure-pr` 出现在「没有 open PR」闸**之前**"),
    ("ensure_pr_failure_swallowed",
     "明细见上方 ⛔ 行。可复制出口：gh pr create --base main --head $LEDGER_BRANCH "
     "--title 'chore(ci): flaky 台账滚动追加' --repo $GITHUB_REPOSITORY\"; exit 1 ;;",
     '明细见上方 ⛔ 行"; exit 1 ;;',
     "#8628：建 PR 失败的错误文案必须带**可复制出口**"),
    ("autopr_marker_branch_removed",
     "            *flaky-ledger-autopr*)\n", "            *NO_SUCH_MARKER*)\n",
     "#8628：本腿自建的 PR 必须按 `flaky-ledger-autopr` 标记"),
    ("admin_merge_allowed",
     'ARM_OUT=$(gh pr merge "$PR" --auto --squash',
     'ARM_OUT=$(gh pr merge "$PR" --admin --auto --squash', "红线：workflow 里出现 `gh pr merge --admin`"),
    # ── #5307：台账分支的欠账必须有**消费面**（否则那条红没人看）────────────────────
    ("debt_visibility_removed",
     '          python3 .github/scripts/flaky_ledger.py reconcile --branch "$LEDGER_BRANCH" \\\n',
     '          python3 .github/scripts/flaky_ledger.py reconcile '
     '--ledger .github/flaky-ledger.json \\\n',
     "#5307 可见性"),
    ("debt_summary_write_removed", '            | tee -a "$GITHUB_STEP_SUMMARY"\n',
     "", "#5307 可见性"),
    # ── #5301 判据②/③/④：台账分支的失败 job 必须能**自动重跑**（上限 1 次、只作用于本分支）──
    ("rerun_invocation_removed",
     '          python3 .github/scripts/flaky_ledger.py rerun-failed \\\n',
     '          true \\\n', "#5301 判据②：没有任何步骤重跑"),
    ("rerun_scope_widened",
     '          python3 .github/scripts/flaky_ledger.py rerun-failed \\\n'
     '            --repo "$GITHUB_REPOSITORY" --branch "$LEDGER_BRANCH" \\\n',
     '          python3 .github/scripts/flaky_ledger.py rerun-failed \\\n'
     '            --repo "$GITHUB_REPOSITORY" --branch "$GITHUB_HEAD_REF" \\\n',
     "#5301 判据④"),
    ("rerun_accounting_removed",
     '            --json-out /tmp/rerun.json | tee -a "$GITHUB_STEP_SUMMARY"\n',
     '            --json-out /tmp/rerun.json\n', "记账"),
    ("rerun_undeterminable_exit_removed",
     '            3) echo "::error::无法判定台账分支的失败 run（rerun-failed 退 3）⇒ **未跑 ≠ 通过**，'
     '不得当成「没有失败」"; exit 1 ;;\n',
     '            3) echo "无法判定"; exit 0 ;;\n', "退 3"),
    ("rerun_action_failure_swallowed",
     '            *) echo "::error::台账失败 job 兜底重跑失败（rc=${RC}）⇒ 台账分支的确定性失败仍'
     '**无人救**（fail-closed，不静默）"; exit 1 ;;\n',
     '            *) echo "重跑失败"; exit 0 ;;\n', "无人救"),
    ("rerun_guidance_probe_removed",
     '          if ! python3 .github/scripts/flaky_ledger.py rerun-failed --help >/dev/null 2>&1; then\n',
     '          if false; then\n', "引导期探测"),
    ("rerun_not_gated_on_drift",
     "      - name: 台账失败 job 兜底重跑（#5301：台账分支不许留白）\n"
     "        if: steps.preflight.outputs.ready == '1' && steps.drift.outputs.drift == '1'\n",
     "      - name: 台账失败 job 兜底重跑（#5301：台账分支不许留白）\n"
     "        if: steps.preflight.outputs.ready == '1'\n",
     "有漂移"),
]

TRIAGE_RED_PROOFS = [
    ("approve_step_removed", "python3 /tmp/flaky_ledger.py approve",
     "python3 /tmp/flaky_ledger.py approve_old", "丢了 `flaky_ledger.py approve` 步骤"),
    ("approve_not_python3", "python3 /tmp/flaky_ledger.py approve",
     "bash /tmp/flaky_ledger.py approve", "未以 `python3 …flaky_ledger.py approve` 形态调用"),
    ("approve_error_signal_removed", 'echo "::error::approve 台账 PR 的 action_required run 失败',
     'echo "approve 台账 PR 的 action_required run 失败', "`::error::` 丢失"),
    ("branch_filter_renamed", "&branch=$BRANCH&per_page=1", "&branch_name=$BRANCH&per_page=1",
     "`branch=$BRANCH` 丢失"),
    ("head_branch_silently_ignored", "&branch=$BRANCH&per_page=1",
     "&branch=$BRANCH&head_branch=$BRANCH&per_page=1", "head_branch="),
    ("mark_flaky_step_removed", "'mark_flaky'", "'mark_ok'", "丢了 `mark_flaky` 步骤"),
    ("flaky_label_removed", '--add-label "flaky/rerun-green"', "", "flaky/rerun-green"),
]


class TestEveryReconcileRuleCanGoRed:
    """兜底 workflow 的**每条**结构判据都有一条红证（删/弱化任一条 ⇒ 该行必红）。"""

    @pytest.mark.parametrize("label,old,new,expected", RECONCILE_RED_PROOFS,
                             ids=[row[0] for row in RECONCILE_RED_PROOFS])
    def test_rule_goes_red(self, label, old, new, expected):
        violations = audit_reconcile(_mutate(REAL_RECONCILE, old, new))
        assert any(expected in v for v in violations), (
            f"{label}：注入后期望违规含 {expected!r}，实际 {violations}")


class TestEveryTriageGuardrailCanGoRed:
    """`flaky-triage.yml` 的**每条**护栏锚点都有一条红证 —— 即「本单没削弱它们」的可执行证据。"""

    @pytest.mark.parametrize("label,old,new,expected", TRIAGE_RED_PROOFS,
                             ids=[row[0] for row in TRIAGE_RED_PROOFS])
    def test_guardrail_goes_red(self, label, old, new, expected):
        violations = audit_triage_guardrails(_mutate(REAL_TRIAGE, old, new))
        assert any(expected in v for v in violations), (
            f"{label}：注入后期望违规含 {expected!r}，实际 {violations}")

# ── #8628：`ensure-pr`（幂等补建 PR，**不 arm**）—— 行为级判据（打桩断言「到底调没调」） ──
#
# 为什么必须**打桩断言调用**而不是看文案：本单的判据是「建 / 不建」这个**动作** —— 文案说会建
# 不等于真的建（本仓「提及 ≠ 调用」已踩多次）。故替换脚本里**唯一**的 `gh` 出口 `_gh`，把每次
# argv 记下来 ⇒ 该建时**恰好一次** `pr create`、不该建时**零次**（幂等 = 这条腿的全部价值）。

def _out(rc=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class GhStub:
    """`_gh` 的桩：`pr list` 按 `open_prs` 依次返回（`None` = 空 ⇒ 没有 open PR）。"""

    def __init__(self, *, open_prs=(), create_rc=0, create_stderr="", created_number=4210):
        self.open_prs = list(open_prs)
        self.create_rc = create_rc
        self.create_stderr = create_stderr
        self.created_number = created_number
        self.calls = []

    def __call__(self, *args):
        self.calls.append([str(a) for a in args])
        if args[:2] == ("pr", "list"):
            nxt = self.open_prs.pop(0) if self.open_prs else None
            return _out(0, "" if nxt is None else str(nxt))
        if args[:2] == ("pr", "create"):
            return _out(self.create_rc, "", self.create_stderr)
        return _out(1, "", f"stub: unexpected gh args {args}")

    def argv_for(self, *prefix):
        return [c for c in self.calls if tuple(c[:len(prefix)]) == prefix]


def _wire(monkeypatch, stub, *, ahead=3, branch_missing=False, module=None):
    """把 `ensure-pr` 依赖的三处外部读数换成桩（**不联网、不建真 PR**）。

    ⚠️ 走**函数全局字典**（`monkeypatch.setitem`）而不是 `setattr(module, …)`：变异体是
    `_load_mutant()` 用 `exec` 造出来的，`setattr(SimpleNamespace, …)` **改不到**它的全局
    （那样桩不生效、会真的去连 GitHub —— 本会话实测踩过一次）。
    """
    mod = module or FL
    g = mod.ensure_ledger_pr.__globals__
    monkeypatch.setitem(g, "_gh", stub)
    monkeypatch.setitem(g, "read_main_ledger_live", lambda repo, rel=None: ledger())
    if branch_missing:
        monkeypatch.setitem(g, "read_branch_ledger", lambda branch=None: None)
    else:
        rows = [entry(run_id=700000 + i) for i in range(ahead)]
        monkeypatch.setitem(g, "read_branch_ledger", lambda branch=None: ledger(*rows))
    return mod


def ensure_violations(info, stub, *, want_action, want_created, want_pr=None,
                      want_create=0, want_ahead=None) -> list:
    """判据本体（空 = 合规）：动作次数 / merged / --admin / 返回值逐项核。"""
    bad = []
    creates = stub.argv_for("pr", "create")
    merges = stub.argv_for("pr", "merge")
    if len(creates) != want_create:
        bad.append(f"`gh pr create` 必须调用 **{want_create}** 次，实际 {len(creates)}（calls={stub.calls}）")
    if merges:
        bad.append(f"`ensure-pr` **不许** arm / merge（#8628 红线：自建 PR 不 arm），实际 {merges}")
    if any("--admin" in c for c in stub.calls):
        bad.append("出现 `--admin`（绕过必需检查，红线）")
    if info.get("action") != want_action:
        bad.append(f"action 必须是 {want_action!r}，实际 {info.get('action')!r}")
    if info.get("created") is not want_created:
        bad.append(f"created 必须是 {want_created!r}，实际 {info.get('created')!r}")
    if want_pr is not None and info.get("pr") != want_pr:
        bad.append(f"pr 必须是**回读**到的 {want_pr!r}，实际 {info.get('pr')!r}")
    if want_ahead is not None and info.get("ahead") != want_ahead:
        bad.append(f"ahead 必须**现取** = {want_ahead}，实际 {info.get('ahead')!r}")
    return bad


class TestEnsurePrJudge:
    def test_ahead_and_no_open_pr_creates_exactly_once(self, monkeypatch):
        stub = GhStub(open_prs=[None, 4210])
        _wire(monkeypatch, stub, ahead=3)
        info = FL.ensure_ledger_pr("owner/repo")
        bad = ensure_violations(info, stub, want_action="created", want_created=True,
                                want_pr=4210, want_create=1, want_ahead=3)
        for argv in stub.argv_for("pr", "create"):
            for flag, want in (("--base", "main"), ("--head", FL.LEDGER_BRANCH),
                               ("--repo", "owner/repo")):
                if flag not in argv or argv[argv.index(flag) + 1] != want:
                    bad.append(f"`gh pr create` 的 {flag} 必须是 {want!r}（实际 {argv}）")
            if FL.AUTOPR_MARKER not in " ".join(argv):
                bad.append("建出来的 PR body 必须带 AUTOPR_MARKER（否则下一轮会被 arm）")
        assert bad == []

    def test_existing_open_pr_is_zero_action(self, monkeypatch):
        stub = GhStub(open_prs=[4210])
        _wire(monkeypatch, stub, ahead=3)
        info = FL.ensure_ledger_pr("owner/repo")
        assert ensure_violations(info, stub, want_action="exists", want_created=False,
                                 want_pr=4210, want_create=0) == []

    def test_ahead_zero_is_zero_action(self, monkeypatch):
        stub = GhStub(open_prs=[None])
        _wire(monkeypatch, stub, ahead=0)
        info = FL.ensure_ledger_pr("owner/repo")
        assert ensure_violations(info, stub, want_action="in-sync", want_created=False,
                                 want_create=0, want_ahead=0) == []

    def test_missing_branch_is_zero_action(self, monkeypatch):
        stub = GhStub(open_prs=[None])
        _wire(monkeypatch, stub, branch_missing=True)
        info = FL.ensure_ledger_pr("owner/repo")
        assert ensure_violations(info, stub, want_action="no-branch", want_created=False,
                                 want_create=0, want_ahead=0) == []

    def test_dry_run_never_creates(self, monkeypatch):
        stub = GhStub(open_prs=[None])
        _wire(monkeypatch, stub, ahead=5)
        info = FL.ensure_ledger_pr("owner/repo", dry_run=True)
        assert ensure_violations(info, stub, want_action="would-create", want_created=False,
                                 want_pr=None, want_create=0, want_ahead=5) == []

    def test_create_failure_is_loud_and_actionable(self, monkeypatch):
        stub = GhStub(open_prs=[None, None], create_rc=1,
                      create_stderr="HTTP 403: Resource not accessible by integration")
        _wire(monkeypatch, stub, ahead=2)
        bad = []
        try:
            info = FL.ensure_ledger_pr("owner/repo")
        except FL.EnsurePrError as exc:
            text = str(exc)
            for want in ("HTTP 403", "gh pr create --base main", FL.LEDGER_BRANCH, "台账仍停在"):
                if want not in text:
                    bad.append(f"失败文案缺 {want!r} ⇒ 出口不可行动：{text}")
        else:
            bad.append(f"建 PR 失败必须抛 `EnsurePrError`（fail-closed），实际返回 {info!r}")
        assert bad == []

    def test_create_race_is_idempotent_success(self, monkeypatch):
        """create 撞「已存在」但**回读**到别人刚建的 PR ⇒ 幂等成功（不判红、不重复建）。"""
        stub = GhStub(open_prs=[None, 4321], create_rc=1, create_stderr="already exists")
        _wire(monkeypatch, stub, ahead=2)
        info = FL.ensure_ledger_pr("owner/repo")
        assert ensure_violations(info, stub, want_action="race-exists", want_created=False,
                                 want_pr=4321, want_create=1) == []

    def test_gh_list_failure_is_undecidable_not_green(self, monkeypatch):
        """读不到 ⇒ `EnsurePrUndecidable`（退 3）；**不许**当「没有 open PR」继续建。"""
        class ListFail:
            def __init__(self):
                self.calls = []

            def __call__(self, *args):
                self.calls.append([str(a) for a in args])
                return _out(1, "", "network down")

        stub = ListFail()
        monkeypatch.setattr(FL, "_gh", stub)
        bad = []
        try:
            info = FL.ensure_ledger_pr("owner/repo")
        except FL.EnsurePrUndecidable as exc:
            if "gh pr list" not in str(exc):
                bad.append(f"「无法判定」必须指向读数面（gh pr list），实际：{exc}")
        else:
            bad.append(f"读不到 open PR 必须抛 `EnsurePrUndecidable`（退 3），实际 {info!r}")
        if any(c[:2] == ["pr", "create"] for c in stub.calls):
            bad.append("读数失败时**不许**建 PR（会把「读不到」当「没有 PR」）")
        assert bad == []

    def test_body_has_marker_and_no_closing_keyword(self):
        bad = []
        body = FL.AUTOPR_BODY
        if FL.AUTOPR_MARKER not in body:
            bad.append("PR body 必须带 AUTOPR_MARKER（跳过 arm 的唯一事实源）")
        if re.search(r"(?i)(close[sd]?|fix(es|ed)?|resolve[sd]?)\s*#\d+", body):
            bad.append("PR body 出现「关闭关键词 + 号」⇒ 合并后会误关 issue（本仓朴素正则，红线）")
        if "#8628" in body:
            bad.append("PR body 不许出现 `#8628`（同族误判风险：关键词旁的数字形态）")
        assert bad == []

    def test_cli_exit_codes_are_three_state(self, monkeypatch):
        """0 = 建成功 / 1 = 建失败 / 3 = 读数失败 —— **三态不许合并**（未跑 ≠ 通过）。"""
        bad = []
        stub = GhStub(open_prs=[None, 4210])
        _wire(monkeypatch, stub, ahead=1)
        rc = FL.main(["ensure-pr", "--repo", "owner/repo"])
        if rc != 0:
            bad.append(f"建成功必须退 0，实际 {rc}")
        stub = GhStub(open_prs=[None, None], create_rc=1, create_stderr="boom")
        _wire(monkeypatch, stub, ahead=1)
        rc = FL.main(["ensure-pr", "--repo", "owner/repo"])
        if rc != 1:
            bad.append(f"建 PR 失败必须退 1（fail-closed），实际 {rc}")

        class ListFail:
            def __call__(self, *args):
                return _out(1, "", "down")

        monkeypatch.setattr(FL, "_gh", ListFail())
        rc = FL.main(["ensure-pr", "--repo", "owner/repo"])
        if rc != 3:
            bad.append(f"读数失败必须退 3（未跑 ≠ 通过），实际 {rc}")
        assert bad == []

    def test_red_proof_existing_pr_shortcut_removed(self, monkeypatch):
        """红证：摘掉「已有 open PR ⇒ 零动作」的短路 ⇒ 同一输入会**多建一条**（幂等被破坏）。

        这条证明上面那条幂等判据是**载荷**（会红），不是空断言。
        """
        mutant_src = inject(
            REAL_SCRIPT,
            "    existing = open_ledger_pr(repo, branch)\n    if existing is not None:",
            "    existing = open_ledger_pr(repo, branch)\n    if False:", where=".github/scripts/flaky_ledger.py")
        mod = _load_mutant(mutant_src, "m_flaky_autopr")
        stub = GhStub(open_prs=[4210, 4210])
        _wire(monkeypatch, stub, ahead=1, module=mod)
        info = mod.ensure_ledger_pr("owner/repo")
        bad = []
        creates = stub.argv_for("pr", "create")
        if len(creates) != 1:
            bad.append(f"红证不成立：摘掉幂等短路后本该**多建一次**，实际 {len(creates)} 次")
        if info.get("action") != "created":
            bad.append(f"红证不成立：摘掉短路后应走到 created，实际 {info.get('action')!r}")
        assert bad == []
