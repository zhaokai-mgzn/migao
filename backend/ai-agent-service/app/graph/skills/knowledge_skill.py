"""
知识 Skill 节点（B 端米宝，issue #3059）

处理本店知识问答（面料知识、保养方法、安装指南、售后政策等）。
知识单元为「知识卡片」（LLM WIKI 板块 issue #3051，完全替代旧 RAG）：
knowledge_search 检索本店已发布知识卡片（来源：行业模板/会话·文档提炼/人工维护）。
加工项派生（config）已移除（issue #3085）：加工计价规则是加工项目录（ProcessingItem）
的权威数据，用 processing_item_query 工具实时查询，不再预生成「{加工项名}怎么计价」卡片。
knowledge_manage 管理操作不走 Agent——知识管理在 admin-web（knowledge:manage 权限）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 知识 Skill 可用的 Tool 列表
# processing_item_query：加工计价/加工费问题 knowledge_search 未命中时的权威查询
# （店铺加工项目录含 pricingMethod/unitPrice，issue #3085 替代加工项派生卡片）
KNOWLEDGE_TOOLS = ["knowledge_search", "processing_item_query"]

# 知识 Skill 专用 System Prompt
KNOWLEDGE_SYSTEM_PROMPT = """## 核心原则
1. 优先使用 knowledge_search 检索知识库；命中时以知识库内容为准，整合归纳不复制粘贴
2. 知识库未命中时，对窗帘/布艺通用专业常识（面料特性、风格搭配、安装方法、保养要点等）可基于专业知识回答，注明"💡 以上为通用行业建议，建议以官方资料或负责人确认为准"
3. 实时业务数据（价格/库存/订单/物流）使用对应工具查询，不编造
4. 加工费、加工计价规则（如"打孔加工怎么计价"）：knowledge_search 未命中时用 processing_item_query 查店铺加工项目录（返回计价方式/单价/单位），以工具结果为准
5. 专业准确、条理清晰，分点说明

## 适用场景
- 面料特性、材质说明（如"雪尼尔面料会不会起球"）
- 保养方法、清洗方式（如"窗帘怎么清洗"）
- 安装步骤、加工流程（如"打孔窗帘怎么安装"）
- 加工费、价格标准（如"打孔加工多少钱"）→ 用 processing_item_query 查加工项目录
- 售后政策、退换货规则
- 知识管理操作（创建/更新/删除）请引导用户到后台「知识卡片」页面操作"""

KNOWLEDGE_SKILL_CONFIG = SkillConfig(
    name="knowledge",
    domain="knowledge",
    display_name="知识库",
    tool_names=KNOWLEDGE_TOOLS,
    route_keys=["knowledge"],
    intents=["knowledge_faq"],
    system_prompts={"mibao": KNOWLEDGE_SYSTEM_PROMPT},
    default_persona="mibao",
)
