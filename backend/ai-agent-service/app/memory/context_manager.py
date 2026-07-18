"""
Agent Context Manager — 在 ReAct 循环前主动构建上下文注入 LLM。

设计原则：
1. 推理模型支持大上下文 → 宁可多塞，别漏信息
2. 上下文在 system prompt 之后、对话历史之前注入
3. 每个 skill 独立存储 entities，跨 skill 共享
"""

import json
import time as _time
from typing import Dict, Optional
from collections import OrderedDict
from loguru import logger

_ = _time  # suppress unused import warning, used in _summarize_result via __import__


class AgentContextManager:
    """管理跨轮、跨 skill 的上下文数据。

    存储结构（内存 + Redis 持久化）：
    {
        "entities": {
            "product_ids": [{"id": "xxx", "name": "遮光窗帘", "source": "product_search"}],
            "order_nos": [{"no": "ORD-xxx", "id": "uuid-xxx", "source": "order_query"}],
            "customer_ids": [{"id": "xxx", "name": "张三", "source": "customer_manage"}],
        },
        "tool_results": [
            {"tool": "product_search", "data": {...}, "ts": 1234567890},
        ],
        "last_skill": "product",
    }
    """

    MAX_ENTITIES = 10
    MAX_TOOL_RESULTS = 8
    MAX_CONTEXT_LENGTH = 800

    # Tool hints: 每个 skill 最常用的工具，减少 LLM 试错
    SKILL_TOOL_HINTS = {
        "product": "product_search(查) → product_detail(详情+SKU) → product_manage(创建/修改) → product_processing_item_manage(加工项关联)",
        "order": "order_query(查) → order_create(新建,先调product_detail选SKU) → order_manage(改状态/发货/取消)",
        "aftersales": "aftersale_query(查) → aftersale_create(新建工单) → after_sales_manage(处理)",
        "customer": "customer_manage(list查→detail详情→update更新)",
        "staff": "employee_manage(list查→detail详情→create新增)",
        "settings": "settings_manage(get查→update改) | quick_reply_manage | notification_manage",
        "data": "dashboard_stats(今日概览/趋势/分布)",
        "general": "product_search | order_query | customer_manage | 不明确时先用查询工具摸底",
    }

    def __init__(self):
        # 内存缓存（同 session 内共享）
        self._cache: Dict[str, OrderedDict] = {}

    # ── 写入 ──

    def record_tool_result(self, session_id: str, tool_name: str, result: dict) -> None:
        """记录一次 tool 调用结果"""
        cache = self._get_or_create(session_id)
        if "tool_results" not in cache:
            cache["tool_results"] = []

        # 只存关键字段，避免塞入大 JSON
        summary = self._summarize_result(tool_name, result)
        if summary:
            cache["tool_results"].append(summary)
            if len(cache["tool_results"]) > self.MAX_TOOL_RESULTS:
                cache["tool_results"].pop(0)

        # 自动提取 entities
        self._extract_entities(cache, tool_name, result)

    def set_last_skill(self, session_id: str, skill_name: str) -> None:
        """记录当前 skill"""
        cache = self._get_or_create(session_id)
        cache["last_skill"] = skill_name

    # ── 读取 ──

    def build_context(self, session_id: str, current_skill: str) -> str:
        """构建注入 LLM 的上下文字符串。

        参考 Claude Code 模式：放在 system prompt 和对话历史之间，
        作为独立逻辑块。精简如 CLAUDE.md（800 字符以内）。
        """
        cache = self._get_or_create(session_id)
        lines = []

        # 1. 已知实体 — 直接给 UUID，不啰嗦
        entities = cache.get("entities", {})
        if entities:
            lines.append("## 已知实体（直接复用 ID，禁止重新查询）")
            for entity_type, items in entities.items():
                if not items:
                    continue
                label = {"product_ids": "商品", "order_nos": "订单",
                         "customer_ids": "客户", "processing_item_ids": "加工项"}\
                        .get(entity_type, entity_type)
                item_strs = []
                for item in items[:3]:
                    eid = (item.get("id") or item.get("no") or "")[:20]
                    name = item.get("name", "")
                    item_strs.append(f"{name}={eid}")
                lines.append(f"{label}: {' | '.join(item_strs)}")

        # 2. Vision/图片识别结果
        vision = cache.get("vision_fields", {})
        if vision:
            parts = []
            if vision.get("name"):
                parts.append(f"商品名: {vision['name']}")
            for field in ("colors", "selling_methods", "door_widths", "specifications", "price"):
                val = vision.get(field)
                if val:
                    parts.append(f"{field}: {json.dumps(val, ensure_ascii=False)}")
            if parts:
                lines.append("图片识别: " + " | ".join(parts))

        # 3. 跨域切换提示 — 一行
        last_skill = cache.get("last_skill", "")
        if last_skill and last_skill != current_skill:
            lines.append(f"刚离开「{last_skill}」，上面实体可直接复用。")

        # 3. Tool hints — 告诉 LLM 当前领域该用什么工具
        hint = self.SKILL_TOOL_HINTS.get(current_skill)
        if hint:
            lines.append(f"工具链: {hint}")

        # 4. 最近 tool 摘要 — 只保留关键统计
        tool_results = cache.get("tool_results", [])
        if tool_results:
            recent = tool_results[-3:]
            for r in recent:
                summary = r.get("summary", "")
                if summary:
                    lines.append(summary[:120])

        context = "\n".join(lines)
        if len(context) > self.MAX_CONTEXT_LENGTH:
            context = context[:self.MAX_CONTEXT_LENGTH]
        return context

    # ── Redis 持久化 ──

    async def save(self, session_id: str) -> None:
        """持久化到 Redis，跨 SAE 实例共享"""
        try:
            from app.utils.redis_client import get_redis
            redis = get_redis()
            if redis and session_id in self._cache:
                key = f"ctx:{session_id}"
                await redis.set(key, json.dumps(self._cache[session_id], ensure_ascii=False, default=str), ex=3600)
        except Exception as e:
            logger.warning(f"[ctx-mgr] Redis save failed: {e}")

    async def load(self, session_id: str) -> None:
        """从 Redis 恢复"""
        try:
            from app.utils.redis_client import get_redis
            redis = get_redis()
            if redis:
                key = f"ctx:{session_id}"
                data = await redis.get(key)
                if data:
                    self._cache[session_id] = json.loads(data)
        except Exception as e:
            logger.warning(f"[ctx-mgr] Redis load failed: {e}")

    # ── 内部 ──

    def _get_or_create(self, session_id: str) -> OrderedDict:
        if session_id not in self._cache:
            self._cache[session_id] = OrderedDict()
        if len(self._cache) > 100:
            self._cache.pop(next(iter(self._cache)))
        return self._cache[session_id]

    def _summarize_result(self, tool_name: str, result: dict) -> Optional[dict]:
        """从 tool result 提取关键摘要"""
        data = result.get("data") or {}
        summary_text = result.get("message", "")[:200]

        summary = {
            "tool": tool_name,
            "summary": summary_text,
            "ts": __import__("time").time(),
        }

        # 提取关键统计
        for key in ("total", "page", "size", "total_pages"):
            if key in data:
                summary[key] = data[key]

        return summary

    def _extract_entities(self, cache: OrderedDict, tool_name: str, result: dict) -> None:
        """从 tool result 中自动提取实体 ID 和结构化字段"""
        if "entities" not in cache:
            cache["entities"] = {}
        if "vision_fields" not in cache:
            cache["vision_fields"] = {}

        data = result.get("data") or {}
        entities = cache["entities"]
        vision = cache["vision_fields"]

        # 1. 常规实体提取
        for list_key, entity_type, id_field, name_field in [
            ("products", "product_ids", "id", "name"),
            ("items", "processing_item_ids", "id", "name"),
            ("orders", "order_nos", "id", "order_no"),
            ("customers", "customer_ids", "id", "name"),
        ]:
            items = data.get(list_key, [])
            if not isinstance(items, list):
                items = [items] if isinstance(items, dict) else []

            for item in items[:5]:
                if not isinstance(item, dict):
                    continue
                eid = item.get(id_field, "")
                name = item.get(name_field, "")
                if not eid:
                    continue

                existing = entities.setdefault(entity_type, [])
                if not any(e.get("id") == eid or e.get("no") == eid for e in existing):
                    existing.append({"id": eid, "name": name, "source": tool_name})

        # 2. Vision/图片识别结果提取（product_manage create 成功后）
        if tool_name == "product_manage" and result.get("success"):
            product_data = data.get("product") or data
            if isinstance(product_data, dict):
                vision["name"] = product_data.get("name", vision.get("name", ""))
                for field in ("colors", "selling_methods", "door_widths",
                              "specifications", "description", "price"):
                    val = product_data.get(field)
                    if val:
                        vision[field] = val

        # 3. product_detail 返回的单条记录
        if tool_name == "product_detail" and result.get("success"):
            product = data if isinstance(data, dict) else {}
            if product:
                vision["name"] = product.get("name", vision.get("name", ""))
                for field in ("specifications", "category_name", "price", "status"):
                    val = product.get(field)
                    if val:
                        vision[field] = val

        # 限制每类实体的数量
        for key in entities:
            if len(entities[key]) > self.MAX_ENTITIES:
                entities[key] = entities[key][-self.MAX_ENTITIES:]


# 全局单例
_context_manager: Optional[AgentContextManager] = None


def get_context_manager() -> AgentContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = AgentContextManager()
    return _context_manager
