#!/usr/bin/env python3
"""合并后 main 侧守护腿（`migao-dev-flow` §23.7 **A2** 的机械化，issue #5423）。

## 病根（2026-09-24 现场，不是推演）

`pr-check` **只在 `pull_request` 触发** ⇒ **main 上的破坏没有任何 run 会报**：

- `#5396` 新增了一条判据（装配层字段 ⊆ DA-016 契约键清单，`tests/unit_ci_workflows/
  test_wiring_status_case_truth_sync.py` 的 C3），**但同一 PR 没把 DA-016 的清单补上**
  ⇒ **半成品落 main**；
- 该判据在**它自己的 PR** 上是绿的（当时数据与判据同刻），合并后 main 立刻是红的
  —— 属 `migao-dev-flow` §23.8 **B3「当时绿 ≠ 合并后绿」**；
- 它爆在**下一次任何 PR** 的 required 检查（`ci workflow helper unit tests`）上
  ⇒ **卡住全队列**，最后由人花一整轮做热修（`#5405`）+ 给 4 个分支逐一 rebase 才解开。

## 本腿判什么（一句话）

**把「本次落入 main 的变更」里**被判据引用**的那些判据重跑一遍** —— 判据与它约束的数据
不同刻落地 ⇒ 这些判据必红 ⇒ 合并后**分钟级**就能发现，而不是等下个 PR 撞上。

## 为什么是「定向跑」而不是 `./verify-all.sh quick`（实测判据，不是口味）

1. **`quick` 的判定面根本不含本例的判据**：`quick` 档的检查项 = admin-api 单测 / ai-agent 单测 /
   admin-web vitest / tsc / worker-h5 node 测试 / QA Growth Gate / UI 回退 / 覆盖体检 —— **没有一项**
   跑 `tests/unit_ci_workflows`（可自证：`sed -n '/^  quick)/,/^    ;;/p' verify-all.sh`）。
   而 `#5396` 爆红的正是 `pr-check.yml` 的 `ci workflow helper unit tests`（命令 =
   `python -m pytest tests/unit_ci_workflows -q`）⇒ **`quick` 抓不到这一类**（拿它当守护腿 =
   建一条永远绿的腿）。
2. **工具链成本**：`quick` 需要 JDK+Maven / npm / node / PG ⇒ main 侧每条腿都要冷启动这四个面；
   本腿只需要 `pytest` + `pyyaml`（+ 真库判据要的 PG **二进制**，不装服务，与 `pr-check` 同源）。
3. 定向跑的选择面随「本次变更触及了什么」走 ⇒ 常规合并只跑个位数判据（见 `--json` 读数）。

## 触发面为什么不止 `push`（实测：push 会被吞）

`on: push: branches: [main]` 是**必须**的那一面（合并后分钟级），**但它不可靠**：

- 实测（2026-09-24 本机 `gh run list --branch main --event push --limit 25`）：最近 ~15 次合并里
  **只有 2 次**产生了 main 上的 push run（`fca6ce3` #5395 / `54bd6c2` #5409），其余（含 `#5396`
  `e8fc247`、`#5405` `69458c2`、`#5412` `dfed199`）**零 push run**；
- 同根因的既有记录：`deploy-reconcile.yml` 头部「`deploy-*.yml` 的 push 主触发（已失效）」、
  `verify-trigger.yml` 头部 issue **#3113「push 被吞」**、`close-linked-issues.yml`（#3585）。
  ⇓ 结论：**只挂 push 的守护腿 = 多数合并根本不会跑它**（正是本单要消灭的「机制静默失效」形态）。
- ⇒ 本腿照既有范式（`deploy-reconcile.yml`）补**已被证明可靠**的那一面：
  `pull_request: [opened, reopened]`（新 PR 打开必触发 —— 恰好就是 `#5396` 破坏**爆在全队列**的那一刻）
  + `schedule`（定时兜底）+ `workflow_dispatch`（人工复算）。
- 另一面同样关键：**判定基准永远是 main 的当前状态**（不是 PR 的 head），全部输入来自
  **同一次 checkout 的同一次取数**（§23 G4）。⇒ 每条腿都是**幂等**的：重复跑不会得出不同结论。

## 判定面（**显式不判表**，§23 G5：面外不是安全区，必须写明）

判定面 = `tests/unit_ci_workflows/test_*.py`（`pr-check.yml` 的 `ci workflow helper unit tests` 的
同一批判据）。**命中规则**：本次变更的文件里，任一被判据**引用**（见 `_referenced`）⇒ 该判据入选。

- **不判**：其它测试面（`tests/unit/**` 的 vitest / Java 单测 / ai-agent 的 `tests/**`）—— 它们各自
  有自己的 PR 面与工具链成本，本腿**不假装覆盖它们**（原因：main 侧把它们跑全 = 每次合并 10 分钟级，
  与 §23 G8 的降成本口径冲突）。
- **可见性的前提 = 既有引用纪律**（`migao-dev-flow` §16.7）：判据若要读某文件，**必须把该文件的路径
  写成仓库相对全路径**（或写成 `REPO / "a" / "b"` 这类可静态解析的链）。否则本腿**看不见**它
  —— 因此 `--list-only` 会打印「**未命中（无判据引用）**」清单：看不见 ≠ 没问题，它每次都会出声。

## 三态退出码（`3` = 无法判定，**不得当** `0` 读）

`0` = 选中判据全绿（含**零动作**）；`1` = 有判据判红；`3` = 无法判定（git 不可用 / 窗口不可解析 /
pytest 不可运行）。零动作**必须出声**（§23 G6）：打印「零动作 + 原因」并 exit 0。

## 读数（§23 G8：禁挂钟当判据）

只报**与负载无关**的量：变更文件数 / 命中判据数 / 真正跑的判据数 / 跳过数 + 原因 / 未命中数。
**不**把 `pytest` 的墙钟时间当任何判据（`--json` 里也不记录它）。

一键复算（本机、零成本）：

    python3 scripts/post_merge_verify.py --list-only --lookback 40   # 只看选中面，不跑
    python3 scripts/post_merge_verify.py --lookback 40               # 真跑选中面
    python3 scripts/post_merge_verify.py --base <sha> --head <sha>   # 定向复算某次落地
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path

#: 判定面：与 `pr-check.yml` 的 `ci workflow helper unit tests` 同一批判据（单一实现 = 这里）。
FACE_DIR = "tests/unit_ci_workflows"
CRITERION_GLOB = "test_*.py"
#: 单次报告里打印的「未命中」清单上限（读数要可读，不能刷屏）。
UNMATCHED_PRINT_LIMIT = 12
#: pytest 摘要行里的跳过计数（`-rs` 会把原因打在正文里，这里只取计数做读数）。
SKIPPED_RE = re.compile(r"(\d+)\s+skipped")
PYTEST_MISSING_MARKERS = ("No module named pytest", "No module named 'pytest'")


class Undecidable(Exception):
    """无法判定 —— **必须**以退出码 3 表达，不得静默当成 0（§19.1 三态）。"""


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], repo)
    if proc.returncode != 0:
        raise Undecidable(f"git {' '.join(args)} 失败：{proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


# ═══════════════════════════════════════════════════════════════════════════
# 一、判据的引用面（AST 静态抽取 —— 不跑被检代码）
# ═══════════════════════════════════════════════════════════════════════════
def _has_parents_call(node: ast.AST) -> bool:
    """`Path(__file__).resolve().parents[2]` 这类表达式 ⇒ 仓库根（本目录的既有写法）。"""
    return any(isinstance(n, ast.Attribute) and n.attr == "parents" for n in ast.walk(node))


def _join(left: str, right: str) -> str:
    return f"{left.rstrip('/')}/{right.lstrip('/')}" if left else right.lstrip("/")


def _eval_path(node: ast.AST, names: dict[str, str]) -> str | None:
    """极小的静态求值器：只认 `<name> / "a" / "b"`、字面量、`Path(__file__).parents[2]`。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _eval_path(node.left, names), _eval_path(node.right, names)
        if left is None or right is None:
            return None
        return _join(left, right)
    if _has_parents_call(node):
        return ""  # 仓库根（`REPO = Path(__file__).resolve().parents[2]`）
    if isinstance(node, ast.Call):
        # `REPO.joinpath("a", "b")` / `Path("a")` —— 只认全字面量参数，认不出就放弃（不猜）。
        if node.args and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args):
            base = None
            if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
                base = _eval_path(node.func.value, names)
            elif isinstance(node.func, ast.Name) and node.func.id == "Path":
                base = ""
            if base is not None:
                out = base
                for a in node.args:
                    out = _join(out, a.value)  # type: ignore[arg-type]
                return out
    return None


def _docstring_ids(tree: ast.AST) -> set[int]:
    """模块 / 类 / 函数的**文档字符串**节点 id。

    🔴 必须剥掉：本仓已立过此教训（`#5323` / `#5338`「判据把**原文**当代码读」）。判据的 docstring
    里**列举别的守卫路径**（本仓惯例：写清「同类守卫 = tests/unit_ci_workflows/test_x.py」）是**说明**，
    不是**读入**。不剥则：改任意一个判据文件 ⇒ 几乎所有判据都"引用了它" ⇒ 定向跑退化成全量跑。
    （§23.8 **B1**：判据语料必须排除判据自身。这里是它的 AST 版。）
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                val = body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    ids.add(id(val))
    return ids


def _path_needles(src: str) -> tuple[set[str], set[str], set[str]]:
    """判据源码 ⇒ (可解析的仓库相对路径, 含 `/` 的路径片段, 模块名)。**只读代码，不读 docstring。**"""
    try:
        with warnings.catch_warnings():
            # 被解析的判据里可能有正则字面量（`"\."` 这类）⇒ `ast.parse` 会抛
            # `DeprecationWarning: invalid escape sequence`。那是**被解析文件的**工装噪声，
            # 不是本腿的结论；不吞掉它会让每个用它的人看到一条与本次判定无关的告警。
            warnings.simplefilter("ignore")
            tree = ast.parse(src)
    except SyntaxError:
        return set(), set(), set()

    names: dict[str, str] = {}
    for node in tree.body:  # 只认模块级赋值（顺序解析：先定义后使用）
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = _eval_path(node.value, names)
            if val is not None:
                names[node.targets[0].id] = val
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            val = _eval_path(node.value, names) if node.value is not None else None
            if val is not None:
                names[node.target.id] = val

    paths = {v for v in names.values() if v}
    docstrings = _docstring_ids(tree)
    fragments: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            text = node.value
            if text.startswith(("http://", "https://")) or "\n" in text:
                continue
            if "/" in text and not text.startswith("-"):
                frag = text.strip("/")
                # ⚠️ `strip("/")` 会把 `"/"` / `"/tmp"` 这类压成**空串或单段**，而 `"" in 任何路径`
                # 恒为真 ⇒ 一条这样的字面量就能让该判据命中**一切**变更（实测把 1 个文件的窗口
                # 撑成 45 条判据）。⇒ 片段必须仍含分隔符（≥2 段）才收。
                if "/" in frag:
                    fragments.add(frag)
            if text.endswith(".py"):
                # `tests/unit_ci_workflows/test_x.py` 这类**代码里的**点名 ⇒ 模块名也算引用
                modules.add(Path(text).stem)
        elif isinstance(node, ast.Import):
            modules.update(a.name.split(".")[-1] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[-1])
            modules.update(a.name for a in node.names)

    # 顶层常量（如 `.github`）单独放路径集里会让**任何** `.github/**` 变更命中所有判据
    # ⇒ 只保留 ≥2 段的具体路径（`.github/cases` 保留、`.github` 丢弃）。见模块 docstring 的命中规则。
    specific = {p for p in paths if len([c for c in p.strip("/").split("/") if c]) >= 2}
    return specific, fragments, modules


def _referenced(needles: tuple[set[str], set[str], set[str]], changed: str) -> bool:
    """变更文件 `changed` 是否被该判据引用（recall-first：宁可多选，不可漏选）。"""
    paths, fragments, modules = needles
    for p in paths:
        if changed == p or changed.startswith(p.rstrip("/") + "/") or p in changed or changed in p:
            return True
    for frag in fragments:
        if frag in changed or changed in frag:
            return True
    if changed.endswith(".py") and Path(changed).stem in modules:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 二、窗口与选择
# ═══════════════════════════════════════════════════════════════════════════
def _window(repo: Path, base: str | None, head: str | None, lookback: int) -> tuple[str, str, int, str]:
    """⇒ (base, head, 跨度, base 的来源)。来源要如实报出来（读数可归因，§23 G3）。"""
    head_sha = _git(repo, "rev-parse", "--verify", f"{(head or 'HEAD')}^{{commit}}")
    if base:
        base_sha, source = _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}"), "explicit(--base)"
    else:
        try:
            base_sha = _git(repo, "rev-parse", "--verify", f"HEAD~{lookback}^{{commit}}")
            source = f"lookback(HEAD~{lookback})"
        except Undecidable:
            # 历史不足 lookback 个提交 ⇒ 退到**根提交**（全历史），并把实际跨度报出来（不静默缩窗）。
            base_sha = _git(repo, "rev-list", "--max-parents=0", "HEAD").splitlines()[-1]
            source = f"root(历史不足 HEAD~{lookback} ⇒ 全历史)"
    span = int(_git(repo, "rev-list", "--count", f"{base_sha}..{head_sha}") or "0")
    return base_sha, head_sha, span, source


def _changed_files(repo: Path, base: str, head: str) -> list[str]:
    # `--no-renames`：重命名拆成 D+A ⇒ **旧路径也在清单里**（否则改名会把「被引用的旧路径消失」
    # 这类破坏从判定面里抹掉 —— 漏选比多选危险得多）。
    out = _git(repo, "diff", "--no-renames", "--name-only", base, head)
    return [line.strip() for line in out.splitlines() if line.strip()]


def select(changed: list[str], criteria: dict[str, tuple[set[str], set[str], set[str]]]) -> tuple[list[str], list[str]]:
    """⇒ (选中的判据, 未命中任何判据的变更文件)。判据**自身**变更 ⇒ 直接选中（Tier A）。"""
    changed_set = set(changed)
    selected, hit = [], set()
    for rel, needles in sorted(criteria.items()):
        if rel in changed_set:
            selected.append(rel)
            hit.add(rel)
            continue
        for f in changed:
            if _referenced(needles, f):
                selected.append(rel)
                hit.add(rel)
                break
    unmatched = [f for f in changed if f not in hit and not any(
        _referenced(n, f) for n in criteria.values())]
    return selected, unmatched


def collect_criteria(repo: Path) -> dict[str, tuple[set[str], set[str], set[str]]]:
    face = repo / FACE_DIR
    if not face.is_dir():
        raise Undecidable(f"判定面不存在：{face}")
    out = {}
    for path in sorted(face.glob(CRITERION_GLOB)):
        out[str(path.relative_to(repo))] = _path_needles(path.read_text(encoding="utf-8", errors="ignore"))
    if not out:
        raise Undecidable(f"判定面为空（{face}/{CRITERION_GLOB} 一个都没匹配到）⇒ 本腿会退化成空跑")
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 三、判定
# ═══════════════════════════════════════════════════════════════════════════
def run_selection(repo: Path, selected: list[str], python: str) -> tuple[int, str, int, str | None]:
    """跑选中的判据 ⇒ (rc, 输出, 跳过数, 无法判定的原因)。"""
    probe = _run([python, "-c", "import pytest"], repo)
    if probe.returncode != 0:
        return 3, probe.stderr.strip()[:300], 0, f"{python} 里没有 pytest ⇒ 无法判定（不等同于通过）"
    argv = [python, "-m", "pytest", *selected, "-q", "--tb=short", "-rs", "-p", "no:cacheprovider"]
    proc = _run(argv, repo)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and any(m in out for m in PYTEST_MISSING_MARKERS):
        return 3, out, 0, "pytest 不可运行 ⇒ 无法判定（不等同于通过）"
    skipped = int((SKIPPED_RE.search(out) or [0, 0])[1]) if SKIPPED_RE.search(out) else 0
    return proc.returncode, out, skipped, None


def render(report: dict) -> str:
    w = report["window"]
    lines = [
        "── 合并后 main 侧守护腿（migao-dev-flow §23.7 A2）──",
        f"判定基准：main 当前状态 head={w['head'][:7]}（窗口 {w['base'][:7]}..{w['head'][:7]}，"
        f"跨度 {w['span']} 个提交；来源 {report['base_source']}）",
        f"变更文件：{report['changed_count']} 个",
    ]
    if report["zero_action"]:
        lines += [
            f"零动作：{report['zero_action']}",
            "",
            "**这不是失败** —— 本腿只判「被判据引用的判据」，窗口内没有可判的东西。",
        ]
        if report["unmatched"]:
            lines += [f"未命中（无判据引用，共 {len(report['unmatched'])} 个）："]
            lines += [f"  - {p}" for p in report["unmatched"][:UNMATCHED_PRINT_LIMIT]]
            lines.append("  注：『未命中』= 没有判据把它的路径写成可解析的引用 ⇒ 本腿看不见它（不是「没问题」）。")
        lines += [
            "（读数：变更文件 "
            f"{report['changed_count']} / 命中判据 0 / 跑判据 0；『零动作』与『没跑』必须长得不一样。）",
        ]
        return "\n".join(lines)

    lines.append(f"命中判据：{report['selected_count']} 条")
    lines += [f"  - {p}" for p in report["selected"]]
    un = report["unmatched"]
    if un:
        shown = un[:UNMATCHED_PRINT_LIMIT]
        lines.append(f"未命中（无判据引用，共 {len(un)} 个）：")
        lines += [f"  - {p}" for p in shown]
        if len(un) > len(shown):
            lines.append(f"  - …（其余 {len(un) - len(shown)} 个略）")
        lines.append("  注：『未命中』= 没有判据把它的路径写成可解析的引用 ⇒ 本腿看不见它（不是「没问题」）。")
    lines += ["", f"命令（可复制）：python3 scripts/post_merge_verify.py --base {w['base']} --head {w['head']}", ""]
    if report["list_only"]:
        lines.append("（--list-only：只看选中面，**未跑判据** —— 这不是「通过」）")
    elif report["undecidable"]:
        lines.append(f"❌ **无法判定**：{report['undecidable']}")
    else:
        lines.append(f"pytest rc={report['rc']}，跳过 {report['skipped']} 条")
    if report["pytest_output"]:
        lines += ["", report["pytest_output"].rstrip(), ""]
    lines.append(
        "读数（与负载无关，§23 G8）：变更文件 "
        f"{report['changed_count']} / 命中判据 {report['selected_count']} / 跑判据 "
        f"{0 if report['list_only'] else report['selected_count']}"
        f" / 跳过 {report['skipped']} / 未命中 {len(un)}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="合并后 main 侧守护腿（定向跑判据面）")
    ap.add_argument("--repo", type=Path, default=None, help="仓库根（默认 = 本脚本的上一级）")
    ap.add_argument("--lookback", type=int, default=40, help="窗口 = HEAD~N..HEAD（默认 40）")
    ap.add_argument("--base", default=None, help="显式窗口起点（覆盖 --lookback）")
    ap.add_argument("--head", default=None, help="显式窗口终点（默认 HEAD）")
    ap.add_argument("--python", default=sys.executable, help="跑判据的解释器（默认 = 当前解释器）")
    ap.add_argument("--json", type=Path, default=None, help="机器可读报告落盘路径")
    ap.add_argument("--list-only", action="store_true", help="只打印选中面，不跑判据")
    args = ap.parse_args(argv)

    repo = (args.repo or Path(__file__).resolve().parents[1]).resolve()
    try:
        base, head, span, base_source = _window(repo, args.base, args.head, args.lookback)
        changed = _changed_files(repo, base, head)
        criteria = collect_criteria(repo)
    except Undecidable as exc:
        print(f"❌ 无法判定：{exc}", file=sys.stderr)
        return 3

    selected, unmatched = select(changed, criteria)
    report: dict = {
        "window": {"base": base, "head": head, "span": span},
        "base_source": base_source,
        "changed_count": len(changed),
        "changed": changed,
        "selected": selected,
        "selected_count": len(selected),
        "unmatched": unmatched,
        "skipped": 0,
        "rc": 0,
        "undecidable": None,
        "zero_action": None,
        "list_only": bool(args.list_only),
        "pytest_output": "",
    }
    if not selected:
        report["zero_action"] = (
            "窗口内没有新提交（base == head）—— 上一次成功验证之后没有任何东西落入 main"
            if len(changed) == 0
            else f"窗口内 {len(changed)} 个变更文件都未被任何判据引用（未触及判定面）"
        )
    elif not args.list_only:
        rc, out, skipped, undecidable = run_selection(repo, selected, args.python)
        report.update(rc=rc, pytest_output=out, skipped=skipped, undecidable=undecidable)

    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if report["undecidable"]:
        return 3
    if args.list_only or report["zero_action"]:
        return 0
    return 0 if report["rc"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())