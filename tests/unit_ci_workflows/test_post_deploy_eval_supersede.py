"""
部署后评测的「被取代即抑制」+「仓库级串行槽位」守卫（issue #3587）。

背景（实测，2026-09-14）：
  · PR 层的真实 LLM 评测**不构成合并门禁**（required 只有确定性 9 项）——
    每个 PR 仍在为"不拦门的信号"付四层真实 LLM 全额成本；
  · 并发把评测轮次从 8min 抬到 12min、确定性失败从 9 条涨到 13 条；并发建栈把
    栈启动从 3.4min 抬到 12min（#3417）；run 34809133992 从建 run 到首个 job 起跑等了 231s；
  · **连合两个 PR 时两轮评测都在排队，而只有最后一轮的 main 状态有意义** ——
    先前那轮评价的镜像已被后续 commit 覆盖：付两份栈构建 + 两份真实 LLM，
    买回一条描述*已经不是 main 的状态*的结论。

本测试锁定三件事（**判据来自行为，不来自实现细节**）：

① 抑制的判定口径必须可复现（脚本可本地跑，两种结果都要演练到）：
   · 本次 SHA == main HEAD                    → superseded=false（照常评测）
   · 本次 SHA != main HEAD（已被更新的 main） → superseded=true（抑制）
   · ls-remote 失败 / 取值为空                → superseded=false（**fail-open**：宁可慢，不可漏评）
   · FORCE_EVAL=true                          → superseded=false（手动逃生口）
   并**反向**锁死：抑制必须留可追溯链接，且消费方不得把跳过当失败。

② concurrency 必须是「仓库级串行槽位」而不是「每 run 独立组」：
   group 名固定（不含表达式）才等于"全局排队"，cancel-in-progress 必须是 false
   （#3526 的有意纪律：取消会让长评测永远跑不完 + 结论档永久丢失）。
   首版写成 `group: post-deploy-eval-${{ github.run_id }}` 时本测试必须红——
   那等于每个 run 一个队列 = 完全没串行（变异测试 M1）。

③ （#3654 追加）schedule（每 3 天全量）的抑制判据 = **"main 未动即跳过"**，方向与
   deploy 相反：本次 schedule 的 SHA == 上次 schedule 全量的 SHA → main 未前进 →
   同一状态已有结论 → 抑制（省一整轮全量）；不等 → 跑。查询失败/取值为空一律 fail-open。
"""
# case_ids: MC-012
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOW = "post-deploy-eval.yml"
SCRIPT = REPO_ROOT / ".github" / "scripts" / "eval_supersede.sh"

# 抑制判定必须发生在**真实成本之前**：栈构建、注入种子、装依赖、真实 LLM 评测、判定。
# 这几步一旦跑在抑制判定之前，"抑制省成本"就无从谈起（钱已经花了）。
COST_STEPS = ("Start local stack", "Seed 评测业务数据", "Install eval runner deps",
              "（真实 LLM）")
# ⚠️ "判定" 是 "抑制判定" 的子串：用**精确**步骤名找结论判定步骤，
#    否则测试会拿判定步骤自己跟它自己比（首版就踩了，假绿）。
VERDICT_STEP_NAME = "判定（completion_verdict：确定性失败=0 + 关键旅程全过）"

SHA_A = "a" * 40
SHA_B = "b" * 40


def _load() -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")) or {}


def _eval_job() -> dict:
    return _load()["jobs"]["eval"]


def _steps() -> list:
    return _eval_job()["steps"]


def _named(*keywords) -> list:
    return [s for s in _steps() if any(k in (s.get("name") or "") for k in keywords)]


def _step_index(keyword: str) -> int:
    for i, s in enumerate(_steps()):
        if keyword in (s.get("name") or ""):
            return i
    raise AssertionError(f"找不到步骤（名称含 {keyword!r}）")


def run_supersede(eval_sha: str, main_sha, *, force: str = "false", repo: str = "o/r",
                  run_id: str = "123", main_ref: str = "refs/heads/main") -> tuple:
    """**真跑**判定脚本（不重写判定逻辑）→ (superseded, stdout)。

    `MAIN_SHA` 覆盖是脚本内置的测试钩子：否则只能拿真实远端 HEAD 当唯一输入，
    「未曾被取代」那条分支就永远演练不到（而它恰恰是"不许漏评"的那一半）。
    `main_sha=None` 时改用**必然连不上**的远端来演练 ls-remote 失败（fail-open）分支，
    不用真网络、也不靠超时。
    """
    env = dict(os.environ)
    env.update({
        "EVAL_SHA": eval_sha,
        "FORCE_EVAL": force,
        "REPO": repo,
        "RUN_ID": run_id,
        "MAIN_REF": main_ref,
    })
    if main_sha is None:
        env.pop("MAIN_SHA", None)
        # 保留本地 git 配置（HOME），只把远端指向一个必然失败、且**立即**失败的位置
        env["MAIN_REMOTE"] = "/nonexistent/migao-test-remote.git"
    else:
        env["MAIN_SHA"] = main_sha
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env,
                       timeout=60)
    assert r.returncode == 0, (
        f"判定脚本退出码 {r.returncode} —— 抑制**永远不得**以非零退出（会被当成失败刷红）：\n"
        f"{r.stdout}\n{r.stderr}"
    )
    m = re.search(r"superseded=(true|false)", r.stdout)
    if m:
        superseded = m.group(1)
    else:
        # 没写 GITHUB_OUTPUT 时按脚本内部结论回推（stdout 是唯一事实源）
        superseded = "true" if "⏭️ 抑制本次评测" in r.stdout else "false"
    return superseded, r.stdout


class TestSupersedeDecision:
    """① 判定口径：两种结果都要演练到，且异常一律 fail-open（不得漏评）。"""

    def test_same_sha_is_not_superseded(self):
        """本次 SHA == main HEAD → 照常评测（这一半保证"门禁不会因为判定而消失"）。"""
        superseded, out = run_supersede(SHA_A, SHA_A)
        assert superseded == "false", f"同 SHA 被判成抑制 → 门禁永远不会跑：\n{out}"
        assert "未被取代" in out

    def test_stale_sha_is_superseded(self):
        """本次 SHA != main HEAD → 抑制（核心：连合场景只让最后一轮有意义）。"""
        superseded, out = run_supersede(SHA_A, SHA_B)
        assert superseded == "true", f"main 已前进却仍要评测 → 本包要修的浪费没修掉：\n{out}"

    def test_supersede_keeps_audit_chain(self):
        """抑制**必须**留可追溯链接（这是"不违反『结论档丢失』顾虑"的唯一凭据）。

        缺链接 = 抑制退化成"静默丢弃"，正好撞上 #3526 那条注释要防的东西。
        """
        _, out = run_supersede(SHA_A, SHA_B, repo="o/r", run_id="999")
        assert f"commit/{SHA_A}" in out, "未打印被取代对象的 commit 链接 → 审计链断了"
        assert f"commit/{SHA_B}" in out, "未打印取代它的 main commit 链接 → 追不到取代者"
        assert "actions/workflows/post-deploy-eval.yml" in out, (
            "未打印取代它的 run 列表链接 —— 「某次部署时行为到底怎样」仍无法回答"
        )
        assert "actions/runs/999" in out, "未打印本 run 链接（被抑制方自身也要留档）"
        assert "不计 failure" in out, "未声明「跳过不计失败」→ 读者会以为这是红灯"

    def test_remote_failure_is_fail_open(self):
        """ls-remote 失败/取值不可得 → **照常评测**（宁可慢，不可漏评）。

        判定逻辑本身绝不能成为"漏评"的来源：网络抖动不该让门禁消失。
        """
        superseded, out = run_supersede(SHA_A, None)
        assert superseded == "false", f"远端不可达时抑制了评测 → 门禁被网络抖动吃掉：\n{out}"
        assert "fail-open" in out

    def test_empty_eval_sha_is_fail_open(self):
        """被评 SHA 为空（理论不该发生）→ 同样 fail-open，不得抑制。"""
        superseded, _ = run_supersede("", SHA_A)
        assert superseded == "false", "EVAL_SHA 为空却抑制 → 无依据的跳过"

    def test_force_eval_escapes_suppression(self):
        """手动 FORCE_EVAL=true 是逃生口：回滚复验/补跑特定部署时必须能强制评测。"""
        superseded, out = run_supersede(SHA_A, SHA_B, force="true")
        assert superseded == "false", "FORCE_EVAL=true 仍被抑制 → 补跑不可能"
        assert "FORCE_EVAL" in out

    def test_script_is_callable_and_writes_github_output(self, tmp_path):
        """脚本必须能把 superseded 写进 GITHUB_OUTPUT（否则下游 if 全落空）。"""
        out_file = tmp_path / "out.txt"
        env = dict(os.environ)
        env.update({"EVAL_SHA": SHA_A, "MAIN_SHA": SHA_B, "REPO": "o/r",
                    "RUN_ID": "1", "GITHUB_OUTPUT": str(out_file)})
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
        assert r.returncode == 0
        assert "superseded=true" in out_file.read_text(encoding="utf-8"), (
            "未把 superseded 写进 GITHUB_OUTPUT —— 下游 `if: steps.supersede.outputs...` 永不生效"
        )


class TestSupersedeIsWiredBeforeCost:
    """① 接线：判定必须最早，且**所有**真实成本步骤都要挂它的门。"""

    def test_supersede_step_exists_with_output_id(self):
        steps = _named("抑制判定")
        assert len(steps) == 1, f"「抑制判定」步骤应唯一，实际 {len(steps)} 个"
        assert steps[0].get("id") == "supersede", "判定步骤缺 id=supersede（下游引用不到）"

    def test_supersede_runs_before_any_cost_step(self):
        idx = _step_index("抑制判定")
        for kw in COST_STEPS + (VERDICT_STEP_NAME,):
            cost = _step_index(kw)
            assert idx < cost, (
                f"「抑制判定」排在第 {idx+1} 步，却在成本步骤 {kw!r}（第 {cost+1} 步）之后"
                " —— 抑制要发生在花钱之前，否则省不下来"
            )

    def test_every_cost_step_gated_on_supersede(self):
        """漏挂任何一步 = 抑制了评测却照样建栈/烧 token（等于没抑制）。"""
        ungated = []
        for s in _steps():
            name = s.get("name") or ""
            if not any(k in name for k in COST_STEPS):
                continue
            if "superseded != 'true'" not in (s.get("if") or ""):
                ungated.append(name)
        assert not ungated, (
            f"以下成本步骤未挂抑制门（`if: steps.supersede.outputs.superseded != 'true'`）：{ungated}"
        )

    def test_verdict_step_cannot_fail_when_superseded(self):
        """跳过**不得**计为 failure：判定步骤被抑制时必须整步跳过。

        否则会落进「无汇总文件 → 判定失败 exit 1」分支 → 每次连合刷一个假红灯 +
        自动开 issue（把"省成本"变成"制造噪音"）。
        """
        step = _steps()[_step_index(VERDICT_STEP_NAME)]
        cond = step.get("if") or ""
        assert "superseded != 'true'" in cond, (
            f"判定步骤未排除被抑制的 run（if={cond!r}）→ 跳过一次就报一次假红"
        )

    def test_report_keeps_trace_but_never_files_issue_on_skip(self):
        """report job：抑制要留档（链接链），但**绝不**在抑制时建 issue。"""
        report = _load()["jobs"]["report"]
        names = [s.get("name") or "" for s in report["steps"]]
        assert any("被抑制留档" in n for n in names), (
            "report job 缺「被抑制留档」步骤 —— 抑制就成静默跳过（审计链断）"
        )
        issue_step = next(s for s in report["steps"] if "Create Issue" in (s.get("name") or ""))
        cond = issue_step.get("if") or ""
        assert "failure" in cond and "superseded" not in cond, (
            f"建 issue 条件被改动（{cond!r}）—— 抑制不得成为建 issue 的触发条件"
        )


class TestScheduleSuppression:
    """③ #3654：schedule（每 3 天全量）的抑制判据 = "main 未动即跳过"（方向与 deploy 相反）。

    为什么方向相反：deploy 抑制的是"被取代的旧状态"（main 前进了 → skip）；
    schedule 抑制的是"没新东西可评"（main 没动 → skip）。共同点：只有 skip 抑制，
    一切异常 fail-open 照常跑；skip 不计 failure、留链接链。
    """

    def _run_schedule(self, eval_sha, last_eval_sha, *, force: str = "false",
                      last_cmd: str = None) -> tuple:
        env = dict(os.environ)
        env.update({"EVAL_SHA": eval_sha, "MODE": "schedule", "FORCE_EVAL": force,
                    "REPO": "o/r", "RUN_ID": "7"})
        if last_cmd is not None:
            env["LAST_EVAL_CMD"] = last_cmd          # 显式覆盖查询命令（如 false = 查询失败）
        elif last_eval_sha is None:
            env["LAST_EVAL_CMD"] = "false"           # 默认：查询必然失败 → 演练 fail-open（不走真网络）
        else:
            env["LAST_EVAL_SHA"] = last_eval_sha     # 测试钩子：跳过 gh 查询直接注入"上次全量 SHA"
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env,
                           timeout=60)
        assert r.returncode == 0, (
            f"schedule 抑制判定退出码 {r.returncode} —— 抑制**永远不得**以非零退出：\n"
            f"{r.stdout}\n{r.stderr}"
        )
        m = re.search(r"superseded=(true|false)", r.stdout)
        assert m, f"stdout 缺 superseded 标记（脚本输出协议被破坏）：\n{r.stdout}"
        return m.group(1), r.stdout

    def test_main_unchanged_since_last_full_is_superseded(self):
        """main 自上次 schedule 全量以来未变动 → 抑制（同一状态已有结论，重跑是纯浪费）。"""
        superseded, out = self._run_schedule(SHA_A, SHA_A)
        assert superseded == "true", f"main 未动却要重跑全量 → 每 3 天档没省下钱：\n{out}"
        assert "未变动" in out

    def test_main_moved_since_last_full_runs(self):
        """main 已前进 → 照常跑（这正是 schedule 全量存在的意义）。"""
        superseded, out = self._run_schedule(SHA_B, SHA_A)
        assert superseded == "false", f"main 已前进却抑制 → 全量档漏掉新状态：\n{out}"
        assert "已前进" in out

    def test_last_sha_unavailable_is_fail_open(self):
        """上次全量 SHA 查询失败（首次运行/gh 抖动）→ 照常评测（宁可慢，不可漏评）。"""
        superseded, out = self._run_schedule(SHA_A, None)
        assert superseded == "false", f"查询失败却抑制 → 全量档被网络抖动吃掉：\n{out}"
        assert "fail-open" in out

    def test_last_cmd_failure_is_fail_open(self):
        """LAST_EVAL_CMD 查询命令失败 → 同样 fail-open（测试显式演练 gh 失败分支）。"""
        superseded, out = self._run_schedule(SHA_A, None, last_cmd="false")
        assert superseded == "false", f"gh 查询失败却抑制：\n{out}"
        assert "fail-open" in out

    def test_empty_eval_sha_is_fail_open(self):
        """EVAL_SHA 为空 → fail-open（无依据不得跳过）。"""
        superseded, _ = self._run_schedule("", SHA_A)
        assert superseded == "false", "EVAL_SHA 为空却抑制 → 无依据的跳过"

    def test_force_eval_escapes_schedule_suppression(self):
        """FORCE_EVAL=true 是逃生口：手动强制时即使 main 未动也要跑。"""
        superseded, out = self._run_schedule(SHA_A, SHA_A, force="true")
        assert superseded == "false", "FORCE_EVAL=true 仍被 schedule 抑制 → 补跑不可能"
        assert "FORCE_EVAL" in out

    def test_schedule_skip_keeps_audit_chain(self):
        """schedule 抑制同样必须留可追溯链接（审计链不因模式而断）。"""
        _, out = self._run_schedule(SHA_A, SHA_A)
        assert f"commit/{SHA_A}" in out, "schedule 抑制未打印 commit 链接 → 审计链断"
        assert "actions/runs/7" in out, "schedule 抑制未打印本 run 链接 → 被抑制方自身不留档"

    def test_schedule_skip_never_counts_as_failure(self):
        """跳过不计 failure 的声明必须存在于两种模式（消费方不得当红灯）。"""
        _, out = self._run_schedule(SHA_A, SHA_A)
        assert "不计 failure" in out

    def test_schedule_mode_echoes_superseded_to_stdout(self):
        """脚本 stdout 必须恒输出 superseded=（本测试的解析依据 + 人工可读判定）。"""
        out = self._run_schedule(SHA_B, SHA_A)[1]
        assert "superseded=false" in out


class TestGlobalEvalSlot:
    """② concurrency = 仓库级串行槽位（排队，不 cancel）。"""

    def test_concurrency_group_is_repo_wide_and_static(self):
        conc = _load().get("concurrency") or {}
        group = str(conc.get("group", ""))
        assert group, "workflow 未声明 concurrency.group → 并发建栈互抢（#3417 的 12min 复发）"
        assert "${{" not in group, (
            f"group 含表达式（{group!r}）→ 每个 run 一个队列 = 完全没串行；"
            "仓库级共享槽位必须是**静态字符串**"
        )
        assert group == "eval-stack-global", (
            f"group 名被改动（{group!r}）—— 跨 workflow 共享槽位靠的就是这个名字一致，"
            "改名会让其他评测 workflow 排到另一个队列（文档 eval-environments.md §3.3 依赖它）"
        )

    def test_cancel_in_progress_is_false(self):
        """保持 #3526 纪律：宁可排队，不取消（取消 = 长评测永远跑不完 + 结论档丢失）。"""
        conc = _load().get("concurrency") or {}
        assert conc.get("cancel-in-progress") is False, (
            f"cancel-in-progress 不是 false（{conc.get('cancel-in-progress')!r}）—— "
            "与文件头『不 cancel-in-progress』的决策冲突"
        )

    def test_decision_comment_documents_cross_workflow_slot(self):
        """抑制与串行的"为什么不违反既有注释"必须留在文件里（防后人当遗漏删掉）。"""
        src = (WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")
        for kw in ("eval-stack-global", "抑制 ≠ 取消", "结论档"):
            assert kw in src, f"workflow 注释缺少 {kw!r} —— 决策上下文丢失后会被当遗漏删掉"

    def test_doc_teaches_other_workflows_to_join_the_slot(self):
        """② 的可执行落地说明：另两个评测 workflow 怎么加入同一 group（本包不改它们）。"""
        doc = (REPO_ROOT / "docs" / "testing" / "eval-environments.md").read_text(encoding="utf-8")
        assert "eval-stack-global" in doc, "文档未写明共享 group 名"
        for wf in ("agent-behavior-eval.yml", "xiaobu-acceptance.yml"):
            assert wf in doc, f"文档未给出 {wf} 的落地改法（改哪一行 + 预期效果 + 注意事项）"
