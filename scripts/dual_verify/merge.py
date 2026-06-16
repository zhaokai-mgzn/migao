#!/usr/bin/env python3
"""
合并判定脚本（#450b / #454）

读主验收 + 复核验收结果 → 比对一致性 → 决策：
- ✅ 一致 + 都过 → close issue + 双签名
- ❌ 一致 + 都失败 → hold（不 close）
- ⚠️ 不一致 → block（凯总/娜总复核）
- 📝 全 manual → hold（待人工）
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

QA_RESULT_ROOT = Path("/opt/qa-results")


def load_result(issue_id: int, kind: str):
    path = QA_RESULT_ROOT / str(issue_id) / f"{kind}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def judge(primary: dict, reviewer: dict) -> dict:
    """比对两个验收结果"""
    p_status = primary.get("status", "skip")
    r_status = reviewer.get("status", "skip")
    p_conf = primary.get("confidence", 0)
    r_conf = reviewer.get("confidence", 0)

    # 一致性判定
    p_pass = p_status in ("pass", "pass_with_manual")
    r_pass = r_status in ("pass", "pass_with_manual")
    p_fail = p_status == "fail"
    r_fail = r_status == "fail"

    conflicts = []
    if p_pass and not r_pass:
        conflicts.append("主验收通过但复核不通过（可能 mock 数据骗人）")
    if r_pass and not p_pass:
        conflicts.append("复核通过但主验收不通过（spec 有 bug）")
    if p_conf >= 90 and r_conf < 60:
        conflicts.append("置信度差异大（主高复低）")
    if r_conf >= 90 and p_conf < 60:
        conflicts.append("置信度差异大（复高主低）")

    # 决策
    if not conflicts and p_pass and r_pass and p_conf >= 90 and r_conf >= 90:
        decision = "close"
        verdict = "✅ 双一致 + 置信度达标"
    elif not conflicts and p_fail and r_fail:
        decision = "hold"
        verdict = "❌ 双一致 + 都失败，留研发修"
    elif p_status == "skip" and r_status == "skip":
        decision = "hold"
        verdict = "⏸️ 双方都跳过（可能无 case / 业务真值缺失）"
    elif r_status == "manual_review":
        decision = "hold"
        verdict = "👀 需人工复核（业务真值无法自动断言）"
    elif conflicts:
        decision = "block"
        verdict = f"⚠️ 不一致：{'; '.join(conflicts)}"
    else:
        decision = "block"
        verdict = f"⚠️ 状态不一致：主={p_status} 复={r_status}"

    return {
        "decision": decision,
        "verdict": verdict,
        "conflicts": conflicts,
        "primary": {"status": p_status, "confidence": p_conf},
        "reviewer": {"status": r_status, "confidence": r_conf}
    }


def post_pr_comment(issue_id: int, judgment: dict, primary: dict, reviewer: dict) -> str:
    """发 issue 评论"""
    decision = judgment["decision"]
    icon = {"close": "✅", "hold": "❌", "block": "⚠️"}.get(decision, "❓")

    body = f"""## 🤖 AI 验收报告

{icon} **决定：{decision.upper()}** — {judgment['verdict']}

### 主验收（军师）
- 状态: `{primary.get('status')}`
- 置信度: {primary.get('confidence')}%
- spec: {primary.get('specs_pass', 0)}/{primary.get('specs_total', 0)} 通过

### 复核验收（独立 AI）
- 状态: `{reviewer.get('status')}`
- 置信度: {reviewer.get('confidence')}%
- 业务真值: {reviewer.get('business_truths_count', 0)} 条
- 断言: {reviewer.get('asserts_pass', 0)} pass / {reviewer.get('asserts_fail', 0)} fail / {reviewer.get('asserts_manual', 0)} 待人工

### 一致性
{chr(10).join('- ' + c for c in judgment['conflicts']) if judgment['conflicts'] else '- ✅ 无冲突'}

---
双 AI 独立证据，5 层兜底
Co-Authored: 军师 + 复核 AI
"""
    p = subprocess.Popen(
        ["gh", "issue", "comment", str(issue_id), "--body", body],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke"
    )
    out, err = p.communicate()
    if p.returncode != 0:
        return f"❌ 评论失败: {err.decode('utf-8', 'ignore')[:200]}"
    return "✅ 评论已发"


def act_on_decision(issue_id: int, decision: str) -> str:
    """根据决定执行动作"""
    if decision == "close":
        # close + 加 verified/auto label
        subprocess.Popen(["gh", "issue", "close", str(issue_id), "--reason", "completed"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke")
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "verified/auto"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke")
        return "✅ close + verified/auto"
    elif decision == "hold":
        # 加 hold/auto-fail label（不 close）
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "hold/auto-fail"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke")
        return "⚠️ 加 hold/auto-fail（不 close）"
    elif decision == "block":
        # 加 block/dual-mismatch label（请凯总/娜总复核）
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "block/dual-mismatch"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke")
        return "🔴 加 block/dual-mismatch（凯总/娜总复核）"
    return "noop"


def merge(issue_id: int, dry_run: bool = False) -> dict:
    primary = load_result(issue_id, "primary")
    reviewer = load_result(issue_id, "reviewer")
    if not primary or not reviewer:
        return {
            "issue_id": issue_id,
            "error": f"缺少结果：primary={bool(primary)} reviewer={bool(reviewer)}",
            "hint": "需先跑 verify-primary 和 verify-reviewer"
        }
    judgment = judge(primary, reviewer)
    result = {
        "issue_id": issue_id,
        **judgment
    }
    if not dry_run:
        result["comment"] = post_pr_comment(issue_id, judgment, primary, reviewer)
        result["action"] = act_on_decision(issue_id, judgment["decision"])
    return result


def main():
    parser = argparse.ArgumentParser(description="合并判定")
    parser.add_argument("issue_id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = merge(args.issue_id, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
