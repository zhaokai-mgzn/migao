# case_ids: OR-016, AS-007, PR-019, CH-010, DF-011, DF-012
"""PR 层评测去冗余守卫（issue #3653）—— L0 静态锁，秒级零 LLM。

## 为什么需要这层锁

AD 结论（docs/testing/eval-pipeline-performance.md §6.2）：**PR 层只保留「定向映射用例」
（窄、报告制、fast 迭代档），完整覆盖交给部署后/批次轮**。用户已裁定落地（issue #3653）。
此前每个 AI 行为 PR 跑**四层**真实 LLM（smoke + xiaobu Acceptance + 行为映射双 persona +
B 端云冒烟），实测 2.5h 内 197 次评测 ≈ ¥135-295 —— 而 PR 层信号**不拦合并**
（§16.5：LLM 行为层不进 required），按拦门的价格买不拦门的信号，纯冗余。

本文件锁住**防回退**的四件事（改动若让去冗余退化即红）：

1. **paths 前置门**：`agent-behavior-eval.yml` 只认 `backend/ai-agent-service/app/**`
   （§13.2 映射表源路径口径）—— 纯 cases/文档/前端/评测基建 PR **不触发**行为评测
   （那些由确定性层 L0 测试 / Case Contract / 覆盖门禁 / 部署后全量兜底）；
2. **PR 档 = fast 迭代档**：normal 桶一律 `--max-retries 0`（失败按首跑计入、不重试），
   且**每条 local_runner 调用都带 `--case-ids`**（收窄，绝不整档全量）——
   反向变异（改回 `--max-retries 3` / 去掉收窄）即红；
3. **persona 由命中的用例分桶派生**：`behavior-eval` 的 matrix 必须消费 map job 的
   `personas` 输出（从分桶派生），**禁止写死双端全跑**（无差别双 persona = 白烧一端腿）——
   反向变异（写死 `persona: [mibao, xiaobu]`）即红；
4. **报告制不退化**：评测步骤**恒 exit 0**（规则命中失败降级为「报告 + PR 评论 + 自动开
   issue」）——与既有的 `test_eval_stack_seed_parity.py::TestBehaviorGateIsNonBlocking`
   同一语义，这里在 fast 新形态下重申（fast 不是把红改绿的理由）；
5. **另两层冗余已去除**：`xiaobu-acceptance.yml` 无 `pull_request` 触发（PR 层 C 端信号
   由行为映射档的 xiaobu persona 映射用例承担）、`pr-check.yml` 无 `agent-eval-smoke` job
   （B 端云冒烟评的是**已部署 main**，与本 PR 改动无因果）—— 防止它们被"顺手加回来"。

## case_ids 说明（不编造）

本文件是基建静态锁，不是行为用例本身；声明的 6 条是**该锁要保护的、受 fast/persona/paths
语义直接影响的既有映射用例**（§13.2 映射表 + DEFAULT_BEHAVIOR_CASES 成员）：
OR-016（下单域）、AS-007（换货域）、PR-019（建品域）、CH-010（C 端交互卡，唯一 xiaobu
专属默认集成员）、DF-011/DF-012（防御域，唯一走 full 桶的非 normal 档映射用例）。
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

BEHAVIOR_EVAL = "agent-behavior-eval.yml"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8")) or {}


def _steps(workflow: str) -> list:
    out = []
    for job in (_load(workflow).get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _triggers(name: str) -> dict:
    # yaml 会把裸 `on:` 解析成布尔 True 键（与 test_schema_integrity 同一处理）
    wf = _load(name)
    return wf.get("on") or wf.get(True) or {}


def _eval_step(workflow: str) -> dict:
    steps = [s for s in _steps(workflow) if s.get("id") == "eval"]
    assert steps, f"{workflow} 找不到 id=eval 的评测步骤（守卫前提失效）"
    return steps[0]


class TestPathsFrontGate:
    """paths 前置门：纯文档/cases/前端 PR 不再触发行为评测（issue #3653）。"""

    def test_paths_contains_only_behavior_source(self):
        paths = (_triggers(BEHAVIOR_EVAL).get("pull_request") or {}).get("paths") or []
        assert paths, "agent-behavior-eval 缺 pull_request.paths（守卫前提失效）"
        assert paths == ["backend/ai-agent-service/app/**"], (
            f"paths 应只含行为源文件 {['backend/ai-agent-service/app/**']!r}，实为 {paths!r} —— "
            "纯 cases/文档/前端/评测基建 PR 不应触发行为评测（issue #3653）；"
            "那些改动由确定性层 L0 测试 / Case Contract / 覆盖门禁 / 部署后全量兜底"
        )

    def test_banned_prefixes_not_in_paths(self):
        paths = (_triggers(BEHAVIOR_EVAL).get("pull_request") or {}).get("paths") or []
        for banned in ("docs/", ".github/cases/", "frontend/", "tests/agent_eval/",
                       "tests/e2e/", "backend/admin-api/", "backend/ai-agent-service/tests/"):
            assert not any(banned in p for p in paths), (
                f"paths 含 {banned!r} —— 该类改动不应触发行为评测（issue #3653）"
            )


class TestPrLayerIsFastIteration:
    """PR 触发档必须是 fast 迭代档（§16.2 收窄 + fast = 1-3 分钟，issue #3653）。

    反向变异：把 `--max-retries 0` 改回 `--max-retries 3`、或去掉 `--case-ids` 收窄
    （整档全量）→ 本测试红。
    """

    def test_normal_buckets_run_without_retries(self):
        run = _eval_step(BEHAVIOR_EVAL).get("run") or ""
        # fast：normal 桶 --max-retries 0（失败按首跑结果计入，不重试）
        assert re.search(r"EXTRA=\(--max-retries 0\)", run), (
            "normal 桶未以 --max-retries 0（fast 迭代档）执行 —— "
            "PR 层不得为重试付真实 LLM 分钟数（issue #3653）"
        )
        # 反向：禁止恢复重试预算（完整档/结论档由部署后全量轮承担）
        assert not re.search(r"--max-retries [1-9]", run), (
            "PR 层出现 >0 的重试预算 —— fast 迭代档语义被改回（issue #3653）"
        )

    def test_every_runner_call_is_case_narrowed(self):
        run = _eval_step(BEHAVIOR_EVAL).get("run") or ""
        # 先剔除注释行（防「注释里提到 --case-ids」造成假通过，与管道守卫同法）
        body = "\n".join(ln for ln in run.splitlines() if not ln.lstrip().startswith("#"))
        # local_runner 调用跨行（命令延续到下一行），故按"调用数 == 收窄参数数"判：
        # 每次调用都必须带 --case-ids（禁止整档全量 = 不加任何全量档，issue #3653）。
        n_calls = body.count("local_runner.py")
        assert n_calls >= 1, "评测步骤没有 local_runner 调用（守卫前提失效）"
        assert body.count("--case-ids") == n_calls, (
            f"local_runner 调用 {n_calls} 次但 --case-ids 出现 {body.count('--case-ids')} 次 —— "
            "存在未收窄的调用（整档全量 = PR 层烧全量 LLM，issue #3653）"
        )


class TestPersonaDerivedFromBuckets:
    """persona 必须由命中的用例分桶派生，不允许无差别双 persona（issue #3653）。

    反向变异：把 matrix 写死成 `persona: [mibao, xiaobu]`（双端全跑）→ 本测试红；
    删掉 map job 的分桶派生逻辑 → 本测试红。
    """

    def test_map_job_derives_personas_from_buckets(self):
        map_run = ""
        for s in (_load(BEHAVIOR_EVAL).get("jobs") or {}).get("map", {}).get("steps") or []:
            map_run += s.get("run") or ""
        assert "personas.append" in map_run, (
            "map job 缺失『personas 从分桶派生』逻辑 —— 写死双端 = 无差别双 persona"
            "（白烧不相关 persona 的栈 + 真实 LLM，issue #3653）"
        )
        assert "buckets.get" in map_run, (
            "personas 派生未以分桶为判据 —— 应只跑命中所及 persona 的腿"
        )
        # 单 persona 时只起一套栈：派生循环必须基于真实分桶（非全量 order）
        assert "for p, _suite in order" in map_run and "p not in personas" in map_run, (
            "personas 派生逻辑被改动（应遍历 order 且去重追加）"
        )

    def test_eval_matrix_consumes_map_personas(self):
        be = (_load(BEHAVIOR_EVAL).get("jobs") or {}).get("behavior-eval") or {}
        strategy = be.get("strategy") or {}
        # matrix 是 `${{ fromJSON(needs.map.outputs.personas) }}` 表达式（不是 dict）
        matrix_expr = str(strategy.get("matrix") or "")
        assert "needs.map.outputs.personas" in matrix_expr, (
            f"behavior-eval 的 matrix 未消费 map 的 personas 输出：{matrix_expr!r} —— "
            "写死双端全跑 = 无差别双 persona（issue #3653）"
        )

    def test_no_hardcoded_dual_persona_matrix(self):
        be = (_load(BEHAVIOR_EVAL).get("jobs") or {}).get("behavior-eval") or {}
        matrix_expr = str((be.get("strategy") or {}).get("matrix") or "")
        # 反向变异：写死双端（如 `{"persona":["mibao","xiaobu"]}`）会让 matrix 不再是
        # fromJSON(map 输出) 形态 —— 直接按表达式形态锁定。
        assert "fromJSON" in matrix_expr and "map.outputs.personas" in matrix_expr, (
            f"matrix 被写死（{matrix_expr!r}）—— 单端命中时白烧另一端（issue #3653）"
        )


class TestReportOnlyPreservedWithFast:
    """fast 迭代档**不得**成为把红改绿的借口：报告制语义原样保留（issue #3653）。

    与既有 test_eval_stack_seed_parity.py::TestBehaviorGateIsNonBlocking 同一语义，
    这里在 fast 新形态下重申（快 ≠ 降判据）。
    """

    def test_eval_step_still_exits_zero(self):
        run = _eval_step(BEHAVIOR_EVAL).get("run") or ""
        assert re.search(r"^\s*exit 0\s*$", run, re.M), (
            "评测步骤不再恒 exit 0 —— 规则命中失败会重新让 workflow 变红"
            "（报告制语义回退，2026-09-14 用户裁定，issue #3653 不得翻案）"
        )
        assert not re.search(r"^\s*exit \"?\$?\{?(BLOCK_STATUS|STATUS)", run, re.M), (
            "评测步骤以规则桶退出码 exit —— blocking 语义被恢复"
        )

    def test_rule_failed_signal_still_emitted(self):
        run = _eval_step(BEHAVIOR_EVAL).get("run") or ""
        # fast 后规则命中失败仍要开 issue（强信号落点）—— 判据是用例层面失败集
        assert "rule_failed" in run, "规则命中失败标志被移除（自动开 issue 的前置信号）"
        steps = _steps(BEHAVIOR_EVAL)
        assert any("rule_failed" in str(s.get("if") or "") for s in steps), (
            "开 issue 步骤未绑定规则命中失败 —— 兜底网失败也会开 issue（无因果噪音）"
        )


class TestRedundantLayersRemoved:
    """另两层 PR 冗余（xiaobu PR 触发 / B 端云冒烟）已去除，防被顺手加回（issue #3653）。"""

    def test_xiaobu_acceptance_has_no_pr_trigger(self):
        triggers = _triggers("xiaobu-acceptance.yml")
        assert "pull_request" not in triggers, (
            "xiaobu-acceptance 不应再有 pull_request 触发（已与行为映射档合并去重，"
            "issue #3653）—— PR 层 C 端信号由 agent-behavior-eval 的 xiaobu persona "
            "映射用例承担（覆盖并强于 smoke 的 C 端抽样）"
        )
        for keep in ("workflow_dispatch", "schedule"):
            assert keep in triggers, f"xiaobu-acceptance 丢失 {keep} 触发（按需/每周档必须保留）"

    def test_pr_check_has_no_cloud_smoke_job(self):
        jobs = (_load("pr-check.yml").get("jobs") or {})
        assert "agent-eval-smoke" not in jobs, (
            "pr-check 的 B 端云冒烟 job（打 ai-api.migaozn.com，评的是已部署 main）被加回 —— "
            "与本 PR 改动无因果，B 端信号由行为映射档承担、完整覆盖由 post-deploy 承担"
            "（issue #3653 / AD §6.3）"
        )

    def test_label_jobs_no_longer_reference_removed_job(self):
        jobs = _load("pr-check.yml").get("jobs") or {}
        for job_name in ("label-needs-changes", "clear-needs-changes"):
            needs = (jobs.get(job_name) or {}).get("needs") or []
            assert "agent-eval-smoke" not in needs, (
                f"{job_name} 的 needs 仍引用已移除的 agent-eval-smoke job —— "
                "GitHub 会报『job 不存在』直接红掉打标链路"
            )
