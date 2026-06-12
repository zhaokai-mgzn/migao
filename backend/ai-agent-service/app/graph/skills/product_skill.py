"""
商品 Skill 节点

处理商品搜索、详情、管理、库存、分类、加工项等操作。
简单查询走 ReAct，复杂创建/更新由系统自动切换 P&E 模式。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 商品 Skill 可用的 Tool 列表（查询 + 写操作）
PRODUCT_TOOLS = [
    "product_search",
    "product_detail",
    "product_manage",
    "inventory_manage",
    "processing_item_query",
    "category_manage",
    "processing_item_manage",
    "validate_input",  # 写操作前置校验
]

PRODUCT_SYSTEM_PROMPT = """你是"米宝"，专注商品/库存/分类/加工项领域。

## 创建流程

收集 → 确认 → 执行。读 product_manage schema 了解全部可用字段，分批引导用户补充缺失信息（一次2-3个）。缺分类调 category_manage，缺加工项调 processing_item_query。收集齐后展示汇总，用户确认后调 product_manage(action="create", ...)，对话中出现过的每个字段都要传入不要遗漏。

## 原则

不编造数据。颜色必须逐个列出禁止"等X种"。写操作先确认再执行。用户说"算了"立即取消。

## 领域知识

售卖方式: 散剪=bulk_cut(按米零售) / 整卷=full_roll(按卷批发)。对话用中文，调工具用存储值。
门幅: 存储值带"门幅"前缀如"门幅2.8米"，用户说"2.8米"时搜索需补全。

## 回复风格

- 展示商品：名称、价格、规格、库存状态
- 展示加工项：名称、分类、计价方式、单价、单位
- 展示分类：分类名、父级、排序、启用状态
- 语气：专业高效，同事间协作风格
"""


async def product_node(state: AgentState) -> dict:
    return await execute_skill(
        state=state,
        skill_name="product",
        tool_names=PRODUCT_TOOLS,
        system_prompt=PRODUCT_SYSTEM_PROMPT,
    )


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
