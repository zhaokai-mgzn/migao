# case_ids: OR-016, AS-007, PR-019, CH-010, DF-011, DF-012
"""**PR 层零真实 LLM** + **自动 LLM 触发白名单**（issue #4034，用户裁定 2′/4′）—— L0 静态锁。

> 文件名保留历史名（`test_behavior_eval_pr_thin.py`）：它锁的一直是「PR 层有多薄」这件事。
> 判据从 #3653 的「PR 层保留**一层**定向映射 fast 档」收紧为「PR 层 **0 层**真实 LLM」——
> **是收紧，不是放宽**（LLM 调用层数：1 → 0）。

## 为什么需要这层锁（裁定原文）

> 「**关闭 PR 时的真实 LLM 自动跑**；真实 LLM 评测**收敛到一个入口**；PR / 合并 / 迭代一律不触发。」
> 「代价已知并接受：**PR 阶段不再有 LLM 行为信号**。」

代价既已被接受，就**不允许**再被"顺手补回来"（例如在别处新增自动 LLM 触发、或把
`behavior-eval` job 加回 PR 路径）—— 那是把用户明确买下的账又花一遍。故本文件把它落成
**机械判据**（否则只是散文：`migao-acceptance`「关键行为禁止只写进自然语文档」同族）。
**「不新增自动 LLM 触发」这句话本身就是本文件的第 ② 组断言。**

## 锁五件事（每条的**反向变异**都会让本文件红）

1. **PR 路径零 LLM**：任何带 `pull_request` / `pull_request_target` 触发的 workflow，
   其**步骤体**（`run` / `with.script`，剔除注释行）里**不得**出现 `local_runner.py`；
2. **自动 LLM 触发白名单**：带真实 LLM 步骤的 workflow，其**自动**触发（`schedule` / `push` /
   `workflow_run` / `pull_request*`）只能是 `AUTOMATIC_LLM_TRIGGERS` 里那三条 `schedule`，
   且 **`post-deploy-eval.yml` 的每 3 天档（`0 3 */3 * *`）不得删除**（用户明确保留"定时跑"）；
   **合并/部署触发（`push` / `workflow_run`）= 0 条**；
3. **手动可达性**：每个带真实 LLM 步骤的 workflow 必须仍有 `workflow_dispatch`
   （"只走定时 + 手动 dispatch"里的**手动**这一半，删掉就等于把评测变成不可执行）；
4. **映射信号不丢**：`agent-behavior-eval.yml` 的**零 LLM** map job 必须在（PR 上回答
   "这次 diff 波及哪些用例"），且 PR 评论必须给出**可复制**的派发命令（"要跑就派发单一入口"），
   并**不得**让读者把它读成"评测通过"（反假绿）；
5. **判据本身非空跑**：见 `TestDetectorActuallyFires`（注入样本 + 负控），
   以及 `TestZeroLlmWorkflowShape`（对"被排除出栈锁"的 workflow 逐条验"确实没有 LLM 机器"）。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 6 条 = 该锁保护的、受"PR 层有没有 LLM"直接
影响的既有映射用例（§13.2 映射表 + `DEFAULT_BEHAVIOR_CASES` 成员）：OR-016（下单域）、
AS-007（换货域）、PR-019（建品域）、CH-010（C 端交互卡，唯一 xiaobu 专属默认集成员）、
DF-011/DF-012（防御域，唯一走 full 桶的非 normal 档映射用例）。
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

BEHAVIOR_EVAL = "agent-behavior-eval.yml"

# 真实 LLM 步骤的判据锚点（与仓库既有口径一致：runner 入口文件）
LLM_MARKER = "local_runner.py"

# ★ 白名单：**允许**存在的自动触发（workflow → 允许的触发键）。
#   加任何一条 = 新增自动 LLM 花费 ⇒ 必须在 PR 里给出用户裁定，并同步改这里。
AUTOMATIC_LLM_TRIGGERS = {
    "post-deploy-eval.yml": {"schedule"},        # 每 3 天 normal 全量（**不得删除**）
    "xiaobu-acceptance.yml": {"schedule"},       # 每周六 adversarial（#3367）
    "agent-eval-adversarial.yml": {"schedule"},  # 每周六 adversarial（B 端）
}
# 与 workflow_dispatch 一起构成"允许的触发全集"：自动触发 ⊆ 白名单，其余必须是手动。
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
    """② 自动 LLM 触发 = 白名单（「不新增自动 LLM 触发」落成机械判据）。"""

    def test_llm_workflow_set_is_the_expected_one(self):
        got = set(_llm_workflows())
        expected = set(AUTOMATIC_LLM_TRIGGERS) | {"agent-eval.yml"}
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

    @pytest.mark.parametrize("name", sorted(AUTOMATIC_LLM_TRIGGERS))
    def test_automatic_triggers_match_whitelist(self, name: str):
        auto = set(_triggers(name).keys()) - ALLOWED_MANUAL_TRIGGERS
        assert auto == AUTOMATIC_LLM_TRIGGERS[name], (
            f"{name} 的自动触发是 {sorted(auto)}，白名单是 "
            f"{sorted(AUTOMATIC_LLM_TRIGGERS[name])} —— 定时档按裁定**保留**（不得以"
            "「收敛」为名删掉定时档 = 白丢覆盖），但**不得新增**其它自动触发"
        )
        assert _triggers(name).get("schedule"), f"{name} 的 schedule 声明为空（守卫前提失效）"

    def test_three_day_cadence_preserved(self):
        """★ 用户明确保留"定时跑"：`post-deploy-eval` 的每 3 天档**不得删除**。"""
        sched = _triggers("post-deploy-eval.yml").get("schedule") or []
        crons = [s.get("cron") for s in sched if isinstance(s, dict)]
        assert "0 3 */3 * *" in crons, (
            f"post-deploy-eval 的每 3 天档（0 3 */3 * *）不在了（现有 {crons}）—— "
            "裁定 4′ 明确「保留既有每 3 天档」（issue #4034）；删掉它 = 白丢宽度覆盖"
        )

    def test_manual_entry_points_survive(self):
        """③「定时 + 手动 dispatch」里的**手动**一半：每个 LLM workflow 都要能手动派发。"""
        missing = [n for n in _llm_workflows() if "workflow_dispatch" not in _triggers(n)]
        assert not missing, (
            f"这些 LLM workflow 没有 workflow_dispatch：{missing} —— "
            "裁定 4′ 允许的触发只有「定时 + 手动」；删掉手动入口 = 评测不可执行"
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

    def test_whitelist_is_not_vacuous(self):
        """白名单不得为空 —— 空白的白名单会让「新增自动触发」这类违规失去对照面。"""
        assert AUTOMATIC_LLM_TRIGGERS, "自动触发白名单为空（判据退化）"
        assert all(v for v in AUTOMATIC_LLM_TRIGGERS.values()), (
            "白名单里有条目声明了空触发集合（判据退化）"
        )