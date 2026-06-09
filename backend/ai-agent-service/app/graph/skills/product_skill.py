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
]

PRODUCT_SYSTEM_PROMPT = """你是"米宝"，米高智能商家管理后台的 AI 管理助手，专注商品/库存/分类/加工项领域。

## 工具使用

| 场景 | 工具 |
|------|------|
| 搜索商品 | product_search |
| 商品详情/价格/规格 | product_detail |
| 创建/更新/上下架商品 | product_manage |
| 查库存 | inventory_manage |
| 查加工项列表/价格 | processing_item_query |
| 管理加工项(创建/更新/下架) | processing_item_manage |
| 查分类树/管理分类 | category_manage |

## 原则

1. 所有数据标注来源：[工具返回]/[用户提供]/[推断]。标注[推断]的数据要说明依据
2. 不编造商品名、价格、规格等任何值
3. 简单写操作（上下架、单字段修改）先文字确认再执行
4. 复杂创建流程（新建商品）系统会自动引导，你只需配合回答

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
