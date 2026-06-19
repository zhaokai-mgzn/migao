#!/usr/bin/env python3
"""
二郎神质量报告 — Quality Loop 自进化引擎

从 GitHub issue 评论中提取 DRAFT_JSON / REVIEW_JSON / VERDICT_JSON / BLOCK_LOG，
统计各环节质量指标，帮助军师识别改进方向。

用法: python quality_report.py [--days 30]
"""
import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()

def gh(*args):
    p = subprocess.Popen(["gh"]+list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, _ = p.communicate()
    return out.decode("utf-8","ignore") if p.returncode == 0 else ""

def parse_json_block(text, block_type):
    """从评论中提取 <!-- BLOCK_TYPE ... -->"""
    m = re.search(rf"<!-- {block_type}\s*(.*?)\s*-->", text, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(1))
    except: return None

def collect(days=30):
    """收集所有 AI 协作数据"""
    issues = []
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time()-days*86400))

    # 拿最近更新的 open + closed issue
    for state in ["open","closed"]:
        ids = gh("issue","list","--state",state,"--limit","100",
                 "--search",f"updated:>={cutoff}","--json","number","--jq",".[].number").strip().split()
        for iid in ids:
            if not iid: continue
            comments_raw = gh("issue","view",iid,"--comments","--json","comments")
            if not comments_raw: continue
            try: comments = json.loads(comments_raw).get("comments",[])
            except: continue

            draft = review = verdict = None
            block_depths = []

            for c in comments:
                body = c.get("body","")
                d = parse_json_block(body, "DRAFT_JSON")
                if d: draft = d
                r = parse_json_block(body, "REVIEW_JSON")
                if r: review = r
                v = parse_json_block(body, "VERDICT_JSON")
                if v: verdict = v
                bm = re.search(r'"block_depth"\s*:\s*(\d+)', body)
                if bm: block_depths.append(int(bm.group(1)))

            issues.append({
                "id": int(iid),
                "draft": draft,
                "review": review,
                "verdict": verdict,
                "block_depths": block_depths,
                "max_block_depth": max(block_depths) if block_depths else 0,
            })
    return issues

def report(days=30):
    issues = collect(days)
    if not issues:
        print("没有找到近{days}天的AI协作数据")
        return

    total = len(issues)
    with_draft = sum(1 for i in issues if i["draft"])
    with_review = sum(1 for i in issues if i["review"])
    with_verdict = sum(1 for i in issues if i["verdict"])
    blocked = sum(1 for i in issues if i["max_block_depth"] > 0)
    melted = sum(1 for i in issues if i["max_block_depth"] >= 3)
    verdicts = [i["verdict"] for i in issues if i["verdict"]]
    close_count = sum(1 for v in verdicts if v.get("decision") == "close")
    block_count = sum(1 for v in verdicts if v.get("decision") == "block")
    hold_count = sum(1 for v in verdicts if v.get("decision") == "hold")

    # 模板维度
    template_stats = defaultdict(lambda: {"total":0,"blocked":0,"melted":0,"auto_assert_ratio":0})
    for i in issues:
        if not i["draft"]: continue
        tmpl = i["draft"].get("template") or "无模板"
        s = template_stats[tmpl]
        s["total"] += 1
        if i["max_block_depth"] > 0: s["blocked"] += 1
        if i["max_block_depth"] >= 3: s["melted"] += 1
        truths = i["draft"].get("truths_count", 0)
        auto = i["draft"].get("auto_asserts", 0)
        if truths > 0: s["auto_assert_ratio"] += auto / truths

    # L4 人工率
    manual_issues = [i for i in issues if i["draft"] and i["draft"].get("truths_count",0) > 0
                     and i["draft"].get("auto_asserts",0) < i["draft"].get("truths_count",0)]

    # Agent reject 率
    reviews = [i["review"] for i in issues if i["review"]]
    reject_count = sum(1 for r in reviews if r.get("action") == "reject")
    accept_count = sum(1 for r in reviews if r.get("action") == "accept")

    # 平均置信度
    pass_rates = []
    for v in verdicts:
        if not v: continue
        checks = v.get("checks", [])
        if checks:
            passed = sum(1 for c in checks if c.get("passed"))
            pass_rates.append(passed / len(checks) * 100)
    confidences = pass_rates
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0

    print("=" * 60)
    print(f"  军师质量报告 — 近 {days} 天")
    print("=" * 60)
    print()

    print("## 总览")
    print(f"| 指标 | 数值 |")
    print(f"|------|------|")
    print(f"| 总 issue 数 | {total} |")
    print(f"| 有 case 草稿 | {with_draft} |")
    print(f"| Agent review 数 | {with_review} |")
    print(f"| 验收完成数 | {with_verdict} |")
    print(f"| **block 率** | {block_count}/{with_verdict} ({int(100*block_count/max(with_verdict,1))}%) |")
    print(f"| **hold 率** | {hold_count}/{with_verdict} ({int(100*hold_count/max(with_verdict,1))}%) |")
    print(f"| **close 率** | {close_count}/{with_verdict} ({int(100*close_count/max(with_verdict,1))}%) |")
    print(f"| 平均置信度 | {avg_confidence:.0f}% |")
    print(f"| Agent reject 率 | {reject_count}/{max(reject_count+accept_count,1)} ({int(100*reject_count/max(reject_count+accept_count,1))}%) |")
    print(f"| 曾被打回 | {blocked} |")
    print(f"| 熔断 | {melted} |")
    print(f"| L4 有人工断言 | {len(manual_issues)} |")
    print()

    print("## 模板维度")
    print(f"| 模板 | 总数 | block率 | 熔断 | L4自动覆盖率 |")
    print(f"|------|------|--------|------|-------------|")
    for tmpl, s in sorted(template_stats.items()):
        block_rate = f"{int(100*s['blocked']/max(s['total'],1))}%"
        auto_rate = f"{int(100*s['auto_assert_ratio']/max(s['total'],1))}%"
        melted_flag = "⚠️" if s["melted"] > 0 else ""
        print(f"| {tmpl} | {s['total']} | {block_rate} | {melted_flag} | {auto_rate} |")
    print()

    # 改进建议
    print("## 改进建议")
    suggestions = []

    block_rate = int(100*block_count/max(with_verdict,1))
    if block_rate > 30:
        suggestions.append(f"🔴 block 率 {block_rate}% 过高 — 优先检查 reviewer 关键词覆盖")
    elif block_rate > 15:
        suggestions.append(f"🟡 block 率 {block_rate}% — 关注高频 block 的模板")

    for tmpl, s in template_stats.items():
        if s["total"] >= 2 and s["blocked"] / s["total"] > 0.5:
            suggestions.append(f"🔴 模板 `{tmpl}`: block率 {int(100*s['blocked']/s['total'])}% — 请review该模板的reviewer_asserts")

    if len(manual_issues) > 0:
        suggestions.append(f"🟡 {len(manual_issues)} 个 issue 有 L4 人工断言 — 请为这些模板补充自动验证方式")

    if reject_count > accept_count * 0.3:
        suggestions.append(f"🟡 Agent reject 率偏高({int(100*reject_count/max(reject_count+accept_count,1))}%) — case草稿质量需提升")

    if not suggestions:
        suggestions.append("✅ 所有指标正常，继续保持")

    for s in suggestions: print(f"- {s}")

    # 趋势数据（供外部监控）
    trend = {
        "period_days": days,
        "total": total, "close_rate": int(100*close_count/max(with_verdict,1)),
        "block_rate": int(100*block_count/max(with_verdict,1)),
        "avg_confidence": round(avg_confidence, 1),
        "agent_reject_rate": int(100*reject_count/max(reject_count+accept_count,1)),
        "melted": melted,
        "manual_assert_issues": len(manual_issues),
        "per_template": {k: {"total":v["total"],"block_rate":int(100*v["blocked"]/max(v["total"],1))}
                         for k,v in template_stats.items()},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print()
    print("---")
    print("<!-- QUALITY_REPORT")
    print(json.dumps(trend, ensure_ascii=False, indent=2))
    print("-->")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    report(args.days)
