# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""A13 守卫：`.github/assertion_taxonomy.py` 的 `WRITE_TOOLS` ⊆ **已注册工具名**（issue #4012）。

## 为什么这条必须常驻

`WRITE_TOOLS` / `WRITE_TOOL_ACTIONS` 是**判据的单一源**：`case_trust_gate.py` 用它决定
「这条用例是不是写用例 ⇒ 必须有效果层断言」。它与**后端工具注册表**是两份可以各自漂移的清单：

- 工具**下线**（例如 `processing_order_*` 三件套按 issue #3917 产品决策**不再注册**，
  工具类文件仍留在 `app/tools/`）→ 名字**留在** `WRITE_TOOLS` 里 = **陈旧判据**；
- 工具**新增**却没人往写集合里加 → 新写工具的用例**不受效果层断言约束** = 门禁静默变空壳。

两种漂移都**不会自己变红**（`WRITE_TOOLS` 非空这条自检照样通过 —— 见该文件末尾的
`assert WRITE_TOOLS, …`）。本守卫把「集合 ⊆ 已注册工具名」补成**可失败的判据**。

## 判据为什么是**纯静态 AST**（不 import 后端 app 包）

本文件跑在 CI 的 `ci workflow helper unit tests` job 里，该 job 只 `pip install pytest pyyaml`
（见 `.github/workflows/pr-check.yml`）—— **没有** pydantic/langchain 等后端依赖。
故注册表真值由 AST 从
`backend/ai-agent-service/app/tools/registry.py::create_default_registry()` 反解：

1. 取**未注释掉**的 `registry.register(<ToolClass>())` 调用 ⇒ 类名集合；
2. 取 `create_default_registry` 里每个 `from app.tools.<mod> import <ToolClass>` ⇒ 模块；
3. 读该模块的同名 `class`，取其 `name = "<tool_name>"` ⇒ 工具名。

⚠️ **注释掉的注册不算**（`# registry.register(ProcessingOrderGenerateTool())`）——
AST 天然只看**活的代码**，这正是要的语义（`processing_order_*` 三件套即活例）。

## 每条的**反例输入**（红证）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_write_tools_are_registered_tools` | 把已下线的 `processing_order_generate` 加回 `WRITE_TOOLS` |
| `test_write_tool_actions_are_registered_tools` | 把 `WRITE_TOOL_ACTIONS` 的 key 改成不存在的工具名 |
| `test_every_registered_write_tool_is_declared` | 新增一个 `read_only=False` 的工具却不动 taxonomy ⇒ 必红 |
| `test_registry_parser_matches_the_known_tool_set` | 把某个 `registry.register(...)` 注释掉 ⇒ 解析集合变化 ⇒ 与名单不符即红 |

> 第 4 条是**解析器自证**：它把「AST 解析出的 35 个工具名」与文件内**逐字写明**的名单比对 ——
> 解析器一旦失效（漏解析/多解析），本用例先红，避免上面三条退化成**恒真空转**。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

import assertion_taxonomy as tax  # noqa: E402

SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
REGISTRY_PY = SERVICE_ROOT / "app" / "tools" / "registry.py"
BASE_PY = SERVICE_ROOT / "app" / "tools" / "base.py"

#: **AST 解析器自证名单** —— `create_default_registry()` 当前实际注册的工具名（逐字，35 个）。
#: 只用于锁「解析器没坏」；工具增删时**必须**同步本名单（这正是想要的摩擦：
#: 新增工具会强制有人看一眼 taxonomy 是否需要同步）。
KNOWN_REGISTERED_TOOLS: frozenset[str] = frozenset({
    "after_sales_manage", "aftersale_create", "aftersale_query", "category_manage",
    "curtain_calc", "customer_address_query", "customer_logistics_track", "customer_manage",
    "customer_order_query", "dashboard_stats", "employee_manage", "finance_api",
    "human_handoff", "interact", "inventory_manage", "knowledge_search", "logistics_track",
    "notification_manage", "order_create", "order_manage", "order_query", "piecework_query",
    "processing_item_manage", "processing_item_query", "product_detail", "product_manage",
    "product_processing_item_manage", "product_search", "product_update",
    "production_progress_query", "role_manage", "session_manage", "settings_manage",
    "sku_update", "validate_input",
})


# ──────────────────────────────────────────────────────────────────────────────
# 静态解析：注册表真值（零后端依赖）
# ──────────────────────────────────────────────────────────────────────────────


def _registered_tool_classes() -> list[str]:
    """`create_default_registry()` 里**活的** `registry.register(<Class>())` 类名（保序）。"""
    tree = ast.parse(REGISTRY_PY.read_text(encoding="utf-8"))
    classes: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "register" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            classes.append(arg.func.id)
    assert classes, (
        f"{REGISTRY_PY} 里解析出 0 个 `registry.register(...)` —— "
        f"注册写法变了，请同步本守卫（不得静默跳过：解析不到 ≠ 无违规）"
    )
    return classes


def _tool_module_by_class() -> dict[str, str]:
    """`{ToolClass: 'app.tools.<mod>'}`（从 registry.py 的 `from app.tools.<mod> import …` 反解）。"""
    tree = ast.parse(REGISTRY_PY.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.tools"):
            for alias in node.names:
                mapping[alias.name] = node.module
    return mapping


def _class_attr(path: Path, class_name: str, attr: str) -> str:
    """类体里的 `attr = "<literal>"`（如 `name = "order_create"`）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                    and any(isinstance(t, ast.Name) and t.id == attr for t in stmt.targets):
                return stmt.value.value
    raise AssertionError(f"{path} 的 class {class_name} 里找不到 `{attr} = \"…\"`（fail-closed）")


def registered_tools() -> dict[str, bool]:
    """`{tool_name: is_write}` —— 静态反解的工具注册表（**注释掉的注册不算**）。"""
    modules = _tool_module_by_class()
    result: dict[str, bool] = {}
    for class_name in _registered_tool_classes():
        module = modules.get(class_name)
        assert module, (
            f"{class_name} 在 registry.py 里被 register，但没有对应的 "
            f"`from app.tools.<mod> import {class_name}` —— 解析链断了（fail-closed）"
        )
        path = SERVICE_ROOT / (module.replace(".", "/") + ".py")
        assert path.exists(), f"工具模块不存在：{path}"
        name = _class_attr(path, class_name, "name")
        # read_only 默认 True（`app/tools/base.py`）；类体里 `read_only = False` 即写工具
        tree = ast.parse(path.read_text(encoding="utf-8"))
        read_only = True
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                            and any(isinstance(t, ast.Name) and t.id == "read_only"
                                    for t in stmt.targets):
                        read_only = bool(stmt.value.value)
        result[name] = not read_only
    assert len(result) == len(_registered_tool_classes()), "工具名有重复（两个类同名）—— fail-closed"
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 解析器自证（防上面三条退化成恒真空转）
# ──────────────────────────────────────────────────────────────────────────────


def test_registry_parser_matches_the_known_tool_set():
    """**解析器自证**：AST 反解的工具名集合必须与本文件逐字写下的名单一致。

    解析器是前三条判据的**真相源**。它一旦失效（漏解析/多解析/写法改变），前三条会
    静默变成恒真——那正是「基于错误的真相模型写出的护栏 = 永远被豁免的空判据」（§19.1）。

    反例输入：把 `registry.register(OrderCreateTool())` 注释掉 ⇒ 解析集合少一个 ⇒ 必红。
    """
    actual = set(registered_tools())
    assert actual == set(KNOWN_REGISTERED_TOOLS), (
        f"AST 反解的工具名集合与名单不一致（差集：\n"
        f"  解析多出 = {sorted(actual - KNOWN_REGISTERED_TOOLS)}\n"
        f"  解析缺少 = {sorted(KNOWN_REGISTERED_TOOLS - actual)}\n"
        f"）\n→ 二选一：① 工具真的增删了 ⇒ 同步本文件的 `KNOWN_REGISTERED_TOOLS`"
        f"**并核对 taxonomy 是否需要同步**（这正是本守卫想要的摩擦）；"
        f"② 注册写法变了 ⇒ 修 `registered_tools()` 的解析。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# A13 判据本体
# ──────────────────────────────────────────────────────────────────────────────


def _unregistered(members: set[str], registered: set[str]) -> list[str]:
    """判据内核（纯函数，供注入式红证驱动）。"""
    return sorted(members - registered)


def test_write_tools_are_registered_tools():
    """**A13 核心不变式**：`WRITE_TOOLS` ⊆ 已注册工具名。

    反例输入（红证 ⑤）：把已下线的 `processing_order_generate` 加回 `WRITE_TOOLS` ⇒ 必红。
    （该工具类文件仍在 `app/tools/processing_order_generate.py`，只是不再注册 ——
    所以「文件存在」不能当判据，必须比注册表。）
    """
    registered = set(registered_tools())
    assert len(registered) >= 30, f"只反解出 {len(registered)} 个工具 —— 解析疑似失效（守卫会空转）"

    stale = _unregistered(set(tax.WRITE_TOOLS), registered)
    assert not stale, (
        f"`WRITE_TOOLS` 里有 {len(stale)} 个**未注册/已下线**的工具名：{stale}\n"
        f"→ 判据会把这些工具的用例判成「写用例」（要求效果层断言），"
        f"而它们根本执行不了 ⇒ 假红；同时掩盖真正在线的写工具缺口。\n"
        f"→ 修法：从 `WRITE_TOOLS` 移除（同 issue #3917 下线 `processing_order_*` 的处置）。"
    )


def test_write_tool_actions_are_registered_tools():
    """`WRITE_TOOL_ACTIONS` 的每个 key 也必须是已注册工具名（同 A13 的口径）。

    反例输入：把 key 改成不存在的工具名（或已下线工具）⇒ 必红。
    """
    registered = set(registered_tools())
    stale = _unregistered(set(tax.WRITE_TOOL_ACTIONS), registered)
    assert not stale, (
        f"`WRITE_TOOL_ACTIONS` 的 key 里有 {len(stale)} 个未注册/已下线工具：{stale}\n"
        f"→ 这些 action 级判据永远不会被命中（工具都调不到）。"
    )


def test_every_registered_write_tool_is_declared():
    """**反方向守卫**：已注册的写工具必须**显式表态** —— 在 `WRITE_TOOLS` 或 `WRITE_TOOL_ACTIONS`。

    这一条挡的是**新增写工具悄悄绕过效果层断言**（`#3778`「调用了 ≠ 成了」那类假绿）。
    与 `tests/test_write_tool_confirm_gate_invariant.py` 的「写工具必须显式表态」同族：
    那边管确认门禁，这边管**判据归属**。

    反例输入：新增一个 `read_only = False` 的工具而不动 taxonomy ⇒ 必红。
    """
    registered = registered_tools()
    write_tools = {n for n, is_write in registered.items() if is_write}
    declared = set(tax.WRITE_TOOLS) | set(tax.WRITE_TOOL_ACTIONS)

    undeclared = sorted(write_tools - declared)
    assert not undeclared, (
        f"以下**已注册写工具**没在 taxonomy 里表态（既不在 `WRITE_TOOLS`，"
        f"也不是 `WRITE_TOOL_ACTIONS` 的 key）：{undeclared}\n"
        f"→ 它们的用例不会被要求效果层断言 = 门禁静默变空壳（#3778 的形态）。\n"
        f"→ 修法：按「整工具即写」还是「仅部分 action 是写」归入对应集合。"
    )


@pytest.mark.parametrize(
    "fabricated",
    [
        {"order_create", "ghost_tool_zzz"},                       # 不存在的名字
        {"order_create", "processing_order_generate"},            # **真实存在但已下线**（#3917）
        {"aftersale_create", "knowledge_manage"},                 # RAG 禁用、未注册
    ],
)
def test_unregistered_detector_fires_on_known_shapes(fabricated):
    """**注入式红证**：判据内核对三种真实形状必须报出（防恒真）。

    第三种 `knowledge_manage` 是 `# [RAG 禁用]` 的活例（工具类仍在，注册被注释掉）——
    证明判据比的是**注册表**而不是「文件是否存在」。
    """
    reported = _unregistered(fabricated, set(registered_tools()))
    assert reported, f"判据对明显违规的输入没有报出：{fabricated}"
    assert "order_create" not in reported, (
        f"判据误伤**已注册**工具（负例失败）：{reported} —— 它只该报未注册的名字"
    )