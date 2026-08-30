"""
Danger Scan — PR 破坏性变更检测（analyze 纯函数单元测试）

场景：新增/修改 workflow（含 secrets 引用）、批量删除、部署文件变更。
"""
# case_ids: DF-010
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".github"))

from danger_scan import analyze


class TestWorkflowChanges:
    def test_new_workflow_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("A", ".github/workflows/malicious.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
        )
        assert any("新增 workflow" in b for b in blockers)

    def test_deleted_workflow_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("D", ".github/workflows/pr-check.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
        )
        assert any("删除 workflow" in b for b in blockers)

    def test_workflow_modified_with_new_secrets_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("M", ".github/workflows/deploy.yml")],
            wf_new_secrets={".github/workflows/deploy.yml": ["+        env: ${{ secrets.ALIYUN_AK }}"]},
            deleted_files=[],
            deploy_files=[],
        )
        assert any("secrets" in b for b in blockers)

    def test_workflow_modified_without_secrets_warns_only(self):
        blockers, warnings = analyze(
            workflow_changes=[("M", ".github/workflows/pr-check.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
        )
        assert not blockers
        assert any("修改 workflow" in w for w in warnings)


class TestBulkDeleteAndDeploy:
    def test_bulk_delete_warns(self):
        _, warnings = analyze(
            workflow_changes=[],
            wf_new_secrets={},
            deleted_files=[f"docs/legacy/doc{i}.md" for i in range(35)],
            deploy_files=[],
        )
        assert any("删除" in w and "35" in w for w in warnings)

    def test_deploy_changes_warn(self):
        _, warnings = analyze(
            workflow_changes=[],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=["deploy/swas/deploy.sh"],
        )
        assert any("部署" in w for w in warnings)

    def test_clean_diff_passes(self):
        blockers, warnings = analyze(
            workflow_changes=[],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
        )
        assert not blockers
        assert not warnings
