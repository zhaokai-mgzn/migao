"""
租户 AI 配置拉取（带缓存）

统一从 admin-api 拉取 TenantAiConfig（机器人设置），供小布 agent 各节点使用：
- autoHandoffKeywords：自动转人工关键词
- afterHoursMode / afterHoursMessage：非营业时间处理
- emotionHandoff / recommendStrategy 等（后续扩展）

缓存 60 秒，避免每次对话都打 admin-api。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from app.utils.http_client import get_admin_api_client

# tenant_id -> (fetch_timestamp, config_dict)
_cache: Dict[int, tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 60.0


async def get_tenant_ai_config(tenant_id: int) -> Dict[str, Any]:
    """拉取租户 AI 配置（带 60s 缓存）。失败返回空 dict（不抛异常，静默降级）。"""
    now = time.time()
    cached = _cache.get(tenant_id)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/tenant/ai-config", tenant_id=tenant_id
        )
        if response.get("success") and response.get("data"):
            config = response["data"]
            _cache[tenant_id] = (now, config)
            return config
        logger.warning(
            f"[tenant-config] 租户 AI 配置为空 | tenant={tenant_id} "
            f"success={response.get('success')}"
        )
    except Exception as e:
        logger.warning(
            f"[tenant-config] 拉取租户 AI 配置失败 | tenant={tenant_id} "
            f"error={type(e).__name__}: {e}"
        )

    return {}


def clear_tenant_ai_config_cache() -> None:
    """清空缓存（测试用）"""
    _cache.clear()


def _normalize_keywords(raw: Any) -> list[str]:
    """规范化 autoHandoffKeywords：兼容 list / JSON 字符串。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    return [str(kw).strip() for kw in raw if kw and str(kw).strip()]


def is_auto_handoff_trigger(message: str, config: Dict[str, Any]) -> bool:
    """判断用户消息是否命中商家配置的自动转人工关键词。

    Args:
        message: 用户消息文本
        config: 租户 AI 配置 dict（get_tenant_ai_config 返回）

    Returns:
        True 表示应自动转人工
    """
    if not message:
        return False
    keywords = _normalize_keywords(config.get("autoHandoffKeywords"))
    return any(kw in message for kw in keywords)


def _coerce_hours(raw: Any) -> Dict[str, Any]:
    """规范化 businessHours：兼容 dict / JSON 字符串。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def is_after_hours(config: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """判断当前是否非营业时间（转人工应降级为 afterHoursMessage）。

    业务语义（重要）：非营业时间 AI 机器人照常服务（算料/查单/咨询不受影响），
    仅「转人工」降级——没有坐席在线，返回 afterHoursMessage 引导留言。

    生效条件：afterHoursMode 有值（如 "auto_reply"）。
    时间判断：businessHours 支持 {"start": "09:00", "end": "18:00"}（每天相同）。
    未配置具体时间但配置了 afterHoursMessage → 视为非营业（降级）。

    Args:
        config: 租户 AI 配置 dict
        now: 当前时间（测试注入用，默认 datetime.now()）

    Returns:
        True 表示转人工应降级
    """
    mode = config.get("afterHoursMode")
    if not mode:
        return False

    hours = _coerce_hours(config.get("businessHours"))
    start = hours.get("start")
    end = hours.get("end")

    # 配置了 afterHoursMode 但没配具体营业时间：有 afterHoursMessage 就降级
    if not start or not end:
        return bool(config.get("afterHoursMessage"))

    now = now or datetime.now()
    current = now.strftime("%H:%M")
    return not (start <= current <= end)
