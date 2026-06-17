#!/usr/bin/env python3
"""
Case 草稿反推 v2 — 零人工验收。auto < truths → 拒绝发稿。
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("缺少 PyYAML: pip install pyyaml", file=sys.stderr); sys.exit(1)

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "docs/verification-templates"

TEMPLATES = {
    "dashboard-jump":    {"kw": ["看板跳转","待发货数","含加工订单数","低库存数"],"min":2},
    "order-classify":    {"kw": ["订单分类","8个分类","6个状态","含加工订单"],"min":2},
    "product-sku-stock": {"kw": ["SKU库存","库存汇总","低库存阈值"],"min":1},
    "customer-list":     {"kw": ["客户列表","客户详情","客户搜索"],"min":1},
    "aftersales-flow":   {"kw": ["售后工单","售后状态","退款"],"min":1},
    "auth-sms":          {"kw": ["短信登录","验证码登录","注册"],"min":1},
    "employee-role":     {"kw": ["员工列表","角色权限","岗位"],"min":1},
    "knowledge-ai":      {"kw": ["知识库文档","知识库检索","AI回答"],"min":2},
}

def match_template(title, body):
    text = title + " " + body[:500]
    best, best_score = None, 0
    for name, cfg in TEMPLATES.items():
        score = sum(1 for kw in cfg["kw"] if kw in text)
        if score >= cfg["min"] and score > best_score: best, best_score = name, score
    return best

def load_template(name):
    p = TEMPLATE_DIR / f"{name}.yml"
    if not p.exists(): return None
    try:
        with open(p) as f: return yaml.safe_load(f)
    except Exception as e:
        print(f"⚠️ 模板 {name} 加载失败: {e}", file=sys.stderr)
        return None

def extract_truths(body):
    m = re.search(r"<!-- CONTRACT_JSON\s*(.*?)\s*-->", body, re.DOTALL)
    if m:
        try:
            t = json.loads(m.group(1)).get("business_truths",[])
            if isinstance(t, list) and len(t) > 0: return t
            if isinstance(t, str) and t.strip(): return [t.strip()]  # 单条字符串也接受
        except: pass
    truths = []
    seen = set()
    for pat in [r"##.*?业务真值.*?(?=^##|\Z)",r"##.*?业务规则.*?(?=^##|\Z)",
                r"##.*?验收标准.*?(?=^##|\Z)",r"##.*?预期.*?(?=^##|\Z)"]:
        m = re.search(pat, body, re.MULTILINE|re.DOTALL)
        if not m: continue
        for line in re.findall(r"^\s*[-*]\s*(.+?)$",m.group(0),re.MULTILINE):
            line = line.strip()
            # 过滤注释和太短的行，去重
            if line and not line.startswith("<!--") and len(line) >= 3 and line not in seen:
                truths.append(line)
                seen.add(line)
    return truths

def count_auto_asserts(template):
    """统计可自动验证的 L4 断言数（API）。"""
    if not template or not template.get("reviewer_asserts"): return 0
    count = 0
    for a in template["reviewer_asserts"]:
        if isinstance(a, str) and "API:" in a: count += 1
        elif isinstance(a, dict):
            for k in a:
                if k.lower() == "api": count += 1
    return count

def quality_gate(truths, tmpl_name, template):
    """返回 (messages, can_post)。can_post=False=拒绝发稿"""
    errors, warnings = [], []
    if len(truths) == 0:
        errors.append("🔴 业务真值为空 — 请先在 issue 中填写")
    if not tmpl_name:
        errors.append("🔴 **拒绝发稿**: 未匹配到任何模板，L4 无法自动验证 → block 率 100%。请军师手动指定模板或补充 reviewer_asserts。")
    elif template:
        if template.get("red_flags"):
            warnings.append(f"🔴 红牌: {template['red_flags']} — 请确认历史 issue 已修复")
        auto = count_auto_asserts(template)
        if auto < len(truths):
            errors.append(
                f"🔴 **拒绝发稿**: L4自动断言({auto}) < 业务真值({len(truths)})\n"
                f"   缺少自动验证的真值会导致 reviewer 无法验收 → block 率 100%\n"
                f"   请为每条真值补充 DB/API 验证方式后重试。")
    return errors + warnings, len(errors) == 0

def draft_l2(truths, template):
    if not truths: return "⚠️ 无业务真值"
    lines = []
    # 从模板推导测试文件
    test_files = []
    if template and template.get("primary_specs"):
        test_files = [s.replace("tests/e2e/specs/","tests/").replace(".spec.ts",".test.ts") for s in template["primary_specs"]]
    if not test_files: test_files = ["tests/test_xxx.py (请根据涉及模块选择)"]

    for i, t in enumerate(truths, 1):
        f = test_files[i % len(test_files)]
        lines.append(f"### L2-{i}")
        lines.append(f"**真值**: {t}")
        lines.append(f"**文件**: `{f}`")
        lines.append(f"**方法**: `test_truth_{i}` — 按真值构造输入 → 断言期望输出")
        if template and template.get("common_pitfalls"):
            lines.append(f"**⚠️ 陷阱**: {', '.join(template['common_pitfalls'][:3])}")
        lines.append("")
    return "\n".join(lines)

def draft_l3(template):
    if not template or not template.get("primary_specs"):
        return "⚠️ 未匹配模板，请手动指定 E2E spec"
    lines = []
    for spec in template["primary_specs"]:
        lines.append(f"- `{spec}`: happy path + 错误路径 + 边界")
    if template.get("common_pitfalls"):
        lines.append(f"\n⚠️ {', '.join(template['common_pitfalls'][:3])}")
    return "\n".join(lines)

def draft_l4(truths, template):
    if not truths: return "⚠️ 无业务真值"
    auto = count_auto_asserts(template) if template else 0
    lines = [f"**自动验证**: {auto}/{len(truths)} | **需人工**: {len(truths)-auto}/{len(truths)}"]
    if auto < len(truths):
        lines.append(f"⚠️ {len(truths)-auto} 条真值无法自动验收 — **必须补充后才能发稿**")
    lines.append("")
    for i, t in enumerate(truths, 1):
        lines.append(f"### L4-{i}")
        lines.append(f"**真值**: {t}")
        if template and template.get("reviewer_asserts"):
            for ra in template["reviewer_asserts"]:
                if isinstance(ra, str): lines.append(f"- {ra}")
                elif isinstance(ra, dict):
                    for k, v in ra.items(): lines.append(f"- **{k}**: `{v}`")
        lines.append("")
    return "\n".join(lines)

def generate(issue_number, dry_run=False):
    p = subprocess.Popen(["gh","issue","view",str(issue_number),"--json","title,body"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, err = p.communicate()
    if p.returncode != 0:
        return f"❌ 拉issue失败: {err.decode('utf-8','ignore')[:200]}"
    issue = json.loads(out.decode())
    title, body = issue.get("title",""), issue.get("body","")
    truths = extract_truths(body)
    tmpl_name = match_template(title, body)
    tmpl = load_template(tmpl_name) if tmpl_name else None
    issues, can_post = quality_gate(truths, tmpl_name, tmpl)

    output = [f"## 🤖 军师反推 — Case草稿 (issue #{issue_number})"]
    if issues:
        output.append("")
        for w in issues:
            prefix = "🔴" if "🔴" in w else "🟡" if "🟡" in w else "ℹ️"
            output.append(f"- {w}")

    if not can_post:
        output.append("")
        output.append("**⚠️ 草稿未发布** — 请修复以上问题后重新触发 case_draft。")
        return "\n".join(output)

    output.append("")
    output.append(f"**模板**: `{tmpl_name or '无'}` | **真值**: {len(truths)}条")
    if tmpl and tmpl.get("confidence_required"):
        output.append(f"**要求置信度**: {tmpl['confidence_required']}%")
    output.append("")
    output.append("---")
    output.append("### L2 单测草稿")
    output.append(draft_l2(truths, tmpl))
    output.append("---")
    output.append("### L3 E2E Web草稿")
    output.append(draft_l3(tmpl))
    output.append("---")
    output.append("### L4 业务断言草稿")
    output.append(draft_l4(truths, tmpl))
    output.append("---")
    output.append("### 研发 Review")
    output.append("- ✅ `REVIEW_JSON accept` → 写码")
    output.append("- ❌ `REVIEW_JSON reject` + 原因 → 军师修正")
    output.append("- ➕ `REVIEW_JSON supplement` + 补充 → 继续")

    draft_json = {
        "issue_id": issue_number, "template": tmpl_name,
        "truths": truths, "truths_count": len(truths),
        "auto_asserts": count_auto_asserts(tmpl) if tmpl else 0,
        "specs": tmpl.get("primary_specs",[]) if tmpl else [],
        "red_flags": tmpl.get("red_flags",[]) if tmpl else [],
        "drafted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    output.append("")
    output.append("<!-- DRAFT_JSON")
    output.append(json.dumps(draft_json, ensure_ascii=False, indent=2))
    output.append("-->")

    draft = "\n".join(output)
    if dry_run: return draft
    p = subprocess.Popen(["gh","issue","comment",str(issue_number),"--body",draft],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, err = p.communicate()
    return f"✅ issue #{issue_number}" if p.returncode == 0 else f"❌ {err.decode('utf-8','ignore')[:200]}"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("issue_number", type=int)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(generate(args.issue_number, args.dry_run))

if __name__ == "__main__": main()
