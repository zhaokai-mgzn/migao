"""
知识 Skill 节点

处理知识库检索相关操作（面料知识、保养方法、安装指南、售后政策等）。

============================================================================
⚠️  RAG DISABLED — 0 ACTIVE TOOLS

The tools bound to this skill (knowledge_search, knowledge_manage) are
commented out in app/graph/tools/registry.py because the RAG knowledge-base
infrastructure is not yet deployed.

As a result, this skill currently has ZERO active tools. The skill definition
and its system prompt are kept as a placeholder so that re-enabling RAG only
requires uncommenting the tool registrations in registry.py — no changes
needed in this file.

When RAG is re-enabled:
  1. Uncomment knowledge_search and knowledge_manage in registry.py.
  2. Verify the DashVector collection and embedding pipeline are ready.
  3. Run the knowledge skill integration tests.
============================================================================
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 知识 Skill 可用的 Tool 列表
KNOWLEDGE_TOOLS = ["knowledge_search", "knowledge_manage"]

# 知识 Skill 专用 System Prompt
KNOWLEDGE_SYSTEM_PROMPT = """## 核心原则
1. 优先使用 knowledge_search 检索知识库；命中时以知识库内容为准，整合归纳不复制粘贴
2. 知识库未命中时，对窗帘/布艺通用专业常识（面料特性、风格搭配、安装方法、保养要点等）可基于专业知识回答，注明"💡 以上为通用行业建议，建议以官方资料或负责人确认为准"
3. 实时业务数据（价格/库存/订单/物流）使用对应工具查询，不编造
4. 专业准确、条理清晰，分点说明

## 适用场景
- 面料特性、材质说明（如"雪尼尔面料会不会起球"）
- 保养方法、清洗方式（如"窗帘怎么清洗"）
- 安装步骤、加工流程（如"打孔窗帘怎么安装"）
- 加工费、价格标准（如"打孔加工多少钱"）
- 售后政策、退换货规则
- 知识条目的创建/更新/删除等管理操作，使用 knowledge_manage 工具"""

KNOWLEDGE_SKILL_CONFIG = SkillConfig(
    name="knowledge",
    domain="knowledge",
    display_name="知识库",
    tool_names=KNOWLEDGE_TOOLS,
    route_keys=["knowledge"],
    intents=["knowledge_faq", "knowledge_manage"],
    system_prompts={"mibao": KNOWLEDGE_SYSTEM_PROMPT},
    default_persona="mibao",
)
