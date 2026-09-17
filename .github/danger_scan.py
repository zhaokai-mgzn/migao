#!/usr/bin/env python3
"""danger_scan.py — PR 破坏性变更检测（安全门禁，fail-closed）

检测 PR（origin/main...HEAD）中的破坏性变更：
- BLOCK：新增/删除 workflow 文件、修改 workflow 且新增 secrets 引用（workflow 可携带 secrets 执行）
- BLOCK：已发布数据库迁移被修改/删除（迁移不可变，MigrationRunner 按序执行）；新增迁移命名非法
- BLOCK：修改 docs/sql/schema*.sql（表结构参考）但未同时新增迁移文件（DDL 与迁移脱节）
- WARN：批量删除文件（>=30）、修改生产部署文件、修改 workflow（无新增 secrets）

用法（由 pr-check 的 danger-scan job 调用）：
    python3 .github/danger_scan.py
输出：danger-scan-result.json（JSON）+ 控制台报告；存在 blocker 时 exit 1。
"""
import json
import os
import pathlib
import re
import subprocess
import sys

BASE = os.environ.get("DANGER_BASE", "origin/main")
BULK_DELETE_THRESHOLD = 30

MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration"
SCHEMA_FILES = ("docs/sql/schema.sql", "docs/sql/schema_full.sql")
MIGRATION_RE = re.compile(r"^V\d+__.*\.sql$")

# workflow 目录（**整目录**为扫描范围，不再写 `*.yml` glob）。
# 为什么（2026-09-17 实测的免检口子）：原 scope 写死 `.github/workflows/*.yml`，而 Actions
# **同时**识别 `.yaml` —— 新增一个 `.github/workflows/evil.yaml` 不在任何一条扫描线里
# （workflow 变更、批量删除、部署文件三条判定都看不到它）⇒ danger_scan 报
# 「✅ 0 blocker / 0 warning」而安全审查该拦的东西**根本没进视野**。
# 故按目录取全量，再用「Actions 实际会执行的后缀」过滤 —— 这是「workflow 文件」的定义，
# 不是白名单；未识别的后缀（如 README.md）不属于可执行 workflow，不参与判定。
WORKFLOW_DIR = ".github/workflows"
WORKFLOW_SUFFIXES = (".yml", ".yaml")

SECRET_REF_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)")


def _truly_new_secret_lines(added_lines, removed_lines):
    """从 diff 的 added/removed 行中筛出「真正新增」的 secrets 引用行。

    修复（issue #2949 实证）：把 workflow 里已有的 secrets 引用行从一处移到另一处
    （如 admin-api 的 docker login 从 build 步骤拆为独立 login 步骤）时，
    git diff 显示为「删除一行 + 新增一行」，但引用的 secrets 标识符集合相同——
    这是移动而非新增，不应 BLOCK 合并。

    判定：某新增行引用的每个 secret 名都已在删除行中出现过 → 移动，跳过；
    若引用了删除行中不存在的 secret 名（或删除行无 secret）→ 真新增，保留。
    保守策略：新增行若混入一个真新 secret（其余为移动），整行保留待人工审查。
    """
    removed_refs = set()
    for line in removed_lines:
        removed_refs.update(SECRET_REF_RE.findall(line))
    truly_new = []
    for line in added_lines:
        added_refs = set(SECRET_REF_RE.findall(line))
        if added_refs and added_refs <= removed_refs:
            continue  # 引用的 secret 都是移动过来的，非新增
        truly_new.append(line)
    return truly_new


def analyze(workflow_changes, wf_new_secrets, deleted_files, deploy_files, migration_changes, schema_changes, trusted_actor=False):
    """纯函数：对变更清单做安全判定。返回 (blockers, warnings)。

    Args:
        workflow_changes: [(status, path)]，status ∈ A/M/D/R
        wf_new_secrets:   {path: [新增的含 secrets 的 diff 行]}
        deleted_files:    删除的文件路径列表
        deploy_files:     deploy/ 或 scripts 下被改动的文件列表
        migration_changes: db/migration/*.sql 的 [(status, path)]
        schema_changes:    docs/sql/schema*.sql 的 [(status, path)]
    """
    blockers = []
    warnings = []

    for status, path in workflow_changes:
        if status == "A":
            if trusted_actor:
                warnings.append(f"新增 workflow 文件 {path}（维护者添加，仍建议人工复核）")
            else:
                blockers.append(f"新增 workflow 文件 {path} —— 需人工安全审查（workflow 可携带 secrets 执行）")
        elif status == "D":
            blockers.append(f"删除 workflow 文件 {path} —— 需人工确认")
        elif status[0] in ("M", "R"):
            new_sec = wf_new_secrets.get(path, [])
            real_sec = [l for l in new_sec if "secrets.GITHUB_TOKEN" not in l]
            if real_sec:
                blockers.append(
                    f"{path} 新增 {len(real_sec)} 处非内置 secrets 引用 —— 需人工审查：{real_sec[0].strip()[:80]}"
                )
            else:
                warnings.append(f"修改 workflow {path} —— 建议人工复核")

    # ---- 迁移不可变（R1）：已发布迁移只增不改；新增迁移命名须 V{n}__desc.sql ----
    # R100 豁免（issue #3812 让号场景）：git 对「纯改名」报 status R100（相似度 100%）。
    # 后合入者撞号时按「后合入者让号」约定 rename 到下一个空闲版本号（V45__x → V46__x）：
    #   · SQL 内容零变化（git 判定相似度 100%）—— 不是「修改已发布迁移」；
    #   · 线上 schema_migrations 保留旧文件名记录（历史事实不改写），新名首跑为幂等空操作
    #     （如 ADD COLUMN IF NOT EXISTS），改名安全（MigrationRunner 仅以文件名判已执行）。
    # 判据收紧（防让号豁免变成改迁移的口子）：只有 status == "R100" 才豁免；
    # rename 但内容有变化（R0xx）＝修改已发布迁移，照旧 BLOCK（fail-closed，§19.1 同族）。
    new_migrations = [p for s, p in migration_changes if s == "A"]
    for status, path in migration_changes:
        name = path.rsplit("/", 1)[-1]
        if status == "A":
            if not MIGRATION_RE.match(name):
                blockers.append(
                    f"新增迁移文件名非法 {path} —— 必须为 V{{n}}__desc.sql（MigrationRunner 按文件名排序执行）"
                )
        elif status == "R100":
            if not MIGRATION_RE.match(name):
                blockers.append(
                    f"迁移改名后文件名非法 {path} —— 必须为 V{{n}}__desc.sql（MigrationRunner 按文件名排序执行）"
                )
            else:
                warnings.append(
                    f"迁移纯改名（让号）{path} —— R100 内容零变化（issue #3812 后合入者让号），"
                    f"新名首跑应为幂等空操作；请人工确认"
                )
        else:
            blockers.append(
                f"已发布迁移被修改/删除 {path} —— 迁移不可变（MigrationRunner 按序执行，"
                f"改动会导致线上 DB 与代码脱节），只能新增 V{{n+1}}__ 迁移"
            )

    # ---- DDL 与迁移同步（R2）：改表结构参考必须伴随迁移 ----
    # 豁免 A（comment_only）：schema 文件只改**注释/文档**（新增行里没有任何 DDL 语句）。
    #   背景（issue #3270 实证假 blocker）：给 schema_full.sql 加废弃标注（纯注释）也被判
    #   「改了表结构未加迁移」—— 规则本意是「结构变更需迁移」，注释不改变结构。
    #   判定前剥掉行尾 `--` 注释，避免注释里提到 CREATE TABLE 被误当成 DDL。
    # 豁免 B（bootstrap_alignment）：schema.sql 只**补齐**迁移链已创建的表（bootstrap 对齐），
    #   而非新增/修改表结构 —— 此时**不应**新建迁移（迁移链才是 schema 事实源，再建迁移是反向漂移）。
    #   判定：diff 里新增的 CREATE TABLE 表名全部能在现有迁移文件中找到定义。
    #   背景（issue #3270 三次踩坑）：schema.sql 与迁移链双源漂移，补表对齐是修复而非变更。
    _ddl_re = re.compile(
        r"\b(?:CREATE|ALTER|DROP|RENAME)\s+(?:TABLE|COLUMN|INDEX|CONSTRAINT|VIEW|SEQUENCE|TYPE)\b",
        re.I,
    )
    comment_only = False
    bootstrap_alignment = False
    if schema_changes and not new_migrations:
        added_tables = set()
        added_ddl_lines = []
        # fail-closed：diff 拿不到（BASE 错/非 git 仓库/无变更）时**不得**据此判定
        # "只是注释" —— 否则门禁会被静默绕过（安全门禁的失效方向必须是"报错"而非"放行"）。
        diff_ok = True
        added_line_seen = False
        for f in schema_changes:
            diff = ""
            try:
                proc = subprocess.run(
                    ["git", "diff", BASE, "--", f],
                    capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    diff = proc.stdout
                else:
                    diff_ok = False
            except Exception:
                diff_ok = False
            for line in diff.splitlines():
                if not line.startswith("+") or line.startswith("+++"):
                    continue  # 只看新增行（`+++` 是文件头）
                added_line_seen = True
                body = re.sub(r"--.*$", "", line[1:])  # 剥行尾注释再判定
                if _ddl_re.search(body):
                    added_ddl_lines.append(body.strip())
                m = re.match(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)",
                    body.strip(), re.I)
                if m:
                    added_tables.add(m.group(1).lower())
        # 只有「diff 读取成功 + 确实看到新增行 + 无任何 DDL」才认定纯注释改动
        comment_only = diff_ok and added_line_seen and not added_ddl_lines
        if added_tables:
            try:
                mig_files = subprocess.run(
                    ["git", "ls-files", MIGRATION_DIR], capture_output=True, text=True,
                    check=False).stdout
            except Exception:
                mig_files = ""
            all_migration_sql = ""
            for mf in mig_files.split():
                try:
                    all_migration_sql += pathlib.Path(mf).read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
            known = {m.group(1).lower() for m in re.finditer(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)",
                all_migration_sql, re.I)}
            if added_tables and added_tables <= known:
                bootstrap_alignment = True

    if schema_changes and not new_migrations and not bootstrap_alignment and not comment_only:
        blockers.append(
            f"修改了表结构参考 {SCHEMA_FILES[0]}/{SCHEMA_FILES[1]} 但未新增迁移文件 —— "
            f"请新增 {MIGRATION_DIR}/V{{n}}__xxx.sql 并保证幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS）"
        )
    elif comment_only:
        warnings.append(
            "schema 文件仅改动注释/文档（新增行无 DDL）—— 非结构变更，无需迁移"
        )
    elif bootstrap_alignment:
        warnings.append(
            f"schema.sql 仅补齐迁移链已存在的表（bootstrap 对齐，非结构变更）—— 无需新迁移"
        )

    if len(deleted_files) >= BULK_DELETE_THRESHOLD:
        warnings.append(f"本次删除 {len(deleted_files)} 个文件（>= {BULK_DELETE_THRESHOLD}）—— 请确认是有意清理")

    if deploy_files:
        warnings.append(f"修改生产部署文件 {len(deploy_files)} 个：{deploy_files[0]} 等 —— 部署链路变更需谨慎")

    return blockers, warnings


def _git_name_status(scope):
    """返回 `git diff --name-status <BASE>...HEAD -- <scope>` 的 [(status, path)]。

    **fail-closed（本次收紧）**：取证失败返回 **None**，与「本次确实无变更」（返回 `[]`）
    严格区分。旧实现（无 returncode 判定 + 裸 `except` → `[]`）把两者收敛成同一件事，
    于是 BASE 配错 / 无共同祖先 / 非 git 仓库 / 超时都会让 **整个安全门禁**退化成
    「0 变更、0 blocker、✅ PASSED」—— 而本文件 docstring 自己声称 fail-closed，
    schema 分支也已按同一原则改过（见 `_ddl` 段的注释与 `test_git_diff_failure_fails_closed`）。
    失效方向对安全门禁只能是「报错」，不能是「放行」。
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-status", f"{BASE}...HEAD", "--", scope],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        print(f"::error:: danger_scan 取证失败（{BASE}...HEAD -- {scope}）: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        detail = (out.stderr or "").strip().splitlines()
        print(f"::error:: danger_scan 取证失败（{BASE}...HEAD -- {scope}，退出码 {out.returncode}）: "
              f"{detail[0] if detail else '（git 未输出 stderr）'}", file=sys.stderr)
        return None
    result = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            # 完整 status（rename 是 R100/R062 等含相似度，A/M/D 为单字符）
            # 调用方按 status[0] 取大类、按 status == "R100" 判纯改名（issue #3812）
            result.append((parts[0], parts[-1]))
    return result


def _workflow_changes():
    """workflow 目录内的变更 [(status, path)]；取证失败 → None（fail-closed）。"""
    changes = _git_name_status(WORKFLOW_DIR)
    if changes is None:
        return None
    return [(s, p) for s, p in changes if p.endswith(WORKFLOW_SUFFIXES)]


def _workflow_new_secrets(paths):
    """对修改的 workflow 提取新增的 secrets 引用行（移动/重排不算新增，issue #2949）。

    取证失败 → **None**（fail-closed）：拿不到某条 workflow 的 diff 时，「没看到新 secrets」
    与「无法判断有没有新 secrets」是两件事 —— 后者若当成前者，等于给安全审查开一条
    「让 git diff 失败即可放行」的路（与 `_git_name_status` 同族，见其 docstring）。
    """
    secrets_by_path = {}
    for status, path in paths:
        if status[0] in ("M", "R"):
            try:
                out = subprocess.run(
                    ["git", "diff", f"{BASE}...HEAD", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception as e:
                print(f"::error:: danger_scan 无法读取 {path} 的 secrets diff: {e}", file=sys.stderr)
                return None
            if out.returncode != 0:
                print(f"::error:: danger_scan 无法读取 {path} 的 secrets diff（退出码 "
                      f"{out.returncode}）", file=sys.stderr)
                return None
            lines = out.stdout.splitlines()
            added = [l for l in lines if l.startswith("+") and "secrets." in l]
            removed = [l for l in lines if l.startswith("-") and "secrets." in l]
            truly_new = _truly_new_secret_lines(added, removed)
            if truly_new:
                secrets_by_path[path] = truly_new
    return secrets_by_path


def main():
    # 取证先行（fail-closed）：三条扫描线任一拿不到变更清单 ⇒ 不判定、直接 blocker。
    # 绝不允许「取证失败」被读成「没有破坏性变更」——那正是安全门禁的假绿形态。
    blockers = []
    all_changes = _git_name_status(".")
    if all_changes is None:
        blockers.append(
            f"无法获取变更清单（git diff {BASE}...HEAD）—— 安全门禁取证失败，"
            f"不得按「无变更」放行。请确认 {BASE} 存在且与 HEAD 有共同祖先"
            f"（CI: `git fetch origin main`；本地: DANGER_BASE 指向真实 ref）"
        )
        all_changes = []
    workflow_paths = _workflow_changes()
    if workflow_paths is None:
        blockers.append(
            f"无法获取 workflow 变更清单（{WORKFLOW_DIR}）—— 安全门禁取证失败，同上"
        )
        workflow_paths = []
    wf_new_secrets = _workflow_new_secrets(workflow_paths)
    if wf_new_secrets is None:
        blockers.append(
            "无法读取 workflow 的 secrets diff —— 安全门禁取证失败，不得按「无新增 secrets」放行"
        )
        wf_new_secrets = {}

    deleted_files = [p for s, p in all_changes if s == "D"]
    deploy_files = [p for s, p in all_changes if s[0] in ("M", "A", "R") and
                    (p.startswith("deploy/") or "/deploy/" in p)]
    migration_changes = _git_name_status(MIGRATION_DIR + "/*.sql")
    if migration_changes is None:
        blockers.append(
            "无法获取迁移文件变更清单 —— 安全门禁取证失败（「迁移只增不改」判定未执行，"
            "不得按「无迁移变更」放行）"
        )
        migration_changes = []
    schema_changes = [p for s, p in all_changes if p in SCHEMA_FILES]

    trusted = os.environ.get("DANGER_TRUSTED_ACTOR", "").lower() in ("1", "true", "yes")
    a_blockers, warnings = analyze(
        workflow_paths, wf_new_secrets, deleted_files, deploy_files,
        migration_changes, schema_changes, trusted_actor=trusted,
    )
    blockers = blockers + a_blockers

    result = {
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
    }
    with open("danger-scan-result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    for b in blockers:
        print(f"❌ {b}")
    for w in warnings:
        print(f"⚠️ {w}")
    if blockers:
        print(f"🔒 danger-scan: {len(blockers)} 处 blocker，阻塞合并")
        sys.exit(1)
    print(f"✅ danger-scan: {len(blockers)} blocker / {len(warnings)} warning")
    sys.exit(0)


if __name__ == "__main__":
    main()
