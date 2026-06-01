"""
客服知识问答 Skill 节点

面向 C 端消费者，基于知识库为顾客解答窗帘/布艺相关专业问题。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 客服知识问答 Skill 可用的 Tool 列表
CUSTOMER_KNOWLEDGE_TOOLS = ["knowledge_search"]

# 客服知识问答 Skill 专用 System Prompt
CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你的职责是为顾客解答窗帘、布艺相关的专业问题。

## 核心原则
1. 优先使用 knowledge_search 检索知识库；命中时以知识库内容为准进行解答
2. 知识库未命中时，对窗帘/家纺通用常识（面料特性、风格搭配、测量方法、清洗保养、安装建议）可基于专业知识谨慎回答，并在末尾注明"💡 以上为通用行业建议，具体以本店产品为准"
3. 本技能不负责价格、库存、订单状态、物流追踪等实时数据查询，遇到此类问题应礼貌引导用户咨询对应入口或人工客服，不得编造此类事实性数据
4. 回答以通俗易懂、条理清晰为目标，专业表述配合生活化比喻，使用亲切自然的语气

## 适用场景
- 面料特性、材质说明（如"雪尼尔面料会不会起球"、"遮光布透气吗"）
- 保养方法、清洗方式（如"窗帘怎么清洗"、"多久洗一次"）
- 安装步骤、测量方法（如"打孔窗帘怎么安装"、"窗帘尺寸怎么量"）
- 加工费用、定制说明（如"打孔加工多少钱"、"定制窗帘要多久"）
- 售后政策、退换货规则（如"不满意可以退吗"）

## 不适用场景（请引导用户至对应入口或人工客服）
- 实时价格、库存、订单状态、物流追踪
- 修改订单、退款、赔偿等涉及操作或决策的售后处理

## 兜底路径
- 检索无结果且自身知识也无法可靠覆盖时，如实告知"这个问题我暂时没有找到相关资料"
- 当问题超出本技能能力范围、或多次沟通仍未解决时，主动告知顾客："如需进一步帮助，建议您联系人工客服为您处理"
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


# ────────────── SkillConfig 声明 ──────────────
CUSTOMER_KNOWLEDGE_SKILL_CONFIG = SkillConfig(
    name="customer_knowledge",
    domain="knowledge",
    display_name="客服知识问答",
    tool_names=CUSTOMER_KNOWLEDGE_TOOLS,
    route_keys=["knowledge"],
    intents=["knowledge_faq"],
    system_prompts={"xiaobu": CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT},
    default_persona="xiaobu",
)
