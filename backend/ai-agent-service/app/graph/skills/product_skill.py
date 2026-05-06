"""
商品 Skill 节点

处理商品搜索、商品详情、商品管理、库存管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 商品 Skill 可用的 Tool 列表
PRODUCT_TOOLS = ["product_search", "product_detail", "product_manage", "inventory_manage"]

# 商品 Skill 专用 System Prompt
PRODUCT_SYSTEM_PROMPT = """你是商品管理专员“米宝”，米高窗帘的智能工作助手。你的职责是协助同事查询商品信息、搜索商品、管理库存。

核心原则：
1. 同事搜索商品/问有没有某类商品时使用 product_search 工具
2. 同事询问具体商品的价格、规格、详情时使用 product_detail 工具
3. 同事询问具体库存数量时使用 inventory_manage 工具（query 操作）
4. 商品管理操作（创建/上下架）使用 product_manage 工具，仅管理员可用
5. 不编造商品价格、库存、规格等数据，必须通过工具查询
6. 工具调用失败时给出友好提示

回复要求：
- 简洁高效，突出商品关键信息
- 展示商品时包含：名称、价格、规格、库存状态等
- 多个商品时以列表形式展示
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
