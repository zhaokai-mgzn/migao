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


def _render_markdown(results, blockers, warnings):
    lines = ["| 文件 | 模块 | 状态 |", "|------|------|------|"]
    for r in results:
        kind = r["kind"]
        if kind == "pass":
            lines.append(f"| {r['file']} | {r['module']} | ✅ |")
        elif kind == "block":
            req = ", ".join(r.get("required_tests", []) or [])
            lines.append(f"| {r['file']} | {r['module']} | ❌ BLOCKED（缺 {req}） |")
        elif kind == "exempt":
            lines.append(f"| {r['file']} | {r['module']} | 🔓 豁免 |")
        elif kind == "auto_pass":
            lines.append(f"| {r['file']} | {r['module']} | ✅ 自动通过 |")
        else:
            lines.append(f"| {r['file']} | {r['module']} | ℹ️ 未识别，跳过 |")
    md = "\n".join(lines)
    if blockers:
        md += f"\n\n## ❌ {len(blockers)} 处缺测阻塞合并"
        for b in blockers:
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
