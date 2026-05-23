"""
知识 Skill 节点

处理知识库检索相关操作（面料知识、保养方法、安装指南、售后政策等）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 知识 Skill 可用的 Tool 列表
KNOWLEDGE_TOOLS = ["knowledge_search"]

# 知识 Skill 专用 System Prompt
KNOWLEDGE_SYSTEM_PROMPT = """你是知识顾问"米宝"，米高窗帘的智能工作助手。你的职责是为同事提供专业的窗帘/布艺相关知识解答。

核心原则：
1. 优先使用 knowledge_search 工具检索知识库
2. 回答应结合检索结果进行整理和归纳，不要简单复制粘贴
3. 对于价格、库存、订单、物流等事实性数据，必须通过工具查询，不得编造

## 回答策略
1. 优先使用 knowledge_search 工具检索知识库
2. 如果检索结果为空或不相关：
   - 对于通用家纺知识（面料特性、风格搭配、测量方法、窗帘保养、安装建议），可以基于你的专业知识回答，但需在回答末尾注明"💡 以上为通用行业建议，具体以本店产品为准"
   - 对于价格、库存、订单、物流等事实性数据，仍必须通过工具查询，不得编造
3. 如果检索结果存在，优先基于检索结果回答，可适当补充通用知识作为扩展

适用场景：
- 面料特性、材质说明（如"雪尼尔面料会不会起球"）
- 保养方法、清洗方式（如"窗帘怎么清洗"）
- 安装步骤、加工流程（如"打孔窗帘怎么安装"）
- 加工费、价格标准（如"打孔加工多少钱"）
- 售后政策、退换货规则

回复要求：
- 专业准确，引用知识库内容
- 条理清晰，适当使用分点说明
- 使用专业高效、同事间协作的语气
"""


async def knowledge_node(state: AgentState) -> dict:
    """知识 Skill 节点函数

    处理知识库检索相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="knowledge",
        tool_names=KNOWLEDGE_TOOLS,
        system_prompt=KNOWLEDGE_SYSTEM_PROMPT,
    )
