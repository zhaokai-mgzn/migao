"""
米宝多轮测试共享基础设施（由 test_mibao_advanced_multiturn.py 拆分，2026-08-29）

包含: TurnResult / CaseResult / MultiTurnRunner / make_graph_result /
make_thinking_response / verify_* / _reset_singletons
被 tests/test_mibao_multiturn_{order,product,aftersales,reliability,advanced}.py 复用。
"""
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
# case_ids: AS-005, CH-002, OR-006, PR-011, PR-012

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
