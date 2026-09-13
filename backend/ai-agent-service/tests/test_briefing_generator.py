# case_ids: DA-001, DA-002, ST-001
"""
智能每日经营简报生成器测试（issue #3468）

覆盖数据安全红线：
1. sanitize_briefing：只保留带 metrics 引用的条目（无法对账的丢弃）；
2. generate_briefing：快照为空/LLM 输出不可解析 → 降级返回 None（不编造数据）；
3. prompt 组装：只含快照 JSON（聚合数字 + 脱敏事实），不含任何客户 PII。
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.briefing.generator import (
    BRIEFING_SYSTEM_PROMPT,
    MAX_TODO_ITEMS,
    generate_briefing,
    sanitize_briefing,
)


class TestSanitizeBriefing:
    """清洗层：结构归一化 + 无 metrics 引用条目丢弃"""

    def test_keeps_items_with_metrics(self):
        raw = {
            "summary": "昨日订单 5 单",
            "review": [{"label": "今日订单", "value": 5, "unit": "单", "change": "较昨日 +66.7%"}],
            "todo": [{
                "priority": "high",
                "title": "10 个订单待发货",
                "reason": "超过发货时效",
                "link": "/orders?status=待发货",
                "metrics": [{"key": "pending_ship_orders", "value": 10}],
            }],
            "risks": [],
            "suggestions": [],
        }
        cleaned = sanitize_briefing(raw)
        assert cleaned is not None
        assert cleaned["summary"] == "昨日订单 5 单"
        assert len(cleaned["todo"]) == 1
        assert cleaned["todo"][0]["metrics"] == [{"key": "pending_ship_orders", "value": 10.0}]

    def test_drops_items_without_metrics(self):
        raw = {
            "summary": "x",
            "todo": [{"priority": "high", "title": "无引用的编造条目"}],
            "risks": [{"title": "也是编造的"}],
            "suggestions": [],
        }
        cleaned = sanitize_briefing(raw)
        assert cleaned["todo"] == []
        assert cleaned["risks"] == []

    def test_drops_invalid_metrics_values(self):
        raw = {
            "summary": "x",
            "todo": [{
                "priority": "high",
                "title": "value 非数字",
                "metrics": [{"key": "today_orders", "value": "abc"}],
            }],
            "risks": [],
            "suggestions": [],
        }
        cleaned = sanitize_briefing(raw)
        assert cleaned["todo"] == []

    def test_truncates_titles_and_limits_items(self):
        raw = {
            "summary": "x",
            "todo": [
                {
                    "priority": "low",
                    "title": f"条目{i}",
                    "metrics": [{"key": "k", "value": i}],
                } for i in range(MAX_TODO_ITEMS * 2)
            ],
            "risks": [],
            "suggestions": [],
        }
        cleaned = sanitize_briefing(raw)
        assert len(cleaned["todo"]) == MAX_TODO_ITEMS

    def test_none_input_returns_none(self):
        assert sanitize_briefing(None) is None


class TestGenerateBriefing:
    """生成层：LLM 输出解析 + 降级"""

    @pytest.mark.asyncio
    async def test_success_path(self):
        llm_output = json.dumps({
            "summary": "昨日订单 5 单",
            "review": [],
            "todo": [{
                "priority": "high",
                "title": "10 个订单待发货",
                "metrics": [{"key": "pending_ship_orders", "value": 10}],
            }],
            "risks": [],
            "suggestions": [],
        })
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = type("R", (), {"content": llm_output})()
        with patch("app.briefing.generator.LLMFactory") as factory:
            factory.create_briefing_llm.return_value = mock_llm
            result = await generate_briefing({"metrics": {"pending_ship_orders": 10}})

        assert result is not None
        assert result["summary"] == "昨日订单 5 单"
        assert len(result["todo"]) == 1

    @pytest.mark.asyncio
    async def test_empty_snapshot_returns_none(self):
        assert await generate_briefing({}) is None
        assert await generate_briefing(None) is None

    @pytest.mark.asyncio
    async def test_unparseable_llm_output_returns_none(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = type("R", (), {"content": "这不是 JSON"})()
        with patch("app.briefing.generator.LLMFactory") as factory:
            factory.create_briefing_llm.return_value = mock_llm
            result = await generate_briefing({"metrics": {"k": 1}})

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("LLM down")
        with patch("app.briefing.generator.LLMFactory") as factory:
            factory.create_briefing_llm.return_value = mock_llm
            result = await generate_briefing({"metrics": {"k": 1}})

        assert result is None


class TestPromptSecurity:
    """Prompt 组装安全：快照即输入，无 PII 拼接路径"""

    def test_system_prompt_forbids_fabrication(self):
        # 铁律必须显式声明「只允许使用快照数字」
        assert "只允许使用快照中出现的数字" in BRIEFING_SYSTEM_PROMPT
        assert "禁止编造" in BRIEFING_SYSTEM_PROMPT

    def test_snapshot_is_only_input(self):
        # 生成函数签名只有 snapshot，没有任何 PII 参数位
        import inspect
        sig = inspect.signature(generate_briefing)
        assert list(sig.parameters) == ["snapshot"]
