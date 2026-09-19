#!/usr/bin/env python3
"""
truths.py — 业务真值 ID 解析器（case-contract 标准配套，零依赖）

背景：已有一版 truth-miner 生成的业务真值模板（seed/<client>/templates/*.yml），
case-contract 标准（design/16-case-contract.md）的用例库（cases/*.yml）通过 truths_ref
引用这些真值。引用机制 = 「ID 前缀标注」：每条 business_truths 以 [<模板名>.<短名>] 开头，
字符串形状不变 → verify-agent / check_assert / learn.py 零破坏。

职责：
  1. index  — 打印全量真值索引 {ID: 文本摘要}
  2. check  — 校验用例的 truths_ref 全部可解析（不可解析 → exit 1，CI fail-closed）；
              空 truths_ref 视为「已标注缺口」，仅告警不失败
  3. check 同时校验**已否证真值**（issue #4430 / B3）：模板里可用 `retired_truths` 登记
              「被后续 issue 否证」的真值（须写 `retired_by` + `reason`）；被登记的 ID
              **不得**再被 cases 引用、**不得**仍留在 `business_truths`，否则 exit 1
              —— 否则「过期真值」只是**静默**存活（引用完整性校验不看真值内容）

用法:
  python3 truths.py index --templates seed/migao/templates
  python3 truths.py check --templates seed/migao/templates --cases seed/migao/cases
"""
import argparse
import json
import os
import re
import sys

ID_RE = re.compile(r"^\[([a-z0-9.-]+)\]\s")

# 阻塞（exit 1）的问题类型 —— `gap`（truths_ref 为空）**不在**其中：它是「已标注缺口」，
# 按既有口径只告警。`retired*`（issue #4430 / B3）是**否证登记**的三种坏形态，必须阻塞。
BLOCKING_PROBLEM_KINDS = frozenset({"unresolved", "duplicate",
                                    "retired", "retired-meta", "retired-live"})


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


# ── 已否证真值（issue #4430 / B3）────────────────────────────────────────────
# 病根：真值模板只被校验**引用完整性**（cases 的 truths_ref 能不能解析），**不校验真值内容**
# ⇒ 条目被后续 issue 否证后（如 #4371 把「商品 ↔ 加工项」绑定彻底解耦、表已 DROP），
# 模板里的过期条目**静默存活**：没人引用它 = 没人会红（「不会红的断言 = 空断言」同族）。
# ⇒ 用 `retired_truths` 显式登记否证，并给三条**可红**判据（缺任一即 exit 1）：
#   ① 登记必须写 `retired_by`（否证它的 issue 号）与 `reason`（否证依据，写明「什么已不成立」）；
#   ② 被登记的 ID **不得**仍留在 `business_truths`（要么活着、要么否证，不留自相矛盾）；
#   ③ 被登记的 ID **不得**再被 `.github/cases/**` 的 truths_ref 引用。
RETIRED_REQUIRED_KEYS = ("retired_by", "reason")


def load_retired(template_path):
    """加载单个模板的 `retired_truths` → ({id: meta}, 问题列表)。

    形状（与既有模板同风格，yaml_light 可解析的嵌套映射）：

        retired_truths:
          <模板名>.<短名>:
            retired_by: 4371
            reason: "商品 ↔ 加工项绑定已解耦（product_processing_items 已 DROP）"
    """
    load_file = _yaml()
    data = load_file(template_path)
    raw = data.get("retired_truths") or {}
    retired, problems = {}, []
    if not isinstance(raw, dict):
        return retired, [{"id": "-", "msg": "retired_truths 必须是「真值 ID → {retired_by, reason}」映射"}]
    for tid, meta in raw.items():
        meta = meta if isinstance(meta, dict) else {}
        missing = [k for k in RETIRED_REQUIRED_KEYS if not str(meta.get(k) or "").strip()]
        if missing:
            problems.append({
                "id": tid,
                "msg": f"已否证真值缺 {'/'.join(missing)}"
                       "（必须写明否证它的 issue 号与依据，否则「为什么不再成立」无人可查）",
            })
        retired[tid] = meta
    return retired, problems


def load_all_retired(templates_dir):
    """加载目录下全部模板的 `retired_truths` → ({id: meta}, 问题列表)。"""
    index, problems = {}, []
    for fn in sorted(os.listdir(templates_dir)):
        if not fn.endswith(".yml"):
            continue
        retired, probs = load_retired(os.path.join(templates_dir, fn))
        problems.extend(probs)
        for tid, meta in retired.items():
            if tid in index:
                problems.append({"id": tid, "msg": "同一条真值在两个模板里被登记为已否证"})
            index[tid] = meta
    return index, problems


def check_cases(cases_dir, templates_dir):
    """校验 cases/*.yml 的全部 truths_ref。返回 (report, exit_code)。"""
    index, conflicts, _ = load_all_truths(templates_dir)
    retired, retired_meta_problems = load_all_retired(templates_dir)
    problems, gaps, total_refs = [], 0, 0
    seen_ids = {}
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        load_file = _yaml()
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("cases") or []:
            cid = c.get("id")
            if cid:
                if cid in seen_ids:
                    problems.append({"case": cid, "kind": "duplicate",
                                     "msg": f"重复用例 ID（与 {seen_ids[cid]} 冲突，需重编号）"})
                else:
                    seen_ids[cid] = fn
            refs = c.get("truths_ref") or []
            if not refs:
                gaps += 1
                problems.append({"case": c.get("id"), "kind": "gap",
                                 "msg": "truths_ref 为空（已标注真值缺口）"})
                continue
            for ref in refs:
                total_refs += 1
                if ref in retired:
                    meta = retired[ref]
                    problems.append({
                        "case": c.get("id"), "kind": "retired",
                        "msg": f"引用了**已被否证**的真值 {ref}"
                               f"（retired_by #{meta.get('retired_by')}）：{meta.get('reason')}"
                               " —— 请改用现行真值，或先撤回该否证登记",
                    })
                    continue
                if ref not in index:
                    problems.append({"case": c.get("id"), "kind": "unresolved",
                                     "msg": f"真值 ID 不存在: {ref}"})
    # 否证登记自身的完整性（issue #4430 / B3）：缺 retired_by/reason、既否证又活着、两处登记
    for p in retired_meta_problems:
        problems.append({"case": "retired_truths", "kind": "retired-meta",
                         "msg": f"{p['id']}: {p['msg']}"})
    for tid in sorted(retired):
        if tid in index:
            problems.append({
                "case": "retired_truths", "kind": "retired-live",
                "msg": f"真值 {tid} 同时在 business_truths 与 retired_truths 里 —— "
                       "要么活着、要么否证：从 business_truths 删掉它（否则索引/渲染仍把它当真值）",
            })
    unresolved = [p for p in problems if p["kind"] == "unresolved"]
    report = {
        "template_truths": len(index),
        "retired_truths": len(retired),
        "truth_conflicts": conflicts,
        "case_refs": total_refs,
        "gap_cases": gaps,
        "problems": problems,
        "duplicate_ids": [p for p in problems if p["kind"] == "duplicate"],
    }
    duplicates = report["duplicate_ids"]
    blocking = [p for p in problems if p["kind"] in BLOCKING_PROBLEM_KINDS]
    # `conflicts`（同一真值 ID 出现在两个模板）不在 problems 里，但一直是阻塞项 —— 保持原口径。
    return report, 1 if (blocking or conflicts) else 0


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


# ═══════════════════════════════════════════════════════════════
# check-draft — DRAFT_JSON 验证契约校验（验证契约标准化）
# ═══════════════════════════════════════════════════════════════

ALLOWED_VERIFY_METHODS = {
    "api", "get", "post", "put", "delete", "patch",      # HTTP API
    "db", "sql", "psql",                                  # 数据库
    "unit", "vitest", "jest", "pytest", "tsc",            # 单测/类型检查
    "e2e", "playwright", "smoke",                         # 端到端
    "visual", "page_accept", "page", "capture",           # 页面视觉
    "curl", "check_assert", "gate_check", "truths_check", # 断言/工具链
}


def _read_arg(v):
    """支持 '@文件路径' 或内联文本。"""
    if v.startswith("@"):
        with open(v[1:], encoding="utf-8") as f:
            return f.read()
    return v


def _extract_json_block(text):
    """从 '<!-- XXX_JSON { ... } -->' 注释块或纯 JSON 文本提取 JSON 对象。"""
    if not text:
        return None
    text = str(text)
    m = re.search(r"<!--\s*[A-Z_]+_JSON\s*\n?(\{.*\})\n?\s*-->", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def check_draft(draft_text, contract_text=None):
    """校验 DRAFT_JSON 验证契约（fail-closed）：
    ① 粒度 truths_count ≤ 5；
    ② 与 CONTRACT business_truths 数量一致；
    ③ 每条真值都有可执行的验证 method（L4 断言带 method）。
    返回 (exit_code, problems列表)。
    """
    problems = []
    draft = _extract_json_block(draft_text)
    if draft is None:
        return 1, ["DRAFT_JSON 无法解析（JSON 块缺失或非法）"]

    truths_count = int(draft.get("truths_count") or 0)
    auto_asserts = int(draft.get("auto_asserts") or 0)
    l4 = draft.get("L4") or []
    if isinstance(l4, dict):
        l4 = list(l4)

    if truths_count <= 0:
        problems.append("truths_count 必须 > 0")
    if truths_count > 5:
        problems.append(f"粒度超界: truths_count={truths_count} > 5（需拆解子任务）")

    if contract_text:
        contract = _extract_json_block(contract_text)
        if contract and isinstance(contract.get("business_truths"), list):
            contract_count = len(contract["business_truths"])
            if truths_count != contract_count:
                problems.append(
                    f"truths_count={truths_count} 与 CONTRACT business_truths 数={contract_count} 不一致"
                )

    # 每条真值必须有可执行的 L4 method（验证契约核心）
    methods = []
    for a in l4:
        if isinstance(a, dict):
            m = str(a.get("method") or "").strip().lower()
            if m:
                methods.append(m)
    bad = sorted({m for m in methods if m not in ALLOWED_VERIFY_METHODS})
    if bad:
        problems.append(f"非法验证 method: {bad}（允许: {sorted(ALLOWED_VERIFY_METHODS)}）")

    if truths_count > 0 and len(methods) < truths_count:
        problems.append(
            f"{truths_count} 条真值仅 {len(methods)} 条 L4 断言带 method —— 缺可执行验证方法，"
            f"需补 method: api/vitest/visual/page_accept/e2e（缺则验收无法判定，会误 block）"
        )
    if auto_asserts and auto_asserts < truths_count:
        problems.append(f"auto_asserts={auto_asserts} < truths_count={truths_count}（自动断言不足）")

    return (1 if problems else 0), problems


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

    pcd = sub.add_parser("check-draft", help="校验 DRAFT_JSON 验证契约（每条真值有可执行 method，fail-closed）")
    pcd.add_argument("--draft", required=True, help="DRAFT_JSON 文本，或 @文件路径")
    pcd.add_argument("--contract", default="", help="CONTRACT_JSON 文本或 @文件路径（可选，校验数量一致性）")

    args = p.parse_args(argv)

    if args.cmd == "check-draft":
        draft_text = _read_arg(args.draft)
        contract_text = _read_arg(args.contract) if args.contract else None
        code, problems = check_draft(draft_text, contract_text)
        for p in problems:
            print(f"❌ {p}")
        if code == 0:
            print("✅ DRAFT 验证契约通过：每条真值都有可执行验证方法")
        return code

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
        # 已否证的真值要**可行动**（issue #4430 / B3）：「不存在」与「已被否证」是两件事 ——
        # 前者可能是打错字，后者应当改用现行真值（并点名否证它的 issue）。
        retired, _ = load_all_retired(args.templates)
        if args.truth_id in retired:
            meta = retired[args.truth_id]
            print(f"❌ 真值已被否证: {args.truth_id}"
                  f"（retired_by #{meta.get('retired_by')}）：{meta.get('reason')}", file=sys.stderr)
            return 1
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
        retired, retired_problems = load_all_retired(args.templates)
        _print_index(index)
        print(f"\n合计 {len(index)} 条真值；已否证 {len(retired)} 条；无 ID {unid} 条；"
              f"冲突 {len(conflicts)} 个")
        for p in retired_problems:
            print(f"  ❌ {p['id']}: {p['msg']}")
        return 1 if (conflicts or retired_problems) else 0

    if args.cmd == "render":
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
    print(f"真值库: {report['template_truths']} 条 | 已否证: {report['retired_truths']} 条 | "
          f"用例引用: {report['case_refs']} 处 | "
          f"缺口用例: {report['gap_cases']} 个 | 冲突: {len(report['truth_conflicts'])} 个")
    for p in report["problems"]:
        mark = "❌" if p["kind"] in BLOCKING_PROBLEM_KINDS else "⚠️"
        print(f"  {mark} {p['case']}: {p['msg']}")
    if code:
        print("\n❌ 真值引用/否证登记存在阻塞问题（fail-closed）")
    else:
        print("\n✅ 全部用例的 truths_ref 可解析，且已否证真值无残留引用")
    return code


if __name__ == "__main__":
    sys.exit(main())
