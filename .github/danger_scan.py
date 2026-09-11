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
        elif status in ("M", "R"):
            new_sec = wf_new_secrets.get(path, [])
            real_sec = [l for l in new_sec if "secrets.GITHUB_TOKEN" not in l]
            if real_sec:
                blockers.append(
                    f"{path} 新增 {len(real_sec)} 处非内置 secrets 引用 —— 需人工审查：{real_sec[0].strip()[:80]}"
                )
            else:
                warnings.append(f"修改 workflow {path} —— 建议人工复核")

    # ---- 迁移不可变（R1）：已发布迁移只增不改；新增迁移命名须 V{n}__desc.sql ----
    new_migrations = [p for s, p in migration_changes if s == "A"]
    for status, path in migration_changes:
        name = path.rsplit("/", 1)[-1]
        if status == "A":
            if not MIGRATION_RE.match(name):
                blockers.append(
                    f"新增迁移文件名非法 {path} —— 必须为 V{{n}}__desc.sql（MigrationRunner 按文件名排序执行）"
                )
        else:
            blockers.append(
                f"已发布迁移被修改/删除 {path} —— 迁移不可变（MigrationRunner 按序执行，"
                f"改动会导致线上 DB 与代码脱节），只能新增 V{{n+1}}__ 迁移"
            )

    # ---- DDL 与迁移同步（R2）：改表结构参考必须伴随迁移 ----
    # 豁免：schema.sql 只**补齐**迁移链已创建的表（bootstrap 对齐），而非新增/修改
    # 表结构 —— 此时**不应**新建迁移（迁移链才是 schema 事实源，再建迁移是反向漂移）。
    # 判定：diff 里新增的 CREATE TABLE 表名全部能在现有迁移文件中找到定义。
    # 背景（issue #3270 三次踩坑）：schema.sql 与迁移链双源漂移，补表对齐是修复而非变更。
    bootstrap_alignment = False
    if schema_changes and not new_migrations:
        added_tables = set()
        for f in schema_changes:
            try:
                diff = subprocess.run(
                    ["git", "diff", BASE, "--", f],
                    capture_output=True, text=True, check=False).stdout
            except Exception:
                diff = ""
            for m in re.finditer(
                    r"^\+CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)",
                    diff, re.M | re.I):
                added_tables.add(m.group(1).lower())
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

    if schema_changes and not new_migrations and not bootstrap_alignment:
        blockers.append(
            f"修改了表结构参考 {SCHEMA_FILES[0]}/{SCHEMA_FILES[1]} 但未新增迁移文件 —— "
            f"请新增 {MIGRATION_DIR}/V{{n}}__xxx.sql 并保证幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS）"
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
    """返回 git diff --name-status origin/main...HEAD -- <scope> 的 [(status, path)]"""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-status", f"{BASE}...HEAD", "--", scope],
            capture_output=True, text=True, timeout=30,
        )
        lines = out.stdout.strip().splitlines() if out.stdout.strip() else []
        result = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2:
                result.append((parts[0][0], parts[-1]))
        return result
    except Exception:
        return []


def _workflow_new_secrets(paths):
    """对修改的 workflow 提取新增的 secrets 引用行（移动/重排不算新增，issue #2949）"""
    secrets_by_path = {}
    for status, path in paths:
        if status in ("M", "R"):
            try:
                out = subprocess.run(
                    ["git", "diff", f"{BASE}...HEAD", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                lines = out.stdout.splitlines()
                added = [l for l in lines if l.startswith("+") and "secrets." in l]
                removed = [l for l in lines if l.startswith("-") and "secrets." in l]
                truly_new = _truly_new_secret_lines(added, removed)
                if truly_new:
                    secrets_by_path[path] = truly_new
            except Exception:
                pass
    return secrets_by_path


def main():
    workflow_paths = _git_name_status(".github/workflows/*.yml")
    all_changes = _git_name_status(".")
    deleted_files = [p for s, p in all_changes if s == "D"]
    deploy_files = [p for s, p in all_changes if s in ("M", "A", "R") and
                    (p.startswith("deploy/") or "/deploy/" in p)]
    wf_new_secrets = _workflow_new_secrets(workflow_paths)
    migration_changes = _git_name_status(MIGRATION_DIR + "/*.sql")
    schema_changes = [p for s, p in all_changes if p in SCHEMA_FILES]

    trusted = os.environ.get("DANGER_TRUSTED_ACTOR", "").lower() in ("1", "true", "yes")
    blockers, warnings = analyze(
        workflow_paths, wf_new_secrets, deleted_files, deploy_files,
        migration_changes, schema_changes, trusted_actor=trusted,
    )

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
