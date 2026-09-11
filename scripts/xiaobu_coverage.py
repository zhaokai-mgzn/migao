#!/usr/bin/env python3
"""
C 端小布评测覆盖体检（issue #3266）。

参考 B 端方法论：把「用例库实际覆盖了哪些能力」显式化，缺口列出来而不是
靠"看起来有覆盖"。B 端有 docs/testing/mibao-verification-cases.md 做用例清单，
但那是渲染生成物、不回答"哪个工具没被测"；本脚本回答后者。

用法（仓根）：
  python3 scripts/xiaobu_coverage.py                 # 打印覆盖矩阵（人读）
  python3 scripts/xiaobu_coverage.py --check         # CI 门禁：有用例的工具 < 阈值或有孤儿用例则 exit 1
  python3 scripts/xiaobu_coverage.py --md            # 输出 Markdown（供文档引用）
  python3 scripts/xiaobu_coverage.py --min-tools 5   # 断言至少 N 个工具被覆盖

输出三张表：
  ① 工具覆盖矩阵：C 端每个工具 ← 哪些用例覆盖（缺口标 ⚠️）
  ② 用例归属清单：PERSONA=xiaobu 实际会跑哪些用例（按 tier 分组）
  ③ 孤儿用例：声明 persona: xiaobu 但工具不在小布工具集内（配置错误防线）
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

if sys.version_info < (3, 10):
    sys.exit(
        "❌ 本脚本需 Python ≥3.10（复用 local_runner，其类型标注用了 `X | None`）。\n"
        "   请用项目 venv 运行：\n"
        "     backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py\n"
        "   （macOS 自带 python3 为 3.9，在此提前失败而非抛 SyntaxError/TypeError）"
    )

from render_cases import load_case_dicts  # noqa: E402
import local_runner as lr  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

# 工具 → 人读能力标签（缺口报告可读性）
TOOL_LABELS = {
    "customer_order_query": "查本人订单",
    "customer_logistics_track": "查物流（仅本人已发货）",
    "customer_address_query": "查收货地址",
    "order_create": "下单创建",
    "product_search": "商品搜索",
    "product_detail": "商品详情",
    "curtain_calc": "窗帘算料报价",
    "aftersale_query": "售后工单查询",
    "aftersale_create": "售后工单创建",
    "knowledge_search": "知识问答（本店知识库）",
    "human_handoff": "转人工",
    "interact": "交互卡片（choice/form/confirm）",
    "validate_input": "写操作前置校验",
}

# 显式豁免：已有用例但因客观原因 skip（不是覆盖缺口，禁止当缺口处理）
# 依据 acceptance-protocol §1.3「关键行为禁止只写进自然语义 data_checks」的反面——
# 豁免必须显式声明理由，不得靠"看起来有覆盖"。
COVERAGE_EXEMPT = {
    "customer_address_query": (
        "CH-025 已覆盖（下单地址自动填充），但 case 声明 skip_reason："
        "agent-eval 无稳定历史订单数据 → 由 pytest tests/test_customer_address_query.py 验证"
    ),
}


def build_report():
    cases = load_case_dicts(str(CASES_DIR))
    selected = lr.select_cases_for_persona(cases, "xiaobu")
    selected_ids = {c["id"] for c in selected}

    # ① 工具 → 覆盖用例
    coverage = {t: [] for t in sorted(lr.XIAOBU_TOOLS)}
    for c in selected:
        for t in lr._case_expectation_tools(c):
            if t in coverage:
                coverage[t].append(c["id"])
            else:
                coverage.setdefault(t, []).append(c["id"])

    # ② 按 tier 分组
    by_tier = {}
    for c in selected:
        by_tier.setdefault(c.get("tier", "normal"), []).append(c)

    # ③ 孤儿：声明 xiaobu 但工具超出小布能力
    orphans = []
    for c in cases:
        if (c.get("persona") or "").strip().lower() != "xiaobu":
            continue
        if (c.get("skip_reason") or "").strip():
            continue          # skip_reason 声明了不跑，不算孤儿
        extra = lr._case_expectation_tools(c) - lr.XIAOBU_TOOLS
        if extra:
            orphans.append((c["id"], sorted(extra)))

    no_case_tools = sorted(t for t in lr.XIAOBU_TOOLS if not coverage.get(t))
    uncovered = [t for t in no_case_tools if t not in COVERAGE_EXEMPT]
    exempted = [t for t in no_case_tools if t in COVERAGE_EXEMPT]
    return coverage, by_tier, uncovered, orphans, selected, cases, exempted


def render_text(coverage, by_tier, uncovered, orphans, selected, cases, exempted):
    out = []
    total_tools = len(lr.XIAOBU_TOOLS)
    covered = total_tools - len(uncovered)
    out.append("=" * 68)
    out.append("  C 端小布评测覆盖体检（issue #3266）")
    out.append("=" * 68)
    out.append(f"用例源: {CASES_DIR.relative_to(REPO_ROOT)}（{len(cases)} 条）")
    out.append(f"C 端用例集: {len(selected)} 条（persona 归属 + 工具能力过滤后）")
    out.append(f"工具覆盖: {covered}/{total_tools}"
               f"（{'✅ 全覆盖' if not uncovered else '⚠️ 缺口 ' + str(len(uncovered)) + ' 个'}）")
    out.append("")

    out.append("── ① 工具覆盖矩阵 ──")
    for t in sorted(lr.XIAOBU_TOOLS):
        ids = coverage.get(t) or []
        label = TOOL_LABELS.get(t, "")
        mark = "✅" if ids else "⚠️ "
        out.append(f"  {mark} {t:26} {label:22} {len(ids):2} 条  {', '.join(ids[:6])}"
                   + (" …" if len(ids) > 6 else ""))
    out.append("")

    out.append("── ② 用例归属（按 tier）──")
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out.append(f"  [{tier}] {len(lst)} 条")
        for c in lst:
            out.append(f"     {c['id']:8} {c['title'][:52]}")
    out.append("")

    if orphans:
        out.append("── ③ 孤儿用例（声明 xiaobu 但断言了非小布工具）⚠️ ──")
        for cid, extra in orphans:
            out.append(f"  {cid}: {extra}")
        out.append("")

    if uncovered:
        out.append("── 缺口清单（无任何用例覆盖的工具）──")
        for t in uncovered:
            out.append(f"  ⚠️  {t:26} {TOOL_LABELS.get(t, '')}")
        out.append("")
        out.append("  填补方式：按 migao-dev-flow §14.1 在对应域 cases/*.yml 新增用例，")
        out.append("  声明 persona: xiaobu + tier，并跑 render_cases.py 提交生成物。")

    if exempted:
        out.append("")
        out.append("── 显式豁免（有用例但声明 skip_reason，非缺口）──")
        for t in exempted:
            out.append(f"  ⓘ  {t:26} {COVERAGE_EXEMPT[t]}")
    return "\n".join(out)


def render_md(coverage, by_tier, uncovered, orphans, selected, cases, exempted):
    total_tools = len(lr.XIAOBU_TOOLS)
    covered = total_tools - len(uncovered)
    out = ["# C 端小布评测覆盖矩阵", "",
           f"> 生成物（`scripts/xiaobu_coverage.py --md` 渲染，禁止手改）。"
           f"单一源 `.github/cases/`。", "",
           f"- C 端用例集：**{len(selected)} 条**（persona 归属 + 工具能力过滤后）",
           f"- 工具覆盖：**{covered}/{total_tools}**"
           + ("（全覆盖）" if not uncovered else f"（缺口 {len(uncovered)} 个）"),
           "", "## ① 工具覆盖矩阵", "",
           "| 工具 | 能力 | 覆盖用例数 | 用例 |", "|---|---|---|---|"]
    for t in sorted(lr.XIAOBU_TOOLS):
        ids = coverage.get(t) or []
        mark = "✅" if ids else "⚠️"
        out.append(f"| {mark} `{t}` | {TOOL_LABELS.get(t, '')} | {len(ids)} | "
                   f"{', '.join(ids) if ids else '**缺口**'} |")
    if exempted:
        out += ["", "### 显式豁免（有用例但 skip_reason，非缺口）", "",
                "| 工具 | 理由 |", "|---|---|"]
        for t in exempted:
            out.append(f"| `{t}` | {COVERAGE_EXEMPT[t]} |")
    out += ["", "## ② 用例归属（按 tier）", ""]
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out += [f"### {tier}（{len(lst)} 条）", "", "| 用例 | 标题 |", "|---|---|"]
        for c in lst:
            out.append(f"| {c['id']} | {c['title']} |")
        out.append("")
    if orphans:
        out += ["## ③ 孤儿用例", "", "| 用例 | 非小布工具 |", "|---|---|"]
        for cid, extra in orphans:
            out.append(f"| {cid} | {', '.join(extra)} |")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="CI 门禁模式：有缺口/孤儿用例/用例集过小 → exit 1")
    ap.add_argument("--md", action="store_true", help="输出 Markdown")
    ap.add_argument("--min-tools", type=int, default=0,
                    help="断言至少 N 个 C 端工具被用例覆盖（--check 时生效）")
    ap.add_argument("--max-uncovered", type=int, default=None,
                    help="允许的最大未覆盖工具数（--check 时生效；缺省不限）")
    args = ap.parse_args()

    coverage, by_tier, uncovered, orphans, selected, cases, exempted = build_report()

    if args.md:
        print(render_md(coverage, by_tier, uncovered, orphans, selected, cases, exempted))
    else:
        print(render_text(coverage, by_tier, uncovered, orphans, selected, cases, exempted))

    if args.check:
        problems = []
        if not selected:
            problems.append("C 端用例集为空（评测假绿）")
        if orphans:
            problems.append(f"{len(orphans)} 条孤儿用例（声明 xiaobu 却断言非小布工具）")
        total = len(lr.XIAOBU_TOOLS)
        if args.min_tools and (total - len(uncovered)) < args.min_tools:
            problems.append(f"工具覆盖 {total - len(uncovered)}/{total} < --min-tools {args.min_tools}")
        if args.max_uncovered is not None and len(uncovered) > args.max_uncovered:
            problems.append(f"未覆盖工具 {len(uncovered)} 个 > --max-uncovered {args.max_uncovered}")
        if problems:
            print("\n❌ 覆盖体检未通过：", file=sys.stderr)
            for p in problems:
                print(f"   - {p}", file=sys.stderr)
            return 1
        print("\n✅ 覆盖体检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
