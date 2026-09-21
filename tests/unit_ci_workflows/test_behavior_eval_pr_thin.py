# case_ids: OR-016, AS-007, PR-019, CH-010, DF-011, DF-012
"""**PR 层零真实 LLM** + **自动 LLM 触发全清零**（#4034 裁定 2′/4′；#4262 → 1 条；#4974 → 0 条）—— L0 静态锁。

> 文件名保留历史名（`test_behavior_eval_pr_thin.py`）：它锁的一直是「PR 层有多薄」这件事。
> 判据从 #3653 的「PR 层保留**一层**定向映射 fast 档」收紧为「PR 层 **0 层**真实 LLM」——
> **是收紧，不是放宽**（LLM 调用层数：1 → 0）。
> #4262（2026-09-18）再次**收紧**：自动 LLM 触发由 **3 条 → 1 条**。
> #4974（2026-09-21）**收紧到底**：最后 1 条（`post-deploy-eval` 每周一 cron）也删除 ⇒
> 全仓自动真实 LLM 触发 = **0 条**，评测**只能人工手动派发**。

## 为什么需要这层锁（裁定原文）

> 「**关闭 PR 时的真实 LLM 自动跑**；真实 LLM 评测**收敛到一个入口**；PR / 合并 / 迭代一律不触发。」
> 「代价已知并接受：**PR 阶段不再有 LLM 行为信号**。」（#4034，2026-09-17）

> 「**不要自动进行验证，都是重复的验证，白白消耗成本**」「**手动集中跑一次即可**」（#4262，2026-09-18）

> 「**完全停止真实 LLM 评测定时任务，改为只能人工手动跑**」（#4974，2026-09-21 —— 用户裁定；
> 被删的那条 = `post-deploy-eval.yml` 的 `schedule: 0 3 * * 1`，单次双 persona normal 全量
> ≈122-126 场真实多轮会话，是 #4262 之后**唯一**还在由 cron 付费的评测）

代价既已被接受，就**不允许**再被"顺手补回来"（例如在别处新增自动 LLM 触发、或把
`behavior-eval` job 加回 PR 路径）—— 那是把用户明确买下的账又花一遍。故本文件把它落成
**机械判据**（否则只是散文：`migao-acceptance`「关键行为禁止只写进自然语文档」同族）。
**「不新增自动 LLM 触发」这句话本身就是本文件的第 ② 组断言。**

> #4974 的**防回退方向**：白名单由 #4262 的"只允许 1 条、且必须是周级 cron"变成
> **空集** —— 任何真实 LLM workflow 的自动触发集合（`schedule` / `push` / `workflow_run` /
> `pull_request*`）都必须为空。把任一条定时加回来（哪怕只是"每周一次兜底"）都会让本文件红。

## 锁五件事（每条的**反向变异**都会让本文件红）

1. **PR 路径零 LLM**：任何带 `pull_request` / `pull_request_target` 触发的 workflow，
   其**步骤体**（`run` / `with.script`，剔除注释行）里**不得**出现 `local_runner.py`；
2. **自动 LLM 触发 = 空集**：带真实 LLM 步骤的 workflow，其**自动**触发（`schedule` / `push` /
   `workflow_run` / `pull_request*`）必须**一条都没有**（#4974 用户裁定 2026-09-21：
   「完全停止真实 LLM 评测定时任务，改为只能人工手动跑」——自动触发由 1 条收敛为 **0 条**）；
   **合并/部署触发（`push` / `workflow_run`）= 0 条**；
3. **手动可达性**：每个带真实 LLM 步骤的 workflow 必须仍有 `workflow_dispatch`
   （自动触发清零后，手动入口是评测**唯一**的执行方式 —— 删掉它 = 评测彻底不可执行）；
4. **映射信号不丢**：`agent-behavior-eval.yml` 的**零 LLM** map job 必须在（PR 上回答
   "这次 diff 波及哪些用例"），且 PR 评论必须给出**可复制**的派发命令（"要跑就派发单一入口"），
   并**不得**让读者把它读成"评测通过"（反假绿）；
5. **判据本身非空跑**：见 `TestDetectorActuallyFires`（注入样本 + 负控 + **注入 `schedule` 必红**），
   以及 `TestZeroLlmWorkflowShape`（对"被排除出栈锁"的 workflow 逐条验"确实没有 LLM 机器"）。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 6 条 = 该锁保护的、受"PR 层有没有 LLM"直接
影响的既有映射用例（§13.2 映射表 + `DEFAULT_BEHAVIOR_CASES` 成员）：OR-016（下单域）、
AS-007（换货域）、PR-019（建品域）、CH-010（C 端交互卡，唯一 xiaobu 专属默认集成员）、
DF-011/DF-012（防御域，唯一走 full 桶的非 normal 档映射用例）。
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

BEHAVIOR_EVAL = "agent-behavior-eval.yml"

# 真实 LLM 步骤的判据锚点（与仓库既有口径一致：runner 入口文件）
LLM_MARKER = "local_runner.py"

# ★ 白名单：**允许**存在的自动触发（workflow → 允许的触发键）—— #4974 起为**空集**。
#   加任何一条 = 新增自动 LLM 花费 ⇒ 必须先拿到用户裁定，并同步改这里。
#   #4974（2026-09-21）用户裁定：「**完全停止真实 LLM 评测定时任务，改为只能人工手动跑**」
#   ⇒ #4262 留下的唯一一条（`post-deploy-eval.yml` 每周一 cron）已删除，白名单清空。
AUTOMATIC_LLM_TRIGGERS: dict[str, set[str]] = {}
# 与 workflow_dispatch 一起构成"允许的触发全集"：自动触发 ⊆ 白名单（空集），其余必须是手动。
ALLOWED_MANUAL_TRIGGERS = {"workflow_dispatch"}
# 合并/部署类触发：本裁定的"合并/迭代一律不触发" ⇒ LLM workflow 上**必须为 0**
MERGE_TRIGGERS = {"push", "workflow_run"}
# PR 类触发：真实 LLM 一律不许挂在 PR 上（含 target 变体）
PR_TRIGGERS = {"pull_request", "pull_request_target"}


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8")) or {}


def _triggers(name: str) -> dict:
    # yaml 会把裸 `on:` 解析成布尔 True 键（与 test_schema_integrity 同一处理）
    wf = _load(name)
    return wf.get("on") or wf.get(True) or {}


def _auto_triggers(wf: dict) -> set:
    """workflow 的**自动**触发键（= 触发全集 − 手动白名单）。

    独立成纯函数：判据本体（`test_automatic_llm_trigger_count_is_zero`）与
    **注入式红证**（`test_injected_schedule_into_post_deploy_eval_reds`）共用同一份口径。
    """
    trig = wf.get("on") or wf.get(True) or {}
    return set(trig.keys()) - ALLOWED_MANUAL_TRIGGERS


def _steps(workflow: str) -> list:
    out = []
    for job in (_load(workflow).get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _step_body(step: dict) -> str:
    """步骤**可执行**正文（`run` + `with.script`）—— 不含 YAML 注释。"""
    body = step.get("run") or ""
    body += "\n" + str((step.get("with") or {}).get("script") or "")
    return body


def _strip_comment_lines(text: str) -> str:
    """剔除**整行**注释 —— 防「整行注释里提到 local_runner.py」被当成真实调用（假红）。

    ★ 只剔整行，**不剔行尾**：行尾 `# ... local_runner.py` 仍算命中。
      方向是 **fail-closed（宁可假红，不可假绿）**：行尾剥离要处理 shell 里的
      `${v#pref}`、`sed 's/#.*//'`、引号内 `#` 等，剥错一次就可能把**真调用**剥掉 ⇒ 静默假绿。
      代价是"行尾注释里提一句"会提示改写成整行注释 —— 这个代价可接受，且红的时候有明确报错。
    """
    keep = []
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith("#") or s.startswith("//"):
            continue
        keep.append(ln)
    return "\n".join(keep)


def _step_bodies(workflow: str) -> str:
    return "\n".join(_strip_comment_lines(_step_body(s)) for s in _steps(workflow))


def _llm_workflows() -> list:
    """带**真实 LLM 步骤**的 workflow（按步骤体判，不扫全文正则）。"""
    return sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml")
                  if LLM_MARKER in _step_bodies(p.name))


class TestPathsFrontGate:
    """paths 前置门：纯文档/cases/前端 PR 不触发映射计算（issue #3653，口径未变）。"""

    def test_paths_contains_only_behavior_source(self):
        paths = (_triggers(BEHAVIOR_EVAL).get("pull_request") or {}).get("paths") or []
        assert paths, "agent-behavior-eval 缺 pull_request.paths（守卫前提失效）"
        assert paths == ["backend/ai-agent-service/app/**"], (
            f"paths 应只含行为源文件 {['backend/ai-agent-service/app/**']!r}，实为 {paths!r} —— "
            "纯 cases/文档/前端/评测基建 PR 不应触发映射计算（issue #3653）"
        )

    def test_banned_prefixes_not_in_paths(self):
        paths = (_triggers(BEHAVIOR_EVAL).get("pull_request") or {}).get("paths") or []
        for banned in ("docs/", ".github/cases/", "frontend/", "tests/agent_eval/",
                       "tests/e2e/", "backend/admin-api/", "backend/ai-agent-service/tests/"):
            assert not any(banned in p for p in paths), (
                f"paths 含 {banned!r} —— 该类改动不应触发映射计算（issue #3653）"
            )

    def test_only_trigger_is_pull_request(self):
        """本 workflow **只**由 PR 触发（零 LLM）—— 不得顺手加回 dispatch/schedule。

        「要跑就派发单一入口」：真评测入口是 `post-deploy-eval.yml`；
        在本文件里加 `workflow_dispatch` = 新增第二个（人工）LLM 入口。
        """
        triggers = set(_triggers(BEHAVIOR_EVAL).keys())
        assert triggers == {"pull_request"}, (
            f"{BEHAVIOR_EVAL} 的触发是 {sorted(triggers)}，应只有 pull_request —— "
            "PR 层零 LLM（裁定 2′/4′，issue #4034）"
        )


class TestPrPathHasZeroLlm:
    """① PR 路径零真实 LLM（裁定 2′：关闭 PR 时的真实 LLM 自动跑）。"""

    def test_no_pr_triggered_workflow_has_llm_steps(self):
        offenders = [name for name in _llm_workflows()
                     if set(_triggers(name).keys()) & PR_TRIGGERS]
        assert not offenders, (
            f"这些 workflow 既挂在 PR 上、又含真实 LLM 步骤：{offenders} —— "
            "PR 层 LLM 信号不拦合并（§16.5）却要付真实 token（裁定 2′，issue #4034）；"
            "要跑请派发单一入口（post-deploy-eval），不要把 LLM 留在 PR 路径上"
        )

    def test_behavior_eval_workflow_has_no_llm_step(self):
        assert LLM_MARKER not in _step_bodies(BEHAVIOR_EVAL), (
            f"{BEHAVIOR_EVAL} 的步骤体里仍有 {LLM_MARKER} —— "
            "裁定 2′ 要求它的 PR 路径**不再执行 LLM 步骤**（issue #4034）"
        )

    def test_behavior_eval_keeps_zero_llm_map_job(self):
        """⚠️ 零 LLM 的映射 job **必须保留**（成本 0，给 PR「改动波及哪些用例」的信号）。"""
        jobs = _load(BEHAVIOR_EVAL).get("jobs") or {}
        assert "map" in jobs, (
            f"{BEHAVIOR_EVAL} 的 map job（diff→case_ids，零 LLM）被删了 —— "
            "裁定 2′ 只关 LLM；映射信号是零成本的，删掉等于白丢 PR 上的可见性（issue #4034）"
        )

    def test_behavior_eval_has_no_stack_machinery(self):
        """被删除的评测栈机器不得留半个（半个 = 死机制 / 静默失效形态）。"""
        bodies = _step_bodies(BEHAVIOR_EVAL)
        for anchor in ("eval_stack_seed.sh", "docker compose", "docker-compose"):
            assert anchor not in bodies, (
                f"{BEHAVIOR_EVAL} 仍含起栈/种子机器 {anchor!r} —— "
                "评测 job 已整体删除，残留机器 = 声明无消费（§19.2）"
            )


class TestAutomaticLlmTriggerWhitelist:
    """② 自动 LLM 触发 = 空集（「不新增自动 LLM 触发」落成机械判据；#4974 清零）。"""

    def test_llm_workflow_set_is_the_expected_one(self):
        got = set(_llm_workflows())
        # #4974：白名单已清空，但**带真实 LLM 步骤的 workflow 仍是 4 个** —— 全部**仅手动**
        # （不是被删），它们仍在 `_llm_workflows()` 里（判据 = 步骤体含 `local_runner.py`）。
        expected = {
            "post-deploy-eval.yml",         # #4974：删每周一 cron，改仅手动（判定用途单一入口）
            "xiaobu-acceptance.yml",        # #4262：删定时，改仅手动
            "agent-eval-adversarial.yml",   # #4262：删定时，改仅手动
            "agent-eval.yml",               # 本就仅手动
        }
        assert got == expected, (
            f"带真实 LLM 步骤的 workflow 集合变了：{sorted(got)}（期望 {sorted(expected)}）—— "
            "新增一个真实 LLM workflow 必须同时：① 在 PR 里给出裁定依据；"
            "② 更新本白名单（否则本锁形同虚设）"
        )

    def test_no_merge_or_deploy_triggered_llm(self):
        offenders = {n: sorted(set(_triggers(n).keys()) & MERGE_TRIGGERS)
                     for n in _llm_workflows() if set(_triggers(n).keys()) & MERGE_TRIGGERS}
        assert not offenders, (
            f"这些 LLM workflow 被合并/部署触发：{offenders} —— "
            "裁定 2′/4′：「PR / **合并** / 迭代一律不触发」（issue #4034）；"
            "部署后自动评测已在 #3925 由用户裁定移除，不得以任何形式加回"
        )

    def test_no_llm_workflow_has_automatic_trigger(self):
        """★ #4974 反向断言（**判据本体**）：任何真实 LLM workflow 都不得有自动触发。

        正向白名单只覆盖"进了白名单的"（现在还是空集 ⇒ 一个都不覆盖）；
        本断言把**整个集合**钉死：漏掉"新写一条 schedule 的 workflow"这条路也堵上。
        """
        offenders = {
            n: sorted(_auto_triggers(_load(n)))
            for n in _llm_workflows()
            if _auto_triggers(_load(n))
        }
        assert not offenders, (
            f"这些真实 LLM workflow 仍有自动触发：{offenders} —— "
            "#4974 用户裁定（2026-09-21）：「完全停止真实 LLM 评测定时任务，改为只能人工手动跑」"
            "⇒ 自动真实 LLM 触发**必须为 0 条**（含 schedule / push / workflow_run / pull_request*）。"
            "要恢复任何自动触发，必须先拿到用户裁定并同步改本文件的白名单。"
        )

    def test_automatic_llm_trigger_count_is_zero(self):
        """★ 数量钉死：自动档**恰好 0 条**（多一条 = 新增自动花费）。"""
        auto = {n for n in _llm_workflows() if _auto_triggers(_load(n))}
        assert auto == set(), (
            f"自动真实 LLM 触发集合 = {sorted(auto)}（期望为空）—— "
            "#4974：最后一条（post-deploy-eval 每周一 cron）已删除；"
            "数量变化必须同步改白名单并给出裁定依据"
        )

    def test_post_deploy_eval_has_no_schedule(self):
        """★ #4974：被删的那一条**不得**以任何形态回来（周级 / 日级 / 3 天级 / `*/N` 都算加回来）。"""
        trig = _triggers("post-deploy-eval.yml")
        assert "schedule" not in trig, (
            f"post-deploy-eval 又有定时档了：{trig.get('schedule')!r} —— "
            "#4974 用户裁定「完全停止真实 LLM 评测定时任务，改为只能人工手动跑」；"
            "要恢复定时必须先拿用户裁定，并同步改本文件的白名单"
        )

    def test_schedule_mode_wiring_survives_for_reenable(self):
        """★ #4974：`schedule` 的**接线**（事件分支 / 抑制判据）必须留在原地。

        当前无定时，所以它不红；但它是**恢复定时的前置条件**（同 #3367 的档位特判范式）：
        删掉接线后再把 cron 加回来，抑制判定会落到 dispatch 语义（免抑制 ⇒ 每轮全量照跑，
        正是 #3587 要治的重复付费）。
        """
        src = (WORKFLOWS_DIR / "post-deploy-eval.yml").read_text(encoding="utf-8")
        assert "github.event_name == 'schedule'" in src, (
            "post-deploy-eval 的 `schedule` 事件接线被删了 —— 恢复定时时会静默退化成"
            "「免抑制的 dispatch 语义」（#3587 的重复付费原样复发）"
        )
        assert "'schedule' && 'schedule'" in src, (
            "抑制判定步骤的 `MODE=schedule` 分支被删了 —— 同上，恢复定时的前置条件丢失"
        )

    def test_manual_entry_points_survive(self):
        """③ 自动触发清零后，**手动**入口是评测唯一的执行方式：每个 LLM workflow 都要能派发。"""
        missing = [n for n in _llm_workflows() if "workflow_dispatch" not in _triggers(n)]
        assert not missing, (
            f"这些 LLM workflow 没有 workflow_dispatch：{missing} —— "
            "#4974 之后触发面只剩「手动」；删掉手动入口 = 评测彻底不可执行"
        )


class TestMappingSignalSurvives:
    """④ 映射信号（零 LLM）不得随 LLM 一起被删掉。"""

    def _comment_script(self) -> str:
        return "\n".join(str((s.get("with") or {}).get("script") or "")
                         for s in _steps(BEHAVIOR_EVAL))

    def test_pr_comment_prints_dispatch_command(self):
        script = self._comment_script()
        assert "gh workflow run post-deploy-eval.yml" in script, (
            "PR 评论不再给出「要跑就派发单一入口」的可复制命令 —— "
            "映射信号就变成「只告诉你哪些用例受影响、却不告诉你怎么办」= 半个信号"
        )

    def test_pr_comment_does_not_read_as_pass(self):
        """反假绿：不得让读者把映射评论读成"评测通过"。"""
        script = self._comment_script()
        assert re.search(r"不跑任何真实 LLM|不跑 LLM", script), (
            "PR 评论没有明确声明「本 workflow 不跑 LLM」—— "
            "裁定 2′ 之后 PR 上不再有 LLM 结论，读者很容易把映射评论读成「通过」"
        )
        assert "评测进行中" not in script, (
            "PR 评论仍写「评测进行中」—— 评测 job 已删除，这是**谎报**（比沉默更糟）"
        )


class TestZeroLlmWorkflowShape:
    """⑤ 被排除出"栈/种子/槽位"锁的 workflow，必须逐条证明它确实没有那些机器。

    为什么需要：`test_eval_stack_seed_parity.py` 把 `agent-behavior-eval.yml` 从
    `EVAL_WORKFLOWS` 里移除了（它不再起栈）。**移除参数化 = 少一组锁** ⇒ 必须有替代判据，
    否则「改回带 LLM 的形态」就从"会红"变成"没人管"。
    """

    def test_no_eval_step_id(self):
        ids = [s.get("id") for s in _steps(BEHAVIOR_EVAL)]
        assert "eval" not in ids, (
            f"{BEHAVIOR_EVAL} 还有 id=eval 的评测步骤（{ids}）—— 评测 job 应已整体删除"
        )

    def test_no_flake_ledger_upload(self):
        names = " ".join(str(s.get("name") or "") for s in _steps(BEHAVIOR_EVAL))
        assert "flake" not in names.lower(), (
            f"{BEHAVIOR_EVAL} 仍在上传波动台账（{names}）—— 不跑评测就没有台账可传"
        )

    def test_no_eval_concurrency_slot(self):
        """不再起栈 ⇒ 不得占用仓库级评测槽位（否则槽位语义被无声改写）。"""
        for job_name, job in (_load(BEHAVIOR_EVAL).get("jobs") or {}).items():
            group = str((job.get("concurrency") or {}).get("group") or "")
            assert "eval-stack-global" not in group, (
                f"{BEHAVIOR_EVAL}/{job_name} 仍进共享评测槽位（group={group!r}）—— "
                "本 workflow 不跑 LLM，占槽位只会让真评测排队"
            )


class TestDetectorActuallyFires:
    """判据自身非空跑（`migao-acceptance`：不会红的断言 = 空断言）。

    注入样本**不依赖仓库当下真值**，故永远有效：它证明"PR + LLM"确实会被判红、
    "只有注释提到 LLM"确实不会被误判（负控）。
    """

    PR_WITH_LLM = {
        "on": {"pull_request": {"paths": ["backend/ai-agent-service/app/**"]}},
        "jobs": {"eval": {"steps": [
            {"name": "Run mapped cases",
             "run": "python tests/agent_eval/local_runner.py normal --cases .github/cases"},
        ]}},
    }
    ONLY_COMMENT_MENTIONS_LLM = {
        "on": {"pull_request": {}},
        "jobs": {"map": {"steps": [
            {"name": "map",
             "run": "set -e\n# 真评测走 tests/agent_eval/local_runner.py（本 workflow 不跑）\necho hi"},
        ]}},
    }
    INLINE_COMMENT_MENTIONS_LLM = {
        "on": {"pull_request": {}},
        "jobs": {"map": {"steps": [
            {"name": "map", "run": "echo hi  # 真评测走 tests/agent_eval/local_runner.py"},
        ]}},
    }

    def _auto_triggers(self, wf: dict) -> set:
        trig = wf.get("on") or wf.get(True) or {}
        return set(trig.keys()) - ALLOWED_MANUAL_TRIGGERS

    def _bodies(self, wf: dict) -> str:
        out = []
        for job in (wf.get("jobs") or {}).values():
            for s in job.get("steps") or []:
                out.append(_strip_comment_lines(_step_body(s)))
        return "\n".join(out)

    def test_pr_sample_is_flagged(self):
        assert LLM_MARKER in self._bodies(self.PR_WITH_LLM), (
            "注入样本（PR 触发 + local_runner 调用）未被识别为 LLM 步骤 —— 本判据是空跑"
        )
        assert self._auto_triggers(self.PR_WITH_LLM) & PR_TRIGGERS, (
            "注入样本的 PR 触发未被识别 —— 判据是空跑"
        )

    def test_comment_only_sample_is_not_flagged(self):
        """负控：**整行注释**提到 LLM 的 workflow 不得被判红（否则会逼出无谓的改注释）。

        真实形态 = 本仓 `drift-audit.yml` 头部注释提到 `local_runner.py`（YAML 级注释，
        不落在步骤体里）+ 各 workflow 头部把 runner 当**术语**引用。
        """
        assert LLM_MARKER not in self._bodies(self.ONLY_COMMENT_MENTIONS_LLM), (
            "负控失败：整行注释里的 local_runner.py 被当成了真实调用（假红来源）"
        )

    def test_inline_comment_mention_still_counts(self):
        """行尾注释提到 LLM **仍算命中** —— fail-closed 方向要显式钉住（见 `_strip_comment_lines`）。

        反向变异（把剥离改成 `sed 's/#.*//'` 式行尾剥离）⇒ 本测试红：那时真调用
        也可能被一起剥掉（shell 的 `${v#pref}` / 引号内 `#`），换来的是**静默假绿**。
        """
        assert LLM_MARKER in self._bodies(self.INLINE_COMMENT_MENTIONS_LLM), (
            "行尾注释里的 local_runner.py 未被识别 —— 剥离口径被改宽，存在静默假绿风险"
        )

    def test_llm_workflow_set_is_not_vacuous(self):
        """反向集合非空 —— 否则「自动触发 = 0 条」是在**空集**上恒真（判据退化）。

        白名单已按 #4974 清空，故"白名单非空"不再是判据；取而代之的是
        「被检集合本身非空」+「注入 `schedule` 必红」（见下一条）。
        """
        assert _llm_workflows(), (
            "没有任何 workflow 被识别为『带真实 LLM 步骤』（判据在空集上恒真 = 退化）"
        )

    def test_injected_schedule_into_post_deploy_eval_reds(self):
        """注入式红证：把 `schedule` 加回 `post-deploy-eval` ⇒ 本文件的判据必须红。"""
        wf = _load("post-deploy-eval.yml")
        trig = dict(wf.get("on") or wf.get(True) or {})
        trig["schedule"] = [{"cron": "0 3 * * 1"}]
        assert _auto_triggers({"on": trig}) == {"schedule"}, (
            "注入 schedule 后判据仍判『无自动触发』—— 判据是空跑（#4974 的锁失效）"
        )
