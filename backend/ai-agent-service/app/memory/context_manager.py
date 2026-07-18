"""
Agent Context Manager — 在 ReAct 循环前主动构建上下文注入 LLM。

设计原则：
1. 推理模型支持大上下文 → 宁可多塞，别漏信息
2. 上下文在 system prompt 之后、对话历史之前注入
3. 每个 skill 独立存储 entities，跨 skill 共享
"""

from typing import Dict, Optional
from collections import OrderedDict


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
    MAX_CONTEXT_LENGTH = 3000  # 字符

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
        """构建注入 LLM 的上下文字符串"""
        cache = self._get_or_create(session_id)
        parts = []

        # 1. 跨 skill 实体缓存
        entities = cache.get("entities", {})
        if entities:
            entity_lines = []
            for entity_type, items in entities.items():
                if not items:
                    continue
                label = {
                    "product_ids": "商品",
                    "order_nos": "订单",
                    "customer_ids": "客户",
                    "processing_item_ids": "加工项",
                }.get(entity_type, entity_type)

                item_strs = []
                for item in items[:3]:  # 每种实体最多 3 条
                    id_str = item.get("id") or item.get("no") or ""
                    name = item.get("name", "")
                    id_short = id_str[:12] + "..." if len(id_str) > 15 else id_str
                    item_strs.append(f"{name}({id_short})")
                entity_lines.append(f"- {label}: {', '.join(item_strs)}")

            if entity_lines:
                parts.append("## 已知实体（可复用 ID）\n" + "\n".join(entity_lines))

        # 2. 最近 tool 结果摘要
        tool_results = cache.get("tool_results", [])
        if tool_results:
            recent = tool_results[-5:]  # 最近 5 条
            lines = ["## 最近的工具调用\n"]
            for r in recent:
                tool = r.get("tool", "")
                ts = r.get("ts", 0)
                summary = r.get("summary", "")
                if summary:
                    lines.append(f"- [{tool}] {summary[:150]}")
            if len(lines) > 1:
                parts.append("\n".join(lines))

        # 3. 跨 skill 提示
        last_skill = cache.get("last_skill", "")
        if last_skill and last_skill != current_skill:
            parts.append(
                f"## 跨域提示\n"
                f"你刚从「{last_skill}」领域切换过来。上面的实体和工具结果来自上一个领域的操作，"
                f"可以直接复用其中的 ID，无需重新查询。"
            )

        context = "\n\n".join(parts)
        if context:
            context = context[: self.MAX_CONTEXT_LENGTH]
        return context

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
        """从 tool result 中自动提取实体 ID"""
        if "entities" not in cache:
            cache["entities"] = {}

        data = result.get("data") or {}
        entities = cache["entities"]

        # 从常见字段中提取 entities
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
                # 去重
                if not any(e.get("id") == eid or e.get("no") == eid for e in existing):
                    existing.append({"id": eid, "name": name, "source": tool_name})

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
