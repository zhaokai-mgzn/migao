# case_ids: MC-012
"""「面内判据不得依赖**别的**判据往 `sys.modules` 注入模块」—— issue #5575 的类级锁。

## 病根（2026-09-25 实测读数，不是推演）

`post-merge-verify` 腿（`.github/workflows/post-merge-verify.yml`）是**按变更文件选子集**跑的
（`scripts/post_merge_verify.py` 的 Tier A/B）。`tests/unit_ci_workflows/test_flake_history_index.py`
会加载 `tests/agent_eval/local_runner.py`（模块级 `import httpx`），而 runner 镜像上本腿只装
`pytest + pyyaml` ⇒ **它单独被选中时 8 条全红**：

    ModuleNotFoundError: No module named 'httpx'

它在另一些 run 上是**绿**的 —— 只因某个**同批被选中**的 L0 判据在 import 期往 `sys.modules`
塞了 httpx 替身（`tests/unit_ci_workflows/test_code_ask_semantics_l0.py::_install_httpx_stub`）。
⇒「判据跑了」≠「判据真的能跑」：**绿是"选择"的事故**。换一批变更文件（哪怕只是加一条用例）
它当场红，而这两种 run 在 PR 页面上长得一样。

## 判据（一句话）

面内判据对「被注入 `sys.modules` 的模块」的需求，必须有**本文件之外**的正当来源 ——
它自己装（自己的替代实现）**或** 本腿 `Install deps` 步声明了它；**唯独不能是别的判据的注入**。

## 取法（结构化；**解析 AST，不读散文** —— 本仓已立过"判据把原文当代码读"的教训）

| 环 | 取法 | 为什么这样取 |
|---|---|---|
| 注入面 | AST：`sys.modules.setdefault("<M>", …)` / `sys.modules["<M>"] = …` / `…setitem(sys.modules, "<M>", …)`，键必须是**字面量** | 「谁往 sys.modules 塞了 M」是判据的**对象** ⇒ 现取，不写死 httpx |
| 需求面 | 判据 **import 期**的顶层 import（跳过函数/类体）逐个解析：仓库内模块（唯一同名 `.py`）**递归**跟进；`spec_from_file_location` 的加载目标（含"本文件带加载器 ⇒ 模块级路径常量"这一形态 —— `_load(RUNNER_PATH, …)` 正是它）一并递归 | #5575 的真实形态是**按路径动态加载** ⇒ 纯 import 图看不见它 |
| 正当来源 | ① 本文件自己注入该模块；② 本腿 `Install deps` 步的 `pip install` 名单里有它（`pyyaml` ⇒ `yaml`） | ② 就是本单的修法：**声明依赖**比让判据吃别人的注入诚实 |
| 判定 | `需求 ∩ 注入面 − 自装 − 已声明 ≠ ∅` ⇒ 红，并逐条点名「哪个文件 · 缺哪个模块 · 两条出口」 | 判红必须可归因（`migao-dev-flow` §23 G3） |

## 射程（**显式不判表**，§23 G5：面外不是安全区，必须写明）

- **判**：`tests/unit_ci_workflows/test_*.py`（= `ci workflow helper unit tests` 与合并后守护腿的同一批）。
- **不判**：
  - 注入**不在**注入面里的模块 —— 没人注入它 ⇒ 不是本类缺陷（那是"依赖没装"的另一个类）；
  - 键不是字面量的注入（`sys.modules[NAME] = …` / 从配置读的键）⇒ **看不见**（假绿方向，不会误伤）；
  - `pr-check.yml` 的**整目录**跑：它一次收集全部判据（注入必然先发生）⇒ 不在本类缺陷面上；
    本单不改它（超出本包授权面），**登记为射程之外的残余**；
  - `tests/smoke/**` / `tests/agent_eval/**` / Java / vitest 等其它测试面（各有自己的 CI 腿）。

## 未固化边界（照实登记，别读成"已覆盖"）

- 需求面是**静态**解析：把加载路径拼成运行时才知道的形态（f-string / 从 YAML 读）本判据看不见；
- 「本腿声明的依赖」只认 `post-merge-verify.yml` 里 `pip install` 的**具名**包；
  `-r requirements.txt` 这类**间接**声明不解析（本判据钉的是"这条腿自己把判据跑起来要什么"）；
- 「面内某个判据需要、而注入面里没有的第三方模块被漏装」不在射程内（见上）。
"""
from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FACE_DIR_REL = "tests/unit_ci_workflows"
FACE_GLOB = "test_*.py"
WORKFLOW_REL = ".github/workflows/post-merge-verify.yml"

#: 普查剪枝（与仓内其它普查同款：剪枝必须发生在**下降之前**）。
EXCLUDE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build",
    "coverage", ".mypy_cache", ".pytest_cache", "__pycache__",
})

#: 允许被**递归跟进**的仓库模块目录（判据面 + 它动态加载的脚本面）。
FOLLOW_DIRS = (".github", "scripts", "tests")


def _parse(path: Path) -> ast.Module | None:
    """解析失败 ⇒ None（**不静默当"没依赖"**：调用方按"无法判定"处理）。"""
    with warnings.catch_warnings():
        # 被解析的**别的**模块可能带无效转义序列告警（非本判据的问题，不该污染 CI 日志）。
        warnings.simplefilter("ignore")
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return None


def module_index(repo: Path) -> tuple[dict[str, list[Path]], set[str]]:
    """→ (`{模块名: [仓库内的 .py]}`, `{包名}`)（同行一次普查，剪枝在下降之前）。"""
    files: dict[str, list[Path]] = {}
    packages: set[str] = set()
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in names:
            if name.endswith(".py"):
                files.setdefault(Path(name).stem, []).append(Path(root) / name)
            if name == "__init__.py":
                packages.add(Path(root).name)
    return files, packages


def import_time_modules(tree: ast.Module) -> set[str]:
    """import 期被引入的**顶层**模块名（函数体/类体里的 import 不算 —— 它们不在 import 期执行）。"""
    found: set[str] = set()

    def walk(body: list) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                walk(node.body)
                walk(node.orelse)
                walk(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    walk(handler.body)
            elif isinstance(node, ast.With):
                walk(node.body)

    walk(tree.body)
    return found


def _literal_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def injected_modules(tree: ast.Module) -> set[str]:
    """本文件往 `sys.modules` 注入的模块名（键必须是**字面量**；散文/文档字符串里的提及不算）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "setdefault" and ast.unparse(node.func.value).endswith("sys.modules"):
                if node.args:
                    key = _literal_key(node.args[0])
                    if key:
                        out.add(key)
            elif node.func.attr == "setitem" and len(node.args) >= 2:
                if ast.unparse(node.args[0]).endswith("sys.modules"):
                    key = _literal_key(node.args[1])
                    if key:
                        out.add(key)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Subscript) and ast.unparse(target.value).endswith("sys.modules"):
                key = _literal_key(target.slice)
                if key:
                    out.add(key)
    return out


def _join(left: str, right: str) -> str:
    """与 `scripts/post_merge_verify.py::_join` **同口径**（左边为空 = 仓库根 ⇒ 不留前导斜杠）。"""
    return f"{left.rstrip('/')}/{right.lstrip('/')}" if left else right.lstrip("/")


def _eval_path(node: ast.AST, names: dict[str, str]) -> str | None:
    """极小静态求值器：`<name> / "a"`、字面量、`Path(__file__).parents[n]`、`Path("a")`。认不出 ⇒ None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _eval_path(node.left, names), _eval_path(node.right, names)
        if left is None or right is None:
            return None
        return _join(left, right)
    if any(isinstance(n, ast.Attribute) and n.attr == "parents" for n in ast.walk(node)):
        return ""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            base = _eval_path(node.func.value, names)
            if base is None:
                return None
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    base = _join(base, arg.value)
                else:
                    return None
            return base
        if isinstance(node.func, ast.Name) and node.func.id == "Path":
            base = ""
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    base = _join(base, arg.value)
                else:
                    return None
            return base
    return None


def _module_level_paths(tree: ast.Module) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target, value = node.target.id, node.value
        if target is None:
            continue
        resolved = _eval_path(value, names)
        if resolved is not None:
            names[target] = resolved
    return names


def load_targets(tree: ast.Module, repo: Path) -> set[Path]:
    """本文件把它当**模块加载**的仓库内 `.py`（import 已由调用方处理；这里是**动态加载**那一半）。

    形态（`tests/unit_ci_workflows/test_flake_history_index.py` 就是它）：
    文件里带 `spec_from_file_location(...)` ⇒ 模块级的 `.py` 路径常量即加载目标。
    """
    out: set[Path] = set()
    has_loader = any(
        isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == "spec_from_file_location")
            or (isinstance(n.func, ast.Name) and n.func.id == "spec_from_file_location")
        )
        for n in ast.walk(tree)
    )
    if not has_loader:
        return out
    names = _module_level_paths(tree)
    for value in names.values():
        if value.endswith(".py") and (repo / value).exists():
            out.add(repo / value)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        if fname == "spec_from_file_location":
            value = _eval_path(node.args[1], names)
            if value and value.endswith(".py") and (repo / value).exists():
                out.add(repo / value)
    return out


_CACHE: dict[tuple[str, str], tuple[dict[str, list[Path]], set[str]]] = {}


def _index_for(repo: Path):
    key = (str(repo), "index")
    if key not in _CACHE:
        _CACHE[key] = module_index(repo)
    return _CACHE[key]


def _trees_for(face_dir: Path) -> dict[Path, ast.Module | None]:
    key = (str(face_dir), "trees")
    if key not in _CACHE:
        _CACHE[key] = {p: _parse(p) for p in sorted(face_dir.glob(FACE_GLOB))}
    return _CACHE[key]


def _follow(name: str, repo: Path, files: dict[str, list[Path]]) -> Path | None:
    """模块名 → 仓库内的唯一实现（只跟进 `FOLLOW_DIRS` 下的文件；否则算外部依赖）。"""
    hits = [p for p in files.get(name, []) if len(p.parts) >= 2 and p.parts[-2] in FOLLOW_DIRS]
    return hits[0] if len(hits) == 1 else None


def required_external_modules(path: Path, repo: Path, seen: set[Path] | None = None) -> set[str]:
    """import 期（递归，含动态加载目标）需要、且**不在仓库内**的顶层模块名。"""
    seen = set() if seen is None else seen
    if path in seen:
        return set()
    seen.add(path)
    tree = _parse(path)
    if tree is None:
        return set()
    files, packages = _index_for(repo)
    out: set[str] = set()
    for name in sorted(import_time_modules(tree)):
        target = _follow(name, repo, files)
        if target is not None and target != path:
            out |= required_external_modules(target, repo, seen)
        elif target is None and name not in packages:
            out.add(name)
    for target in load_targets(tree, repo):
        out |= required_external_modules(target, repo, seen)
    return out


def declared_dependencies(repo: Path = REPO, workflow_rel: str = WORKFLOW_REL) -> set[str]:
    """本腿 `Install deps` 类步骤声明的模块名（**现取**：不写死 pytest/pyyaml/httpx）。

    `-r requirements.txt` 这种间接声明读不出具体包 ⇒ 不解析（见模块 docstring 的未固化边界）。
    """
    data = yaml.safe_load((repo / workflow_rel).read_text(encoding="utf-8"))
    names: set[str] = set()
    for job in (data.get("jobs") or {}).values():
        for step in (job.get("steps") or []):
            for line in (step.get("run") or "").splitlines():
                line = line.strip()
                if "pip install" not in line:
                    continue
                tokens = [t for t in line.split() if not t.startswith("-")]
                if "install" in tokens:
                    tokens = tokens[tokens.index("install") + 1:]
                names.update("yaml" if t == "pyyaml" else t for t in tokens)
    return names


def find_victims(face_dir: Path, repo: Path, installed: set[str]) -> dict[str, list[str]]:
    """→ `{判据文件（仓库相对路径）: [缺正当来源的模块名]}`；空 dict = 本判据全绿。"""
    trees = _trees_for(face_dir)
    surface: dict[str, list[str]] = {}
    for path, tree in trees.items():
        if tree is None:
            continue
        for name in injected_modules(tree):
            surface.setdefault(name, []).append(str(path))
    victims: dict[str, list[str]] = {}
    for path, tree in sorted(trees.items()):
        if tree is None:
            continue
        own = injected_modules(tree)
        missing = sorted(
            (required_external_modules(path, repo) & set(surface)) - own - installed
        )
        if missing:
            try:
                rel = path.resolve().relative_to(repo).as_posix()
            except ValueError:
                rel = path.name
            victims[rel] = missing
    return victims


# ═══════════════════════════════════════════════════════════════════════════
# 夹具（**两条注入式控制**）：证明本判据有牙齿，且不吃自己的说明文字
# ═══════════════════════════════════════════════════════════════════════════
INJECTOR = '''\
"""夹具：往 sys.modules 注入一个替身（形态与 #5575 的注入者同源）。"""
import sys
import types

_stub = types.ModuleType("fakemod")
sys.modules.setdefault("fakemod", _stub)
'''

BORROWER = '''\
"""夹具：**吃**别的判据的注入 —— 加载一个 import 期需要 fakemod 的仓库模块（#5575 的受害形态）。"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "pkg" / "consumer.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_borrower():
    _load(TARGET, "consumer")
'''

SELF_SUFFICIENT = '''\
"""夹具：**自己装** —— 既注入 fakemod，又加载需要它的模块（不受本判据约束）。"""
import importlib.util
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "pkg" / "consumer.py"

sys.modules.setdefault("fakemod", types.ModuleType("fakemod"))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_self_sufficient():
    _load(TARGET, "consumer")
'''

MENTION_ONLY = '''\
"""夹具：只在**说明文字**里提到 `sys.modules.setdefault("ghost", ...)` —— 不算注入（不得误伤）。"""
import sys


def test_mention_only():
    assert isinstance(sys.modules, dict)
'''

CONSUMER = '"""夹具：import 期需要 fakemod（= local_runner 里 `import httpx` 的同位形态）。"""\nimport fakemod\n'


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "fixture"
    face = repo / FACE_DIR_REL
    (repo / "pkg").mkdir(parents=True)
    face.mkdir(parents=True)
    (face / "test_injector.py").write_text(INJECTOR, encoding="utf-8")
    (face / "test_borrower.py").write_text(BORROWER, encoding="utf-8")
    (face / "test_self_sufficient.py").write_text(SELF_SUFFICIENT, encoding="utf-8")
    (face / "test_mention_only.py").write_text(MENTION_ONLY, encoding="utf-8")
    (repo / "pkg" / "consumer.py").write_text(CONSUMER, encoding="utf-8")
    return face, repo


# ═══════════════════════════════════════════════════════════════════════════
# 判据
# ═══════════════════════════════════════════════════════════════════════════
def test_no_face_criterion_depends_on_another_criterion_injecting_sys_modules():
    """**核心**：面内判据对「被注入的模块」的需求，必须有本文件之外的正当来源（issue #5575）。"""
    victims = find_victims(REPO / FACE_DIR_REL, REPO, declared_dependencies())
    assert victims == {}, (
        "这些判据**独自被选中**时跑不起来 —— 它们的依赖只由别的判据往 `sys.modules` 注入提供。"
        "`post-merge-verify` 腿按变更文件**选子集**跑 ⇒ 换一批变更就当场红，"
        "而这两种 run 在 PR 上长得一样（`migao-dev-flow` §23.8 B3：当时绿 ≠ 合并后绿）：\n  "
        + "\n  ".join(f"{f}：缺 {', '.join(mods)}" for f, mods in sorted(victims.items()))
        + "\n两条出口（任选，都能在本条腿自证）："
          "① 该文件在**模块级**自行提供替代实现（如 `test_code_ask_semantics_l0.py::_install_httpx_stub` 的形态）；"
          "② 在 `.github/workflows/post-merge-verify.yml` 的 `Install deps` 步**声明该依赖**"
          "（#5575 走的就是这条：声明依赖比吃别人的注入诚实）。"
    )


def test_the_declared_dependency_is_what_clears_the_httpx_hole():
    """**实例红证（构造式）**：把本腿声明的依赖换回改前的 `pytest + pyyaml`，本判据必须点名 #5575 的受害文件。

    这条锁的是**实例本身**（`tests/unit_ci_workflows/test_flake_history_index.py` × `httpx`）：
    若有人把 httpx 从 `Install deps` 里删掉，上一条会红；若有人把该判据改成"不加载 runner"，
    本条会因为"受害文件不在清单里"而红 —— 两种回退方向都拦得住。
    """
    victims = find_victims(REPO / FACE_DIR_REL, REPO, {"pytest", "yaml"})
    victim = victims.get(f"{FACE_DIR_REL}/test_flake_history_index.py")
    assert victim == ["httpx"], (
        f"#5575 的形态消失了（预期 `{FACE_DIR_REL}/test_flake_history_index.py` 缺 httpx，"
        f"实测 {victims}）—— 要么它真的不再依赖 httpx（那就把本条与 docstring 一起改准，"
        f"并说明改后谁来覆盖「判据单独被选中」这一面），要么是需求面解析退化成了空转。"
    )


def test_the_injection_scanner_sees_literal_keys_and_ignores_prose(tmp_path):
    """控制组：注入面取法本身要有牙齿 —— 认字面量键、**不认**说明文字里的提及（§23.8 B1）。"""
    face, repo = _fixture(tmp_path)
    surface: set[str] = set()
    for path, tree in _trees_for(face).items():
        if tree is not None:
            surface |= injected_modules(tree)
    assert surface == {"fakemod"}, f"注入面取法失真（实测 {sorted(surface)}）"


def test_a_borrower_is_flagged_and_a_self_sufficient_file_is_not(tmp_path):
    """夹具红/绿两侧：吃别人注入的 ⇒ 点名；自己装的 ⇒ 放行；只声明依赖 ⇒ 也放行。"""
    face, repo = _fixture(tmp_path)
    victims = find_victims(face, repo, {"pytest"})
    assert list(victims) == [f"{FACE_DIR_REL}/test_borrower.py"], f"夹具判定失真：{victims}"
    assert victims[f"{FACE_DIR_REL}/test_borrower.py"] == ["fakemod"]
    assert find_victims(face, repo, {"pytest", "fakemod"}) == {}, (
        "在 Install deps 里声明依赖后仍被判红 ⇒ 修法出口没接线（本单 #5575 走的就是这条出口）"
    )


def test_the_declared_dependency_list_is_actually_read():
    """fail-loud：`Install deps` 的解析必须真读到东西（读不到 ⇒ 上面几条会退化成空转）。"""
    declared = declared_dependencies()
    assert {"pytest", "yaml"} <= declared, (
        f"从 {WORKFLOW_REL} 里读不到 Install deps 的声明（实测 {sorted(declared)}）—— "
        f"本判据的'正当来源'一环失效，不许静默通过"
    )
