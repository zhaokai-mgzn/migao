"""
LLM 熔断器作用域隔离（issue #3270）。

背景（2026-09-11 实证，本地 DEBUG 栈 + 真实 LLM）：
`app/graph/skills/base_skill.py` 用一个**全局常量**做熔断器名：

    LLM_BREAKER = "llm_minimax"          # 遗留名，与实际模型无关
    llm_breaker = get_breaker(LLM_BREAKER)   # 所有 skill 共用同一个实例

后果：任一 skill 的 LLM 连续 3 次超时（60s 阈值）→ 该**全局**熔断器 OPEN →
**全部** skill 的 LLM 调用被拒 → 用户侧统一看到 "抱歉，AI 服务暂时不可用，请稍后重试。"

实测日志：
    [circuit-breaker:llm_minimax] OPEN → HALF_OPEN | reason=recovery_timeout(30.0s)
    [circuit-breaker:llm_minimax] HALF_OPEN → OPEN | reason=probe failed: TimeoutError failures=4
    [customer_order][SLS] LLM circuit_breaker_open
    → assistant: 抱歉，AI 服务暂时不可用，请稍后重试。

C 端场景影响：查订单 / 下单 / 问知识 全部返回同一句兜底文案 —— 单点超时拖垮整机。
"""
# case_ids: DF-011, DF-012
import asyncio
import inspect

import pytest

from app.core.circuit_breaker import (
    CircuitBreakerState,
    get_breaker,
    reset_breakers,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_breakers()
    yield
    reset_breakers()


class TestLLMBreakerScope:
    """每个 skill 必须拥有独立熔断器（防单点超时拖垮整机）"""

    def test_llm_breaker_name_is_per_skill(self):
        """llm_breaker_name(skill) 对不同 skill 返回不同名字"""
        from app.graph.skills.base_skill import llm_breaker_name

        names = {llm_breaker_name(s) for s in
                 ("customer_order", "customer_product", "customer_knowledge")}
        assert len(names) == 3, f"不同 skill 必须得到不同熔断器名，实得 {names}"

    def test_llm_breaker_name_stable_for_same_skill(self):
        """同一 skill 多次取名字必须稳定（否则熔断器每次都新建，熔断失效）"""
        from app.graph.skills.base_skill import llm_breaker_name

        assert llm_breaker_name("customer_order") == llm_breaker_name("customer_order")

    def test_llm_breaker_name_prefix_identifies_llm(self):
        """名字带统一前缀，便于日志/监控按 llm 维度聚合"""
        from app.graph.skills.base_skill import llm_breaker_name

        assert llm_breaker_name("customer_order").startswith("llm:")

    def test_legacy_global_name_no_longer_used(self):
        """遗留的全局常量 LLM_BREAKER 不得再被用作熔断器名（防回归）"""
        import app.graph.skills.base_skill as bs

        # 若保留该常量，必须不再参与 get_breaker 调用
        src = inspect.getsource(bs)
        assert "get_breaker(LLM_BREAKER)" not in src, (
            "仍有 get_breaker(LLM_BREAKER) 调用 —— 全局单一熔断器回归"
        )

    @pytest.mark.asyncio
    async def test_one_skill_failure_does_not_open_other_skill_breaker(self):
        """核心契约：skill A 的 LLM 连续失败 → skill B 的熔断器仍 CLOSED"""
        from app.graph.skills.base_skill import llm_breaker_name

        async def boom():
            raise TimeoutError("llm slow")

        a = get_breaker(llm_breaker_name("customer_order"))
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await a.call(boom)
        assert a.state == CircuitBreakerState.OPEN, "A 连续失败应 OPEN"

        b = get_breaker(llm_breaker_name("customer_product"))
        assert b.state == CircuitBreakerState.CLOSED, (
            "skill A 熔断不得影响 skill B —— 这正是 #3270 的整机降级根因"
        )

    @pytest.mark.asyncio
    async def test_other_skill_still_usable_after_first_opens(self):
        """skill A 熔断后，skill B 的 LLM 调用仍能成功（用户可见契约）"""
        from app.graph.skills.base_skill import llm_breaker_name

        async def boom():
            raise TimeoutError("llm slow")

        async def ok():
            return "fine"

        a = get_breaker(llm_breaker_name("customer_order"))
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await a.call(boom)

        b = get_breaker(llm_breaker_name("customer_knowledge"))
        assert await b.call(ok) == "fine", "skill B 应仍可用"


class TestLLMTimeoutConfigurable:
    """LLM 调用超时不得硬编码 60s（慢模型/长 prompt 下必然误熔断）"""

    def test_timeout_is_module_level_constant(self):
        """超时应是模块级常量（可单测、可配置），不再散落两处字面量"""
        import app.graph.skills.base_skill as bs

        assert hasattr(bs, "LLM_CALL_TIMEOUT_S"), "缺 LLM_CALL_TIMEOUT_S 常量"
        assert isinstance(bs.LLM_CALL_TIMEOUT_S, (int, float))
        assert bs.LLM_CALL_TIMEOUT_S >= 60.0, (
            "LLM 超时阈值应 >= 60s（低于此值在 reasoning 模型 + 多工具 prompt 下误熔断）"
        )

    def test_no_hardcoded_timeout_literal(self):
        """源码中不得再出现 wait_for(..., timeout=60.0) 字面量"""
        import app.graph.skills.base_skill as bs

        src = inspect.getsource(bs)
        assert "timeout=60.0" not in src, (
            "仍有硬编码 timeout=60.0 —— 应改用 LLM_CALL_TIMEOUT_S"
        )


class TestRegisteredSkillsGetDistinctBreakers:
    """集成级契约：真实注册的所有 skill 必须各自拥有独立熔断器"""

    def test_all_registered_skills_map_to_distinct_breakers(self):
        """遍历 skill_registry 注册的真实 skill，验证熔断器名两两不同。

        防止将来新增 skill 时误传固定名（如把 config.name 换成字面量）
        → 又退回「全局单一熔断器」。
        """
        from app.graph.skills.skill_registry import get_skill_registry
        from app.graph.skills.base_skill import llm_breaker_name

        registry = get_skill_registry()
        names = registry.get_names()
        assert len(names) >= 10, f"注册 skill 过少，疑似取错对象：{names}"

        breaker_names = [llm_breaker_name(n) for n in names]
        assert len(set(breaker_names)) == len(breaker_names), (
            f"存在共享熔断器名的 skill：{breaker_names}"
        )
