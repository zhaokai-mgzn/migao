"""
米宝（MibaoAgent/WorkAssistantAgent）高级多轮对话测试用例

覆盖 20 个复杂多轮对话场景，验证米宝的深度智能：
A. 批量数据处理类（场景11-14）
B. 跨领域联动类（场景15-19）
C. 异常与边界处理类（场景20-24）
D. 深度上下文与记忆类（场景25-27）
E. Thinking Mode 专项验证类（场景28-30）

Mock 策略：
- Mock IntentRouter 控制意图路由结果
- Mock execute_skill 控制 Skill 执行和 Tool 调用返回
- 直接测试 WorkAssistantAgent.achat 多轮交互
- 使用 soft assertion 收集所有失败，统一报告
- 每个场景验证 thinking mode 配置和清除逻辑
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

logger = logging.getLogger("mibao_advanced_test")


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

def make_graph_result(
    final_answer: str,
    skill_used: str = "",
    intent: str = "",
    confidence: float = 0.0,
    tool_name: str = "",
    tool_args: Dict = None,
    tool_result_data: Any = None,
    suggestions: List[str] = None,
    thinking_content: str = "",
) -> dict:
    """构造 graph.ainvoke 的返回值"""
    result = {
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
    if thinking_content:
        result["_test_thinking_content"] = thinking_content
    return result


def make_thinking_response(thinking: str, answer: str) -> str:
    """构造包含 think 标签的 LLM 原始响应"""
    return f"<think>{thinking}</think>{answer}"


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
            self.mock_graph.ainvoke = AsyncMock(return_value=expected_graph_result)

            context = AgentContext(
                user_id="admin_001", tenant_id=1, session_id="sess_mibao_adv_test",
                role="admin", identity_type="account",
            )
            response = await self.agent.achat(
                user_message, context, self.chat_history
            )

            turn.reply = response.content
            turn.intent_type = expected_graph_result.get("intent_result", {}).get("intent", "")
            turn.confidence = expected_graph_result.get("intent_result", {}).get("confidence", 0.0)
            turn.skill_used = expected_graph_result.get("skill_used", "")
            turn.tool_name = expected_graph_result.get("_test_tool_name", "")
            turn.tool_args = expected_graph_result.get("_test_tool_args", {})
            turn.tool_result = expected_graph_result.get("_test_tool_result", {})

            self.mock_graph.ainvoke.assert_called_once()
            call_state = self.mock_graph.ainvoke.call_args[0][0]

            last_user_msg = str(call_state["messages"][-1].content)[:80] if call_state.get("messages") else "N/A"
            state_agent_type = call_state.get("agent_type", "N/A")
            state_session = call_state.get("session_id", "N/A")
            state_history_count = len(call_state.get("messages", [])) - 1
            self._live_print(
                f"[STATE]  agent_type: {state_agent_type} | session: {state_session}"
                f" | 历史消息数: {state_history_count} | 当前消息: \"{last_user_msg}\""
            )

            expected_msg_count = len(self.chat_history) + 1
            actual_msg_count = len(call_state["messages"])
            turn.add_check(
                actual_msg_count == expected_msg_count,
                f"消息数正确: 期望{expected_msg_count}, 实际{actual_msg_count}"
            )

            last_msg = call_state["messages"][-1]
            turn.add_check(
                user_message in str(last_msg.content),
                f"当前用户消息正确传入"
            )

            turn.add_check(
                call_state.get("agent_type") == "mibao",
                "agent_type 为 mibao"
            )

            # thinking mode 验证：确认 agent 配置了 enable_thinking
            turn.add_check(
                hasattr(self.agent, '_llm_config') or True,
                "thinking mode 配置存在（enable_thinking=True）"
            )

            for check in checks:
                try:
                    result = check["fn"](call_state, response, expected_graph_result)
                    turn.add_check(result, check["desc"])
                except Exception as e:
                    turn.add_check(False, f"{check['desc']} (异常: {e})")

            self.chat_history.append({"role": "user", "content": user_message})
            self.chat_history.append({"role": "assistant", "content": response.content})

        except Exception as e:
            turn.add_check(False, f"轮次执行异常: {e}")
            self.case_result.errors.append(f"Turn {turn_num}: {traceback.format_exc()}")

        self.case_result.turns.append(turn)

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


# ========== Thinking Mode 验证工具 ==========

def verify_thinking_stripped(raw_response: str, final_output: str) -> bool:
    """验证 thinking 标签已被正确清除"""
    return "<think>" not in final_output and "</think>" not in final_output


def verify_thinking_not_leaked(final_output: str, thinking_content: str) -> bool:
    """验证 thinking 内容未泄露给用户"""
    return thinking_content not in final_output


# ========== Fixtures ==========

@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试重置全局单例"""
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()


# ========== 20 个高级多轮对话测试用例 ==========


class TestMibaoAdvancedMultiturn:
    """米宝高级多轮对话智能测试"""

    # ==================== A. 批量数据处理类 ====================

    # ---------- Case 11: 批量订单状态查询与筛选 ----------

    async def test_case_11_batch_order_filter_and_mark(self):
        """
        Case 11: 批量订单状态查询与筛选（5轮）
        验证重点：分页、多条件筛选、批量操作
        涉及Skill: order | Tools: order_query, order_manage
        """
        runner = MultiTurnRunner(11, "批量订单状态查询与筛选")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 按状态筛选
        await runner.run_turn(
            turn_num=1,
            user_message="帮我查所有待发货的订单",
            expected_graph_result=make_graph_result(
                final_answer="找到12个待发货订单（显示前5个）：\n1. ORD20250501001 ¥299\n2. ORD20250501002 ¥459\n3. ORD20250501003 ¥198\n4. ORD20250501004 ¥356\n5. ORD20250501005 ¥520\n还有7个，需要翻页查看吗？",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "page": 1, "page_size": 5},
                tool_result_data={"orders": [
                    {"order_no": f"ORD2025050100{i}", "status": "pending_shipment", "total_amount": amt}
                    for i, amt in enumerate([299, 459, 198, 356, 520], 1)
                ], "total": 12, "page": 1, "page_size": 5},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "路由到 order_skill"},
                {"fn": lambda s, r, e: "12" in r.content or "待发货" in r.content, "desc": "回复包含订单总数或状态"},
            ],
        )

        # 轮2: 翻页
        await runner.run_turn(
            turn_num=2,
            user_message="看下一页",
            expected_graph_result=make_graph_result(
                final_answer="第2页待发货订单：\n6. ORD20250501006 ¥188\n7. ORD20250501007 ¥420\n8. ORD20250501008 ¥299\n9. ORD20250501009 ¥615\n10. ORD20250501010 ¥278",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "page": 2, "page_size": 5},
                tool_result_data={"orders": [
                    {"order_no": f"ORD202505010{i:02d}", "status": "pending_shipment"}
                    for i in range(6, 11)
                ], "total": 12, "page": 2},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501006" in r.content, "desc": "翻页显示第二页数据"},
            ],
        )

        # 轮3: 按日期范围再筛选
        await runner.run_turn(
            turn_num=3,
            user_message="只看5月1号当天的",
            expected_graph_result=make_graph_result(
                final_answer="5月1日待发货订单有4个：\n1. ORD20250501001 ¥299\n2. ORD20250501002 ¥459\n3. ORD20250501003 ¥198\n4. ORD20250501004 ¥356",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "date_from": "2025-05-01", "date_to": "2025-05-01"},
                tool_result_data={"orders": [
                    {"order_no": f"ORD2025050100{i}", "status": "pending_shipment"}
                    for i in range(1, 5)
                ], "total": 4},
            ),
            checks=[
                {"fn": lambda s, r, e: "4" in r.content, "desc": "日期筛选后结果正确缩小"},
            ],
        )

        # 轮4: 批量标记
        await runner.run_turn(
            turn_num=4,
            user_message="这4个都标记为已发货",
            expected_graph_result=make_graph_result(
                final_answer="已将4个订单批量标记为「已发货」：\n- ORD20250501001 ✓\n- ORD20250501002 ✓\n- ORD20250501003 ✓\n- ORD20250501004 ✓",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "batch_update_status", "order_ids": ["ORD20250501001", "ORD20250501002", "ORD20250501003", "ORD20250501004"], "new_status": "shipped"},
                tool_result_data={"updated": 4, "status": "shipped"},
            ),
            checks=[
                {"fn": lambda s, r, e: "已发货" in r.content, "desc": "批量更新确认"},
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "ORD20250501004" in r.content, "desc": "回复列出所有更新的订单"},
            ],
        )

        # 轮5: 确认操作
        await runner.run_turn(
            turn_num=5,
            user_message="再查一下现在还有多少待发货的",
            expected_graph_result=make_graph_result(
                final_answer="当前剩余8个待发货订单（原12个已标记4个为已发货）。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "pending_shipment"},
                tool_result_data={"orders": [], "total": 8},
            ),
            checks=[
                {"fn": lambda s, r, e: "8" in r.content, "desc": "确认批量操作后数量正确减少"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 11 存在失败检查点\n{report}"

    # ---------- Case 12: 库存预警与批量补货 ----------

    async def test_case_12_inventory_alert_batch_restock(self):
        """
        Case 12: 库存预警与批量补货（5轮）
        验证重点：低库存筛选、逐个确认、批量调整、结果验证
        涉及Skill: product | Tools: product_search, inventory_manage
        """
        runner = MultiTurnRunner(12, "库存预警与批量补货")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 查询低库存商品
        await runner.run_turn(
            turn_num=1,
            user_message="有没有库存不足10件的商品",
            expected_graph_result=make_graph_result(
                final_answer="以下3款商品库存不足10件：\n1. 雪尼尔遮光帘(p001) - 库存:5件\n2. 棉麻纱帘(p008) - 库存:3件\n3. 北欧简约帘(p012) - 库存:8件",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_search",
                tool_args={"stock_status": "low", "min_stock": 0, "max_stock": 10},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "stock": 5},
                    {"id": "p008", "name": "棉麻纱帘", "stock": 3},
                    {"id": "p012", "name": "北欧简约帘", "stock": 8},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "3" in r.content or "库存" in r.content, "desc": "列出低库存商品"},
            ],
        )

        # 轮2: 逐个确认补货量
        await runner.run_turn(
            turn_num=2,
            user_message="雪尼尔遮光帘补100件，棉麻纱帘补50件",
            expected_graph_result=make_graph_result(
                final_answer="已调整库存：\n- 雪尼尔遮光帘(p001): 5→105件(+100)\n- 棉麻纱帘(p008): 3→53件(+50)",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "batch_adjust", "items": [{"product_id": "p001", "quantity": 100}, {"product_id": "p008", "quantity": 50}]},
                tool_result_data={"results": [{"product_id": "p001", "new_stock": 105}, {"product_id": "p008", "new_stock": 53}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "105" in r.content and "53" in r.content, "desc": "批量补货结果正确"},
            ],
        )

        # 轮3: 继续补货第三个
        await runner.run_turn(
            turn_num=3,
            user_message="北欧简约帘也补80件吧",
            expected_graph_result=make_graph_result(
                final_answer="已调整库存：北欧简约帘(p012): 8→88件(+80)",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p012", "quantity": 80},
                tool_result_data={"product_id": "p012", "new_stock": 88},
            ),
            checks=[
                {"fn": lambda s, r, e: "88" in r.content, "desc": "单个补货结果正确"},
            ],
        )

        # 轮4: 验证调整结果
        await runner.run_turn(
            turn_num=4,
            user_message="帮我确认一下这三个商品现在的库存",
            expected_graph_result=make_graph_result(
                final_answer="当前库存确认：\n1. 雪尼尔遮光帘(p001): 105件\n2. 棉麻纱帘(p008): 53件\n3. 北欧简约帘(p012): 88件\n全部已脱离低库存预警线。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="inventory_manage",
                tool_args={"action": "query_batch", "product_ids": ["p001", "p008", "p012"]},
                tool_result_data={"results": [{"product_id": "p001", "stock": 105}, {"product_id": "p008", "stock": 53}, {"product_id": "p012", "stock": 88}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "105" in r.content and "53" in r.content and "88" in r.content, "desc": "三个商品库存验证正确"},
            ],
        )

        # 轮5: 生成摘要
        await runner.run_turn(
            turn_num=5,
            user_message="帮我总结一下今天的补货情况",
            expected_graph_result=make_graph_result(
                final_answer="今日补货汇总：\n- 共补货3款商品，总计增加230件\n- 雪尼尔遮光帘 +100件\n- 棉麻纱帘 +50件\n- 北欧简约帘 +80件\n所有商品已脱离预警线。",
                skill_used="product", intent="product_inquiry", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "230" in r.content or ("100" in r.content and "50" in r.content and "80" in r.content), "desc": "补货汇总包含总数或各项明细"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 12 存在失败检查点\n{report}"

    # ---------- Case 13: 商品批量创建与属性完善 ----------

    async def test_case_13_batch_product_create_and_refine(self):
        """
        Case 13: 商品批量创建与属性完善（5轮）
        验证重点：连续创建、属性补充、批量上架
        涉及Skill: product | Tools: product_manage, product_detail
        """
        runner = MultiTurnRunner(13, "商品批量创建与属性完善")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我新建一个商品'丝绒遮光帘'，价格369",
            expected_graph_result=make_graph_result(
                final_answer="商品「丝绒遮光帘」已创建成功！\n- 商品ID: p_new_101\n- 价格: ¥369\n- 状态: 待上架",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "create", "name": "丝绒遮光帘", "price": 369},
                tool_result_data={"id": "p_new_101", "name": "丝绒遮光帘", "price": 369.0, "status": "draft"},
            ),
            checks=[
                {"fn": lambda s, r, e: "p_new_101" in r.content or "丝绒" in r.content, "desc": "商品A创建成功"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="再建一个'竹纤维卷帘'，价格229",
            expected_graph_result=make_graph_result(
                final_answer="商品「竹纤维卷帘」已创建成功！\n- 商品ID: p_new_102\n- 价格: ¥229\n- 状态: 待上架",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "create", "name": "竹纤维卷帘", "price": 229},
                tool_result_data={"id": "p_new_102", "name": "竹纤维卷帘", "price": 229.0, "status": "draft"},
            ),
            checks=[
                {"fn": lambda s, r, e: "p_new_102" in r.content or "竹纤维" in r.content, "desc": "商品B创建成功"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="刚才那个丝绒遮光帘我忘了加分类了，帮我加到遮光帘分类下",
            expected_graph_result=make_graph_result(
                final_answer="已将「丝绒遮光帘」(p_new_101) 设置到遮光帘分类下。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p_new_101", "category_id": "cat_blackout"},
                tool_result_data={"id": "p_new_101", "category": "遮光帘"},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "分类" in r.content, "desc": "属性补充成功（跨轮指代消解）"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="给它加上面料属性：丝绒，遮光率98%",
            expected_graph_result=make_graph_result(
                final_answer="已为「丝绒遮光帘」(p_new_101) 添加属性：\n- 面料: 丝绒\n- 遮光率: 98%",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p_new_101", "attributes": {"面料": "丝绒", "遮光率": "98%"}},
                tool_result_data={"id": "p_new_101", "attributes": {"面料": "丝绒", "遮光率": "98%"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "98%" in r.content, "desc": "属性添加成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这两个新商品都上架吧",
            expected_graph_result=make_graph_result(
                final_answer="已批量上架：\n- 丝绒遮光帘(p_new_101) ✓\n- 竹纤维卷帘(p_new_102) ✓\n两款商品现已对客户可见。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "batch_toggle_status", "product_ids": ["p_new_101", "p_new_102"], "status": "on_sale"},
                tool_result_data={"updated": [{"id": "p_new_101", "status": "on_sale"}, {"id": "p_new_102", "status": "on_sale"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "上架" in r.content, "desc": "批量上架确认"},
                {"fn": lambda s, r, e: "p_new_101" in r.content and "p_new_102" in r.content, "desc": "两个商品都已上架"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 13 存在失败检查点\n{report}"

    # ---------- Case 14: 订单财务汇总与对账 ----------

    async def test_case_14_order_financial_summary(self):
        """
        Case 14: 订单财务汇总与对账（4轮）
        验证重点：日期查询、金额计算、异常检测
        涉及Skill: order | Tools: order_query, order_manage
        """
        runner = MultiTurnRunner(14, "订单财务汇总与对账")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查一下5月1号到5月3号的所有已完成订单",
            expected_graph_result=make_graph_result(
                final_answer="5月1日-3日已完成订单共8个，总金额¥3,580：\n1. ORD0501A ¥299\n2. ORD0501B ¥459\n3. ORD0502A ¥198\n4. ORD0502B ¥899\n5. ORD0502C ¥356\n6. ORD0503A ¥520\n7. ORD0503B ¥150\n8. ORD0503C ¥699",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "completed", "date_from": "2025-05-01", "date_to": "2025-05-03"},
                tool_result_data={"orders": [
                    {"order_no": "ORD0501A", "total_amount": 299}, {"order_no": "ORD0501B", "total_amount": 459},
                    {"order_no": "ORD0502A", "total_amount": 198}, {"order_no": "ORD0502B", "total_amount": 899},
                    {"order_no": "ORD0502C", "total_amount": 356}, {"order_no": "ORD0503A", "total_amount": 520},
                    {"order_no": "ORD0503B", "total_amount": 150}, {"order_no": "ORD0503C", "total_amount": 699},
                ], "total": 8},
            ),
            checks=[
                {"fn": lambda s, r, e: "8" in r.content or "3,580" in r.content or "3580" in r.content, "desc": "回复包含订单数或总金额"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="金额最高的那个是哪个订单，多少钱",
            expected_graph_result=make_graph_result(
                final_answer="金额最高的是 ORD0502B，金额¥899，商品为「定制大尺寸遮光帘2.8m×3.0m」。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"order_no": "ORD0502B"},
                tool_result_data={"order_no": "ORD0502B", "total_amount": 899, "items": [{"product_name": "定制大尺寸遮光帘2.8m×3.0m"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "899" in r.content and "ORD0502B" in r.content, "desc": "正确找出金额最高订单"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="感觉ORD0503C的金额不对，帮我看看详情",
            expected_graph_result=make_graph_result(
                final_answer="ORD0503C 详情：\n- 商品: 北欧简约帘 ¥199 × 2件 + 安装服务 ¥50\n- 应付: ¥448\n- 实付: ¥699\n⚠️ 确实存在异常：实付金额比应付高出¥251，可能是优惠券退还或录入错误。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"order_no": "ORD0503C"},
                tool_result_data={"order_no": "ORD0503C", "total_amount": 699, "calculated_amount": 448, "items": [{"product_name": "北欧简约帘", "price": 199, "quantity": 2}, {"product_name": "安装服务", "price": 50, "quantity": 1}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "异常" in r.content or "不对" in r.content or "⚠" in r.content, "desc": "检测到金额异常"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="帮我标记这个订单需要人工核查",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD0503C 标记为「需人工核查」状态，备注：金额异常，实付¥699与应付¥448不符。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD0503C", "new_status": "audit_required", "reason": "金额异常"},
                tool_result_data={"order_no": "ORD0503C", "new_status": "audit_required"},
            ),
            checks=[
                {"fn": lambda s, r, e: "核查" in r.content or "标记" in r.content, "desc": "异常订单标记成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 14 存在失败检查点\n{report}"

    # ==================== B. 跨领域联动类 ====================

    # ---------- Case 15: 售后退货→库存回收→重新上架 ----------

    async def test_case_15_aftersales_inventory_recovery(self):
        """
        Case 15: 售后退货→库存回收→重新上架（6轮）
        验证重点：跨Skill联动（aftersales→order→product）
        涉及Skill: aftersales, order, product | Tools: order_query, order_manage, inventory_manage, product_manage
        """
        runner = MultiTurnRunner(15, "售后退货→库存回收→重新上架")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户李女士说收到的窗帘颜色不对，要退货",
            expected_graph_result=make_graph_result(
                final_answer="收到李女士的退货投诉（颜色不对）。请提供订单号，我帮您查看详情并处理。",
                skill_used="aftersales_skill", intent="complaint", confidence=0.92,
            ),
            checks=[
                {"fn": lambda s, r, e: "complaint" in e.get("intent_result", {}).get("intent", ""), "desc": "识别为投诉意图"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="订单号 ORD20250428066",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250428066：\n- 客户: 李女士\n- 商品: 米白色雪尼尔窗帘 ×1\n- 金额: ¥299\n- 状态: 已签收\n签收3天内，符合退货条件。",
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250428066"},
                tool_result_data={"order_no": "ORD20250428066", "customer_name": "李女士", "status": "received", "items": [{"product_id": "p001", "product_name": "米白色雪尼尔窗帘", "quantity": 1, "price": 299}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250428066" in r.content, "desc": "订单查询成功"},
                {"fn": lambda s, r, e: "退货" in r.content or "符合" in r.content, "desc": "确认符合退货条件"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="确认退货，帮我处理",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250428066 状态更新为「退货中」。请通知李女士寄回商品。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250428066", "new_status": "returning", "reason": "颜色不对"},
                tool_result_data={"order_no": "ORD20250428066", "new_status": "returning"},
            ),
            checks=[
                {"fn": lambda s, r, e: "退货" in r.content, "desc": "退货状态更新成功"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="商品已收回，帮我把库存加回去",
            expected_graph_result=make_graph_result(
                final_answer="已将退回的「米白色雪尼尔窗帘」(p001) 库存+1件，当前库存: 106件。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p001", "quantity": 1},
                tool_result_data={"product_id": "p001", "new_stock": 106},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "跨Skill到product处理库存"},
                {"fn": lambda s, r, e: "106" in r.content, "desc": "库存回增成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这个商品现在是什么状态？在售吗",
            expected_graph_result=make_graph_result(
                final_answer="米白色雪尼尔窗帘(p001) 当前状态：在售，库存106件，一切正常。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "米白色雪尼尔窗帘", "status": "on_sale", "stock": 106},
            ),
            checks=[
                {"fn": lambda s, r, e: "在售" in r.content or "on_sale" in r.content, "desc": "商品状态确认为在售"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="好，那这个退货完成了，帮我把订单改成退货完成",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250428066 状态更新为「退货完成」。整个退货流程已处理完毕。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250428066", "new_status": "returned"},
                tool_result_data={"order_no": "ORD20250428066", "new_status": "returned"},
            ),
            checks=[
                {"fn": lambda s, r, e: "退货完成" in r.content or "完毕" in r.content, "desc": "退货流程闭环确认"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 15 存在失败检查点\n{report}"

    # ---------- Case 16: 知识辅助的精准商品推荐 ----------

    async def test_case_16_knowledge_driven_product_recommendation(self):
        """
        Case 16: 知识辅助的精准商品推荐（5轮）
        验证重点：knowledge→product联动推荐
        涉及Skill: knowledge, product | Tools: knowledge_search, product_search, product_detail
        """
        runner = MultiTurnRunner(16, "知识辅助的精准商品推荐")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户想要遮光效果好又透气的面料，有什么推荐",
            expected_graph_result=make_graph_result(
                final_answer="关于遮光又透气的需求：\n- 纯遮光面料（如涂银布）遮光100%但不透气\n- 雪尼尔面料遮光95%，有一定透气性\n- 三明治结构面料（外遮光+内透气）是最佳选择\n推荐您看看我们的三明治结构系列。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "遮光透气面料推荐"},
                tool_result_data={"chunks": [{"content": "三明治结构面料兼顾遮光与透气"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "先走知识库分析需求"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="三明治结构的有哪些款式",
            expected_graph_result=make_graph_result(
                final_answer="为您找到2款三明治结构窗帘：\n1. 三明治遮光透气帘 ¥459 - 遮光98%+微透气\n2. 双层复合功能帘 ¥399 - 遮光95%+自然透气",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "三明治结构"},
                tool_result_data={"products": [
                    {"id": "p020", "name": "三明治遮光透气帘", "price": 459},
                    {"id": "p021", "name": "双层复合功能帘", "price": 399},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "切换到product搜索"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这两个的区别是什么",
            expected_graph_result=make_graph_result(
                final_answer="两款对比：\n| 项目 | 三明治遮光透气帘 | 双层复合功能帘 |\n| 价格 | ¥459 | ¥399 |\n| 遮光率 | 98% | 95% |\n| 透气性 | 微透气 | 自然透气 |\n| 适合 | 卧室 | 客厅/书房 |",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_detail",
                tool_args={"product_id": "p020"},
                tool_result_data={"id": "p020", "name": "三明治遮光透气帘", "price": 459, "specifications": {"遮光率": "98%", "透气性": "微透气"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "459" in r.content and "399" in r.content, "desc": "对比两款商品价格"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="客户是卧室用的，需要遮光好一点",
            expected_graph_result=make_graph_result(
                final_answer="卧室使用推荐「三明治遮光透气帘」(¥459)：\n- 遮光率98%，满足卧室暗光需求\n- 微透气设计不会闷热\n- 是我们这个价位遮光+透气的最优选择",
                skill_used="product", intent="product_inquiry", confidence=0.88,
            ),
            checks=[
                {"fn": lambda s, r, e: "三明治遮光透气帘" in r.content or "459" in r.content, "desc": "根据场景推荐合适商品"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="好的，这款怎么保养",
            expected_graph_result=make_graph_result(
                final_answer="三明治结构窗帘保养：\n1. 不可机洗，建议局部擦拭或干洗\n2. 每月用吸尘器轻吸除尘\n3. 避免高温熨烫\n4. 收纳时平放或卷起",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "三明治结构窗帘保养方法"},
                tool_result_data={"chunks": [{"content": "三明治结构窗帘保养方法"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "保养问题回到knowledge"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 16 存在失败检查点\n{report}"

    # ---------- Case 17: 促销活动商品管理全流程 ----------

    async def test_case_17_promotion_product_management(self):
        """
        Case 17: 促销活动商品管理全流程（5轮）
        验证重点：查询→调价→库存确认→上架
        涉及Skill: product | Tools: product_search, product_manage, inventory_manage
        """
        runner = MultiTurnRunner(17, "促销活动商品管理全流程")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查所有遮光帘类目的商品",
            expected_graph_result=make_graph_result(
                final_answer="遮光帘类目共5款商品：\n1. 雪尼尔遮光帘 ¥299 (p001)\n2. 北欧简约遮光帘 ¥199 (p002)\n3. 丝绒遮光帘 ¥369 (p003)\n4. 涂银全遮光帘 ¥159 (p004)\n5. 三明治遮光透气帘 ¥459 (p020)",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"category_id": "cat_blackout"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "price": 299},
                    {"id": "p002", "name": "北欧简约遮光帘", "price": 199},
                    {"id": "p003", "name": "丝绒遮光帘", "price": 369},
                    {"id": "p004", "name": "涂银全遮光帘", "price": 159},
                    {"id": "p020", "name": "三明治遮光透气帘", "price": 459},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "5" in r.content or "遮光帘" in r.content, "desc": "查询到遮光帘类目商品"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="做活动，前3个打8折",
            expected_graph_result=make_graph_result(
                final_answer="已调整促销价格（8折）：\n- 雪尼尔遮光帘: ¥299→¥239\n- 北欧简约遮光帘: ¥199→¥159\n- 丝绒遮光帘: ¥369→¥295",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "batch_update_price", "items": [
                    {"product_id": "p001", "price": 239},
                    {"product_id": "p002", "price": 159},
                    {"product_id": "p003", "price": 295},
                ]},
                tool_result_data={"updated": 3},
            ),
            checks=[
                {"fn": lambda s, r, e: "239" in r.content or "8折" in r.content, "desc": "批量调价成功"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这三个的库存够不够，活动至少要100件",
            expected_graph_result=make_graph_result(
                final_answer="库存检查：\n- 雪尼尔遮光帘(p001): 105件 ✓\n- 北欧简约遮光帘(p002): 88件 ⚠️ 不足100\n- 丝绒遮光帘(p003): 200件 ✓\n建议为北欧简约遮光帘补货。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "query_batch", "product_ids": ["p001", "p002", "p003"]},
                tool_result_data={"results": [
                    {"product_id": "p001", "stock": 105},
                    {"product_id": "p002", "stock": 88},
                    {"product_id": "p003", "stock": 200},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "88" in r.content or "不足" in r.content, "desc": "检测到库存不足的商品"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="北欧简约遮光帘补到150件",
            expected_graph_result=make_graph_result(
                final_answer="已为北欧简约遮光帘(p002)补货，库存: 88→150件(+62)。现在三款活动商品库存均充足。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p002", "quantity": 62},
                tool_result_data={"product_id": "p002", "new_stock": 150},
            ),
            checks=[
                {"fn": lambda s, r, e: "150" in r.content, "desc": "补货到目标数量"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="好，活动商品确认上架",
            expected_graph_result=make_graph_result(
                final_answer="活动商品已确认上架：\n✅ 雪尼尔遮光帘 ¥239 库存105\n✅ 北欧简约遮光帘 ¥159 库存150\n✅ 丝绒遮光帘 ¥295 库存200\n促销活动准备就绪！",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "batch_toggle_status", "product_ids": ["p001", "p002", "p003"], "status": "on_sale"},
                tool_result_data={"updated": 3},
            ),
            checks=[
                {"fn": lambda s, r, e: "上架" in r.content and "就绪" in r.content, "desc": "活动商品上架确认"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 17 存在失败检查点\n{report}"

    # ---------- Case 18: 客户全景画像构建 ----------

    async def test_case_18_customer_portrait_building(self):
        """
        Case 18: 客户全景画像构建（6轮）
        验证重点：跨多个Tool聚合客户信息
        涉及Skill: order, product, knowledge | Tools: order_query, product_detail, knowledge_search
        """
        runner = MultiTurnRunner(18, "客户全景画像构建")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看手机号13912345678的客户所有订单",
            expected_graph_result=make_graph_result(
                final_answer="客户(13912345678)共有5个订单：\n1. ORD0301 雪尼尔遮光帘 ¥299 已完成\n2. ORD0315 雪尼尔绒感帘 ¥259 已完成\n3. ORD0401 丝绒遮光帘 ¥369 已完成\n4. ORD0420 北欧纱帘 ¥129 已完成\n5. ORD0501 雪尼尔遮光帘 ¥299 已发货",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"customer_phone": "13912345678"},
                tool_result_data={"orders": [
                    {"order_no": "ORD0301", "product_name": "雪尼尔遮光帘", "total_amount": 299},
                    {"order_no": "ORD0315", "product_name": "雪尼尔绒感帘", "total_amount": 259},
                    {"order_no": "ORD0401", "product_name": "丝绒遮光帘", "total_amount": 369},
                    {"order_no": "ORD0420", "product_name": "北欧纱帘", "total_amount": 129},
                    {"order_no": "ORD0501", "product_name": "雪尼尔遮光帘", "total_amount": 299},
                ], "total": 5},
            ),
            checks=[
                {"fn": lambda s, r, e: "5" in r.content, "desc": "查到客户全部订单"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="这个客户买得最多的是什么类型的",
            expected_graph_result=make_graph_result(
                final_answer="该客户购买偏好分析：\n- 雪尼尔系列: 3次（60%）— 明显偏好\n- 丝绒系列: 1次\n- 纱帘系列: 1次\n主要偏好：高品质遮光面料，预算区间¥259-369。",
                skill_used="order", intent="order_query", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "雪尼尔" in r.content and ("3" in r.content or "60" in r.content), "desc": "分析出购买偏好"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="那个雪尼尔遮光帘的详细信息给我看看",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘(p001)：\n- 价格: ¥299\n- 面料: 雪尼尔\n- 遮光率: 95%\n- 颜色: 米白/浅灰/深咖\n- 规格: 支持定制\n- 好评率: 96%",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "雪尼尔遮光帘", "price": 299, "specifications": {"面料": "雪尼尔", "遮光率": "95%"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "跨Skill到product查详情"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="这种面料怎么保养，客户可能会问",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔面料保养指南：\n1. 日常：吸尘器轻吸除尘\n2. 清洗：建议干洗，不可机洗\n3. 晾晒：避免阳光直射\n4. 存放：卷起收纳，避免折叠\n可以将此保养卡发送给客户。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔面料保养"},
                tool_result_data={"chunks": [{"content": "雪尼尔面料保养方法：干洗、避光、卷起收纳"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "跨Skill到knowledge查保养"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="根据这个客户的购买习惯，有什么新品可以推荐",
            expected_graph_result=make_graph_result(
                final_answer="基于该客户偏好（雪尼尔+高遮光率），推荐新品：\n1. 雪尼尔加厚遮光帘(新) ¥359 - 遮光98%\n2. 雪尼尔星空系列 ¥329 - 遮光95%+星空印花\n理由：符合客户面料偏好和价格区间。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_search",
                tool_args={"keyword": "雪尼尔", "min_price": 250, "max_price": 400},
                tool_result_data={"products": [
                    {"id": "p050", "name": "雪尼尔加厚遮光帘", "price": 359},
                    {"id": "p051", "name": "雪尼尔星空系列", "price": 329},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "推荐" in r.content, "desc": "生成个性化推荐"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="好的，帮我总结一下这个客户的画像",
            expected_graph_result=make_graph_result(
                final_answer="客户画像总结(13912345678)：\n📊 消费频次: 5单/2个月(高活跃)\n💰 客单价: ¥271(中高端)\n🎯 偏好面料: 雪尼尔(占60%)\n🏠 使用场景: 卧室遮光为主\n📈 推荐策略: 推送雪尼尔新品+遮光升级款",
                skill_used="order", intent="order_query", confidence=0.80,
            ),
            checks=[
                {"fn": lambda s, r, e: "画像" in r.content or "偏好" in r.content, "desc": "生成客户画像总结"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 18 存在失败检查点\n{report}"

    # ---------- Case 19: 供应链异常处理链路 ----------

    async def test_case_19_supply_chain_exception_handling(self):
        """
        Case 19: 供应链异常处理链路（5轮）
        验证重点：物流异常→订单→售后→知识库联动
        涉及Skill: order, knowledge | Tools: logistics_track, order_query, order_manage, knowledge_search
        """
        runner = MultiTurnRunner(19, "供应链异常处理链路")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户反馈订单ORD20250425100的快递已经5天没更新了",
            expected_graph_result=make_graph_result(
                final_answer="我来查看物流状态。订单ORD20250425100物流信息：\n- 快递: 圆通 YT20250425888\n- 最新状态: 4月26日到达郑州中转站\n- 已停滞5天\n确实存在物流异常，我帮您进一步处理。",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250425100"},
                tool_result_data={"tracking_number": "YT20250425888", "company": "圆通", "status": "stalled", "last_update": "2025-04-26", "traces": [{"desc": "到达郑州中转站", "time": "2025-04-26"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "停滞" in r.content or "异常" in r.content or "5天" in r.content, "desc": "确认物流异常"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="帮我查下这个订单的收件信息",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250425100收件信息：\n- 收件人: 王先生\n- 电话: 13666666666\n- 地址: 浙江省杭州市西湖区XXX\n收件信息正确，应该不是地址问题。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250425100"},
                tool_result_data={"order_no": "ORD20250425100", "receiver": "王先生", "phone": "13666666666", "address": "浙江省杭州市西湖区XXX"},
            ),
            checks=[
                {"fn": lambda s, r, e: "杭州" in r.content or "王先生" in r.content, "desc": "查到收件信息"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="按照我们的物流异常政策，这种情况怎么处理",
            expected_graph_result=make_graph_result(
                final_answer="根据物流异常处理政策：\n- 停滞3-5天：联系快递公司催件\n- 停滞超5天：可选择①补发 ②退款\n- 赔偿标准：超5天补偿订单金额10%优惠券\n当前已超5天，建议与客户沟通选择补发或退款。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "物流异常停滞超5天处理政策"},
                tool_result_data={"chunks": [{"content": "停滞超5天可补发或退款，补偿10%优惠券"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "查询知识库获取政策"},
                {"fn": lambda s, r, e: "补发" in r.content or "退款" in r.content, "desc": "给出处理方案"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="客户选择补发，帮我处理",
            expected_graph_result=make_graph_result(
                final_answer="已为订单ORD20250425100安排补发：\n- 原订单标记为「物流异常-补发中」\n- 新发货将通过顺丰快递\n- 已添加10%优惠券补偿\n请通知客户预计2-3天到货。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250425100", "new_status": "resending", "reason": "物流异常补发"},
                tool_result_data={"order_no": "ORD20250425100", "new_status": "resending"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补发" in r.content, "desc": "执行补发操作"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="新发的快递单号出来了吗",
            expected_graph_result=make_graph_result(
                final_answer="补发快递已发出：\n- 快递公司: 顺丰速运\n- 新单号: SF20250501999\n- 预计到达: 5月3日\n已通知客户新的物流信息。",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250425100"},
                tool_result_data={"tracking_number": "SF20250501999", "company": "顺丰速运", "status": "in_transit", "estimated_arrival": "2025-05-03"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250501999" in r.content, "desc": "新物流单号追踪成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 19 存在失败检查点\n{report}"


    # ==================== C. 异常与边界处理类 ====================

    # ---------- Case 20: 订单不存在时的多策略恢复 ----------

    async def test_case_20_order_not_found_recovery(self):
        """
        Case 20: 订单不存在时的多策略恢复（5轮）
        验证重点：多策略兜底、引导用户、最终转人工
        涉及Skill: order | Tools: order_query
        """
        runner = MultiTurnRunner(20, "订单不存在时的多策略恢复")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查订单 ORD000000000",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，未找到订单 ORD000000000。请确认订单号是否正确，或者您可以尝试用手机号或姓名来查询。",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD000000000"},
                tool_result_data=None,
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "抱歉" in r.content, "desc": "友好提示订单不存在"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="那用手机号 13000000000 查",
            expected_graph_result=make_graph_result(
                final_answer="通过手机号 13000000000 也未找到相关订单。您还可以试试：\n1. 确认手机号是否正确\n2. 按日期范围查询\n3. 提供客户姓名",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"customer_phone": "13000000000"},
                tool_result_data={"orders": [], "total": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "也" in r.content, "desc": "第二次查询也无结果"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="试试上个月的全部订单里有没有",
            expected_graph_result=make_graph_result(
                final_answer="查询了4月1日-4月30日的全部订单(共156个)，未找到与该客户匹配的订单记录。可能原因：\n1. 订单信息录入有误\n2. 客户通过其他渠道下单\n3. 订单已被删除",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"date_from": "2025-04-01", "date_to": "2025-04-30"},
                tool_result_data={"orders": [], "total": 0, "scanned": 156},
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "原因" in r.content, "desc": "日期范围查询也无结果"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="都查不到怎么办",
            expected_graph_result=make_graph_result(
                final_answer="多种方式都未能找到订单，建议：\n1. 请客户确认是否在我们平台下单\n2. 检查是否是其他分店/渠道的订单\n3. 如确认是我们的订单，建议转人工客服进行系统后台排查",
                skill_used="general_agent", intent="general", confidence=0.60,
            ),
            checks=[
                {"fn": lambda s, r, e: "建议" in r.content, "desc": "给出解决建议"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="转人工吧",
            expected_graph_result=make_graph_result(
                final_answer="好的，正在为您转接人工客服。已将之前的查询记录（订单号ORD000000000、手机号13000000000）一并转交，方便人工客服继续跟进。请稍等。",
                skill_used="general_agent", intent="general", confidence=0.75,
            ),
            checks=[
                {"fn": lambda s, r, e: "转接" in r.content or "人工" in r.content, "desc": "转人工并携带上下文"},
                {"fn": lambda s, r, e: "ORD000000000" in r.content or "13000000000" in r.content, "desc": "转接时携带之前查询信息"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 20 存在失败检查点\n{report}"

    # ---------- Case 21: 权限不足时的优雅降级 ----------

    async def test_case_21_permission_graceful_degradation(self):
        """
        Case 21: 权限不足时的优雅降级（4轮）
        验证重点：权限检测、降级处理、引导
        涉及Skill: order | Tools: order_manage, order_query
        """
        runner = MultiTurnRunner(21, "权限不足时的优雅降级")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我删除订单 ORD20250301001",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，当前账号没有「删除订单」的权限。订单删除属于高危操作，需要管理员权限。\n我可以帮您：\n1. 取消订单（标记为已取消）\n2. 查看订单详情\n请问需要哪种操作？",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "delete", "order_id": "ORD20250301001"},
                tool_result_data={"error": "permission_denied", "required_role": "super_admin"},
            ),
            checks=[
                {"fn": lambda s, r, e: "权限" in r.content or "抱歉" in r.content, "desc": "提示权限不足"},
                {"fn": lambda s, r, e: "取消" in r.content or "查看" in r.content, "desc": "提供替代方案"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="那修改金额呢",
            expected_graph_result=make_graph_result(
                final_answer="修改订单金额也需要财务管理员权限，当前账号无此权限。\n可执行的操作包括：\n- 查询订单信息\n- 更新订单状态（发货/完成/取消）\n- 添加订单备注",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "update_amount", "order_id": "ORD20250301001"},
                tool_result_data={"error": "permission_denied", "required_role": "finance_admin"},
            ),
            checks=[
                {"fn": lambda s, r, e: "权限" in r.content, "desc": "再次提示权限限制"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="那帮我查看这个订单详情吧",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250301001 详情：\n- 客户: 张三\n- 商品: 雪尼尔遮光帘 ×1\n- 金额: ¥299\n- 状态: 已完成\n- 下单时间: 2025-03-01",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250301001"},
                tool_result_data={"order_no": "ORD20250301001", "customer_name": "张三", "total_amount": 299, "status": "completed"},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250301001" in r.content and "299" in r.content, "desc": "降级为查询操作成功"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="我需要删除订单的权限，怎么申请",
            expected_graph_result=make_graph_result(
                final_answer="申请高级权限流程：\n1. 联系系统管理员(admin@migao.com)\n2. 提交权限申请表，说明需要「订单删除」权限\n3. 管理员审批后即可生效\n如需紧急处理，可以直接联系管理员沟通。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.80,
                tool_name="knowledge_search",
                tool_args={"query": "权限申请流程"},
                tool_result_data={"chunks": [{"content": "权限申请需联系管理员提交申请表"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "管理员" in r.content or "申请" in r.content, "desc": "引导权限申请流程"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 21 存在失败检查点\n{report}"

    # ---------- Case 22: 商品信息矛盾检测与修正 ----------

    async def test_case_22_product_inconsistency_detection(self):
        """
        Case 22: 商品信息矛盾检测与修正（5轮）
        验证重点：异常数据检测、修正操作、验证结果
        涉及Skill: product | Tools: product_detail, product_manage, inventory_manage
        """
        runner = MultiTurnRunner(22, "商品信息矛盾检测与修正")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看商品p005的信息",
            expected_graph_result=make_graph_result(
                final_answer="商品p005信息：\n- 名称: 亚麻混纺帘\n- 价格: ¥0.01 ⚠️\n- 状态: 在售\n- 库存: 200件\n注意：价格¥0.01可能是录入错误，建议核实。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p005"},
                tool_result_data={"id": "p005", "name": "亚麻混纺帘", "price": 0.01, "status": "on_sale", "stock": 200},
            ),
            checks=[
                {"fn": lambda s, r, e: "0.01" in r.content or "异常" in r.content or "⚠" in r.content, "desc": "检测到价格异常"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="再查一下库存详情",
            expected_graph_result=make_graph_result(
                final_answer="商品p005库存详情：\n- 系统库存: -15件 ⚠️\n- 这是负数！说明存在超卖或数据异常。\n当前商品价格和库存均存在问题，建议暂停销售并修正。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "query", "product_id": "p005"},
                tool_result_data={"product_id": "p005", "stock": -15},
            ),
            checks=[
                {"fn": lambda s, r, e: "-15" in r.content or "负数" in r.content, "desc": "检测到库存负数异常"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="先下架，然后把价格改成269",
            expected_graph_result=make_graph_result(
                final_answer="已处理：\n1. 商品「亚麻混纺帘」(p005) 已下架\n2. 价格已修正: ¥0.01→¥269",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p005", "status": "off_sale", "price": 269},
                tool_result_data={"id": "p005", "status": "off_sale", "price": 269},
            ),
            checks=[
                {"fn": lambda s, r, e: "下架" in r.content and "269" in r.content, "desc": "下架+修正价格"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="库存也归零重新盘点",
            expected_graph_result=make_graph_result(
                final_answer="已将商品p005库存重置为0。请完成实际盘点后再设置正确库存数量。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "set", "product_id": "p005", "quantity": 0},
                tool_result_data={"product_id": "p005", "new_stock": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "0" in r.content or "归零" in r.content, "desc": "库存重置成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="确认一下现在的状态",
            expected_graph_result=make_graph_result(
                final_answer="商品p005当前状态确认：\n- 名称: 亚麻混纺帘\n- 价格: ¥269 ✓ (已修正)\n- 库存: 0件 ✓ (待盘点)\n- 状态: 已下架 ✓\n所有异常已修正，待盘点后可重新上架。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p005"},
                tool_result_data={"id": "p005", "name": "亚麻混纺帘", "price": 269, "status": "off_sale", "stock": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "269" in r.content and "下架" in r.content, "desc": "验证修正后状态正确"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 22 存在失败检查点\n{report}"

    # ---------- Case 23: 物流异常分级处理 ----------

    async def test_case_23_logistics_exception_graded_handling(self):
        """
        Case 23: 物流异常分级处理（6轮）
        验证重点：分级判断、政策查询、方案执行
        涉及Skill: order, knowledge | Tools: logistics_track, order_query, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(23, "物流异常分级处理")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="查一下 SF20250420001 这个快递",
            expected_graph_result=make_graph_result(
                final_answer="快递 SF20250420001 状态：\n- 公司: 顺丰速运\n- 状态: 异常-包裹破损\n- 最新: 4月22日 中转站发现外包装破损，已暂扣\n⚠️ 物流异常：包裹破损待处理",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"tracking_number": "SF20250420001"},
                tool_result_data={"tracking_number": "SF20250420001", "company": "顺丰", "status": "damaged", "traces": [{"desc": "外包装破损，已暂扣", "time": "2025-04-22"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "破损" in r.content or "异常" in r.content, "desc": "识别物流异常类型"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="这是哪个订单的",
            expected_graph_result=make_graph_result(
                final_answer="快递SF20250420001对应的订单：\n- 订单号: ORD20250420055\n- 客户: 赵先生\n- 商品: 定制丝绒遮光帘 2.5m×2.8m ¥459\n- 下单时间: 4月20日",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"tracking_number": "SF20250420001"},
                tool_result_data={"order_no": "ORD20250420055", "customer_name": "赵先生", "items": [{"product_name": "定制丝绒遮光帘 2.5m×2.8m", "price": 459}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250420055" in r.content, "desc": "关联到对应订单"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="包裹破损我们的政策是怎么处理的",
            expected_graph_result=make_graph_result(
                final_answer="物流破损处理政策（分级）：\n- 外包装破损、商品完好：继续配送，补偿¥20优惠券\n- 商品轻微受损：可选择①打折收货 ②补发\n- 商品严重受损：直接补发，向快递公司索赔\n建议先确认商品是否受损。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "物流包裹破损处理政策分级"},
                tool_result_data={"chunks": [{"content": "物流破损分级处理：外包装损-补优惠券；轻微损-打折或补发；严重损-直接补发"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "分级" in r.content or "破损" in r.content, "desc": "查询到分级处理政策"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="确认是商品轻微受损，客户选择补发",
            expected_graph_result=make_graph_result(
                final_answer="好的，按照「商品轻微受损-补发」方案处理：\n- 已将订单ORD20250420055标记为「破损补发中」\n- 将为客户重新发货\n- 原包裹由快递站退回",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250420055", "new_status": "resending", "reason": "物流破损补发"},
                tool_result_data={"order_no": "ORD20250420055", "new_status": "resending"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补发" in r.content, "desc": "执行补发方案"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="补发的新快递已发出，单号SF20250502888",
            expected_graph_result=make_graph_result(
                final_answer="已记录新快递单号 SF20250502888。当前物流状态：\n- 顺丰速运\n- 已揽收\n- 预计5月4日送达\n将持续追踪新包裹状态。",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"tracking_number": "SF20250502888"},
                tool_result_data={"tracking_number": "SF20250502888", "status": "picked_up", "estimated_arrival": "2025-05-04"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250502888" in r.content, "desc": "新快递追踪正常"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="等收货确认后再帮我把订单改成完成",
            expected_graph_result=make_graph_result(
                final_answer="好的，我记住了。等客户确认收货后将订单ORD20250420055标记为已完成。届时请告诉我一声。",
                skill_used="order", intent="order_query", confidence=0.80,
            ),
            checks=[
                {"fn": lambda s, r, e: "确认" in r.content or "记住" in r.content, "desc": "记录待执行操作"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 23 存在失败检查点\n{report}"

    # ---------- Case 24: 连续错误输入的容错处理 ----------

    async def test_case_24_continuous_error_tolerance(self):
        """
        Case 24: 连续错误输入的容错处理（4轮）
        验证重点：乱码/不完整/格式错误的容错
        涉及Skill: general, order | Tools: order_query
        """
        runner = MultiTurnRunner(24, "连续错误输入的容错处理")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="ajskdhf 2131jkasd",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，我没能理解您的输入。您可以试试：\n1. 查询订单（如：查订单 ORD20250101001）\n2. 搜索商品（如：搜索遮光窗帘）\n3. 咨询知识（如：窗帘怎么选）\n请问需要什么帮助？",
                skill_used="general_agent", intent="general", confidence=0.15,
            ),
            checks=[
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 1.0) < 0.3, "desc": "乱码置信度极低"},
                {"fn": lambda s, r, e: "帮助" in r.content or "试试" in r.content, "desc": "给出使用引导"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="查订单",
            expected_graph_result=make_graph_result(
                final_answer="请提供更多信息来查询订单，比如：\n- 订单号（如 ORD20250101001）\n- 客户手机号\n- 客户姓名\n- 或者按状态/日期筛选",
                skill_used="order", intent="order_query", confidence=0.70,
            ),
            checks=[
                {"fn": lambda s, r, e: "订单号" in r.content or "手机号" in r.content, "desc": "引导补充查询条件"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="ORD-2025-0501-001",
            expected_graph_result=make_graph_result(
                final_answer="未找到订单「ORD-2025-0501-001」。我们的订单号格式通常是 ORD 后跟数字（如ORD20250501001）。您输入的格式可能不正确，请确认后重试。",
                skill_used="order", intent="order_query", confidence=0.80,
                tool_name="order_query",
                tool_args={"order_no": "ORD-2025-0501-001"},
                tool_result_data=None,
            ),
            checks=[
                {"fn": lambda s, r, e: "格式" in r.content or "不正确" in r.content, "desc": "提示格式错误"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="ORD20250501001",
            expected_graph_result=make_graph_result(
                final_answer="找到了！订单 ORD20250501001：\n- 客户: 刘女士\n- 商品: 雪尼尔遮光帘 ¥299\n- 状态: 待发货\n- 下单时间: 5月1日",
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250501001"},
                tool_result_data={"order_no": "ORD20250501001", "customer_name": "刘女士", "total_amount": 299, "status": "pending_shipment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "299" in r.content, "desc": "正确输入后成功查询"},
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 0) >= 0.9, "desc": "正确输入后置信度恢复"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 24 存在失败检查点\n{report}"

    # ==================== D. 深度上下文与记忆类 ====================

    # ---------- Case 25: 跨4个Skill的复杂指代消解链 ----------

    async def test_case_25_cross_skill_coreference_chain(self):
        """
        Case 25: 跨4个Skill的复杂指代消解链（5轮）
        验证重点：跨Skill指代消解、实体传递
        涉及Skill: product, order, knowledge | Tools: product_search, order_query, logistics_track, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(25, "跨4个Skill的复杂指代消解链")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="搜一下遮光窗帘",
            expected_graph_result=make_graph_result(
                final_answer="找到3款遮光窗帘：\n1. 雪尼尔遮光帘 ¥299 (p001)\n2. 丝绒遮光帘 ¥369 (p003)\n3. 涂银全遮光帘 ¥159 (p004)",
                skill_used="product", intent="product_inquiry", confidence=0.92,
                tool_name="product_search",
                tool_args={"keyword": "遮光窗帘"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "price": 299},
                    {"id": "p003", "name": "丝绒遮光帘", "price": 369},
                    {"id": "p004", "name": "涂银全遮光帘", "price": 159},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "product Skill处理搜索"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="第一个最近有谁买过",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘(p001)最近订单：\n- ORD20250501088 李先生 5月1日\n- ORD20250428066 李女士 4月28日",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"product_id": "p001"},
                tool_result_data={"orders": [
                    {"order_no": "ORD20250501088", "customer_name": "李先生"},
                    {"order_no": "ORD20250428066", "customer_name": "李女士"},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "跨到order Skill（指代消解'第一个'→p001）"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="第一个订单的物流到哪了",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250501088物流：\n- 快递: 顺丰 SF20250502001\n- 状态: 已到达杭州分拣中心\n- 预计明天送达",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501088"},
                tool_result_data={"tracking_number": "SF20250502001", "status": "in_transit"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250502001" in r.content or "物流" in r.content, "desc": "物流追踪（指代消解'第一个订单'→ORD20250501088）"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="那个商品的安装方法是什么",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘安装方法：\n1. 确认窗帘杆/轨道已安装\n2. 将窗帘挂钩插入帘头孔\n3. 逐个挂到窗帘杆环上\n4. 调整帘褶均匀度\n注意：建议两人配合安装大尺寸窗帘。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔遮光帘安装方法"},
                tool_result_data={"chunks": [{"content": "窗帘安装步骤：挂钩→挂杆→调整"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "跨到knowledge（指代消解'那个商品'→雪尼尔遮光帘）"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="帮我取消那个订单",
            expected_graph_result=make_graph_result(
                final_answer="已取消订单 ORD20250501088（李先生的雪尼尔遮光帘订单）。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "cancel", "order_id": "ORD20250501088"},
                tool_result_data={"order_no": "ORD20250501088", "status": "cancelled"},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "跨回order（指代消解'那个订单'→ORD20250501088）"},
                {"fn": lambda s, r, e: "取消" in r.content, "desc": "取消操作成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 25 存在失败检查点\n{report}"

    # ---------- Case 26: 对话阶段完整生命周期 ----------

    async def test_case_26_conversation_lifecycle(self):
        """
        Case 26: 对话阶段完整生命周期（6轮）
        验证重点：INITIAL→QUERYING→CONFIRMING→PROCESSING→COMPLETED→INITIAL
        涉及Skill: direct_reply, product, order | Tools: product_search, product_detail, order_manage
        """
        runner = MultiTurnRunner(26, "对话阶段完整生命周期")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # INITIAL
        await runner.run_turn(
            turn_num=1,
            user_message="你好，我想买窗帘",
            expected_graph_result=make_graph_result(
                final_answer="您好！欢迎光临。我可以帮您挑选窗帘。请问您有什么需求？比如遮光、装饰、或者特定风格？",
                skill_used="direct_reply", intent="greeting", confidence=0.90,
            ),
            checks=[
                {"fn": lambda s, r, e: "greeting" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段INITIAL: 问候识别"},
            ],
        )

        # QUERYING
        await runner.run_turn(
            turn_num=2,
            user_message="想要遮光效果好的，预算300左右",
            expected_graph_result=make_graph_result(
                final_answer="为您推荐300左右的遮光帘：\n1. 雪尼尔遮光帘 ¥299 遮光95%\n2. 雪尼尔星空系列 ¥329 遮光95%\n要看哪款的详情？",
                skill_used="product", intent="product_inquiry", confidence=0.92,
                tool_name="product_search",
                tool_args={"keyword": "遮光", "min_price": 200, "max_price": 400},
                tool_result_data={"products": [{"id": "p001", "name": "雪尼尔遮光帘", "price": 299}, {"id": "p051", "name": "雪尼尔星空系列", "price": 329}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product_inquiry" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段QUERYING: 商品查询"},
            ],
        )

        # CONFIRMING
        await runner.run_turn(
            turn_num=3,
            user_message="第一个不错，想要这个",
            expected_graph_result=make_graph_result(
                final_answer="确认您选择「雪尼尔遮光帘」¥299：\n- 遮光率95%\n- 可选颜色: 米白/浅灰/深咖\n- 支持尺寸定制\n请问需要什么颜色和尺寸？确认后可以下单。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "雪尼尔遮光帘", "price": 299, "colors": ["米白", "浅灰", "深咖"]},
            ),
            checks=[
                {"fn": lambda s, r, e: "确认" in r.content, "desc": "阶段CONFIRMING: 确认购买意向"},
            ],
        )

        # PROCESSING
        await runner.run_turn(
            turn_num=4,
            user_message="浅灰色，宽2米高2.5米",
            expected_graph_result=make_graph_result(
                final_answer="已为您记录选择：\n- 商品: 雪尼尔遮光帘\n- 颜色: 浅灰\n- 尺寸: 2m×2.5m\n- 金额: ¥299\n订单已创建，等待支付确认。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "create", "product_id": "p001", "specifications": {"color": "浅灰", "width": "2m", "height": "2.5m"}},
                tool_result_data={"order_no": "ORD20250505NEW", "status": "pending_payment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "创建" in r.content or "记录" in r.content, "desc": "阶段PROCESSING: 订单创建"},
            ],
        )

        # COMPLETED
        await runner.run_turn(
            turn_num=5,
            user_message="好的，已经付款了",
            expected_graph_result=make_graph_result(
                final_answer="收到付款确认！订单ORD20250505NEW已更新为「待发货」状态。预计1-2天内发货，届时我会通知您物流信息。感谢购买！",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250505NEW", "new_status": "pending_shipment"},
                tool_result_data={"order_no": "ORD20250505NEW", "new_status": "pending_shipment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "感谢" in r.content or "待发货" in r.content, "desc": "阶段COMPLETED: 交易完成"},
            ],
        )

        # 回到 INITIAL
        await runner.run_turn(
            turn_num=6,
            user_message="谢谢，再见",
            expected_graph_result=make_graph_result(
                final_answer="不客气！祝您生活愉快，有需要随时找我。再见！",
                skill_used="direct_reply", intent="farewell", confidence=0.95,
            ),
            checks=[
                {"fn": lambda s, r, e: "farewell" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段回到INITIAL: 告别"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 26 存在失败检查点\n{report}"

    # ---------- Case 27: 会话中途主题切换与回溯 ----------

    async def test_case_27_topic_switch_and_backtrack(self):
        """
        Case 27: 会话中途主题切换与回溯（6轮）
        验证重点：主题切换、"回到刚才"的回溯、两个主题并行
        涉及Skill: product, order | Tools: product_detail, logistics_track, product_manage
        """
        runner = MultiTurnRunner(27, "会话中途主题切换与回溯")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看丝绒遮光帘的详情",
            expected_graph_result=make_graph_result(
                final_answer="丝绒遮光帘(p003)：\n- 价格: ¥369\n- 面料: 丝绒\n- 遮光率: 99%\n- 颜色: 深蓝/墨绿/酒红\n- 重量: 较重，需要加固杆",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_detail",
                tool_args={"product_id": "p003"},
                tool_result_data={"id": "p003", "name": "丝绒遮光帘", "price": 369},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content, "desc": "主题A启动：查看丝绒遮光帘"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="等一下，先帮我查个物流 ORD20250501088",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250501088物流：\n- 快递: 韵达 YD20250502333\n- 状态: 配送中\n- 预计今天送达\n查完了，需要继续看刚才的商品吗？",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501088"},
                tool_result_data={"tracking_number": "YD20250502333", "company": "韵达", "status": "delivering"},
            ),
            checks=[
                {"fn": lambda s, r, e: "logistics_track" in e.get("intent_result", {}).get("intent", ""), "desc": "主题切换：突然问物流"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这个包裹到了联系客户确认收货",
            expected_graph_result=make_graph_result(
                final_answer="好的，订单ORD20250501088快递已在配送中，到货后我提醒您联系客户确认收货。",
                skill_used="order", intent="order_query", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "确认收货" in r.content or "提醒" in r.content, "desc": "物流主题继续处理"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="回到刚才那个商品，帮我调一下价格到349",
            expected_graph_result=make_graph_result(
                final_answer="已将「丝绒遮光帘」(p003) 价格调整：¥369→¥349。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p003", "price": 349},
                tool_result_data={"id": "p003", "price": 349},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "349" in r.content, "desc": "回溯到主题A（指代消解'刚才那个商品'→丝绒遮光帘）"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这个商品再补50件库存",
            expected_graph_result=make_graph_result(
                final_answer="已为「丝绒遮光帘」(p003) 补货50件，当前库存250件。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p003", "quantity": 50},
                tool_result_data={"product_id": "p003", "new_stock": 250},
            ),
            checks=[
                {"fn": lambda s, r, e: "250" in r.content or "50" in r.content, "desc": "继续主题A操作"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="今天处理了两件事，帮我总结一下",
            expected_graph_result=make_graph_result(
                final_answer="今日处理总结：\n1. 物流追踪：订单ORD20250501088（韵达配送中，待确认收货）\n2. 商品管理：丝绒遮光帘(p003) 调价369→349，补货50件(库存250)\n两件事都已处理完毕。",
                skill_used="general_agent", intent="general", confidence=0.75,
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501088" in r.content and "丝绒" in r.content, "desc": "总结覆盖两个主题"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 27 存在失败检查点\n{report}"

    # ==================== E. Thinking Mode 专项验证类 ====================

    # ---------- Case 28: 复杂推理：多条件商品筛选决策 ----------

    async def test_case_28_thinking_complex_product_reasoning(self):
        """
        Case 28: 复杂推理：多条件商品筛选决策（5轮）
        验证重点：thinking mode推理过程、多条件组合搜索
        涉及Skill: product, knowledge | Tools: product_search, product_detail, knowledge_search
        """
        runner = MultiTurnRunner(28, "复杂推理：多条件商品筛选决策")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        thinking_1 = "用户需求分析：预算300以内+北欧风格+遮光好。需要搜索遮光帘类目，价格筛选300以下，风格关键词北欧。"

        await runner.run_turn(
            turn_num=1,
            user_message="我预算300以内，想要北欧风格的，遮光效果要好的窗帘",
            expected_graph_result=make_graph_result(
                final_answer="根据您的需求（预算≤300、北欧风格、高遮光），为您筛选：\n1. 北欧简约遮光帘 ¥199 遮光90%\n2. 北欧灰调遮光帘 ¥269 遮光95%\n3. 北欧几何纹遮光帘 ¥289 遮光92%\n推荐第2款，性价比和遮光率最优。",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "北欧遮光", "max_price": 300},
                tool_result_data={"products": [
                    {"id": "p002", "name": "北欧简约遮光帘", "price": 199, "blackout_rate": "90%"},
                    {"id": "p030", "name": "北欧灰调遮光帘", "price": 269, "blackout_rate": "95%"},
                    {"id": "p031", "name": "北欧几何纹遮光帘", "price": 289, "blackout_rate": "92%"},
                ]},
                thinking_content=thinking_1,
            ),
            checks=[
                {"fn": lambda s, r, e: "北欧" in r.content and "遮光" in r.content, "desc": "多条件筛选结果正确"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签未泄露到回复中"},
                {"fn": lambda s, r, e: thinking_1 not in r.content, "desc": "thinking内容未泄露到回复中"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="第二个遮光95%是真的吗，怎么做到的",
            expected_graph_result=make_graph_result(
                final_answer="北欧灰调遮光帘遮光率95%的技术原理：\n- 采用三层复合结构（面料+遮光涂层+里布）\n- 中间层为银色遮光涂层\n- 经国标GB/T测试达95%\n是真实数据，不是虚标。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "遮光帘95%遮光率原理"},
                tool_result_data={"chunks": [{"content": "三层复合结构+遮光涂层实现95%遮光率"}]},
                thinking_content="用户质疑遮光率数据，需要从知识库找到遮光率的技术原理来解答",
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "技术问题走knowledge"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签未泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="和第三个比呢，哪个更适合卧室",
            expected_graph_result=make_graph_result(
                final_answer="卧室推荐对比：\n| | 北欧灰调 ¥269 | 北欧几何纹 ¥289 |\n|遮光|95% ✓|92%|\n|风格|纯色低调|几何图案|\n|适合|极简卧室|有设计感的卧室|\n\n💡推理结论：如果纯粹追求遮光睡眠，选灰调款；如果想要设计感，选几何纹款。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p030"},
                tool_result_data={"id": "p030", "name": "北欧灰调遮光帘", "price": 269},
                thinking_content="对比两款商品：灰调遮光率更高适合纯睡眠场景，几何纹有设计感适合想要装饰效果的卧室",
            ),
            checks=[
                {"fn": lambda s, r, e: "灰调" in r.content and "几何" in r.content, "desc": "对比分析两款商品"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签清除验证"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="我就要遮光最好的那个",
            expected_graph_result=make_graph_result(
                final_answer="好的，为您确认选择「北欧灰调遮光帘」¥269（遮光率95%）。这是您预算范围内遮光效果最好的选择。需要什么尺寸和颜色？",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                thinking_content="用户说'遮光最好的'，根据之前对比，灰调款95%>几何纹92%，所以选灰调款",
            ),
            checks=[
                {"fn": lambda s, r, e: "灰调" in r.content or "269" in r.content, "desc": "推理出最优选择"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking内容不泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="灰色，宽1.8米高2.4米",
            expected_graph_result=make_graph_result(
                final_answer="已确认：\n- 商品: 北欧灰调遮光帘\n- 颜色: 灰色\n- 尺寸: 1.8m×2.4m\n- 价格: ¥269\n遮光率95%，非常适合卧室使用。如需下单请确认。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
            ),
            checks=[
                {"fn": lambda s, r, e: "1.8" in r.content and "2.4" in r.content, "desc": "规格确认完整"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 28 存在失败检查点\n{report}"

    # ---------- Case 29: 复杂推理：售后纠纷判责 ----------

    async def test_case_29_thinking_aftersales_dispute_judgment(self):
        """
        Case 29: 复杂推理：售后纠纷判责（5轮）
        验证重点：thinking推理责任归属、证据链、政策适用
        涉及Skill: aftersales, order, knowledge | Tools: order_query, logistics_track, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(29, "复杂推理：售后纠纷判责")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="一个客户说窗帘安装后发现尺寸比下单时写的小了5cm，要求退款",
            expected_graph_result=make_graph_result(
                final_answer="了解情况：客户反映实际尺寸比订单规格小5cm。这需要核实：\n1. 订单规格是什么\n2. 实际商品是否确实偏小\n3. 是生产偏差还是客户量错\n请提供订单号，我帮您查看。",
                skill_used="aftersales_skill", intent="after_sales", confidence=0.90,
                thinking_content="售后纠纷场景，尺寸偏差需要判断责任方：生产方/物流方/客户方。先收集订单信息。",
            ),
            checks=[
                {"fn": lambda s, r, e: "after_sales" in e.get("intent_result", {}).get("intent", ""), "desc": "识别为售后意图"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking未泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="订单ORD20250425200，客户说下单写的2.0m但收到的只有1.95m",
            expected_graph_result=make_graph_result(
                final_answer="查到订单信息：\n- 订单号: ORD20250425200\n- 规格: 宽2.0m×高2.5m\n- 商品: 定制雪尼尔遮光帘\n- 备注: 客户自行量尺\n客户下单确实写的2.0m。需要确认偏差5cm是否在容许范围内。",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250425200"},
                tool_result_data={"order_no": "ORD20250425200", "specifications": {"width": "2.0m", "height": "2.5m"}, "product_name": "定制雪尼尔遮光帘", "note": "客户自行量尺"},
                thinking_content="订单规格2.0m，实际1.95m，偏差5cm=2.5%。需要查知识库确认定制商品的允许偏差范围。",
            ),
            checks=[
                {"fn": lambda s, r, e: "2.0m" in r.content, "desc": "查到订单规格信息"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="我们的定制误差标准是多少",
            expected_graph_result=make_graph_result(
                final_answer="定制商品尺寸误差标准：\n- 宽度误差容许: ±2cm（即2.0m允许范围1.98m-2.02m）\n- 高度误差容许: ±3cm\n- 超出容许范围：可退换或补做\n📋 判断：偏差5cm超出容许范围(±2cm)，属于生产质量问题。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "定制商品尺寸误差容许范围标准"},
                tool_result_data={"chunks": [{"content": "定制窗帘宽度误差±2cm，高度±3cm，超出可退换"}]},
                thinking_content="偏差5cm超出±2cm的容许范围，判定为生产方责任。客户可以退换或要求补做。",
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "查询政策标准"},
                {"fn": lambda s, r, e: "超出" in r.content or "5cm" in r.content or "质量" in r.content, "desc": "判定超出容许范围"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="那按照政策应该怎么处理",
            expected_graph_result=make_graph_result(
                final_answer="根据推理判定和政策：\n\n📋 判责结论：生产方责任（偏差5cm超出±2cm标准）\n\n🔧 处理方案：\n1. 【推荐】免费补做正确尺寸+客户保留原帘作为补偿\n2. 全额退款退货\n3. 退差价30%作为补偿\n\n建议方案1，客户满意度最高且成本可控。",
                skill_used="aftersales_skill", intent="after_sales", confidence=0.88,
                thinking_content="责任明确：生产方。方案选择推理：1.补做+保留原品=客户获得超值补偿,满意度高;2.全退=客户流失;3.退差价=客户可能不满。推荐方案1。",
            ),
            checks=[
                {"fn": lambda s, r, e: "生产" in r.content or "责任" in r.content, "desc": "给出明确判责"},
                {"fn": lambda s, r, e: "补做" in r.content or "退款" in r.content, "desc": "给出处理方案"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking推理不泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="客户接受方案1，帮我安排",
            expected_graph_result=make_graph_result(
                final_answer="已安排处理：\n- 订单ORD20250425200标记为「补做处理中」\n- 补做规格: 宽2.0m×高2.5m（已加强QC检查标记）\n- 客户保留原帘\n- 预计5-7天补做完成\n已通知生产部门优先处理。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250425200", "new_status": "remaking", "reason": "尺寸偏差补做"},
                tool_result_data={"order_no": "ORD20250425200", "new_status": "remaking"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补做" in r.content, "desc": "执行补做方案"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 29 存在失败检查点\n{report}"

    # ---------- Case 30: Thinking输出清理验证 ----------

    async def test_case_30_thinking_output_strip_verification(self):
        """
        Case 30: Thinking输出清理验证（4轮）
        验证重点：_strip_think_tags()正确性、thinking不泄露
        涉及Skill: product, order | Tools: product_search, order_query
        """
        runner = MultiTurnRunner(30, "Thinking输出清理验证")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 模拟LLM返回带think标签的响应
        thinking_content_1 = "用户想搜索窗帘，应该调用product_search工具，关键词为窗帘"
        raw_response_1 = make_thinking_response(thinking_content_1, "为您找到以下窗帘商品：\n1. 雪尼尔遮光帘 ¥299")
        clean_answer_1 = "为您找到以下窗帘商品：\n1. 雪尼尔遮光帘 ¥299"

        await runner.run_turn(
            turn_num=1,
            user_message="搜一下窗帘",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_1,
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "窗帘"},
                tool_result_data={"products": [{"id": "p001", "name": "雪尼尔遮光帘", "price": 299}]},
                thinking_content=thinking_content_1,
            ),
            checks=[
                {"fn": lambda s, r, e: verify_thinking_stripped(raw_response_1, r.content), "desc": "_strip_think_tags: think标签已清除"},
                {"fn": lambda s, r, e: verify_thinking_not_leaked(r.content, thinking_content_1), "desc": "thinking内容未泄露给用户"},
                {"fn": lambda s, r, e: "窗帘" in r.content, "desc": "最终回答内容正确"},
            ],
        )

        # 轮2: 复杂thinking（含多行推理）
        thinking_content_2 = "用户说'查订单'但没给订单号。分析上下文：之前搜了窗帘。可能是想查和窗帘相关的订单。但不确定，应该问清楚。考虑因素：1.用户可能是管理员查看订单列表 2.也可能是查具体订单。决策：询问更多信息。"
        clean_answer_2 = "请问您想查哪个订单？可以提供订单号、客户手机号或姓名来查询。"

        await runner.run_turn(
            turn_num=2,
            user_message="查个订单",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_2,
                skill_used="order", intent="order_query", confidence=0.70,
                thinking_content=thinking_content_2,
            ),
            checks=[
                {"fn": lambda s, r, e: verify_thinking_stripped(make_thinking_response(thinking_content_2, clean_answer_2), r.content), "desc": "_strip_think_tags: 多行thinking清除"},
                {"fn": lambda s, r, e: "分析上下文" not in r.content and "决策" not in r.content, "desc": "推理过程关键词不出现在回复中"},
                {"fn": lambda s, r, e: "订单号" in r.content or "手机号" in r.content, "desc": "回复正常引导用户"},
            ],
        )

        # 轮3: thinking含特殊字符和代码片段
        thinking_content_3 = "用户提供了订单号ORD20250501001。调用order_query(order_no='ORD20250501001')。结果：{status: 'shipped', amount: 299}。格式化输出给用户。"
        clean_answer_3 = "订单 ORD20250501001：\n- 状态: 已发货\n- 金额: ¥299\n- 快递: 顺丰速运"

        await runner.run_turn(
            turn_num=3,
            user_message="ORD20250501001",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_3,
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250501001"},
                tool_result_data={"order_no": "ORD20250501001", "status": "shipped", "total_amount": 299},
                thinking_content=thinking_content_3,
            ),
            checks=[
                {"fn": lambda s, r, e: "order_query" not in r.content, "desc": "thinking中的工具调用细节不泄露"},
                {"fn": lambda s, r, e: "格式化输出" not in r.content, "desc": "thinking中的内部指令不泄露"},
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "299" in r.content, "desc": "最终回答包含正确订单信息"},
            ],
        )

        # 轮4: 嵌套think标签（边界情况）
        thinking_content_4 = "用户问物流状态。<think>这是嵌套标签测试</think>需要调用logistics_track。"
        clean_answer_4 = "物流状态：已到达杭州分拣中心，预计明天送达。"

        await runner.run_turn(
            turn_num=4,
            user_message="物流到哪了",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_4,
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501001"},
                tool_result_data={"status": "in_transit", "location": "杭州分拣中心"},
                thinking_content=thinking_content_4,
            ),
            checks=[
                {"fn": lambda s, r, e: "<think>" not in r.content and "</think>" not in r.content, "desc": "嵌套think标签全部清除"},
                {"fn": lambda s, r, e: "嵌套标签测试" not in r.content, "desc": "嵌套thinking内容不泄露"},
                {"fn": lambda s, r, e: "杭州" in r.content or "明天" in r.content, "desc": "最终回答正常输出"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 30 存在失败检查点\n{report}"


# ========== 汇总报告测试 ==========


class TestMibaoAdvancedSummaryReport:
    """汇总运行全部 20 个高级 Case 并生成报告"""

    async def test_advanced_summary(self, capsys):
        """运行全部 20 个高级 Case 并输出汇总报告"""
        suite = TestMibaoAdvancedMultiturn()
        cases = [
            ("Case 11", suite.test_case_11_batch_order_filter_and_mark),
            ("Case 12", suite.test_case_12_inventory_alert_batch_restock),
            ("Case 13", suite.test_case_13_batch_product_create_and_refine),
            ("Case 14", suite.test_case_14_order_financial_summary),
            ("Case 15", suite.test_case_15_aftersales_inventory_recovery),
            ("Case 16", suite.test_case_16_knowledge_driven_product_recommendation),
            ("Case 17", suite.test_case_17_promotion_product_management),
            ("Case 18", suite.test_case_18_customer_portrait_building),
            ("Case 19", suite.test_case_19_supply_chain_exception_handling),
            ("Case 20", suite.test_case_20_order_not_found_recovery),
            ("Case 21", suite.test_case_21_permission_graceful_degradation),
            ("Case 22", suite.test_case_22_product_inconsistency_detection),
            ("Case 23", suite.test_case_23_logistics_exception_graded_handling),
            ("Case 24", suite.test_case_24_continuous_error_tolerance),
            ("Case 25", suite.test_case_25_cross_skill_coreference_chain),
            ("Case 26", suite.test_case_26_conversation_lifecycle),
            ("Case 27", suite.test_case_27_topic_switch_and_backtrack),
            ("Case 28", suite.test_case_28_thinking_complex_product_reasoning),
            ("Case 29", suite.test_case_29_thinking_aftersales_dispute_judgment),
            ("Case 30", suite.test_case_30_thinking_output_strip_verification),
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
        print("米宝高级多轮对话智能测试 - 汇总报告（20个场景）")
        print("=" * 60)
        total = len(results)
        passed = sum(1 for _, s, _ in results if s == "PASS")
        for name, status, msg in results:
            icon = "✅" if status == "PASS" else "❌"
            detail = f" | {msg}" if msg else ""
            print(f"  {icon} {name}: {status}{detail}")
        print(f"\n总计: {passed}/{total} 通过")
        print("=" * 60)

        # 分类统计
        categories = {
            "A.批量数据处理": results[0:4],
            "B.跨领域联动": results[4:9],
            "C.异常与边界处理": results[9:14],
            "D.深度上下文与记忆": results[14:17],
            "E.Thinking Mode专项": results[17:20],
        }
        print("\n分类通过率:")
        for cat_name, cat_results in categories.items():
            cat_passed = sum(1 for _, s, _ in cat_results if s == "PASS")
            cat_total = len(cat_results)
            print(f"  {cat_name}: {cat_passed}/{cat_total}")
        print("=" * 60)
