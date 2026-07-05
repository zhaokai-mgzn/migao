"""
数据分析 Skill 节点

处理经营数据看板查询、客服会话管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 数据 Skill 可用的 Tool 列表
DATA_TOOLS = ["dashboard_stats", "session_manage"]

# 数据 Skill 专用 System Prompt
DATA_SYSTEM_PROMPT = """当前聚焦经营看板与客服会话，遇到其他领域需求也应承接（如 "查看订单" → 引导进入订单管理）。

## 核心工具

| 工具 | 场景 |
|------|------|
| dashboard_stats | overview / order_trend / order_status / recent_orders / active_sessions |
| session_manage | 在线会话 / 排队会话 / 历史会话 / 转人工 |

## 数据原则

- 基于工具返回的真实数据解读，不编造趋势
- 数据缺失时告知 "暂未取到数据"，建议核实时间范围或稍后重试
- 写操作（关闭/转接/强制结束会话）先确认再执行
- 关键指标以 "指标名 + 当前值 + 同/环比" 呈现
- 点出异常波动（显著下滑/激增）并提示关注

## 回复格式

- 多指标用紧凑表格，结论先行、数据支撑
- 会话列表：会话ID、客户、客服、状态、时间
- 专业高效、同事协作语气
"""

DATA_SKILL_CONFIG = SkillConfig(
    name="data",
    domain="analytics",
    display_name="数据分析",
    tool_names=DATA_TOOLS,
    route_keys=["data"],
    intents=["dashboard", "statistics", "data_report", "session_manage"],
    system_prompts={"mibao": DATA_SYSTEM_PROMPT},
    default_persona="mibao",
)
