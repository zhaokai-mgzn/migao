#!/usr/bin/env python3
"""
render_cases.py — 用例契约渲染器（case-contract 单一源的两端）

输入 : cases/*.yml（唯一行为用例源，schema 见 design/16-case-contract.md）
输出 :
  1. eval_cases.py              — 生成物，供 local_runner.py 导入（兼容期）
  2. mibao-verification-cases.md — 生成物，人读 casebook

★ 生成物禁止手改：改用例 → 改 cases/*.yml → 重新渲染。
  头部均有 GENERATED 标记；与源不一致时以 cases/*.yml 为准。

用法:
  python3 render_cases.py --cases seed/migao/cases \
      --out-eval tests/agent_eval/eval_cases.py \
      --out-md docs/testing/mibao-verification-cases.md
"""
import argparse
import os
import re
import sys

GENERATED_HEADER = "# GENERATED FILE — DO NOT EDIT\n" \
                   "# 源: cases/*.yml（case-contract 单一源）\n" \
                   "# 重新生成: python3 render_cases.py --cases <dir> --out-eval <py> --out-md <md>\n"

# 域 → 旧 eval_cases Skill 枚举（生成物兼容 local_runner 的导入面）
SKILL_MAP = {
    "order": "ORDER",
    "product": "PRODUCT",
    "processing": "PRODUCT",
    "category": "PRODUCT",
    "aftersales": "AFTERSALES",
    "customer": "CUSTOMER",
    "cross": "CROSS",
    "chat": "MULTI_TURN",
    "defense": "GENERAL",
    "hr": "GENERAL",
    "settings": "GENERAL",
    "data": "GENERAL",
}

TIER_MAP = {"smoke": "SMOKE", "normal": "NORMAL", "edge": "EDGE", "adversarial": "ADVERSARIAL"}

DOMAIN_TITLES = {
    "order": "订单域", "product": "商品域", "processing": "加工项域", "category": "分类域",
    "aftersales": "售后域", "customer": "客户域", "hr": "人事域", "settings": "设置域",
    "data": "数据域", "chat": "对话边界域", "cross": "跨域", "defense": "防御域",
}


def _yaml():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.join(here, "..", "qa"), os.path.join(here, "..", "..", ".github")):
        if d not in sys.path:
            sys.path.insert(0, d)
    from yaml_light import load_file
    return load_file


def load_case_dicts(cases_dir):
    """读 cases/*.yml → [case_dict]，每个 dict 附带 _file 域名。"""
    load_file = _yaml()
    cases = []
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        domain = fn[:-4]
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("cases") or []:
            c = dict(c)
            c["_domain"] = domain
            cases.append(c)
    return cases


def filter_by_persona(cases, persona: str):
    """按归属 agent 过滤用例（issue #2855）。

    persona 字段取值：mibao / xiaobu / ""(缺省=双端)。
    - 跑 mibao 时：跳过 persona=="xiaobu" 的用例（C 端专属，B 端必挂）
    - 跑 xiaobu 时：跳过 persona=="mibao" 的用例（B 端专属，C 端必挂）
    - persona 为空/其它：双端都跑（向后兼容）
    """
    persona = (persona or "").strip().lower()
    if persona not in ("mibao", "xiaobu"):
        return list(cases)
    # 跑 mibao 排除 xiaobu 专属；跑 xiaobu 排除 mibao 专属；未标记(both)双端保留
    other = "xiaobu" if persona == "mibao" else "mibao"

    def _p(c):
        v = c.get("persona") if isinstance(c, dict) else getattr(c, "persona", "")
        return (v or "").strip().lower()

    return [c for c in cases if _p(c) != other]


# ── 期望断言 → 旧 eval 的字符串形态 ──

def exp_to_str(e):
    if isinstance(e, str):
        return e
    tool = e.get("tool", "")
    args = e.get("args") or {}
    if not args:
        return tool
    parts = []
    for k, v in args.items():
        if isinstance(v, list):
            parts.append(f"{k}=[{', '.join(str(x) for x in v)}]")
        else:
            parts.append(f"{k}={v}")
    return f"{tool}({', '.join(parts)})"


def _py_repr(s):
    if not isinstance(s, str):
        return repr(s)
    # 优先用双引号（eval 原文风格），含双引号时用单引号
    if '"' in s and "'" not in s:
        return "'" + s + "'"
    if "'" in s and '"' not in s:
        return '"' + s + '"'
    return repr(s)


def to_eval_py(cases):
    """cases → eval_cases.py 文本（与旧 eval_cases.py 同一导入面）。"""
    out = [GENERATED_HEADER, "",
           "from dataclasses import dataclass, field",
           "from typing import List, Optional",
           "from enum import Enum",
           "", "",
           "class Difficulty(Enum):",
           '    SMOKE = "smoke"       # 冒烟，必须 100% 通过',
           '    NORMAL = "normal"     # 正常流程',
           '    EDGE = "edge"         # 边缘情况',
           '    ADVERSARIAL = "adversarial"  # 对抗性，弱 LLM 可能挂',
           "", "",
           "class Skill(Enum):",
           '    PRODUCT = "product"',
           '    ORDER = "order"',
           '    AFTERSALES = "aftersales"',
           '    CUSTOMER = "customer"',
           '    CROSS = "cross"',
           '    MULTI_TURN = "multi_turn"',
           '    GENERAL = "general"',
           "", "",
           "@dataclass",
           "class EvalCase:",
           "    id: str",
           "    title: str",
           "    skill: Skill",
           "    difficulty: Difficulty",
           "    # 每轮可为 str（纯文本）或 dict（{text, images[]} 带图消息，issue #2794）",
           "    user_inputs: List[str]",
           "    expectations: List[str]",
           '    data_checks: List[str]',
           '    skip_reason: str = ""',
           '    legacy_id: str = ""',
           "    tags: List[str] = field(default_factory=list)",
           '    persona: str = ""   # 归属 agent: mibao / xiaobu / ""(双端)，issue #2855',
           "", ""]

    for c in cases:
        cid = c.get("id", "")
        skill = SKILL_MAP.get(c.get("_domain", ""), "GENERAL")
        tier = TIER_MAP.get(c.get("tier", "normal"), "NORMAL")
        out.append(f"# ── {cid} [{tier}] {c.get('title', '')}（源: cases/{c.get('_domain')}.yml）──")
        out.append(f'_CASE_{c.get("id", "?").replace("-", "_")} = EvalCase(')
        out.append(f"    id={_py_repr(cid)},")
        out.append(f"    legacy_id={_py_repr(c.get('legacy_id', ''))},")
        out.append(f"    title={_py_repr(c.get('title', ''))},")
        out.append(f"    skill=Skill.{skill},")
        out.append(f"    difficulty=Difficulty.{tier},")
        out.append(f"    user_inputs={c.get('user_inputs') or []!r},")
        exps = [exp_to_str(e) for e in (c.get("expectations") or [])]
        out.append(f"    expectations={exps!r},")
        out.append(f"    data_checks={c.get('data_checks') or []!r},")
        out.append(f"    skip_reason={_py_repr(c.get('skip_reason', ''))},")
        out.append(f"    tags={c.get('tags') or []!r},")
        out.append(f"    persona={_py_repr(c.get('persona', ''))},")
        out.append(")")
        out.append("")

    refs = ", ".join(f'_CASE_{c.get("id", "?").replace("-", "_")}' for c in cases)
    out.append("ALL_CASES = (")
    for c in cases:
        out.append(f"    _CASE_{c.get('id', '?').replace('-', '_')},")
    out.append(")")
    out.append("")
    out.append("def get_active_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if not c.skip_reason]")
    out.append("")
    out.append("def get_smoke_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if c.difficulty == Difficulty.SMOKE and not c.skip_reason]")
    out.append("")
    out.append("def get_adversarial_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]")
    out.append("")
    out.append("def print_summary():")
    out.append("    active = get_active_cases()")
    out.append('    print(f"评测用例总数: {len(active)} (跳过 {len(ALL_CASES) - len(active)})")')
    out.append('    print(f"  冒烟: {len(get_smoke_cases())}")')
    out.append('    print(f"  正常: {len([c for c in active if c.difficulty == Difficulty.NORMAL])}")')
    out.append('    print(f"  对抗: {len(get_adversarial_cases())}")')
    out.append('    for skill in Skill:')
    out.append('        cs = [c for c in active if c.skill == skill]')
    out.append("        if cs:")
    out.append('            print(f"\\n## {skill.value}")')
    out.append("            for c in cs:")
    out.append('                print(f"  [{c.difficulty.value.upper():4}] {c.id}: {c.title}")')
    out.append("")
    out.append('if __name__ == "__main__":')
    out.append("    print_summary()")
    return "\n".join(out) + "\n"


def to_md(cases):
    """cases → mibao-verification-cases.md 人读 casebook。"""
    by_domain = {}
    for c in cases:
        by_domain.setdefault(c["_domain"], []).append(c)

    lines = [
        "# 米宝 B端 全覆盖验证 Case（生成物）",
        "",
        "> ⚠️ 本文件由 `render_cases.py` 从 `cases/*.yml` 生成，禁止手改。",
        "> 单一源：`ershen/seed/migao/cases/`（部署副本 `.github/cases/`）。",
        "> 启动服务后按序执行；每轮 Case 独立。tier：🟢 smoke / 🔵 normal / 🔴 adversarial。",
        "",
    ]
    icons = {"smoke": "🟢", "normal": "🔵", "edge": "🟡", "adversarial": "🔴"}

    for domain in sorted(by_domain):
        lines.append(f"## {DOMAIN_TITLES.get(domain, domain)}（{len(by_domain[domain])} case）")
        lines.append("")
        for c in by_domain[domain]:
            icon = icons.get(c.get("tier", "normal"), "⚪")
            lines.append(f"### {c['id']}. {c['title']} {icon}")
            lines.append("```")
            for msg in c.get("user_inputs") or []:
                if isinstance(msg, dict):
                    # 带图消息：文本 + 图片数（issue #2794）
                    _t = msg.get("text", "")
                    _imgs = msg.get("images") or []
                    lines.append(f"你: {_t} [📷 附 {len(_imgs)} 图]" if _t else f"你: [📷 纯图片 x{len(_imgs)}]")
                else:
                    lines.append(f"你: {msg}")
            for e in (c.get("expectations") or []):
                lines.append(f"期望: {exp_to_str(e)}")
            for d in (c.get("data_checks") or []):
                lines.append(f"数据: {d}")
            if c.get("skip_reason"):
                lines.append(f"跳过: {c['skip_reason']}")
            lines.append("```")
            if c.get("truths_ref"):
                lines.append(f"真值: {', '.join(c['truths_ref'])}")
            elif c.get("merge_log") and "缺口" in str(c.get("merge_log", "")):
                lines.append("真值: ⚠️ 缺口（见对应模板 ⚠️ 注释）")
            lines.append(f"溯源: {c.get('merge_log', '')} ｜ tags: {', '.join(c.get('tags') or [])}")
            lines.append("")

    # 覆盖统计
    from collections import Counter
    tier_cnt = Counter(c.get("tier", "normal") for c in cases)
    active = [c for c in cases if not c.get("skip_reason")]
    lines.append("---")
    lines.append("")
    lines.append("## 覆盖统计（生成）")
    lines.append("")
    lines.append(f"- 用例总数：{len(cases)}（活跃 {len(active)}，跳过 {len(cases) - len(active)}）")
    lines.append(f"- tier 分布：smoke {tier_cnt.get('smoke', 0)} / normal {tier_cnt.get('normal', 0)} / adversarial {tier_cnt.get('adversarial', 0)}")
    for domain in sorted(by_domain):
        lines.append(f"- {DOMAIN_TITLES.get(domain, domain)}：{len(by_domain[domain])}")
    gaps = [c for c in cases if not c.get("truths_ref")]
    if gaps:
        lines.append("")
        lines.append("### 真值缺口用例（truths_ref 为空，已在模板 ⚠️ 注释标注）")
        for c in gaps:
            lines.append(f"- {c['id']}: {c.get('title', '')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="case-contract 渲染器（YAML → eval_cases.py + casebook）")
    p.add_argument("--cases", required=True, help="用例库目录（cases/*.yml）")
    p.add_argument("--out-eval", required=True, help="eval_cases.py 输出路径")
    p.add_argument("--out-md", required=True, help="mibao-verification-cases.md 输出路径")
    args = p.parse_args(argv)

    cases = load_case_dicts(args.cases)
    if not cases:
        print(f"❌ {args.cases} 下无用例文件", file=sys.stderr)
        return 1

    py = to_eval_py(cases)
    with open(args.out_eval, "w", encoding="utf-8") as f:
        f.write(py)
    print(f"✓ eval_cases.py → {args.out_eval}（{len(cases)} 条）")

    md = to_md(cases)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ casebook → {args.out_md}（{len(cases)} 条）")

    # 自检：生成物可导入（防渲染出语法错误）
    ns = {}
    exec(compile(py, "<generated eval_cases.py>", "exec"), ns)
    assert len(ns["ALL_CASES"]) == len(cases), "ALL_CASES 数量与源不一致"
    assert ns["get_smoke_cases"]() and ns["get_adversarial_cases"](), "冒烟/对抗子集为空"
    print(f"✓ 生成物自检通过（ALL_CASES={len(ns['ALL_CASES'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
