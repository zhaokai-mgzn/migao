#!/usr/bin/env python3
"""
合并判定脚本（#450b / #454）

读主验收 + 复核验收结果 → 比对一致性 → 决策：
- ✅ 一致 + 都过 → close issue + 双签名
- ❌ 一致 + 都失败 → hold（不 close）
- ⚠️ 不一致 → block → 自动创建修复 issue（3 次打回后熔断）
- 📝 全 manual → hold（待人工）
"""
import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
QA_RESULT_ROOT = Path(os.getenv("QA_RESULT_ROOT", "/opt/qa-results"))
MAX_BLOCK_DEPTH = 3


def _get_issue_body(issue_id: int) -> str:
    p = subprocess.Popen(
        ["gh", "issue", "view", str(issue_id), "--json", "body"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, _ = p.communicate()
    if p.returncode != 0:
        return ""
    try:
        return json.loads(out.decode("utf-8")).get("body", "")
    except json.JSONDecodeError:
        return ""


def _parse_contract(issue_body: str) -> dict:
    match = re.search(r"<!-- CONTRACT_JSON\s*(.*?)\s*-->", issue_body, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def _get_block_chain_depth(issue_body: str) -> int:
    return _parse_contract(issue_body).get("block_depth", 0) + 1


def _get_root_issue_id(issue_body: str) -> int:
    return _parse_contract(issue_body).get("root_issue", 0)


def _log_block_rate(issue_id: int, root_id: int, depth: int):
    log_path = QA_RESULT_ROOT / "block-rate.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "issue_id": issue_id, "root_issue": root_id, "block_depth": depth}
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _check_block_rate_alert() -> str:
    log_path = QA_RESULT_ROOT / "block-rate.jsonl"
    if not log_path.exists():
        return ""
    cutoff = time.time() - 7 * 86400
    blocks, roots = 0, set()
    with open(log_path) as f:
        for line in f:
            try:
                e = json.loads(line)
                if time.mktime(time.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ")) >= cutoff:
                    blocks += 1
                    roots.add(e.get("root_issue", 0))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    if blocks >= 5 and len(roots) >= 3 and int(100 * blocks / max(blocks, 10)) > 30:
        return f"⚠️ **Block 率告警**：近 7 天 {blocks} 次 block / {len(roots)} 个独立根 issue。建议检查 reviewer 关键词覆盖和业务真值质量。"
    return ""


def load_result(issue_id: int, kind: str):
    path = QA_RESULT_ROOT / str(issue_id) / f"{kind}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def judge(primary: dict, reviewer: dict, cloud: dict = None) -> dict:
    p_status = primary.get("status", "skip")
    r_status = reviewer.get("status", "skip")
    p_conf = primary.get("confidence", 0)
    r_conf = reviewer.get("confidence", 0)
    c_verdict = cloud.get("verdict", "skip") if cloud else "skip"

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
    if cloud and c_verdict == "fail":
        conflicts.append("云验收 fail（真实业务不通过）")

    if cloud and c_verdict == "fail":
        decision, verdict = "block", "🔴 云验收 fail"
    elif not conflicts and p_pass and r_pass and p_conf >= 90 and r_conf >= 90:
        decision, verdict = "close", "✅ 双一致 + 置信度达标"
    elif not conflicts and p_fail and r_fail:
        decision, verdict = "hold", "❌ 双一致 + 都失败，留研发修"
    elif "skip_deployment" in str(p_status):
        decision, verdict = "hold", "⏸️ 部署类 issue — 等云验收"
    elif p_status == "skip" and r_status == "skip":
        decision, verdict = "hold", "⏸️ 双方都跳过"
    elif r_status == "manual_review":
        decision, verdict = "hold", "👀 需人工复核"
    elif conflicts:
        decision, verdict = "block", f"⚠️ 不一致：{'; '.join(conflicts)}"
    else:
        decision, verdict = "block", f"⚠️ 状态不一致：主={p_status} 复={r_status}"

    return {"decision": decision, "verdict": verdict, "conflicts": conflicts}


def _build_verdict_json(issue_id: int, judgment: dict, primary: dict, reviewer: dict) -> dict:
    return {
        "issue_id": issue_id, "decision": judgment["decision"], "verdict": judgment["verdict"],
        "primary": {"status": primary.get("status"), "confidence": primary.get("confidence"),
                    "specs_pass": primary.get("specs_pass", 0), "specs_total": primary.get("specs_total", 0),
                    "failed_results": [r for r in primary.get("results", []) if r.get("status") == "fail"]},
        "reviewer": {"status": reviewer.get("status"), "confidence": reviewer.get("confidence"),
                     "asserts_pass": reviewer.get("asserts_pass", 0), "asserts_fail": reviewer.get("asserts_fail", 0)},
        "conflicts": judgment.get("conflicts", [])}


def post_pr_comment(issue_id: int, judgment: dict, primary: dict, reviewer: dict) -> str:
    decision = judgment["decision"]
    icon = {"close": "✅", "hold": "❌", "block": "⚠️"}.get(decision, "❓")
    vj = json.dumps(_build_verdict_json(issue_id, judgment, primary, reviewer), ensure_ascii=False, indent=2)

    body = f"""## 🤖 AI 验收报告

{icon} **决定：{decision.upper()}** — {judgment['verdict']}

### 主验收（军师）
- 状态: `{primary.get('status')}` / 置信度: {primary.get('confidence')}%
- spec: {primary.get('specs_pass', 0)}/{primary.get('specs_total', 0)} 通过

### 复核验收（独立 AI）
- 状态: `{reviewer.get('status')}` / 置信度: {reviewer.get('confidence')}%
- 断言: {reviewer.get('asserts_pass', 0)} pass / {reviewer.get('asserts_fail', 0)} fail

### 一致性
{chr(10).join('- ' + c for c in judgment['conflicts']) if judgment['conflicts'] else '- ✅ 无冲突'}

---
双 AI 独立证据，5 层兜底

<!-- VERDICT_JSON
{vj}
-->
"""
    p = subprocess.Popen(["gh", "issue", "comment", str(issue_id), "--body", body],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, err = p.communicate()
    return "✅ 评论已发" if p.returncode == 0 else f"❌ 评论失败: {err.decode('utf-8', 'ignore')[:200]}"


def act_on_decision(issue_id: int, decision: str, judgment: dict = None,
                    primary: dict = None, reviewer: dict = None, issue_body: str = "") -> str:
    if decision == "close":
        subprocess.Popen(["gh", "issue", "close", str(issue_id), "--reason", "completed"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "verified/auto"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
        return "✅ close + verified/auto"

    if decision == "hold":
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "hold/auto-fail"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
        return "⚠️ hold/auto-fail"

    if decision == "block":
        body = issue_body or _get_issue_body(issue_id)
        depth = _get_block_chain_depth(body)
        root_id = _get_root_issue_id(body) or issue_id
        _log_block_rate(issue_id, root_id, depth)

        # ── 3 次打回熔断 ──
        if depth >= MAX_BLOCK_DEPTH:
            subprocess.Popen(["gh", "issue", "edit", str(issue_id),
                              "--add-label", "block/need-human,block/dual-mismatch"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
            melt = (f"## 🛑 熔断：已打回 {depth} 次\n\n"
                    f"根 issue #{root_id} 已被打回 {depth} 次（≥{MAX_BLOCK_DEPTH}），自动修复循环已停止。\n\n"
                    f"请凯总/娜总人工介入。可能原因：业务真值歧义 / reviewer 验证 bug / 代码与真值根本不一致。\n\n"
                    f"<!-- COMMENT_JSON {{\"from\":\"junshi\",\"intent\":\"circuit_breaker\",\"block_depth\":{depth},\"root_issue\":{root_id}}} -->")
            subprocess.Popen(["gh", "issue", "comment", str(issue_id), "--body", melt],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
            alert = _check_block_rate_alert()
            if alert:
                subprocess.Popen(["gh", "issue", "comment", str(issue_id), "--body", alert],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
            return f"🛑 熔断: 根 issue #{root_id} 打回 {depth} 次，已停止"

        # ── 正常 block ──
        subprocess.Popen(["gh", "issue", "edit", str(issue_id), "--add-label", "block/dual-mismatch"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))

        summary = judgment["conflicts"][0][:80] if (judgment and judgment.get("conflicts")) else ""
        failed = [r.get("spec", r.get("test", "")) for r in (primary.get("results", []) if primary else []) if r.get("status") == "fail"]

        fix = f"""## 🔧 验收 blocked — 自动修复（第 {depth}/{MAX_BLOCK_DEPTH} 次）

父 issue: #{issue_id} / 根 issue: #{root_id}

### 冲突
{chr(10).join('- ' + c for c in (judgment.get('conflicts', []) if judgment else [])) if (judgment and judgment.get('conflicts')) else '- 见验收报告'}

### 失败 spec
{chr(10).join('- `' + s + '`' for s in failed) if failed else '- 见验收报告'}

修复 → PR → merge → 军师重新验收。第 {MAX_BLOCK_DEPTH} 次打回后将熔断。

<!-- CONTRACT_JSON
{{"schema_version":"1.0","type":"bug","parent_issue":{issue_id},"root_issue":{root_id},"block_depth":{depth},"failed_specs":{json.dumps(failed)},"conflicts":{json.dumps(judgment.get('conflicts', []) if judgment else [])}}}
-->
"""
        p = subprocess.Popen(
            ["gh", "issue", "create",
             "--title", f"🔧 修复验收 #{issue_id} (第{depth}次): {summary}" if summary else f"🔧 修复验收 #{issue_id} (第{depth}次)",
             "--body", fix, "--label", "bug,needs-verification"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
        out, err = p.communicate()
        if p.returncode == 0:
            return f"🔴 block (第{depth}次) + 修复 issue {out.decode('utf-8').strip()}"
        return f"🔴 block（修复 issue 创建失败: {err.decode('utf-8','ignore')[:100]}）"

    return "noop"


def merge(issue_id: int, dry_run: bool = False) -> dict:
    primary = load_result(issue_id, "primary")
    reviewer = load_result(issue_id, "reviewer")
    cloud = load_result(issue_id, "cloud")
    if not primary or not reviewer:
        return {"issue_id": issue_id, "error": f"缺少结果 primary={bool(primary)} reviewer={bool(reviewer)}"}
    judgment = judge(primary, reviewer, cloud)
    issue_body = _get_issue_body(issue_id)
    result = {"issue_id": issue_id, **judgment}
    if not dry_run:
        result["comment"] = post_pr_comment(issue_id, judgment, primary, reviewer)
        result["action"] = act_on_decision(issue_id, judgment["decision"], judgment, primary, reviewer, issue_body)
    return result


def main():
    p = argparse.ArgumentParser(description="合并判定")
    p.add_argument("issue_id", type=int)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(json.dumps(merge(args.issue_id, args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
