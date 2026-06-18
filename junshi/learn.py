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


# ═══════════════════════════════════════════════════════════════
# QA 生长体系 — 自动发现覆盖盲区并生长
# ═══════════════════════════════════════════════════════════════

# 当前 _TRUTH_KEYWORD_MAP（与 reviewer.py 同步）
# 生长机制会从 manual 断言中提取新关键词，补充到这里
CURRENT_KEYWORD_COVERAGE = {
    "看板/dashboard/跳转": "API: GET /api/admin/dashboard/stats",
    "订单/order": "API: GET /api/admin/orders?page=1&size=5",
    "商品/product/SKU/库存/stock": "API: GET /api/admin/products",
    "客户/customer": "API: GET /api/admin/customers?keyword=",
    "售后/aftersales/退款": "API: GET /api/admin/aftersales/{id}",
    "登录/login/验证码/注册/密码/token": "API: POST /api/auth/sms/login",
    "员工/employee/角色/权限/岗位": "API: GET /api/admin/employees",
    "知识库/knowledge/AI/回答/检索/文档": "API: POST /api/knowledge/search",
    "加工/processing/has_processing": "API: GET /api/admin/dashboard/processing-shipment-count",
    "待发货/pending_shipment": "API: GET /api/admin/dashboard/pending-shipment-count",
    "tab/分类/tab计数": "API: GET 对应列表 + 分页 total 匹配",
    "发送/send/消息/chat/对话/SSE": "API: POST /api/chat/send",
}


def scan_manual_assertions() -> list:
    """扫 QA results，提取 manual 断言中的业务真值文本"""
    manual_truths = []
    if not QA_RESULTS_DIR.exists():
        return manual_truths

    for issue_dir in sorted(QA_RESULTS_DIR.iterdir()):
        if not issue_dir.is_dir() or not issue_dir.name.isdigit():
            continue
        reviewer_path = issue_dir / "reviewer.json"
        if not reviewer_path.exists():
            continue
        try:
            r = json.loads(reviewer_path.read_text(encoding="utf-8"))
            for result in r.get("results", []):
                if result.get("type") == "manual":
                    note = result.get("note", "")
                    name = result.get("name", "")
                    # 从 name 提取真值文本（格式：L4-N: 真值文本前60字）
                    if ":" in name:
                        truth_text = name.split(":", 1)[1].strip()
                        if truth_text and len(truth_text) >= 3:
                            manual_truths.append({
                                "issue_id": r["issue_id"],
                                "text": truth_text,
                                "note": note,
                            })
        except Exception:
            continue
    return manual_truths


def find_keyword_gaps(manual_truths: list) -> list:
    """分析 manual 断言文本，找到未被现有关键词覆盖的业务领域"""
    gaps = []
    for mt in manual_truths:
        text_lower = mt["text"].lower()
        # 检查是否被任何已知关键词覆盖
        covered = False
        for kw_group in CURRENT_KEYWORD_COVERAGE:
            if any(kw.lower() in text_lower for kw in kw_group.split("/")):
                covered = True
                break
        if not covered:
            gaps.append(mt)

    # 聚合同类 gap
    keyword_counts = {}
    for g in gaps:
        # 提取可能的业务关键词（中文词或英文词）
        words = re.findall(r"[一-鿿]{2,4}|[a-z_]{3,}", g["text"].lower())
        for w in words:
            if w not in keyword_counts:
                keyword_counts[w] = {"count": 0, "examples": []}
            keyword_counts[w]["count"] += 1
            if len(keyword_counts[w]["examples"]) < 2:
                keyword_counts[w]["examples"].append(g["text"][:80])

    # 过滤：出现 ≥2 次的才算有效 gap
    return [
        {"keyword": kw, "count": info["count"], "examples": info["examples"]}
        for kw, info in keyword_counts.items()
        if info["count"] >= 2
    ]


def detect_template_gaps() -> list:
    """检测模板 auto_asserts 不足的情况"""
    rules = load_rules()
    gaps = []
    template_coverage = rules.get("template_coverage", {})
    truths_ratio = template_coverage.get("truths_to_asserts_ratio", {})

    for tmpl, ratio_str in truths_ratio.items():
        # 解析 "4:4 (100%)" 格式
        m = re.match(r"(\d+):(\d+)", ratio_str)
        if m:
            truths = int(m.group(1))
            asserts = int(m.group(2))
            if asserts < truths:
                gaps.append({
                    "template": tmpl,
                    "truths": truths,
                    "asserts": asserts,
                    "gap": truths - asserts,
                })
    return gaps


def detect_mock_deception() -> list:
    """检测 primary=pass + reviewer=fail 的 mock 欺骗模式"""
    if not QA_RESULTS_DIR.exists():
        return []

    deceptions = []
    for issue_dir in QA_RESULTS_DIR.iterdir():
        if not issue_dir.is_dir() or not issue_dir.name.isdigit():
            continue
        primary_path = issue_dir / "primary.json"
        reviewer_path = issue_dir / "reviewer.json"
        if not primary_path.exists() or not reviewer_path.exists():
            continue
        try:
            p = json.loads(primary_path.read_text(encoding="utf-8"))
            r = json.loads(reviewer_path.read_text(encoding="utf-8"))
            if p.get("status") in ("pass", "pass_with_manual") and r.get("status") == "fail":
                # primary 通过但 reviewer 失败 → 可能是 mock 骗过了单测
                spec_files = []
                for res in p.get("results", []):
                    if res.get("spec"):
                        spec_files.append(res["spec"])
                deceptions.append({
                    "issue_id": p["issue_id"],
                    "primary_confidence": p.get("confidence", 0),
                    "reviewer_confidence": r.get("confidence", 0),
                    "specs": spec_files,
                })
        except Exception:
            continue
    return deceptions


def cmd_grow(dry_run: bool = True):
    """QA 生长 — 分析数据，生成生长建议"""
    print("🌱 QA 生长体系 — 自检中...")
    print()

    # 1. 关键词覆盖盲区
    print("1️⃣  关键词覆盖盲区")
    manual_truths = scan_manual_assertions()
    print(f"   扫到 {len(manual_truths)} 条 manual 断言")
    keyword_gaps = find_keyword_gaps(manual_truths)

    if keyword_gaps:
        print(f"   发现 {len(keyword_gaps)} 个未覆盖关键词:")
        for kg in sorted(keyword_gaps, key=lambda x: -x["count"]):
            print(f"   🔑 {kg['keyword']} (×{kg['count']}) — 例: {kg['examples'][0][:50]}")
    else:
        print("   ✅ 关键词覆盖完整")

    # 2. 模板缺口
    print()
    print("2️⃣  模板断言缺口")
    template_gaps = detect_template_gaps()
    if template_gaps:
        for tg in template_gaps:
            print(f"   ⚠️  {tg['template']}: {tg['truths']}条真值 vs {tg['asserts']}条断言 (缺{tg['gap']}条)")
    else:
        print("   ✅ 模板断言充足")

    # 3. Mock 欺骗检测
    print()
    print("3️⃣  Mock 欺骗检测 (primary=pass + reviewer=fail)")
    deceptions = detect_mock_deception()
    if deceptions:
        print(f"   ⚠️  发现 {len(deceptions)} 次疑似 mock 欺骗:")
        for d in deceptions[:5]:
            print(f"   🎭 issue #{d['issue_id']}: 主验收{d['primary_confidence']}% vs 复核{d['reviewer_confidence']}%")
    else:
        print("   ✅ 未发现 mock 欺骗")

    # 4. 生长行动
    print()
    print("4️⃣  生长行动")

    growth_log = {
        "timestamp": datetime.now().isoformat(),
        "keyword_gaps": keyword_gaps,
        "template_gaps": template_gaps,
        "mock_deceptions": deceptions,
        "actions_taken": [],
    }

    rules = load_rules()

    # 高频关键词 → 自动补充到规则库
    if keyword_gaps and not dry_run:
        new_keywords = []
        for kg in keyword_gaps:
            if kg["count"] >= 3:  # ≥3 次才自动补充
                new_keywords.append({"keyword": kg["keyword"], "count": kg["count"]})
                print(f"   ✅ 自动补充关键词: {kg['keyword']} (×{kg['count']})")

        if new_keywords:
            rules.setdefault("suggested_keywords", [])
            for nk in new_keywords:
                if nk not in rules["suggested_keywords"]:
                    rules["suggested_keywords"].append(nk)
            growth_log["actions_taken"].append({
                "type": "add_keywords",
                "keywords": new_keywords,
            })

    # mock 欺骗 → 生成 Gate 收紧建议
    if deceptions:
        affected_files = set()
        for d in deceptions:
            for s in d.get("specs", []):
                affected_files.add(s)
        rules["gate_feedback"]["patterns"][0]["last_seen_in"] = list(affected_files)[:5]
        print(f"   ⚠️  Gate 收紧建议: {len(affected_files)} 个文件需集成测试而非纯单测")

    if not growth_log["actions_taken"] and not deceptions:
        print("   ✅ 无需生长 — 当前覆盖充分")

    # 更新规则
    rules.setdefault("growth_log", [])
    rules["growth_log"].append(growth_log)
    # 只保留最近 10 次生长记录
    rules["growth_log"] = rules["growth_log"][-10:]

    if not dry_run:
        save_rules(rules)
        print(f"\n✅ 生长记录已写入 {RULES_FILE}")
    else:
        print(f"\n🔍 --dry-run 模式，未写入（加 --apply 执行生长）")

    return growth_log


def main():
    parser = argparse.ArgumentParser(description="军师自我进化工具")
    parser.add_argument("--scan", action="store_true", help="扫实战 + 更新统计")
    parser.add_argument("--grow", action="store_true", help="QA 生长 — 分析盲区并自动补充")
    parser.add_argument("--apply", action="store_true", help="配合 --grow 使用，实际执行生长（否则 dry-run）")
    parser.add_argument("--rule", type=str, help="看具体规则")
    parser.add_argument("--stats", action="store_true", help="看实战统计")
    args = parser.parse_args()

    if args.scan:
        cmd_scan()
    elif args.grow:
        cmd_grow(dry_run=not args.apply)
    elif args.rule:
        cmd_rule(args.rule)
    elif args.stats:
        cmd_stats()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()