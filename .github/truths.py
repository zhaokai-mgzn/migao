#!/usr/bin/env python3
"""
truths.py — 业务真值 ID 解析器（case-contract 标准配套，零依赖）

背景：二郎神已有一版 truth-miner 生成的业务真值模板（seed/<client>/templates/*.yml），
case-contract 标准（design/16-case-contract.md）的用例库（cases/*.yml）通过 truths_ref
引用这些真值。引用机制 = 「ID 前缀标注」：每条 business_truths 以 [<模板名>.<短名>] 开头，
字符串形状不变 → verify-agent / check_assert / learn.py 零破坏。

职责：
  1. index  — 打印全量真值索引 {ID: 文本摘要}
  2. check  — 校验用例的 truths_ref 全部可解析（不可解析 → exit 1，CI fail-closed）；
              空 truths_ref 视为「已标注缺口」，仅告警不失败

用法:
  python3 truths.py index --templates seed/migao/templates
  python3 truths.py check --templates seed/migao/templates --cases seed/migao/cases
"""
import argparse
import os
import re
import sys

ID_RE = re.compile(r"^\[([a-z0-9.-]+)\]\s")


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _yaml():
    here = _here()
    for d in (here, os.path.join(here, "..", "qa")):
        if d not in sys.path:
            sys.path.insert(0, d)
    from yaml_light import load_file
    return load_file


def extract_id(text):
    """从 '[id] 文本' 提取 ID，无前缀返回 None。"""
    m = ID_RE.match(str(text))
    return m.group(1) if m else None


def load_truths(template_path):
    """加载单个模板 → (truhs {id: text}, 无 ID 条目数)。"""
    load_file = _yaml()
    data = load_file(template_path)
    truths, unid = {}, 0
    for t in data.get("business_truths") or []:
        tid = extract_id(t)
        if tid:
            truths[tid] = str(t)
        else:
            unid += 1
    return truths, unid


def load_all_truths(templates_dir):
    """加载目录下全部模板 → {id: text}；同 ID 冲突时后写覆盖并记录。"""
    index, conflicts, unid = {}, [], 0
    for fn in sorted(os.listdir(templates_dir)):
        if not fn.endswith(".yml"):
            continue
        truths, u = load_truths(os.path.join(templates_dir, fn))
        unid += u
        for tid, text in truths.items():
            if tid in index:
                conflicts.append(tid)
            index[tid] = text
    return index, conflicts, unid


def check_cases(cases_dir, templates_dir):
    """校验 cases/*.yml 的全部 truths_ref。返回 (report, exit_code)。"""
    index, conflicts, _ = load_all_truths(templates_dir)
    problems, gaps, total_refs = [], 0, 0
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        load_file = _yaml()
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("cases") or []:
            refs = c.get("truths_ref") or []
            if not refs:
                gaps += 1
                problems.append({"case": c.get("id"), "kind": "gap",
                                 "msg": "truths_ref 为空（已标注真值缺口）"})
                continue
            for ref in refs:
                total_refs += 1
                if ref not in index:
                    problems.append({"case": c.get("id"), "kind": "unresolved",
                                     "msg": f"真值 ID 不存在: {ref}"})
    unresolved = [p for p in problems if p["kind"] == "unresolved"]
    report = {
        "template_truths": len(index),
        "truth_conflicts": conflicts,
        "case_refs": total_refs,
        "gap_cases": gaps,
        "problems": problems,
    }
    return report, 1 if (unresolved or conflicts) else 0


def find_case(cases_dir, case_id):
    """按 ID 或 legacy_id 查找用例 → (case, domain) 或 (None, None)。"""
    load_file = _yaml()
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("cases") or []:
            if c.get("id") == case_id or str(c.get("legacy_id", "")) == case_id:
                return c, fn[:-4]
    return None, None


def find_page_case(cases_dir, case_id):
    """按 ID 查找页面用例（page_cases）→ (case, domain) 或 (None, None)。"""
    load_file = _yaml()
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("page_cases") or []:
            if c.get("id") == case_id:
                return c, fn[:-4]
    return None, None


def _print_index(index):
    for tid in sorted(index):
        text = index[tid]
        body = text[len(tid) + 3:]  # 去掉 '[id] ' 前缀
        print(f"{tid}\t{body[:70]}")


def main(argv=None):
    p = argparse.ArgumentParser(description="业务真值 ID 解析器（case-contract 配套）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="打印真值索引")
    pi.add_argument("--templates", required=True)

    pc = sub.add_parser("check", help="校验用例 truths_ref（fail-closed）")
    pc.add_argument("--templates", required=True)
    pc.add_argument("--cases", required=True)

    pf = sub.add_parser("case", help="按 ID 或 legacy_id 查单条用例（issue CONTRACT_JSON cases 校验用）")
    pf.add_argument("case_id")
    pf.add_argument("--cases", required=True)

    pv = sub.add_parser("verdict", help="生成 VERDICT_JSON 的 case_results 脚手架（verify-agent 逐用例打分用）")
    pv.add_argument("--cases", required=True)
    pv.add_argument("--ids", nargs="*", help="用例 ID 列表（issue 声明的 cases）；不提供则全量活跃用例")

    pr = sub.add_parser("render", help="渲染真值投影（truths.json / truths.md / truths.html dashboard）")
    pr.add_argument("--templates", required=True)
    pr.add_argument("--cases", required=True)
    pr.add_argument("--page-specs", default="", help="page-specs 目录（可选，页面真值 P 层）")
    pr.add_argument("--out", required=True, help="输出目录")

    ppc = sub.add_parser("page-case", help="按 ID 查单条页面用例（issue CONTRACT_JSON page_cases 校验用）")
    ppc.add_argument("case_id")
    ppc.add_argument("--cases", required=True)

    pq = sub.add_parser("query", help="按 ID 查单条真值（agent 引用真值/理解业务规则用）")
    pq.add_argument("truth_id")
    pq.add_argument("--templates", required=True)

    ps = sub.add_parser("search", help="按关键字搜真值（ID 或文本，模糊匹配）")
    ps.add_argument("keyword")
    ps.add_argument("--templates", required=True)

    args = p.parse_args(argv)

    if args.cmd == "verdict":
        ids = args.ids
        if not ids:
            load_file = _yaml()
            ids = []
            for fn in sorted(os.listdir(args.cases)):
                if not fn.endswith(".yml"):
                    continue
                for c in load_file(os.path.join(args.cases, fn)).get("cases") or []:
                    if not c.get("skip_reason"):
                        ids.append(c.get("id"))
        scaffold = {"case_results": {}}
        missing = []
        for cid in ids:
            case, _ = find_case(args.cases, cid)
            if case is None:
                missing.append(cid)
                continue
            scaffold["case_results"][cid] = {
                "title": case.get("title", ""),
                "passed": 0,
                "total": len(case.get("expectations") or []),
                "score": 0.0,
                "verdict": "pending",
            }
        import json as _json
        print(_json.dumps(scaffold, ensure_ascii=False, indent=2))
        if missing:
            print(f"⚠️ 不存在的用例 ID: {', '.join(missing)}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "case":
        case, domain = find_case(args.cases, args.case_id)
        if case is None:
            print(f"❌ 用例不存在: {args.case_id}（用例库 {args.cases}）", file=sys.stderr)
            return 1
        print(f"✅ {case.get('id')} [{case.get('tier', 'normal')}] {case.get('title', '')}")
        print(f"   域: {domain} ｜ legacy: {case.get('legacy_id', '-')}")
        print(f"   真值: {', '.join(case.get('truths_ref') or []) or '（缺口）'}")
        return 0

    if args.cmd == "page-case":
        case, domain = find_page_case(args.cases, args.case_id)
        if case is None:
            print(f"❌ 页面用例不存在: {args.case_id}（用例库 {args.cases} 的 page_cases）", file=sys.stderr)
            return 1
        print(f"✅ {case.get('id')} [{case.get('tier', 'normal')}] {case.get('title', '')}")
        print(f"   域: {domain} ｜ spec: {case.get('spec', '-')}")
        return 0

    if args.cmd == "query":
        index, conflicts, _ = load_all_truths(args.templates)
        if args.truth_id in index:
            print(index[args.truth_id])
            return 0
        print(f"❌ 真值不存在: {args.truth_id}（真值库 {args.templates}）", file=sys.stderr)
        return 1

    if args.cmd == "search":
        index, _, _ = load_all_truths(args.templates)
        kw = args.keyword.lower()
        hits = {tid: text for tid, text in index.items() if kw in (tid + text).lower()}
        if hits:
            for tid, text in sorted(hits.items()):
                print(f"{tid}\t{text}")
            return 0
        print(f"无匹配: {args.keyword}", file=sys.stderr)
        return 1

    if args.cmd == "index":
        index, conflicts, unid = load_all_truths(args.templates)
        _print_index(index)
        print(f"\n合计 {len(index)} 条真值；无 ID {unid} 条；冲突 {len(conflicts)} 个")
        return 1 if conflicts else 0

    if args.cmd == "render":
        from junshi.contract_view import render_contract  # 懒加载，避免与 contract_view 的 junshi.truths 引用成环
        from pathlib import Path
        try:
            stats = render_contract(Path(args.templates), Path(args.cases),
                                    Path(args.page_specs) if args.page_specs else None, Path(args.out))
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
        detail = " / ".join(f"{k} {v}" for k, v in stats.items())
        print(f"✅ 已渲染 → {args.out}（{detail}）")
        return 0

    report, code = check_cases(args.cases, args.templates)
    print(f"真值库: {report['template_truths']} 条 | 用例引用: {report['case_refs']} 处 | "
          f"缺口用例: {report['gap_cases']} 个 | 冲突: {len(report['truth_conflicts'])} 个")
    for p in report["problems"]:
        mark = "❌" if p["kind"] == "unresolved" else "⚠️"
        print(f"  {mark} {p['case']}: {p['msg']}")
    if code:
        print("\n❌ 存在不可解析的真值引用（fail-closed）")
    else:
        print("\n✅ 全部用例的 truths_ref 可解析")
    return code


if __name__ == "__main__":
    sys.exit(main())
