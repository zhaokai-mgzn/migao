#!/usr/bin/env python3
"""
C 端小布评测覆盖体检（issue #3266，判据收紧于 #3555）。

参考 B 端方法论：把「用例库实际覆盖了哪些能力」显式化，缺口列出来而不是
靠"看起来有覆盖"。B 端有 docs/testing/mibao-verification-cases.md 做用例清单，
但那是渲染生成物、不回答"哪个工具没被测"；本脚本回答后者。
（B 端对称面 = `scripts/mibao_coverage.py`，二者共用 `scripts/case_coverage.py` 判据。）

用法（仓根）：
  python3 scripts/xiaobu_coverage.py                 # 打印覆盖矩阵（人读）
  python3 scripts/xiaobu_coverage.py --check         # 门禁：结构性缺失 → exit 1（见下）
  python3 scripts/xiaobu_coverage.py --md            # 输出 Markdown（供文档引用）
  python3 scripts/xiaobu_coverage.py --min-tools 5   # 断言至少 N 个工具被覆盖

输出四张表：
  ① 工具覆盖矩阵：C 端每个工具 ← 哪些用例覆盖（缺口标 ⚠️）
  ② 用例归属清单：PERSONA=xiaobu 实际会跑哪些用例（按 tier 分组）
  ③ 孤儿用例：声明 persona: xiaobu 但工具不在小布工具集内（配置错误防线）
  ④ 薄覆盖清单：**缺正向用例**（结构性缺失，--check 拦截）/ **仅 1 条用例**
     （厚度不足，只报告；缺口数是随迭代收敛的活指标，不设硬阈值）

`--check` 的失败条件（只含**结构性缺失**，不含"厚度不足"）：
  · C 端用例集为空；
  · 孤儿用例（用例挂到了错的端）；
  · 断言了两端注册表都没有的工具（拼错/已删除 → 期望永不满足）；
  · 工具 0 用例（旧判据，保留）；
  · **工具只有对抗/拒绝用例、没有任何正向用例**（#3555 新增：把"没有能力证据"
    从"厚度不足"里区分出来 —— 前者是配置完整性，不随迭代收敛）。
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_cases import load_case_dicts  # noqa: E402
import eval_case_filter as lr  # noqa: E402
from case_coverage import (  # noqa: E402
    BASELINE_PATH, PERSONA_LABELS, _attach_baseline, build_coverage_report,
    case_title, load_baseline, render_baseline_worklist, tool_label,
)

CASES_DIR = REPO_ROOT / ".github" / "cases"
PERSONA = "xiaobu"

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
    return build_coverage_report(cases, PERSONA, exempt=COVERAGE_EXEMPT)


def _by_tier(cases, ids) -> dict:
    out: dict = {}
    for c in cases:
        if c["id"] not in ids:
            continue
        out.setdefault(str(c.get("tier") or "normal"), []).append(c)
    return out


def render_text(rep, cases, by_tier) -> str:
    out = []
    out.append("=" * 68)
    out.append(f"  {PERSONA_LABELS[PERSONA]}评测覆盖体检（issue #3266 / 判据 #3555）")
    out.append("=" * 68)
    out.append(f"用例源: {CASES_DIR.relative_to(REPO_ROOT)}（{len(cases)} 条）")
    out.append(f"C 端用例集: {rep.cases_run} 条（persona 归属 + 工具能力过滤后）")
    out.append(f"工具覆盖: {rep.covered}/{len(rep.tools)}"
               f"（{'✅ 全覆盖' if not rep.uncovered else '⚠️ 缺口 ' + str(len(rep.uncovered)) + ' 个'}）")
    out.append("")
    _render_matrix(out, rep, mark_positive=True)
    out.append("")
    _render_by_tier(out, by_tier)
    if rep.orphan_cases:
        out.append("── ③ 孤儿用例（期望工具小布没有）⚠️ ──")
        for cid, extra in rep.orphan_cases:
            out.append(f"  {cid}: {extra}")
        out.append("")
    if rep.dangling_cases:
        out.append("── ③ 用例断言了两端都没有的工具（拼错/已删除）⚠️ ──")
        for cid, extra in rep.dangling_cases:
            out.append(f"  {cid}: {extra}")
        out.append("")
    _render_thin(out, rep)
    return "\n".join(out)


def _render_matrix(out, rep, mark_positive: bool) -> None:
    out.append("── ① 工具覆盖矩阵（正向 = 有非否定断言证明能力可用）──")
    for t in sorted(rep.tools):
        ids = rep.cases.get(t) or []
        pos = rep.positive.get(t) or []
        mark = "✅" if ids else "⚠️ "
        flag = ""
        if ids and not pos:
            flag = "  ❌ 缺正向用例"
        elif len(ids) == 1:
            flag = "  ⚠️ 薄覆盖（仅 1 条）"
        out.append(f"  {mark} {t:26} {tool_label(PERSONA, t):22} {len(ids):2} 条"
                   f"（正向 {len(pos)}）  {', '.join(ids[:6])}"
                   + (" …" if len(ids) > 6 else "") + flag)
    out.append("")


def _render_by_tier(out, by_tier) -> None:
    out.append("── ② 用例归属（按 tier）──")
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out.append(f"  [{tier}] {len(lst)} 条")
        for c in lst:
            out.append(f"     {c['id']:8} {case_title(c)[:52]}")
    out.append("")


def _render_thin(out, rep) -> None:
    """薄覆盖清单 —— 直接当作补用例的任务书（人读）。"""
    if rep.missing_positive:
        out.append("── ④ 缺正向用例（结构性缺失，--check 拦截）❌ ──")
        for t, ids in sorted(rep.missing_positive.items()):
            out.append(f"  ❌ {t:26} {tool_label(PERSONA, t)}")
            out.append(f"     现仅被断言: {', '.join(ids)}（都是拒绝/不调用式，"
                       f"证明不了该工具能力可用）")
        out.append("")
    if rep.thin_tools:
        out.append("── ④ 薄覆盖（仅 1 条用例，只报告不阻塞）⚠️ ──")
        for t in rep.thin_tools:
            out.append(f"  ⚠️  {t:26} {tool_label(PERSONA, t):22} 仅 {', '.join(rep.cases[t])}")
        out.append("")
        out.append("  说明：厚度不足是**随迭代收敛的活指标**（verify-all.sh:66-68 的设计意图：")
        out.append("  不硬编码缺口阈值制造返工式门禁）—— 报告它，但不拦它。")
        out.append("  补用例触发条件见 migao-dev-flow §14.5。")
    if rep.uncovered:
        out.append("── 缺口清单（零用例覆盖，--check 拦截）❌ ──")
        for t in rep.uncovered:
            tag = "ⓘ 显式豁免" if t in rep.exempt else "❌"
            out.append(f"  {tag} {t:26} {tool_label(PERSONA, t)}")
            if t in rep.exempt:
                out.append(f"     {rep.exempt[t]}")
        out.append("")
        out.append("  填补方式：按 migao-dev-flow §14.1/§14.5 在对应域 cases/*.yml 新增用例，")
        out.append("  声明 persona: xiaobu + tier，并跑 render_cases.py 提交生成物。")
    if rep.exempt:
        out.append("")
        out.append("── 显式豁免（非缺口）──")
        for t, reason in sorted(rep.exempt.items()):
            out.append(f"  ⓘ  {t:26} {reason}")


def render_md(rep, by_tier) -> str:
    total = len(rep.tools)
    out = ["# C 端小布评测覆盖矩阵", "",
           "> 生成物（`scripts/xiaobu_coverage.py --md` 渲染，禁止手改）。"
           "单一源 `.github/cases/`。", "",
           f"- C 端用例集：**{rep.cases_run} 条**（persona 归属 + 工具能力过滤后）",
           f"- 工具覆盖：**{rep.covered}/{total}**"
           + ("（全覆盖）" if not rep.uncovered else f"（缺口 {len(rep.uncovered)} 个）"),
           f"- 缺正向用例：**{len(rep.missing_positive)} 个**"
           + ("" if not rep.missing_positive else f"（{'、'.join(sorted(rep.missing_positive))}）"),
           f"- 薄覆盖（仅 1 条用例，只报告）：**{len(rep.thin_tools)} 个**"
           + ("" if not rep.thin_tools else f"（{'、'.join(rep.thin_tools)}）"),
           "", "## ① 工具覆盖矩阵", "",
           "| 工具 | 能力 | 用例数 | 正向 | 用例 | 备注 |", "|---|---|---|---|---|---|"]
    for t in sorted(rep.tools):
        ids = rep.cases.get(t) or []
        pos = rep.positive.get(t) or []
        mark = "✅" if ids else "⚠️"
        note = ""
        if ids and not pos:
            note = "❌ 缺正向用例"
        elif len(ids) == 1:
            note = "⚠️ 薄覆盖"
        if t in rep.exempt:
            note = (note + " " if note else "") + "ⓘ 显式豁免"
        out.append(f"| {mark} `{t}` | {tool_label(PERSONA, t)} | {len(ids)} | {len(pos)} | "
                   f"{', '.join(ids) if ids else '**缺口**'} | {note} |")
    if rep.exempt:
        out += ["", "### 显式豁免（非缺口）", "", "| 工具 | 理由 |", "|---|---|"]
        for t, reason in sorted(rep.exempt.items()):
            out.append(f"| `{t}` | {reason} |")
    out += ["", "## ② 用例归属（按 tier）", ""]
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out += [f"### {tier}（{len(lst)} 条）", "", "| 用例 | 标题 |", "|---|---|"]
        for c in lst:
            out.append(f"| {c['id']} | {case_title(c)} |")
        out.append("")
    if rep.missing_positive:
        out += ["## ③ 缺正向用例（结构性缺失，`--check` 拦截）", "",
                "| 工具 | 能力 | 现仅被断言的用例 |", "|---|---|---|"]
        for t, ids in sorted(rep.missing_positive.items()):
            out.append(f"| `{t}` | {tool_label(PERSONA, t)} | {', '.join(ids)} |")
        out.append("")
    if rep.thin_tools:
        out += ["## ④ 薄覆盖（仅 1 条用例，只报告不阻塞）", "",
                "| 工具 | 能力 | 唯一用例 |", "|---|---|---|"]
        for t in rep.thin_tools:
            out.append(f"| `{t}` | {tool_label(PERSONA, t)} | {', '.join(rep.cases[t])} |")
        out.append("")
    if rep.orphan_cases:
        out += ["## ⑤ 孤儿用例", "", "| 用例 | 非小布工具 |", "|---|---|"]
        for cid, extra in rep.orphan_cases:
            out.append(f"| {cid} | {', '.join(extra)} |")
        out.append("")
    if rep.dangling_cases:
        out += ["## ⑥ 断言了未知工具的用例", "", "| 用例 | 未知工具 |", "|---|---|"]
        for cid, extra in rep.dangling_cases:
            out.append(f"| {cid} | {', '.join(extra)} |")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="门禁模式：结构性缺失（孤儿/零覆盖/缺正向用例/空用例集）→ exit 1")
    ap.add_argument("--md", action="store_true", help="输出 Markdown")
    ap.add_argument("--min-tools", type=int, default=0,
                    help="断言至少 N 个 C 端工具被用例覆盖（--check 时生效）")
    ap.add_argument("--max-uncovered", type=int, default=None,
                    help="允许的最大未覆盖工具数（--check 时生效；缺省不限）")
    ap.add_argument("--baseline", default=None,
                    help=f"存量豁免清单（默认 {BASELINE_PATH.name}）—— 只豁免已登记的存量缺口")
    ap.add_argument("--strict-gaps", action="store_true",
                    help="忽略存量豁免（用于验证判据本身：所有结构性缺口都必须阻塞）")
    args = ap.parse_args()

    rep = build_report()
    if args.check:
        if args.strict_gaps:
            print(f"  （--strict-gaps：忽略 {BASELINE_PATH.name} 的存量豁免）", file=sys.stderr)
        else:
            try:
                _attach_baseline(rep, load_baseline(args.baseline, "xiaobu", rep.tools))
            except ValueError as exc:
                print(f"❌ 覆盖体检无法执行：\n{exc}", file=sys.stderr)
                return 1
    cases = load_case_dicts(str(CASES_DIR))
    by_tier = _by_tier(cases, lr.selected_case_ids(cases, PERSONA))
    if args.md:
        print(render_md(rep, by_tier))
    else:
        print(render_text(rep, cases, by_tier))
    if rep.baseline:
        print("")
        print(render_baseline_worklist(rep, persona_label=PERSONA_LABELS[PERSONA]))

    if args.check:
        problems = rep.check_problems()
        total = len(rep.tools)
        if args.min_tools and rep.covered < args.min_tools:
            problems.append(f"工具覆盖 {rep.covered}/{total} < --min-tools {args.min_tools}")
        if args.max_uncovered is not None and len(rep.uncovered) > args.max_uncovered:
            problems.append(f"未覆盖工具 {len(rep.uncovered)} 个 > --max-uncovered {args.max_uncovered}")
        if problems:
            print("\n❌ 覆盖体检未通过：", file=sys.stderr)
            for p in problems:
                print(f"   - {p}", file=sys.stderr)
            print("   补用例触发条件见 migao-dev-flow §14.5；判据实现见 scripts/case_coverage.py",
                  file=sys.stderr)
            return 1
        print("\n✅ 覆盖体检通过")
        if rep.thin_tools:
            print(f"   ⚠️ 薄覆盖（只报告，不阻塞）{len(rep.thin_tools)} 个: "
                  f"{', '.join(rep.thin_tools)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
