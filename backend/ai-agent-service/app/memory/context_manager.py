"""
Agent Context Manager — 在 ReAct 循环前主动构建上下文注入 LLM。

设计原则：
1. 推理模型支持大上下文 → 宁可多塞，别漏信息
2. 上下文在 system prompt 之后、对话历史之前注入
3. 每个 skill 独立存储 entities，跨 skill 共享
"""

import json
import time as _time
from typing import Dict, List, Optional
from collections import OrderedDict
from loguru import logger

from app.memory.session_state_store import SessionStateStore

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

    # 域分桶映射：entity 类型 → 归属域（主题域隔离 T1 依据）
    # 同一实体类型固定属于一个域；域切换时只重置当前域，不误伤其他域
    ENTITY_DOMAIN = {
        "order_nos": "order",
        "product_ids": "product",
        "processing_item_ids": "product",
        "customer_ids": "customer",
        "aftersale_nos": "aftersales",
    }

    # 记录每个 entity 的域归属（_extract_entities 时写入 {entity_type: {id: domain}}）
    # 用于 reset_domain 精确清空指定域的实体
    DOMAIN_INDEX_KEY = "_domain_index"

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
        # 内存缓存：key = user_id（跨 session 共享）
        self._cache: Dict[str, OrderedDict] = {}
        # user_id → session_id 映射，用于找回最近 session 的数据
        self._user_session_map: Dict[str, str] = {}

    # ── 写入 ──

    def record_tool_result(self, session_id: str, tool_name: str, result: dict) -> None:
        """记录一次 tool 调用结果"""
        cache = self._get_or_create(session_id)
        if "tool_results" not in cache:
            cache["tool_results"] = []

        # 只存关键字段，避免塞入大 JSON
        summary = self._summarize_result(tool_name, result)
        if summary:
            # 记录工具结果归属域（T1 切域后按域过滤，不注入旧域摘要）
            summary["domain"] = self._tool_domain(tool_name)
            cache["tool_results"].append(summary)
            if len(cache["tool_results"]) > self.MAX_TOOL_RESULTS:
                cache["tool_results"].pop(0)

        # 自动提取 entities
        self._extract_entities(cache, tool_name, result)

    def record_vision_candidates(
        self, session_id: str, entity_type: str, candidates: List[dict]
    ) -> None:
        """记录 vision 分析识别出的候选实体到上下文实体槽（issue #2821 切片 2）

        图片链路 grounding 关键一步：vision 分析结果写入实体槽后，
        build_context 跨轮注入「图片关联对象」——澄清卡候选 grounded 到商户对象
        有了代码层保障（G10 修复）。

        Args:
            session_id: 会话 ID
            entity_type: 实体类型，必须 ∈ ENTITY_DOMAIN（order_nos/product_ids/
                         processing_item_ids/customer_ids/aftersale_nos）
            candidates: 候选实体列表，每项含 id/name，如
                        [{"id": "sku-1", "name": "雪尼尔遮光窗帘"}]

        Raises:
            ValueError: entity_type 不在 ENTITY_DOMAIN 中
        """
        if entity_type not in self.ENTITY_DOMAIN:
            raise ValueError(
                f"非法实体类型 {entity_type}，合法值: {sorted(self.ENTITY_DOMAIN)}"
            )
        cache = self._get_or_create(session_id)
        if "entities" not in cache:
            cache["entities"] = {}
        entities = cache["entities"]

        existing = entities.setdefault(entity_type, [])
        for cand in candidates or []:
            if not isinstance(cand, dict):
                continue
            eid = cand.get("id") or cand.get("no") or ""
            name = cand.get("name", "")
            if not eid:
                continue
            if any(e.get("id") == eid or e.get("no") == eid for e in existing):
                continue
            existing.append({"id": eid, "name": name, "source": "vision"})
            # 记录实体域归属（与 _extract_entities 一致，供 reset_domain 精确清空）
            domain = self.ENTITY_DOMAIN.get(entity_type)
            if domain:
                idx = cache.setdefault(self.DOMAIN_INDEX_KEY, {})
                idx.setdefault(entity_type, {})[eid] = domain

        # 限制每类实体数量（与 _extract_entities 一致）
        if len(existing) > self.MAX_ENTITIES:
            del existing[: len(existing) - self.MAX_ENTITIES]

    def record_vision_analysis(self, session_id: str, analysis_text: str) -> None:
        """记录 vision 分析全文到上下文槽（issue #2821 延续切片 C）

        与 record_vision_candidates（结构化候选实体）互补：本方法保留分析原文，
        build_context 跨 skill 注入「用户上轮发了图，识别结果为 X」——
        图片关联对象（商品/订单/客户）有跨 skill 召回保障（G10 收口）。

        Args:
            session_id: 会话 ID
            analysis_text: vision 分析文本；空文本不落槽（不产生噪音）
        """
        if not session_id or not analysis_text:
            return
        cache = self._get_or_create(session_id)
        cache["vision_analysis"] = analysis_text

    def set_last_skill(self, session_id: str, skill_name: str) -> None:
        """记录当前 skill"""
        cache = self._get_or_create(session_id)
        cache["last_skill"] = skill_name

    def get_entities(self, session_id: str) -> Dict:
        """获取会话已记录的实体（跨轮复用），供意图分类器等消费。

        返回 {entity_type: [{id/name/...}, ...]}，无实体时返回空 dict。
        调用前需先 await load(session_id) 从 Redis 恢复跨实例数据。
        """
        cache = self._get_or_create(session_id)
        return cache.get("entities", {})

    # ── 上下文自动清理（T1/T2/T3，见 xiaobu-c-end-redesign.md §4.2）──

    def record_domain_switch(self, session_id: str, current_skill: str) -> None:
        """T1 主题域切换：将旧域实体标 stale，防止跨域污染。

        - 同域（last_skill == current_skill）：no-op
        - 异域：把非当前域的实体标记 stale（不移除——支持"回到刚才话题"回溯名称）
        - build_context 只注入当前域实体 + 最近 1 个 stale 域的名称索引（不带 ID）
        """
        cache = self._get_or_create(session_id)
        last_skill = cache.get("last_skill", "")
        if not last_skill or last_skill == current_skill:
            return
        # 记录 stale 域（保留名称索引供回溯），并标记非当前域实体
        stale_domains = set(cache.get("_stale_domains", []))
        stale_domains.add(last_skill)
        cache["_stale_domains"] = list(stale_domains)
        cache["_current_domain"] = current_skill

    def reset_domain(self, session_id: str, domain: str) -> None:
        """T2 事务终态：清空指定域全部会话级状态（草稿/实体/tool_results/pending）。

        被 terminal tool（order_create/aftersale_create/human_handoff 成功）触发。
        其他域状态保留（product 域的推荐结果不受下单影响）。
        """
        cache = self._get_or_create(session_id)
        entities = cache.get("entities", {})
        domain_index = cache.get(self.DOMAIN_INDEX_KEY, {})
        # 清空属于该域的实体类型
        for etype, edomain in self.ENTITY_DOMAIN.items():
            if edomain == domain:
                entities.pop(etype, None)
        # 清空该域的工具结果（tool_results 里记录 tool 名，按域过滤）
        domain_tools = self._domain_tools(domain)
        if cache.get("tool_results"):
            cache["tool_results"] = [
                r for r in cache["tool_results"]
                if r.get("tool") not in domain_tools
            ]
        # 当前域完成：移除 last_skill（避免残留导致下轮误判同域）
        if cache.get("last_skill") == domain:
            cache.pop("last_skill", None)
        cache.pop("_current_domain", None)
        # 从 stale 集合中移除已重置的域
        if cache.get("_stale_domains"):
            cache["_stale_domains"] = [d for d in cache["_stale_domains"] if d != domain]

    def reset_session(self, session_id: str) -> None:
        """T4/T3b：完整清空会话级状态（新对话/长空闲）。

        仅清 L2（entities/tool_results/last_skill/vision），
        不动对话历史（L3）与用户级记忆（L1，由调用方决定）。
        """
        cache = self._get_or_create(session_id)
        for key in ("entities", "tool_results", "last_skill", "vision_fields",
                    "_stale_domains", "_current_domain", self.DOMAIN_INDEX_KEY):
            cache.pop(key, None)

    def decay_tool_state(self, session_id: str) -> None:
        """T3a 短空闲（15min）：清工具结果缓存，保留实体与历史供续聊。

        工具缓存失效 → 下轮 LLM 重新查询获取最新数据（避免用过期结果应答）。
        """
        cache = self._get_or_create(session_id)
        cache.pop("tool_results", None)

    # ── 读取 ──

    def build_context(self, session_id: str, current_skill: str) -> str:
        """构建注入 LLM 的上下文字符串。

        参考：放在 system prompt 和对话历史之间，
        作为独立逻辑块。精简至 800 字符以内。
        """
        cache = self._get_or_create(session_id)
        lines = []

        # 1. 已知实体 — 按当前域过滤注入（T1：切域后旧域实体不注入，防跨域污染）
        entities = cache.get("entities", {})
        current_domain = cache.get("_current_domain", "")
        stale_domains = set(cache.get("_stale_domains", []))
        active_entities = {}
        for etype, items in entities.items():
            edomain = self.ENTITY_DOMAIN.get(etype)
            # 当前域或未分类的实体注入；stale 域实体只留名称索引
            if edomain in stale_domains and edomain != current_domain:
                continue
            active_entities[etype] = items
        if active_entities:
            header = "🔴 以下 ID 在之前的对话中已获取，直接复用，禁止重新查询："
            lines.append(header)
            for entity_type, items in active_entities.items():
                if not items:
                    continue
                label = {"product_ids": "商品 UUID", "order_nos": "订单 UUID",
                         "customer_ids": "客户 UUID", "processing_item_ids": "加工项 UUID"}\
                        .get(entity_type, entity_type)
                item_strs = []
                for item in items[:3]:
                    eid = (item.get("id") or item.get("no") or "")
                    name = item.get("name", "")
                    item_strs.append(f"  {label} → {name} = {eid}")
                lines.append("\n".join(item_strs))

        # 1.5 主题域切换提示（T1）：告诉 LLM 上一话题已归档
        if stale_domains and current_domain:
            domain_label = {"order": "订单", "product": "商品",
                            "aftersales": "售后", "customer": "客户"}.get(current_domain, current_domain)
            lines.append(f"【话题已切换】当前话题为「{domain_label}」；上一话题的上下文已归档，若用户回到原话题请重新查询。")

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

        # 2.5 vision 分析全文（切片 C：跨 skill 召回「用户上轮发了图，识别结果为 X」）
        vision_analysis = cache.get("vision_analysis", "")
        if vision_analysis:
            lines.append(f"图片分析: {vision_analysis[:self.MAX_CONTEXT_LENGTH]}")

        # 3. 跨域切换提示 — 一行
        last_skill = cache.get("last_skill", "")
        if last_skill and last_skill != current_skill:
            lines.append(f"刚离开「{last_skill}」，上面实体可直接复用。")

        # 3. Tool hints — 告诉 LLM 当前领域该用什么工具
        hint = self.SKILL_TOOL_HINTS.get(current_skill)
        if hint:
            lines.append(f"工具链: {hint}")

        # 4. 最近 tool 摘要 — 只保留关键统计（T1：切域后只注入当前域摘要）
        tool_results = cache.get("tool_results", [])
        stale_domains_tool = stale_domains  # 复用上方 stale 集合
        if tool_results:
            current_domain_tools = self._domain_tools(current_domain) if current_domain else None
            recent = tool_results[-3:]
            for r in recent:
                # 若已切域：跳过旧域摘要，避免"找到1个订单"污染商品话题
                if current_domain_tools is not None and r.get("domain") != current_domain:
                    continue
                summary = r.get("summary", "")
                if summary:
                    lines.append(summary[:120])

        context = "\n".join(lines)
        if len(context) > self.MAX_CONTEXT_LENGTH:
            context = context[:self.MAX_CONTEXT_LENGTH]
        return context

    # ── 对话摘要（压缩长上下文）──

    async def compress_conversation(
        self, session_id: str, messages: list, max_recent: int = 12
    ) -> str:
        """压缩长对话：保留最近 N 条消息，更早的生成结构化摘要。

        参考 Claude Code 的滚动摘要机制：
        - 最近 12 条消息完整保留
        - 更早的总结成要点列表（用户意图、已完成操作、当前状态）

        Returns:
            压缩后的摘要文本，追加在 system prompt 末尾
        """
        if len(messages) <= max_recent:
            return ""

        old_msgs = messages[:-max_recent]

        # 从旧消息中提取关键信息
        entities = self._cache.get(session_id, {}).get("entities", {})
        vision = self._cache.get(session_id, {}).get("vision_fields", {})

        lines = ["## 对话历史摘要（早期消息已压缩）"]

        # 用户意图轨迹
        user_msgs = [m for m in old_msgs if hasattr(m, 'type') and m.type == 'human']
        if user_msgs:
            intents = []
            for m in user_msgs[-5:]:
                content = getattr(m, 'content', '') or ''
                if len(content) > 60:
                    content = content[:60] + "..."
                intents.append(content)
            lines.append("用户意图: " + " → ".join(intents))

        # 已完成的实体操作
        if entities:
            for etype, items in entities.items():
                label = {"product_ids": "查过商品", "order_nos": "查过订单",
                         "customer_ids": "查过客户"}.get(etype, etype)
                names = [f"{i.get('name','')}({i.get('id','')[:8]}...)" for i in items[:3]]
                lines.append(f"{label}: {', '.join(names)}")

        # Vision 结果
        if vision and vision.get("name"):
            lines.append(f"图片商品: {vision['name']}")

        return "\n".join(lines)

    # ── 持久化（经 SessionStateStore，会话管理重构 P1）──
    #
    # 跨轮工作状态统一存于 PG session_states 表（SessionStateStore 深模块）。
    # save/load 采用合并语义：先读已有状态，再并入本模块维护的字段
    # （entities / tool_results / last_skill / vision_fields），不覆盖其它字段
    # （如 pending_skill，未来也可能入同一状态）。

    async def save(self, session_id: str) -> None:
        """持久化当前缓存到 SessionStateStore（合并语义）"""
        try:
            store = SessionStateStore()
            existing = await store.load(session_id) or {}
            if session_id in self._cache:
                existing.update(self._cache[session_id])
            await store.commit(session_id, existing)
        except Exception as e:
            logger.warning(f"[ctx-mgr] save failed: {e}")

    async def load(self, session_id: str) -> None:
        """从 SessionStateStore 恢复缓存（不覆盖已存在的内存状态）"""
        try:
            store = SessionStateStore()
            data = await store.load(session_id)
            if data and session_id not in self._cache:
                self._cache[session_id] = OrderedDict(data)
        except Exception as e:
            logger.warning(f"[ctx-mgr] load failed: {e}")

    # ── 内部 ──

    def _domain_tools(self, domain: str) -> set:
        """返回某域的工具名集合（tool_results 按工具名归属域）"""
        mapping = {
            "order": {"order_query", "customer_order_query", "order_create", "order_manage", "logistics_track", "customer_logistics_track"},
            "product": {"product_search", "product_detail", "product_manage", "product_update",
                        "sku_update", "curtain_calc", "processing_item_query", "processing_item_manage"},
            "aftersales": {"aftersale_query", "aftersale_create", "after_sales_manage"},
            "customer": {"customer_manage"},
        }
        return mapping.get(domain, set())

    def _tool_domain(self, tool_name: str) -> str:
        """反查工具名归属域（默认 general）"""
        for domain, tools in {
            "order": {"order_query", "customer_order_query", "order_create", "order_manage", "logistics_track", "customer_logistics_track"},
            "product": {"product_search", "product_detail", "product_manage", "product_update",
                        "sku_update", "curtain_calc", "processing_item_query", "processing_item_manage"},
            "aftersales": {"aftersale_query", "aftersale_create", "after_sales_manage"},
            "customer": {"customer_manage"},
        }.items():
            if tool_name in tools:
                return domain
        return "general"

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
        # 生产缺陷（线上 sess_60238786c0694dbc 实证）：售后工单列表/订单列表等
        # 也返回 data.items（工单/订单 id 无 name），泛化抽取把工单 UUID 误记为
        # 空名加工项实体，污染商品录入等流程的加工项上下文。
        # 因此 items → processing_item_ids 仅限加工项域工具。
        PROCESSING_ITEM_TOOLS = {"processing_item_query", "processing_item_manage"}
        for list_key, entity_type, id_field, name_field, allowed_tools in [
            ("products", "product_ids", "id", "name", None),
            ("items", "processing_item_ids", "id", "name", PROCESSING_ITEM_TOOLS),
            ("orders", "order_nos", "id", "order_no", None),
            ("customers", "customer_ids", "id", "name", None),
        ]:
            if allowed_tools is not None and tool_name not in allowed_tools:
                continue
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
                    # 记录实体域归属（供 reset_domain 精确清空）
                    domain = self.ENTITY_DOMAIN.get(entity_type)
                    if domain:
                        idx = cache.setdefault(self.DOMAIN_INDEX_KEY, {})
                        idx.setdefault(entity_type, {})[eid] = domain

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
