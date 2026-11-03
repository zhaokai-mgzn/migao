# case_ids: CH-051, HR-014
"""**进程级缓存不得经测试替身接缝取值**的类级元守卫（issue #8125）。

## 病（origin/main 已复现）

ai-agent 的能力边界投影带**进程级** `lru_cache`（一次算好后全进程复用）。它的可达性探测原先
从 `app.graph.skills.base_skill` 取 `create_skill_registry` —— 而那是**测试替身接缝**：
驱动 `execute_skill` 的用例普遍 `@patch("app.graph.skills.base_skill.create_skill_registry")`，
且这些用例会经 `prepare_turn` → `_build_system_prompt` → `_capability_boundary` **反调**投影。
替身返回的 `MagicMock.get_tool_names()` 迭代为空 ⇒ 探测得到空集，**再被缓存冻住全进程** ⇒
后续任何投影/渲染都宣称「零可达能力」。

实测（修复前）：`pytest tests/test_graph_skills.py tests/test_capability_boundary.py`
⇒ **10 failed / 279 passed**（反序或单独跑全绿）。这不是本单引入的：issue #8125 在
origin/main 的干净检出上逐字复现。

## 为什么必须在结构面加一道（不是只补行为判据）

行为判据（`backend/ai-agent-service/tests/test_capability_boundary_state_isolation.py`）只在
**这一条**反调链上红。复发形态是结构性的：**任何**被 `lru_cache` 缓存的投影，只要沿调用链
从「测试会打桩的模块」取值，就会把替身期间的退化值冻进进程级缓存，而**表现得像真值变化**。
⇒ 本判据扫**全部**缓存函数（不是只认文件名/只认这一个函数），沿**同模块调用链**收集取值来源。

## 判据（静态、零依赖、秒级；每条 checker 都吃源码字符串，可内存变异）

1. 扫描面非空且 fail-closed：`app/agents/**` + `app/graph/skills/**` 里必须真的扫到
   `mibao_reachable_tool_names` 这个缓存函数、接缝名单必须非空且含 `base_skill`
   —— 否则判据会静默恒绿。
2. **违规判定**：缓存函数的调用链（同模块，深度受限）内，若出现「从替身接缝模块 import」
   或「使用模块级从替身接缝导入的符号」⇒ 具名报红。
3. **判别力自证**（注入变异，内存里做）：
   - 把 `create_skill_registry` 的来源改回 `base_skill` ⇒ 必报违规且具名；
   - 模块级导入 + 缓存函数使用该符号 ⇒ 必报违规（证明第二条分支不是死代码）；
   - 只改注释 / 把来源改回实现模块 ⇒ **不报**（对照，防判据被自己的文案喂红）。

## 边界（照实登记，别把绿读成「这一类都安全」）

- 只沿**同模块**调用链收集（跨模块一层出口的旁路不在射程内：`A.cached() → B.helper()` 若
  `B` 又读接缝，本判据看不见 —— 出口是让被缓存的投影留在同一模块里，或把新接缝登记进
  `PATCH_SEAMS`）；
- 接缝名单是**登记式**（`PATCH_SEAMS`）：新增一个会被测试打桩的模块而没登记 ⇒ 不会自动变红；
- 不判「替身是否真在某条用例里被用到」（那由 ai-agent 侧的实例判据承担）；
- 不改任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "ai-agent-service" / "app"
SCAN_DIRS = (APP_ROOT / "agents", APP_ROOT / "graph" / "skills")
CAPABILITY_BOUNDARY = APP_ROOT / "agents" / "capability_boundary.py"

#: **测试替身接缝**（登记式）：这些模块的符号在测试里被 `@patch` 换掉，进程级缓存不得经它们取值。
PATCH_SEAMS = frozenset({"app.graph.skills.base_skill"})

#: 缓存装饰器的名字形态（`from functools import lru_cache` / `functools.cache` 两种写法都认）。
CACHE_DECORATORS = frozenset({"lru_cache", "cache", "functools.lru_cache", "functools.cache"})

#: 同模块调用链的最大深度（防递归/病态大图；当前真语料最大深度 = 2）。
_MAX_DEPTH = 5


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        if isinstance(target.value, ast.Name):
            return f"{target.value.id}.{target.attr}"
        return target.attr
    return ""


def _is_cached(fn: ast.AST) -> bool:
    return any(_decorator_name(d) in CACHE_DECORATORS for d in fn.decorator_list)


def _module_functions(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_same_module(fn: ast.AST, defined: dict[str, ast.AST]) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in defined
    }


def _call_closure(roots: list[str], defined: dict[str, ast.AST]) -> list[tuple[str, list[str]]]:
    """→ [(调用链末端函数名, 链)]；链形如 `["cached", "helper"]`。"""
    out: list[tuple[str, list[str]]] = []
    stack: list[tuple[str, list[str]]] = [(r, [r]) for r in roots]
    while stack:
        name, chain = stack.pop()
        if len(chain) > _MAX_DEPTH:
            out.append((name, chain))
            continue
        fn = defined.get(name)
        if fn is None:
            continue
        out.append((name, chain))
        for callee in _called_same_module(fn, defined):
            if callee in chain:
                continue
            stack.append((callee, chain + [callee]))
    return out


def _seam_imports_in(fn: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and (node.module or "") in PATCH_SEAMS:
            imported = ", ".join(alias.name for alias in node.names)
            hits.append(f"from {node.module} import {imported}")
        elif isinstance(node, ast.Import):
            hits.extend(f"import {alias.name}" for alias in node.names if alias.name in PATCH_SEAMS)
    return hits


def _module_level_seam_symbols(tree: ast.Module) -> dict[str, str]:
    """模块级 `from <接缝> import X` ⇒ {X: "<接缝>::X"}。"""
    symbols: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "") in PATCH_SEAMS:
            for alias in node.names:
                symbols[alias.asname or alias.name] = f"{node.module}::{alias.name}"
    return symbols


def _loaded_names(fn: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def cached_projection_violations(sources: dict[str, str]) -> list[str]:
    """纯函数判据：`{相对路径: 源码}` ⇒ 违规清单（空 = 通过）。

    只吃源码字符串（不读工作树）⇒ 判别力自证可以在内存里变异语料。
    """
    violations: list[str] = []
    for rel, src in sorted(sources.items()):
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:  # fail-closed：解析不了不等于没问题
            violations.append(f"{rel}: 源码解析失败（{exc.msg}）—— 判据无法判定，不许当通过")
            continue
        defined = _module_functions(tree)
        seam_symbols = _module_level_seam_symbols(tree)
        for fn_name, chain in _call_closure(
            [name for name, fn in defined.items() if _is_cached(fn)], defined
        ):
            fn = defined[fn_name]
            seam_imports = _seam_imports_in(fn)
            if seam_imports:
                violations.append(
                    f"{rel}::{'.'.join(chain)} 从测试替身接缝取值：{'；'.join(seam_imports)}"
                    " —— 缓存会把替身期间的退化值冻住全进程"
                )
            used = sorted(_loaded_names(fn) & set(seam_symbols))
            if used:
                where = ", ".join(f"{name}={seam_symbols[name]}" for name in used)
                violations.append(
                    f"{rel}::{'.'.join(chain)} 使用了模块级从测试替身接缝导入的符号：{where}"
                    " —— 同族（缓存 + 可被打桩的取值来源）"
                )
    return violations


def _read_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for root in SCAN_DIRS:
        for path in sorted(root.rglob("*.py")):
            sources[path.relative_to(REPO_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return sources


def _cached_function_names(sources: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for src in sources.values():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        names.update(
            name for name, fn in _module_functions(tree).items() if _is_cached(fn)
        )
    return names


def test_scan_surface_is_not_empty():
    """扫描面 / 接缝名单必须现取到对象，否则判据会静默恒绿（fail-closed）。"""
    sources = _read_sources()
    assert len(sources) > 20, f"扫描面只有 {len(sources)} 个文件 —— 目录/路径已变，判据需同步"
    assert CAPABILITY_BOUNDARY.relative_to(REPO_ROOT).as_posix() in sources, (
        "扫描面里没有 capability_boundary.py —— 判据射程已偏"
    )
    assert "mibao_reachable_tool_names" in _cached_function_names(sources), (
        "扫描面里找不到被缓存的 mibao_reachable_tool_names（改名/去缓存）—— 判据需同步，不许静默通过"
    )
    assert PATCH_SEAMS and "app.graph.skills.base_skill" in PATCH_SEAMS, (
        "接缝名单被清空或不含 base_skill —— 判据会恒绿"
    )


def test_no_cached_projection_reads_through_a_test_double_seam():
    """真语料：任何缓存投影都不得经测试替身接缝取值。"""
    violations = cached_projection_violations(_read_sources())
    assert not violations, (
        "有缓存投影经测试替身接缝取值（issue #8125 的复发形态）：\n"
        + "\n".join(violations)
        + "\n修法：从**实现模块**取符号（如 create_skill_registry 取自 "
        "app.graph.skills.tool_selection），或用注入式参数把真实现传进来。"
    )


def test_checker_has_red_power_when_the_seam_read_is_restored():
    """判别力自证：把来源改回 base_skill ⇒ 必报违规且**具名**。"""
    rel = CAPABILITY_BOUNDARY.relative_to(REPO_ROOT).as_posix()
    clean = CAPABILITY_BOUNDARY.read_text(encoding="utf-8")
    poisoned = clean.replace(
        "from app.graph.skills.tool_selection import create_skill_registry",
        "from app.graph.skills.base_skill import create_skill_registry",
    )
    assert poisoned != clean, "注入未生效：锚点文本已变 —— 判据需同步到新结构"

    violations = cached_projection_violations({rel: poisoned})
    assert any("mibao_reachable_tool_names" in v and "base_skill" in v for v in violations), (
        f"注入「从接缝取值」后判据没有具名报出：{violations}"
    )


def test_checker_has_red_power_on_module_level_seam_symbol():
    """判别力自证（第二条分支）：模块级从接缝导入、缓存函数直接使用 ⇒ 必报违规。"""
    rel = "app/synthetic_cached_projection.py"
    synthetic = (
        "from functools import lru_cache\n"
        "from app.graph.skills.base_skill import create_skill_registry\n"
        "\n"
        "@lru_cache(maxsize=1)\n"
        "def reachable():\n"
        "    return create_skill_registry([]).get_tool_names()\n"
    )
    violations = cached_projection_violations({rel: synthetic})
    assert any("base_skill::create_skill_registry" in v for v in violations), (
        f"模块级接缝符号分支没有判别力：{violations}"
    )


def test_checker_is_not_vacuous_on_controls():
    """对照：只改注释 / 来源就是实现模块 ⇒ 都不许报（防判据被文案喂红）。"""
    rel = CAPABILITY_BOUNDARY.relative_to(REPO_ROOT).as_posix()
    clean = CAPABILITY_BOUNDARY.read_text(encoding="utf-8")
    commented = clean + "\n# 对照：只加一行注释，判据不得因此变红（issue #8125）\n"

    assert cached_projection_violations({rel: commented}) == []
    assert cached_projection_violations({rel: clean}) == []
