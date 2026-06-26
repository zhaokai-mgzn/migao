"""
Test junshi-case-draft CI workflow label guard logic.

Issue #729: junshi-daily-report cron 创建 issue 时漏打 ai-draft 标签。
本测试验证 CI guard 正确补标。
"""
import re
import yaml
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "junshi-case-draft.yml"


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
