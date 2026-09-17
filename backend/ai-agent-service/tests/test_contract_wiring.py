# case_ids: OR-029, OR-014
"""死机制扫描（A2）：`ToolResult` 声明的字段必须在**执行出口**被传递、在**消费点**被读。

> 本文件 = issue #4012（P3「常驻 L0 守卫」包）的 A2 落点（守卫侧）。**只读静态守卫**。
> 产品代码的修复（把 `terminal` 真正传进 `result_dict`）由 **P4 包 #4013** 负责 ——
> 本文件只负责「让它在没修好之前**一直红**」，以及「下一个死字段落地时**立刻红**」。

## 病灶形状（R5 明令禁止的「静默失效」形态）

`app/tools/base.py` 的 `ToolResult` 声明了 7 个字段。执行出口
`app/graph/skills/base_skill.py` 的 `_execute_tool_safe` 用**手写字典**构造 `result_dict`
（刻意不用 `result.model_dump()`），于是**声明**与**传递**是两份可以各自漂移的清单：

```python
result_dict = {
    "success": result.success,
    "data": result.data,
    "error": result.error,
    "message": result.message,
    "suggestion": getattr(result, "suggestion", None) or "",
}   # ← terminal / summary 从来没有出现在这里
```

后果（实测，全部**读源**得到）：

| 字段 | 生产端赋值 | 消费端 | 落地时的实际状态 |
|---|---|---|---|
| `terminal` | **4 处**赋 `True`（`order_create` / `aftersale_create` / `human_handoff`×2） | `base_skill.py` 的 `result_dict.get("terminal")` | 曾是**恒为 `None`** ⇒ `ContextManager.reset_domain()` **永不触发**（4 处赋值全是空转）；**已由 #4018（P4 包）修复** |
| `summary` | 各工具自行填写（docstring 明确要求） | **全仓 0 处读 `result.summary`/`result_dict["summary"]`** | 曾是**死契约**（LLM 友好摘要从未进入上下文）；**已由 #4018 补进出口** |

`grep terminal tests/` = **0** ⇒ 没有任何测试能发现这件事：这正是「声明了字段但无人消费」
的静默形态（fail-closed 的另一面）。

> **落地记录（锚定）**：本守卫落地时（`origin/main` @ `c0be8e35`）两条**都是红的**；
> #4018 合入后（`origin/main` @ `67db87ae`）两条**转绿** —— 本文件**不是**为红而红，
> 它锁的是「声明 ⇒ 传递 ⇒ 消费」这条链下一次断裂时**立刻红**（例如下一个新字段只被声明）。

## 本文件锁的三条不变式（每条都有反例输入）

1. `test_every_tool_result_field_crosses_the_execution_exit` —— **声明 ⇒ 传递**：
   `ToolResult` 的每个字段都必须出现在 `_execute_tool_safe` 的 `result_dict` 字面量里。
2. `test_no_field_is_written_by_tools_but_never_read_back` —— **传递 ⇒ 消费**：
   任何被工具代码赋值过（`ToolResult(..., f=…)`）的字段，必须存在读取点
   （`result_dict.get("f")` / `result_dict["f"]`）。防「修了 ① 但仍没人读」的半步修复。
3. `TestFieldCrossingDetectorIsNotVacuous` —— **判据自身可红 + 不恒真**（注入式夹具）：
   多声明一个没人传的字段 ⇒ 判据必报；把字段补全 ⇒ 判据必不报（负例）。

## 判据为什么按**字面量**取 `result_dict`，而不是 `hasattr` / `model_dump`

因为要锁的正是「**手写字典**与声明清单漂移」这个形状。若将来改写成
`result.model_dump()`（**更少代码、结构上不可能漂移**），本守卫的解析会 fail-closed 报错
—— 那正是期望行为：请把守卫**换成**「出口必须走 `model_dump()`」的断言
（更好的一条不变式），而不是把守卫删掉。
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
BASE_PY = APP_DIR / "tools" / "base.py"
BASE_SKILL_PY = APP_DIR / "graph" / "skills" / "base_skill.py"

EXECUTOR_FUNC = "_execute_tool_safe"
RESULT_DICT_NAME = "result_dict"


# ──────────────────────────────────────────────────────────────────────────────
# 解析工具
# ──────────────────────────────────────────────────────────────────────────────


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(
        f"{BASE_SKILL_PY} 里找不到函数 `{name}` —— 守卫的真相源消失了（fail-closed，不得静默跳过）"
    )


def declared_tool_result_fields() -> list[str]:
    """`ToolResult` 的**声明字段**（`x: T = Field(...)` 的注解名，保序）。"""
    tree = _module_ast(BASE_PY)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ToolResult"]
    if not classes:
        raise AssertionError(f"{BASE_PY} 里找不到 `class ToolResult` —— fail-closed（真相源消失）")
    cls = classes[0]
    fields = [
        stmt.target.id
        for stmt in cls.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]
    assert fields, "`ToolResult` 解析出 0 个声明字段 —— 守卫会空转（fail-closed）"
    return fields


def executor_result_dict_keys() -> list[str]:
    """`_execute_tool_safe` 里 `result_dict = {...}` 字面量的 **key** 列表（保序）。

    只看**该函数内**、变量名恰为 `result_dict` 的那一个字面量 —— 不扫全文件，
    避免把别处的字典（`_self_correct_retry`、tool-not-found 分支等）当成执行出口。
    """
    func = _find_function(_module_ast(BASE_SKILL_PY), EXECUTOR_FUNC)
    literals: list[ast.Dict] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == RESULT_DICT_NAME for t in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            literals.append(node.value)
        else:
            raise AssertionError(
                f"`{EXECUTOR_FUNC}` 里的 `{RESULT_DICT_NAME}` 不再是字典字面量"
                f"（{ast.dump(node.value)[:80]}）—— 这是**好消息**（结构上不再可能漂移），"
                f"但请把本守卫换成「出口必须走 result.model_dump()」的断言，不要删掉守卫。"
            )
    assert len(literals) >= 1, (
        f"`{EXECUTOR_FUNC}` 里找不到 `{RESULT_DICT_NAME} = {{...}}` —— 执行出口被改了（fail-closed）"
    )
    keys = [k.value for lit in literals for k in lit.keys if isinstance(k, ast.Constant)]
    assert keys, f"`{RESULT_DICT_NAME}` 解析出 0 个 key —— 守卫会空转（fail-closed）"
    return keys


def tool_result_assignments() -> dict[str, list[str]]:
    """全仓 `ToolResult(..., <field>=…)` 的**生产端赋值**：{字段: ["文件:行", …]}。

    只认关键字实参（位置实参无法静态对应字段名）；`extra="allow"` 允许额外字段，
    故这里也可能收到**非声明字段**——那本身是另一个信号（见第 1 条用例的消息）。
    """
    assignments: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = _module_ast(path)
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "ToolResult":
                continue
            for kw in node.keywords:
                if kw.arg:
                    assignments.setdefault(kw.arg, []).append(f"{path.name}:{kw.value.lineno}")
    return assignments


def result_dict_read_fields() -> set[str]:
    """`base_skill.py` 里对执行出口结果的**读取点**：`result_dict.get("x")` / `result_dict["x"]`。"""
    func = _find_function(_module_ast(BASE_SKILL_PY), EXECUTOR_FUNC)
    reads: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == RESULT_DICT_NAME:
            if node.args and isinstance(node.args[0], ast.Constant):
                reads.add(node.args[0].value)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == RESULT_DICT_NAME \
                and isinstance(node.slice, ast.Constant):
            reads.add(node.slice.value)
    return reads


def consumer_read_sites(field: str) -> list[str]:
    """全仓对 `result_dict`/`result` 上该字段的**消费点**（读源，供判据 ② 用）。

    形态覆盖 `result_dict.get("<f>")`、`result_dict["<f>"]`、`result.<f>`：
    只看**已存在的读取写法**，不引入新语法（判据建立在**已有事实**上，R5）。
    """
    sites: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if f'"{field}"' in stripped and ("result_dict" in stripped or "result" in stripped):
                sites.append(f"{path.name}:{i}")
            elif f"result.{field}" in stripped:
                sites.append(f"{path.name}:{i}")
    return sites


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：声明 ⇒ 传递
# ──────────────────────────────────────────────────────────────────────────────


def test_every_tool_result_field_crosses_the_execution_exit():
    """**A2 核心不变式**：`ToolResult` 的每个声明字段必须出现在执行出口的 `result_dict` 里。

    **当前红**：`terminal`（`reset_domain` 永不触发的直接原因）与 `summary` 缺失。

    反例输入：把 `_execute_tool_safe` 的 `result_dict` 改回当前形态（删掉 `"terminal"` 一行）
    ⇒ 必红。绿色条件是「每个声明字段都被传递」，不是「某个特定字段在」。
    """
    declared = declared_tool_result_fields()
    passed = set(executor_result_dict_keys())
    missing = [f for f in declared if f not in passed]

    assert not missing, (
        f"`ToolResult` 声明的 {len(missing)} 个字段**没有穿过执行出口**"
        f"（`{EXECUTOR_FUNC}` 的 `{RESULT_DICT_NAME}` 里缺席）：{missing}\n"
        f"  声明字段 = {declared}\n"
        f"  出口 key = {sorted(passed)}\n"
        f"→ 声明了但无人传递 = 消费点恒为 None（`terminal` ⇒ `reset_domain` 永不触发；"
        f"`summary` ⇒ LLM 友好摘要从未进上下文）。\n"
        f"→ 修法二选一：① 补进 `{RESULT_DICT_NAME}`；② 改写成 `result.model_dump()`"
        f"（更少代码、结构上不可能漂移）。**不得**删掉字段声明或让守卫豁免。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②：传递 ⇒ 消费（防「修了一半」）
# ──────────────────────────────────────────────────────────────────────────────


def test_no_field_is_written_by_tools_but_never_read_back():
    """**A2 第二半**：被工具**赋值**过的字段，必须存在**读取点**（否则仍是死契约）。

    只看「生产端真的有赋值」的字段（`terminal` 4 处、`summary` 由各工具填写）——
    对从未被任何工具赋值的声明字段不判（那可能是为未来预留的扩展位，判红会误伤）。

    反例输入：给某个已赋值的字段删掉所有消费点（就是把 `terminal` 修进
    `result_dict` 却仍没人 `get("terminal")`）⇒ 必红。
    """
    assigned = tool_result_assignments()
    assert assigned, "全仓找不到任何 `ToolResult(...)` 关键字赋值 —— 解析失效（守卫会空转）"

    dead: list[str] = []
    for field, sites in sorted(assigned.items()):
        if not consumer_read_sites(field):
            dead.append(f"{field}（生产端 {len(sites)} 处：{', '.join(sites[:4])}）")

    assert not dead, (
        "以下 `ToolResult` 字段**被工具赋值但全仓无人读取** = 死契约（R5 明令禁止的形态）：\n  "
        + "\n  ".join(dead)
        + "\n→ 生产端每一次赋值都是空转；消费点拿到的是默认值/None。\n"
        "→ 修法：要么补消费点，要么删掉字段与生产端赋值（不留『声明了没人用』的形状）。"
    )


def test_tool_result_literal_assignments_are_declared_fields():
    """附带判据：`ToolResult(...)` 的**关键字赋值**必须是已声明字段。

    这是判据 ② 的前置（否则「赋值集合」里混进拼写错字段名，会让 ② 的结论不可信）。
    `ToolResult.Config.extra = "allow"` 允许额外字段**静默**通过 pydantic 校验 ——
    拼错的字段名因此不会在运行时炸，只会静默丢失。本用例把这条静默面关掉。

    反例输入：写 `ToolResult(success=True, termianl=True)`（拼错）⇒ 必红。
    """
    declared = set(declared_tool_result_fields())
    undeclared = sorted(f for f in tool_result_assignments() if f not in declared)
    assert not undeclared, (
        f"`ToolResult(...)` 里出现**未声明**的字段名（extra='allow' 会静默吞掉）：{undeclared}\n"
        f"  声明字段 = {sorted(declared)}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ③：判据自身可红 + 不恒真（注入式夹具）
# ──────────────────────────────────────────────────────────────────────────────


def _missing_fields(declared: list[str], passed: list[str]) -> list[str]:
    """判据 ① 的**纯函数内核**（与真值解耦，供注入式红证驱动）。"""
    return [f for f in declared if f not in set(passed)]


class TestFieldCrossingDetectorIsNotVacuous:
    """**:red_circle: 红证**（注入式）+ **负例**：判据必须能报出，也必须能不报。"""

    def test_detector_reports_a_fabricated_dead_field(self):
        """多声明一个没人传递的字段 ⇒ **必须报出**（否则判据是空的）。"""
        assert _missing_fields(["success", "terminal", "ghost_field"],
                               ["success", "data"]) == ["terminal", "ghost_field"]

    def test_detector_stays_quiet_when_all_fields_are_passed(self):
        """负例：声明与出口一致 ⇒ **必须不报**（防恒红 —— 修好后守卫要让路）。"""
        assert _missing_fields(["success", "terminal"], ["success", "terminal", "extra_key"]) == []

    def test_red_proof_record_matches_the_live_truth(self):
        """**红证记录不得变成陈旧快照**：文档里说的「当前红在哪」必须与真值一致。

        本用例**不**要求「必须一直红」——修好后它照样该绿（`missing == []`），
        此时它退回成纯文档锚定。它防的是**第三种状态**：出口的缺口集合与文件头
        记录的不一致（既有新字段悄悄落地、也有旧缺口悄悄被修却没人知道），
        那会让下一个人按**过期快照**判断现状（`migao-dev-flow` §19.1「写死易变数字」）。

        反例输入：让出口缺一个文件头没记录的字段 ⇒ 必红。
        """
        missing = set(_missing_fields(declared_tool_result_fields(), executor_result_dict_keys()))
        # ← 与文件头「病灶形状」表逐字对应。
        # 2026-09-17（rebase 到 #4018 之后）：`terminal`/`summary` 已由 P4 包补进出口
        # （`base_skill.py` 的 result_dict 现含 summary + terminal）⇒ 缺口清空，
        # 本行按「修好了就改这一行」的设计改为 `set()`。
        documented: set[str] = set()
        assert missing == documented, (
            f"执行出口的缺口集合与文件头红证记录不一致：\n"
            f"  实测 = {sorted(missing) or '（已全部传递）'}\n"
            f"  记录 = {sorted(documented)}\n"
            f"→ 二选一：① 修好了 ⇒ 把本行 `documented` 改成 `set()` 并在 PR 里登记；"
            f"② 新增了缺口 ⇒ 在文件头「病灶形状」表里补一行（别让快照过期）。"
        )