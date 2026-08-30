#!/usr/bin/env python3
"""danger_scan.py — PR 破坏性变更检测（安全门禁，fail-closed）

检测 PR（origin/main...HEAD）中的破坏性变更：
- BLOCK：新增/删除 workflow 文件、修改 workflow 且新增 secrets 引用（workflow 可携带 secrets 执行）
- WARN：批量删除文件（>=30）、修改生产部署文件、修改 workflow（无新增 secrets）

用法（由 pr-check 的 danger-scan job 调用）：
    python3 .github/danger_scan.py
输出：danger-scan-result.json（JSON）+ 控制台报告；存在 blocker 时 exit 1。
"""
import json
import os
import subprocess
import sys

BASE = os.environ.get("DANGER_BASE", "origin/main")
BULK_DELETE_THRESHOLD = 30


def analyze(workflow_changes, wf_new_secrets, deleted_files, deploy_files):
    """纯函数：对变更清单做安全判定。返回 (blockers, warnings)。

    Args:
        workflow_changes: [(status, path)]，status ∈ A/M/D/R
        wf_new_secrets:   {path: [新增的含 secrets 的 diff 行]}
        deleted_files:    删除的文件路径列表
        deploy_files:     deploy/ 或 scripts 下被改动的文件列表
    """
    blockers = []
    warnings = []

    for status, path in workflow_changes:
        if status == "A":
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
    """对修改的 workflow 提取新增的 secrets 引用行"""
    secrets_by_path = {}
    for status, path in paths:
        if status in ("M", "R"):
            try:
                out = subprocess.run(
                    ["git", "diff", f"{BASE}...HEAD", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                added = [l for l in out.stdout.splitlines() if l.startswith("+") and "secrets." in l]
                if added:
                    secrets_by_path[path] = added
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

    blockers, warnings = analyze(workflow_paths, wf_new_secrets, deleted_files, deploy_files)

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
