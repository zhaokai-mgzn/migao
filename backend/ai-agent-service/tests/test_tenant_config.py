"""租户 AI 配置拉取与自动转人工关键词单元测试（app/agents/tenant_config.py）

覆盖：
- is_auto_handoff_trigger：命中/未命中关键词、JSON 字符串兼容、空配置
- get_tenant_ai_config：缓存命中、HTTP 失败降级空 dict
"""
# case_ids: ST-008

import pytest
from unittest.mock import AsyncMock, patch

from app.agents.tenant_config import (
    get_tenant_ai_config,
    clear_tenant_ai_config_cache,
    is_auto_handoff_trigger,
    is_after_hours,
)

from datetime import datetime, timezone


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

    # ═══ 时区缺陷回归（生产实测：tenant1 上海 10:16 被误判非营业）═══
    # 业务时间按租户配置 timezone（Asia/Shanghai）解读；now 为 UTC 时须先转换。
    # 生产现象：容器默认 UTC，上海 10:16 = UTC 02:16，落在 09:00-18:00 外 → 误降级。

    def test_shanghai_business_hours_with_utc_now(self):
        """UTC 02:16 = 上海 10:16（配置 timezone=Asia/Shanghai）→ 营业中，不降级"""
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": {"start": "09:00", "end": "18:00"},
            "afterHoursMessage": "已下班",
            "timezone": "Asia/Shanghai",
        }
        # UTC 02:16 对应上海 10:16，应在营业时间内
        utc_now = datetime(2026, 8, 29, 2, 16, tzinfo=timezone.utc)
        assert is_after_hours(config, now=utc_now) is False

    def test_shanghai_after_hours_with_utc_now(self):
        """UTC 14:00 = 上海 22:00 → 营业外，降级"""
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": {"start": "09:00", "end": "18:00"},
            "afterHoursMessage": "已下班",
            "timezone": "Asia/Shanghai",
        }
        utc_now = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
        assert is_after_hours(config, now=utc_now) is True

    def test_naive_now_interpreted_as_tenant_timezone(self):
        """无时区 now（老测试注入方式）按租户时区解读：上海 12:00 营业中"""
        config = {
            "afterHoursMode": "auto_reply",
            "businessHours": {"start": "09:00", "end": "18:00"},
            "afterHoursMessage": "已下班",
            "timezone": "Asia/Shanghai",
        }
        assert is_after_hours(config, now=datetime(2026, 8, 29, 12, 0)) is False
