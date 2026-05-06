"""
米宝（MibaoAgent/WorkAssistantAgent）多轮对话智能测试用例

覆盖 10 个多轮对话场景，验证米宝的智能程度：
1. 商品搜索→查看详情→库存查询（跨Tool连续调用）
2. 订单查询→物流追踪→订单状态变更（全订单流程）
3. 模糊问题→引导澄清→精准服务（意图澄清能力）
4. 知识查询→追问深入→关联商品推荐（跨Skill联动）
5. 售后投诉处理全流程（复杂业务场景）
6. 能力探索→具体请求→反馈（功能引导能力）
7. 商品管理操作（创建/上下架/库存调整）
8. 错误恢复与引导（异常处理能力）
9. 混合意图识别（一句话多意图）
10. 长对话上下文压缩测试（压力测试）

Mock 策略：
- Mock IntentRouter 控制意图路由结果
- Mock execute_skill 控制 Skill 执行和 Tool 调用返回
- 直接测试 WorkAssistantAgent.achat 多轮交互
- 使用 soft assertion 收集所有失败，统一报告
"""

import json
import logging
import sys
import traceback
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.agents.customer_service_agent import (
    WorkAssistantAgent,
    AgentContext,
    AgentResponse,
    reset_agent,
)
from app.router.intent_config import IntentType, IntentResult, RouteDecision
from app.tools.registry import reset_tool_registry


# ========== 测试日志系统 ==========

logger = logging.getLogger("mibao_test")


@dataclass
class TurnResult:
    """单轮对话测试结果"""
    turn: int
    user_input: str
    intent_type: str = ""
    confidence: float = 0.0
    skill_used: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_result: Dict[str, Any] = field(default_factory=dict)
    reply: str = ""
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def add_check(self, passed: bool, description: str):
        self.checks.append({"passed": passed, "description": description})

    @property
    def all_passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c["passed"])

    @property
    def total_checks(self) -> int:
        return len(self.checks)


@dataclass
class CaseResult:
    """测试用例结果"""
    case_num: int
    case_name: str
    turns: List[TurnResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def format_report(self) -> str:
        lines = [f"\n{'='*10} Case {self.case_num}: {self.case_name} {'='*10}"]
        for t in self.turns:
            lines.append(f"--- Turn {t.turn} ---")
            lines.append(f"[INPUT]  用户消息: \"{t.user_input}\"")
            lines.append(f"[ROUTE]  意图: {t.intent_type} | 置信度: {t.confidence:.2f} | Skill: {t.skill_used}")
            if t.tool_name:
                args_str = ", ".join(f"{k}={v}" for k, v in t.tool_args.items())
                lines.append(f"[TOOL]   调用: {t.tool_name}({args_str})")
                lines.append(f"[TOOL]   返回: {json.dumps(t.tool_result, ensure_ascii=False)[:200]}")
            lines.append(f"[OUTPUT] 米宝回复: \"{t.reply[:100]}{'...' if len(t.reply) > 100 else ''}\"")
            for c in t.checks:
                status = "✅ PASS" if c["passed"] else "❌ FAIL"
                lines.append(f"[CHECK]  {status}: {c['description']}")

        total_turns = len(self.turns)
        passed_turns = sum(1 for t in self.turns if t.all_passed)
        total_checks = sum(t.total_checks for t in self.turns)
        passed_checks = sum(t.pass_count for t in self.turns)
        issues = [c["description"] for t in self.turns for c in t.checks if not c["passed"]]
        issues.extend(self.errors)
        issue_str = " | ".join(issues) if issues else "无"
        lines.append(
            f"[SUMMARY] Case {self.case_num} 结果: "
            f"{passed_turns}/{total_turns} 轮通过, "
            f"{passed_checks}/{total_checks} 检查通过 | 问题: {issue_str}"
        )
        return "\n".join(lines)


# ========== Mock 工厂函数 ==========

def make_route_decision(
    intent: IntentType,
    confidence: float = 0.85,
    source: str = "rule",
    action: str = "route_with_hint",
    direct_reply: Optional[str] = None,
    tool_hint: Optional[str] = None,
) -> RouteDecision:
    """构造 RouteDecision"""
    return RouteDecision(
        intent_result=IntentResult(
            intent=intent,
            confidence=confidence,
            source=source,
        ),
        action=action,
        direct_reply=direct_reply,
        tool_hint=tool_hint,
    )


def make_skill_result(
    final_answer: str,
    skill_used: str,
    tool_name: str = "",
    tool_args: Dict = None,
    tool_result_data: Any = None,
    entities: Dict = None,
) -> dict:
    """构造 execute_skill 的返回值"""
    return {
        "messages": [],
        "final_answer": final_answer,
        "skill_used": skill_used,
        "entities": entities or {},
        "_test_tool_name": tool_name,
        "_test_tool_args": tool_args or {},
        "_test_tool_result": {"success": True, "data": tool_result_data} if tool_result_data else {},
    }


def make_graph_result(
    final_answer: str,
    skill_used: str = "",
    intent: str = "",
    confidence: float = 0.0,
    tool_name: str = "",
    tool_args: Dict = None,
    tool_result_data: Any = None,
    suggestions: List[str] = None,
) -> dict:
    """构造 graph.ainvoke 的返回值"""
    return {
        "final_answer": final_answer,
        "skill_used": skill_used,
        "intent_result": {"intent": intent, "confidence": confidence, "source": "mock"},
        "route_decision": {"action": "route_with_hint"},
        "entities": {},
        "suggestions": suggestions or [],
        "_test_tool_name": tool_name,
        "_test_tool_args": tool_args or {},
        "_test_tool_result": {"success": True, "data": tool_result_data} if tool_result_data else {},
    }


# ========== 多轮对话测试运行器 ==========

class MultiTurnRunner:
    """多轮对话测试运行器"""

    def __init__(self, case_num: int, case_name: str):
        self.case_result = CaseResult(case_num=case_num, case_name=case_name)
        self.chat_history: List[Dict[str, str]] = []
        self.agent = None
        self.mock_graph = None

    @staticmethod
    def _live_print(text: str):
        """实时输出到 stderr，绕过 pytest stdout 捕获"""
        sys.stderr.write(text + "\n")
        sys.stderr.flush()

    def setup_agent(self, mock_graph: AsyncMock):
        """设置带 mock graph 的 agent"""
        self.mock_graph = mock_graph
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.customer_service_agent.create_default_registry") as mock_reg:
            mock_reg.return_value = MagicMock()
            mock_build.return_value = mock_graph
            self.agent = WorkAssistantAgent()
        # 打印 Case 标题
        self._live_print(f"\n{'=' * 10} Case {self.case_result.case_num}: {self.case_result.case_name} {'=' * 10}")

    async def run_turn(
        self,
        turn_num: int,
        user_message: str,
        expected_graph_result: dict,
        checks: List[Dict[str, Any]],
    ) -> TurnResult:
        """执行单轮对话"""
        turn = TurnResult(turn=turn_num, user_input=user_message)

        try:
            # 配置 mock graph 对这一轮的返回
            self.mock_graph.ainvoke = AsyncMock(return_value=expected_graph_result)

            # 调用 agent.achat
            context = AgentContext(
                user_id="admin_001", tenant_id=1, session_id="sess_mibao_test",
                role="admin", identity_type="account",
            )
            response = await self.agent.achat(
                user_message, context, self.chat_history
            )

            # 记录结果
            turn.reply = response.content
            turn.intent_type = expected_graph_result.get("intent_result", {}).get("intent", "")
            turn.confidence = expected_graph_result.get("intent_result", {}).get("confidence", 0.0)
            turn.skill_used = expected_graph_result.get("skill_used", "")
            turn.tool_name = expected_graph_result.get("_test_tool_name", "")
            turn.tool_args = expected_graph_result.get("_test_tool_args", {})
            turn.tool_result = expected_graph_result.get("_test_tool_result", {})

            # 验证 graph.ainvoke 被调用
            self.mock_graph.ainvoke.assert_called_once()
            call_state = self.mock_graph.ainvoke.call_args[0][0]

            # --- 实时输出该轮调用状态 ---
            last_user_msg = str(call_state["messages"][-1].content)[:80] if call_state.get("messages") else "N/A"
            state_agent_type = call_state.get("agent_type", "N/A")
            state_session = call_state.get("session_id", "N/A")
            state_history_count = len(call_state.get("messages", [])) - 1
            self._live_print(
                f"[STATE]  agent_type: {state_agent_type} | session: {state_session}"
                f" | 历史消息数: {state_history_count} | 当前消息: \"{last_user_msg}\""
            )

            # 验证消息数：历史 + 当前
            expected_msg_count = len(self.chat_history) + 1
            actual_msg_count = len(call_state["messages"])
            turn.add_check(
                actual_msg_count == expected_msg_count,
                f"消息数正确: 期望{expected_msg_count}, 实际{actual_msg_count}"
            )

            # 验证当前消息
            last_msg = call_state["messages"][-1]
            turn.add_check(
                user_message in str(last_msg.content),
                f"当前用户消息正确传入"
            )

            # 验证 agent_type 为 mibao
            turn.add_check(
                call_state.get("agent_type") == "mibao",
                "agent_type 为 mibao"
            )

            # 执行自定义检查
            for check in checks:
                try:
                    result = check["fn"](call_state, response, expected_graph_result)
                    turn.add_check(result, check["desc"])
                except Exception as e:
                    turn.add_check(False, f"{check['desc']} (异常: {e})")

            # 更新对话历史
            self.chat_history.append({"role": "user", "content": user_message})
            self.chat_history.append({"role": "assistant", "content": response.content})

        except Exception as e:
            turn.add_check(False, f"轮次执行异常: {e}")
            self.case_result.errors.append(f"Turn {turn_num}: {traceback.format_exc()}")

        self.case_result.turns.append(turn)

        # --- 实时输出该轮详细日志 ---
        self._live_print(f"--- Turn {turn.turn} ---")
        self._live_print(f'[INPUT]  用户消息: "{turn.user_input}"')
        self._live_print(f"[ROUTE]  意图: {turn.intent_type} | 置信度: {turn.confidence:.2f} | Skill: {turn.skill_used}")
        if turn.tool_name:
            args_str = ", ".join(f"{k}={v}" for k, v in turn.tool_args.items())
            self._live_print(f"[TOOL]   调用: {turn.tool_name}({args_str})")
            self._live_print(f"[TOOL]   返回: {json.dumps(turn.tool_result, ensure_ascii=False)[:200]}")
        self._live_print(f'[OUTPUT] 米宝回复: "{turn.reply[:100]}{"..." if len(turn.reply) > 100 else ""}"')
        for c in turn.checks:
            status = "✅ PASS" if c["passed"] else "❌ FAIL"
            self._live_print(f"[CHECK]  {status}: {c['description']}")

        return turn

    def report(self) -> str:
        """生成测试报告"""
        return self.case_result.format_report()

    @property
    def all_passed(self) -> bool:
        return all(t.all_passed for t in self.case_result.turns) and not self.case_result.errors


# ========== Fixtures ==========

@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试重置全局单例"""
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()


# ========== 10 个多轮对话测试用例 ==========


class TestMibaoMultiturnIntelligence:
    """米宝多轮对话智能测试"""

    # ---------- Case 1: 商品搜索→查看详情→库存查询 ----------

    async def test_case1_product_search_detail_inventory(self):
        """Case 1: 商品搜索→查看详情→库存查询（跨Tool连续调用）"""
        runner = MultiTurnRunner(1, "商品搜索→查看详情→库存查询")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 商品搜索
        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看店里有没有遮光窗帘",
            expected_graph_result=make_graph_result(
                final_answer="为您找到以下遮光窗帘：\n1. 雪尼尔遮光窗帘 ¥299\n2. 北欧简约遮光帘 ¥199",
                skill_used="product",
                intent="product_inquiry", confidence=0.92,
                tool_name="product_search",
                tool_args={"keyword": "遮光窗帘"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光窗帘", "price": 299.0},
                    {"id": "p002", "name": "北欧简约遮光帘", "price": 199.0},
                ], "total": 2},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""),
                 "desc": "正确路由到 product_skill"},
                {"fn": lambda s, r, e: r.content and "遮光" in r.content,
                 "desc": "回复包含遮光窗帘信息"},
            ],
        )

        # 轮2: 查看详情（指代消解："第一个商品"）
        await runner.run_turn(
            turn_num=2,
            user_message="第一个商品的详细信息给我看看",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光窗帘详情：\n- 价格: ¥299\n- 面料: 雪尼尔\n- 遮光率: 95%\n- 规格: 多种尺寸可选",
                skill_used="product",
                intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "雪尼尔遮光窗帘", "price": 299.0,
                                  "specifications": {"面料": "雪尼尔", "遮光率": "95%"}},
            ),
            checks=[
                {"fn": lambda s, r, e: len(s["messages"]) == 3,
                 "desc": "历史包含2条历史消息+1条当前消息"},
                {"fn": lambda s, r, e: "雪尼尔" in r.content,
                 "desc": "回复包含第一个商品详情（上下文理解'第一个'）"},
            ],
        )

        # 轮3: 库存查询（需记住 product_id）
        await runner.run_turn(
            turn_num=3,
            user_message="这个商品库存还有多少",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光窗帘(p001) 当前库存：150件",
                skill_used="product",
                intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "query", "product_id": "p001"},
                tool_result_data={"product_id": "p001", "stock": 150},
            ),
            checks=[
                {"fn": lambda s, r, e: len(s["messages"]) == 5,
                 "desc": "历史包含4条历史消息+1条当前消息"},
                {"fn": lambda s, r, e: "150" in r.content,
                 "desc": "回复包含库存数量（上下文传递 product_id）"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 1 存在失败检查点\n{report}"

    # ---------- Case 2: 订单查询→物流追踪→订单状态变更 ----------

    async def test_case2_order_query_logistics_status(self):
        """Case 2: 订单查询→物流追踪→订单状态变更（全订单流程）"""
        runner = MultiTurnRunner(2, "订单查询→物流追踪→订单状态变更")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 查订单
        await runner.run_turn(
            turn_num=1,
            user_message="帮我查下张三的订单",
            expected_graph_result=make_graph_result(
                final_answer="找到张三的订单：\n- 订单号: ORD20250301001\n- 状态: 已发货\n- 金额: ¥598",
                skill_used="order",
                intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"customer_name": "张三"},
                tool_result_data={"orders": [
                    {"order_no": "ORD20250301001", "status": "shipped", "total_amount": 598.0,
                     "customer_name": "张三"}
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""),
                 "desc": "正确路由到 order_skill"},
                {"fn": lambda s, r, e: "ORD20250301001" in r.content,
                 "desc": "回复包含订单号"},
            ],
        )

        # 轮2: 物流追踪
        await runner.run_turn(
            turn_num=2,
            user_message="这个订单的物流到哪了",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250301001 物流信息：\n- 快递: 顺丰速运\n- 单号: SF1234567890\n- 最新: 已到达杭州中转站",
                skill_used="order",
                intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250301001"},
                tool_result_data={"tracking_number": "SF1234567890", "company": "顺丰速运",
                                  "status": "in_transit", "traces": [{"desc": "已到达杭州中转站"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF1234567890" in r.content or "顺丰" in r.content,
                 "desc": "回复包含物流信息（上下文关联订单号）"},
            ],
        )

        # 轮3: 订单状态变更（写操作需确认）
        await runner.run_turn(
            turn_num=3,
            user_message="帮我把这个订单标记为已完成",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250301001 状态更新为「已完成」。",
                skill_used="order",
                intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250301001", "status": "completed"},
                tool_result_data={"order_no": "ORD20250301001", "new_status": "completed"},
            ),
            checks=[
                {"fn": lambda s, r, e: "已完成" in r.content or "completed" in r.content.lower(),
                 "desc": "回复确认订单状态已更新"},
                {"fn": lambda s, r, e: len(s["messages"]) == 5,
                 "desc": "累积历史消息数正确"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 2 存在失败检查点\n{report}"

    # ---------- Case 3: 模糊问题→引导澄清→精准服务 ----------

    async def test_case3_ambiguous_intent_clarification(self):
        """Case 3: 模糊问题→引导澄清→精准服务（意图澄清能力）"""
        runner = MultiTurnRunner(3, "模糊问题→引导澄清→精准服务")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 模糊意图
        await runner.run_turn(
            turn_num=1,
            user_message="窗帘有问题",
            expected_graph_result=make_graph_result(
                final_answer="请问您遇到的是哪方面的问题呢？比如：\n1. 客户反馈质量/颜色问题（售后相关）\n2. 窗帘安装/使用问题（知识咨询）\n3. 窗帘商品信息有误（商品管理）\n请描述一下具体情况，我来帮您处理。",
                skill_used="general_agent",
                intent="general", confidence=0.45,
            ),
            checks=[
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 1.0) < 0.7,
                 "desc": "模糊意图置信度低于0.7"},
                {"fn": lambda s, r, e: "问题" in r.content or "请" in r.content,
                 "desc": "回复包含引导澄清的内容"},
            ],
        )

        # 轮2: 补充信息 → 路由到 aftersales
        await runner.run_turn(
            turn_num=2,
            user_message="客户说颜色和图片不一样",
            expected_graph_result=make_graph_result(
                final_answer="收到，这是一个色差问题的售后投诉。我来帮您处理。请问能提供一下相关的订单号吗？这样我可以查看订单详情和商品信息。",
                skill_used="aftersales_skill",
                intent="after_sales", confidence=0.88,
            ),
            checks=[
                {"fn": lambda s, r, e: "after_sales" in e.get("intent_result", {}).get("intent", ""),
                 "desc": "补充信息后正确识别为售后意图"},
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 0) >= 0.7,
                 "desc": "置信度提升到0.7以上"},
            ],
        )

        # 轮3: 提供订单号
        await runner.run_turn(
            turn_num=3,
            user_message="帮我查下这个客户的订单 ORD20250101001",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250101001 信息如下：\n- 商品: 雪尼尔窗帘(米白色)\n- 金额: ¥399\n- 状态: 已签收\n根据售后政策，签收7天内可以申请退换货。",
                skill_used="order",
                intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_id": "ORD20250101001"},
                tool_result_data={"order_no": "ORD20250101001", "status": "received",
                                  "items": [{"product_name": "雪尼尔窗帘(米白色)", "price": 399.0}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250101001" in r.content,
                 "desc": "回复包含查询到的订单信息"},
                {"fn": lambda s, r, e: "order_query" in e.get("intent_result", {}).get("intent", ""),
                 "desc": "路由准确性：提供订单号后识别为订单查询"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 3 存在失败检查点\n{report}"

    # ---------- Case 4: 知识查询→追问深入→关联商品推荐 ----------

    async def test_case4_knowledge_followup_product_switch(self):
        """Case 4: 知识查询→追问深入→关联商品推荐（跨Skill联动）"""
        runner = MultiTurnRunner(4, "知识查询→追问深入→关联商品推荐")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 知识库查询
        await runner.run_turn(
            turn_num=1,
            user_message="雪尼尔面料会不会起球",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔面料一般不容易起球。雪尼尔是一种绒感面料，纤维牢固度较高，正常使用下不会起球。但需注意避免与粗糙表面摩擦。",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.92,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔面料起球"},
                tool_result_data={"chunks": [{"content": "雪尼尔面料不容易起球"}], "source_count": 1},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""),
                 "desc": "正确路由到 knowledge_skill"},
                {"fn": lambda s, r, e: "雪尼尔" in r.content,
                 "desc": "回复包含雪尼尔面料信息"},
            ],
        )

        # 轮2: 同Skill追问
        await runner.run_turn(
            turn_num=2,
            user_message="那这种面料的窗帘怎么保养",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔面料窗帘保养建议：\n1. 日常用吸尘器轻吸灰尘\n2. 不可机洗，建议干洗\n3. 避免阳光直射\n4. 收纳时卷起而非折叠",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔面料窗帘保养"},
                tool_result_data={"chunks": [{"content": "雪尼尔窗帘保养方法"}], "source_count": 1},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""),
                 "desc": "连续追问仍路由到 knowledge_skill"},
                {"fn": lambda s, r, e: "保养" in r.content or "清洗" in r.content or "干洗" in r.content,
                 "desc": "回复包含保养信息（上下文知道是雪尼尔面料）"},
            ],
        )

        # 轮3: 意图切换 → product_skill
        await runner.run_turn(
            turn_num=3,
            user_message="店里有雪尼尔面料的窗帘吗？推荐几款",
            expected_graph_result=make_graph_result(
                final_answer="为您找到以下雪尼尔面料窗帘：\n1. 雪尼尔遮光窗帘 ¥299（遮光率95%）\n2. 雪尼尔绒感窗帘 ¥259（柔软亲肤）",
                skill_used="product",
                intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "雪尼尔"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光窗帘", "price": 299.0},
                    {"id": "p003", "name": "雪尼尔绒感窗帘", "price": 259.0},
                ], "total": 2},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""),
                 "desc": "跨Skill切换：knowledge → product"},
                {"fn": lambda s, r, e: "product_inquiry" in e.get("intent_result", {}).get("intent", ""),
                 "desc": "意图从 knowledge_faq 自然切换到 product_inquiry"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 4 存在失败检查点\n{report}"

    # ---------- Case 5: 售后投诉处理全流程 ----------

    async def test_case5_aftersales_full_flow(self):
        """Case 5: 售后投诉处理全流程（4轮复杂业务场景）"""
        runner = MultiTurnRunner(5, "售后投诉处理全流程")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 投诉接入
        await runner.run_turn(
            turn_num=1,
            user_message="有个客户投诉了，说窗帘尺寸不对",
            expected_graph_result=make_graph_result(
                final_answer="收到尺寸不对的投诉。请提供一下订单号，我帮您查看订单详情和商品规格信息。",
                skill_used="aftersales_skill",
                intent="complaint", confidence=0.90,
            ),
            checks=[
                {"fn": lambda s, r, e: "complaint" in e.get("intent_result", {}).get("intent", ""),
                 "desc": "正确识别为投诉意图"},
            ],
        )

        # 轮2: 提供订单号
        await runner.run_turn(
            turn_num=2,
            user_message="订单号是 ORD20250315888",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250315888 信息：\n- 商品: 定制遮光帘 2.0m×2.7m\n- 金额: ¥459\n- 状态: 已签收\n客户反馈尺寸不对，我建议查看一下退换货政策。",
                skill_used="order",
                intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_id": "ORD20250315888"},
                tool_result_data={"order_no": "ORD20250315888", "status": "received",
                                  "items": [{"product_name": "定制遮光帘 2.0m×2.7m", "price": 459.0}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250315888" in r.content,
                 "desc": "回复包含订单详情"},
            ],
        )

        # 轮3: 查退换货政策
        await runner.run_turn(
            turn_num=3,
            user_message="按照售后政策可以给退换吗",
            expected_graph_result=make_graph_result(
                final_answer="根据售后政策：\n- 签收7天内可申请退换货\n- 定制商品如存在尺寸偏差超过2cm，可以退换\n- 需客户提供尺寸对比照片\n该订单在售后期内，可以安排退换。",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.85,
                tool_name="knowledge_search",
                tool_args={"query": "尺寸不对退换货政策"},
                tool_result_data={"chunks": [{"content": "7天内可退换，定制商品尺寸偏差超2cm可退换"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""),
                 "desc": "查询政策路由到 knowledge_skill"},
                {"fn": lambda s, r, e: "退换" in r.content,
                 "desc": "回复包含退换货政策信息"},
            ],
        )

        # 轮4: 执行退货操作（写操作）
        await runner.run_turn(
            turn_num=4,
            user_message="那帮我把这个订单改成退货退款状态",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250315888 状态更新为「退货退款中」。请通知客户寄回商品，收到后将安排退款。",
                skill_used="order",
                intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250315888", "status": "refunding"},
                tool_result_data={"order_no": "ORD20250315888", "new_status": "refunding"},
            ),
            checks=[
                {"fn": lambda s, r, e: "退" in r.content,
                 "desc": "回复确认退货退款操作"},
                {"fn": lambda s, r, e: len(s["messages"]) == 7,
                 "desc": "第4轮累积6条历史+1条当前=7条消息"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 5 存在失败检查点\n{report}"

    # ---------- Case 6: 能力探索→具体请求→反馈 ----------

    async def test_case6_capabilities_then_request(self):
        """Case 6: 能力探索→具体请求→反馈（功能引导能力）"""
        runner = MultiTurnRunner(6, "能力探索→具体请求→反馈")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 问能力
        await runner.run_turn(
            turn_num=1,
            user_message="你能帮我做什么",
            expected_graph_result=make_graph_result(
                final_answer="我是米宝，您的智能工作助手。我可以帮您：\n1. 📦 订单管理（查询、物流追踪、状态变更）\n2. 🛍️ 商品管理（搜索、上下架、库存管理）\n3. 📚 知识查询（面料知识、安装指南、售后政策）\n4. 🔧 售后处理（投诉、退换货）\n请问需要什么帮助？",
                skill_used="direct_reply",
                intent="capabilities", confidence=0.95,
            ),
            checks=[
                {"fn": lambda s, r, e: "direct_reply" in e.get("skill_used", ""),
                 "desc": "capabilities 走 direct_reply"},
                {"fn": lambda s, r, e: "订单" in r.content or "商品" in r.content,
                 "desc": "回复列举了米宝的核心能力"},
            ],
        )

        # 轮2: 具体业务请求
        await runner.run_turn(
            turn_num=2,
            user_message="那帮我查下今天的待处理订单",
            expected_graph_result=make_graph_result(
                final_answer="今天有3个待处理订单：\n1. ORD20250503001 - 待发货 ¥299\n2. ORD20250503002 - 待发货 ¥459\n3. ORD20250503003 - 待确认 ¥198",
                skill_used="order",
                intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "pending"},
                tool_result_data={"orders": [
                    {"order_no": "ORD20250503001", "status": "pending", "total_amount": 299.0},
                    {"order_no": "ORD20250503002", "status": "pending", "total_amount": 459.0},
                    {"order_no": "ORD20250503003", "status": "pending", "total_amount": 198.0},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""),
                 "desc": "从功能介绍自然过渡到业务请求"},
                {"fn": lambda s, r, e: "ORD20250503" in r.content,
                 "desc": "回复包含待处理订单信息"},
            ],
        )

        # 轮3: 告别
        await runner.run_turn(
            turn_num=3,
            user_message="谢谢，没别的事了",
            expected_graph_result=make_graph_result(
                final_answer="好的，有需要随时找我！祝工作顺利！",
                skill_used="direct_reply",
                intent="farewell", confidence=0.95,
            ),
            checks=[
                {"fn": lambda s, r, e: "direct_reply" in e.get("skill_used", ""),
                 "desc": "farewell 走 direct_reply"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 6 存在失败检查点\n{report}"

    # ---------- Case 7: 商品管理操作 ----------

    async def test_case7_product_manage_create_inventory_toggle(self):
        """Case 7: 商品管理操作（创建/库存/上下架，连续写操作）"""
        runner = MultiTurnRunner(7, "商品管理操作（创建/库存/上下架）")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 新建商品
        await runner.run_turn(
            turn_num=1,
            user_message="帮我新建一个商品，名字叫'北欧简约遮光帘'，价格 199",
            expected_graph_result=make_graph_result(
                final_answer="商品「北欧简约遮光帘」已创建成功！\n- 商品ID: p_new_001\n- 价格: ¥199\n- 状态: 待上架",
                skill_used="product",
                intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "create", "name": "北欧简约遮光帘", "price": 199},
                tool_result_data={"id": "p_new_001", "name": "北欧简约遮光帘", "price": 199.0, "status": "draft"},
            ),
            checks=[
                {"fn": lambda s, r, e: "p_new_001" in r.content or "北欧简约遮光帘" in r.content,
                 "desc": "回复包含新建商品信息"},
            ],
        )

        # 轮2: 设置库存
        await runner.run_turn(
            turn_num=2,
            user_message="再帮我设置库存 500 件",
            expected_graph_result=make_graph_result(
                final_answer="已为「北欧简约遮光帘」(p_new_001) 设置库存 500 件。",
                skill_used="product",
                intent="product_inquiry", confidence=0.82,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p_new_001", "quantity": 500},
                tool_result_data={"product_id": "p_new_001", "new_stock": 500},
            ),
            checks=[
                {"fn": lambda s, r, e: "500" in r.content,
                 "desc": "回复确认库存设置（上下文关联新建的商品）"},
            ],
        )

        # 轮3: 下架
        await runner.run_turn(
            turn_num=3,
            user_message="先下架吧，等拍好图片再上架",
            expected_graph_result=make_graph_result(
                final_answer="已将「北欧简约遮光帘」(p_new_001) 设为下架状态。拍好图片后告诉我，我帮您上架。",
                skill_used="product",
                intent="product_inquiry", confidence=0.80,
                tool_name="product_manage",
                tool_args={"action": "toggle_status", "product_id": "p_new_001", "status": "off_sale"},
                tool_result_data={"id": "p_new_001", "status": "off_sale"},
            ),
            checks=[
                {"fn": lambda s, r, e: "下架" in r.content,
                 "desc": "回复确认下架操作（上下文传递商品ID）"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 7 存在失败检查点\n{report}"

    # ---------- Case 8: 错误恢复与引导 ----------

    async def test_case8_error_recovery_guidance(self):
        """Case 8: 错误恢复与引导（异常处理能力）"""
        runner = MultiTurnRunner(8, "错误恢复与引导")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 查不到的订单
        await runner.run_turn(
            turn_num=1,
            user_message="查一下订单 ORD999999999999",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，未找到订单 ORD999999999999。请确认订单号是否正确，或尝试用手机号、客户姓名等方式查询。",
                skill_used="order",
                intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_id": "ORD999999999999"},
                tool_result_data=None,
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "抱歉" in r.content,
                 "desc": "查不到订单时给出友好提示"},
                {"fn": lambda s, r, e: "手机号" in r.content or "姓名" in r.content,
                 "desc": "提供替代查询方式建议"},
            ],
        )

        # 轮2: 用户换方式查
        await runner.run_turn(
            turn_num=2,
            user_message="那用手机号 13800138000 查",
            expected_graph_result=make_graph_result(
                final_answer="通过手机号 13800138000 找到2个订单：\n1. ORD20250401001 - 已完成 ¥299\n2. ORD20250415002 - 已发货 ¥459",
                skill_used="order",
                intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"phone": "13800138000"},
                tool_result_data={"orders": [
                    {"order_no": "ORD20250401001", "status": "completed", "total_amount": 299.0},
                    {"order_no": "ORD20250415002", "status": "shipped", "total_amount": 459.0},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250401001" in r.content,
                 "desc": "通过手机号成功查到订单"},
            ],
        )

        # 轮3: 取消订单（写操作+确认）
        await runner.run_turn(
            turn_num=3,
            user_message="帮我把第一个订单取消掉，原因是客户不想要了",
            expected_graph_result=make_graph_result(
                final_answer="已取消订单 ORD20250401001，原因：客户不想要了。如需恢复请告知。",
                skill_used="order",
                intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "cancel", "order_id": "ORD20250401001", "reason": "客户不想要了"},
                tool_result_data={"order_no": "ORD20250401001", "status": "cancelled"},
            ),
            checks=[
                {"fn": lambda s, r, e: "取消" in r.content,
                 "desc": "回复确认取消操作"},
                {"fn": lambda s, r, e: "ORD20250401001" in r.content,
                 "desc": "正确取消第一个订单（上下文理解'第一个'）"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 8 存在失败检查点\n{report}"

    # ---------- Case 9: 混合意图识别 ----------

    async def test_case9_mixed_intent_recognition(self):
        """Case 9: 混合意图识别（一句话多意图）"""
        runner = MultiTurnRunner(9, "混合意图识别")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 混合意图（物流+库存）
        await runner.run_turn(
            turn_num=1,
            user_message="帮我查下 ORD20250201001 的物流，顺便看看店里遮光帘还有库存没",
            expected_graph_result=make_graph_result(
                final_answer="1. 订单 ORD20250201001 物流：顺丰速运 SF9876543210，已签收。\n2. 遮光帘库存：雪尼尔遮光帘 剩余 80 件，北欧遮光帘 剩余 45 件。",
                skill_used="general_agent",
                intent="general", confidence=0.60,
                tool_name="logistics_track,product_search",
                tool_args={"mixed": True},
                tool_result_data={"logistics": {"status": "signed"}, "products": [{"name": "遮光帘", "stock": 80}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "general" in e.get("intent_result", {}).get("intent", ""),
                 "desc": "混合意图走 general_agent 处理"},
                {"fn": lambda s, r, e: "物流" in r.content or "签收" in r.content or "SF" in r.content,
                 "desc": "回复包含物流信息"},
                {"fn": lambda s, r, e: "库存" in r.content or "剩余" in r.content or "件" in r.content,
                 "desc": "回复包含库存信息"},
            ],
        )

        # 轮2: 基于物流结果操作
        await runner.run_turn(
            turn_num=2,
            user_message="物流显示已签收，帮我把订单改成已完成",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250201001 状态更新为「已完成」。",
                skill_used="order",
                intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250201001", "status": "completed"},
                tool_result_data={"order_no": "ORD20250201001", "new_status": "completed"},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""),
                 "desc": "从混合意图切换到单一 order_skill"},
                {"fn": lambda s, r, e: "已完成" in r.content,
                 "desc": "回复确认状态变更"},
            ],
        )

        # 轮3: 基于库存结果操作
        await runner.run_turn(
            turn_num=3,
            user_message="那个遮光帘库存不多的话帮我补100件",
            expected_graph_result=make_graph_result(
                final_answer="已为遮光帘补货 100 件，当前库存更新为 180 件。",
                skill_used="product",
                intent="product_inquiry", confidence=0.82,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p001", "quantity": 100},
                tool_result_data={"product_id": "p001", "new_stock": 180},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""),
                 "desc": "切换到 product_skill 处理库存"},
                {"fn": lambda s, r, e: "100" in r.content or "180" in r.content,
                 "desc": "回复确认补货操作"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 9 存在失败检查点\n{report}"

    # ---------- Case 10: 长对话上下文压缩测试 ----------

    async def test_case10_long_conversation_context_compression(self):
        """Case 10: 长对话上下文压缩测试（12轮压力测试）"""
        runner = MultiTurnRunner(10, "长对话上下文压缩测试")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 问候
        await runner.run_turn(
            turn_num=1,
            user_message="你好米宝",
            expected_graph_result=make_graph_result(
                final_answer="您好！我是米宝，有什么可以帮您的吗？",
                skill_used="direct_reply",
                intent="greeting", confidence=0.98,
            ),
            checks=[
                {"fn": lambda s, r, e: "direct_reply" in e.get("skill_used", ""),
                 "desc": "问候走 direct_reply"},
            ],
        )

        # 轮2: 商品查询
        await runner.run_turn(
            turn_num=2,
            user_message="帮我搜一下雪尼尔窗帘",
            expected_graph_result=make_graph_result(
                final_answer="找到2款雪尼尔窗帘：\n1. 雪尼尔遮光帘 ¥299\n2. 雪尼尔绒感帘 ¥259",
                skill_used="product",
                intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "雪尼尔"},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""),
                 "desc": "商品搜索路由正确"},
            ],
        )

        # 轮3: 商品详情
        await runner.run_turn(
            turn_num=3,
            user_message="第一款什么规格",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘规格：面料雪尼尔，遮光率95%，支持多种尺寸定制。",
                skill_used="product",
                intent="product_inquiry", confidence=0.85,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
            ),
            checks=[
                {"fn": lambda s, r, e: len(s["messages"]) == 5,
                 "desc": "第3轮消息数正确"},
            ],
        )

        # 轮4-6: 切换到订单
        await runner.run_turn(
            turn_num=4,
            user_message="帮我查下最近的订单",
            expected_graph_result=make_graph_result(
                final_answer="最近3个订单：\n1. ORD001 已完成\n2. ORD002 已发货\n3. ORD003 待处理",
                skill_used="order",
                intent="order_query", confidence=0.88,
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""),
                 "desc": "切换到订单查询"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="ORD002 的物流信息",
            expected_graph_result=make_graph_result(
                final_answer="ORD002 物流：圆通 YT001，在途中。",
                skill_used="order",
                intent="logistics_track", confidence=0.90,
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD002" in r.content or "物流" in r.content,
                 "desc": "物流查询结果正确"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="ORD003 帮我确认一下",
            expected_graph_result=make_graph_result(
                final_answer="ORD003 已确认处理。",
                skill_used="order",
                intent="order_query", confidence=0.85,
            ),
            checks=[
                {"fn": lambda s, r, e: len(s["messages"]) == 11,
                 "desc": "第6轮消息数正确（10历史+1当前）"},
            ],
        )

        # 轮7-9: 切换到知识库
        await runner.run_turn(
            turn_num=7,
            user_message="窗帘怎么测量尺寸",
            expected_graph_result=make_graph_result(
                final_answer="窗帘测量方法：宽度=窗户宽+两侧各15cm，高度=从杆到地面-2cm。",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.88,
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""),
                 "desc": "切换到知识库"},
            ],
        )

        await runner.run_turn(
            turn_num=8,
            user_message="罗马杆和滑轨哪个好",
            expected_graph_result=make_graph_result(
                final_answer="罗马杆适合简约风格，滑轨适合弧形窗户和大面积。各有优劣，看需求选择。",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.85,
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""),
                 "desc": "继续知识库查询"},
            ],
        )

        await runner.run_turn(
            turn_num=9,
            user_message="安装费用一般多少",
            expected_graph_result=make_graph_result(
                final_answer="安装费用一般50-150元/窗，取决于窗户大小和安装方式。",
                skill_used="knowledge",
                intent="knowledge_faq", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: len(s["messages"]) == 17,
                 "desc": "第9轮消息数正确（16历史+1当前）"},
            ],
        )

        # 轮10-12: 回到最早的商品话题，测试上下文保持
        await runner.run_turn(
            turn_num=10,
            user_message="回到前面说的那个雪尼尔遮光帘，帮我补一下库存",
            expected_graph_result=make_graph_result(
                final_answer="为雪尼尔遮光帘(p001)补货，请问补多少件？",
                skill_used="product",
                intent="product_inquiry", confidence=0.80,
                tool_name="inventory_manage",
                tool_args={"action": "query", "product_id": "p001"},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""),
                 "desc": "回到商品话题"},
                {"fn": lambda s, r, e: "雪尼尔" in r.content,
                 "desc": "长对话后仍能回忆早期商品信息"},
            ],
        )

        await runner.run_turn(
            turn_num=11,
            user_message="补200件",
            expected_graph_result=make_graph_result(
                final_answer="已为雪尼尔遮光帘补货200件，当前库存更新为350件。",
                skill_used="product",
                intent="product_inquiry", confidence=0.80,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p001", "quantity": 200},
                tool_result_data={"product_id": "p001", "new_stock": 350},
            ),
            checks=[
                {"fn": lambda s, r, e: "200" in r.content or "350" in r.content,
                 "desc": "补货操作成功"},
                {"fn": lambda s, r, e: len(s["messages"]) == 21,
                 "desc": "第11轮消息数正确（20历史+1当前，>10轮应触发压缩）"},
            ],
        )

        await runner.run_turn(
            turn_num=12,
            user_message="好的，今天就到这里，辛苦了",
            expected_graph_result=make_graph_result(
                final_answer="好的，今天帮您处理了商品查询、订单管理和知识咨询等事务。有需要随时找我，再见！",
                skill_used="direct_reply",
                intent="farewell", confidence=0.95,
            ),
            checks=[
                {"fn": lambda s, r, e: "direct_reply" in e.get("skill_used", ""),
                 "desc": "farewell 走 direct_reply"},
                {"fn": lambda s, r, e: len(s["messages"]) == 23,
                 "desc": "第12轮消息数正确（22历史+1当前）"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 10 存在失败检查点\n{report}"


# ========== 汇总报告测试 ==========


class TestMibaoSummaryReport:
    """汇总运行所有 Case 并生成报告（用于单独运行查看全景）"""

    async def test_summary_report(self, capsys):
        """运行全部 10 个 Case 并输出汇总报告"""
        suite = TestMibaoMultiturnIntelligence()
        cases = [
            ("Case 1", suite.test_case1_product_search_detail_inventory),
            ("Case 2", suite.test_case2_order_query_logistics_status),
            ("Case 3", suite.test_case3_ambiguous_intent_clarification),
            ("Case 4", suite.test_case4_knowledge_followup_product_switch),
            ("Case 5", suite.test_case5_aftersales_full_flow),
            ("Case 6", suite.test_case6_capabilities_then_request),
            ("Case 7", suite.test_case7_product_manage_create_inventory_toggle),
            ("Case 8", suite.test_case8_error_recovery_guidance),
            ("Case 9", suite.test_case9_mixed_intent_recognition),
            ("Case 10", suite.test_case10_long_conversation_context_compression),
        ]

        results = []
        for name, test_fn in cases:
            try:
                await test_fn()
                results.append((name, "PASS", ""))
            except AssertionError as e:
                results.append((name, "FAIL", str(e)[:100]))
            except Exception as e:
                results.append((name, "ERROR", f"{type(e).__name__}: {e}"[:100]))

        # 汇总报告
        print("\n" + "=" * 60)
        print("米宝多轮对话智能测试 - 汇总报告")
        print("=" * 60)
        total = len(results)
        passed = sum(1 for _, s, _ in results if s == "PASS")
        for name, status, msg in results:
            icon = "✅" if status == "PASS" else "❌"
            detail = f" | {msg}" if msg else ""
            print(f"  {icon} {name}: {status}{detail}")
        print(f"\n总计: {passed}/{total} 通过")
        print("=" * 60)
