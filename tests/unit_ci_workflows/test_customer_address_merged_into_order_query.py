# case_ids: MC-240
"""#8726 收敛的**等价性 + 零残留**元守卫（收货地址查询 → `customer_order_query(action=recent_address)`）

收敛事实（issue #8726）：`customer_address_query` 与 `customer_order_query` 是**同端点**
（`/api/admin/agent/orders/mine`）、**同角色**（`allowed_roles=["customer"]`）、**同强制用户过滤**、
同数据源的两次查询 —— 前者只是后者列表结果的**派生视图**（取第一条有地址的记录）。
故收敛为同一工具的第二个 action。这是一个**等价变换**，本文件就是它的机器判据。

四条判据（各自会红）+ 两条自证：

1. **旧工具名零残留**（`test_no_old_tool_name_in_executable_positions`）：5 个调用面里旧名
   **一处都不许**出现在**可执行位置**（字面量 / import / 标识符 / 断言字段）。
   **注释与 docstring 允许**（历史证据要留，且它们是 prose，不驱动任何调用）。
2. **能力面等价**（`test_capability_surface_is_equivalent`）：收敛前「工具名 × 入参」集合与
   收敛后逐项对上 —— 旧地址能力 ⇒ `action=recent_address`；旧 `list` 能力 ⇒ `action=list`；
   入参一个不多一个不少；**不许**出现第三个 action。
3. **返回形状不变**（`test_recent_address_return_shape_matches_frozen_surface`）：
   `_recent_address` 里的两个 `data=` 字典必须**恰好**是收敛前的六键 / 四键（不许多也不许少）。
4. **扫描面非空自证**（`test_every_scan_surface_is_non_empty`）：每个面扫到的文件数 > 0；
   面目录不存在 ⇒ 判红（"扫了个空 = 绿"是空断言）。
5. **反向负控**（`test_guard_discriminates_comment_from_code`）：往 docstring / YAML 注释里插旧名
   ⇒ 判据 1 仍绿；插进可执行位置 ⇒ 判据 1 红并具名。**只改注释/文档不改判据结论**。
"""
import ast
import io
import json
import pathlib
import tokenize

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVICE = REPO / "backend" / "ai-agent-service"

#: 收敛掉的旧工具名。**故意拼接**：本文件自己也在扫描面内，直接写字面量会把守卫自己判红。
OLD_NAME = "customer_" + "address_query"
NEW_TOOL = "customer_order_query"
NEW_ACTION = "recent_address"
NEW_FILE = SERVICE / "app" / "tools" / "customer_order_query.py"

#: 收敛前对外可观测面（冻结）：`{工具名: 入参集合}`。这是"收敛前是什么"的 durable 载体。
FROZEN_OLD_SURFACE = {
    OLD_NAME: frozenset(),
    NEW_TOOL: frozenset({"action", "status", "page", "page_size"}),
}
#: 收敛前的返回键（冻结）：命中 / 未命中两条路径
FROZEN_HIT_KEYS = frozenset({
    "has_address", "customer_name", "customer_phone", "customer_address", "order_no", "source",
})
FROZEN_MISS_KEYS = frozenset({"has_address", "customer_name", "customer_phone", "customer_address"})

#: 用例 yml 里**机器判定**的字段（散文 `data_checks` / `merge_log` / `title` / `tags` 不算调用面）
CASE_EXEC_FIELDS = (
    "expectations", "order_before", "must_succeed", "required_args", "output_verify",
    "db_verify", "forbidden_text", "traces", "precondition", "namespaces", "user_inputs",
)


# ── 可执行位置提取（注释 / docstring 一律排除）────────────────────────────────

def _docstring_nodes(tree: ast.AST) -> set:
    """模块 / 类 / 函数的 docstring 节点（**按对象身份**排除，比按行号可靠）。"""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            out.add(id(first.value))
    return out


def python_executable_hits(path: pathlib.Path, needle: str) -> list:
    """`path` 里出现在**可执行位置**的 `needle`（注释 / docstring 不算），返回具名清单。"""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{path}::SYNTAX_ERROR({e.msg})"]
    docs = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs and needle in node.value:
                hits.append(f"{path}:string@{node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if needle in (node.module or ""):
                hits.append(f"{path}:import-from@{node.lineno}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if needle in alias.name:
                    hits.append(f"{path}:import@{node.lineno}")
        elif isinstance(node, ast.Name):
            if needle in node.id:
                hits.append(f"{path}:name@{node.lineno}")
        elif isinstance(node, ast.Attribute):
            if needle in node.attr:
                hits.append(f"{path}:attr@{node.lineno}")
        elif isinstance(node, ast.keyword):
            if node.arg and needle in node.arg:
                hits.append(f"{path}:kwarg@{getattr(node, 'lineno', 0)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if needle in node.name:
                hits.append(f"{path}:def@{node.lineno}")
    return hits


def case_exec_payloads(path: pathlib.Path) -> list:
    """用例 yml 的**机器判定位**载荷（YAML 解析天然丢掉注释）。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else (data or {}).get("cases", [])
    out = []
    for case in cases or []:
        picked = {k: case.get(k) for k in CASE_EXEC_FIELDS if case.get(k)}
        if picked:
            out.append(json.dumps(picked, ensure_ascii=False, sort_keys=True))
    return out


# ── 扫描面 ────────────────────────────────────────────────────────────────────

def scan_surfaces(needle: str) -> dict:
    """扫 5 个调用面，返回 `{面名: {"files": n, "hits": [...]}}`（面缺失 ⇒ files=0）。"""
    surfaces = {
        "app（源码 + 内联 prompt）": ("py", SERVICE / "app"),
        "agent-service 测试": ("py", SERVICE / "tests"),
        ".github/cases（机器判定位）": ("yml", REPO / ".github" / "cases"),
        "仓级测试与 eval harness": ("py", REPO / "tests"),
        "scripts（附加面：覆盖率工装）": ("py", REPO / "scripts"),
    }
    report = {}
    for name, (kind, root) in surfaces.items():
        files = sorted(root.rglob("*.py")) if kind == "py" else sorted(root.glob("*.yml"))
        # 生成物不是调用面：`tests/agent_eval/eval_cases/**` 由 `.github/render_cases.py`
        # 从 `.github/cases/*.yml` 渲染（真值源在本判据的 YAML 面里已扫），且**不入库**
        # （生成物新鲜度由 gate 的另一条判据负责）。
        files = [f for f in files
                 if "__pycache__" not in str(f) and "/eval_cases/" not in str(f).replace("\\", "/")]
        hits = []
        if kind == "py":
            for f in files:
                hits.extend(python_executable_hits(f, needle))
        else:
            for f in files:
                for payload in case_exec_payloads(f):
                    if needle in payload:
                        hits.append(f"{f}:case-field")
        report[name] = {"files": len(files), "hits": hits}
    return report


def all_hits(report: dict) -> list:
    out = []
    for v in report.values():
        out.extend(v["hits"])
    return out


# ── 判据 1 + 4 ────────────────────────────────────────────────────────────────

def test_no_old_tool_name_in_executable_positions():
    """判据 1：旧工具名在 5 个面的**可执行位置**零残留（注释/docstring 不算）。"""
    report = scan_surfaces(OLD_NAME)
    hits = all_hits(report)
    assert hits == [], (
        "旧工具名仍出现在可执行位置（收敛未完成 / 有人回填）—— 逐条：\n  "
        + "\n  ".join(hits)
        + f"\n现取命令：git grep -n {OLD_NAME!r}"
    )


def test_every_scan_surface_is_non_empty():
    """判据 4：每个面都真的扫到了文件（面不存在 ⇒ 红，不许"空扫描 = 绿"）。"""
    report = scan_surfaces(OLD_NAME)
    empty = {name: v["files"] for name, v in report.items() if v["files"] == 0}
    assert empty == {}, f"这些扫描面一个文件都没扫到（判据空转）: {empty}"


# ── 判据 5：判别力自证（负控 + 正控）────────────────────────────────────────

def test_guard_discriminates_comment_from_code(tmp_path):
    """判据 5：只改注释/docstring ⇒ 不红；写进可执行位置 ⇒ 红并具名。"""
    docstring_only = tmp_path / "neg.py"
    docstring_only.write_text(
        'def f():\n'
        f'    """收敛前这里调 {OLD_NAME}（历史说明）"""\n'
        f'    # {OLD_NAME} 已删\n'
        '    return 1\n',
        encoding="utf-8",
    )
    assert python_executable_hits(docstring_only, OLD_NAME) == [], (
        "只写在 docstring / 注释里也被判红 ⇒ 守卫会在历史证据上误伤（假红）")

    literal = tmp_path / "pos.py"
    literal.write_text(f'TOOL = "{OLD_NAME}"\n', encoding="utf-8")
    hits = python_executable_hits(literal, OLD_NAME)
    assert len(hits) == 1, f"可执行位置的旧名没有被抓到（判据没牙）: {hits}"
    assert hits[0].endswith(":string@1"), f"命中没有具名到行: {hits}"

    # YAML 面：注释不算、机器判定位算
    yml = tmp_path / "case.yml"
    yml.write_text(
        "cases:\n  - id: XX-001\n"
        f"    # {OLD_NAME} 已收敛（注释）\n"
        f"    merge_log: \"历史：{OLD_NAME}\"\n"
        f"    expectations:\n      - tool: {OLD_NAME}\n",
        encoding="utf-8",
    )
    payloads = case_exec_payloads(yml)
    assert len(payloads) == 1, f"用例载荷解析失败: {payloads}"
    assert OLD_NAME in payloads[0], "机器判定位里的旧名没有被抓到（判据没牙）"


# ── 判据 2：能力面等价 ───────────────────────────────────────────────────────

def _module_consts(tree: ast.Module) -> dict:
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant):
            consts[node.targets[0].id] = node.value.value
    return consts


def _literal(node, consts: dict):
    """把 AST 节点还原成 Python 值（Constant / List / Dict / 模块级常量名 / `list(<常量>)`）。

    **静态求不了的表达式**（如 `list(AGENT_ORDER_STATUSES)` —— 常量来自
    `app/constants/order_status.py`，那里自己又引用生成物）返回
    `("<unresolved>", <ast dump 片段>)`，让调用方**显式登记边界**，而不是让判据静默变空。
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_literal(e, consts) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal(k, consts): _literal(v, consts)
                for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "list" and len(node.args) == 1:
        inner = _literal(node.args[0], consts)
        if not isinstance(inner, tuple):
            return list(inner)
    return ("<unresolved>", ast.dump(node)[:80])


def _tool_surface() -> dict:
    """从**源码**读出收敛后的工具面：`{参数名: {...}}`（不 import 服务，保持本腿轻量）。"""
    tree = ast.parse(NEW_FILE.read_text(encoding="utf-8"))
    consts = _module_consts(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CustomerOrderQueryTool":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                        and isinstance(stmt.targets[0], ast.Name) \
                        and stmt.targets[0].id == "parameters":
                    params = _literal(stmt.value, consts)
                    return params["properties"]
    raise AssertionError("customer_order_query 的 parameters 解析失败（判据 fail-closed）")


def test_capability_surface_is_equivalent():
    """判据 2：收敛前后「工具名 × 入参」集合逐项等价（等价变换的证据）。"""
    props = _tool_surface()

    # ① 入参集合：一个不多、一个不少
    assert set(props) == FROZEN_OLD_SURFACE[NEW_TOOL], (
        f"入参集合变了：现值={sorted(props)} 冻结={sorted(FROZEN_OLD_SURFACE[NEW_TOOL])}")

    # ② action 面：恰好两个 —— 旧 list 能力 + 旧地址能力的落点；**不许**第三个
    assert props["action"]["enum"] == ["list", NEW_ACTION], (
        f"action 枚举必须恰好是 list + {NEW_ACTION}（多一个 = 新增能力，少一个 = 能力丢失）: "
        f"{props['action']['enum']}")
    assert props["action"]["default"] == "list", "默认值必须仍是 list（旧调用面的行为不变）"

    # ③ 旧地址能力**零入参**：新工具不得引入 required（否则零入参调用面不再可表达）
    assert "required" not in json.dumps(props, ensure_ascii=False, default=str), (
        "新工具引入了 required 参数 ⇒ 旧地址调用面（零入参）不再可表达")

    # ④ **边界（照实登记）**：`status.enum` 的真实取值是 `list(AGENT_ORDER_STATUSES)`，
    #    其常量来自 `app/constants/order_status.py`（再引用生成物）⇒ 本判据**静态求不了**，
    #    故只裁「参数名集合 + action 面」；**值级等价**（六个状态、顺序、不含 packed）由
    #    service 侧可执行判据 `test_tools_customer_order_query_recent_address.py::`
    #    `TestToolContract::test_old_params_are_still_present` 证明。
    assert isinstance(props["status"]["enum"], tuple), (
        "status.enum 变成本判据能静态求值的形式了 ⇒ 请把它也钉进等价性对照（撤销本边界登记）")


def test_old_tool_is_gone_from_registry_and_disk():
    """判据 2 的另一半：旧工具名不得再被注册 / 旧文件不得存在（名字级能力真的消失了）。"""
    old_file = SERVICE / "app" / "tools" / (OLD_NAME + ".py")
    assert old_file.exists() is False, f"旧工具文件还在: {old_file}"
    registry_src = (SERVICE / "app" / "tools" / "registry.py").read_text(encoding="utf-8")
    assert python_executable_hits(SERVICE / "app" / "tools" / "registry.py", OLD_NAME) == []
    assert f"registry.register" in registry_src


# ── 判据 3：返回形状 ─────────────────────────────────────────────────────────

def _recent_address_data_keys() -> list:
    """`_recent_address` 里每个 `ToolResult(data={...})` 的键集合（按出现顺序）。"""
    tree = ast.parse(NEW_FILE.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                or node.name != "_recent_address":
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) \
                    or call.func.id != "ToolResult":
                continue
            for kw in call.keywords:
                if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                    out.append(frozenset(k.value for k in kw.value.keys))
    return out


def test_recent_address_return_shape_matches_frozen_surface():
    """判据 3：两条返回路径的 data 键集合必须**恰好**等于收敛前的冻结值。"""
    shapes = _recent_address_data_keys()
    assert len(shapes) == 2, f"recent_address 必须只有命中/未命中两条返回路径: {shapes}"
    assert frozenset(map(frozenset, shapes)) == frozenset({FROZEN_HIT_KEYS, FROZEN_MISS_KEYS}), (
        f"返回形状变了：现值={[sorted(s) for s in shapes]} "
        f"冻结={[sorted(FROZEN_HIT_KEYS), sorted(FROZEN_MISS_KEYS)]}")
