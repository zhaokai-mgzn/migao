"""
Danger Scan — PR 破坏性变更检测（analyze 纯函数单元测试）

场景：新增/修改 workflow（含 secrets 引用）、批量删除、部署文件变更、数据库迁移不可变、DDL 伴随迁移。
"""
# case_ids: DF-010, OB-001
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".github"))

from danger_scan import (
    analyze,
    _truly_new_secret_lines,
    parse_delete_acks,
    ack_env_lines,
    parse_migration_acks,
    migration_ack_env_lines,
    verify_migration_acks,
)


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

    MIG = "backend/admin-api/src/main/resources/db/migration-archive"

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
            migration_changes=[], schema_changes=[("M", "backend/admin-api/src/main/resources/db/init/schema.sql")],
        )
        assert any("未新增迁移" in b for b in blockers)

    def test_schema_change_with_migration_passes(self):
        blockers, _ = analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[("A", f"{self.MIG}/V19__add_x.sql")],
            schema_changes=[("M", "docs/sql/archive/schema_full.sql")],
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

    背景（实证假 blocker）：给 `docs/sql/archive/schema_full.sql` 加废弃标注（纯注释）也被判
    「改了表结构未加迁移」—— 规则本意是「**结构**变更需迁移」，注释不改变结构。
    但放宽这条判定极易开出安全口子：只要判定「没看到 DDL」就放行，那么
    BASE 配错 / 非 git 环境 / diff 读取失败时，**任何**结构改动都会被静默放行。
    故豁免成立的前提是「diff 确实读到了新增行」。
    """

    MIG = "backend/admin-api/src/main/resources/db/migration-archive"

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

    def _analyze(self, schema_file="docs/sql/archive/schema_full.sql"):
        from danger_scan import analyze
        return analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[], schema_changes=[("M", schema_file)],
        )

    def test_comment_only_change_is_exempt(self, monkeypatch):
        diff = (
            "diff --git a/docs/sql/archive/schema_full.sql b/docs/sql/archive/schema_full.sql\n"
            "--- a/docs/sql/archive/schema_full.sql\n"
            "+++ b/docs/sql/archive/schema_full.sql\n"
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
            "+++ b/docs/sql/archive/schema_full.sql\n"
            "+-- 注意：本文件仍会 CREATE TABLE knowledge_documents（已被 V36 DROP）\n"
        )
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze()
        assert not blockers, f"注释里提到 CREATE TABLE 不应 block，实得 {blockers}"

    def test_real_ddl_still_blocks(self, monkeypatch):
        """真正的结构改动必须照旧 block（豁免不得开成安全口子）"""
        diff = (
            "+++ b/backend/admin-api/src/main/resources/db/init/schema.sql\n"
            "+CREATE TABLE brand_new_table (\n"
            "+    id VARCHAR(36) PRIMARY KEY\n"
            "+);\n"
        )
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze(schema_file="backend/admin-api/src/main/resources/db/init/schema.sql")
        assert any("未新增迁移" in b for b in blockers), (
            "新增建表语句必须仍然 block —— 豁免把结构变更也放过了就是安全口子"
        )

    def test_added_alter_table_blocks(self, monkeypatch):
        diff = "+++ b/backend/admin-api/src/main/resources/db/init/schema.sql\n+ALTER TABLE orders ADD COLUMN foo TEXT;\n"
        self._fake_git_diff(monkeypatch, diff)
        blockers, _ = self._analyze(schema_file="backend/admin-api/src/main/resources/db/init/schema.sql")
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


class TestDeleteWorkflowAck:
    """删除 workflow 的**人工确认通道**（#4295）：`DANGER_ACK_DELETE` → 该条降 WARN。

    病根（#4288 实测）：原判据对 `status == "D"` 是**无条件 blocker**，文案写「需人工确认」，
    但**全文没有任何记录确认的地方**（`DANGER_TRUSTED_ACTOR` 只对"新增"降级）⇒ 在
    `enforce_admins=true` 的仓库里「删除任何 workflow」在机制上都不可能合并
    （`gh pr merge --admin` 被 GraphQL 拒、UI 也不提供绕过入口）—— 护栏要求的东西
    **无法被满足** = 恒红护栏（`migao-acceptance` 的同族形态）。

    本类把"确认"落成可执行 + 可留痕的判据，并**钉死无确认时的行为逐字不变**。
    """

    def _analyze(self, changes, acked=()):
        return analyze(
            workflow_changes=changes,
            wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=[], schema_changes=[],
            delete_acked=frozenset(acked),
        )

    PATH = ".github/workflows/pr-check.yml"

    def test_no_ack_still_blocks(self):
        """**负控（防放宽）**：不传 ack ⇒ 与补通道前逐字同形（仍 BLOCK）。"""
        blockers, warnings = self._analyze([("D", self.PATH)])
        assert any("删除 workflow" in b for b in blockers), (
            "无确认时删除 workflow 不再 BLOCK —— 那等于把这条安全护栏整条砍掉"
        )
        assert not warnings

    def test_owner_ack_downgrades_to_warning(self):
        """确认命中该路径 ⇒ 降为 WARN（不再 blocker），且文案点明"已显式确认"。"""
        blockers, warnings = self._analyze([("D", self.PATH)], acked=[self.PATH])
        assert not blockers, f"已确认的删除仍被 BLOCK：{blockers}"
        assert any("已由维护者显式确认" in w for w in warnings), warnings

    def test_ack_all_covers_every_path(self):
        """`*` = 一次确认全部删除（批量清理场景）。"""
        blockers, warnings = self._analyze(
            [("D", self.PATH), ("D", ".github/workflows/other.yml")], acked=["*"]
        )
        assert not blockers, f"`*` 未覆盖全部删除：{blockers}"
        assert len(warnings) == 2

    def test_ack_for_other_path_does_not_leak(self):
        """**越权隔离**：确认了 A 文件不等于确认了 B 文件（不得整仓库放行）。"""
        blockers, _ = self._analyze(
            [("D", self.PATH)], acked=[".github/workflows/some-other.yml"]
        )
        assert any("删除 workflow" in b for b in blockers), (
            "确认被当成了全局开关 —— 确认一个文件等于放行所有删除"
        )

    def test_ack_does_not_downgrade_new_workflow(self):
        """**作用域锁**：ack 只对"删除"生效，**不得**顺带放宽"新增"（新增风险更高）。"""
        blockers, warnings = self._analyze([("A", self.PATH)], acked=[self.PATH])
        assert any("新增 workflow" in b for b in blockers), (
            "ack 顺带放行了「新增 workflow」—— 那是把确认通道变成万能钥匙"
        )
        assert not warnings



class TestParseDeleteAcks:
    """确认解析 = **行为级**纯函数测试（#4295）。

    ⚠️ 上一版把这些判据写成「pr-check.yml 的脚本文本里有没有某几个词」——**红证实测不红**：
    把 owner 过滤整条删掉，断言照样绿（同一脚本里取 ACK_URL 的另一条查询也含那些词）。
    这是空断言（`migao-acceptance`：断言的东西不是"决定放行的那个表达式"）。
    故判据改挂到 `parse_delete_acks()` 上 —— 它才是真正决定放不放行的逻辑。
    """

    OWNER = "zhaokai-mgzn"
    A = ".github/workflows/agent-behavior-eval.yml"
    B = ".github/workflows/other.yml"

    @staticmethod
    def _c(login, body, url="https://example.invalid/c/1"):
        return {"user": {"login": login}, "body": body, "html_url": url}

    def test_no_comments_acks_nothing(self):
        acked, via = parse_delete_acks([], self.OWNER, [self.A])
        assert acked == set() and via == ""

    def test_owner_marker_for_exact_path(self):
        comments = [self._c(self.OWNER, f"同意删除\n/danger-ack delete-workflow {self.A}")]
        acked, via = parse_delete_acks(comments, self.OWNER, [self.A, self.B])
        assert acked == {self.A}, f"只确认了 A，却放行了 {acked}"
        assert via, "留痕缺确认评论链接"

    def test_marker_all_covers_every_path(self):
        comments = [self._c(self.OWNER, "/danger-ack delete-workflow all")]
        acked, _ = parse_delete_acks(comments, self.OWNER, [self.A, self.B])
        assert acked == {self.A, self.B}

    def test_non_owner_comment_is_ignored(self):
        """**核心安全判据**：非 owner 评论一律不采信（否则任何人一句话就能删 workflow）。"""
        comments = [self._c("random-contributor", f"/danger-ack delete-workflow {self.A}")]
        acked, via = parse_delete_acks(comments, self.OWNER, [self.A])
        assert acked == set(), f"非 owner 的确认被采信：{acked}"
        assert via == ""

    def test_empty_owner_never_acks(self):
        """owner 未配置（env 缺失）⇒ 一律不放行（fail-closed，不得退化成"谁都可以"）。"""
        comments = [self._c("", "/danger-ack delete-workflow all")]
        acked, _ = parse_delete_acks(comments, "", [self.A])
        assert acked == set()

    def test_ack_for_other_path_does_not_leak(self):
        comments = [self._c(self.OWNER, f"/danger-ack delete-workflow {self.B}")]
        acked, _ = parse_delete_acks(comments, self.OWNER, [self.A])
        assert acked == set(), "确认被当成全局开关（确认 B 等于放行 A）"

    def test_marker_without_path_is_not_a_wildcard(self):
        """裸 marker（没跟路径、也没跟 all）**不得**匹配任何路径。"""
        comments = [self._c(self.OWNER, "/danger-ack delete-workflow")]
        acked, _ = parse_delete_acks(comments, self.OWNER, [self.A])
        assert acked == set()

    def test_paginated_slurp_shape_is_flattened(self):
        """`gh api --paginate --slurp` 产出「页数组的数组」（两页）—— 展平后照常解析。"""
        page1 = [self._c(self.OWNER, "第一页：无 marker")]
        page2 = [self._c(self.OWNER, f"第二页：/danger-ack delete-workflow {self.A}")]
        raw = [page1, page2]
        flat = [c for page in raw for c in page]   # workflow 里就是靠 danger_scan 内部展平
        acked, _ = parse_delete_acks(flat, self.OWNER, [self.A, self.B])
        assert acked == {self.A}, acked

    def test_junk_entries_do_not_crash_or_ack(self):
        """非法元素（字符串 / None / 数字）不得崩、不得误放行。"""
        acked, _ = parse_delete_acks(
            ["junk", None, 42, self._c(self.OWNER, "没有 marker")], self.OWNER, [self.A]
        )
        assert acked == set()

    def test_env_lines_are_empty_when_nothing_acked(self):
        lines = ack_env_lines(set(), self.OWNER, "")
        assert lines[0] == "DANGER_ACK_DELETE=", lines
        assert all("danger-ack" not in ln for ln in lines)

    def test_env_lines_carry_audit_identity(self):
        lines = ack_env_lines({self.A}, self.OWNER, "https://example.invalid/c/9")
        joined = "\n".join(lines)
        assert f"DANGER_ACK_DELETE={self.A}" in joined
        assert f"DANGER_ACK_BY={self.OWNER}" in joined
        assert "https://example.invalid/c/9" in joined


class TestAckStepWiringIsThin:
    """接线锁（L0 静态）：ack 步骤只做「取评论 → 交给纯函数 → 写 GITHUB_ENV」。

    判据**刻意只锁结构与 fail-closed 出口**，不锁判定逻辑的词句（词句判据已被证明会空跑）——
    逻辑正确性由上面的 `TestParseDeleteAcks` 行为级覆盖。
    """

    WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr-check.yml"

    def _job(self) -> dict:
        import yaml
        wf = yaml.safe_load(self.WF.read_text(encoding="utf-8")) or {}
        return (wf.get("jobs") or {})["danger-scan"]

    def _ack_step(self) -> dict:
        for s in self._job().get("steps") or []:
            if "acks" in str(s.get("name") or ""):
                return s
        raise AssertionError("pr-check 的 danger-scan job 里找不到 ack 步骤")

    def test_ack_step_runs_before_scan(self):
        names = [str(s.get("name") or "") for s in self._job().get("steps") or []]
        i_ack = next(i for i, n in enumerate(names) if "acks" in n)
        i_scan = next(i for i, n in enumerate(names) if n == "Run danger scan")
        assert i_ack < i_scan, "ack 步骤必须在 danger scan 之前（否则 env 还没注入）"

    def test_ack_step_delegates_to_pure_function(self):
        script = self._ack_step()["run"]
        assert "--resolve-acks" in script, (
            "ack 步骤没有调用 danger_scan.py --resolve-acks —— 判定逻辑又回到 YAML 字符串里了"
        )

    def test_ack_step_fails_closed_on_api_error(self):
        """评论 API 失败 ⇒ 提前 exit 0（不写任何 ack ⇒ danger_scan 仍 BLOCK）。"""
        script = self._ack_step()["run"]
        assert "exit 0" in script, "评论 API 失败时没有提前返回 ⇒ 会带着空文件继续往下跑"
        assert "fail-closed" in script, "缺少 fail-closed 的显式说明（防后人当可删注释）"

    def test_marker_lives_in_python_not_in_yaml(self):
        """**结构锁**：确认 marker 只许出现在 `danger_scan.py`（有行为级单测的地方）。

        反向变异：把 `/danger-ack delete-workflow` 的匹配写回 YAML ⇒ 本断言红 ——
        那正是首版"空断言"的形态（判据落在脚本文本上，删掉真逻辑照样绿）。
        """
        script = self._ack_step()["run"]
        assert "/danger-ack delete-workflow" not in script, (
            "确认 marker 出现在 workflow YAML 里 —— 判定逻辑又被搬回字符串匹配了"
        )
        assert "DANGER_ACK_OWNER" not in script or "parse_delete_acks" in script

    def test_ack_step_writes_env_via_pure_function(self):
        """ack 经 `--resolve-acks` 的 stdout 写 GITHUB_ENV（唯一写入口）。"""
        script = self._ack_step()["run"]
        assert '--resolve-acks >> "$GITHUB_ENV"' in script, (
            "ack 不是由纯函数输出写入 GITHUB_ENV —— 出现了第二套写入口"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 已发布迁移被**重写**的人工确认通道（#4936：授权把 V102~V106 合并为单条 V102）
# ══════════════════════════════════════════════════════════════════════════════
#
# 病根：「迁移不可变」判据只看 **git 状态（M/D）**，**不认指纹账本** ⇒ 经维护者裁定的
# 合并重写（#4936 的 5 条从未在任何环境成功应用过的迁移）**结构性过不了 CI**
# （本地实测 5 处 blocker），而既有确认通道只覆盖 workflow 删除。
#
# 本通道与 `delete-workflow` **同形**（同源 owner / 同源评论读取 / 同源 fail-closed），
# 但 ack **不足以**放行 —— 必须同时过 `verify_migration_acks()` 的四条交叉校验。
# 放宽门禁的改动，判据必须比原判据**更严**，否则就是「把护栏换成开关」。


class TestParseMigrationAcks:
    """`/danger-ack rewrite-migration <V###|all>` 的解析（行为级纯函数）。"""

    OWNER = "zhaokai-mgzn"
    MIG = "backend/admin-api/src/main/resources/db/migration-archive"
    V102 = f"{MIG}/V102__rewrite_published.sql"
    V103 = f"{MIG}/V103__other.sql"

    @staticmethod
    def _c(login, body, url="https://example.invalid/c/1"):
        return {"user": {"login": login}, "body": body, "html_url": url}

    def test_owner_marker_for_exact_version(self):
        acked, via = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration V102")],
            self.OWNER, [self.V102, self.V103],
        )
        assert acked == {"V102"}, f"只确认了 V102，却放行了 {acked}"
        assert via, "留痕缺确认评论链接"

    def test_marker_all_covers_every_changed_migration(self):
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration all")],
            self.OWNER, [self.V102, self.V103],
        )
        assert acked == {"V102", "V103"}, f"`all` 未展开为本次改动集合：{acked}"

    def test_all_with_no_changed_migrations_grants_nothing(self):
        """本次没有迁移改动时，`all` 不得变成「全局开关」。"""
        acked, via = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration all")], self.OWNER, [])
        assert acked == set() and via == ""

    def test_non_owner_comment_is_ignored(self):
        """**核心安全判据**：非 owner 评论一律不采信（否则任何人一句话就能改已发布迁移）。"""
        acked, via = parse_migration_acks(
            [self._c("random-contributor", "/danger-ack rewrite-migration all")],
            self.OWNER, [self.V102],
        )
        assert acked == set(), f"非 owner 的确认被采信：{acked}"
        assert via == ""

    def test_empty_owner_never_acks(self):
        """owner 未配置（env 缺失）⇒ 一律不放行（fail-closed，不得退化成"谁都可以"）。"""
        acked, _ = parse_migration_acks(
            [self._c("", "/danger-ack rewrite-migration all")], "", [self.V102])
        assert acked == set()

    def test_no_marker_acks_nothing(self):
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "同意重写，但没写 marker")], self.OWNER, [self.V102])
        assert acked == set()

    def test_empty_comments_acks_nothing(self):
        assert parse_migration_acks([], self.OWNER, [self.V102]) == (set(), "")

    def test_version_match_is_case_insensitive(self):
        """`v102` / `V102` 都算（用户原话里的版本号大小写不敏感）。"""
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration v102")],
            self.OWNER, [self.V102])
        assert acked == {"V102"}, f"小写 v102 未匹配 V102__ 迁移：{acked}"

    def test_lowercase_filename_version_is_recognized(self):
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration V102")],
            self.OWNER, [f"{self.MIG}/v102__rewrite.sql"])
        assert acked == {"V102"}, f"小写文件名的版本号未被识别：{acked}"

    def test_ack_for_unrelated_version_grants_nothing(self):
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration V999")],
            self.OWNER, [self.V102])
        assert acked == set(), "确认被当成全局开关（确认 V999 等于放行 V102）"

    def test_bare_marker_is_not_a_wildcard(self):
        """裸 marker（没跟版本号、也没跟 `all`）**不得**匹配任何版本。"""
        acked, _ = parse_migration_acks(
            [self._c(self.OWNER, "/danger-ack rewrite-migration")], self.OWNER, [self.V102])
        assert acked == set()

    def test_junk_entries_do_not_crash_or_ack(self):
        acked, _ = parse_migration_acks(
            ["junk", None, 42, self._c(self.OWNER, "/danger-ack rewrite-migration all")],
            self.OWNER, [])
        assert acked == set()

    def test_env_lines_empty_when_nothing_acked(self):
        lines = migration_ack_env_lines(set(), self.OWNER, "")
        assert lines[0] == "DANGER_ACK_MIGRATION=", lines
        assert all("rewrite-migration" not in ln for ln in lines)

    def test_env_lines_carry_versions_and_audit_identity(self):
        joined = "\n".join(migration_ack_env_lines(
            {"V103", "V102"}, self.OWNER, "https://example.invalid/c/9"))
        assert "DANGER_ACK_MIGRATION=V102,V103" in joined, joined
        assert f"DANGER_ACK_MIGRATION_BY={self.OWNER}" in joined
        assert "DANGER_ACK_MIGRATION_URL=https://example.invalid/c/9" in joined


class TestVerifyMigrationAcks:
    """交叉校验纯函数（四条判据各自独立，互不掩盖）。"""

    MIG = "backend/admin-api/src/main/resources/db/migration-archive"
    V102 = f"{MIG}/V102__rewrite_published.sql"
    NAME = "V102__rewrite_published.sql"
    H = "sha256:" + "a" * 64
    H2 = "sha256:" + "b" * 64

    def _verify(self, changes, acked=("V102",), *, ledger_changed=True, entries=None, disk=None):
        return verify_migration_acks(
            frozenset(acked), changes, ledger_changed,
            {self.NAME: self.H} if entries is None else entries,
            {self.NAME: self.H} if disk is None else disk,
        )

    def test_granted_when_all_checks_pass(self):
        granted, problems = self._verify([("M", self.V102)])
        assert granted == {"V102"} and not problems

    def test_no_ledger_update_rejects(self):
        granted, problems = self._verify([("M", self.V102)], ledger_changed=False)
        assert granted == set()
        assert "同批更新" in problems["V102"], problems

    def test_disk_hash_mismatch_rejects(self):
        granted, problems = self._verify([("M", self.V102)], disk={self.NAME: self.H2})
        assert granted == set()
        assert "哈希与磁盘不符" in problems["V102"] and "--write-ledger" in problems["V102"]

    def test_unreadable_ledger_fails_closed(self):
        """`ledger_entries=None`（读不到账本）≠ `{}`（账本里没这条）—— 前者必须 fail-closed。"""
        granted, problems = verify_migration_acks(
            frozenset({"V102"}), [("M", self.V102)], True, None, {self.NAME: self.H})
        assert granted == set(), "读不到账本却放行了 —— 安全门禁的失效方向必须是报错"
        assert "无法读取指纹账本" in problems["V102"], problems

    def test_delete_ack_requires_ledger_entry_removed(self):
        granted, problems = self._verify([("D", self.V102)])
        assert granted == set()
        assert "账本仍留有该文件名" in problems["V102"], problems
        granted2, problems2 = self._verify([("D", self.V102)], entries={})
        assert granted2 == {"V102"} and not problems2

    def test_ack_for_unmodified_version_is_inert(self):
        granted, problems = self._verify([("M", self.V102)], acked=("V999",))
        assert granted == set() and not problems, "ack 了本次没改的版本 ⇒ 不算数（也不报错）"

    def test_rename_with_content_change_is_not_ackable(self):
        """`R0xx`（改名 + 内容变化）不是 M/D ⇒ ack 不得顺带豁免它。"""
        granted, _ = self._verify([("R062", self.V102)])
        assert granted == set()


class TestMigrationRewriteAck:
    """`analyze` **行为级**：ack + 交叉校验通过 ⇒ 降 WARN；任一条件不满足 ⇒ 照旧 BLOCK。"""

    MIG = "backend/admin-api/src/main/resources/db/migration-archive"
    V102 = f"{MIG}/V102__rewrite_published.sql"
    V103 = f"{MIG}/V103__other.sql"
    NAME102 = "V102__rewrite_published.sql"
    H = "sha256:" + "a" * 64
    H2 = "sha256:" + "b" * 64
    BY = "zhaokai-mgzn"
    URL = "https://example.invalid/pr/4936#issuecomment-1"

    def _analyze(self, changes, acked=(), *, ledger_changed=True, entries=None, disk=None):
        return analyze(
            workflow_changes=[], wf_new_secrets={}, deleted_files=[], deploy_files=[],
            migration_changes=changes, schema_changes=[],
            migration_acked=frozenset(acked),
            migration_ack_by=self.BY, migration_ack_url=self.URL,
            ledger_changed=ledger_changed,
            ledger_entries={self.NAME102: self.H} if entries is None else entries,
            disk_hashes={self.NAME102: self.H} if disk is None else disk,
        )

    def test_no_ack_still_blocks_verbatim(self):
        """**负控（防放宽）**：不传 ack ⇒ 与补通道前**逐字同形**（仍 BLOCK）。"""
        blockers, warnings = self._analyze([("M", self.V102)])
        expected = (
            f"已发布迁移被修改/删除 {self.V102} —— 迁移不可变（MigrationRunner 按序执行，"
            f"改动会导致线上 DB 与代码脱节），只能新增 V{{n+1}}__ 迁移"
        )
        assert blockers == [expected], f"无 ack 时的行为必须逐字不变，实得 {blockers}"
        assert not warnings

    def test_deleted_migration_no_ack_still_blocks_verbatim(self):
        blockers, _ = self._analyze([("D", self.V102)])
        assert len(blockers) == 1 and "迁移不可变" in blockers[0]

    def test_ack_with_ledger_updated_and_hash_match_passes(self):
        """① ack + 账本已更新 + 哈希一致 ⇒ 无 blocker，且 WARN 带齐留痕三要素。"""
        blockers, warnings = self._analyze([("M", self.V102)], acked=["V102"])
        assert not blockers, f"已确认且账本一致仍被 BLOCK：{blockers}"
        joined = "\n".join(warnings)
        assert "已由维护者显式确认" in joined, joined
        assert self.BY in joined, "WARN 文案缺确认人"
        assert self.URL in joined, "WARN 文案缺评论链接"
        assert "账本哈希一致" in joined, "WARN 文案缺「账本哈希一致」"

    def test_ack_without_ledger_update_still_blocks(self):
        """② ack 但账本**未**同批更新 ⇒ 仍 BLOCK（文案点明原因）。"""
        blockers, warnings = self._analyze(
            [("M", self.V102)], acked=["V102"], ledger_changed=False)
        joined = "\n".join(blockers)
        assert "迁移不可变" in joined, blockers
        assert "同批更新" in joined and "migration_fingerprints.json" in joined, blockers
        assert not any("已由维护者显式确认" in w for w in warnings), (
            "账本没跟上却降级为 WARN —— ack 被当成了万能钥匙"
        )

    def test_ack_with_ledger_disk_mismatch_still_blocks(self):
        """③ 账本哈希与磁盘不符 ⇒ 仍 BLOCK（防「ack 了但忘了登记新指纹」）。"""
        blockers, _ = self._analyze(
            [("M", self.V102)], acked=["V102"], disk={self.NAME102: self.H2})
        joined = "\n".join(blockers)
        assert "哈希与磁盘不符" in joined and "--write-ledger" in joined, blockers

    def test_ack_delete_with_ledger_entry_kept_still_blocks(self):
        """④ 删除型被 ack 但账本仍留名 ⇒ 仍 BLOCK；账本条目已删 ⇒ 放行。"""
        blockers, _ = self._analyze([("D", self.V102)], acked=["V102"])
        assert any("账本仍留有该文件名" in b for b in blockers), blockers
        blockers2, warnings2 = self._analyze([("D", self.V102)], acked=["V102"], entries={})
        assert not blockers2, f"账本条目已删仍被 BLOCK：{blockers2}"
        assert any("已由维护者显式确认" in w for w in warnings2)

    def test_ack_for_unmodified_version_grants_nothing(self):
        """⑥ ack 了本次没改的版本 ⇒ 不放行任何东西（本次真改的仍 BLOCK）。"""
        blockers, _ = self._analyze([("M", self.V102)], acked=["V999"])
        assert any("迁移不可变" in b for b in blockers), "ack 了没改的版本却放行了 V102"

    def test_ack_for_unmodified_version_with_no_changes_is_not_an_error(self):
        blockers, warnings = self._analyze([], acked=["V999"])
        assert not blockers and not warnings

    def test_unacked_sibling_migration_still_blocks(self):
        """④「本次改了但没 ack 的 ⇒ 照旧 BLOCK（逐个报）」—— 确认不得顺带放行兄弟文件。"""
        blockers, _ = self._analyze(
            [("M", self.V102), ("M", self.V103)], acked=["V102"],
            entries={self.NAME102: self.H}, disk={self.NAME102: self.H})
        assert any(self.V103 in b for b in blockers), blockers
        assert not any(self.V102 in b for b in blockers), blockers

    def test_ack_does_not_exempt_rename_with_content_change(self):
        """**作用域锁**：ack 只对 M/D 生效，不得顺带放宽 `R0xx`（改名 + 内容变化）。"""
        blockers, _ = self._analyze([("R062", self.V102)], acked=["V102"])
        assert any("迁移不可变" in b for b in blockers), (
            "ack 顺带放行了「改名 + 内容变化」—— 那是把确认通道变成万能钥匙"
        )

    def test_ledger_entry_missing_blocks_with_regen_hint(self):
        blockers, _ = self._analyze(
            [("M", self.V102)], acked=["V102"], entries={}, disk={self.NAME102: self.H})
        assert any("--write-ledger" in b for b in blockers), blockers


class TestMigrationAckResolveMode:
    """`--resolve-acks`：除既有三行外**追加**迁移三行；迁移清单由脚本自己算。"""

    OWNER = "zhaokai-mgzn"
    MIG = "backend/admin-api/src/main/resources/db/migration-archive"
    V102 = f"{MIG}/V102__rewrite_published.sql"
    V103 = f"{MIG}/V103__other.sql"

    def _run(self, monkeypatch, tmp_path, capsys, body, changes):
        import json as _json

        import danger_scan

        comments_path = tmp_path / "pr-comments.json"
        comments_path.write_text(_json.dumps(
            [{"user": {"login": self.OWNER}, "body": body,
              "html_url": "https://example.invalid/c/42"}]),
            encoding="utf-8")
        monkeypatch.setenv("DANGER_COMMENTS_JSON", str(comments_path))
        monkeypatch.setenv("DANGER_OWNER", self.OWNER)
        monkeypatch.delenv("DANGER_DELETED_WORKFLOWS", raising=False)
        monkeypatch.setattr(
            danger_scan, "_git_name_status",
            lambda scope: list(changes) if scope.endswith("*.sql") else [])
        danger_scan.resolve_acks_main()
        return capsys.readouterr()

    def test_prints_migration_env_lines(self, monkeypatch, tmp_path, capsys):
        cap = self._run(
            monkeypatch, tmp_path, capsys, "/danger-ack rewrite-migration all",
            [("M", self.V102), ("D", self.V103)])
        assert "DANGER_ACK_MIGRATION=V102,V103" in cap.out, cap.out
        assert f"DANGER_ACK_MIGRATION_BY={self.OWNER}" in cap.out, cap.out
        assert "DANGER_ACK_MIGRATION_URL=https://example.invalid/c/42" in cap.out, cap.out
        # 既有三行**逐字不变**（同一次调用里两个通道各写各的）
        assert "DANGER_ACK_DELETE=\n" in cap.out + "\n", cap.out

    def test_heartbeat_is_visible(self, monkeypatch, tmp_path, capsys):
        """**心跳**：静默失效（读不到评论 ⇒ 永远不放行）必须肉眼可见。"""
        cap = self._run(
            monkeypatch, tmp_path, capsys, "/danger-ack rewrite-migration V102",
            [("M", self.V102)])
        assert "迁移 ack" in cap.err, f"缺迁移通道心跳行：{cap.err!r}"
        assert "V102" in cap.err, cap.err

    def test_non_owner_comment_yields_empty_env(self, monkeypatch, tmp_path, capsys):
        import json as _json

        import danger_scan

        comments_path = tmp_path / "pr-comments.json"
        comments_path.write_text(_json.dumps(
            [{"user": {"login": "random-contributor"},
              "body": "/danger-ack rewrite-migration all",
              "html_url": "https://example.invalid/c/43"}]), encoding="utf-8")
        monkeypatch.setenv("DANGER_COMMENTS_JSON", str(comments_path))
        monkeypatch.setenv("DANGER_OWNER", self.OWNER)
        monkeypatch.setattr(
            danger_scan, "_git_name_status",
            lambda scope: [("M", self.V102)] if scope.endswith("*.sql") else [])
        danger_scan.resolve_acks_main()
        cap = capsys.readouterr()
        assert "DANGER_ACK_MIGRATION=\n" in cap.out + "\n", cap.out
        assert "DANGER_ACK_MIGRATION_BY=\n" in cap.out + "\n", cap.out


class TestMigrationAckScanMode:
    """scan 模式端到端：从 `DANGER_ACK_MIGRATION` 读入，**并重跑交叉校验**（不只信环境变量）。"""

    LEDGER = "tests/unit_ci_workflows/migration_fingerprints.json"
    MIG = "backend/admin-api/src/main/resources/db/migration-archive"
    # 用一条**真实且已登记**的迁移：账本指纹必须等于磁盘指纹（本 worktree 干净 ⇒ 恒等）
    REAL = f"{MIG}/V1__add_permissions_to_users.sql"

    def _run_main(self, monkeypatch, tmp_path, by_scope, env=None):
        import json as _json

        import danger_scan

        monkeypatch.setattr(
            danger_scan, "_git_name_status", lambda scope: list(by_scope.get(scope, [])))
        for k, v in (env or {}).items():
            monkeypatch.setenv(k, v)
        monkeypatch.chdir(tmp_path)
        try:
            danger_scan.main()
            rc = 0
        except SystemExit as e:
            rc = e.code
        payload = _json.loads((tmp_path / "danger-scan-result.json").read_text(encoding="utf-8"))
        return rc, payload

    def _scopes(self, *, ledger_changed=True):
        import danger_scan

        return {
            ".": [("M", self.REAL)] + ([("M", self.LEDGER)] if ledger_changed else []),
            danger_scan.MIGRATION_DIR + "/*.sql": [("M", self.REAL)],
        }

    ACK_ENV = {
        "DANGER_ACK_MIGRATION": "V1",
        "DANGER_ACK_MIGRATION_BY": "zhaokai-mgzn",
        "DANGER_ACK_MIGRATION_URL": "https://example.invalid/c/42",
    }

    def test_no_ack_blocks(self, monkeypatch, tmp_path):
        rc, payload = self._run_main(monkeypatch, tmp_path, self._scopes())
        assert rc == 1, payload
        assert any("迁移不可变" in b for b in payload["blockers"]), payload["blockers"]

    def test_ack_with_consistent_ledger_passes_and_is_audited(self, monkeypatch, tmp_path):
        rc, payload = self._run_main(monkeypatch, tmp_path, self._scopes(), self.ACK_ENV)
        assert rc == 0, f"ack + 账本一致仍被 BLOCK：{payload['blockers']}"
        acks = [a for a in payload["acks"] if a.get("version")]
        assert acks and acks[0]["version"] == "V1", payload["acks"]
        assert acks[0]["by"] == "zhaokai-mgzn" and acks[0]["via"].startswith("https://")

    def test_scan_mode_rechecks_ledger(self, monkeypatch, tmp_path):
        """**不能只信环境变量**：账本本次没改 ⇒ 即便 ack 存在也必须 BLOCK。"""
        rc, payload = self._run_main(
            monkeypatch, tmp_path, self._scopes(ledger_changed=False), self.ACK_ENV)
        assert rc == 1, f"账本没改却放行了：{payload}"
        assert any("同批更新" in b for b in payload["blockers"]), payload["blockers"]


class TestArchiveMoveIsNotARewrite:
    """**归档搬家 ≠ 重写已发布迁移**（issue #5243）—— `split_migration_moves()` 的判据与红证。

    ## 为什么需要这条（实测）

    迁移链整链归档是一次 `git mv`（内容逐字节未变），但 `danger_scan` 的
    `_git_name_status()` 是**按目录分片**跑的 ⇒ git 配不出 old↔new：
    归档片全报 `A`、活目录片全报 `D` ⇒ 116 处 blocker，PR 被卡死。
    而用 ack 放行 116 次「删除」，在审计上等于「owner 批准删除已发布迁移」—— 错误先例。

    ## 判据（**同时**满足才算搬家；否则照旧按真删除 ⇒ blocker）

      ① 该 `D` 路径的文件名在**另一个**载体目录里存在；
      ② 那份文件的内容与 **merge-base 上原路径的 blob** sha256 **逐字节相同**。

    下面五条各自**单独可红**（把对应分支改掉即红），且都**不放过**真改写/真删除。
    """

    LIVE = "backend/admin-api/src/main/resources/db/migration"
    ARCH = "backend/admin-api/src/main/resources/db/migration-archive"

    @staticmethod
    def _identical(monkeypatch, digest="sha256:same"):
        import danger_scan
        monkeypatch.setattr(danger_scan, "_sha256_of", lambda rel: digest)
        monkeypatch.setattr(danger_scan, "_blob_sha256_at_base",
                            lambda rel, base=None: digest)

    def test_identical_content_is_recognised_as_a_move(self, monkeypatch):
        """① 内容逐字节一致 ⇒ 认作搬家（不进 blocker 面），且**单独报告**（不静默）。"""
        import danger_scan
        self._identical(monkeypatch)
        kept, moves = danger_scan.split_migration_moves(
            [("D", f"{self.LIVE}/V50__create_client_request_keys.sql")])
        assert kept == [], f"搬家被当成改动 ⇒ 整链归档会被 116 处 blocker 卡死：{kept}"
        assert moves == [("D", f"{self.LIVE}/V50__create_client_request_keys.sql",
                          f"{self.ARCH}/V50__create_client_request_keys.sql")], moves

    def test_one_byte_changed_is_still_a_rewrite(self, monkeypatch):
        """② **改了内容再搬** ⇒ 留在判定面（⇒ 照旧 BLOCK）—— 这是本判据的红线。"""
        import danger_scan
        monkeypatch.setattr(danger_scan, "_sha256_of", lambda rel: "sha256:new")
        monkeypatch.setattr(danger_scan, "_blob_sha256_at_base",
                            lambda rel, base=None: "sha256:old")
        kept, moves = danger_scan.split_migration_moves(
            [("D", f"{self.LIVE}/V50__create_client_request_keys.sql")])
        assert moves == [], "内容变了还被当成搬家 ⇒ 重写已发布迁移从这个口子溜过去了"
        assert [p for _s, p in kept] == [f"{self.LIVE}/V50__create_client_request_keys.sql"], kept

    def test_deleted_archive_entry_without_counterpart_is_kept(self, monkeypatch):
        """③ 从**归档**里删一条、活目录里没有同名件 ⇒ 真删除（⇒ 照旧 BLOCK）。

        用真实文件系统判据（不 stub 内容比对）：`V50` 在归档里、活目录里没有同名件。
        """
        import danger_scan
        self._identical(monkeypatch)   # 即便「内容一致」也不该放行 —— 关键是**没有对应件**
        got = danger_scan._repo_file(f"{self.ARCH}/V50__create_client_request_keys.sql")
        assert got.is_file(), f"夹具前提不成立（归档里应有 {got}）"
        kept, moves = danger_scan.split_migration_moves(
            [("D", f"{self.ARCH}/V50__create_client_request_keys.sql")])
        assert moves == [], "归档件被删却当成搬家 ⇒ 「删掉历史迁移」失去护栏"
        assert [p for _s, p in kept] == [f"{self.ARCH}/V50__create_client_request_keys.sql"]

    def test_genuinely_deleted_live_migration_is_kept(self, monkeypatch):
        """④ 真删一条**活目录**里的迁移（归档无同名件）⇒ 照旧进判定面（BLOCK）。"""
        import danger_scan
        self._identical(monkeypatch)
        live = sorted((danger_scan._repo_file(self.LIVE)).glob("V*.sql"))
        assert live, "活目录当前应有至少一条迁移（切点之后的增量）—— 夹具前提"
        path = f"{self.LIVE}/{live[-1].name}"
        kept, moves = danger_scan.split_migration_moves([("D", path)])
        assert moves == [], "真删除被当成搬家 ⇒ 已发布迁移可以静默消失"
        assert [p for _s, p in kept] == [path]

    def test_unreadable_base_blob_fails_closed(self, monkeypatch):
        """⑤ 取不到 merge-base 的 blob（取证失败）⇒ **不得**当成「内容相同」⇒ 留在判定面。"""
        import danger_scan
        monkeypatch.setattr(danger_scan, "_sha256_of", lambda rel: "sha256:x")
        monkeypatch.setattr(danger_scan, "_blob_sha256_at_base",
                            lambda rel, base=None: None)
        kept, moves = danger_scan.split_migration_moves(
            [("D", f"{self.LIVE}/V50__create_client_request_keys.sql")])
        assert moves == [], "取证失败被读成「内容相同」⇒ fail-open（本仓最忌的形态）"
        assert len(kept) == 1

    def test_non_delete_statuses_pass_through_untouched(self, monkeypatch):
        """反向护栏：`M` / `A` 一律原样通过（搬家识别不得顺手吞掉改写/新增）。"""
        import danger_scan
        self._identical(monkeypatch)
        changes = [("M", f"{self.LIVE}/V9__x.sql"), ("A", f"{self.LIVE}/V124__y.sql"),
                   ("R100", f"{self.LIVE}/V45__z.sql")]
        kept, moves = danger_scan.split_migration_moves(changes)
        assert kept == changes and moves == []
