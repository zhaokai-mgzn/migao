#!/usr/bin/env python3
"""rework_hotspot_scan — 返工高频扫描：**同一文件/函数在 git 历史里被 fix 了多少次**（issue #4012 追加）。

## 为什么需要它

issue #4009 的「防复发执行纪律」把本批的病灶量化成一句话：
**fix 占比 6 月 56% / 7 月 66% / 9 月 61% —— 一直在修同一批地方**。
R1（修机制不修事故点）要求每个 PR 回答「**这个缺陷的同类实例还有几个？**」，
但那个回答目前只能靠人**记得**某处之前修过几次 —— 没有任何静态东西把它摆到台面上。

本脚本就是那台「摆到台面上」的机器：**零 LLM、秒级、纯 git 只读**，
按 `(文件, 函数)` 统计历史 fix 命中次数，命中阈值即报告。

## 它**不**做什么（诚实登记，防被读成门禁）

- **不阻塞**（永远 exit 0，除用法错误）—— 报告型，供人/agent 决策；
- **不判**「这次改动有没有修机制」—— 那需要读懂 diff 语义，本脚本只给**次数证据**；
- **不建基线、不写文件**（除 `--json` 显式指定）。

## 命中阈值要求的处置（issue #4012 原文）

> 命中阈值（建议 ≥5）时报告出来，供后续要求「机制级修法或登记独立 issue」。

⇒ 输出里对每个 hotspot 打印这条要求原文，避免读者把它当「仅供参考的统计」。

## 判据

- **fix 提交**：subject 命中 `fix|hotfix|bugfix|修复|修正|回归|regression|补丁|revert`
  （**词首/词内都算**，但 `prefix` 类词如 `fixup!`（squash 残留）显式排除）；
- **文件命中**：该提交的 diff 触及该文件；
- **函数命中**：该提交 diff 的**改动行区间**落在该文件当前版本的某个顶层函数/方法体内
  （按 `git diff -U0` 的 `@@` 头取区间，再映射到当前工作树的 AST 函数区间）。
  ⚠️ 用**当前**函数划分去回溯历史行号 —— 历史行号与今天不同，这里有已知的**近似**：
  函数被大改/搬走时命中会漂到邻居。故函数级结论一律标注为**近似**，文件级是**精确**的。
  这是有意取舍：精确方案（逐 commit 解析当时 AST）代价高一个量级，而本脚本的用途是
  **排序让人去看**，不是给出可引用的绝对数。

## 用法（仓根）

    python3 scripts/rework_hotspot_scan.py                    # 全历史，阈值 5，top 15
    python3 scripts/rework_hotspot_scan.py --threshold 3 --top 30
    python3 scripts/rework_hotspot_scan.py --paths backend/ai-agent-service/app scripts
    python3 scripts/rework_hotspot_scan.py --json /tmp/rework.json
    python3 scripts/rework_hotspot_scan.py --ref HEAD          # 只扫到某个 rev
    python3 scripts/rework_hotspot_scan.py --max-commits 2000  # 大仓提速

退出码：0 = 报告完成（**无论有没有命中**）；2 = 用法错误。**不做门禁判定。**
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── 判据 ①：fix 提交识别 ──────────────────────────────────────────────────────
#
# 形态取**既有事实**（本仓 commit subject 实录），不引入新语料：
#   `fix(scope): …` / `fix: …` / `修复…` / `Hotfix …` / `Revert "…"` / `regression`
# 注意：`fixup!` 是 interactive rebase 的 autosquash 残留，**不是**一次独立修复 ⇒ 排除。
_FIX_RE = re.compile(
    r"(?i)(?<![a-z])(fix|fixes|fixed|hotfix|bugfix|修复|修正|订正|回归|regression|补丁|revert)"
)
_NOT_FIX_RE = re.compile(r"(?i)^\s*fixup!|^\s*squash!")

# ── 判据 ②：哪些提交算「有待分析改动」 ────────────────────────────────────────
_MERGE_SUBJECT_RE = re.compile(r"^Merge (branch|pull request|remote-tracking)")

#: 默认只看代码面（文档/生成物不参与「返工热区」排序）
DEFAULT_PATHS: tuple[str, ...] = (
    "backend/ai-agent-service/app",
    "backend/admin-api/src/main",
    "frontend/admin-web/src",
    "frontend/mini-app/src",
    "scripts",
    ".github",
)

#: 生成物/账本类文件不参与排序（它们被高频改写是**设计如此**，不是返工信号）
_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    "/eval_cases.py",
    "/mibao-verification-cases.md",
    "/CHANGELOG.md",
    "/package-lock.json",
    "/pnpm-lock.yaml",
)


def is_fix_subject(subject: str) -> bool:
    """该 commit subject 是否表示一次修复（判据单一实现，测试直接驱动它）。"""
    if _NOT_FIX_RE.search(subject):
        return False
    return bool(_FIX_RE.search(subject))


def _run_git(args: list[str], repo: Path) -> str:
    # errors="replace"：diff 里可能夹着非 UTF-8 字节（实测一次几十 MB 的 show 输出在
    # 0xa9 处炸掉整轮扫描）—— 本脚本只读**结构**（路径 / @@ 头），不读内容语义，
    # 故替换坏字节是安全的；绝不让一个坏字节把整轮扫描变成 Traceback。
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc.stdout


def commit_subjects(repo: Path, ref: str, max_commits: int | None) -> list[tuple[str, str]]:
    """`[(sha, subject)]`（跳过 merge 提交），新→旧。"""
    out = _run_git(
        ["log", "--no-merges", "--pretty=format:%H%x1f%s%x1e", ref]
        + ([f"--max-count={max_commits}"] if max_commits else []),
        repo,
    )
    commits: list[tuple[str, str]] = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, _, subject = record.partition("\x1f")
        subject = subject.strip()
        if not subject or _MERGE_SUBJECT_RE.match(subject):
            continue
        commits.append((sha, subject))
    return commits


def changed_files_and_ranges(
    repo: Path, sha: str,
) -> tuple[list[str], dict[str, list[tuple[int, int]]]]:
    """**一次** `git show` 同时取「改动文件」与「每个文件在新版本里的改动行区间」。

    合并两次 git 调用是本脚本的主要提速手段（实测大提交的 `git show` 输出可达几十 MB）。
    `git diff` 天然**跟随重命名**（不带 `--no-renames`），故文件级判据对改名不敏感；
    区间只对 `+++ b/<path>` 的**新路径**累计。

    ⚠️ `+++ ` 也会出现在 **hunk 内容**里（被改动的行本身以 `+` 开头）—— 这是最阴的坑：
    必须用「当前是否在 hunk 内」这个状态机区分 **文件头** 与 **内容行**，
    否则一行内容 `+ "+++ b/xxx"` 会把后续区间挂到错误的文件上。
    """
    out = _run_git(["show", "--format=", "--unified=0", sha], repo)
    files: list[str] = []
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    current: str | None = None
    in_hunk = False
    for line in out.split("\n"):
        if line.startswith("@@ "):
            in_hunk = True
            if current is None:
                continue
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count == 0:  # 纯删除：落在该行位置
                ranges[current].append((max(start, 1), max(start, 1)))
            else:
                ranges[current].append((start, start + count - 1))
            continue
        if line.startswith("diff --git "):
            in_hunk = False
            current = None
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            in_hunk = False
            path = line[4:].strip()
            if path == "/dev/null":
                current = None
                continue
            current = path[2:] if path.startswith("b/") else path
            if current not in files:
                files.append(current)
            continue
        if in_hunk and line[:1] in ("+", "-"):
            continue  # hunk 内容行：不参与任何解析（见 docstring 的坑）
    return files, dict(ranges)


# ── 函数区间（用**当前工作树**的 AST；见文件头的近似声明）──────────────────────


def function_spans(source: str) -> list[tuple[str, int, int]]:
    """`[(qualname, start_line, end_line)]` —— 顶层函数 + 类方法（含嵌套一层）。

    `qualname` 形态：`func_name` / `Class.method`（便于人读与跨文件比对）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: list[tuple[str, int, int]] = []

    def _end(node: ast.AST) -> int:
        return max(
            [node.lineno] + [n.lineno for n in ast.walk(node) if hasattr(n, "lineno")],
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.name, node.lineno, _end(node)))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    spans.append((f"{node.name}.{sub.name}", sub.lineno, _end(sub)))
    return spans


def _hit(spans: list[tuple[str, int, int]], ranges: list[tuple[int, int]]) -> set[str]:
    """改动区间命中的函数名集合。"""
    names: set[str] = set()
    for name, lo, hi in spans:
        for rlo, rhi in ranges:
            if rlo <= hi and rhi >= lo:
                names.add(name)
                break
    return names


def scan(
    repo: Path,
    ref: str = "HEAD",
    paths: tuple[str, ...] = DEFAULT_PATHS,
    max_commits: int | None = None,
) -> dict:
    """扫描并返回报告数据结构（**纯读**：不改工作树、不写文件）。"""
    commits = commit_subjects(repo, ref, max_commits)
    file_fix: Counter[str] = Counter()          # 文件 → fix 次数
    file_all: Counter[str] = Counter()          # 文件 → 总改动次数
    func_fix: Counter[str] = Counter()          # "file::func" → fix 次数
    func_shas: dict[str, list[str]] = defaultdict(list)
    file_shas: dict[str, list[str]] = defaultdict(list)
    spans_cache: dict[str, list[tuple[str, int, int]]] = {}

    fix_total = 0
    for sha, subject in commits:
        is_fix = is_fix_subject(subject)
        fix_total += int(is_fix)
        files, ranges_by_file = changed_files_and_ranges(repo, sha)
        for path in files:
            if _EXCLUDE_SUFFIXES and any(path.endswith(s) for s in _EXCLUDE_SUFFIXES):
                continue
            if paths and not any(path.startswith(p) for p in paths):
                continue
            file_all[path] += 1
            if not is_fix:
                continue
            file_fix[path] += 1
            file_shas[path].append(sha[:8])
            abs_path = repo / path
            if abs_path.suffix != ".py" or not abs_path.exists():
                continue
            if path not in spans_cache:
                spans_cache[path] = function_spans(abs_path.read_text(encoding="utf-8", errors="ignore"))
            for func in _hit(spans_cache[path], ranges_by_file.get(path, [])):
                key = f"{path}::{func}"
                func_fix[key] += 1
                func_shas[key].append(sha[:8])

    return {
        "repo_commits": len(commits),
        "fix_commits": fix_total,
        "fix_ratio": round(fix_total / len(commits), 4) if commits else 0.0,
        # **全部被分析到的文件**都进报告（fix 次数可以为 0）—— 只收 fix>0 的文件会让
        # 「0 次 fix」与「压根没扫到」在输出里长得一样（空跑与真结论不可区分）。
        "files": {p: {"fix": file_fix.get(p, 0), "all": n, "shas": file_shas[p][:12]}
                  for p, n in file_all.items()},
        "functions": {k: {"fix": n, "shas": func_shas[k][:12]} for k, n in func_fix.items()},
    }


# ── 渲染 ──────────────────────────────────────────────────────────────────────


def render(report: dict, threshold: int, top: int, approx_note: bool = True) -> str:
    """人读报告（**必须**包含处置要求原文 —— 否则被读成「仅供参考的统计」）。"""
    files = sorted(
        ((p, d) for p, d in report["files"].items() if d["fix"] >= threshold),
        key=lambda kv: (-kv[1]["fix"], kv[0]),
    )[:top]
    funcs = sorted(
        ((k, d) for k, d in report["functions"].items() if d["fix"] >= threshold),
        key=lambda kv: (-kv[1]["fix"], kv[0]),
    )[:top]

    lines = [
        "═" * 78,
        "返工高频扫描（issue #4012 追加）—— 同一文件/函数在 git 历史里被 fix 的次数",
        "═" * 78,
        f"扫描范围：{report['repo_commits']} 个非 merge 提交，其中 fix {report['fix_commits']} 个"
        f"（占比 {report['fix_ratio']:.1%}）",
        f"阈值：≥{threshold} 次 fix 命中即报告（建议值，来自 issue #4012）",
        "",
        f"── 文件级（精确：该提交 diff 触及该文件）TOP {len(files)} ──",
    ]
    if not files:
        lines.append(f"  （无 —— 没有文件被 fix ≥{threshold} 次）")
    for path, data in files:
        lines.append(f"  {data['fix']:>3} 次 fix / {data['all']:>3} 次改动  {path}")
        lines.append(f"        最近：{' '.join(data['shas'][:6])}")

    lines += ["", f"── 函数级（**近似**：按当前工作树的函数区间回溯历史行号）TOP {len(funcs)} ──"]
    if approx_note:
        lines.append(
            "  ⚠️ 函数划分取**今天**的 AST；函数被大改/搬走时命中会漂到邻居。"
            "用于**排序让人去看**，不作为可引用的绝对数。"
        )
    if not funcs:
        lines.append(f"  （无 —— 没有函数被 fix ≥{threshold} 次）")
    for key, data in funcs:
        lines.append(f"  {data['fix']:>3} 次 fix  {key}")
        lines.append(f"        最近：{' '.join(data['shas'][:6])}")

    lines += [
        "",
        "── 命中后的处置（issue #4012 原文，非建议）──",
        "  「命中阈值时报告出来，供后续要求**机制级修法或登记独立 issue**。」",
        "  → R1：修机制，不修事故点。每个此类 PR 必须回答「这个缺陷的同类实例还有几个？」；",
        "  → R4：**不得**把新发现的违规登记进豁免清单（只许移除）。",
        "  → 本报告**不阻塞**任何合并（报告型）—— 但 hotspot 上的改动必须给出机制级说明。",
        "═" * 78,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="返工高频扫描（报告型，不阻塞）")
    parser.add_argument("--repo", default=None, help="仓库根（默认：本脚本的上两级目录）")
    parser.add_argument("--ref", default="HEAD", help="扫描到哪个 rev（默认 HEAD）")
    parser.add_argument("--threshold", type=int, default=5, help="fix 次数阈值（默认 5）")
    parser.add_argument("--top", type=int, default=15, help="每类展示前 N 条（默认 15）")
    parser.add_argument("--paths", nargs="*", default=list(DEFAULT_PATHS),
                        help="只看这些路径前缀（默认：代码面）")
    parser.add_argument("--max-commits", type=int, default=None, help="最多扫描多少个提交")
    parser.add_argument("--json", default=None, help="把报告写到该 JSON 路径")
    args = parser.parse_args(argv)

    if args.threshold < 1 or args.top < 1:
        print("用法错误：--threshold / --top 必须 ≥1", file=sys.stderr)
        return 2

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists():
        print(f"用法错误：{repo} 不是 git 仓库根", file=sys.stderr)
        return 2

    report = scan(repo, ref=args.ref, paths=tuple(args.paths), max_commits=args.max_commits)
    print(render(report, args.threshold, args.top))
    if args.json:
        Path(args.json).write_text(
            json.dumps({"threshold": args.threshold, **report}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[report] 已写入 {args.json}")
    return 0  # ← 报告型：**任何命中都不改变退出码**（不阻塞）


if __name__ == "__main__":
    raise SystemExit(main())