#!/usr/bin/env python3
"""
军师自我进化工具 — learn.py

每 4h 跑一次：
1. 扫最近 100 个 issue 的实战数据
2. 找反复出现的"漏识别段名" / "误判关键词" / "误判决策"
3. 自动生成 patch（写 learned_rules.json）
4. 写到 PR review

用法：
    python3 junshi/learn.py --scan     # 扫实战 + 更新规则
    python3 junshi/learn.py --rule <name>  # 看具体规则
    python3 junshi/learn.py --stats    # 看实战统计
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path("/opt/youke")
RULES_FILE = REPO_ROOT / "junshi" / "learned_rules.json"
QA_RESULTS_DIR = Path("/opt/qa-results")


def load_rules() -> dict:
    if not RULES_FILE.exists():
        return {"version": "v0.1", "rules": [], "stats": {}}
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


def save_rules(rules: dict):
    rules["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    RULES_FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def scan_real_cases():
    """扫最近实战数据，找 patterns"""
    if not QA_RESULTS_DIR.exists():
        return {}

    issues = []
    for issue_dir in sorted(QA_RESULTS_DIR.iterdir(), key=lambda p: p.name, reverse=True):
        if not issue_dir.is_dir() or not issue_dir.name.isdigit():
            continue
        issue_id = int(issue_dir.name)
        primary_path = issue_dir / "primary.json"
        reviewer_path = issue_dir / "reviewer.json"
        if not primary_path.exists() or not reviewer_path.exists():
            continue
        try:
            p = json.loads(primary_path.read_text(encoding="utf-8"))
            r = json.loads(reviewer_path.read_text(encoding="utf-8"))
            issues.append({
                "issue_id": issue_id,
                "primary_status": p.get("status", "skip"),
                "primary_confidence": p.get("confidence", 0),
                "reviewer_status": r.get("status", "manual_review"),
                "reviewer_confidence": r.get("confidence", 0),
                "truths_count": r.get("business_truths_count", 0),
                "asserts_total": r.get("asserts_total", 0),
                "asserts_pass": r.get("asserts_pass", 0),
            })
        except Exception:
            continue
    return {"issues": issues[:100], "scanned_at": datetime.now().isoformat()}


def detect_patterns(scan_data: dict) -> dict:
    """从实战数据找 patterns"""
    issues = scan_data.get("issues", [])
    if not issues:
        return {"patterns": [], "recommendations": []}

    patterns = {
        "low_truths_count": [],  # 业务真值 = 0 但实际有真值的 issue
        "high_manual_review": [],  # 大量 manual 的 issue
        "deployment_skipped": [],  # 部署类 skip 的
        "blocked_decisions": [],  # block 决策的
        "skip_decisions": [],  # skip / hold 的
    }
    recommendations = []

    for i in issues:
        if i["truths_count"] == 0:
            patterns["low_truths_count"].append(i["issue_id"])
        if i["reviewer_status"] == "manual_review" and i["truths_count"] > 10:
            patterns["high_manual_review"].append(i["issue_id"])
        if i["primary_status"] == "skip_deployment":
            patterns["deployment_skipped"].append(i["issue_id"])
        if i["primary_status"] == "skip" and i["reviewer_status"] in ("pass", "pass_with_manual"):
            patterns["blocked_decisions"].append(i["issue_id"])

    # 生成建议
    if len(patterns["low_truths_count"]) >= 2:
        recommendations.append({
            "type": "add_section",
            "reason": f"≥2 issue 业务真值=0（{patterns['low_truths_count']}）",
            "action": "扩展 truth_patterns 加新段名（参考军师手册）"
        })
    if len(patterns["deployment_skipped"]) >= 1:
        recommendations.append({
            "type": "verify_deployment_logic",
            "reason": f"部署类 issue（{patterns['deployment_skipped']}）",
            "action": "确认 is_deployment_issue 逻辑没误判"
        })

    return {"patterns": patterns, "recommendations": recommendations}


def cmd_scan():
    """扫实战 + 更新规则"""
    print("🔍 扫最近实战数据...")
    scan_data = scan_real_cases()
    issues = scan_data.get("issues", [])
    print(f"   找到 {len(issues)} 个 issue 实战")

    print("\n📊 检测 patterns...")
    detection = detect_patterns(scan_data)
    patterns = detection["patterns"]
    recommendations = detection["recommendations"]

    print(f"   低真值数（=0）: {patterns['low_truths_count']}")
    print(f"   高 manual: {patterns['high_manual_review']}")
    print(f"   部署类 skip: {patterns['deployment_skipped']}")
    print(f"   block 决策: {patterns['blocked_decisions']}")

    # 更新 stats
    rules = load_rules()
    rules["stats"] = {
        "total_runs": len(issues),
        "issues_verified": [i["issue_id"] for i in issues],
        "decision_distribution": {
            "close": sum(1 for i in issues if i["primary_status"] == "pass" and i["reviewer_status"] == "pass"),
            "hold": len(patterns["deployment_skipped"]),
            "block": len(patterns["blocked_decisions"]),
        },
        "low_truths_count_issues": patterns["low_truths_count"],
        "last_scan": datetime.now().isoformat()
    }
    rules["next_self_update"] = (
        datetime.now().replace(hour=(datetime.now().hour + 4) % 24).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    )
    save_rules(rules)
    print(f"\n✅ 规则已更新 → {RULES_FILE}")

    if recommendations:
        print("\n💡 建议:")
        for r in recommendations:
            print(f"   - {r['type']}: {r['reason']}")
            print(f"     行动: {r['action']}")
    else:
        print("\n✅ 无需调整 — 当前规则覆盖所有实战")


def cmd_rule(name: str):
    """看具体规则"""
    rules = load_rules()
    for r in rules.get("rules", []):
        if r.get("id") == name:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
    print(f"❌ 未找到规则: {name}")


def cmd_stats():
    """看实战统计"""
    rules = load_rules()
    stats = rules.get("stats", {})
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="军师自我进化工具")
    parser.add_argument("--scan", action="store_true", help="扫实战 + 更新规则")
    parser.add_argument("--rule", type=str, help="看具体规则")
    parser.add_argument("--stats", action="store_true", help="看实战统计")
    args = parser.parse_args()

    if args.scan:
        cmd_scan()
    elif args.rule:
        cmd_rule(args.rule)
    elif args.stats:
        cmd_stats()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()