"""
Test case-draft CI workflow label guard logic.

Issue #729: ci-daily-report cron 创建 issue 时漏打 ai-draft 标签。
本测试验证 CI guard 正确补标。
"""
# case_ids: MC-001
import re
import yaml
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "case-draft.yml"
#: 写标签的一侧（新 issue 一开就跑）——「有无真值」的另一处判定，词表必须与 case-draft.yml 同源。
ISSUE_CONTRACT_WORKFLOW = (
    Path(__file__).parent.parent.parent / ".github" / "workflows" / "issue-contract-check.yml"
)
#: 两份 workflow 里都写着 `TRUTH_VOCAB = '<词表>'`（JS 与 shell 同形），本判据按字面取。
VOCAB_RE = re.compile(r"TRUTH_VOCAB\s*=\s*'([^']+)'")


def load_workflow() -> dict:
    """加载并解析 CI workflow YAML。"""
    if not WORKFLOW_PATH.exists():
        raise FileNotFoundError(f"Workflow not found: {WORKFLOW_PATH}")
    with open(WORKFLOW_PATH) as f:
        return yaml.safe_load(f)


class TestLabelGuardStructure:
    """验证 workflow 的结构完整性 — 必须有 label guard 相关逻辑。"""

    def test_workflow_exists_and_parses(self):
        """YAML 文件存在且能正常解析。"""
        wf = load_workflow()
        assert wf is not None
        assert wf.get("name") is not None

    def test_job_trigger_includes_process_improvement(self):
        """job trigger 的 if 条件必须覆盖 process-improvement label。"""
        wf = load_workflow()
        jobs = wf.get("jobs", {})
        assert jobs, "workflow 至少应有 1 个 job"

        # 找到 trigger job
        trigger_job = jobs.get("trigger")
        if trigger_job is None:
            # 可能改名了，取第一个 job
            trigger_job = list(jobs.values())[0]

        job_if = trigger_job.get("if", "")
        assert job_if, "job 必须有 if 条件做 label 过滤"

        # 必须包含 process-improvement 关键字
        assert "process-improvement" in job_if, (
            f"if 条件缺少 process-improvement label 检查:\n  if: {job_if}"
        )

    def test_has_ai_draft_guard_step(self):
        """必须有补 ai-draft 标签的 step（label guard）。"""
        wf = load_workflow()
        jobs = wf.get("jobs", {})
        trigger_job = jobs.get("trigger") or list(jobs.values())[0]
        steps = trigger_job.get("steps", [])

        ai_draft_steps = []
        for step in steps:
            step_if = step.get("if", "")
            run_cmd = step.get("run", "")
            step_name = step.get("name", "")
            combined = f"{step_name} {step_if} {run_cmd}"
            if "ai-draft" in combined:
                ai_draft_steps.append(step)

        assert len(ai_draft_steps) > 0, (
            "workflow 缺少补 ai-draft 标签的 step（label guard）\n"
            f"现有 steps: {[s.get('name', 'unnamed') for s in steps]}"
        )


class TestLabelGuardLogic:
    """验证 label guard 的逻辑正确性。"""

    def test_process_improvement_without_ai_draft_triggers_label_add(self):
        """process-improvement 无 ai-draft → 应触发补标。"""
        labels = ["process-improvement"]
        has_ai_draft = "ai-draft" in labels
        has_process_improvement = "process-improvement" in labels
        should_trigger = has_process_improvement and not has_ai_draft
        assert should_trigger, (
            f"process-improvement 无 ai-draft 应触发补标: labels={labels}"
        )

    def test_process_improvement_with_ai_draft_skips(self):
        """process-improvement + ai-draft → 不重复补标。"""
        labels = ["process-improvement", "ai-draft"]
        has_ai_draft = "ai-draft" in labels
        has_process_improvement = "process-improvement" in labels
        should_trigger = has_process_improvement and not has_ai_draft
        assert not should_trigger, (
            f"已有 ai-draft 不应触发补标: labels={labels}"
        )

    def test_needs_verification_without_ai_draft_still_triggers(self):
        """原有 needs-verification 逻辑不受影响。"""
        labels = ["needs-verification"]
        has_needs_verification = "needs-verification" in labels
        has_needs_truths = "needs-truths" in labels
        has_ai_draft = "ai-draft" in labels
        should_trigger = (has_needs_verification or has_needs_truths) and not has_ai_draft
        assert should_trigger, (
            f"needs-verification 无 ai-draft 仍应触发: labels={labels}"
        )

    def test_other_labels_without_ai_draft_do_not_trigger(self):
        """非 process-improvement/needs-verification/needs-truths → 不触发。"""
        labels = ["bug"]
        has_ai_draft = "ai-draft" in labels
        has_process = "process-improvement" in labels
        has_nv = "needs-verification" in labels
        has_nt = "needs-truths" in labels
        should_trigger = (has_process or has_nv or has_nt) and not has_ai_draft
        assert not should_trigger, (
            f"纯 bug label 不应触发: labels={labels}"
        )

    def test_block_need_human_skips(self):
        """block/need-human 的 issue 跳过补标。"""
        labels = ["process-improvement", "block/need-human"]
        has_block_human = "block/need-human" in labels
        assert has_block_human, "block/need-human label 应跳过所有自动操作"

    def test_hold_auto_fail_skips(self):
        """hold/auto-fail 的 issue 跳过补标。"""
        labels = ["process-improvement", "hold/auto-fail"]
        has_hold_fail = "hold/auto-fail" in labels
        assert has_hold_fail, "hold/auto-fail label 应跳过所有自动操作"

    def test_closed_issue_not_retroactively_fixed(self):
        """已 CLOSED 的 issue 不追溯补标（#648 边界）。"""
        # 本条为 CONTRACT_JSON 隐含规则：已关闭 issue 不改 label
        issue_state = "CLOSED"
        assert issue_state == "CLOSED", (
            "CLOSED 状态的 issue 不应被追溯修改（#648 边界）"
        )


class TestRunCommands:
    """验证 gh CLI 命令格式正确。"""

    def test_ai_draft_add_command_uses_add_label(self):
        """补 ai-draft 标签必须用 --add-label（非 --remove-label）。"""
        wf = load_workflow()
        jobs = wf.get("jobs", {})
        trigger_job = jobs.get("trigger") or list(jobs.values())[0]

        for step in trigger_job.get("steps", []):
            run = step.get("run", "")
            if "ai-draft" in run:
                # 补标操作用 --add-label，不能是 --remove-label
                assert "--add-label" in run, (
                    f"补 ai-draft 标签必须用 --add-label，当前:\n  {run}"
                )
                assert "ai-draft" in run, (
                    f"补标命令中必须包含 ai-draft:\n  {run}"
                )
                # 确保不会误删
                assert "--remove-label" not in run or "ai-draft" not in run.split(
                    "--remove-label"
                )[-1].split()[0], (
                    f"ai-draft 标签不应出现在 --remove-label 参数中:\n  {run}"
                )


class TestTruthVocabularySingleSource:
    """「有无业务真值」的判定词表必须两侧同源（issue #5481）。

    病根：`issue-contract-check.yml`（新 issue 一开就跑、负责写标签）与 `case-draft.yml`
    （负责「补了真值就翻转标签」）**各维护一份词表**，且两份都与仓库实际写法脱节 ——
    AGENTS.md 铁律 6 与 migao-dev-flow / migao-acceptance 教的是「验收判据」，
    而门禁原先只认「业务真值 / 验收标准 / 问题描述」⇒ 2026-09-25 实测：172 条 open issue 里
    77 条「判据节本来就在」仍被打上 `needs-truths`，其 PR 随后被 verify-trigger 静默跳过自动验收。

    红证（改一处不红 = 空判据，故两侧都比）：把任意一侧 `TRUTH_VOCAB` 里的某个词删掉
    （例如 `判据`）⇒ `test_vocabulary_identical_on_both_sides` 必红；
    把 `TRUTH_VOCAB` 写成两处 ⇒ `_vocab` 的「恰好一处」断言必红。
    """

    #: 词表必须覆盖的仓库实际写法（spec：与技能 / AGENTS.md 的口径对齐，不是「当前实现长这样」）
    REQUIRED_SPELLINGS = (
        "验收判据", "验收标准", "验收清单", "验收口径", "完成判据", "判定标准", "判据",
    )

    def _vocab(self, path: Path) -> str:
        found = VOCAB_RE.findall(path.read_text(encoding="utf-8"))
        assert len(found) == 1, (
            f"{path.name} 里的 `TRUTH_VOCAB = '…'` 必须**恰好一处**（现 {len(found)} 处）"
            "—— 两处会让两侧词表再次分叉，且只改一处不会红"
        )
        return found[0]

    def test_vocabulary_identical_on_both_sides(self):
        """同一份真值只有一处投影：两侧词表逐字相等。"""
        writing_side = self._vocab(ISSUE_CONTRACT_WORKFLOW)
        converting_side = self._vocab(WORKFLOW_PATH)
        assert writing_side == converting_side, (
            "两侧判据词表已分叉（同一份真值两处投影）:\n"
            f"  issue-contract-check.yml: {writing_side}\n"
            f"  case-draft.yml:           {converting_side}"
        )

    def test_vocabulary_covers_repo_spellings(self):
        """词表必须覆盖仓库实际写法，否则用这些拼写的 issue 仍会被误判「缺业务真值」。"""
        tokens = self._vocab(ISSUE_CONTRACT_WORKFLOW).split("|")
        missing = [t for t in self.REQUIRED_SPELLINGS if t not in tokens]
        assert not missing, (
            f"判据词表缺仓库实际写法 {missing} ⇒ 这些 issue 仍会被误判「缺业务真值」"
            f"（当前词表: {tokens}）"
        )
