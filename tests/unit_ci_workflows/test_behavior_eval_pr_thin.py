# case_ids: OR-016, AS-007, PR-019, CH-010, DF-011, DF-012
"""**PR 层零真实 LLM** + **自动 LLM 触发白名单**（#4034 裁定 2′/4′；#4262 收紧为 1 条）—— L0 静态锁。

> 文件名保留历史名（`test_behavior_eval_pr_thin.py`）：它锁的一直是「PR 层有多薄」这件事。
> 判据从 #3653 的「PR 层保留**一层**定向映射 fast 档」收紧为「PR 层 **0 层**真实 LLM」——
> **是收紧，不是放宽**（LLM 调用层数：1 → 0）。
> #4262（2026-09-18）再次**收紧**：自动 LLM 触发由 **3 条 → 1 条**（见下）。

## 为什么需要这层锁（裁定原文）

> 「**关闭 PR 时的真实 LLM 自动跑**；真实 LLM 评测**收敛到一个入口**；PR / 合并 / 迭代一律不触发。」
> 「代价已知并接受：**PR 阶段不再有 LLM 行为信号**。」（#4034，2026-09-17）

> 「**不要自动进行验证，都是重复的验证，白白消耗成本**」「**手动集中跑一次即可**」
> 「兜底定时**改成每周自动跑一次**」（#4262，2026-09-18 —— 用户实测 9/17 CST 2 次、
> 9/18 CST 8 次全量评测被 agent 自动派发，两天合计 1205 场真实多轮 LLM 会话）

代价既已被接受，就**不允许**再被"顺手补回来"（例如在别处新增自动 LLM 触发、或把
`behavior-eval` job 加回 PR 路径）—— 那是把用户明确买下的账又花一遍。故本文件把它落成
**机械判据**（否则只是散文：`migao-acceptance`「关键行为禁止只写进自然语文档」同族）。
**「不新增自动 LLM 触发」这句话本身就是本文件的第 ② 组断言。**

> #4262 的另一半（**防回退方向反转**）：#4034 时白名单是"允许 3 条定时"，
> 现在白名单是"**只允许 1 条**、且必须是**周级** cron"—— 其余真实 LLM workflow
> 的自动触发集合必须**为空**。把任一条定时加回来（或把周级改回日级/3 天级）
> 都会让本文件红。

## 锁三件事（每条的**反向变异**都会让本文件红）

1. **PR 路径零 LLM**：任何带 `pull_request` / `pull_request_target` 触发的 workflow，
   其**步骤体**（`run` / `with.script`，剔除注释行）里**不得**出现 `local_runner.py`；
2. **自动 LLM 触发白名单**：带真实 LLM 步骤的 workflow，其**自动**触发（`schedule` / `push` /
   `workflow_run` / `pull_request*`）只能是 `AUTOMATIC_LLM_TRIGGERS` 里那**一条** `schedule`
   （`post-deploy-eval.yml` 的**每周一**档 `0 3 * * 1`，不得删除、**也不得加密**为日级/3 天级）；
   **其余真实 LLM workflow 的自动触发必须为空集合**（#4262 用户裁定 2026-09-18：
   「不要自动进行验证，都是重复的验证，白白消耗成本」——自动触发由 3 条收敛为 1 条）；
   **合并/部署触发（`push` / `workflow_run`）= 0 条**；
3. **手动可达性**：每个带真实 LLM 步骤的 workflow 必须仍有 `workflow_dispatch`
   （"只走定时 + 手动 dispatch"里的**手动**这一半，删掉就等于把评测变成不可执行）。

判据本身非空跑由 `TestDetectorActuallyFires` 保证（注入样本 + 负控）。

## 已删除的断言组（#4275，如实登记，不是静默削弱）

> **#4275（2026-09-18 用户裁定）删除了 `agent-behavior-eval.yml`**（PR 层零 LLM 映射信号）——
> 它是 #4034 之后 PR 侧唯一的自动「diff → 该跑哪些用例」提示，零 LLM、零成本，
> 但每个触及 `backend/ai-agent-service/app/**` 的 PR 都会自动跑并刷评论（9/18 实测 13 次/天）。
> 用户裁定「不要自动进行验证」+「CI 运行次数太多」⇒ 删除。
>
> 随之**删掉的是"被测对象已不存在"的断言**（不是放宽门槛）：
> - ①「PR `paths` 前置门」组（`TestPathsFrontGate`）—— 被测 workflow 已删；
> - ④「映射信号不丢」组（`TestMappingSignalSurvives`）—— 被测 PR 评论已删；
> - `TestZeroLlmWorkflowShape` —— 它是 `test_eval_stack_seed_parity.py` 把该 workflow
>   移出 `EVAL_WORKFLOWS` 的**替代判据**，对象已删故一并移除。
>
> **能力去向**（不是白丢）：映射能力仍在 `tests/agent_eval/behavior_mapping.py`（零依赖纯函数，
> 可本地调用）；「该跑哪几条用例」改由 `migao-dev-flow` §13.2 映射表 + 本地纯函数承担。
> 真评测入口不变：`post-deploy-eval.yml`（每周一自动 + 手动）。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 6 条 = 该锁保护的、受"PR 层有没有 LLM"直接
影响的既有映射用例（§13.2 映射表 + `DEFAULT_BEHAVIOR_CASES` 成员）：OR-016（下单域）、
AS-007（换货域）、PR-019（建品域）、CH-010（C 端交互卡，唯一 xiaobu 专属默认集成员）、
DF-011/DF-012（防御域，唯一走 full 桶的非 normal 档映射用例）。
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


# 真实 LLM 步骤的判据锚点（与仓库既有口径一致：runner 入口文件）
LLM_MARKER = "local_runner.py"

# ★ 白名单：**允许**存在的自动触发（workflow → 允许的触发键）。
#   加任何一条 = 新增自动 LLM 花费 ⇒ 必须在 PR 里给出用户裁定，并同步改这里。
#   #4262（2026-09-18）用户裁定：自动触发由 **3 条 → 1 条**（「不要自动进行验证，
#   都是重复的验证，白白消耗成本」+「兜底定时改成每周自动跑一次」）。
#   ⇒ 其余真实 LLM workflow 的自动触发必须为空（由下面的反向断言钉死）。
AUTOMATIC_LLM_TRIGGERS = {
    "post-deploy-eval.yml": {"schedule"},  # **唯一**自动档：每周一 normal 全量（#4262 由每 3 天收紧）
}
# 唯一自动档的 cron 语义（#4262）：**周级**。写成日级/3 天级/小时级都算把成本加回来。
WEEKLY_CADENCE_CRON = "0 3 * * 1"  # 每周一 03:00 UTC = 11:00 CST
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

class TestAutomaticLlmTriggerWhitelist:
    """② 自动 LLM 触发 = 白名单（「不新增自动 LLM 触发」落成机械判据）。"""

    def test_llm_workflow_set_is_the_expected_one(self):
        got = set(_llm_workflows())
        # #4262：白名单只剩 1 条自动档，但**带真实 LLM 步骤的 workflow 仍是 4 个** ——
        # 另 3 个改为**仅手动**（不是被删），它们仍在 `_llm_workflows()` 里（判据 = 步骤体
        # 含 `local_runner.py`）。故期望集 = 白名单 ∪ 仅手动的那三个。
        expected = set(AUTOMATIC_LLM_TRIGGERS) | {
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

    @pytest.mark.parametrize("name", sorted(AUTOMATIC_LLM_TRIGGERS))
    def test_automatic_triggers_match_whitelist(self, name: str):
        auto = set(_triggers(name).keys()) - ALLOWED_MANUAL_TRIGGERS
        assert auto == AUTOMATIC_LLM_TRIGGERS[name], (
            f"{name} 的自动触发是 {sorted(auto)}，白名单是 "
            f"{sorted(AUTOMATIC_LLM_TRIGGERS[name])} —— #4262 裁定后白名单只剩**周级 1 条**，"
            "新增任何其它自动触发（含把删掉的定时加回来）= 把用户买下的账又花一遍"
        )
        assert _triggers(name).get("schedule"), f"{name} 的 schedule 声明为空（守卫前提失效）"

    def test_no_other_llm_workflow_has_automatic_trigger(self):
        """★ #4262 反向断言：**只允许 1 条**自动档，其余真实 LLM workflow 必须零自动触发。

        这是本次收紧的**判据本体**（正向白名单只覆盖"进了白名单的"，
        漏掉"新写一条 schedule 的 workflow"；本断言把整个集合钉死）。
        """
        offenders = {
            n: sorted(set(_triggers(n).keys()) - ALLOWED_MANUAL_TRIGGERS)
            for n in _llm_workflows()
            if n not in AUTOMATIC_LLM_TRIGGERS
            and (set(_triggers(n).keys()) - ALLOWED_MANUAL_TRIGGERS)
        }
        assert not offenders, (
            f"这些真实 LLM workflow 仍有自动触发：{offenders} —— "
            "#4262 用户裁定（2026-09-18）：「不要自动进行验证，都是重复的验证，白白消耗成本」"
            "⇒ 自动真实 LLM 触发**只允许 1 条**（post-deploy-eval 每周一）。"
            "要恢复某条自动触发，必须先拿到用户裁定并同步改本文件的白名单。"
        )

    def test_automatic_llm_trigger_count_is_one(self):
        """★ 数量钉死：自动档**恰好 1 条**（多一条 = 新增花费，少一条 = 连兜底都没了）。"""
        auto = {n for n in _llm_workflows()
                if set(_triggers(n).keys()) - ALLOWED_MANUAL_TRIGGERS}
        assert auto == {"post-deploy-eval.yml"}, (
            f"自动真实 LLM 触发集合 = {sorted(auto)}（期望只有 post-deploy-eval.yml）—— "
            "#4262：3 条收敛为 1 条；数量变化必须同步改白名单并给出裁定依据"
        )

    def test_weekly_cadence_only(self):
        """★ #4262：唯一自动档必须是**周级** cron（由每 3 天收紧为每周）。

        「不得删除」已由上一组断言钉死；本断言钉**频率**——把周级改回日级/3 天级/小时级
        等于悄悄把成本加回来（这正是本单要治的形态）。
        """
        sched = _triggers("post-deploy-eval.yml").get("schedule") or []
        crons = [s.get("cron") for s in sched if isinstance(s, dict)]
        assert crons == [WEEKLY_CADENCE_CRON], (
            f"post-deploy-eval 的定时档应为唯一周级『{WEEKLY_CADENCE_CRON}』，现有 {crons} —— "
            "#4262 用户裁定「兜底定时改成每周自动跑一次」；删掉它 = 白丢宽度覆盖，"
            "改密（日级 / 3 天级 / */N） = 把成本加回来"
        )
        assert "*/" not in WEEKLY_CADENCE_CRON, "周级档不得含 `*/` 步进（那是日级/小时级的形态）"

    def test_manual_entry_points_survive(self):
        """③「定时 + 手动 dispatch」里的**手动**一半：每个 LLM workflow 都要能手动派发。"""
        missing = [n for n in _llm_workflows() if "workflow_dispatch" not in _triggers(n)]
        assert not missing, (
            f"这些 LLM workflow 没有 workflow_dispatch：{missing} —— "
            "裁定 4′ 允许的触发只有「定时 + 手动」；删掉手动入口 = 评测不可执行"
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