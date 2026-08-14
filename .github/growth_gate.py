#!/usr/bin/env python3
"""
二郎神 QA Growth Gate — 数据驱动的事前测试覆盖门禁（G1 修复）

单一规则源：tech-stack.yml 的 `modules`（文件 → 测试映射）。
豁免：.github/qa-exemptions.yml 的 `exemptions[].pattern`（路径 glob，`*` 不跨 `/`）。

替代 pr-check.yml 内硬编码的 case 矩阵，消除「tech-stack.yml vs pr-check.yml」双源漂移。
纯函数（compile_rules / classify_file 等）可单测；main() 只在 CI / 本地薄壳调用。

用法:
  python3 growth_gate.py --files f1 f2 --json            # CI：手动指定变更文件
  python3 growth_gate.py --base origin/main --json        # 本地：git diff
  TECH_STACK_FILE=.github/tech-stack.yml python3 growth_gate.py --json
"""
import argparse
import fnmatch
import glob as _glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── 规则编译（数据 → 可执行规则）──

def compile_rules(modules, test_commands=None):
    """把 tech-stack.yml 的 modules 编译为 [(regex, tests, language, cwd, service)]。"""
    tc = test_commands or {}
    rules = []
    for mod in modules or []:
        language = mod.get("language", "unknown")
        service = mod.get("service", "")
        cwd = (tc.get(language) or {}).get("cwd", ".")
        for pat in mod.get("patterns") or []:
            pattern = pat.get("pattern", "")
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue
            rules.append({
                "regex": compiled,
                "tests": pat.get("tests") or [],
                "language": language,
                "service": service,
                "cwd": cwd,
            })
    return rules


def match_rule(file_path, rules):
    """返回第一个匹配 file_path 的规则，无匹配返回 None。"""
    for rule in rules:
        if rule["regex"].search(file_path):
            return rule
    return None


def expand_test_names(rule, file_path):
    """把规则里的测试模板（{1}/{2} 捕获组）展开为测试文件名。"""
    m = rule["regex"].search(file_path)
    groups = m.groups() if m else ()
    names = []
    for tf in rule["tests"]:
        try:
            names.append(tf.format(None, *groups) if "{" in tf else tf)
        except (IndexError, KeyError, ValueError):
            continue
    return names


def find_existing_tests(rule, test_names, repo_root):
    """检查哪些测试文件实际存在。

    tech-stack.yml 的 test 模板有两种基准（历史口径不一）：
    - cwd 相对：如 frontend/admin-web 的 tests/unit/components/...
    - repo 根相对：如 tests/e2e/specs/（E2E 在仓库根）
    任一命中即算存在，避免因基准不一致误判缺测。
    """
    cwd = rule.get("cwd") or "."
    base = repo_root if cwd in (".", "") else os.path.join(repo_root, cwd)
    existing = []
    for tn in test_names:
        if rule["language"] == "java":
            if tn.endswith(".java"):
                hits = _glob.glob(os.path.join(base, tn), recursive=True)
            else:
                hits = _glob.glob(os.path.join(base, f"**/{tn}.java"), recursive=True)
            if hits:
                existing.append(tn)
        else:
            candidates = [os.path.join(base, tn), os.path.join(repo_root, tn)]
            if any(os.path.exists(c) for c in candidates):
                existing.append(tn)
    return existing


def resolve_test_paths(rule, test_names, repo_root):
    """把规则的测试模板展开为磁盘上真实存在的测试文件路径（G5 追溯链用）。

    与 find_existing_tests 同基准逻辑，但返回真实路径而非模板名。
    """
    cwd = rule.get("cwd") or "."
    base = repo_root if cwd in (".", "") else os.path.join(repo_root, cwd)
    paths = []
    for tn in test_names:
        if rule["language"] == "java":
            if tn.endswith(".java"):
                hits = _glob.glob(os.path.join(base, tn), recursive=True)
            else:
                hits = _glob.glob(os.path.join(base, f"**/{tn}.java"), recursive=True)
        else:
            hits = [c for c in (os.path.join(base, tn), os.path.join(repo_root, tn))
                    if os.path.exists(c)]
        paths.extend(hits)
    return paths


# ── 分类 ──

def is_auto_pass(file_path):
    """测试/文档/配置/资源文件自动通过（等价原 case 的 auto-pass 分支）。"""
    segs = file_path.split("/")
    if any(s.startswith("test") for s in segs):
        return True
    if file_path.endswith((".md", ".xml", ".json", ".lock", ".sql", ".png", ".jpg", ".svg")):
        return True
    if segs[-1] in (".gitignore", ".env.example"):
        return True
    if file_path.startswith("docs/"):
        return True
    return False


def _glob_match(segs, pattern):
    """段级 glob：`*` 不跨 `/`（等价 shell case 语义）。"""
    pats = pattern.split("/")
    if len(segs) != len(pats):
        return False
    return all(fnmatch.fnmatch(s, p) for s, p in zip(segs, pats))


def is_exempt(file_path, exemptions):
    """命中 qa-exemptions.yml 的 pattern 则豁免。"""
    segs = file_path.split("/")
    for ex in exemptions or []:
        pat = ex.get("pattern", "")
        if pat and _glob_match(segs, pat):
            return True
    return False


def classify_file(file_path, rules, exemptions, repo_root):
    """单文件分类：auto_pass | exempt | pass | block | unmatched。"""
    if is_auto_pass(file_path):
        return {"file": file_path, "kind": "auto_pass", "module": "Test/Doc/Config"}
    if is_exempt(file_path, exemptions):
        return {"file": file_path, "kind": "exempt", "module": "—"}
    rule = match_rule(file_path, rules)
    if rule is None:
        return {"file": file_path, "kind": "unmatched", "module": "—"}
    test_names = expand_test_names(rule, file_path)
    existing = find_existing_tests(rule, test_names, repo_root)
    if existing:
        return {"file": file_path, "kind": "pass", "module": rule["service"], "tests": existing}
    return {"file": file_path, "kind": "block", "module": rule["service"],
            "required_tests": test_names}


def summarize(results):
    """聚合 blockers / warnings。"""
    blockers = [r for r in results if r["kind"] == "block"]
    warnings = [r for r in results if r["kind"] == "warn"]
    return blockers, warnings


# ── G5: 用例追溯链（测试文件 ↔ 行为用例 case-contract）──

CASE_IDS_RE = re.compile(r"case_ids\s*[:=]\s*\[?([^\]\n]*)\]?")


def extract_case_ids(test_file):
    """测试文件头部声明的用例 ID（`# case_ids: OR-001, OR-002` / `// case_ids=[...]`）。"""
    ids = []
    try:
        text = Path(test_file).read_text(encoding="utf-8")
    except OSError:
        return ids
    for line in text.split("\n")[:50]:
        m = CASE_IDS_RE.search(line)
        if m:
            for tok in m.group(1).split(","):
                tok = tok.strip().strip("'\"")
                if tok:
                    ids.append(tok)
    return ids


def load_case_index(cases_dir):
    """cases/*.yml → {case_id: {tier, file}}。目录缺失/解析失败 → ({}, err)。"""
    if not cases_dir or not os.path.isdir(cases_dir):
        return {}, f"用例库目录不存在: {cases_dir}"
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (here, os.path.join(here, "..", "junshi")):
            if d not in sys.path:
                sys.path.insert(0, d)
        from yaml_light import load_file
        index = {}
        for fn in sorted(os.listdir(cases_dir)):
            if not fn.endswith(".yml"):
                continue
            data = load_file(os.path.join(cases_dir, fn))
            for c in data.get("cases") or []:
                cid = c.get("id", "")
                if cid:
                    index[cid] = {"tier": c.get("tier", "normal"), "file": fn}
        return index, None
    except Exception as e:
        return {}, f"用例库解析失败 {cases_dir}: {e}"


TEST_FILE_EXTS = (".py", ".java", ".ts", ".tsx")


def _is_test_file(file_path):
    """路径是否为测试文件。

    判定：扩展名必须是代码文件（.py/.java/.ts/.tsx），文件名含 test/spec；
    conftest（pytest 夹具，非用例）与 runner/生成数据文件（local_runner/eval_cases 等）不算。
    """
    base = file_path.split("/")[-1]
    if not base.endswith(TEST_FILE_EXTS):
        return False
    if base in ("conftest.py", "conftest.ts"):
        return False
    return re.search(r"(test|spec)", base, re.I) is not None


def case_trace_check(rules, files, repo_root, cases_dir, base="origin/main"):
    """G5：对 PR 涉及的测试文件做「测试 ↔ 行为用例」追溯。

    规则：
    - 测试文件声明 case_ids → 每个 ID 必须存在于用例库，否则 block
    - 新增（本 PR added）测试未声明 → block「新增测试未关联行为用例」
    - 修改（本 PR changed）测试未声明 → block「修改测试未声明 case_ids」
    - 存量测试未声明 → warn（历史遗留，不阻塞，鼓励补关联）
    返回 (blocks, warns, report)。
    """
    blocks, warns, report = [], [], []
    if not cases_dir:
        return blocks, warns, [{"level": "info", "msg": "未提供 --check-cases，跳过 G5 用例追溯"}]
    if not os.path.isdir(cases_dir):
        warns.append({"file": cases_dir, "kind": "warn", "module": "Case Contract",
                      "reason": "用例库目录不存在，G5 用例追溯未启用（项目接入 case-contract 后自动生效）"})
        return blocks, warns, report
    case_index, err = load_case_index(cases_dir)
    if err:
        blocks.append({"file": cases_dir, "kind": "block", "module": "Case Contract",
                       "reason": f"G5 无法加载用例库: {err}"})
        return blocks, warns, report

    added = {os.path.normpath(os.path.join(repo_root, a)) for a in get_added_files(base)}
    changed = {os.path.normpath(os.path.join(repo_root, a)) for a in files}

    traced = set()
    for f in files:
        if _is_test_file(f):
            p = os.path.normpath(os.path.join(repo_root, f))
            if os.path.exists(p):
                traced.add(p)
            continue
        if is_auto_pass(f):
            continue
        rule = match_rule(f, rules)
        if rule is None:
            continue
        for p in resolve_test_paths(rule, expand_test_names(rule, f), repo_root):
            traced.add(os.path.normpath(p))

    for p in sorted(traced):
        declared = extract_case_ids(p)
        if declared:
            unknown = [c for c in declared if c not in case_index]
            if unknown:
                blocks.append({"file": p, "kind": "block", "module": "Case Contract",
                               "reason": f"测试声明了不存在的用例 ID: {', '.join(unknown)}"})
            else:
                report.append({"file": p, "level": "pass", "case_ids": declared})
        elif p in added:
            blocks.append({"file": p, "kind": "block", "module": "Case Contract",
                           "reason": "新增测试未声明 case_ids（头部加 # case_ids: <用例ID>，见 design/16-case-contract.md §五 G5）"})
        elif p in changed:
            blocks.append({"file": p, "kind": "block", "module": "Case Contract",
                           "reason": "修改的测试未声明 case_ids（头部加 # case_ids: <用例ID>）"})
        else:
            warns.append({"file": p, "kind": "warn", "module": "Case Contract",
                          "reason": "存量测试未声明 case_ids（建议关联行为用例）"})
    return blocks, warns, report


# ── G2: 覆盖率%门禁（解析三种报告 + 新鲜度 + 阈值）──

def parse_coverage_percent(text, coverage_type):
    """解析覆盖率报告文本 → 覆盖率百分比（float），失败返回 None。

    coverage_type:
      - jacoco   : JaCoCo XML 的 <counter type="LINE" missed covered/>
      - coverage : coverage.py `coverage json` 输出（totals.percent_covered）
      - vitest   : coverage-summary.json（total.lines.pct）
    """
    if coverage_type == "jacoco":
        m = re.search(r'<counter[^>]*type="LINE"[^>]*/?>', text)
        if not m:
            return None
        tag = m.group(0)
        missed = re.search(r'missed="(\d+)"', tag)
        covered = re.search(r'covered="(\d+)"', tag)
        if not missed or not covered:
            return None
        missed_n, covered_n = int(missed.group(1)), int(covered.group(1))
        total = missed_n + covered_n
        return round(covered_n * 100.0 / total, 2) if total else None
    if coverage_type == "coverage":
        try:
            pct = json.loads(text).get("totals", {}).get("percent_covered")
            return float(pct) if pct is not None else None
        except (ValueError, TypeError):
            return None
    if coverage_type == "vitest":
        try:
            pct = json.loads(text).get("total", {}).get("lines", {}).get("pct")
            return float(pct) if pct is not None else None
        except (ValueError, TypeError):
            return None
    return None


def coverage_gate(percent, threshold=60):
    """覆盖率%门禁判定。返回 (verdict, msg)，verdict ∈ {pass, block, warn}。"""
    if percent is None:
        return ("warn", "覆盖率报告缺失/不可解析，无法执行%门禁")
    if percent < threshold:
        return ("block", f"覆盖率 {percent}% < {threshold}%")
    return ("pass", f"覆盖率 {percent}% ≥ {threshold}%")


SOURCE_SUFFIXES = {".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".kt", ".go"}


def _is_report_stale(report_path, source_roots):
    """覆盖率报告是否过期：报告 mtime 早于任一源码根的最新源文件。"""
    report_mtime = report_path.stat().st_mtime
    latest = 0.0
    for root in source_roots or []:
        root = Path(root) if root else None
        if not root or not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in SOURCE_SUFFIXES:
                try:
                    latest = max(latest, f.stat().st_mtime)
                except OSError:
                    pass
    return latest > report_mtime


def coverage_gate_from_report(report_path, coverage_type, source_roots, threshold=60):
    """读覆盖率报告 + 新鲜度 + 阈值 → (verdict, msg)。"""
    report = Path(report_path) if report_path else None
    if not report or not report.exists():
        return ("warn", "覆盖率报告缺失，无法执行%门禁")
    if _is_report_stale(report, source_roots):
        return ("warn", "覆盖率报告过期（源码已更新），%门禁不可信")
    try:
        text = report.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ("warn", "覆盖率报告读取失败")
    pct = parse_coverage_percent(text, coverage_type)
    return coverage_gate(pct, threshold)


# ── G4: 弱断言检测（防"凑数测试"过门禁）──

_WEAK_PATTERNS = [
    re.compile(r"assert\s+\w+\s+is\s+not\s+None"),
    re.compile(r"assert\s+\w+\s+is\s+None"),
    re.compile(r"assert\s+True\b"),
    re.compile(r"assert\s+False\b"),
    re.compile(r"assertTrue\s*\(\s*true\s*,"),
    re.compile(r"assertFalse\s*\(\s*false\s*,"),
    re.compile(r"expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)"),
    re.compile(r"expect\s*\(\s*false\s*\)\s*\.toBe\s*\(\s*false\s*\)"),
    re.compile(r"^\s*pass\s*$"),
]


def find_weak_asserts(test_file):
    """扫描测试文件的弱断言（不触业务数据的存在性/恒真断言 + 空 pass）。

    返回 [{line_no, line, reason}]。弱断言无法证明功能正确，属「凑数」。
    """
    weak = []
    try:
        text = Path(test_file).read_text(encoding="utf-8")
    except OSError:
        return weak
    for no, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped:
            continue
        for pat in _WEAK_PATTERNS:
            if pat.search(stripped):
                weak.append({"line_no": no, "line": stripped,
                             "reason": "弱断言（不触业务数据）"})
                break
    return weak


# ── 加载 + CLI ──

def _load_yaml(path):
    """返回 (data, error)。error 非空表示路径缺失或解析失败（门禁 fail-closed 依据）。"""
    if not path:
        return {}, "未提供配置文件路径"
    if not os.path.exists(path):
        return {}, f"配置文件不存在: {path}"
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (here, os.path.join(here, "..", "junshi")):
            if d not in sys.path:
                sys.path.insert(0, d)
        from yaml_light import load_file
        data = load_file(path)
        if not isinstance(data, dict):
            return {}, f"配置解析结果非对象: {path}"
        return data, None
    except Exception as e:
        return {}, f"配置解析失败 {path}: {e}"


def _find_tech_stack():
    env = os.environ.get("TECH_STACK_FILE")
    if env and os.path.exists(env):
        return env
    for cand in (".github/tech-stack.yml", "junshi/tech-stack.yml"):
        if os.path.exists(cand):
            return cand
    return None


def _find_exemptions():
    env = os.environ.get("EXEMPTIONS_FILE")
    if env and os.path.exists(env):
        return env
    if os.path.exists(".github/qa-exemptions.yml"):
        return ".github/qa-exemptions.yml"
    return None


def get_changed_files(base="origin/main"):
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "diff", "--name-only", base, "HEAD"],
                capture_output=True, text=True, timeout=15,
            )
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except Exception as e:
        print(f"⚠️ git diff 失败: {e}", file=sys.stderr)
        return []


def get_added_files(base="origin/main"):
    """git diff --diff-filter=A → 本 PR 新增文件（G5 用）。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--diff-filter=A", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "diff", "--diff-filter=A", "--name-only", base, "HEAD"],
                capture_output=True, text=True, timeout=15,
            )
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except Exception as e:
        print(f"⚠️ git diff --diff-filter=A 失败: {e}", file=sys.stderr)
        return []


def _render_markdown(results, blockers, warnings):
    lines = ["| 文件 | 模块 | 状态 |", "|------|------|------|"]
    for r in results:
        kind = r["kind"]
        if kind == "pass":
            lines.append(f"| {r['file']} | {r['module']} | ✅ |")
        elif kind == "block":
            if r.get("reason"):
                lines.append(f"| {r['file']} | {r['module']} | ❌ BLOCKED（{r['reason']}） |")
            else:
                req = ", ".join(r.get("required_tests", []) or [])
                lines.append(f"| {r['file']} | {r['module']} | ❌ BLOCKED（缺 {req}） |")
        elif kind == "exempt":
            lines.append(f"| {r['file']} | {r['module']} | 🔓 豁免 |")
        elif kind == "warn":
            lines.append(f"| {r['file']} | {r['module']} | ⚠️ {r.get('reason', '警告')} |")
        elif kind == "auto_pass":
            lines.append(f"| {r['file']} | {r['module']} | ✅ 自动通过 |")
        else:
            lines.append(f"| {r['file']} | {r['module']} | ℹ️ 未识别，跳过 |")
    md = "\n".join(lines)
    if blockers:
        md += f"\n\n## ❌ {len(blockers)} 处缺测阻塞合并"
        for b in blockers:
            if b.get("reason"):
                md += f"\n- **{b['file']}** → {b['reason']}"
            else:
                req = ", ".join(b.get("required_tests", []) or [])
                md += f"\n- **{b['file']}** → 补 {req}"
    elif warnings:
        md += f"\n\n## ⚠️ {len(warnings)} 处警告（非阻塞）"
    else:
        md += "\n\n## ✅ 全部通过"
    return md


def main(argv=None):
    parser = argparse.ArgumentParser(description="二郎神 QA Growth Gate（数据驱动）")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*", help="手动指定变更文件（跳过 git diff）")
    parser.add_argument("--tech-stack", help="tech-stack.yml 路径")
    parser.add_argument("--exemptions", help="qa-exemptions.yml 路径")
    parser.add_argument("--repo-root", default=os.getcwd())
    parser.add_argument("--json", action="store_true", help="写 JSON 结果文件")
    parser.add_argument("--json-file", default="growth-gate-result.json")
    parser.add_argument("--coverage-threshold", type=float, default=None,
                        help="覆盖率%门禁阈值（如 60）；不设则跳过覆盖率检查")
    parser.add_argument("--coverage-report",
                        help="覆盖率报告路径（jacoco.xml / coverage.json / coverage-summary.json）")
    parser.add_argument("--coverage-type", choices=["jacoco", "coverage", "vitest"],
                        default="jacoco")
    parser.add_argument("--exit-on-block", action="store_true",
                        help="有 blocker 时退出码 1（本地/CLI 用）；默认退出码 0（CI 由 JSON 判定，崩溃才非零）")
    parser.add_argument("--check-weak", action="store_true",
                        help="扫描 --files 指定测试文件的弱断言（凑数断言），有则退出 1")
    parser.add_argument("--check-cases",
                        help="用例库目录（cases/*.yml）——启用 G5 用例追溯链：测试文件 ↔ 行为用例")
    args = parser.parse_args(argv)

    if args.check_weak:
        if not args.files:
            print("⚠️ --check-weak 需配合 --files 指定测试文件")
            return 1
        total = 0
        for tf in args.files:
            weak = find_weak_asserts(tf)
            print(f"📄 {tf}: {len(weak)} 处弱断言")
            for w in weak:
                print(f"  L{w['line_no']}: {w['line']}")
            total += len(weak)
        print(f"\n合计 {len(args.files)} 个测试文件，{total} 处弱断言")
        return 1 if total > 0 else 0

    tech_path = args.tech_stack or _find_tech_stack()
    ex_path = args.exemptions or _find_exemptions()

    tech, tech_err = _load_yaml(tech_path)
    if tech_err:
        print(f"::error:: growth_gate 无法加载 tech-stack.yml: {tech_err}", file=sys.stderr)
        return 2  # fail-closed：规则源缺失/损坏时门禁必须失败，不能静默放行
    ex, ex_err = _load_yaml(ex_path)
    if ex_err:
        print(f"::warning:: growth_gate 无法加载 qa-exemptions.yml: {ex_err}（按无豁免处理）", file=sys.stderr)
        ex = {}

    modules = tech.get("modules") or []
    test_commands = tech.get("test_commands") or {}
    exemptions = ex.get("exemptions") or []

    rules = compile_rules(modules, test_commands)
    if not rules:
        print("::warning:: tech-stack.yml 的 modules 为空，覆盖率门禁无规则可执行", file=sys.stderr)
    files = args.files if args.files else get_changed_files(args.base)

    results = [classify_file(f, rules, exemptions, args.repo_root) for f in files]
    blockers, warnings = summarize(results)

    # G5: 用例追溯链（测试文件 ↔ 行为用例；--check-cases 启用）
    case_blocks, case_warns, case_report = [], [], []
    if args.check_cases:
        case_blocks, case_warns, case_report = case_trace_check(
            rules, files, args.repo_root, args.check_cases, args.base)
        blockers.extend(case_blocks)
        warnings.extend(case_warns)

    md = _render_markdown(results, blockers, warnings)
    print(md)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a") as f:
                f.write(md + "\n")
        except OSError:
            pass

    if args.json:
        payload = {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "blockers": blockers,
            "warnings": warnings,
            "results": results,
            "case_trace": {
                "blockers": len(case_blocks),
                "warnings": len(case_warns),
                "report": case_report,
            },
        }
        with open(args.json_file, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    cov_block = False
    if args.coverage_threshold is not None and args.coverage_report:
        cov_verdict, cov_msg = coverage_gate_from_report(
            args.coverage_report, args.coverage_type, [args.repo_root], args.coverage_threshold)
        line = f"📊 覆盖率门禁 [{cov_verdict}] {cov_msg}"
        print(line)
        if summary_file:
            try:
                with open(summary_file, "a") as f:
                    f.write("\n" + line + "\n")
            except OSError:
                pass
        if cov_verdict == "block":
            cov_block = True

    # 默认 exit 0 = 成功（blocker 由 JSON 判定，CI fail-closed 靠崩溃时非零退出 + set -e）。
    # --exit-on-block 供本地/CLI 便捷使用（有 blocker 即退出 1）。
    if args.exit_on_block:
        return 1 if (blockers or cov_block) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
