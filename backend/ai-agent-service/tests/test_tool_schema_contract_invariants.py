"""工具 schema 跨工具不变式 — action 枚举对账 + 工具注册闭环 + 描述点名有效性

# case_ids: PR-001, PR-002, PR-019

四条机器可判不变式，锁死工具接口审计（/tmp/migao-audit）暴露的结构性缺陷不再复发：

1. **action 分发工具：`action.enum ⊆ 模块级 VALID_ACTIONS`**
   防「枚举里留着运行时必拒的死分支」——审计 B1：LLM 选它 → 运行时被拒 → 白跑一轮对话
   （历史形态：product_manage 的 `manage_processing_items` 拆成独立工具后 schema 却忘改）。

2. **action 分发工具：`action.description` 覆盖每个 enum 成员的语义**
   防「操作类型」三字占位（审计 J1：20 个 action 工具里唯一描述缺分支语义者）。

3. **`app/tools/` 下每个 `BaseTool` 子类要么已注册、要么显式标注弃用**
   防「工具写好了忘注册」的死工具静默躺着——本次审计复核实证：
   `ProcessingItemsTool`（name=query_processing_items）从未注册进
   `create_default_registry()`，全仓只被 fallback 文案与自身单测引用（#3574 已删除）。
   约定：确实要保留的弃用工具，在类上加 `deprecated = True`（本测试按 AST 识别）。

4. **描述点名的工具必须真实注册**（防描述指向不存在/LLM 看不见的工具）
   ——审计 B2 的形态：消歧说明写在模块 docstring（LLM 看不见），
   而 `base.get_schema()` 只取类属性 `description`。

判据来源：审计 report.md §1 J1/J4、§2 A4/B1/B2、§4 R4。
"""

import ast
import importlib
import re
from pathlib import Path

from app.tools.registry import get_tool_registry

TOOLS_DIR = Path(__file__).resolve().parent.parent / "app" / "tools"

# 非工具模块（基类/注册器/适配器），不参与「工具类必须注册」扫描
_NON_TOOL_MODULES = {"base.py", "registry.py", "langchain_adapter.py", "__init__.py"}

# 未收敛到模块级 VALID_ACTIONS 的遗留 action 工具：无法机器判「enum ↔ execute 分支」一致，
# 显式登记（集合封闭：新工具必须提供 VALID_ACTIONS 才能进本文件的白名单以外路径）。
_NO_VALID_ACTIONS_ALLOWLIST = {
    "customer_logistics_track",
    "order_query",
    "customer_order_query",
    "aftersale_query",
}

# 描述里形如工具名的 token（xxx_query / xxx_manage / ...）中**非工具**的合法出现：
# 动作值/领域名词，非工具名（封闭白名单：新出现的未注册 token 会红）
_NON_TOOL_NAME_TOKENS = {
    "follow_status_stats",  # order_query 的 action 值
    "processing_items",     # 领域名词（product_detail 响应字段）
}
_TOOL_LIKE_REF_RE = re.compile(
    r"\b([a-z][a-z0-9_]*_(?:query|manage|create|update|detail|search|list|"
    r"delete|generate|track|stats|calc|handoff|input|api|items))\b"
)


def _llm_visible_description(tool) -> str:
    """LLM 实际看到的口径：base.get_schema() 的 function.description"""
    return tool.get_schema()["function"]["description"]


def _action_enum_tools():
    """所有声明了 action 枚举的分发工具"""
    tools = []
    for tool in get_tool_registry().get_all_tools():
        action_prop = (tool.parameters or {}).get("properties", {}).get("action", {})
        if action_prop.get("enum"):
            tools.append(tool)
    return tools


def _tool_classes_in_source() -> dict:
    """AST 扫 app/tools/*.py：{工具名: 文件名}，含**未注册**的类

    只认顶层 `class X(BaseTool)`；工具名取类属性 `name = "..."`；
    `deprecated = True` 的类视为显式弃用，不参与注册闭环断言。
    """
    found = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name in _NON_TOOL_MODULES or path.name.startswith("__"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "BaseTool" for b in node.bases):
                continue
            tool_name = None
            deprecated = False
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name) or not isinstance(stmt.value, ast.Constant):
                    continue
                if target.id == "name":
                    tool_name = stmt.value.value
                elif target.id == "deprecated":
                    deprecated = bool(stmt.value.value)
            if tool_name and not deprecated:
                found[tool_name] = path.name
    return found


def test_action_enum_tools_are_discovered():
    """不变式自检：确实扫到了 action 分发工具（防断言空跑）"""
    names = sorted(t.name for t in _action_enum_tools())
    assert len(names) >= 10, f"只扫到 {len(names)} 个 action 工具，注册表可能未加载：{names}"
    assert "product_manage" in names


def test_action_enum_subset_of_module_valid_actions():
    """每个 action 分发工具的 enum 必须是模块级 VALID_ACTIONS 的子集（无死分支）"""
    checked = []
    for tool in _action_enum_tools():
        enum = set(tool.parameters["properties"]["action"]["enum"])
        module = importlib.import_module(tool.__module__)
        valid = getattr(module, "VALID_ACTIONS", None)

        if valid is None:
            assert tool.name in _NO_VALID_ACTIONS_ALLOWLIST, (
                f"{tool.name} 声明了 action 枚举但模块未定义 VALID_ACTIONS —— "
                f"请在 {tool.__module__} 定义 VALID_ACTIONS 并保持 enum 一致"
            )
            continue

        assert enum <= set(valid), (
            f"{tool.name} action enum 含运行时必拒的死分支：{enum - set(valid)} "
            f"（VALID_ACTIONS={sorted(valid)}）"
        )
        checked.append(tool.name)

    assert len(checked) >= 10, f"只校验了 {len(checked)} 个工具的 enum⊆VALID_ACTIONS：{checked}"


def test_action_description_covers_every_enum_member():
    """每个 action 分发工具的描述必须逐个带上 enum 分支名（LLM 才知道分支语义）"""
    failures = []
    for tool in _action_enum_tools():
        action_prop = tool.parameters["properties"]["action"]
        desc = action_prop.get("description", "")
        missing = [m for m in action_prop["enum"] if m not in desc]
        if missing:
            failures.append(f"{tool.name} 缺少分支说明: {missing}（desc={desc!r}）")
        elif len(desc) < 20:
            failures.append(f"{tool.name} 描述疑似占位（{len(desc)} 字）: {desc!r}")
    assert not failures, "action 描述缺分支语义：\n" + "\n".join(failures)


def test_every_tool_class_is_registered_or_marked_deprecated():
    """app/tools/ 下每个 BaseTool 子类必须已注册（或显式 deprecated=True）

    死工具形态（本次实证 #3574）：类写好了、没人注册 → LLM 永远看不到它，
    但 fallback 文案/测试还在引用，静态看像"活的能力"，实际是死代码。
    """
    registered = set(get_tool_registry().get_tool_names())
    defined = _tool_classes_in_source()

    assert len(defined) >= 30, f"只扫到 {len(defined)} 个工具类，AST 扫描可能失效：{sorted(defined)}"

    dead = {name: f for name, f in defined.items() if name not in registered}
    assert not dead, (
        f"app/tools/ 存在未注册的死工具（注册到 create_default_registry()，"
        f"或删除代码/加 `deprecated = True` 显式弃用）：{dead}"
    )


def test_registered_tool_names_match_class_definitions():
    """反向：注册表里的工具名必须都能在 app/tools/*.py 找到类定义（防幽灵注册）"""
    defined = set(_tool_classes_in_source())
    registered = set(get_tool_registry().get_tool_names())
    ghosts = sorted(registered - defined)
    assert not ghosts, f"注册表有工具名但 app/tools/ 下找不到对应类定义（幽灵注册）：{ghosts}"


def test_descriptions_only_name_registered_tools():
    """描述里点名的工具必须真实注册（防描述指向不存在/LLM 看不见的工具）"""
    registered = set(get_tool_registry().get_tool_names())
    ghosts = {}
    for tool in get_tool_registry().get_all_tools():
        desc = _llm_visible_description(tool)
        refs = set(_TOOL_LIKE_REF_RE.findall(desc)) - _NON_TOOL_NAME_TOKENS - {tool.name}
        unknown = sorted(refs - registered)
        if unknown:
            ghosts[tool.name] = unknown
    assert not ghosts, (
        f"工具描述点名的工具不存在/未注册（LLM 会照着去调一个不存在的工具）：{ghosts}"
    )
