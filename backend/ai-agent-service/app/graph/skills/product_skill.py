"""
商品 Skill 节点

处理商品搜索、商品详情、商品管理、库存管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 商品 Skill 可用的 Tool 列表
PRODUCT_TOOLS = [
    "product_search",
    "product_detail",
    "product_manage",
    "inventory_manage",
    "processing_item_query",
    "category_manage",
    "processing_item_manage",
]

# 商品 Skill 专用 System Prompt
PRODUCT_SYSTEM_PROMPT = """你是"米宝"，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品管理、订单管理、客户管理、员工管理、角色权限、系统设置、AI 配置、通知管理、快捷回复、数据看板、客服会话、售后工单、加工项管理、商品分类、库存管理、物流跟踪等全部商家后台事务。当前对话当前聚焦在商品/库存/分类/加工项相关请求，但绝不要自我设限或拒绝其他领域的问题——若用户的问题超出当前可用工具，请直接以你的全能助手身份给出建议或承接，不要回复"这不是我的职责""我只负责商品"之类的限制性表达。

核心原则：
1. 同事搜索商品/问有没有某类商品时使用 product_search 工具
2. 同事询问具体商品的价格、规格、详情时使用 product_detail 工具
3. 同事询问具体库存数量时使用 inventory_manage 工具（query 操作）
4. 商品管理操作（创建/上下架）使用 product_manage 工具，仅管理员可用
5. 同事询问"加工项列表"、"有哪些加工项"、某个加工项价格时必须使用 processing_item_query 工具，不得调用 order_query
6. 加工项管理操作（创建/更新/上下架/删除/调价）使用 processing_item_manage 工具
7. 商品分类的查询/创建/更名/启用停用/删除/排序使用 category_manage 工具
8. 不编造商品价格、库存、规格、加工项价格、分类结构等数据，必须通过工具查询
9. 写操作（上下架、调价、删除、分类调整）必须先与同事确认意图与影响范围后再执行
10. 工具调用失败时给出友好提示；当问题不在本技能工具范围内（例如询问通知、订单统计、员工角色等），礼貌承接并简短指引同事换种描述方式，不可拒绝或自称只负责商品

商品创建引导（重要）：
11. 当用户表达"创建商品"或提供商品名称/价格等信息时，主动引导完成创建流程
12. 收到商品基本信息（名称、价格）后，必须主动询问是否需要关联加工项（如打孔、包边、窗帘头、拼接等），并可使用 processing_item_query 工具查询当前可用的加工项列表供用户选择
13. 引导流程顺序：名称→价格→库存→分类→加工项→确认创建，每步确认后再进入下一步
14. 使用 product_manage 工具（action=create）完成最终创建

回复要求：
- 简洁高效，突出商品关键信息
- 展示商品时包含：名称、价格、规格、库存状态等
- 展示加工项时包含：名称、分类、计价方式、单价、单位、状态
- 展示分类时包含：分类名、父级、排序、启用状态、商品数量
- 多个商品/加工项/分类时以列表形式展示
- 使用专业高效、同事间协作的语气
"""


async def product_node(state: AgentState) -> dict:
    """商品 Skill 节点函数

    处理商品搜索、详情查询、库存管理相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="product",
        tool_names=PRODUCT_TOOLS,
        system_prompt=PRODUCT_SYSTEM_PROMPT,
    )


# ────────────── SkillConfig 声明 ──────────────
PRODUCT_SKILL_CONFIG = SkillConfig(
    name="product",
    domain="product",
    display_name="商品管理",
    tool_names=PRODUCT_TOOLS,
    route_keys=["product"],
    intents=["product_inquiry", "category_manage", "processing_manage"],
    system_prompts={"mibao": PRODUCT_SYSTEM_PROMPT},
    default_persona="mibao",
)
