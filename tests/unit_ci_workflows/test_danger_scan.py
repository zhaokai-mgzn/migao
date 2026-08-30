"""
Danger Scan — PR 破坏性变更检测（analyze 纯函数单元测试）

场景：新增/修改 workflow（含 secrets 引用）、批量删除、部署文件变更、数据库迁移不可变、DDL 伴随迁移。
"""
# case_ids: DF-010, OB-001
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
            migration_changes=[],
            schema_changes=[],
        )
        assert any("新增 workflow" in b for b in blockers)

    def test_deleted_workflow_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("D", ".github/workflows/pr-check.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
        )
        assert any("删除 workflow" in b for b in blockers)

    def test_workflow_modified_with_new_secrets_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("M", ".github/workflows/deploy.yml")],
            wf_new_secrets={".github/workflows/deploy.yml": ["+        env: ${{ secrets.ALIYUN_AK }}"]},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
        )
        assert any("secrets" in b for b in blockers)

    def test_workflow_modified_without_secrets_warns_only(self):
        blockers, warnings = analyze(
            workflow_changes=[("M", ".github/workflows/pr-check.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
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
            migration_changes=[],
            schema_changes=[],
        )
        assert any("删除" in w and "35" in w for w in warnings)

    def test_deploy_changes_warn(self):
        _, warnings = analyze(
            workflow_changes=[],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=["deploy/swas/deploy.sh"],
            migration_changes=[],
            schema_changes=[],
        )
        assert any("部署" in w for w in warnings)

    def test_clean_diff_passes(self):
        blockers, warnings = analyze(
            workflow_changes=[],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
        )
        assert not blockers
        assert not warnings


class TestMigrationRules:
    """迁移不可变 / 命名校验 / DDL 伴随迁移（OB-001 关联）"""

    MIG = "backend/admin-api/src/main/resources/db/migration"

    def test_modified_published_migration_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("M", f"{self.MIG}/V18__x.sql")], schema_changes=[],
        )
        assert any("迁移不可变" in b for b in blockers)

    def test_deleted_published_migration_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("D", f"{self.MIG}/V18__x.sql")], schema_changes=[],
        )
        assert any("迁移不可变" in b for b in blockers)

    def test_new_valid_migration_passes(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("A", f"{self.MIG}/V19__add_x.sql")], schema_changes=[],
        )
        assert not blockers

    def test_new_migration_bad_name_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("A", f"{self.MIG}/rename_table.sql")], schema_changes=[],
        )
        assert any("文件名非法" in b for b in blockers)

    def test_schema_change_without_migration_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[], schema_changes=[("M", "docs/sql/schema.sql")],
        )
        assert any("未新增迁移" in b for b in blockers)

    def test_schema_change_with_migration_passes(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("A", f"{self.MIG}/V19__add_x.sql")],
            schema_changes=[("M", "docs/sql/schema_full.sql")],
        )
        assert not blockers
