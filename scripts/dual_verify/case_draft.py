#!/usr/bin/env python3
"""
Case 草稿反推脚本 v2 — 质量优先

用法: python case_draft.py <issue_number> [--dry-run]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("缺少 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "docs/verification-templates"

# ── 模板匹配（精确优先）──

TEMPLATES = {
    "dashboard-jump":    {"kw": ["看板跳转", "待发货数", "含加工订单数", "低库存数"], "min_kw": 2},
    "order-classify":    {"kw": ["订单分类", "8个分类", "6个状态", "含加工订单"], "min_kw": 2},
    "product-sku-stock": {"kw": ["SKU库存", "库存汇总", "低库存阈值"], "min_kw": 1},
    "customer-list":     {"kw": ["客户列表", "客户详情", "客户搜索"], "min_kw": 1},
    "aftersales-flow":   {"kw": ["售后工单", "售后状态", "退款"], "min_kw": 1},
    "auth-sms":          {"kw": ["短信登录", "验证码登录", "注册"], "min_kw": 1},
    "employee-role":     {"kw": ["员工列表", "角色权限", "岗位"], "min_kw": 1},
    "knowledge-ai":      {"kw": ["知识库文档", "知识库检索", "AI回答"], "min_kw": 2},
}

def match_template(title: str, body: str) -> Optional[str]:
    text = title + " " + body[:500]
    best, best_score = None, 0
    for name, cfg in TEMPLATES.items():
        score = sum(1 for kw in cfg["kw"] if kw in text)
        if score >= cfg["min_kw"] and score > best_score:
            best, best_score = name, score
    return best

def load_template(name: str) -> Optional[dict]:
    path = TEMPLATE_DIR / f"{name}.yml"
    return yaml.safe_load(open(path)) if path.exists() else None

# ── 业务真值提取（优先 CONTRACT_JSON，fallback 正则）──

def extract_truths(body: str) -> list:
    # 优先机读
    m = re.search(r"<!-- CONTRACT_JSON\s*(.*?)\s*-->", body, re.DOTALL)
    if m:
        try:
            c = json.loads(m.group(1))
            truths = c.get("business_truths", [])
            if truths: return truths
        except json.JSONDecodeError: pass

    # Fallback: 正则匹配章节
    patterns = [
        r"##.*?业务真值.*?(?=^##|\Z)", r"##.*?业务规则.*?(?=^##|\Z)",
        r"##.*?验收标准.*?(?=^##|\Z)", r"##.*?Acceptance Criteria.*?(?=^##|\Z)",
        r"##.*?预期.*?(?=^##|\Z)", r"##.*?正确行为.*?(?=^##|\Z)",
    ]
    truths = []
    for pat in patterns:
        m = re.search(pat, body, re.MULTILINE | re.DOTALL)
        if not m: continue
        for line in re.findall(r"^\s*[-*]\s*(.+?)$", m.group(0), re.MULTILINE):
            line = line.strip()
            if line and not line.startswith("<!--") and len(line) > 5:
                truths.append(line)
    return truths

# ── Case 生成（具体可执行）──

def draft_l2(truths: list, template: dict) -> str:
    if not truths: return "⚠️ 无业务真值，请先在 issue 中填写"
    lines = []
    for i, t in enumerate(truths, 1):
        lines.append(f"### L2-{i}")
        lines.append(f"**业务真值**: {t}")
        lines.append(f"**测试文件**: `tests/test_xxx.py`（请根据涉及模块选择）")
        lines.append(f"**测试方法**: test_truth_{i}")
        lines.append(f"**输入**: 根据真值构造测试数据")
        lines.append(f"**期望**: 真值中描述的预期结果")
        lines.append(f"**边界**: 空数据 / 极端值 / 并发")
        if template and template.get("common_pitfalls"):
            lines.append(f"**陷阱**: {', '.join(template['common_pitfalls'][:3])}")
        lines.append("")
    if template and template.get("primary_specs"):
        lines.append("**推荐文件**: " + ", ".join(template["primary_specs"]))
    return "\n".join(lines)

def draft_l3(template: dict) -> str:
    if not template or not template.get("primary_specs"):
        return "⚠️ 未匹配模板，请根据业务真值手动指定 E2E spec"
    lines = []
    for spec in template["primary_specs"]:
        lines.append(f"- `{spec}`")
        lines.append(f"  - happy path: 正常业务流程")
        lines.append(f"  - 错误路径: 异常输入/网络错误")
        lines.append(f"  - 边界: 空数据/极端值")
    if template.get("common_pitfalls"):
        lines.append(f"\n⚠️ 注意: {', '.join(template['common_pitfalls'][:3])}")
    return "\n".join(lines)

def draft_l4(truths: list, template: dict) -> str:
    if not truths: return "⚠️ 无业务真值"
    lines = []
    auto_count = 0
    manual_count = 0

    for i, t in enumerate(truths, 1):
        assert_type = "manual"
        sql = ""
        api = ""

        # 从模板 reviewer_asserts 匹配
        if template and template.get("reviewer_asserts"):
            for ra in template["reviewer_asserts"]:
                if isinstance(ra, str) and "DB:" in ra:
                    sql = ra.replace("DB:", "").strip()
                    assert_type = "auto"
                elif isinstance(ra, str) and "API:" in ra:
                    api = ra.replace("API:", "").strip()
                    assert_type = "auto"
                elif isinstance(ra, dict):
                    for k, v in ra.items():
                        if "sql" in k.lower(): sql, assert_type = v, "auto"
                        if "api" in k.lower(): api, assert_type = v, "auto"

        if assert_type == "auto": auto_count += 1
        else: manual_count += 1

        lines.append(f"### L4-{i} [{assert_type}]")
        lines.append(f"**真值**: {t}")
        if sql: lines.append(f"**DB验证**: `{sql}`")
        if api: lines.append(f"**API验证**: `{api}`")
        if assert_type == "manual":
            lines.append(f"**⚠️ 无法自动反推**，请军师手动补充 SQL/API 验证方式")
        lines.append("")

    summary = f"**自动验证**: {auto_count}/{len(truths)} | **需人工**: {manual_count}/{len(truths)}"
    if manual_count > 0:
        summary += f"\n⚠️ {manual_count} 条真值无法自动验收 → 可能增加 block 风险"
    lines.insert(0, summary + "\n")
    return "\n".join(lines)

# ── 发前质量检查 ──

def quality_gate(truths: list, template_name: str, template: dict) -> list:
    warnings = []
    if len(truths) == 0:
        warnings.append("🔴 业务真值为空 — case 草稿无法生成有效验收标准")
    if not template_name:
        warnings.append("🟡 未匹配模板 — L3/L4 自动反推受限")
    if template and template.get("red_flags"):
        warnings.append(f"🔴 红牌标记: {template['red_flags']} — 请确认历史问题已修复")
    # 检查 L4 覆盖率
    if template and template.get("reviewer_asserts"):
        auto_asserts = [a for a in template["reviewer_asserts"] if isinstance(a, str) and ("DB:" in a or "API:" in a)]
        if len(auto_asserts) < len(truths):
            warnings.append(f"🟡 L4自动断言({len(auto_asserts)}条) < 业务真值({len(truths)}条) — 部分真值无法自动验收")
    return warnings

# ── 主流程 ──

def generate(issue_number: int, dry_run: bool = False) -> str:
    p = subprocess.Popen(["gh","issue","view",str(issue_number),"--json","title,body"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT))
    out, err = p.communicate()
    if p.returncode != 0:
        return f"❌ 拉 issue #{issue_number} 失败: {err.decode('utf-8','ignore')[:200]}"

    issue = json.loads(out.decode())
    title = issue.get("title", "")
    body = issue.get("body", "")
    truths = extract_truths(body)
    tmpl_name = match_template(title, body)
    tmpl = load_template(tmpl_name) if tmpl_name else None
    warnings = quality_gate(truths, tmpl_name, tmpl)

    output = []
    output.append(f"## 🤖 军师反推 — Case 草稿 (issue #{issue_number})")
    output.append("")

    # 质量告警
    if warnings:
        output.append("### ⚠️ 质量检查")
        for w in warnings: output.append(f"- {w}")
        output.append("")

    output.append(f"**模板**: `{tmpl_name or '无匹配'}` | **真值数**: {len(truths)}")
    if tmpl and tmpl.get("confidence_required"):
        output.append(f"**要求置信度**: {tmpl['confidence_required']}%")
    output.append("")
    output.append("---")
    output.append("### L2 单测草稿")
    output.append(draft_l2(truths, tmpl))
    output.append("---")
    output.append("### L3 E2E Web 草稿")
    output.append(draft_l3(tmpl))
    output.append("---")
    output.append("### L4 业务断言草稿")
    output.append(draft_l4(truths, tmpl))
    output.append("---")
    output.append("### 研发 Review")
    output.append("- ✅ 同意 → 贴 `REVIEW_JSON accept` → 写码")
    output.append("- ❌ 不同意 → 贴 `REVIEW_JSON reject` + 原因 → 军师修正")
    output.append("- ➕ 补 case → 贴 `REVIEW_JSON supplement` + 补充内容")

    # 机读块
    draft_json = {
        "issue_id": issue_number, "template": tmpl_name,
        "truths": truths, "truths_count": len(truths),
        "auto_asserts": sum(1 for t in truths if tmpl and tmpl.get("reviewer_asserts")),
        "manual_asserts": sum(1 for t in truths if not tmpl or not tmpl.get("reviewer_asserts")),
        "specs": tmpl.get("primary_specs", []) if tmpl else [],
        "red_flags": tmpl.get("red_flags", []) if tmpl else [],
        "warnings": warnings,
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
    p = argparse.ArgumentParser(description="反推 issue case 草稿")
    p.add_argument("issue_number", type=int)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(generate(args.issue_number, args.dry_run))

if __name__ == "__main__":
    main()
