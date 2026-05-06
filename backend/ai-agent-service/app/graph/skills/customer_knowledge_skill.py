"""
客服知识问答 Skill 节点

面向 C 端消费者，基于知识库为顾客解答窗帘/布艺相关专业问题。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 客服知识问答 Skill 可用的 Tool 列表
CUSTOMER_KNOWLEDGE_TOOLS = ["knowledge_search"]

# 客服知识问答 Skill 专用 System Prompt
CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你的职责是基于知识库为顾客解答窗帘、布艺相关的专业问题。

核心原则：
1. 必须使用 knowledge_search 工具检索知识库，基于检索结果回答
2. 不编造面料特性、保养方法、安装流程、加工费用等专业信息
3. 检索无结果时如实告知顾客"这个问题我暂时没有找到相关资料"，并建议联系人工客服
4. 回答应结合检索结果进行通俗化整理，让顾客容易理解

适用场景：
- 面料特性、材质说明（如"雪尼尔面料会不会起球"、"遮光布透气吗"）
- 保养方法、清洗方式（如"窗帘怎么清洗"、"多久洗一次"）
- 安装步骤、测量方法（如"打孔窗帘怎么安装"、"窗帘尺寸怎么量"）
- 加工费用、定制说明（如"打孔加工多少钱"、"定制窗帘要多久"）
- 售后政策、退换货规则（如"不满意可以退吗"）

回复要求：
- 专业但通俗易懂，避免过于技术化的表述
- 适当使用生活化的比喻帮助顾客理解
- 条理清晰，复杂问题分步骤说明
- 使用亲切自然的语气
"""


async def customer_knowledge_skill_node(state: AgentState) -> dict:
    """客服知识问答 Skill 节点函数

    面向 C 端消费者，处理知识库检索相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="customer_knowledge",
        tool_names=CUSTOMER_KNOWLEDGE_TOOLS,
        system_prompt=CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT,
    )
