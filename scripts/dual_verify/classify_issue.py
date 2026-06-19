#!/usr/bin/env python3
"""
Issue 复杂度分级 — verify-agent 验收前的"分级门"

二郎神 v3.1 新增：按 issue 复杂度触发不同深度的验收，避免修小 bug 跑 4 层太重。

## 规则（纯规则判定，0 LLM 调用）

**small_bug**（小 bug）: 1 个 service + < 50 行 → L1 + L4
**medium_bug**（中 bug）: 1 个 service 多文件 / 改 template → L1 + L2 + L4
**strong_feature**（强 feature）: 跨 service / 改 frontend / 改 verification template → 全 4 层 + 跨层

## 判定信号
- affected_modules 数量 > 1 → 至少 medium_bug
- 改了 frontend/admin-web/src/pages/** → strong_feature
- 改了 docs/verification-templates/** → strong_feature
- 改了 backend/admin-api/** AND backend/ai-agent-service/** → strong_feature
- 文件改动数 ≤ 2 且单 service → small_bug
- 其他 → medium_bug

## 输出
JSON: {"complexity": "small_bug|medium_bug|strong_feature", "layers": ["L1","L4"], "reason": "..."}
"""
import argparse
import json
import re
import subprocess
import sys
import calendar
import time


def parse_iso8601(s):
    """Python 3.6 兼容的 ISO 8601 解析（datetime.fromisoformat 仅 3.7+ 支持）"""
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except AttributeError:
        # Python 3.6 fallback: 手动解析
        s = s.replace("Z", "+00:00")
        if "+" in s[10:]:
            dt_part, tz_part = s.rsplit("+", 1)
            sign = 1
        elif s.count("-") > 2:
            dt_part, tz_part = s.rsplit("-", 1)
            sign = -1
        else:
            dt_part, tz_part = s, "00:00"
            sign = 1
        dt = time.strptime(dt_part, "%Y-%m-%dT%H:%M:%S")
        ts = calendar.timegm(dt)
        if ":" in tz_part:
            h, m = tz_part.split(":")
            ts -= sign * (int(h) * 3600 + int(m) * 60)
        return ts


def gh(*args):
    p = subprocess.Popen(["gh"] + list(args), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    if p.returncode != 0:
        return None
    return out


def get_affected_modules(issue_body):
    """从 issue body 的 CONTRACT_JSON 提取 affected_modules"""
    if not issue_body:
        return []
    m = re.search(r'"affected_modules"\s*:\s*\[([^\]]*)\]', issue_body)
    if not m:
        return []
    raw = m.group(1)
    return [x.strip().strip('"').strip("'") for x in raw.split(",") if x.strip()]


def get_pr_files(pr_number):
    """拿 PR 改的文件清单"""
    out = gh("pr", "view", str(pr_number), "--json", "files", "--jq", ".files[].path")
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def find_all_merged_prs(issue_id):
    """找 issue 关联的所有 merged PR"""
    out = gh("pr", "list", "--search", f"{issue_id} in:body",
             "--state", "merged", "--json", "number,mergedAt", "--jq",
             '.[] | "\\(.number) \\(.mergedAt)"')
    if not out:
        return []
    import time
    cutoff = time.time() - 7 * 24 * 3600  # 7 天内
    prs = []
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            num = int(parts[0])
            merged_at = parts[1]
            # ISO 8601 → epoch
            from datetime import datetime
            ts = parse_iso8601(merged_at)
            if ts >= cutoff:
                prs.append(num)
        except (ValueError, TypeError):
            continue
    return prs


def get_pr_files_batch(pr_numbers):
    """拿多个 PR 的全部文件清单（去重）"""
    files = set()
    for n in pr_numbers:
        out = gh("pr", "view", str(n), "--json", "files", "--jq", ".files[].path")
        if out:
            for line in out.splitlines():
                if line.strip():
                    files.add(line.strip())
    return sorted(files)


def classify(issue_id):
    """主入口：返回分级结果"""
    # 1. 拿 issue body
    out = gh("issue", "view", str(issue_id), "--json", "body", "--jq", ".body")
    if not out:
        return {"complexity": "medium_bug", "layers": ["L1", "L2", "L4"],
                "reason": "拿不到 issue body，默认 medium_bug"}

    body = out
    modules = get_affected_modules(body)

    # 2. 拿所有关联 PR 的文件清单（综合判定）
    pr_nums = find_all_merged_prs(issue_id)
    files = get_pr_files_batch(pr_nums)

    # 3. 判定逻辑（按升级顺序，强 feature 优先）
    reasons = []

    # === strong_feature 信号 ===
    if any("frontend/admin-web/src/pages/" in f for f in files):
        reasons.append(f"改 frontend pages → strong_feature")
    if any("docs/verification-templates/" in f for f in files):
        reasons.append(f"改 verification template → strong_feature")
    services = set()
    for f in files:
        if "backend/admin-api/" in f:
            services.add("admin-api")
        if "backend/ai-agent-service/" in f:
            services.add("ai-agent-service")
    if len(services) > 1:
        reasons.append(f"跨服务 {sorted(services)} → strong_feature")

    if reasons:
        return {
            "complexity": "strong_feature",
            "layers": ["L1", "L2", "L3", "L4", "cross_layer"],
            "reason": "; ".join(reasons),
            "modules": modules,
            "pr": pr_nums,
            "file_count": len(files),
        }

    # === medium_bug 信号 ===
    if len(modules) > 1:
        reasons.append(f"affected_modules={len(modules)} → medium_bug")
    if len(files) > 2:
        reasons.append(f"files={len(files)} > 2 → medium_bug")

    if reasons:
        return {
            "complexity": "medium_bug",
            "layers": ["L1", "L2", "L4"],
            "reason": "; ".join(reasons),
            "modules": modules,
            "pr": pr_nums,
            "file_count": len(files),
        }

    # === small_bug（默认）===
    return {
        "complexity": "small_bug",
        "layers": ["L1", "L4"],
        "reason": f"files={len(files)} ≤ 2 且单 service → small_bug",
        "modules": modules,
        "pr": pr_nums,
        "file_count": len(files),
    }


def main():
    ap = argparse.ArgumentParser(description="Issue 复杂度分级（verify-agent 验收前）")
    ap.add_argument("issue_id", type=int, help="issue 编号")
    args = ap.parse_args()

    result = classify(args.issue_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()