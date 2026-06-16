#!/usr/bin/env python3
"""
Case 草稿反推脚本（#450b）

读取 issue body + 模板库，反推 L2/L3/L4 case 草稿。

用法：
    python case_draft.py <issue_number>
    python case_draft.py --dry-run <issue_number>
"""
import argparse
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("缺少 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


TEMPLATE_DIR = Path(__file__).parent.parent.parent / "docs/verification-templates"


def match_template(issue_title: str, issue_body: str) -> Optional[str]:
    """根据 issue 标题/描述匹配业务模式模板"""
    keywords_map = {
        "dashboard-jump": ["看板", "跳转", "待发货", "含加工", "低库存"],
        "order-classify": ["分类", "订单状态", "8 个分类", "6 个状态"],
        "product-sku-stock": ["SKU", "库存", "商品列表"],
        "customer-list": ["客户", "客户列表", "客户详情"],
        "aftersales-flow": ["售后", "退款", "工单"],
        "auth-sms": ["登录", "注册", "短信", "验证码", "密码"],
        "employee-role": ["员工", "角色", "权限", "岗位"],
        "knowledge-ai": ["知识库", "知识", "AI", "客服"],
    }
    text = issue_title + issue_body
    for template, keywords in keywords_map.items():
        if any(kw in text for kw in keywords):
            return template
    return None


def load_template(name: str) -> Optional[dict]:
    path = TEMPLATE_DIR / f"{name}.yml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def extract_business_truths(issue_body: str) -> "list[str]":
    """从 issue body 提取业务真值（业务语言）"""
    match = re.search(r"## 业务真值.*?(?=^##|\Z)", issue_body, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    section = match.group(0)
    # 提取 - 开头的条目
    truths = re.findall(r"^\s*[-*]\s*(.+?)$", section, re.MULTILINE)
    return [t.strip() for t in truths if t.strip() and not t.strip().startswith("<!--")]


def draft_l2_cases(business_truths: "list[str]", template: Optional[dict]) -> str:
    """反推 L2 单测 case 草稿"""
    cases = []
    for i, truth in enumerate(business_truths, 1):
        if template:
            cases.append(f"- ☐ 测试方法 {i}（基于\"{truth[:30]}...\"）")
            cases.append(f"  - 业务真值: {truth}")
            cases.append(f"  - 建议断言: 准备测试数据 → 调用方法 → 断言返回值")
            cases.append(f"  - 边界: 空数据 / 极端值 / 异常输入")
        else:
            cases.append(f"- ☐ 业务真值 {i} 对应单测")
            cases.append(f"  - 业务真值: {truth}")
            cases.append(f"  - 建议断言: 准备测试数据 → 调用方法 → 断言返回值")
    if template and "primary_specs" in template:
        cases.append("")
        cases.append("### 推荐文件路径")
        for spec in template.get("primary_specs", []):
            cases.append(f"- 建议在对应 spec 同目录新增测试：{spec.replace('.spec.ts', '.test.ts')}")
    return "\n".join(cases) if cases else "（无业务真值可反推，请先填业务真值）"


def draft_l3_cases(template: Optional[dict]) -> str:
    """反推 L3 E2E Web case 草稿"""
    if template and "primary_specs" in template:
        cases = ["### 推荐 spec"]
        for spec in template.get("primary_specs", []):
            cases.append(f"- ☐ 在 `{spec}` 中加 case")
            cases.append(f"  - happy path: 正常流程")
            cases.append(f"  - 错误路径: 异常情况")
            cases.append(f"  - 边界: 极端输入")
        cases.append("")
        cases.append("（参考模板常见错误，避免）")
        for pitfall in template.get("common_pitfalls", []):
            cases.append(f"- ⚠️ {pitfall}")
        return "\n".join(cases)
    return "（无模板匹配，研发请按业务真值自建 E2E）"


def draft_l4_asserts(business_truths: "list[str]", template: Optional[dict]) -> str:
    """反推 L4 业务断言（独立于 L2/L3）"""
    asserts = []
    for i, truth in enumerate(business_truths, 1):
        asserts.append(f"- ☐ 业务真值 {i} 独立断言")
        asserts.append(f"  - 业务真值: {truth}")
        asserts.append(f"  - 实现: 军师/独立 AI 翻译成 DB SQL 或 API 调用")
        asserts.append(f"  - 验证: 与 L2/L3 结果一致")
    if template and "reviewer_asserts" in template:
        asserts.append("")
        asserts.append("### 模板推荐断言")
        for a in template["reviewer_asserts"]:
            if isinstance(a, dict):
                for k, v in a.items():
                    asserts.append(f"- **{k}**: `{v}`")
            else:
                asserts.append(f"- {a}")
    return "\n".join(asserts) if asserts else "（待业务真值明确后反推）"


def generate_draft(issue_number: int, dry_run: bool = False) -> str:
    """生成 case 草稿"""
    import subprocess
    p = subprocess.Popen(
        ["gh", "issue", "view", str(issue_number), "--json", "title,body"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke"
    )
    out, err = p.communicate()
    out_text = out.decode("utf-8", errors="replace")
    err_text = err.decode("utf-8", errors="replace")
    if p.returncode != 0:
        return f"❌ 拉 issue #{issue_number} 失败: {err_text}"
    import json
    issue = json.loads(out_text)
    title = issue.get("title", "")
    body = issue.get("body", "")
    truths = extract_business_truths(body)
    template_name = match_template(title, body)
    template = load_template(template_name) if template_name else None

    output = []
    output.append(f"## 🤖 军师反推 — Case 草稿（issue #{issue_number}）")
    output.append("")
    if template_name:
        output.append(f"**匹配模板**：`{template_name}`（红牌: {template.get('red_flags', [])}）")
    else:
        output.append("**未匹配到模板**，按业务真值通用反推")
    output.append(f"**业务真值数**：{len(truths)}")
    output.append("")
    output.append("---")
    output.append("")
    output.append("### L2 单测草稿")
    output.append(draft_l2_cases(truths, template))
    output.append("")
    output.append("---")
    output.append("")
    output.append("### L3 E2E Web 草稿")
    output.append(draft_l3_cases(template))
    output.append("")
    output.append("---")
    output.append("")
    output.append("### L4 业务断言草稿（独立路径）")
    output.append(draft_l4_asserts(truths, template))
    output.append("")
    output.append("---")
    output.append("")
    output.append("## 研发 review 流程")
    output.append("- ✅ 同意 → 写代码 + 提交 case")
    output.append("- ❌ 不同意 → 评论 \"X case 不合理，原因是 [Y]\"")
    output.append("- ➕ 补 case → 直接加进 issue")
    output.append("")
    output.append("—— 军师（自动反推，请研发 review）")

    draft = "\n".join(output)
    if dry_run:
        return draft
    # 实际发到 issue
    p = subprocess.Popen(
        ["gh", "issue", "comment", str(issue_number), "--body", draft],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/opt/youke"
    )
    out, err = p.communicate()
    err_text = err.decode("utf-8", errors="replace")
    if p.returncode != 0:
        return f"❌ 评论失败: {err_text}"
    return f"✅ 已发到 issue #{issue_number}\n\n{draft}"


def main():
    parser = argparse.ArgumentParser(description="反推 issue 的 case 草稿")
    parser.add_argument("issue_number", type=int, help="issue 编号")
    parser.add_argument("--dry-run", action="store_true", help="只输出，不发评论")
    args = parser.parse_args()
    print(generate_draft(args.issue_number, args.dry_run))


if __name__ == "__main__":
    main()
