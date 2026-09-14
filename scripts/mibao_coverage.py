#!/usr/bin/env python3
"""
B 端米宝评测覆盖体检（issue #3555）—— C 端 `xiaobu_coverage.py` 的对称面。

**背景**：C 端自 #3266 起有覆盖体检（哪个能力没被测），B 端一直没有 —— `scripts/`
里只有 `xiaobu_coverage.py`，于是 B 端的工具覆盖缺口只能靠**真实 LLM 全量复测**撞出来
（工具存在但用例从未断言它 → 全量每轮都不测它，却没人知道）。本脚本把 B 端缺口显式化。

**复用既有契约，不复制平行实现**（口径漂移是这类脚本的头号失效方式）：
  · 用例选择 → `eval_case_filter.select_cases_for_persona`（= `filter_by_persona(mibao)`
    去 skip，与 B 端用例边界守卫 `test_mibao_case_invariants._bend_runnable_cases` 同口径）；
  · B 端工具集 → `eval_case_filter.mibao_real_toolset()`（skill 源码解析真值，
    与 `TestMibaoToolsetTruth` 同一实现）；
  · 判据/矩阵/薄覆盖 → `scripts/case_coverage.py`（C 端同一份）。
一致性由 `tests/unit_ci_workflows/test_mibao_case_invariants.py::TestMibaoCoverageReport`
锁定（用例集 / 工具集必须逐字一致）。

用法（仓根）：
  python3 scripts/mibao_coverage.py            # 覆盖矩阵（人读）
  python3 scripts/mibao_coverage.py --check    # 门禁：结构性缺失 → exit 1
  python3 scripts/mibao_coverage.py --md       # Markdown（供文档引用）

`--check` 失败条件（结构性缺失，与 C 端同判据）：
  · B 端用例集为空；
  · 孤儿用例（期望工具 B 端没有 → 用例挂错端）；
  · 断言了两端注册表都没有的工具（拼错/已删除）；
  · 工具 0 用例；**已覆盖但没有任何正向用例**；
  · 工具集解析低于下界（防体检静默失效：解析不到工具 = 假绿）。
"仅 1 条用例"（厚度不足）**只报告不阻塞** —— 与 verify-all.sh:66-68 的活指标设计意图一致。
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_case_filter as lr  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402
from case_coverage import (  # noqa: E402
    BASELINE_PATH, PERSONA_LABELS, _attach_baseline, build_coverage_report,
    case_title, load_baseline, render_action_gaps, render_baseline_worklist, tool_label,
)

CASES_DIR = REPO_ROOT / ".github" / "cases"
PERSONA = "mibao"

# 显式豁免：确认无法用链路级用例覆盖的 B 端工具（必须写明理由）。
# **当前为空**：缺口必须被看见（豁免会掩盖回归，见 C 端同类注释与 migao-dev-flow §14.5）。
COVERAGE_EXEMPT: dict = {}


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


def sanity_errors() -> list:
    """体检自身的失效防线：解析口径坏了必须报错，而不是给出一张假绿的矩阵。"""
    errors = []
    tools = lr.mibao_real_toolset()
    broken = lr.skill_files_without_tools()
    if broken:
        errors.append(f"以下米宝 skill 解析不出任何工具（文件改名/解析口径漂移）: {broken}")
    if lr.toolset_below_floor(tools):
        errors.append(
            f"B 端工具集只解析到 {len(tools)} 个 < 下界 {lr.MIBAO_TOOLSET_MIN}"
            f"（新增能力后请上调 eval_case_filter.MIBAO_TOOLSET_MIN）"
        )
    return errors


def render_text(rep, cases, by_tier) -> str:
    out = []
    out.append("=" * 68)
    out.append(f"  {PERSONA_LABELS[PERSONA]}评测覆盖体检（issue #3555）")
    out.append("=" * 68)
    out.append(f"用例源: {CASES_DIR.relative_to(REPO_ROOT)}（{len(cases)} 条）")
    out.append(f"B 端用例集: {rep.cases_run} 条（persona 归属后；skip 的不计）")
    out.append(f"工具覆盖: {rep.covered}/{len(rep.tools)}"
               f"（{'✅ 全覆盖' if not rep.uncovered else '⚠️ 缺口 ' + str(len(rep.uncovered)) + ' 个'}）")
    out.append("")

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
        out.append(f"  {mark} {t:32} {tool_label(PERSONA, t):24} {len(ids):2} 条"
                   f"（正向 {len(pos)}）  {', '.join(ids[:6])}"
                   + (" …" if len(ids) > 6 else "") + flag)
    out.append("")

    out.append("── ② 用例归属（按 tier）──")
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out.append(f"  [{tier}] {len(lst)} 条")
        for c in lst:
            out.append(f"     {c['id']:8} {case_title(c)[:52]}")
    out.append("")

    if rep.orphan_cases or rep.dangling_cases:
        out.append("── ③ 端点错配 / 未知工具（--check 拦截）❌ ──")
        for cid, tools in rep.orphan_cases:
            out.append(f"  ❌ {cid}: 期望工具 B 端没有 → {tools}（改 persona 或加 OR 分支）")
        for cid, tools in rep.dangling_cases:
            out.append(f"  ❌ {cid}: 断言了两端都没有的工具 → {tools}（拼错/已删除）")
        out.append("")

    if rep.missing_positive:
        out.append("── ④ 缺正向用例（结构性缺失，--check 拦截）❌ ──")
        for t, ids in sorted(rep.missing_positive.items()):
            out.append(f"  ❌ {t:32} {tool_label(PERSONA, t)}")
            out.append(f"     现仅被断言: {', '.join(ids)}（都是拒绝/不调用式）")
        out.append("")
    if rep.uncovered:
        out.append("── ④ 零覆盖工具（--check 拦截）❌ ──")
        for t in rep.uncovered:
            tag = "ⓘ 显式豁免" if t in rep.exempt else "❌"
            out.append(f"  {tag} {t:32} {tool_label(PERSONA, t)}")
        out.append("")
        out.append("  填补方式：按 migao-dev-flow §14.1/§14.5 在对应域 cases/*.yml 新增用例，")
        out.append("  跑 render_cases.py 提交生成物；本清单一经输出即可当补用例任务书。")
        out.append("")
    if rep.thin_tools:
        out.append("── ⑤ 薄覆盖（仅 1 条用例，只报告不阻塞）⚠️ ──")
        for t in rep.thin_tools:
            out.append(f"  ⚠️  {t:32} {tool_label(PERSONA, t):24} 仅 {', '.join(rep.cases[t])}")
        out.append("")
        out.append("  说明：厚度不足是随迭代收敛的活指标（verify-all.sh:66-68 的设计意图：")
        out.append("  不硬编码缺口阈值制造返工式门禁）—— 报告它，不拦它。")
    if rep.exempt:
        out.append("")
        out.append("── 显式豁免（非缺口）──")
        for t, reason in sorted(rep.exempt.items()):
            out.append(f"  ⓘ  {t:32} {reason}")
    out.append(render_action_gaps(rep, PERSONA_LABELS[PERSONA]))
    return "\n".join(out)


def render_md(rep, by_tier) -> str:
    total = len(rep.tools)
    out = ["# B 端米宝评测覆盖矩阵", "",
           "> 生成物（`scripts/mibao_coverage.py --md` 渲染，禁止手改）。"
           "单一源 `.github/cases/`。", "",
           f"- B 端用例集：**{rep.cases_run} 条**（mibao 归属，skip 不计）",
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
        out.append(f"| {mark} `{t}` | {tool_label(PERSONA, t)} | {len(ids)} | {len(pos)} | "
                   f"{', '.join(ids) if ids else '**缺口**'} | {note} |")
    out += ["", "## ② 用例归属（按 tier）", ""]
    for tier in ["smoke", "normal", "edge", "adversarial"]:
        lst = by_tier.get(tier) or []
        if not lst:
            continue
        out += [f"### {tier}（{len(lst)} 条）", "", "| 用例 | 标题 |", "|---|---|"]
        for c in lst:
            out.append(f"| {c['id']} | {case_title(c)} |")
        out.append("")
    if rep.uncovered:
        out += ["## ③ 零覆盖工具（`--check` 拦截）", "", "| 工具 | 能力 |", "|---|---|"]
        for t in rep.uncovered:
            out.append(f"| `{t}` | {tool_label(PERSONA, t)} |")
        out.append("")
    if rep.missing_positive:
        out += ["## ④ 缺正向用例（`--check` 拦截）", "",
                "| 工具 | 能力 | 现仅被断言的用例 |", "|---|---|---|"]
        for t, ids in sorted(rep.missing_positive.items()):
            out.append(f"| `{t}` | {tool_label(PERSONA, t)} | {', '.join(ids)} |")
        out.append("")
    if rep.thin_tools:
        out += ["## ⑤ 薄覆盖（仅 1 条用例，只报告不阻塞）", "",
                "| 工具 | 能力 | 唯一用例 |", "|---|---|---|"]
        for t in rep.thin_tools:
            out.append(f"| `{t}` | {tool_label(PERSONA, t)} | {', '.join(rep.cases[t])} |")
        out.append("")
    if rep.orphan_cases:
        out += ["## ⑥ 端点错配用例", "", "| 用例 | B 端没有的工具 |", "|---|---|"]
        for cid, tools in rep.orphan_cases:
            out.append(f"| {cid} | {', '.join(tools)} |")
        out.append("")
    out.append(render_action_gaps(rep, PERSONA_LABELS[PERSONA], md=True))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="门禁模式：结构性缺失（孤儿/零覆盖/缺正向/空用例集/解析失效）→ exit 1")
    ap.add_argument("--md", action="store_true", help="输出 Markdown")
    ap.add_argument("--baseline", default=None,
                    help=f"存量豁免清单（默认 {BASELINE_PATH.name}）—— 只豁免已登记的存量缺口")
    ap.add_argument("--strict-gaps", action="store_true",
                    help="忽略存量豁免（用于验证判据本身：所有结构性缺口都必须阻塞）")
    args = ap.parse_args()

    fatal = sanity_errors()
    if fatal:
        print("❌ B 端覆盖体检无法可信执行：", file=sys.stderr)
        for e in fatal:
            print(f"   - {e}", file=sys.stderr)
        return 1

    rep = build_report()
    if args.check:
        if args.strict_gaps:
            print(f"  （--strict-gaps：忽略 {BASELINE_PATH.name} 的存量豁免）", file=sys.stderr)
        else:
            try:
                _attach_baseline(rep, load_baseline(args.baseline, "mibao", rep.tools))
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
        if problems:
            print("\n❌ B 端覆盖体检未通过：", file=sys.stderr)
            for p in problems:
                print(f"   - {p}", file=sys.stderr)
            print("   补用例触发条件见 migao-dev-flow §14.5；判据实现见 scripts/case_coverage.py",
                  file=sys.stderr)
            return 1
        print("\n✅ B 端覆盖体检通过")
        if rep.thin_tools:
            print(f"   ⚠️ 薄覆盖（只报告，不阻塞）{len(rep.thin_tools)} 个: "
                  f"{', '.join(rep.thin_tools)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
