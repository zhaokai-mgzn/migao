"""
订单 Skill 节点

处理订单查询、物流追踪、订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 订单 Skill 可用的 Tool 列表
ORDER_TOOLS = ["order_query", "order_manage", "order_create", "logistics_track", "product_search", "product_detail"]

# 订单 Skill 专用 System Prompt
ORDER_SYSTEM_PROMPT = """你是"米宝"，米高智能商家管理后台的 AI 管理助手，专注订单/物流领域。

## 工具使用

| 场景 | 工具 |
|------|------|
| 查订单/统计/跟进 | order_query |
| 创建订单 | order_create |
| 修改/取消订单 | order_manage |
| 查物流 | logistics_track |

## 原则

1. 不编造订单状态或物流信息。回复中不要出现[工具返回]等来源标签
2. 简单写操作（取消订单、修改状态）先文字确认再执行
3. 复杂创建流程（新建订单）系统会自动引导，你只需配合回答
4. 工具失败时友好提示，建议稍后重试

## 回复格式（必须遵守）

- **订单列表**：用表格或 `•` 列表展示关键字段（订单号、客户、金额、状态、时间），每条独立一行
- **空行分隔**：不同信息块之间用空行分隔，避免糊成一坨
- **emoji 辅助**：用 📦🟡🔴✅❌⚠️ 等标记状态和重点，但不要过度使用
- **标题清晰**：用粗体标题归纳每组信息，如「**📦 待发货订单**（共 3 个）」
- **尾部引导**：在回复末尾用一行引导用户下一步操作

示例回复：
```
📦 **待发货订单**（共 3 个）

• ORD-20260531-X1 · 张三 · ¥264.00 · 2件 · 05-31
• ORD-20260601-X2 · 李四 · ¥130.00 · 1件 · 06-01
• ORD-20260602-X3 · 王五 · ¥450.00 · 3件 · 06-02

⚠️ 商品明细暂不可查，请去后台查看。

需要查看哪个订单的详情？
```

## 回复风格

- 专业高效，同事间协作语气
- 简洁不啰嗦，但关键信息不省略
"""


async def order_node(state: AgentState) -> dict:
    """订单 Skill 节点函数

    处理订单查询、物流追踪、订单管理相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="order",
        tool_names=ORDER_TOOLS,
        system_prompt=ORDER_SYSTEM_PROMPT,
    )


# ────────────── SkillConfig 声明 ──────────────
ORDER_SKILL_CONFIG = SkillConfig(
    name="order",
    domain="order",
    display_name="订单管理",
    tool_names=ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "order_create", "logistics_track"],
    system_prompts={"mibao": ORDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
