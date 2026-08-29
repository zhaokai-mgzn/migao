"""租户 AI 配置拉取与自动转人工关键词单元测试（app/agents/tenant_config.py）

覆盖：
- is_auto_handoff_trigger：命中/未命中关键词、JSON 字符串兼容、空配置
- get_tenant_ai_config：缓存命中、HTTP 失败降级空 dict
"""
# case_ids: SE-012

import pytest
from unittest.mock import AsyncMock, patch

from app.agents.tenant_config import (
    get_tenant_ai_config,
    clear_tenant_ai_config_cache,
    is_auto_handoff_trigger,
    is_after_hours,
)

from datetime import datetime


class TestAutoHandoffTrigger:
    def test_hit_keyword_returns_true(self):
        config = {"autoHandoffKeywords": ["老板", "投诉", "退款"]}
        assert is_auto_handoff_trigger("我要找老板", config) is True
        assert is_auto_handoff_trigger("这个质量问题我要投诉", config) is True

    def test_miss_returns_false(self):
        config = {"autoHandoffKeywords": ["老板", "投诉"]}
        assert is_auto_handoff_trigger("帮我算一下窗帘多少钱", config) is False

    def test_empty_config_returns_false(self):
        assert is_auto_handoff_trigger("我要找老板", {}) is False

    def test_json_string_keywords(self):
        config = {"autoHandoffKeywords": '["老板", "投诉"]'}
        assert is_auto_handoff_trigger("我要找老板", config) is True

    def test_empty_message_returns_false(self):
        config = {"autoHandoffKeywords": ["老板"]}
        assert is_auto_handoff_trigger("", config) is False


class TestGetTenantAiConfig:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_tenant_ai_config_cache()
        yield
        clear_tenant_ai_config_cache()

    async def test_fetch_success(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"botName": "小布", "autoHandoffKeywords": ["老板"]},
        })
        with patch("app.agents.tenant_config.get_admin_api_client", return_value=mock_client):
            config = await get_tenant_ai_config(1)
        assert config["botName"] == "小布"

    async def test_cache_hit_avoids_second_http(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"botName": "小布"},
        })
        with patch("app.agents.tenant_config.get_admin_api_client", return_value=mock_client):
            await get_tenant_ai_config(1)
            await get_tenant_ai_config(1)
        # 缓存命中：只调一次 HTTP
        assert mock_client.get.await_count == 1

    async def test_failure_returns_empty_dict(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("boom"))
        with patch("app.agents.tenant_config.get_admin_api_client", return_value=mock_client):
            config = await get_tenant_ai_config(1)
        assert config == {}


class TestAfterHours:
    def test_no_mode_returns_false(self):
        # 未配置 afterHoursMode → 正常转人工（不降级）
        assert is_after_hours({}) is False

    def test_within_hours_returns_false(self):
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": {"start": "09:00", "end": "18:00"},
            "afterHoursMessage": "已下班",
        }
        # 12:00 在营业时间内 → 不降级
        assert is_after_hours(config, now=datetime(2026, 8, 29, 12, 0)) is False

    def test_outside_hours_returns_true(self):
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": {"start": "09:00", "end": "18:00"},
            "afterHoursMessage": "已下班",
        }
        # 20:00 在营业时间外 → 降级
        assert is_after_hours(config, now=datetime(2026, 8, 29, 20, 0)) is True

    def test_no_hours_but_message_returns_true(self):
        # 配置了 afterHoursMode + afterHoursMessage 但没配具体时间 → 降级
        config = {"afterHoursMode": "auto_reply", "afterHoursMessage": "已下班"}
        assert is_after_hours(config) is True

    def test_json_string_hours(self):
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": '{"start": "09:00", "end": "18:00"}',
            "afterHoursMessage": "已下班",
        }
        assert is_after_hours(config, now=datetime(2026, 8, 29, 20, 0)) is True
