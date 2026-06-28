#!/usr/bin/env python3
"""
军师覆盖率周扫 — coverage_weekly.py

每周一 10:30 跑一次：
1. 扫 3 个模块的覆盖率：admin-api (JaCoCo) / admin-web (vitest) / ai-agent-service (coverage)
2. 60% 阈值卡
3. 输出报告 + （--create-issues）自动建 issue 走二郎神 loop

用法：
    python3 junshi/coverage_weekly.py --scan                 # 扫 + 报告
    python3 junshi/coverage_weekly.py --scan --create-issues # 扫 + 报告 + 建 issue
    python3 junshi/coverage_weekly.py --scan --dry-run       # 扫 + 报告（不写文件不发钉钉）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path("/opt/migao")
THRESHOLD = 60  # 行覆盖率阈值
REPORT_DIR = Path("/opt/qa-results/_archive/qa-growth")

MODULES = {
    "admin-api": {
        "type": "jacoco",
        "path": REPO_ROOT / "backend" / "admin-api" / "target" / "site" / "jacoco" / "jacoco.xml",
        "cmd_test": "cd backend/admin-api && ./mvnw test jacoco:report -q",
    },
    "admin-web": {
        "type": "vitest",
        "path": REPO_ROOT / "frontend" / "admin-web" / "coverage" / "coverage-summary.json",
        "cmd_test": "cd frontend/admin-web && npm run test:coverage -- --silent",
    },
    "ai-agent-service": {
        "type": "coverage",
        "path": REPO_ROOT / "backend" / "ai-agent-service" / ".coverage",
        "report_cmd": "cd backend/ai-agent-service && .venv/bin/coverage json -o coverage.json",
        "report_path": REPO_ROOT / "backend" / "ai-agent-service" / "coverage.json",
        "cmd_test": "cd backend/ai-agent-service && .venv/bin/pytest tests/ --cov=app --cov-report=json:coverage.json -q",
    },
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_jacoco_analysis(xml_path: Path) -> dict:
    """解析 JaCoCo XML 报告。返回 {package: {lines_covered, lines_missed, line_pct, file: [...]}}"""
    if not xml_path.exists():
        return {"error": f"JaCoCo 报告不存在: {xml_path}"}

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 聚合（root 元素不一定有 LINE_*, 从所有 package/counter 求和）
    def sum_counters(elem, counter_type):
        total_missed = 0
        total_covered = 0
        for counter in elem.findall("counter"):
            if counter.get("type") == counter_type:
                total_missed += int(counter.get("missed", 0))
                total_covered += int(counter.get("covered", 0))
        return total_missed, total_covered

    total_missed, total_covered = sum_counters(root, "LINE")
    total_lines = total_missed + total_covered
    line_pct = round(total_covered / total_lines * 100, 2) if total_lines else 0.0

    packages = {}
    files_below_threshold = []

    for pkg in root.findall("package"):
        pkg_name = pkg.get("name", "").replace("/", ".")
        pkg_missed, pkg_covered = sum_counters(pkg, "LINE")
        pkg_total = pkg_missed + pkg_covered
        pkg_pct = round(pkg_covered / pkg_total * 100, 2) if pkg_total else 0.0
        packages[pkg_name] = {
            "line_pct": pkg_pct,
            "lines_covered": pkg_covered,
            "lines_missed": pkg_missed,
        }

        # 收集 < 阈值的文件（用 sourcefile 聚合；package 拼到 file 路径里，便于按 controller/service 拆）
        pkg_path = pkg.get("name", "")  # e.g. com/migao/admin/controller
        for src in pkg.findall("sourcefile"):
            file_name = src.get("name", "")
            # 拼成全路径：com/migao/admin/controller/DashboardController.java
            full_path = f"{pkg_path}/{file_name}" if pkg_path else file_name
            f_missed, f_covered = sum_counters(src, "LINE")
            f_total = f_missed + f_covered
            f_pct = round(f_covered / f_total * 100, 2) if f_total else 0.0
            if f_pct < THRESHOLD and f_total > 0:
                files_below_threshold.append({
                    "package": pkg_name,
                    "file": full_path,  # 用全路径喂给 group_files_by_feature
                    "file_name": file_name,  # 保留原文件名
                    "line_pct": f_pct,
                    "lines_missed": f_missed,
                    "lines_covered": f_covered,
                    "lines_total": f_total,
                })

    files_below_threshold.sort(key=lambda x: (x["line_pct"], -x["lines_missed"]))

    return {
        "type": "jacoco",
        "line_pct": line_pct,
        "lines_covered": total_covered,
        "lines_missed": total_missed,
        "lines_total": total_lines,
        "package_count": len(packages),
        "packages_below_threshold": [p for p in packages.items() if p[1]["line_pct"] < THRESHOLD],
        "files_below_threshold": files_below_threshold[:50],  # top 50
    }


def run_vitest_analysis(json_path: Path) -> dict:
    """解析 vitest coverage-summary.json。"""
    if not json_path.exists():
        return {"error": f"vitest 报告不存在: {json_path}"}

    data = json.loads(json_path.read_text(encoding="utf-8"))
    total = data.get("total", {})
    lines = total.get("lines", {})

    line_pct = round(lines.get("pct", 0), 2)
    lines_covered = lines.get("covered", 0)
    lines_total = lines.get("total", 0)
    lines_missed = lines_total - lines_covered

    files_below = []
    for path, metrics in data.items():
        if path == "total":
            continue
        l = metrics.get("lines", {})
        if l.get("total", 0) == 0:
            continue
        pct = round(l.get("pct", 0), 2)
        if pct < THRESHOLD:
            files_below.append({
                "file": path,
                "line_pct": pct,
                "lines_missed": l["total"] - l["covered"],
                "lines_covered": l["covered"],
                "lines_total": l["total"],
            })

    files_below.sort(key=lambda x: (x["line_pct"], -x["lines_missed"]))

    return {
        "type": "vitest",
        "line_pct": line_pct,
        "lines_covered": lines_covered,
        "lines_missed": lines_missed,
        "lines_total": lines_total,
        "files_below_threshold": files_below[:50],
    }


def run_coverage_analysis(json_path: Path) -> dict:
    """解析 Python coverage.json。"""
    if not json_path.exists():
        return {"error": f"coverage.json 不存在: {json_path}"}

    data = json.loads(json_path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    line_pct = round(totals.get("percent_covered", 0), 2)
    lines_covered = totals.get("covered_lines", 0)
    lines_total = lines_covered + totals.get("missing_lines", 0)
    lines_missed = totals.get("missing_lines", 0)

    files_below = []
    for path, info in data.get("files", {}).items():
        missing = len(info.get("missing_lines", []))
        covered = len(info.get("covered_lines", []))
        total = missing + covered
        if total == 0:
            continue
        pct = round(covered / total * 100, 2)
        if pct < THRESHOLD:
            # path 是相对路径，转绝对
            rel_path = path
            if path.startswith(str(REPO_ROOT)):
                rel_path = str(Path(path).relative_to(REPO_ROOT / "backend" / "ai-agent-service"))
            files_below.append({
                "file": rel_path,
                "line_pct": pct,
                "lines_missed": missing,
                "lines_covered": covered,
                "lines_total": total,
            })

    files_below.sort(key=lambda x: (x["line_pct"], -x["lines_missed"]))

    return {
        "type": "coverage",
        "line_pct": line_pct,
        "lines_covered": lines_covered,
        "lines_missed": lines_missed,
        "lines_total": lines_total,
        "files_below_threshold": files_below[:50],
    }


def run_module_scan(name: str, mod: dict, run_tests: bool = False) -> dict:
    """扫一个模块。"""
    log(f"[{name}] 开始扫描 (type={mod['type']})")
    result = {
        "module": name,
        "type": mod["type"],
        "scanned_at": datetime.now().isoformat(),
    }

    if run_tests and mod.get("cmd_test"):
        log(f"[{name}] 跑测试生成报告: {mod['cmd_test']}")
        try:
            proc = subprocess.run(
                mod["cmd_test"],
                shell=True,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=600,
            )
            result["test_exit_code"] = proc.returncode
            if proc.returncode != 0:
                result["test_error"] = (proc.stderr or "")[-500:]
        except subprocess.TimeoutExpired:
            result["test_error"] = "测试超时（600s）"

    # ai-agent 先转 json
    if mod["type"] == "coverage" and mod.get("report_cmd"):
        report_json = mod.get("report_path")
        if report_json and not report_json.exists():
            log(f"[{name}] 生成 coverage.json")
            try:
                subprocess.run(mod["report_cmd"], shell=True, cwd=REPO_ROOT, timeout=60)
            except Exception as e:
                result["test_error"] = f"coverage json 转换失败: {e}"

    # 解析报告
    if mod["type"] == "jacoco":
        result.update(run_jacoco_analysis(mod["path"]))
    elif mod["type"] == "vitest":
        result.update(run_vitest_analysis(mod["path"]))
    elif mod["type"] == "coverage":
        result.update(run_coverage_analysis(mod.get("report_path") or mod["path"]))

    if "error" in result:
        log(f"[{name}] ❌ {result['error']}")
    else:
        log(f"[{name}] ✅ line_pct={result.get('line_pct')}% | "
            f"files_below_threshold={len(result.get('files_below_threshold', []))}")

    return result


def build_summary(scan_results: list) -> dict:
    """汇总扫描结果。"""
    summary = {
        "scan_at": datetime.now().isoformat(),
        "threshold": THRESHOLD,
        "modules": {},
        "total_files_below": 0,
        "modules_below": [],
        "modules_above": [],
    }
    for r in scan_results:
        name = r["module"]
        if "error" in r:
            summary["modules"][name] = {"status": "error", "error": r["error"]}
            continue
        line_pct = r.get("line_pct", 0)
        below_count = len(r.get("files_below_threshold", []))
        summary["modules"][name] = {
            "status": "ok",
            "line_pct": line_pct,
            "files_below": below_count,
            "lines_total": r.get("lines_total", 0),
            "lines_covered": r.get("lines_covered", 0),
        }
        summary["total_files_below"] += below_count
        if line_pct < THRESHOLD:
            summary["modules_below"].append(name)
        else:
            summary["modules_above"].append(name)
    return summary


def group_files_by_feature(files: list, module: str) -> dict:
    """按功能拆分组。

    拆法（按文件路径前缀 / 命名约定）：
    - admin-api (Java)：按 controller / service / security / config / dto / util 分组
    - admin-web (TS/TSX)：按 app / components / lib / store / hooks 分组
    - ai-agent-service (Python)：按 agents / tools / utils / services / api 分组

    同一分组的文件数 > MAX_FILES_PER_ISSUE 就再按字母拆，确保每个 issue 不超过上限。
    单文件小分组过多时（如 ai-agent 13 个 tool 各 1 文件），按父目录合并到「混合」组，避免 1 个 issue 1 个文件。
    """
    MAX_FILES_PER_ISSUE = 8  # 单 issue 装得下，研发 review 不会头大
    MAX_SINGLE_FILE_GROUPS = 4  # 单文件小分组超过这个数 → 合并到混合组

    # 1. 按 feature 关键词分组
    def get_feature(file_path: str) -> str:
        p = file_path.lower()
        # admin-api
        if "controller/" in p:
            cls = p.split("controller/")[-1].split(".")[0].lower()
            for kw in ["order", "customer", "user", "product", "auth", "sms",
                       "knowledge", "menu", "dashboard", "tag", "upload",
                       "notification", "agent", "quickreply", "processing", "registration"]:
                if kw in cls:
                    return f"controller-{kw}"
            return "controller-other"
        if "service/" in p:
            cls = p.split("service/")[-1].split(".")[0].lower()
            for kw in ["order", "customer", "user", "product", "auth",
                       "knowledge", "notification", "agent", "quickreply",
                       "processing", "menu", "tag", "registration", "dashboard"]:
                if kw in cls:
                    return f"service-{kw}"
            return "service-other"
        if "security/" in p:
            return "security"
        if "config/" in p:
            return "config"
        if "dto/" in p:
            return "dto"
        if "util" in p or "utils/" in p:
            return "utils"
        # admin-web
        if "/app/" in p:
            return "app-routes"
        if "/components/" in p:
            cls = p.split("/components/")[-1].split("/")[0].lower()
            return f"components-{cls}"
        if "/lib/" in p:
            cls = p.split("/lib/")[-1].split("/")[0].split(".")[0].lower()
            return f"lib-{cls}"
        if "/store/" in p:
            cls = p.split("/store/")[-1].split("/")[0].split(".")[0].lower()
            return f"store-{cls}"
        if "/hooks/" in p:
            return "hooks"
        if "/utils/" in p:
            return "utils"
        # ai-agent
        if "/agents/" in p:
            cls = p.split("/agents/")[-1].split("/")[0].split(".")[0].lower()
            return f"agents-{cls}"
        if "/tools/" in p:
            return "tools-mixed"  # ai-agent tools 父目录统一一个 group，按需细分
        if "/api/" in p:
            return "api"
        if "/services/" in p:
            return "services"
        return "misc"

    groups = {}
    for f in files:
        feat = get_feature(f.get("file", ""))
        groups.setdefault(feat, []).append(f)

    # 2. 合并单文件小分组（避免 13 个 1 文件 issue）
    single_file_groups = {k: v for k, v in groups.items() if len(v) == 1}
    multi_file_groups = {k: v for k, v in groups.items() if len(v) > 1}

    if len(single_file_groups) > MAX_SINGLE_FILE_GROUPS:
        # 按父目录再聚类
        parent_groups = {}
        for k, v in single_file_groups.items():
            # k 例 "tools-order_create" → parent "tools"
            parent = k.rsplit("-", 1)[0] if "-" in k else k
            parent_groups.setdefault(parent, []).extend(v)

        # 如果父分组还 > MAX_FILES_PER_ISSUE，再按字母拆
        final_groups = dict(multi_file_groups)
        for parent, fs in parent_groups.items():
            if len(fs) <= MAX_FILES_PER_ISSUE:
                final_groups[parent] = fs
            else:
                chunks = [fs[i:i + MAX_FILES_PER_ISSUE]
                          for i in range(0, len(fs), MAX_FILES_PER_ISSUE)]
                for i, chunk in enumerate(chunks):
                    final_groups[f"{parent}-part{i+1}"] = chunk
    else:
        final_groups = groups

    # 3. 超限再按字母拆（multi-file groups 阶段已处理，这里再保险一次）
    final_groups2 = {}
    for feat, fs in final_groups.items():
        if len(fs) <= MAX_FILES_PER_ISSUE:
            final_groups2[feat] = fs
        else:
            chunks = [fs[i:i + MAX_FILES_PER_ISSUE]
                      for i in range(0, len(fs), MAX_FILES_PER_ISSUE)]
            for i, chunk in enumerate(chunks):
                final_groups2[f"{feat}-part{i+1}"] = chunk

    return final_groups2


def build_issue_body(module: str, feature: str, files: list, module_summary: dict) -> str:
    """生成单个 feature issue body（CONTRACT_JSON 风格）。"""
    line_pct = module_summary.get("line_pct", 0)

    # 业务真值（不带技术词）
    truth_lines = [
        f"## 背景",
        f"- 模块：`{module}` | 功能分组：**{feature}**",
        f"- 当前模块行覆盖率：**{line_pct}%**（阈值 {THRESHOLD}%）",
        f"- 本 issue 涉及文件数：**{len(files)}**",
        f"- 涉及未覆盖行数：{sum(f.get('lines_missed', 0) for f in files)}",
        "",
        f"## 业务真值（待补全）",
        f"军师反推骨架：本分组每个文件补 1-2 个核心 case，覆盖：",
        f"1. 正常路径（happy path）",
        f"2. 异常路径（异常输入/边界值）",
        f"3. 关键业务规则（如订单状态流转、含加工订单判定）",
        "",
        f"## 涉及文件清单（{len(files)} 个）",
        "",
        "| 文件 | 当前覆盖率 | 未覆盖行 | 总行数 |",
        "|---|---|---|---|",
    ]
    for f in files:
        truth_lines.append(
            f"| `{f.get('package', '')}/{f.get('file', '')}` "
            f"| {f.get('line_pct', 0)}% "
            f"| {f.get('lines_missed', 0)} "
            f"| {f.get('lines_total', 0)} |"
        )

    truth_lines.extend([
        "",
        "## 验收标准",
        f"1. 本分组所有文件行覆盖率 ≥ {THRESHOLD}%",
        f"2. 关键业务文件（订单/含加工/客户/AI 工具）覆盖率 ≥ 80%",
        f"3. 新增 case 走二郎神体系（issue → case_draft → PR → 双验）",
        f"4. PR 合 main 后覆盖率 PR-CI 全绿",
        "",
        "## CONTRACT_JSON",
        "```json",
        json.dumps({
            "type": "coverage-gap",
            "module": module,
            "feature": feature,
            "current_coverage": line_pct,
            "threshold": THRESHOLD,
            "files_count": len(files),
            "verification_method": "qa-growth-gate + pr-check",
        }, ensure_ascii=False, indent=2),
        "```",
    ])

    return "\n".join(truth_lines)


def build_top_summary_issue(module: str, module_summary: dict, feature_count: int) -> str:
    """生成顶层 tracking issue（追踪所有子 issue，长期监督）。"""
    return "\n".join([
        f"## 背景",
        f"- 模块：`{module}` 当前行覆盖率 **{module_summary.get('line_pct', 0)}%**（阈值 {THRESHOLD}%）",
        f"- 拆分为 **{feature_count}** 个子 issue 按功能跟进",
        f"- **本顶层 issue 永远不主动 close**（凯总 2026-06-20 09:00 指示）",
        f"- 累计达 60% 后继续增长，新发现的低覆盖文件会建新子 issue",
        "",
        f"## 业务真值",
        f"凯总指示（2026-06-20 08:51）：大任务按功能拆 issue，不放一个 issue。",
        f"本顶层 issue 是**长期监督 tracking**，研发认领时认领对应子 issue。",
        f"覆盖率是'长期健康指标'，不是'完成就关'的任务。",
        "",
        f"## 涉及模块整体统计",
        f"- 总行数：{module_summary.get('lines_total', 0)}",
        f"- 已覆盖：{module_summary.get('lines_covered', 0)}",
        f"- 未覆盖：{module_summary.get('lines_missed', 0)}",
        f"- 低覆盖率文件数：{module_summary.get('files_below', 0)}",
        "",
        f"## 子 issue 列表",
        f"见本 issue 评论列表（每个 feature 一个子 issue，由军师自动建好后贴链接）",
        "",
        f"## CONTRACT_JSON",
        "```json",
        json.dumps({
            "type": "coverage-gap-tracking",
            "module": module,
            "current_coverage": module_summary.get("line_pct", 0),
            "threshold": THRESHOLD,
            "feature_count": feature_count,
            "verification_method": "qa-growth-gate + pr-check",
            "auto_close": False,  # 凯总 09:00 指示：永远不 auto close
            "policy": "long-term-monitoring",
        }, ensure_ascii=False, indent=2),
        "```",
    ])


def create_issues(scan_results: list, dry_run: bool = True) -> list:
    """对每个低于阈值的模块建 issue（按功能拆 + 顶层 tracking）。

    凯总 2026-06-20 09:00 指示：
    - 顶层 tracking issue 永远不主动 close（即使 ≥ 60% 也保留并继续观察）
    - 累计达 60% 后继续增长：模块新发现低覆盖文件就建新子 issue
    - 只有"模块完全无低覆盖文件"才真的不建（这是真正的"全达标"）
    """
    created = []
    for r in scan_results:
        if "error" in r:
            continue
        line_pct = r.get("line_pct", 0)
        files = r.get("files_below_threshold", [])

        # 凯总 09:00 改：永远建顶层 tracking（除非模块真的 100% 覆盖），
        # 旧的"达标跳过"逻辑去掉 —— 即使 ≥ 60% 也保留顶层继续观察
        if line_pct >= 100.0 and not files:
            log(f"[{r['module']}] 完全覆盖（{line_pct}%），跳过建 issue")
            continue

        groups = group_files_by_feature(files, r["module"])
        module_summary = {
            "line_pct": line_pct,
            "lines_total": r.get("lines_total", 0),
            "lines_covered": r.get("lines_covered", 0),
            "lines_missed": r.get("lines_missed", 0),
            "files_below": len(files),
        }

        # 1. 顶层 tracking issue（永远建，永不 close）
        # 凯总 09:15 改：coverage issue 不走二郎神，**不打 needs-verification label**
        if line_pct >= THRESHOLD:
            top_title = f"[coverage-tracking] {r['module']} 覆盖率 {line_pct}% ≥ {THRESHOLD}%（持续监督）"
        else:
            top_title = f"[coverage-tracking] {r['module']} 覆盖率 {line_pct}% < {THRESHOLD}%（{len(groups)} 个子 issue）"
        top_body = build_top_summary_issue(r["module"], module_summary, len(groups))
        top_labels = ["coverage-gap", "coverage-tracking", "qa-growth"]  # 09:15: 移除 needs-verification
        top_url = None

        if dry_run:
            log(f"[{r['module']}] [DRY-RUN] 顶层 issue: {top_title}")
            created.append({"dry_run": True, "kind": "tracking", "title": top_title, "body": top_body[:200] + "..."})
        else:
            top_url = _create_one_issue(top_title, top_body, top_labels)
            created.append({"url": top_url, "kind": "tracking", "title": top_title})

        # 2. 每个 feature 一个子 issue（即使顶层 ≥ 60%，有新文件就建）
        for feature, feature_files in groups.items():
            sub_title = f"[coverage] {r['module']}/{feature} 覆盖率补全（{len(feature_files)} 个文件）"
            sub_body = build_issue_body(r["module"], feature, feature_files, module_summary)
            sub_labels = ["qa-todo", "coverage-gap", "qa-growth"]  # 09:15: 移除 needs-verification

            if dry_run:
                log(f"[{r['module']}] [DRY-RUN] 子 issue: {sub_title}")
                created.append({"dry_run": True, "kind": "feature", "title": sub_title, "body": sub_body[:200] + "..."})
            else:
                sub_url = _create_one_issue(sub_title, sub_body, sub_labels)
                created.append({"url": sub_url, "kind": "feature", "title": sub_title})
                if top_url:
                    _add_sub_issue_comment(top_url, sub_url, feature, len(feature_files))

    return created


def _create_one_issue(title: str, body: str, labels: list) -> str:
    """实际通过 gh CLI 建一个 issue，返回 url。"""
    body_file = Path(f"/tmp/coverage_issue_{int(datetime.now().timestamp())}.md")
    body_file.write_text(body, encoding="utf-8")
    try:
        proc = subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", "zhaokai-mgzn/migao",
                "--title", title,
                "--body-file", str(body_file),
                "--label", ",".join(labels),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
        if proc.returncode == 0:
            issue_url = proc.stdout.strip()
            log(f"  ✅ {issue_url}")
            return issue_url
        else:
            log(f"  ❌ gh 失败: {proc.stderr}")
            return f"ERROR: {proc.stderr}"
    finally:
        if body_file.exists():
            body_file.unlink()


def _add_sub_issue_comment(top_url: str, sub_url: str, feature: str, file_count: int):
    """在顶层 tracking issue 评论里挂子 issue 链接。"""
    issue_num = top_url.rstrip("/").split("/")[-1]
    comment = f"- [{feature}]({sub_url}) — {file_count} 个文件"
    try:
        proc = subprocess.run(
            ["gh", "issue", "comment", issue_num, "--body", comment],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=30,
        )
        if proc.returncode != 0:
            log(f"  ⚠️ 评论挂载失败: {proc.stderr}")
    except Exception as e:
        log(f"  ⚠️ 评论异常: {e}")


def archive_report(summary: dict, scan_results: list, issues_created: list, dry_run: bool):
    """归档报告。"""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_dir = REPORT_DIR / f"{ts}_coverage-weekly"
    archive_dir.mkdir(parents=True, exist_ok=True)

    (archive_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (archive_dir / "scan_results.json").write_text(
        json.dumps(scan_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (archive_dir / "issues_created.json").write_text(
        json.dumps(issues_created, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Markdown 报告
    md = [f"# 覆盖率周扫报告 — {ts}\n"]
    md.append(f"- 阈值：{THRESHOLD}%")
    md.append(f"- 模式：{'DRY-RUN' if dry_run else 'FULL'}\n")
    md.append("## 模块总览\n")
    md.append("| 模块 | 状态 | 行覆盖率 | 低于阈值文件 |")
    md.append("|---|---|---|---|")
    for name, m in summary["modules"].items():
        if m["status"] == "error":
            md.append(f"| {name} | ❌ error | - | - |")
        else:
            md.append(f"| {name} | ✅ | {m['line_pct']}% | {m['files_below']} |")
    md.append(f"\n**低于阈值模块**：{', '.join(summary['modules_below']) or '无'}")
    md.append(f"\n**总低于阈值文件**：{summary['total_files_below']}")

    (archive_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    log(f"📦 报告归档: {archive_dir}")
    return archive_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true", required=True)
    parser.add_argument("--run-tests", action="store_true", help="先跑测试生成报告")
    parser.add_argument("--create-issues", action="store_true", help="建 issue")
    parser.add_argument("--dry-run", action="store_true", help="不实际建 issue，不归档")
    args = parser.parse_args()

    log(f"🚀 覆盖率周扫开始（threshold={THRESHOLD}%, "
        f"create_issues={args.create_issues}, dry_run={args.dry_run}）")

    scan_results = []
    for name, mod in MODULES.items():
        scan_results.append(run_module_scan(name, mod, run_tests=args.run_tests))

    summary = build_summary(scan_results)
    log(f"\n📊 汇总: {summary}")

    issues_created = []
    if args.create_issues:
        issues_created = create_issues(scan_results, dry_run=args.dry_run)

    if not args.dry_run:
        archive_report(summary, scan_results, issues_created, dry_run=False)
    else:
        log("DRY-RUN 模式：跳过归档")

    # 打印 JSON 摘要给 cron 收
    print("\n===JSON_RESULT_BEGIN===")
    print(json.dumps({
        "summary": summary,
        "issues_created": issues_created,
        "dry_run": args.dry_run,
    }, ensure_ascii=False))
    print("===JSON_RESULT_END===")


if __name__ == "__main__":
    main()
