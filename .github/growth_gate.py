#!/usr/bin/env python3
"""
QA Growth Gate — 数据驱动的事前测试覆盖门禁（G1 修复）

单一规则源：tech-stack.yml 的 `modules`（文件 → 测试映射）。
豁免：.github/qa-exemptions.yml 的 `exemptions[].pattern`（路径 glob，`*` 不跨 `/`）。

替代 pr-check.yml 内硬编码的 case 矩阵，消除「tech-stack.yml vs pr-check.yml」双源漂移。
纯函数（compile_rules / classify_file 等）可单测；main() 只在 CI / 本地薄壳调用。

用法:
  python3 growth_gate.py --files f1 f2 --json            # CI：手动指定变更文件
  python3 growth_gate.py --base origin/main --json        # 本地：git diff
  python3 growth_gate.py --render-pr-comment growth-gate-result.json   # CI：结果对象 → PR 评论正文
  TECH_STACK_FILE=.github/tech-stack.yml python3 growth_gate.py --json
"""
import argparse
import ast
import datetime
import fnmatch
import glob as _glob
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

# ── 规则编译（数据 → 可执行规则）──

def compile_rules(modules, test_commands=None, errors=None):
    """把 tech-stack.yml 的 modules 编译为 [(regex, tests, language, cwd, service)]。

    `errors`：可选列表；把**被丢弃**的规则（pattern 为空 / 正则非法）登记进去。
    为什么（fail-closed，本次收紧）：旧实现用裸 `continue` 静默丢弃，规则源的一部分
    于是**悄悄消失** —— 对应文件随即落进 `unmatched`（既非 block 也非 warn，
    控制台只显示「ℹ️ 未识别，跳过」）⇒ 缺测门禁对它们**完全失效**，而**没有任何东西变红**。
    规则源退化必须报错，不得降级成「这些文件没有规则」（同族：issue #3631 的
    「扫描失败 ≠ 无变更」、danger_scan 的取证 fail-closed）。
    `errors` 为 None 时保持旧签名可用（纯函数调用方不受影响）。
    """
    tc = test_commands or {}
    rules = []
    for mod in modules or []:
        language = mod.get("language", "unknown")
        service = mod.get("service", "")
        cwd = (tc.get(language) or {}).get("cwd", ".")
        for pat in mod.get("patterns") or []:
            pattern = pat.get("pattern", "")
            if not pattern:
                if errors is not None:
                    errors.append(f"service={service or '?'}: 空 pattern（该 rules 条目被丢弃）")
                continue
            try:
                compiled = re.compile(pattern)
            except re.error as e:
                if errors is not None:
                    errors.append(f"service={service or '?'}: 正则非法 {pattern!r}（{e}）—— 该条规则被丢弃")
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


def _test_file_variants(path):
    """返回测试文件路径的候选变体：原样 + .ts/.tsx 互换。

    项目测试实际用 .test.tsx，但 tech-stack.yml 模板写 .test.ts（历史口径），
    两个扩展名都应命中，避免误判缺测。
    """
    if path.endswith(".ts"):
        return [path, path[:-3] + ".tsx"]
    if path.endswith(".tsx"):
        return [path, path[:-4] + ".ts"]
    return [path]


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
            for cand in [os.path.join(base, tn), os.path.join(repo_root, tn)]:
                if any(os.path.exists(v) for v in _test_file_variants(cand)):
                    existing.append(tn)
                    break
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
            hits = []
            for c in (os.path.join(base, tn), os.path.join(repo_root, tn)):
                hits.extend(v for v in _test_file_variants(c) if os.path.exists(v))
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

# 只认**注释起始的声明行**（issue #4239）：`# case_ids: OR-001, OR-002` /
# `// case_ids=OR-001` / `// case_ids=[...]` / JSDoc 块注释续行 ` * case_ids: X`
# （四种形态由全仓已声明测试文件枚举得出，不得误伤）。正文 / docstring 里「提及」
# `case_ids:` **不算声明** —— 旧实现用 search 全文累积：提及会混入垃圾令牌
# （假红：合规 PR 被判「声明了不存在的用例 ID」）或让未声明的文件被判「已声明」
# （假绿：QA Growth Gate 根本失效）。
CASE_IDS_RE = re.compile(r"^\s*(?:#|//|\*)\s*case_ids\s*[:=]\s*\[?([^\]\n]*)\]?")

# 需要扫 `/* … */` 与引号串（含模板串）的语言后缀（issue #4311）；其余后缀不做区域判定。
_BLOCK_COMMENT_SUFFIXES = (".java", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".kt", ".kts")


def _non_declaration_lines(text, head, suffix):
    """前 50 行里落在**字符串字面量 / 块注释内**的行号（1-based）—— 它们不是「真声明」（#4311）。

    行级正则分不清「注释」与「字符串里的行」：`# case_ids: FAKE-777` 落在 Python 模块 docstring 内、
    或 ` * case_ids: FAKE-777` 落在 Java/TS 块注释内时，`CASE_IDS_RE` 照样命中 ⇒ 首个命中即停
    ⇒ 文档里贴的样例会把后面的真声明顶掉（假红 block 合规 PR / 真声明失效）。

    - `.py`：用 `ast` 取**字符串常量**的行区间（模块 docstring 即字符串常量）；解析失败
      （夹具里的非 Python 片段、语法残缺）⇒ 空集：**无从判定就不排除**（只影响收窄力度，不影响正确性）。
    - Java/TS/JS：扫 `/* … */`（含 `/** */`）与引号串（含模板串）。
    - 其余后缀：空集（不做区域判定）。状态自文件头起算，只扫前 50 行（与位置约束同界）。
    """
    if suffix == ".py":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # 无关文件的语法告警（如非法转义）不污染门禁输出
                tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return set()
        lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        return lines
    if suffix not in _BLOCK_COMMENT_SUFFIXES:
        return set()

    lines, in_block, quote = set(), False, ""
    for no, line in enumerate(head, 1):
        i, n = 0, len(line)
        while i < n:
            ch = line[i]
            if in_block:
                lines.add(no)
                if ch == "*" and line.startswith("/", i + 1):
                    in_block = False
                    i += 2
                    continue
            elif quote:
                lines.add(no)
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = ""
            elif ch == "/" and line.startswith("*", i + 1):
                in_block = True
                lines.add(no)
            elif ch == "/" and line.startswith("/", i + 1):
                break  # 行注释：其后不再是字符串
            elif ch in "\"'`":
                quote = ch
                lines.add(no)
            i += 1
    return lines


def extract_case_ids(test_file):
    """测试文件头部**首个声明行**的用例 ID（`# case_ids: OR-001, OR-002` / `// case_ids=[...]`）。

    只认注释起始的声明行 + **取首个命中即停**（issue #4239）：docstring / 正文里的提及不是声明。

    `#4311` 再加一条：字符串字面量 / 块注释内的候选**不是真声明**，真声明优先于它
    （伪声明不再把真声明顶掉）。但**无真声明时按旧口径取首个候选** —— 全仓实测有 17 个测试文件
    只有这种非注释形态的候选（13 个 Python 文件的声明行在模块 docstring 内、4 个 TS 文件的
    声明行在文件头 JSDoc 块注释内），严格排除会把它们判成「未声明」= 对合规文件制造假红，
    且按 §19.1「存量基线只许缩短」这条豁免**永远缩不掉** ⇒ 取兜底。

    **残留（如实登记，不粉饰）**：某文件的**唯一**声明候选若落在字符串/块注释内，**仍会被当成
    声明** —— 它在静态上与那 17 个合规文件**不可区分**（#4311 判据 3「全仓逐值相同」正要求如此）。
    唯一可判的坏形态 = 「伪声明在前 + 真声明在后」的**遮蔽形态**，它已被本条修掉。
    复核（**不要写死数字**，全仓会前进）：

        /opt/homebrew/bin/python3.11 -m pytest tests/unit_ci_workflows/test_growth_gate_case_ids.py -q -s -k fallback
        # 打印「依赖兜底的合规文件=N（下限 17）  遮蔽形态=M（今天 0，不设上限）」

    「只扫前 50 行」的位置约束不变（#3555 的既有裁定，与本缺陷正交）。
    """
    try:
        text = Path(test_file).read_text(encoding="utf-8")
    except OSError:
        return []
    head = text.split("\n")[:50]
    non_decl = _non_declaration_lines(text, head, os.path.splitext(str(test_file))[1].lower())
    candidate = None
    for no, line in enumerate(head, 1):
        m = CASE_IDS_RE.match(line)
        if not m:
            continue
        ids = [tok for tok in (t.strip().strip("'\"") for t in m.group(1).split(",")) if tok]
        if no not in non_decl:
            return ids
        if candidate is None:
            candidate = ids
    return candidate or []


def load_case_index(cases_dir):
    """cases/*.yml → {case_id: {tier, file}}。目录缺失/解析失败 → ({}, err)。"""
    if not cases_dir or not os.path.isdir(cases_dir):
        return {}, f"用例库目录不存在: {cases_dir}"
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
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

    ⚠️ **本函数是「哪些文件算测试文件」的单一事实源（issue #4077）**：G5 用例追溯与新测试
    弱断言扫描（`--check-weak --new-tests-only`）都必须调它。此前这句判定在三处各写了一遍
    （本函数 / `pr-check.yml` 的内联 grep / `verify-all.sh` 的内联 grep），且本地那处**只**过滤
    工作区新增文件、不过滤已提交 diff 里的新增文件 ⇒ 新增**源文件**（如 `app/**/x.py`）被当作
    测试文件扫弱断言、报出 CI 不会报的红（`verify-all.sh` 曾断言「与 pr-check 语义一致」但实现
    不同 = 注释漂移）。**禁止在别处再写一套判定**：复制一份必然漂移。
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
#
# 存在性/缺失性两条模式的**口径收窄**（2026-09-21 / issue #5083 的一条：正则误报真断言）：
# 只命中「**整个断言表达式就是这一个比较**」的形态（= 不触业务数据的空断言）；
# 带布尔续接（`or` / `and`）的复合表达式是**真断言**，此前被判弱断言属**假红**——
# 本地实测 5 处 `… is None or …`（如 backend/ai-agent-service/tests/contracts/test_contract_api.py、
# tests/smoke/test_05_tenant.py）+ 6 处 `… is not None and …`
# （如 backend/ai-agent-service/tests/test_graph_skills.py）全部被误报。
# ⚠️ **不是删表**：裸形态（`assert x is None` / `assert x is not None`）仍逐条检出，
# 带尾随断言消息 / 行尾注释的也仍检出（表达式没变，只是多了消息参数/注释）。
_WEAK_PATTERNS = [
    re.compile(r"assert\s+\w+\s+is\s+not\s+None(?!\s+(?:or|and)\b)"),
    re.compile(r"assert\s+\w+\s+is\s+None(?!\s+(?:or|and)\b)"),
    re.compile(r"assert\s+True\b"),
    re.compile(r"assert\s+False\b"),
    re.compile(r"assertTrue\s*\(\s*true\s*,"),
    re.compile(r"assertFalse\s*\(\s*false\s*,"),
    re.compile(r"expect\s*\(\s*true\s*\)\s*\.toBe\s*\(\s*true\s*\)"),
    re.compile(r"expect\s*\(\s*false\s*\)\s*\.toBe\s*\(\s*false\s*\)"),
    re.compile(r"^\s*pass\s*$"),
]

# TS/TSX 侧形态（issue #5080 盲区①）：`.ts`/`.tsx` 属 `_is_test_file` 覆盖面、本来就会被
# 收进扫描集，但模式表原先只有 Python 形态 ⇒ 命中率**恒为 0**（TS 侧零判据 = 完全不可见）。
# **入表集合按全仓实测判别力决定**（本仓当前树实测：`toBeDefined` 38 处 / 21 个测试文件、
# `not.toBeNull` 35 处 / 16 个、`toBeTruthy` 500 处 / 60 个）：
#   · 入表：`toBeDefined` / `not.toBeNull` —— 只证明「东西在」（存在性/非空性），
#     与 Python 侧的 `is not None` 同族，全仓**无**假阳性形态；
#   · **有意不入表**：`toBeTruthy` —— 500 处里 424 处作用在 testing-library 的
#     `getBy*`/`findBy*` 返回值上（该 getter 未命中即抛 ⇒ 断言恒真、属**更弱**），但余下
#     76 处作用在 `querySelector` / `includes` / 位掩码等**真断言**上 ⇒ 文本层一刀切会认下
#     76 处假红，判别力不足。取舍钉在 tests/unit_ci_workflows/test_weak_assert_blindspots.py。
_TS_WEAK_PATTERNS = [
    re.compile(r"expect\s*\(.*\)\s*\.toBeDefined\s*\(\s*\)"),
    re.compile(r"expect\s*\(.*\)\s*\.not\.toBeNull\s*\(\s*\)"),
]


def _weak_patterns_for(test_file):
    """按扩展名取模式集：TS 专属形态**只**对 .ts/.tsx 生效（不施加到 Python 文件）。"""
    patterns = list(_WEAK_PATTERNS)
    if str(test_file).endswith((".ts", ".tsx")):
        patterns += _TS_WEAK_PATTERNS
    return patterns


def find_weak_asserts(test_file):
    """扫描测试文件的弱断言（不触业务数据的存在性/恒真断言 + 空 pass）。

    返回 [{line_no, line, reason}]。弱断言无法证明功能正确，属「凑数」。
    TS/TSX 文件额外套用 `_TS_WEAK_PATTERNS`（issue #5080 盲区①）。
    读文件失败/路径不存在/编码异常 → 抛 ValueError（fail-closed：门禁依赖的
    扫描不可空转，「路径不可读」绝不允许退化成「0 处弱断言」放行，见 issue #3631）。
    """
    weak = []
    try:
        text = Path(test_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"无法读取测试文件 {test_file}（{e.__class__.__name__}）") from e
    patterns = _weak_patterns_for(test_file)
    for no, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped:
            continue
        for pat in patterns:
            if pat.search(stripped):
                weak.append({"line_no": no, "line": stripped,
                             "reason": "弱断言（不触业务数据）"})
                break
    return weak


# ── G4b: 存量弱断言锚点账本（issue #5080 盲区②：只扫新增 ⇒ 存量永久免疫）──
#
# 口径 = 「**新增文件 fail-closed**（不变：CI 与本地都只把新增文件喂给 `--check-weak`）
#          + **存量只许非增**（本节）」。**不做一次性全量清账**：存量三位数处逐条清偿不现实，
# 但必须给它一个**可缩短的载体** —— 锚点快照明细 + `history`（范式同
# `.github/skip-exemption-baseline.json`，不另造一套）。
# 判据（fail-closed）：某文件当前处数 **>** 锚点 ⇒ 红；文件不在锚点里却有处数（新增文件
# / 新入账）⇒ 红；**少于**锚点 ⇒ 放行（净缩是唯一合法方向）。账本缺失/损坏 ⇒ rc 2。
WEAK_BASELINE_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "weak-assert-baseline.json")

# 全仓扫描跳过的目录（依赖/构建产物）。只决定「扫哪些路径」，不改「是不是测试文件」的判定
# —— 那句判定仍走 `_is_test_file` 单一事实源（issue #4077）。
_WEAK_SCAN_SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "coverage",
                        "htmlcov", ".venv", "venv", "__pycache__", ".pytest_cache",
                        "out", ".turbo"}


def iter_repo_test_files(repo_root="."):
    """全仓测试文件（相对路径，排序稳定）。判定唯一事实源 = `_is_test_file`。"""
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _WEAK_SCAN_SKIP_DIRS)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), repo_root)
            if _is_test_file(rel):
                yield rel


def scan_repo_weak_asserts(repo_root="."):
    """全仓弱断言实测 → {相对路径: 处数}（只收 > 0 的文件）。

    读文件失败/编码异常 → 抛 ValueError（fail-closed：账本依赖的扫描不可空转，见 issue #3631）。
    """
    counts = {}
    for rel in iter_repo_test_files(repo_root):
        n = len(find_weak_asserts(os.path.join(repo_root, rel)))
        if n > 0:
            counts[rel] = n
    return counts


def load_weak_baseline(path):
    """→ (anchored_counts, meta, error)。error 非空 = 账本缺失/损坏（fail-closed 依据）。"""
    if not path or not os.path.exists(path):
        return {}, {}, f"弱断言锚点账本不存在: {path}"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return {}, {}, f"弱断言锚点账本解析失败 {path}（{e.__class__.__name__}）"
    if not isinstance(data, dict):
        return {}, {}, f"弱断言锚点账本非对象: {path}"
    counts = data.get("legacy_weak_counts")
    if not isinstance(counts, dict) or not counts:
        return {}, {}, f"弱断言锚点账本 legacy_weak_counts 缺失/为空: {path}"
    if not all(isinstance(v, int) and v > 0 for v in counts.values()):
        return {}, {}, f"弱断言锚点账本的处数必须为正整数: {path}"
    if not all(_is_test_file(k) for k in counts):
        return {}, {}, f"弱断言锚点账本的键必须是测试文件（同 _is_test_file）: {path}"
    total = sum(counts.values())
    if data.get("weak_total") != total:
        return {}, {}, f"弱断言锚点账本 weak_total({data.get('weak_total')}) != 明细合计({total}): {path}"
    history = data.get("history") or []
    if not history or history[-1].get("weak_total") != total:
        return {}, {}, f"弱断言锚点账本 history 缺失或末行总量不符: {path}"
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("anchor_sha", ""))):
        return {}, {}, f"弱断言锚点账本 anchor_sha 非法: {path}"
    return counts, data, ""


def weak_baseline_diff(counts, anchored):
    """纯函数：相对锚点的**增长**（含新入账文件）→ [(path, cur, base)]，base=None 表示新文件。"""
    return [(p, c, anchored.get(p)) for p, c in sorted(counts.items())
            if c > anchored.get(p, 0)]


def check_weak_baseline(repo_root=".", baseline_path=None):
    """存量弱断言锚点检查（issue #5080 盲区②）→ (rc, report_lines, counts)。

    rc：0 = 不增长（净缩放行）/ 1 = 有增长或新入账 / 2 = 账本缺失损坏或扫描失败（fail-closed）。
    """
    baseline_path = baseline_path or WEAK_BASELINE_DEFAULT
    anchored, _, err = load_weak_baseline(baseline_path)
    if err:
        lines = [f"::error:: {err}",
                 "❌ 存量弱断言锚点不可用即门禁失败（fail-closed）：账本缺失/损坏 ≠ 无存量弱断言"]
        for ln in lines:
            print(ln, file=sys.stderr)
        return 2, lines, {}
    try:
        counts = scan_repo_weak_asserts(repo_root)
    except ValueError as e:
        lines = [f"::error:: {e}",
                 "❌ 全仓弱断言扫描失败即门禁失败（fail-closed）：扫描不可空转（见 issue #3631）"]
        for ln in lines:
            print(ln, file=sys.stderr)
        return 2, lines, {}
    growth = weak_baseline_diff(counts, anchored)
    if growth:
        lines = [f"❌ 弱断言只许非增：{len(growth)} 个文件越过锚点"
                 f"（锚点 {sum(anchored.values())} 处 → 当前 {sum(counts.values())} 处）"]
        for p, cur, base in growth:
            kind = "新增入账 —— 新文件一律 fail-closed" if base is None else f"存量增长 {base} → {cur}"
            lines.append(f"  · {p}: {cur} 处（{kind}）")
        lines.append("  处置：把弱断言改成触业务数据的断言（不得靠改账本洗白："
                     "重锚定只接受净缩，见 --write-weak-baseline）")
        for ln in lines:
            print(ln)
        return 1, lines, counts
    saved = sum(anchored.values()) - sum(counts.values())
    lines = [f"✅ 存量弱断言不增长：锚点 {sum(anchored.values())} 处 / 当前 {sum(counts.values())} 处"
             f"（净缩 {saved} 处；账本 {baseline_path}）"]
    for ln in lines:
        print(ln)
    return 0, lines, counts


def _head_sha(repo_root="."):
    """当前 HEAD（取不到 → 空串，调用方回退到旧值）。"""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = (r.stdout or "").strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else ""


def write_weak_baseline(repo_root=".", baseline_path=None):
    """重锚定（**只许缩**）→ (rc, report_lines, counts)。

    任一文件增长/新入账 ⇒ **拒绝**（rc 1，不得用改账本洗白新增弱断言）；
    否则写回明细 + 追加 `history` 一行（只许非增）。账本缺失/损坏 ⇒ rc 2。
    """
    baseline_path = baseline_path or WEAK_BASELINE_DEFAULT
    _, data, err = load_weak_baseline(baseline_path)
    if err:
        print(f"::error:: {err}", file=sys.stderr)
        return 2, [err], {}
    rc, lines, counts = check_weak_baseline(repo_root, baseline_path)
    if rc != 0:
        print("❌ 重锚定被拒：账本只接受净缩（增长/新入账必须先把弱断言改掉）", file=sys.stderr)
        return rc, lines, counts
    old_total = data.get("weak_total")
    new_total = sum(counts.values())
    data["legacy_weak_counts"] = counts
    data["weak_total"] = new_total
    data["anchor_sha"] = _head_sha(repo_root) or data.get("anchor_sha")
    data["anchored_at"] = datetime.date.today().isoformat()
    data.setdefault("history", []).append({
        "anchored_at": data["anchored_at"], "anchor_sha": data["anchor_sha"],
        "weak_total": new_total, "note": f"重锚定（只许缩）：{old_total} → {new_total}",
    })
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    lines = list(lines) + [f"✅ 已重锚定 {baseline_path}：{old_total} → {new_total} 处"]
    for ln in lines:
        print(ln)
    return 0, lines, counts


# ── 加载 + CLI ──

def _load_yaml(path):
    """返回 (data, error)。error 非空表示路径缺失或解析失败（门禁 fail-closed 依据）。"""
    if not path:
        return {}, "未提供配置文件路径"
    if not os.path.exists(path):
        return {}, f"配置文件不存在: {path}"
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
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
    for cand in (".github/tech-stack.yml",):
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
    """本 PR 变更文件（rename 感知）：改名文件只按新路径计，避免旧路径被误判为「缺配套测试」。

    旧实现 `git diff --name-only` 在 rename 检测关闭时会把改名文件输出为旧路径（删除）+ 新路径（新增），
    导致 gate 对已改名的 Mapper/实体按旧名查找配套测试 → 误报 BLOCKED（实测 issue #3051 知识卡片改名）。
    用 `--name-status -M` 输出 Rxxx old→new，只保留新路径。

    git diff 失败（base 缺失/非 git 仓库/超时等）→ 返回 None（fail-closed：
    「扫描不到变更」≠「无变更」——门禁依赖的扫描空转必须显式报错，见 issue #3631）。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", "-M", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "diff", "--name-status", "-M", base, "HEAD"],
                capture_output=True, text=True, timeout=15,
            )
        if result.returncode != 0:
            print(f"::error:: git diff 失败: {(result.stderr or '').strip() or f'git diff {base} 退出码 {result.returncode}'}",
                  file=sys.stderr)
            return None
        files = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            if parts[0].startswith("R") and len(parts) >= 3:
                # R100  old_path  new_path → 只保留新路径
                files.append(parts[2])
            elif parts[0].startswith("D"):
                # 删除的文件不需要配套测试（issue #3051 旧知识库移除误报修复）
                continue
            else:
                files.append(parts[1])
        return files
    except Exception as e:
        print(f"::error:: git diff 失败: {e}", file=sys.stderr)
        return None


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


# ── PR 评论渲染（issue #5292：判红必须可归因，且不得诱导扩豁免）──
#
# 病灶（实测 PR #5285，评论正文只有标题 +「Blockers: 6」，**看不到是哪 6 条**）：
# `Post PR comment` step 读的是**它自己那一步**的 `$GITHUB_STEP_SUMMARY` —— 该变量是
# **逐步**文件（每步一个 uuid），而 markdown 是本脚本在 `check` step 里写进**那一步**的
# summary ⇒ 读到的永远是空文件（`readFileSync` 不抛，只是空串 ⇒ 正文那一块留白）。
# 于是「清单不可见」+ 末尾「或在 qa-exemptions.yml 中添加合法豁免项」= **诱导扩豁免**
# （本仓口径：豁免面只许缩短）。数据一直都在 `--json-file` 里（同一 job 的同一工作区），
# 丢的只是「渲染进评论」这一步。修法：正文**只**从那份 JSON 渲染（单一数据源），逐条列出。

# 「结果文件不可用」的正文明细前缀 —— 计数与清单自相矛盾 / 结果文件读不到时**唯一**的
# 合规正文形态（fail-closed）：此时**不得**渲染成「看起来正常」的评论，更不得提豁免。
_RESULT_UNUSABLE_PREFIX = "## ❌ QA Growth Gate — 结果文件不可用（fail-closed）"


def result_mismatch(payload):
    """结果对象**自相矛盾**的说明（计数 ≠ 清单条数）；一致 → None。

    为什么必须判：`blocker_count` 驱动 job 判红（`Fail on blocking violations` 读它），
    清单驱动「是哪几条」。两者不一致时两条渲染路都不许静默：
    - 按计数渲染 ⇒ 「6 处缺测（清单 0 条）」= issue #5292 的现网形态（不可归因、且诱导加豁免）；
    - 按清单渲染 ⇒ 6 处**真实**阻塞被渲染成「0 条 / 全部通过」= 假绿（更危险）。
    ⇒ fail-closed：显式报「结果文件不可用」（同「扫描空转 ≠ 无发现」的既有口径，issue #3631）。
    """
    b = int(payload.get("blocker_count") or 0)
    w = int(payload.get("warning_count") or 0)
    n_b = len(payload.get("blockers") or [])
    n_w = len(payload.get("warnings") or [])
    if b != n_b:
        return f"blocker_count={b} 与 blockers 清单 {n_b} 条不一致"
    if w != n_w:
        return f"warning_count={w} 与 warnings 清单 {n_w} 条不一致"
    return None


def _blocker_entry(index, blocker):
    """单条 blocker 的**条目行**：`file` + 可操作说明（缺测清单 / G5 的 reason）。

    条目格式就是判据的载体（`tests/unit_ci_workflows/test_growth_gate_pr_comment.py`
    按「序号 + `. `」逐条解析、数条目并与 `blocker_count` 比对）。
    **不得**改成摘要式输出（如「6 处缺测」）—— 那正是 issue #5292 的现网形态：
    实施方看不到是哪几条，只能本地复跑才拿到清单。
    """
    req = [t for t in (blocker.get("required_tests") or []) if t]
    if req:
        action = "补 " + "、".join(f"`{t}`" for t in req)
    else:
        action = blocker.get("reason") or "缺配套测试（结果文件未给出清单）"
    return f"{index}. `{blocker.get('file', '?')}` — {action}（模块：{blocker.get('module') or '—'}）"


def render_pr_comment(payload):
    """把 `--json-file` 写出的**那一份**结果对象渲染成 PR 评论正文（**唯一数据源**）。

    输入必须是结果 JSON 解析出的对象本身：本函数**不**读文件、不读环境变量、不读
    `$GITHUB_STEP_SUMMARY`（结构性判据钉在 tests/unit_ci_workflows/test_growth_gate_pr_comment.py
    的 AST 面：函数体内不得出现 `open()` / `os.environ`）—— 另起一套渲染数据源必然与 JSON 漂移，
    而漂移的两处会让「job 为什么红」和「评论说了什么」各说各话。

    判据（issue #5292）：
    - `blocker_count > 0` ⇒ **逐条**列出每个 blocker 的 `file` + 缺测清单（`required_tests`）
      / G5 的 `reason`，条目数 == `blocker_count`（摘要式输出 = 不可归因）；
    - `blocker_count == 0` ⇒ 维持既有形态（`✅ 所有检查通过！`），**不加**清单噪音；
    - 末尾建议**不诱导加豁免**：只有在**已列出清单**时才提豁免，并写明「豁免面只许缩短」。
    """
    mismatch = result_mismatch(payload)
    if mismatch:
        return (_RESULT_UNUSABLE_PREFIX + "\n\n"
                f"> {mismatch}\n"
                "> ⇒ 门禁结论**不可归因**（不得据此判断通过与否）。请重跑本 job；"
                "若复现，请修 `.github/growth_gate.py` 的结果写出。\n")

    blockers = list(payload.get("blockers") or [])
    b = int(payload.get("blocker_count") or 0)
    w = int(payload.get("warning_count") or 0)

    if b > 0:
        icon, verdict = "❌", "BLOCKED"
        blocks = [f"### ❌ {b} 处缺测（阻塞合并）—— 逐条如下", ""]
        blocks += [_blocker_entry(i, bl) for i, bl in enumerate(blockers, 1)]
        blocks.append("")
        detail = [
            "",
            f"> ❌ **合并被阻塞**。请先按上面 {b} 条清单补齐缺失的测试。",
            "> 仅当**确有正当理由**时才走豁免（`.github/qa-exemptions.yml`）"
            "—— 本仓口径：**豁免面只许缩短**。",
            "> 详见 [docs/wiki/Testing.md](docs/wiki/Testing.md)",
        ]
    elif w > 0:
        icon, verdict = "⚠️", "WARNINGS"
        blocks = []
        detail = ["> ⚠️ 有警告但不阻塞合并。请尽快补充测试。"]
    else:
        icon, verdict = "✅", "PASSED"
        blocks = []
        detail = ["> ✅ 所有检查通过！"]

    return "\n".join([f"## {icon} QA Growth Gate — {verdict}", "", *blocks, "---",
                      f"**Blockers**: {b} | **Warnings**: {w}", *detail]) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="QA Growth Gate（数据驱动）")
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
    parser.add_argument("--new-tests-only", action="store_true",
                        help="配合 --check-weak：先按 _is_test_file 过滤掉非测试文件再扫"
                             "（调用方可能把候选文件与源文件混在一起传进来，见 issue #4077）")
    parser.add_argument("--check-weak-baseline", action="store_true",
                        help="全仓扫描弱断言并与锚点账本比对（存量只许非增、新文件 fail-closed，"
                             "见 issue #5080）；有增长退 1，账本缺失/损坏退 2（fail-closed）")
    parser.add_argument("--write-weak-baseline", action="store_true",
                        help="重锚定弱断言账本（**只许缩**：有增长即拒绝，见 --check-weak-baseline）")
    parser.add_argument("--weak-baseline", default=None,
                        help=f"锚点账本路径（默认 {WEAK_BASELINE_DEFAULT}）")
    parser.add_argument("--check-cases",
                        help="用例库目录（cases/*.yml）——启用 G5 用例追溯链：测试文件 ↔ 行为用例")
    parser.add_argument("--render-pr-comment", metavar="RESULT_JSON",
                        help="把 --json-file 写出的结果对象渲染成 PR 评论正文（stdout）——"
                             "CI 的 PR 评论**只**走这一条渲染路（单一数据源，issue #5292）；"
                             "结果文件缺失/损坏/自相矛盾 ⇒ 仍打印可发布的正文 + ::error:: + 退 2")
    args = parser.parse_args(argv)

    if args.render_pr_comment:
        # 结果对象 → PR 评论正文（issue #5292）。**唯一数据源 = 结果文件本身**：
        # 渲染不出正文时绝不允许退化成「发一条空评论」（那正是本 issue 的现网形态）
        # ⇒ 打印可发布的「结果文件不可用」正文 + `::error::` + 非零退出（fail-closed）。
        path = args.render_pr_comment
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("结果文件不是对象")
        except (OSError, ValueError) as e:
            print(_RESULT_UNUSABLE_PREFIX + "\n\n"
                  f"> 无法读取结果文件 `{path}`（{e.__class__.__name__}）——"
                  "门禁脚本未成功产出结果。\n"
                  "> ⇒ 门禁结论**不可归因**（不得据此判断通过与否）。请查看本 job 日志。\n")
            print(f"::error:: PR 评论渲染失败：无法读取结果文件 {path}（{e}）", file=sys.stderr)
            return 2
        print(render_pr_comment(payload))
        mismatch = result_mismatch(payload)
        if mismatch:
            print(f"::error:: PR 评论渲染：{mismatch}（结果文件不可用，见上）", file=sys.stderr)
            return 2
        return 0

    if args.check_weak_baseline or args.write_weak_baseline:
        # 存量锚点（issue #5080 盲区②）：`--check-weak` 只扫**新增**文件 ⇒ 存量永久免疫、
        # 没有燃尽出口；本分支给存量一个「只许非增」的机械载体。
        path = args.weak_baseline or WEAK_BASELINE_DEFAULT
        if args.write_weak_baseline:
            rc, _, _ = write_weak_baseline(args.repo_root, path)
        else:
            rc, _, _ = check_weak_baseline(args.repo_root, path)
        return rc

    if args.check_weak:
        if not args.files:
            print("⚠️ --check-weak 需配合 --files 指定测试文件")
            return 1
        # 只扫**测试文件**：候选文件里可能混着新增源文件（本地 `verify-all.sh gate` 把
        # 「已提交新增文件 ∪ 工作区新增文件」一并传来），判定走 `_is_test_file` 单一事实源
        # —— 门禁的扫描集与「测试文件」的定义必须同源，否则新增源文件会被当测试文件扫
        # ⇒ 报出 CI 不会报的红（issue #4077）。该步只缩小扫描集，**不放宽判定**：
        # 真弱断言仍逐个检出（解释器无关，纯文本扫描）。
        files = [f for f in args.files if f.strip()]
        if args.new_tests_only:
            kept = [f for f in files if _is_test_file(f)]
            if len(kept) < len(files):
                print(f"  ⏭️ 按测试文件判定剔除 {len(files) - len(kept)} 个非测试文件"
                      f"（新增源文件不参与弱断言扫描，与 CI 同一判定：_is_test_file）")
            files = kept
        if not files:
            print("✅ 候选文件中无新增测试文件，跳过弱断言检查")
            return 0
        total = 0
        for tf in files:
            try:
                weak = find_weak_asserts(tf)
            except ValueError as e:
                print(f"::error:: {e}", file=sys.stderr)
                print("❌ --check-weak 扫描失败即门禁失败（fail-closed）："
                      "文件不存在/不可读/编码异常 ≠ 无弱断言，见 issue #3631", file=sys.stderr)
                # 退出码 2（区别于「扫到了弱断言」的 1）：与本节规则源退化（tech-stack.yml
                # 缺失/规则为空 ⇒ return 2）同一 fail-closed 口径 —— 「扫描没跑成」与
                # 「跑成了且有发现」必须可区分。
                return 2
            print(f"📄 {tf}: {len(weak)} 处弱断言")
            for w in weak:
                print(f"  L{w['line_no']}: {w['line']}")
            total += len(weak)
        print(f"\n合计 {len(files)} 个测试文件，{total} 处弱断言")
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

    rule_errors: list = []
    rules = compile_rules(modules, test_commands, rule_errors)
    # fail-closed（本次收紧）：规则源**退化**必须报错，不得静默降级。
    # 病根：`rules` 为空（modules 被清空 / pattern 全非法）时，每个变更文件都落进
    # `classify_file` 的 `unmatched` 分支 —— 而 `unmatched` 既不是 blocker 也不是 warning
    # ⇒ `blocker_count = 0` ⇒ CI 的 `Fail on blocking violations` 不触发、`verify-all.sh gate`
    # 打 ✅。**编辑 `.github/tech-stack.yml` 本身不需要任何测试**（它 unmatched），
    # 所以「把 modules 清空」是一条现实的、不用改代码就能关掉整条缺测门禁的路
    # （2026-09-17 实测：`modules: []` ⇒ 真源码文件显示「ℹ️ 未识别，跳过」+ ✅ 全部通过）。
    if rule_errors:
        print(f"::error:: tech-stack.yml 有 {len(rule_errors)} 条规则无法编译 ⇒ 这些规则对应的"
              f"文件会静默落进 unmatched（缺测门禁失效）。规则源退化必须 fail-closed：", file=sys.stderr)
        for e in rule_errors:
            print(f"  · {e}", file=sys.stderr)
        return 2
    if not rules:
        print("::error:: tech-stack.yml 的 modules 为空（无任何可执行规则）⇒ 全部变更文件都会落进"
              " unmatched（既非 block 也非 warn）⇒ 缺测门禁整条失效。规则源退化必须 fail-closed："
              "要么恢复 modules，要么本门禁不成立（见 issue #3631 同族口径）。", file=sys.stderr)
        return 2
    files = args.files if args.files else get_changed_files(args.base)
    if files is None:
        print("::error:: growth_gate 无法获取变更文件清单（fail-closed：扫描失败 ≠ 无变更，见 issue #3631）",
              file=sys.stderr)
        return 2

    # 仅保留磁盘上存在的文件：git diff --name-only 会把「已删除/改名前的旧路径」也列入，
    # 这些路径无配套测试要求（issue #3051 知识卡片改名 + 旧知识库移除误报修复）。
    files = [f for f in files if os.path.exists(os.path.join(args.repo_root, f))]

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
