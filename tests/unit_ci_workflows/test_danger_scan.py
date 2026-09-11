"""
Danger Scan — PR 破坏性变更检测（analyze 纯函数单元测试）

场景：新增/修改 workflow（含 secrets 引用）、批量删除、部署文件变更、数据库迁移不可变、DDL 伴随迁移。
"""
# case_ids: DF-010, OB-001
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".github"))

from danger_scan import analyze, _truly_new_secret_lines


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


class TestMovedSecrets:
    """secrets 引用「移动」不算新增（issue #2949 实证：admin-api docker login 行拆步被误判新增）"""

    def test_moved_secrets_line_not_blocked(self):
        # 同一 secrets 引用从「build 步骤内」移动到「独立 login 步骤」——
        # git diff 显示为一行删除 + 一行新增，但引用的 secret 完全相同 → 不应判为新增
        added = ['+        run: echo "${{ secrets.ACR_PASSWORD }}" | docker login ${{ env.ACR_REGISTRY }} -u ${{ secrets.ACR_USERNAME }} --password-stdin']
        removed = ['-          echo "${{ secrets.ACR_PASSWORD }}" | docker login ${{ env.ACR_REGISTRY }} -u ${{ secrets.ACR_USERNAME }} --password-stdin']
        assert _truly_new_secret_lines(added, removed) == []

    def test_truly_new_secret_blocks(self):
        added = ['+        run: echo "${{ secrets.NEW_SECRET }}" | cmd']
        removed = ['-          echo "${{ secrets.ACR_PASSWORD }}" | cmd']
        assert _truly_new_secret_lines(added, removed) == added

    def test_moved_then_modified_line_blocks(self):
        # 移动且内容变化（引用集合不同）→ 仍是新增（引用集合变化需人工审查）
        added = ['+        run: echo "${{ secrets.ACR_PASSWORD }}" | docker login --password-stdin']
        removed = ['-          echo "${{ secrets.ACR_USERNAME }}" | docker login']
        assert _truly_new_secret_lines(added, removed) == added


class TestTrustedActor:
    """维护者新增 workflow（如发布流程）→ 降为 WARN；非维护者 → BLOCK"""

    def test_new_workflow_trusted_actor_warns(self):
        blockers, warnings = analyze(
            workflow_changes=[("A", ".github/workflows/release.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
            trusted_actor=True,
        )
        assert not blockers
        assert any("新增 workflow" in w for w in warnings)

    def test_new_workflow_untrusted_blocks(self):
        blockers, _ = analyze(
            workflow_changes=[("A", ".github/workflows/evil.yml")],
            wf_new_secrets={},
            deleted_files=[],
            deploy_files=[],
            migration_changes=[],
            schema_changes=[],
            trusted_actor=False,
        )
        assert any("新增 workflow" in b for b in blockers)


class TestSchemaCommentOnlyExemption:
    """schema 文件**纯注释**改动免迁移；但 diff 拿不到时必须 fail-closed（issue #3270）。

    背景（实证假 blocker）：给 `docs/sql/schema_full.sql` 加废弃标注（纯注释）也被判
    「改了表结构未加迁移」—— 规则本意是「**结构**变更需迁移」，注释不改变结构。
    但放宽这条判定极易开出安全口子：只要判定「没看到 DDL」就放行，那么
    BASE 配错 / 非 git 环境 / diff 读取失败时，**任何**结构改动都会被静默放行。
    故豁免成立的前提是「diff 确实读到了新增行」。
    """

    MIG = "backend/admin-api/src/main/resources/db/migration"

    @staticmethod
    def _fake_git_diff(monkeypatch, diff_text: str, returncode: int = 0):
        """把 danger_scan 内部的 git diff 调用替换成固定输出"""
        import danger_scan
        import subprocess as _sp

        class _R:
            def __init__(self, out, rc):
                self.stdout = out
                self.returncode = rc

        real = _sp.run

        def fake_run(cmd, *a, **kw):
            if isinstance(cmd, list) and cmd[:2] == ["git", "diff"]:
                return _R(diff_text, returncode)
            return real(cmd, *a, **kw)

        monkeypatch.setattr(danger_scan.subprocess, "run", fake_run)

    def _analyze(self, schema_file="docs/sql/schema_full.sql"):
        from danger_scan import analyze
        return analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[], schema_changes=[("M", schema_file)],
        )

    def test_comment_only_change_is_exempt(self, monkeypatch):
        diff = (
            "diff --git a/docs/sql/schema_full.sql b/docs/sql/schema_full.sql\n"
            "--- a/docs/sql/schema_full.sql\n"
            "+++ b/docs/sql/schema_full.sql\n"
            "@@ -1,3 +1,6 @@\n"
            "+-- ⚠️ 已废弃（DEPRECATED）—— 请勿用于新建库\n"
            "+--   本文件缺失 finance_transactions 等 6 张表\n"
            " -- 原有注释\n"
        )
        self._fake_git_diff(monkeypatch, diff)
        blockers, warnings = self._analyze()
        assert not blockers, f"纯注释改动不应 block，实得 {blockers}"
        assert any("注释" in w for w in warnings), "应给出'仅注释改动'的提示"

    def test_comment_mentioning_create_table_still_exempt(self, monkeypatch):
        """注释里提到 CREATE TABLE 不算 DDL（否则文档写不了「本文件会创建 X 表」）"""
        diff = (
            "+++ b/docs/sql/schema_full.sql\n"
            "+-- 注意：本文件仍会 CREATE TABLE knowledge_documents（已被 V36 DROP）\n"
        )
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze()
        assert not blockers, f"注释里提到 CREATE TABLE 不应 block，实得 {blockers}"

    def test_real_ddl_still_blocks(self, monkeypatch):
        """真正的结构改动必须照旧 block（豁免不得开成安全口子）"""
        diff = (
            "+++ b/docs/sql/schema.sql\n"
            "+CREATE TABLE brand_new_table (\n"
            "+    id VARCHAR(36) PRIMARY KEY\n"
            "+);\n"
        )
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze(schema_file="docs/sql/schema.sql")
        assert any("未新增迁移" in b for b in blockers), (
            "新增建表语句必须仍然 block —— 豁免把结构变更也放过了就是安全口子"
        )

    def test_added_alter_table_blocks(self, monkeypatch):
        diff = "+++ b/docs/sql/schema.sql\n+ALTER TABLE orders ADD COLUMN foo TEXT;\n"
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze(schema_file="docs/sql/schema.sql")
        assert any("未新增迁移" in b for b in blockers)

    def test_empty_diff_fails_closed(self, monkeypatch):
        """diff 读到但没有任何新增行 → 不得据此判「纯注释」。"""
        self._fake_git_diff(monkeypatch, "")
        blockers, _ = self._analyze()
        assert any("未新增迁移" in b for b in blockers), (
            "空 diff 时不得放行 —— 否则 BASE 配错就能绕过整个 DDL 门禁"
        )

    def test_git_diff_failure_fails_closed(self, monkeypatch):
        """git diff 读取失败（returncode != 0）→ 必须 fail-closed"""
        self._fake_git_diff(monkeypatch, "some output", returncode=128)
        blockers, _ = self._analyze()
        assert any("未新增迁移" in b for b in blockers), (
            "diff 读取失败时不得放行 —— 安全门禁的失效方向必须是报错而非放行"
        )
