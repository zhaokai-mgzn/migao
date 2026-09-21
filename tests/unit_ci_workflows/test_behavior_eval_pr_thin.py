# case_ids: OR-016, AS-007, PR-019, CH-010, DF-011, DF-012
"""**PR 层零真实 LLM / 零评测机具** + **自动 LLM 触发全清零**（#4034 裁定 2′/4′；#4262 → 1 条；#4974 → 0 条；#4275 → PR 层机具面）—— L0 静态锁。

> 文件名保留历史名（`test_behavior_eval_pr_thin.py`）：它锁的一直是「PR 层有多薄」这件事。
> 判据从 #3653 的「PR 层保留**一层**定向映射 fast 档」收紧为「PR 层 **0 层**真实 LLM」——
> **是收紧，不是放宽**（LLM 调用层数：1 → 0）。
> #4262（2026-09-18）再次**收紧**：自动 LLM 触发由 **3 条 → 1 条**。
> #4974（2026-09-21）**收紧到底**：最后 1 条（`post-deploy-eval` 每周一 cron）也删除 ⇒
> 全仓自动真实 LLM 触发 = **0 条**，评测**只能人工手动派发**。
> #4275（2026-09-21）把 PR 层最后一件事也去掉：`agent-behavior-eval.yml`（零 LLM 的
> **映射评论** workflow）按用户裁定**整体删除**（承接 #4262「不要自动进行验证」
> 「CI 运行次数太多」）⇒ PR 层**再无任何自动行为信号**。

## 为什么需要这层锁（裁定原文）

> 「**关闭 PR 时的真实 LLM 自动跑**；真实 LLM 评测**收敛到一个入口**；PR / 合并 / 迭代一律不触发。」
> 「代价已知并接受：**PR 阶段不再有 LLM 行为信号**。」（#4034，2026-09-17）

> 「**不要自动进行验证，都是重复的验证，白白消耗成本**」「**手动集中跑一次即可**」（#4262，2026-09-18）

> 「**完全停止真实 LLM 评测定时任务，改为只能人工手动跑**」（#4974，2026-09-21 —— 用户裁定；
> 被删的那条 = `post-deploy-eval.yml` 的 `schedule: 0 3 * * 1`，单次双 persona normal 全量
> ≈122-126 场真实多轮会话，是 #4262 之后**唯一**还在由 cron 付费的评测）

代价既已被接受，就**不允许**再被"顺手补回来"（例如在别处新增自动 LLM 触发、或把
LLM 步骤加回 PR 路径）—— 那是把用户明确买下的账又花一遍。故本文件把它落成
**机械判据**（否则只是散文：`migao-acceptance`「关键行为禁止只写进自然语文档」同族）。
**「PR 层不许有机具、不许有自动 LLM 触发」这句话本身就是本文件的第 ① ② 组断言。**

> #4974 的**防回退方向**：白名单由 #4262 的"只允许 1 条、且必须是周级 cron"变成
> **空集** —— 任何真实 LLM workflow 的自动触发集合（`schedule` / `push` / `workflow_run` /
> `pull_request*`）都必须为空。把任一条定时加回来（哪怕只是"每周一次兜底"）都会让本文件红。

## 锁四件事（每条的**反向变异**都会让本文件红）

1. **PR 路径零 LLM 机具**：任何带 `pull_request` / `pull_request_target` 触发的 workflow，
   其**步骤体**（`run` / `with.script`，剔除注释行）里**不得**出现 `local_runner.py` /
   起栈注种子机具 / `id: eval` 步骤 / 仓储级评测槽位 `eval-stack-global` /
   真实 LLM 波动台账 `agent-eval-flakes.json`；
2. **自动 LLM 触发 = 空集**：带真实 LLM 步骤的 workflow，其**自动**触发（`schedule` / `push` /
   `workflow_run` / `pull_request*`）必须**一条都没有**（#4974 用户裁定 2026-09-21：
   「完全停止真实 LLM 评测定时任务，改为只能人工手动跑」——自动触发由 1 条收敛为 **0 条**）；
   **合并/部署触发（`push` / `workflow_run`）= 0 条**；
3. **手动可达性**：每个带真实 LLM 步骤的 workflow 必须仍有 `workflow_dispatch`
   （自动触发清零后，手动入口是评测**唯一**的执行方式 —— 删掉它 = 评测彻底不可执行）；
4. **判据本身非空跑**：`TestDetectorActuallyFires` + `TestPrLayerScannerActuallyFires`
   （注入样本 + 负控 + **注入 `schedule` 必红**），且被检集合非空（防空集恒真）。

## #4275：被测 workflow 已删除 ⇒ 逐条改判（**删的是不存在的对象，不是放宽门槛**）

`agent-behavior-eval.yml`（426 行）按用户裁定（落法 A：删掉整个 workflow + 同步守卫）
**整体删除**。它当初的**唯一产物是 PR 评论**（`issues.createComment`），map job 绑死
PR 上下文 ⇒ 无法改造成有意义的手动档（留 `workflow_dispatch` 空档 = 仓库明令禁止的
「永不执行的死 job」）。它**零 LLM、不花钱**；删它是为 **CI 运行次数**。

| 被删/被改的断言 | 处理 | 理由（为什么删的是不存在的对象 / 为什么改成哪个现存面） |
|---|---|---|
| `TestPathsFrontGate::test_paths_contains_only_behavior_source` | **改判** → `TestNonBehaviorDiffMapsToNothing::test_only_behavior_source_prefixes_trigger_mapping` | 原判据解析的是**被删文件**的 `on.pull_request.paths`（对象已不存在，无处施加）。同一意图（#3653「纯 cases/文档/前端 PR 不触发映射计算」）**仍活着**，载体是 `tests/agent_eval/behavior_mapping.py` 的 `AI_BEHAVIOR_PATH_PREFIXES`（本文件未删它）⇒ 改为对**纯函数**断言"非行为路径 → 映射结果为空（`source == 'none'`）" |
| `TestPathsFrontGate::test_banned_prefixes_not_in_paths` | **改判** → 同上（同一测试内的禁用前缀循环） | 同上。⚠️ 原禁用表里的 `.github/cases/`、`tests/agent_eval/` 是**workflow 触发器**层面的禁用（它们不该触发那次映射 run），而纯函数里它们是**合法**行为输入（改了用例库→跑兜底网复验，`#3502`）⇒ 改判时按新载体的真实口径重列，不照抄 |
| `TestPathsFrontGate::test_only_trigger_is_pull_request` | **删除** | 被测对象是该文件的**触发集合**（文件已删）。其意图（"不得给 PR 层零 LLM 的 workflow 加 dispatch/schedule 造第二个入口"）落在现存面：`test_no_pr_triggered_workflow_has_llm_steps`（PR 层 + LLM ⇒ 红）+ `TestAutomaticLlmTriggerWhitelist::test_no_llm_workflow_has_automatic_trigger`（LLM workflow + 自动触发 ⇒ 红） |
| `TestPrPathHasZeroLlm::test_behavior_eval_workflow_has_no_llm_step` | **删除** | 被测对象（该文件的步骤体）已不存在。同一判据的**集合面**版本 `test_no_pr_triggered_workflow_has_llm_steps` **逐字保留**，且覆盖全部 PR 触发者（比只看一个文件更宽） |
| `TestPrPathHasZeroLlm::test_behavior_eval_keeps_zero_llm_map_job` | **删除** | 它要求"map job **必须保留**"——该 job 已随文件按用户裁定删除，断言**与裁定冲突**且对象不存在。（原判据的立意是"零成本信号别白丢"；裁定后该信号**整体取消**，代价已由 #4275 显式登记：PR 上不再有任何自动行为信号） |
| `TestPrPathHasZeroLlm::test_behavior_eval_has_no_stack_machinery` | **改判** → `TestPrLayerMachineryIsZero::test_no_pr_triggered_workflow_has_stack_machinery` | 被测对象已不存在；意图是"**将来不许有人再造一个 PR 层起栈入口**"，与那个文件无关 ⇒ 改为对**现存 PR 层 workflow 集合**断言（覆盖面从 1 个文件变宽到全部 PR 触发者） |
| `TestMappingSignalSurvives`（2 条） | **删除** | 被测对象是**被删文件的 PR 评论脚本**（`with.script` 里的派发命令与"不跑 LLM"声明）。没有评论脚本，就没有"评论会不会被读成评测通过"这一风险面。反假绿的**剩余意图**（PR 上不得出现会被误读成 LLM 结论的东西）由 `TestPrLayerMachineryIsZero` 承担：PR 层零 LLM 机具 ⇒ 不存在可被误读的 LLM 结论 |
| `TestZeroLlmWorkflowShape::test_no_eval_step_id` | **改判** → `TestPrLayerMachineryIsZero::test_no_pr_triggered_workflow_has_eval_step_id` | 对象已不存在 ⇒ 改判到现存 PR 层集合（同 `test_no_eval_step_id` 的判据形态：`id: eval` 出现即红） |
| `TestZeroLlmWorkflowShape::test_no_flake_ledger_upload` | **改判** → `TestPrLayerMachineryIsZero::test_no_pr_triggered_workflow_uploads_the_flake_ledger` | 同上。判据收紧为按**产物名**（`agent-eval-flakes.json`，真实 LLM 波动台账）判，而不是按步骤名里有没有 "flake" 字符串 |
| `TestZeroLlmWorkflowShape::test_no_eval_concurrency_slot` | **改判** → `TestPrLayerMachineryIsZero::test_no_pr_triggered_workflow_holds_the_eval_slot` | 同上。判据从"那个文件有没有占槽位"改成"**现存 PR 层**有没有占 `eval-stack-global`"（PR 层不起栈就不该占槽位，否则真评测排队） |

**没动的东西**（判据一个没少）：`TestAutomaticLlmTriggerWhitelist`（8 条）、
`TestDetectorActuallyFires`（7 条）、`_llm_workflows` / `_strip_comment_lines` 等口径函数。

## 能力去向（不是白丢）

映射能力仍在 `tests/agent_eval/behavior_mapping.py`（零依赖纯函数，本地可调
`map_changed_files_with_source(<改动文件列表>)`）；§13.2 的「该跑哪几条用例」由**本机**按
映射表 + 该纯函数算（零成本、不派发）——这正是 #4262 保留的「零成本动作」。
删掉的只是「在 PR 上**自动**贴评论」这个入口。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 6 条 = 该锁保护的、受"PR 层有没有 LLM"直接
影响的既有映射用例（§13.2 映射表 + `DEFAULT_BEHAVIOR_CASES` 成员）：OR-016（下单域）、
AS-007（换货域）、PR-019（建品域）、CH-010（C 端交互卡，唯一 xiaobu 专属默认集成员）、
DF-011/DF-012（防御域，唯一走 full 桶的非 normal 档映射用例）。
"""
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from behavior_mapping import map_changed_files_with_source  # noqa: E402

# 真实 LLM 步骤的判据锚点（与仓库既有口径一致：runner 入口文件）
LLM_MARKER = "local_runner.py"
# PR 层不得出现的**评测机具**（起栈 / 注种子 / 真实 LLM 波动台账）
STACK_MARKERS = ("eval_stack_seed.sh", "docker compose", "docker-compose")
EVAL_FLAKE_LEDGER = "agent-eval-flakes.json"
EVAL_STEP_ID = "eval"
EVAL_SLOT = "eval-stack-global"

# 非行为路径（#3653 的意图：纯文档 / 前端 / 非 agent 后端的 PR 不该触发映射计算）。
# ⚠️ **不**含 `.github/cases/` 与 `tests/agent_eval/`：它们是**纯函数**口径里合法的行为输入
#    （改了用例库/评测基建 → 跑兜底网复验，`#3502`），只是当初不该触发那次 workflow run。
NON_BEHAVIOR_PROBE_PATHS = (
    "docs/wiki/CI-CD.md",
    "frontend/worker-h5/src/index.ts",
    "backend/admin-api/src/main/java/A.java",
    "tests/e2e/foo.spec.ts",
    "backend/ai-agent-service/tests/test_x.py",
    ".github/workflows/pr-check.yml",
)

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


def _wf_steps(wf: dict) -> list:
    out = []
    for job in (wf.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _steps(workflow: str) -> list:
    return _wf_steps(_load(workflow))


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


def _wf_step_bodies(wf: dict) -> str:
    return "\n".join(_strip_comment_lines(_step_body(s)) for s in _wf_steps(wf))


def _step_bodies(workflow: str) -> str:
    return _wf_step_bodies(_load(workflow))


def _llm_workflows() -> list:
    """带**真实 LLM 步骤**的 workflow（按步骤体判，不扫全文正则）。"""
    return sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml")
                  if LLM_MARKER in _step_bodies(p.name))


def _pr_layer_workflows() -> dict:
    """**现存 PR 层** workflow（带 `pull_request` / `pull_request_target`）→ `{name: 文档}`。

    #4275 的改判载体：原判据解析的是**被删文件**；现在换成"扫这一整层"——
    覆盖面从 1 个文件变宽到全部 PR 触发者，且不受任何单文件增删影响。
    """
    out = {}
    for p in sorted(WORKFLOWS_DIR.glob("*.yml")):
        wf = _load(p.name)
        trig = wf.get("on") or wf.get(True) or {}
        if set(trig.keys()) & PR_TRIGGERS:
            out[p.name] = wf
    return out


def pr_layer_machinery_problems(pr_layer: dict) -> list:
    """PR 层**评测机具**扫描（纯函数：仓库真值断言与注入式红证共用同一口径）。

    返回 `[(workflow, 机具类别, 证据), ...]`（空列表 = PR 层零机具）。
    「机具」= 起栈/注种子机器、真实 LLM runner、`id: eval` 评测步骤、
    仓储级评测槽位 `eval-stack-global`、真实 LLM 波动台账。
    """
    problems = []
    for name, wf in pr_layer.items():
        bodies = _wf_step_bodies(wf)
        ids = [s.get("id") for s in _wf_steps(wf)]
        groups = [str((wf.get("concurrency") or {}).get("group") or "")]
        groups += [str((j.get("concurrency") or {}).get("group") or "")
                   for j in (wf.get("jobs") or {}).values()]
        for banned in STACK_MARKERS:
            if banned in bodies:
                problems.append((name, "stack", banned))
        if LLM_MARKER in bodies:
            problems.append((name, "llm", LLM_MARKER))
        if EVAL_FLAKE_LEDGER in bodies:
            problems.append((name, "flake-ledger", EVAL_FLAKE_LEDGER))
        if EVAL_STEP_ID in ids:
            problems.append((name, "eval-step", f"id: {EVAL_STEP_ID}"))
        for g in groups:
            if EVAL_SLOT in g:
                problems.append((name, "eval-slot", g))
    return problems


class TestPrLayerMachineryIsZero:
    """① PR 路径上的**评测机具数 = 0**（裁定 2′/4′ 的机械形式）。

    ## #4275 改判说明（为什么这几条不是"删掉的断言"）

    原判据解析 `agent-behavior-eval.yml` 的步骤体（"它里面不得有这些机具"）——该文件已按
    用户裁定**整体删除**，那几条断言**无处可施加**。但它们的**真实意图与那个文件无关**：
    「**将来不许有人再造一个 PR 层自动 LLM / 起栈入口**」。故判据整体搬到**现存 PR 层集合**上
    （`_pr_layer_workflows()`），覆盖面**变宽**（1 个文件 → 全部 PR 触发者），
    且判据形态（机具出现即红）**一字未改**。
    """

    @staticmethod
    def _problems(kind: str) -> list:
        return [p for p in pr_layer_machinery_problems(_pr_layer_workflows()) if p[1] == kind]

    def test_pr_layer_workflow_set_is_not_vacuous(self):
        """被检集合非空 —— 否则下面每一条都在空集上恒真（判据退化）。"""
        assert len(_pr_layer_workflows()) >= 3, (
            f"识别到的 PR 层 workflow 只有 {sorted(_pr_layer_workflows())} —— "
            "判据在过小的集合上跑（PR 触发识别口径失效？）"
        )

    def test_no_pr_triggered_workflow_has_llm_steps(self):
        """（原 `TestPrPathHasZeroLlm::test_no_pr_triggered_workflow_has_llm_steps`，逐字保留）"""
        offenders = [name for name in _llm_workflows()
                     if set(_triggers(name).keys()) & PR_TRIGGERS]
        assert not offenders, (
            f"这些 workflow 既挂在 PR 上、又含真实 LLM 步骤：{offenders} —— "
            "PR 层 LLM 信号不拦合并（§16.5）却要付真实 token（裁定 2′，issue #4034）；"
            "要跑请派发单一入口（post-deploy-eval），不要把 LLM 留在 PR 路径上"
        )

    def test_no_pr_triggered_workflow_has_stack_machinery(self):
        """（原 `test_behavior_eval_has_no_stack_machinery` 的现存面改判）起栈/注种子机具 = 0。"""
        bad = self._problems("stack")
        assert bad == [], (
            f"PR 层出现了起栈/注种子机具：{bad} —— "
            "PR 路径上起栈 = 每个行为 PR 付一次 docker 栈成本（裁定 2′/4′，issue #4034）；"
            "真评测走手动派发（post-deploy-eval / xiaobu-acceptance）"
        )

    def test_no_pr_triggered_workflow_has_eval_step_id(self):
        """（原 `TestZeroLlmWorkflowShape::test_no_eval_step_id` 的现存面改判）无 `id: eval` 步骤。"""
        bad = self._problems("eval-step")
        assert bad == [], (
            f"PR 层出现了 `id: eval` 评测步骤：{bad} —— "
            "PR 层零 LLM 的形态是「**没有**评测步骤」，不是「评测步骤恒 exit 0」"
        )

    def test_no_pr_triggered_workflow_holds_the_eval_slot(self):
        """（原 `test_no_eval_concurrency_slot` 的现存面改判）PR 层不得占仓库级评测槽位。

        槽位 `eval-stack-global` 的语义是「谁真起栈谁进」（#3587）；PR 层不起栈却占槽位，
        只会让**真评测**排队（#3563 的 required 饿死形态）。
        """
        bad = self._problems("eval-slot")
        assert bad == [], (
            f"PR 层 workflow 占了共享评测槽位：{bad} —— "
            "不起栈就不该进槽位（#3587）；要跑评测请走手动派发的起栈 workflow"
        )

    def test_no_pr_triggered_workflow_uploads_the_flake_ledger(self):
        """（原 `test_no_flake_ledger_upload` 的现存面改判）PR 层不得产出 LLM 波动台账。

        判据按**产物名**（`agent-eval-flakes.json`）判：不跑真实 LLM 就没有台账可传，
        传一个恒不存在的 artifact 会让"按台账放行"的判据静默退化（#3563 的真实形态）。
        """
        bad = self._problems("flake-ledger")
        assert bad == [], (
            f"PR 层 workflow 引用了真实 LLM 波动台账：{bad} —— "
            "不跑真实 LLM 就没有台账；引用只存在于起栈评测 workflow 里"
        )


class TestNonBehaviorDiffMapsToNothing:
    """（原 `TestPathsFrontGate` 的现存面改判）纯文档/前端/非 agent 后端 PR **不触发**映射计算。

    原判据解析被删 workflow 的 `on.pull_request.paths`。同一意图的**活载体**是
    `tests/agent_eval/behavior_mapping.py`（`#4275` 明确保留：#4262 的「零成本动作」=
    本机按 §13.2 映射表 + 这个纯函数算该跑哪几条用例）⇒ 判据落在纯函数上。
    """

    def test_only_behavior_source_prefixes_trigger_mapping(self):
        for path in NON_BEHAVIOR_PROBE_PATHS:
            case_ids, source = map_changed_files_with_source([path])
            assert (case_ids, source) == ([], "none"), (
                f"非行为路径 {path!r} 触发了映射计算（source={source!r}, cases={case_ids}）—— "
                "纯 cases/文档/前端/非 agent 后端的 PR 不该烧评测预算（issue #3653 的口径）"
            )

    def test_behavior_source_prefix_still_triggers_mapping(self):
        """负控（防"把映射面改空"式的假绿）：行为源文件仍必须触发映射。"""
        case_ids, source = map_changed_files_with_source(
            ["backend/ai-agent-service/app/main.py"])
        assert case_ids and source in {"default_net", "rules"}, (
            f"行为源文件 `app/main.py` 没触发映射（source={source!r}, cases={case_ids}）—— "
            "判据被修坏了：`test_only_behavior_source_prefixes_trigger_mapping` 会在空集上恒真"
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
        return _wf_step_bodies(wf)

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


class TestPrLayerScannerActuallyFires:
    """`pr_layer_machinery_problems` 自身非空跑：**五个轴各有一个能单独让它红的变异体**。

    （#4275 改判后的新判据不允许是"恒绿"的：每个机具类别都要有一条注入样本；
    负控证明"只在整行注释里提到"不会被误判成机具 —— 与 `_strip_comment_lines` 同口径。）
    """

    @staticmethod
    def _wf(run: str = "echo hi", **extra) -> dict:
        wf = {"on": {"pull_request": {}},
              "jobs": {"map": {"steps": [{"name": "map", "run": run}]}}}
        wf.update(extra)
        return wf

    def test_injected_stack_machinery_reds(self):
        for sample in ("bash scripts/eval_stack_seed.sh --persona mibao",
                       "docker compose up -d"):
            bad = pr_layer_machinery_problems({"injected.yml": self._wf(sample)})
            assert [k for _n, k, _e in bad] == ["stack"], (
                f"注入起栈机具未被判红：{sample!r} ⇒ {bad}"
            )

    def test_injected_llm_runner_reds(self):
        bad = pr_layer_machinery_problems(
            {"injected.yml": self._wf("python tests/agent_eval/local_runner.py normal")})
        assert [k for _n, k, _e in bad] == ["llm"], f"注入 local_runner 未被判红：{bad}"

    def test_injected_eval_step_id_reds(self):
        wf = self._wf()
        wf["jobs"]["map"]["steps"][0]["id"] = "eval"
        bad = pr_layer_machinery_problems({"injected.yml": wf})
        assert [k for _n, k, _e in bad] == ["eval-step"], f"注入 id: eval 未被判红：{bad}"

    def test_injected_eval_slot_reds(self):
        bad = pr_layer_machinery_problems(
            {"injected.yml": self._wf(concurrency={"group": "eval-stack-global", "cancel-in-progress": False})})
        assert [k for _n, k, _e in bad] == ["eval-slot"], f"注入评测槽位未被判红：{bad}"

    def test_injected_flake_ledger_reds(self):
        bad = pr_layer_machinery_problems(
            {"injected.yml": self._wf("echo agent-eval-flakes.json")})
        assert [k for _n, k, _e in bad] == ["flake-ledger"], f"注入波动台账未被判红：{bad}"

    def test_comment_only_injection_is_not_flagged(self):
        """负控：机具只在**整行注释**里出现 ⇒ 不得判红（否则会逼出无谓的改注释）。"""
        bad = pr_layer_machinery_problems(
            {"injected.yml": self._wf("set -e\n# 曾经的评测：local_runner.py + docker compose\necho hi")})
        assert bad == [], f"整行注释里的机具被当成真实机具（假红来源）：{bad}"

    def test_clean_pr_workflow_is_not_flagged(self):
        """基线负控：一个普通的静态 PR workflow 不得被判红（判据不是"有步骤就红"）。"""
        assert pr_layer_machinery_problems({"clean.yml": self._wf("pytest -q")}) == []
