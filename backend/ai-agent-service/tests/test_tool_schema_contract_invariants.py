"""工具 schema 跨工具不变式 — action 枚举对账 + 双胞胎工具消歧可见性

# case_ids: PR-001, PR-002, PR-019, PP-001, PP-005

三条机器可判不变式，锁死工具接口审计（/tmp/migao-audit）暴露的结构性缺陷不再复发：

1. **action 分发工具：`action.enum ⊆ 模块级 VALID_ACTIONS`**
   防「枚举里留着运行时必拒的死分支」——product_manage 的 `manage_processing_items`
   已拆分为独立工具 `product_processing_item_manage`，schema 却忘改
   （审计 B1：LLM 选它 → 运行时被拒 → 白跑一轮对话）。

2. **action 分发工具：`action.description` 覆盖每个 enum 成员的语义**
   防「操作类型」三字占位（审计 J1：20 个 action 工具里唯一描述缺分支语义者）。

3. **双胞胎工具消歧必须落在 `description`（LLM 可见），不是模块 docstring**
   `base.get_schema()` 只把 `self.description` 拼进 schema，
   `processing_item_query.py` 模块 docstring 里的消歧说明 LLM 根本看不见
   （审计 B2：`query_processing_items` vs `processing_item_query` 仅词序差异，
   LLM 只能按名字猜 → 选错工具）。**复核补充**：`query_processing_items` 目前
   未注册进全局 registry（死工具），故本文件直接实例化两者锁消歧说明。

判据来源：审计 report.md §1 J1/J4、§2 A4/B1/B2、§4 R4。
"""

import importlib

from app.tools.processing_item_query import ProcessingItemQueryTool
from app.tools.processing_items import ProcessingItemsTool
from app.tools.registry import get_tool_registry

# 未收敛到模块级 VALID_ACTIONS 的遗留 action 工具：无法机器判「enum ↔ execute 分支」一致，
# 显式登记（集合封闭：新工具必须提供 VALID_ACTIONS 才能进本文件的白名单以外路径）。
_NO_VALID_ACTIONS_ALLOWLIST = {
    "customer_logistics_track",
    "order_query",
    "customer_order_query",
    "aftersale_query",
    "product_processing_item_manage",
}

TWIN_PRODUCT_PROCESSING_ITEMS = "query_processing_items"   # 查「某商品」关联加工项及价格
TWIN_PROCESSING_ITEM_QUERY = "processing_item_query"       # 查「店铺」加工项目录


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


def _twin_processing_item_tools():
    """双胞胎工具实例

    注意（审计复核发现）：`query_processing_items`（ProcessingItemsTool）**未注册**进
    全局 registry（`create_default_registry` 只注册 ProcessingItemQueryTool）→ 目前
    LLM 看不到它，属死工具。此处**直接实例化**而非走 registry，目的是把两者的命名/描述
    消歧锁死：一旦它被注册（或有人照它新建工具），LLM 立刻面对两个仅词序不同的工具名。
    """
    return ProcessingItemsTool(), ProcessingItemQueryTool()


def test_twin_processing_item_tools_name_each_other_in_description():
    """双胞胎工具必须在 LLM 可见的 description 里双向点名（不是模块 docstring）"""
    query_items, item_query = _twin_processing_item_tools()

    query_items_desc = _llm_visible_description(query_items)
    item_query_desc = _llm_visible_description(item_query)

    assert TWIN_PROCESSING_ITEM_QUERY in query_items_desc, (
        f"{TWIN_PRODUCT_PROCESSING_ITEMS} 描述未点名双胞胎工具 {TWIN_PROCESSING_ITEM_QUERY}："
        f"{query_items_desc!r}"
    )
    assert TWIN_PRODUCT_PROCESSING_ITEMS in item_query_desc, (
        f"{TWIN_PROCESSING_ITEM_QUERY} 描述未点名双胞胎工具 {TWIN_PRODUCT_PROCESSING_ITEMS}："
        f"{item_query_desc!r}"
    )


def test_query_processing_items_description_has_trigger_and_counterexample():
    """`query_processing_items` 描述须补齐三段式（【触发】/【参数】/【反例】）"""
    query_items, _ = _twin_processing_item_tools()
    desc = _llm_visible_description(query_items)
    for marker in ("【触发】", "【反例】"):
        assert marker in desc, f"{TWIN_PRODUCT_PROCESSING_ITEMS} 描述缺 {marker}：{desc!r}"
    # 参数二选一语义必须写明（product_id / product_name）
    assert "product_id" in desc and "product_name" in desc
