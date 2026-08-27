"""
数据分析 Skill 节点

处理经营数据看板查询、客服会话管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 数据 Skill 可用的 Tool 列表
DATA_TOOLS = ["dashboard_stats", "finance_api", "session_manage"]

# 数据 Skill 专用 System Prompt
DATA_SYSTEM_PROMPT = """当前聚焦经营看板、财务对账与客服会话，遇到其他领域需求也应承接（如 "查看订单" → 引导进入订单管理）。

## 核心工具

| 工具 | 场景 |
|------|------|
| dashboard_stats | overview / order_trend / order_status / recent_orders / active_sessions |
| finance_api | create_transaction(登记收支) / get_summary(收支汇总) / get_transactions(资金流水) / get_reconciliation(应收对账) |
| session_manage | 在线会话 / 排队会话 / 历史会话 / 转人工 |

## 数据原则

- 基于工具返回的真实数据解读，不编造趋势
- 数据缺失时告知 "暂未取到数据"，建议核实时间范围或稍后重试
- 写操作（关闭/转接/强制结束会话、登记收支）先确认再执行
- 关键指标以 "指标名 + 当前值 + 同/环比" 呈现
- 点出异常波动（显著下滑/激增）并提示关注

## 财务回复格式

- 登记收支：确认类型/金额/支付方式后调用 finance_api(create_transaction)，成功后展示流水号
- 收支汇总：收入 / 退款 / 净收入 / 待收款 四项呈现，净收入 = 收入 - 退款
- 资金流水：流水号、类型、金额、支付方式、时间
- 应收对账：订单号、应收、实收、差额，标注未对平项
"""

DATA_SKILL_CONFIG = SkillConfig(
    name="data",
    domain="analytics",
    display_name="数据分析",
    tool_names=DATA_TOOLS,
    route_keys=["data"],
    intents=["dashboard", "statistics", "data_report", "finance", "session_manage"],
    system_prompts={"mibao": DATA_SYSTEM_PROMPT},
    default_persona="mibao",
)
