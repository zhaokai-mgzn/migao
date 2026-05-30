"""
单元测试: LLM 管道 (app/llm/*)

覆盖范围:
- router.select_model: 路由开关 / 简单意图 / 工具数量 / 文本长度
- cost_tracker: CostRecord / track_call 计费 / check_budget warning / get_summary / reset / Lock
- retry_policy.call_with_retry: 超时 / 429 / 5xx / 401 / 400 / 重试上限 / 指数退避
- factory.LLMFactory: skill / intent / suggestion 实例参数

全部使用 mock，不发起真实 API 调用。
"""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.llm import (
    LLMFactory,
    MODEL_MAX,
    MODEL_PLUS,
    MODEL_TURBO,
    MODEL_FLASH,
    CostRecord,
    CostTracker,
    MODEL_PRICING,
    call_with_retry,
    select_model,
)
from app.llm.factory import DASHSCOPE_BASE_URL


# =============================================================================
# helpers
# =============================================================================
class _FakeHTTPStatusError(Exception):
    """模拟 httpx.HTTPStatusError，仅用于触发 retry_policy 的状态码识别"""

    def __init__(self, status_code: int, message: str = "fake http error"):
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        # 同时挂一个 response 对象，覆盖 _extract_status_code 的两条分支
        self.response = MagicMock()
        self.response.status_code = status_code


def _make_factory(side_effects):
    """生成一个无参 async 工厂；side_effects 元素若为 Exception 则抛出，否则返回。"""
    iterator = iter(side_effects)

    async def _factory():
        item = next(iterator)
        if isinstance(item, BaseException):
            raise item
        return item

    return _factory


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def routing_on(monkeypatch):
    """开启模型路由"""
    monkeypatch.setattr(settings, "LLM_ENABLE_MODEL_ROUTING", True)


@pytest.fixture
def routing_off(monkeypatch):
    """关闭模型路由"""
    monkeypatch.setattr(settings, "LLM_ENABLE_MODEL_ROUTING", False)


@pytest.fixture
def cost_tracking_on(monkeypatch):
    """开启成本追踪"""
    monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)


@pytest.fixture
def fresh_tracker(cost_tracking_on):
    """提供一个干净的 CostTracker 实例"""
    return CostTracker()


@pytest.fixture
def fast_retry(monkeypatch):
    """加速重试：sleep 立即返回，避免单测真等"""
    async def _zero_sleep(_seconds):
        return None

    monkeypatch.setattr("app.llm.retry_policy.asyncio.sleep", _zero_sleep)
    # 默认 2 次重试，0.01s 基础延迟
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY_S", 0.01)


# =============================================================================
# 1. 模型路由 router.select_model
# =============================================================================
class TestSelectModel:
    """模型路由测试"""

    def test_routing_disabled_returns_default_model(self, routing_off, monkeypatch):
        """LLM_ENABLE_MODEL_ROUTING=False 时返回 settings.DASHSCOPE_MODEL"""
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.7-max")
        # 即便参数复杂，也必须返回默认模型
        assert select_model(intent="other", tool_count=10, text_length=99999) == "qwen3.7-max"

    def test_routing_disabled_ignores_force_model(self, routing_off, monkeypatch):
        """关闭路由时即使 force_model 也不生效"""
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.7-max")
        assert select_model(force_model="qwen-turbo") == "qwen3.7-max"

    def test_routing_greeting_intent_to_turbo(self, routing_on):
        """greeting 意图 → MODEL_TURBO"""
        assert select_model(intent="greeting") == MODEL_TURBO

    def test_routing_farewell_intent_to_turbo(self, routing_on):
        """farewell 意图 → MODEL_TURBO"""
        assert select_model(intent="farewell") == MODEL_TURBO

    def test_routing_capabilities_intent_to_turbo(self, routing_on):
        """capabilities 意图也属于简单意图 → MODEL_TURBO"""
        assert select_model(intent="capabilities") == MODEL_TURBO

    def test_routing_intent_case_insensitive(self, routing_on):
        """意图判定大小写不敏感"""
        assert select_model(intent="GREETING") == MODEL_TURBO
        assert select_model(intent="FareWell") == MODEL_TURBO

    def test_routing_high_tool_count_to_max(self, routing_on):
        """tool_count >= 3 → MODEL_MAX"""
        assert select_model(tool_count=3) == MODEL_MAX
        assert select_model(tool_count=10) == MODEL_MAX

    def test_routing_long_text_to_max(self, routing_on):
        """text_length > 8000 → MODEL_MAX"""
        assert select_model(text_length=8001) == MODEL_MAX
        assert select_model(text_length=20000) == MODEL_MAX

    def test_routing_default_to_plus(self, routing_on):
        """普通场景 → MODEL_PLUS"""
        assert select_model() == MODEL_PLUS
        assert select_model(intent="order_query", tool_count=2, text_length=1000) == MODEL_PLUS

    def test_routing_force_model_overrides_auto(self, routing_on):
        """force_model 直接覆盖自动判定"""
        assert select_model(intent="greeting", force_model="qwen-flash") == "qwen-flash"

    def test_model_constants_aligned(self):
        """模型常量与百炼对齐"""
        assert MODEL_MAX == "qwen3.7-max"
        assert MODEL_PLUS == "qwen3.6-plus"
        assert MODEL_TURBO == "qwen-turbo"
        assert MODEL_FLASH == "qwen-flash"

    def test_routing_threshold_boundary(self, routing_on):
        """阈值边界: tool_count=2 走 plus, text_length=8000 走 plus"""
        assert select_model(tool_count=2) == MODEL_PLUS
        assert select_model(text_length=8000) == MODEL_PLUS


# =============================================================================
# 2. 成本追踪 cost_tracker
# =============================================================================
class TestCostRecord:
    """CostRecord 数据结构测试"""

    def test_record_basic_fields(self):
        record = CostRecord(
            model="qwen-turbo",
            input_tokens=100,
            output_tokens=50,
            cost_cny=0.0001,
        )
        assert record.model == "qwen-turbo"
        assert record.input_tokens == 100
        assert record.output_tokens == 50
        assert record.cost_cny == 0.0001
        assert record.tenant_id is None
        assert record.session_id is None

    def test_record_with_tenant_session(self):
        record = CostRecord(
            model="qwen3.7-max",
            input_tokens=1000,
            output_tokens=500,
            cost_cny=0.05,
            tenant_id=42,
            session_id="sess_abc",
        )
        assert record.tenant_id == 42
        assert record.session_id == "sess_abc"


class TestCostTracker:
    """CostTracker 单元测试"""

    def test_track_call_returns_record_when_enabled(self, fresh_tracker):
        record = fresh_tracker.track_call(
            model="qwen-turbo",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert record is not None
        assert isinstance(record, CostRecord)
        # turbo 定价: input=0.50, output=2.00, 1M tokens 各算 1 单位
        assert record.cost_cny == pytest.approx(0.50 + 2.00, rel=1e-6)

    def test_track_call_disabled_returns_none(self, monkeypatch):
        """LLM_COST_TRACKING_ENABLED=False 时 track_call 返回 None 且不计入"""
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", False)
        tracker = CostTracker()
        result = tracker.track_call(model="qwen-turbo", input_tokens=100, output_tokens=50)
        assert result is None
        assert tracker.total_cost == 0.0

    def test_calc_cost_cny_for_each_model(self, fresh_tracker):
        """每个模型的定价计算正确"""
        # qwen-flash: input=0.30, output=1.20 元/百万
        r = fresh_tracker.track_call(model="qwen-flash", input_tokens=2_000_000, output_tokens=1_000_000)
        assert r.cost_cny == pytest.approx(0.30 * 2 + 1.20 * 1, rel=1e-6)

        # qwen3.6-plus: input=4.00, output=12.00
        r2 = fresh_tracker.track_call(model="qwen3.6-plus", input_tokens=500_000, output_tokens=500_000)
        assert r2.cost_cny == pytest.approx(4.00 * 0.5 + 12.00 * 0.5, rel=1e-6)

        # qwen3.7-max: input=20.00, output=60.00
        r3 = fresh_tracker.track_call(model="qwen3.7-max", input_tokens=100_000, output_tokens=100_000)
        assert r3.cost_cny == pytest.approx(20.00 * 0.1 + 60.00 * 0.1, rel=1e-6)

    def test_unknown_model_falls_back_to_plus_pricing(self, fresh_tracker):
        """未知模型按 plus 兜底"""
        r = fresh_tracker.track_call(model="qwen-unknown", input_tokens=1_000_000, output_tokens=0)
        # plus input=4.00 元/百万
        assert r.cost_cny == pytest.approx(4.00, rel=1e-6)

    def test_total_cost_accumulates(self, fresh_tracker):
        """多次调用累计 total_cost"""
        fresh_tracker.track_call(model="qwen-turbo", input_tokens=1_000_000, output_tokens=0)
        fresh_tracker.track_call(model="qwen-turbo", input_tokens=1_000_000, output_tokens=0)
        # 0.50 * 2 = 1.00
        assert fresh_tracker.total_cost == pytest.approx(1.00, rel=1e-6)

    def test_check_budget_triggers_warning(self, fresh_tracker, monkeypatch, caplog):
        """超预算时 logger.warning 被触发（仅首次）"""
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 1.0)
        with caplog.at_level(logging.WARNING, logger="app.llm.cost_tracker"):
            # 一次大额调用：max input = 20元/百万, 1M => 20元 > 1元
            fresh_tracker.track_call(model="qwen3.7-max", input_tokens=1_000_000, output_tokens=0)

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("budget exceeded" in m for m in warning_msgs)

        # 第二次再超预算不再 warning（_budget_warned=True）
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.llm.cost_tracker"):
            fresh_tracker.track_call(model="qwen3.7-max", input_tokens=1_000_000, output_tokens=0)
        more_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "budget exceeded" in r.message]
        assert len(more_warnings) == 0

    def test_check_budget_disabled_when_zero(self, fresh_tracker, monkeypatch):
        """budget<=0 时直接返回 False"""
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 0.0)
        fresh_tracker.track_call(model="qwen3.7-max", input_tokens=1_000_000, output_tokens=1_000_000)
        assert fresh_tracker.check_budget() is False

    def test_check_budget_returns_true_when_over(self, fresh_tracker, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 0.5)
        fresh_tracker.track_call(model="qwen3.7-max", input_tokens=1_000_000, output_tokens=0)
        assert fresh_tracker.check_budget() is True

    def test_get_summary_groups_by_model(self, fresh_tracker, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 100.0)
        fresh_tracker.track_call(model="qwen-turbo", input_tokens=1_000_000, output_tokens=0)
        fresh_tracker.track_call(model="qwen-turbo", input_tokens=2_000_000, output_tokens=1_000_000)
        fresh_tracker.track_call(model="qwen3.6-plus", input_tokens=500_000, output_tokens=500_000)

        summary = fresh_tracker.get_summary()
        assert summary["total_calls"] == 3
        assert "qwen-turbo" in summary["by_model"]
        assert "qwen3.6-plus" in summary["by_model"]
        assert summary["by_model"]["qwen-turbo"]["calls"] == 2
        assert summary["by_model"]["qwen-turbo"]["input_tokens"] == 3_000_000
        assert summary["by_model"]["qwen-turbo"]["output_tokens"] == 1_000_000
        assert summary["budget_cny"] == 100.0
        assert summary["over_budget"] is False
        assert summary["total_cost"] == pytest.approx(fresh_tracker.total_cost, rel=1e-6)

    def test_reset_clears_state(self, fresh_tracker):
        fresh_tracker.track_call(model="qwen-turbo", input_tokens=1_000_000, output_tokens=0)
        assert fresh_tracker.total_cost > 0

        fresh_tracker.reset()

        assert fresh_tracker.total_cost == 0.0
        summary = fresh_tracker.get_summary()
        assert summary["total_calls"] == 0
        assert summary["by_model"] == {}
        # 重置后再次超预算应能再次 warning
        assert fresh_tracker._budget_warned is False

    def test_thread_safety_lock_present(self, fresh_tracker):
        """至少验证内部 Lock 存在（线程安全占位）"""
        assert hasattr(fresh_tracker, "_lock")
        # threading.Lock() 是工厂函数，返回 _thread.lock 对象，不能用 isinstance(Lock)
        assert hasattr(fresh_tracker._lock, "acquire")
        assert hasattr(fresh_tracker._lock, "release")

    def test_model_pricing_table_completeness(self):
        """关键模型必须存在于 MODEL_PRICING"""
        for m in ("qwen-flash", "qwen-turbo", "qwen3.6-plus", "qwen3.7-max"):
            assert m in MODEL_PRICING
            assert "input" in MODEL_PRICING[m]
            assert "output" in MODEL_PRICING[m]


# =============================================================================
# 3. 重试策略 retry_policy.call_with_retry
# =============================================================================
class TestCallWithRetry:
    """call_with_retry 单元测试"""

    async def test_success_on_first_attempt(self, fast_retry):
        """首次成功直接返回，不重试"""
        factory = _make_factory(["ok"])
        result = await call_with_retry(factory)
        assert result == "ok"

    async def test_timeout_then_success(self, fast_retry):
        """首次 asyncio.TimeoutError → 重试后成功"""
        factory = _make_factory([asyncio.TimeoutError(), "recovered"])
        result = await call_with_retry(factory)
        assert result == "recovered"

    async def test_http_429_then_success(self, fast_retry):
        """429 限流 → 重试后成功"""
        factory = _make_factory([_FakeHTTPStatusError(429), "ok"])
        result = await call_with_retry(factory)
        assert result == "ok"

    async def test_http_500_then_success(self, fast_retry):
        """500 服务异常 → 重试后成功"""
        factory = _make_factory([_FakeHTTPStatusError(500), "ok"])
        result = await call_with_retry(factory)
        assert result == "ok"

    async def test_http_502_503_504_retried(self, fast_retry):
        """502/503/504 都属于可重试"""
        for status in (502, 503, 504):
            factory = _make_factory([_FakeHTTPStatusError(status), f"ok-{status}"])
            assert await call_with_retry(factory) == f"ok-{status}"

    async def test_http_401_not_retried(self, fast_retry):
        """401 鉴权错误 → 不重试，直接抛出"""
        factory = _make_factory([_FakeHTTPStatusError(401)])
        with pytest.raises(_FakeHTTPStatusError) as exc_info:
            await call_with_retry(factory)
        assert exc_info.value.status_code == 401

    async def test_http_400_not_retried(self, fast_retry):
        """400 参数错误 → 不重试，直接抛出"""
        factory = _make_factory([_FakeHTTPStatusError(400)])
        with pytest.raises(_FakeHTTPStatusError) as exc_info:
            await call_with_retry(factory)
        assert exc_info.value.status_code == 400

    async def test_http_403_not_retried(self, fast_retry):
        factory = _make_factory([_FakeHTTPStatusError(403)])
        with pytest.raises(_FakeHTTPStatusError):
            await call_with_retry(factory)

    async def test_http_422_not_retried(self, fast_retry):
        factory = _make_factory([_FakeHTTPStatusError(422)])
        with pytest.raises(_FakeHTTPStatusError):
            await call_with_retry(factory)

    async def test_unknown_exception_not_retried(self, fast_retry):
        """未知异常默认不重试（收敛策略）"""
        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise ValueError("unknown")

        with pytest.raises(ValueError):
            await call_with_retry(_factory)
        assert call_count["n"] == 1

    async def test_circuit_breaker_open_not_retried(self, fast_retry):
        """CircuitBreakerOpenError（按类名识别）→ 不重试"""

        class CircuitBreakerOpenError(Exception):
            pass

        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise CircuitBreakerOpenError("breaker open")

        with pytest.raises(CircuitBreakerOpenError):
            await call_with_retry(_factory)
        assert call_count["n"] == 1

    async def test_max_attempts_respected(self, fast_retry, monkeypatch):
        """重试次数不超过 max_attempts；总尝试次数 = max_retries + 1"""
        monkeypatch.setattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 2)
        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await call_with_retry(_factory)
        # 1 次首发 + 2 次重试 = 3 次
        assert call_count["n"] == 3

    async def test_explicit_max_retries_param(self, fast_retry):
        """显式传入 max_retries 覆盖 settings"""
        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await call_with_retry(_factory, max_retries=4)
        assert call_count["n"] == 5  # 1 + 4

    async def test_zero_retries(self, fast_retry):
        """max_retries=0 时只调用一次"""
        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await call_with_retry(_factory, max_retries=0)
        assert call_count["n"] == 1

    async def test_exponential_backoff_invokes_sleep(self, monkeypatch):
        """验证指数退避：每次重试都调用 asyncio.sleep，且参数随次数递增"""
        monkeypatch.setattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 3)
        monkeypatch.setattr(settings, "LLM_RETRY_BASE_DELAY_S", 1.0)

        sleep_calls: list[float] = []

        async def _spy_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("app.llm.retry_policy.asyncio.sleep", _spy_sleep)
        # 让 jitter 固定为 0，便于断言
        monkeypatch.setattr("app.llm.retry_policy.random.uniform", lambda a, b: 0.0)

        call_count = {"n": 0}

        async def _factory():
            call_count["n"] += 1
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await call_with_retry(_factory)

        # max_retries=3 → 总尝试 4 次，重试前 sleep 3 次
        assert call_count["n"] == 4
        assert len(sleep_calls) == 3
        # 指数退避：1*2^0=1, 1*2^1=2, 1*2^2=4
        assert sleep_calls == [1.0, 2.0, 4.0]

    async def test_status_code_via_response_attr(self, fast_retry):
        """异常通过 .response.status_code 暴露状态码也能识别"""

        class _HttpError(Exception):
            pass

        err = _HttpError("boom")
        err.response = MagicMock()
        err.response.status_code = 401

        factory = _make_factory([err])
        with pytest.raises(_HttpError):
            await call_with_retry(factory)

    async def test_connection_error_retried(self, fast_retry):
        """ConnectionError 视为瞬时错误，可重试"""
        factory = _make_factory([ConnectionError("dns failed"), "ok"])
        assert await call_with_retry(factory) == "ok"


# =============================================================================
# 4. Factory.LLMFactory
# =============================================================================
class TestLLMFactory:
    """LLMFactory 单元测试"""

    @pytest.fixture(autouse=True)
    def _patch_api_key(self, monkeypatch):
        """ChatOpenAI 构造需要 api_key 非空"""
        monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", "test-api-key")

    def test_create_skill_llm_default_model(self, monkeypatch):
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.7-max")
        llm = LLMFactory.create_skill_llm()
        assert llm.model_name == "qwen3.7-max"
        assert llm.temperature == 0.7
        assert llm.streaming is True
        assert llm.max_tokens == 2048
        assert float(llm.request_timeout) == 60.0
        assert llm.extra_body == {"enable_thinking": True}
        assert llm.openai_api_base == DASHSCOPE_BASE_URL

    def test_create_skill_llm_with_model_override(self, monkeypatch):
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.7-max")
        llm = LLMFactory.create_skill_llm(model_override="qwen-turbo")
        assert llm.model_name == "qwen-turbo"
        # 其他参数仍按默认
        assert llm.temperature == 0.7
        assert llm.streaming is True

    def test_create_skill_llm_override_none_uses_default(self, monkeypatch):
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.6-plus")
        llm = LLMFactory.create_skill_llm(model_override=None)
        assert llm.model_name == "qwen3.6-plus"

    def test_create_skill_llm_override_empty_uses_default(self, monkeypatch):
        """空字符串视为未提供，回退到默认模型"""
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.6-plus")
        llm = LLMFactory.create_skill_llm(model_override="")
        assert llm.model_name == "qwen3.6-plus"

    def test_create_intent_llm_config(self, monkeypatch):
        monkeypatch.setattr(settings, "INTENT_MODEL", "qwen-turbo")
        llm = LLMFactory.create_intent_llm()
        assert llm.model_name == "qwen-turbo"
        assert llm.temperature == 0
        assert llm.max_tokens == 100
        assert llm.openai_api_base == DASHSCOPE_BASE_URL
        # intent 不需要 streaming
        assert llm.streaming is False

    def test_create_suggestion_llm_config(self, monkeypatch):
        monkeypatch.setattr(settings, "INTENT_MODEL", "qwen-turbo")
        llm = LLMFactory.create_suggestion_llm()
        assert llm.model_name == "qwen-turbo"
        assert llm.temperature == 0.3
        assert llm.max_tokens == 200
        assert llm.openai_api_base == DASHSCOPE_BASE_URL


# =============================================================================
# 5. 模块级单例 cost_tracker
# =============================================================================
class TestCostTrackerSingleton:
    """app.llm.cost_tracker 模块单例验证"""

    def test_module_level_tracker_is_instance(self):
        from app.llm import cost_tracker  # noqa: WPS433
        assert isinstance(cost_tracker, CostTracker)
