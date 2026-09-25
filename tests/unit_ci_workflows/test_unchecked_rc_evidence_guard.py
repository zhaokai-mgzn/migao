# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""类级元守卫：「`check=False` 的子进程调用**把 stdout 当证据**」必须判退出码（issue #5430）。

## 病根（一类缺陷，不是一个缺陷）

`git rev-parse <ref>` 在 `ref` **不存在**时把 `<ref>` **原样回显**到 stdout（并返回非零）。
判据里写成 `x = git(..., check=False).stdout.strip()` 就等于**把进程对象丢掉** ⇒ 结构上无从判 rc
⇒ **回显被当成数据**。#5430 的实测形态：回显 `"origin/main"` 被当基线 sha ⇒ 打印
「活锚检出拥有基线提交 origin/main（同一份历史）」这种**伪造读数**；若活锚里恰好没有该字面量 ref，
则反手判「不同源」⇒ **exit 0 = 与「通过」同一个退出码**（判据在最需要它的场景下静默失效）。

⇒ 本判据把这一**形态**冻死：射程内任何「`check=False` + `.stdout` 当数据 + 同函数内不读 `.returncode`」
的子进程调用 ⇒ **未登记即红**。豁免台账只许缩短（§23 G2 燃尽靶子）。

## 判据（**AST 取法**，不读散文 —— 与本仓「原文口径」族刻意区分）

对射程内每个文件的每个函数：

| 形态 | 判定 |
|---|---|
| 调用点直接摘 stdout（`x = git(..., check=False).stdout.strip()`，进程对象被丢掉） | ❌ 红（**不可能**判过 rc） |
| 先命名、只读它的 `.stdout`（`p = git(..., check=False)` … `p.stdout`），而同函数内**从未**读 `p.returncode` | ❌ 红 |
| 命名了、**读过** `p.returncode`（`if p.returncode != 0: …`） | ✅ 放行（正常用法） |
| `check=True`（失败即抛） | ✅ 放行 |
| `check=False` 但只读 `.returncode`（只关心成败） | ✅ 放行（不摘 stdout） |

## 豁免台账 = `unchecked_rc_evidence_allowlist.json`（数据文件，**diff 里看得见**）

- 每条必须有 `reason` + `issue`（缺任一项 ⇒ 红）；`hits` 是**现取条数**（不写死解释性上限）；
- **只许缩短**：未登记的命中 ⇒ 红；已登记文件的命中数涨或跌 ⇒ 红；条目陈旧（已无命中）⇒ 红；
- 燃尽锚点 = 条目数与 `hits` 之和，每次运行打印（§23 G2）。

## 有意不做的（照实登记，**不是**「已覆盖」）

- 射程 = `scripts/*.py` + `.github/*.py`（**不递归下游目录**，与仓内其它 Python 判据面一致）；
  `tests/**` 不在射程内（那里没有判据本体）。
- **已知盲区**：本判据只认「`.stdout` 当数据」这一形态 —— 「读了 rc，但把某个非零 rc 当空读数」
  （例如把 `git show-ref --verify` 的 `1`（无此 ref）与 `128`（根本不是仓库）混同）**看不见**。
  同理，stderr 面、以及 rc 被读但**读错分支**的形态，都不在射程内。
"""
from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).resolve().parent / "unchecked_rc_evidence_allowlist.json"
#: 射程（**结构化声明**，与 `_scoped_files()` 同一份来源；改射程只需改这一处，diff 里看得见）。
GUARD_SCOPE = {"roots": ["scripts", ".github"], "glob": "*.py"}
#: 子进程调用名（`git` / `git_bytes` / `_git` / `_run` 是本仓的薄封装；`run` / `check_output` 是属性调用）。
PROC_NAMES = {"git", "git_bytes", "_git", "_run", "run", "check_output"}
#: 命中即红、**不接受登记**的文件（#5430 的判据本体 —— 它已收口，回归必须立刻可见）。
FIXED_FILE = "scripts/agent-presets-guard.py"


def _scoped_files(root: Path = REPO_ROOT) -> list[str]:
    """射程内的文件（仓库相对路径，排序）—— **现取**，不写死清单。"""
    out: list[str] = []
    for base in GUARD_SCOPE["roots"]:
        d = root / base
        if not d.is_dir():
            continue
        out += [p.relative_to(root).as_posix() for p in d.glob(GUARD_SCOPE["glob"]) if p.is_file()]
    return sorted(out)


def _is_proc_call(node: ast.AST) -> bool:
    """该节点**就是**那个子进程调用（`git(...)` / `subprocess.run(...)`）。"""
    if not isinstance(node, ast.Call):
        return False
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    return name in PROC_NAMES


def _chain(node: ast.AST) -> tuple[list[str], ast.AST]:
    """→ (自顶向下的属性/方法名链, 链根)，**遇到子进程调用本身即停**（它才是进程对象）。

    `p.stdout.strip()` ⇒ (['strip','stdout'], Name('p'))；
    `git(...).stdout.strip()` ⇒ (['strip','stdout'], Call(git…))。
    """
    attrs: list[str] = []
    n = node
    while True:
        if _is_proc_call(n):
            return attrs, n
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            attrs.append(n.func.attr)
            n = n.func.value
            continue
        if isinstance(n, ast.Attribute):
            attrs.append(n.attr)
            n = n.value
            continue
        return attrs, n


def _proc_call(node: ast.AST) -> ast.Call | None:
    """链根归约到那个**子进程调用**（不是 ⇒ `None`）。"""
    _, root = _chain(node)
    return root if _is_proc_call(root) else None


def _checks_false(call: ast.Call) -> bool:
    """该调用显式 `check=False`（`check=True` 失败即抛 ⇒ 不必判 rc）。"""
    for kw in call.keywords:
        if kw.arg == "check" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
    return False


def _assignment_call(fn: ast.AST, name: str) -> ast.Call | None:
    """函数内把 `name` 赋成子进程调用的那次调用（取不到 ⇒ `None`）。"""
    for p in ast.walk(fn):
        if not isinstance(p, (ast.Assign, ast.AnnAssign)):
            continue
        targets = p.targets if isinstance(p, ast.Assign) else [p.target]
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        if p.value is None:
            continue
        call = _proc_call(p.value)
        if call is not None:
            return call
    return None


def census(root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """→ {仓库相对路径: [命中说明, …]}（AST 取法；`check=True` 与「rc 读过」不命中）。"""
    hits: dict[str, list[str]] = {}
    for rel in _scoped_files(root):
        path = root / rel
        with warnings.catch_warnings():
            # 解析**别的**模块源码时 Python 会替它们报源码里的告警（非 raw 字符串的无效转义等）——
            # 那不是本判据的问题，不该污染 CI 日志（与 test_guard_parse/ scope 元守卫同做法）。
            warnings.simplefilter("ignore")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:      # 解析不了 ⇒ 红（不得静默跳过，否则射程内可以藏东西）
                hits.setdefault(rel, []).append(f"<源码无法解析（判据不得静默跳过）：{exc}>")
                continue
        seen: set[tuple[str, int]] = set()
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for fn in functions:
            rc_read = {
                a.value.id for a in ast.walk(fn)
                if isinstance(a, ast.Attribute) and a.attr == "returncode" and isinstance(a.value, ast.Name)
            }
            for expr in ast.walk(fn):
                if not isinstance(expr, ast.expr):
                    continue
                attrs, root_node = _chain(expr)
                if "stdout" not in attrs or "returncode" in attrs:
                    continue
                if isinstance(root_node, ast.Name):
                    # 命名后只读 stdout：同函数内读过该名字的 rc ⇒ 正常用法（放行）
                    if root_node.id in rc_read:
                        continue
                    call = _assignment_call(fn, root_node.id)
                else:
                    call = _proc_call(expr)      # 调用点直接摘 stdout（进程对象被丢掉）
                if call is None or not _checks_false(call):
                    continue
                key = (fn.name, call.lineno)
                if key in seen:
                    continue
                seen.add(key)
                hits.setdefault(rel, []).append(
                    f"{fn.name}()（第 {call.lineno} 行）：`{ast.unparse(expr)[:70]}` —— "
                    "把 `check=False` 调用的 stdout 当证据却没判 `.returncode`"
                )
    return hits


def _entries(path: Path = LEDGER_PATH) -> dict[str, dict]:
    """台账条目（缺文件 ⇒ fail-closed 抛错，**不是**静默跳过）。"""
    if not path.exists():
        raise AssertionError(f"台账不存在：{path} —— 本判据 fail-closed（缺台账 = 无人管，不是「无需登记」）")
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise AssertionError(f"台账格式错（缺 `entries` 对象）：{path}")
    return entries


def _fixture_root(tmp: Path, files: dict[str, str]) -> Path:
    """只含注入文件的临时根（**真解析真源码**，不 mock 判据）。"""
    for rel, body in files.items():
        target = tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return tmp


# ── 判据本体：现状普查 ≡ 台账（未登记即红 / 只许缩短 / 条目须活着）────────────────

def test_census_matches_ledger_and_guard_body_is_clean():
    """① 射程内**未登记即红**；② 台账**只许缩短**（条目须活着 + 条数现取）；③ 守卫本体已收口。"""
    hits = census()
    entries = _entries()
    total = sum(len(v) for v in hits.values())
    print(f"\n[燃尽锚点] 台账条目 = {len(entries)} / 命中 = {total}（条目 + 命中 = {len(entries) + total}）")
    for rel, why in sorted(hits.items()):
        print(f"  命中 {rel}：{len(why)} 处")
        for line in why:
            print(f"     - {line}")

    # ③ #5430 的判据本体：形态**不得复活**（这条红了就说明修好的那处被改回去了）
    assert FIXED_FILE not in hits, (
        f"{FIXED_FILE} 又出现「`check=False` + stdout 当证据」的形态 —— #5430 的病灶复活：\n"
        + "\n".join(hits.get(FIXED_FILE, []))
    )

    for rel, why in hits.items():
        entry = entries.get(rel)
        if entry is None:
            raise AssertionError(
                f"{rel} 有 {len(why)} 处未登记命中 ⇒ 要么判 `.returncode`，要么按台账纪律登记"
                f"（`reason` + `issue` + 现取 `hits`）：\n" + "\n".join(why)
            )
        assert entry.get("hits") == len(why), (
            f"{rel} 的 `hits` 与现取条数不符（台账**只许缩短**，且数字必须现取）："
            f"台账 {entry.get('hits')} ≠ 实测 {len(why)}"
        )
    for rel, entry in entries.items():
        assert rel in hits, f"台账条目陈旧：{rel} 已无命中 ⇒ 必须删掉该条（只许缩短）"
        for field in ("reason", "issue"):
            assert str(entry.get(field) or "").strip(), f"台账条目缺 `{field}`：{rel}"


def test_ledger_missing_fails_closed(tmp_path: Path):
    """缺台账 ⇒ **fail-closed 抛错**（不得静默「无豁免 ⇒ 通过」）。"""
    try:
        _entries(tmp_path / "nope.json")
    except AssertionError as exc:
        assert "fail-closed" in str(exc)
    else:
        raise AssertionError("台账缺失时没有 fail-closed —— 判据会静默空跑")


# ── 红证：判据有判别力（注入 ⇒ 必红；正常用法 ⇒ 不得误伤）──────────────────────

_INJECTED = '''import subprocess


def leak(ref):
    out = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True,
                         check=False).stdout.strip()
    return out
'''

_OK_NAMED = '''import subprocess


def ok_named(ref):
    proc = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()
'''

_OK_RAISING = '''import subprocess


def ok_raising(ref):
    return subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True,
                          check=True).stdout.strip()
'''


def test_injected_shape_is_caught(tmp_path: Path):
    """**红证**（判据不是空断言）：注入「调用点直摘 stdout」⇒ 必须命中。"""
    root = _fixture_root(tmp_path / "inject", {"scripts/leak.py": _INJECTED})

    hits = census(root)

    assert list(hits) == ["scripts/leak.py"], hits
    assert len(hits["scripts/leak.py"]) == 1, hits
    assert "leak()" in hits["scripts/leak.py"][0]


def test_injected_named_shape_is_caught(tmp_path: Path):
    """**红证**（第二种形态）：命名了但同函数内**从未**读 `.returncode` ⇒ 同样必须命中。"""
    root = _fixture_root(tmp_path / "inject-named", {"scripts/leak2.py": '''import subprocess


def leak_named(ref):
    proc = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True, check=False)
    return proc.stdout.strip()
'''})

    hits = census(root)

    assert list(hits) == ["scripts/leak2.py"], hits
    assert "leak_named()" in hits["scripts/leak2.py"][0]


def test_named_shapes_are_not_flagged(tmp_path: Path):
    """**负控**（别误伤正常用法）：命名后判 `rc` / `check=True` 摘 stdout ⇒ 0 命中。"""
    root = _fixture_root(tmp_path / "clean", {"scripts/ok.py": _OK_NAMED + _OK_RAISING})

    assert census(root) == {}