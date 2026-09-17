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

    def test_pure_rename_migration_exempt(self):
        """R100 纯改名（内容 100% 相似）＝后合入者让号（issue #3812）→ 豁免，不 block。

        #3812 场景：两个 V45 撞号，后合入者改名让号（V45__x → V46__x）。git 对纯改名
        报 status R100（相似度 100%），SQL 内容零变化 —— 线上 schema_migrations 已有
        旧文件名记录（历史事实不改写），新名首跑为幂等空操作（如 ADD COLUMN IF NOT EXISTS）。
        此时仍按「迁移不可变」block 会堵死 #3812 的唯一合规修法。
        """
        blockers, warnings = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("R100", f"{self.MIG}/V46__add_order_logistics_shipper_name.sql")],
            schema_changes=[],
        )
        assert not blockers, f"R100 纯改名（让号）不应 block，实得 {blockers}"
        assert any("改名" in w for w in warnings), "应给出'迁移改名'提示"

    def test_rename_with_content_change_still_blocks(self):
        """rename 且内容有变化（非 R100）＝修改已发布迁移 → 仍 fail-closed block。

        判据收紧：只有 100% 相似（纯改名）才豁免；内容任何变化（R0xx）都是
        「改已发布迁移」，不能让让号豁免变成改迁移的口子（§19.1 假绿同族）。
        """
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("R062", f"{self.MIG}/V46__add_order_logistics_shipper_name.sql")],
            schema_changes=[],
        )
        assert any("迁移不可变" in b for b in blockers), (
            f"内容有变化的 rename 必须照旧 block，实得 {blockers}"
        )

    def test_rename_bad_target_name_blocks(self):
        """rename 目标文件名非法仍 block（改名让号也得守命名规范）"""
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("R100", f"{self.MIG}/renamed.sql")], schema_changes=[],
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


# ── 取证 fail-closed + workflow 覆盖 `.yaml`（2026-09-17 收紧）────────────────

class TestForensicsFailClosed:
    """取证失败必须报错，**不得**被读成「没有破坏性变更」；workflow 扫描必须覆盖 `.yaml`。

    病根（实测，非推断）：

    ① `_git_name_status` 旧实现是裸 `except: return []`，**且不看 returncode** ——
       `BASE` 配错 / 无共同祖先 / 非 git 仓库 / 超时都会返回 `[]`，于是「取证失败」与
       「本次确实无变更」**不可区分**，整个安全门禁退化成
       「0 变更、0 blocker、✅ danger-scan: 0 blocker / 0 warning」并 exit 0。
       这与本文件 docstring 自称的 fail-closed、以及 schema 分支已经采纳的口径
       （`test_git_diff_failure_fails_closed`）直接矛盾 —— 失效方向对安全门禁只能是报错。

    ② workflow 扫描范围曾写死 `".github/workflows/*.yml"`，而 GitHub Actions **同样执行
       `.yaml`** ⇒ 新增 `.github/workflows/evil.yaml` 不在任何一条判定线里
       （workflow 变更 / 批量删除 / 部署文件三条都看不到）⇒ 安全审查该拦的东西根本没进视野。
       收紧后扫描范围是**整个 `.github/workflows/` 目录**，再按「Actions 实际执行的后缀」过滤。
    """

    @staticmethod
    def _fake_git(monkeypatch, *, rc=0, out="", err="fatal: bad revision 'origin/main...HEAD'"):
        """把 danger_scan 内的 git 调用整体替换掉（返回固定 stdout/returncode/stderr）。"""
        import danger_scan
        import subprocess as _sp

        class _R:
            def __init__(self, stdout, returncode, stderr):
                self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

        real = _sp.run

        def fake_run(cmd, *a, **kw):
            if isinstance(cmd, list) and cmd[:2] == ["git", "diff"]:
                return _R(out, rc, err)
            return real(cmd, *a, **kw)

        monkeypatch.setattr(danger_scan.subprocess, "run", fake_run)

    def test_git_name_status_distinguishes_failure_from_empty(self, monkeypatch):
        """取证失败 → None；真无变更 → `[]`。两者**必须**可区分（旧实现都返回 `[]`）。"""
        import danger_scan

        self._fake_git(monkeypatch, rc=128)
        failed = danger_scan._git_name_status(".")
        self._fake_git(monkeypatch, rc=0, out="")
        empty = danger_scan._git_name_status(".")
        assert failed in (None,), f"取证失败必须返回 None，实得 {failed!r}"
        assert empty == [], f"真无变更必须返回 []，实得 {empty!r}"

    def test_main_fails_closed_when_forensics_fail(self, monkeypatch, tmp_path, capsys):
        """端到端红证：让 git diff 失败 ⇒ main() 必须 exit 1 且 JSON 里有 blocker。

        收紧前同一份输入得到 `✅ danger-scan: 0 blocker / 0 warning` + exit 0。
        """
        import json

        import danger_scan

        self._fake_git(monkeypatch, rc=128)
        monkeypatch.chdir(tmp_path)
        try:
            danger_scan.main()
            rc = 0
        except SystemExit as e:
            rc = e.code
        err = capsys.readouterr().err
        payload = json.loads((tmp_path / "danger-scan-result.json").read_text(encoding="utf-8"))
        assert rc == 1, f"取证失败必须阻塞（exit 1），实得 exit {rc}；stderr={err}"
        assert payload["blocker_count"] >= 1, f"取证失败必须记 blocker，实得 {payload}"
        assert "取证失败" in " ".join(payload["blockers"])

    def test_new_yaml_workflow_is_in_scan_scope(self, monkeypatch):
        """`.yaml` 形态的新增 workflow 必须进入扫描范围（旧 scope 写死 `.yml` 会漏掉它）。"""
        import danger_scan

        name_status = "A\t.github/workflows/evil.yaml\nA\t.github/workflows/also.yaml\n"
        self._fake_git(monkeypatch, rc=0, out=name_status)
        changes = danger_scan._workflow_changes()
        assert changes == [
            ("A", ".github/workflows/evil.yaml"),
            ("A", ".github/workflows/also.yaml"),
        ], f"`.yaml` workflow 必须被纳入扫描范围，实得 {changes}"

    def test_non_workflow_files_in_dir_are_not_flagged(self, monkeypatch):
        """负例（防误伤）：`.github/workflows/` 下的非 workflow 文件不参与判定。"""
        import danger_scan

        self._fake_git(monkeypatch, rc=0, out="A\t.github/workflows/README.md\n")
        assert danger_scan._workflow_changes() == [], (
            "Actions 不执行的后缀不属于 workflow 变更，不得误报"
        )

    def test_new_yaml_workflow_blocks_end_to_end(self):
        """`analyze` 对 `.yaml` 新增 workflow 照旧 BLOCK（覆盖范围的收紧不改变判据）。"""
        blockers, _ = analyze(
            workflow_changes=[("A", ".github/workflows/evil.yaml")],
            wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[], schema_changes=[],
        )
        assert any("新增 workflow" in b for b in blockers)
