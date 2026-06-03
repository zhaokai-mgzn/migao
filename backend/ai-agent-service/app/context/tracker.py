"""
AI 智能客服系统 - 对话上下文追踪器

功能：
- 实体提取（订单号、手机号、商品名等）
- 对话状态追踪（阶段 + 意图链）
- 上下文摘要生成（注入到 System Prompt）
- 指代消解（"那个订单"→ 具体订单号）
- 对话历史压缩（超长对话自动摘要）
"""

import re
import json
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from loguru import logger
from langchain_openai import ChatOpenAI


# DashScope OpenAI 兼容接口地址
DASHSCOPE_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


class ConversationStage(str, Enum):
    """对话阶段"""
    INITIAL = "initial"           # 初始 / 问候
    QUERYING = "querying"         # 查询中（用户正在咨询）
    CONFIRMING = "confirming"     # 确认中（写操作前的确认）
    PROCESSING = "processing"     # 处理中（正在执行操作）
    COMPLETED = "completed"       # 已完成（本轮任务结束）


# ---------- 正则规则 ----------

# 订单号：常见格式 ORD-xxx / SO20250503xxx / 纯数字长串
ORDER_NO_PATTERNS = [
    re.compile(r"(?:订单号?|单号|order)[\uff1a:\s是为]*([A-Za-z0-9\-]{6,32})", re.IGNORECASE),
    re.compile(r"\b(ORD[-_]?\d{6,20})\b", re.IGNORECASE),
    re.compile(r"\b(SO\d{10,20})\b", re.IGNORECASE),
]

# 手机号
PHONE_PATTERN = re.compile(r"(?:手机号?|电话|联系方式)[：:\s]*(1[3-9]\d{9})\b")
PHONE_STANDALONE = re.compile(r"\b(1[3-9]\d{9})\b")

# 金额
AMOUNT_PATTERN = re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)")

# 商品 ID
PRODUCT_ID_PATTERN = re.compile(r"(?:商品|产品)\s*(?:ID|编号|id)[：:\s]*(\d+)")

# 指代词
PRONOUN_PATTERN = re.compile(r"(?:那个|这个|它|它的|这笔|那笔|上面的|之前的|刚才的)")


@dataclass
class ExtractedEntities:
    """已提取的实体集合"""
    order_nos: List[str] = field(default_factory=list)
    phone_numbers: List[str] = field(default_factory=list)
    product_names: List[str] = field(default_factory=list)
    product_ids: List[str] = field(default_factory=list)
    amounts: List[str] = field(default_factory=list)
    custom: Dict[str, Any] = field(default_factory=dict)

    def _add_unique(self, lst: list, value: str) -> None:
        if value and value not in lst:
            lst.append(value)

    def add_order_no(self, v: str) -> None:
        self._add_unique(self.order_nos, v)

    def add_phone(self, v: str) -> None:
        self._add_unique(self.phone_numbers, v)

    def add_product_name(self, v: str) -> None:
        self._add_unique(self.product_names, v)

    def add_product_id(self, v: str) -> None:
        self._add_unique(self.product_ids, v)

    def add_amount(self, v: str) -> None:
        self._add_unique(self.amounts, v)

    def is_empty(self) -> bool:
        return not (
            self.order_nos or self.phone_numbers or self.product_names
            or self.product_ids or self.amounts or self.custom
        )

    def to_summary_str(self) -> str:
        """生成简洁的实体摘要"""
        parts: list[str] = []
        if self.order_nos:
            parts.append(f"订单号: {', '.join(self.order_nos)}")
        if self.phone_numbers:
            parts.append(f"手机号: {', '.join(self.phone_numbers)}")
        if self.product_names:
            parts.append(f"商品: {', '.join(self.product_names)}")
        if self.product_ids:
            parts.append(f"商品ID: {', '.join(self.product_ids)}")
        if self.amounts:
            parts.append(f"金额: {', '.join(self.amounts)}")
        for k, v in self.custom.items():
            parts.append(f"{k}: {v}")
        return "; ".join(parts) if parts else "无"

    def get_latest_entity_for_pronoun(self) -> Optional[str]:
        """获取最近一个实体，用于指代消解"""
        if self.order_nos:
            return f"订单 {self.order_nos[-1]}"
        if self.product_names:
            return f"商品「{self.product_names[-1]}」"
        if self.product_ids:
            return f"商品(ID:{self.product_ids[-1]})"
        return None


class ConversationTracker:
    """
    对话上下文追踪器

    按 session_id 维护每个会话的：
    - 已提取实体 (ExtractedEntities)
    - 对话阶段 (ConversationStage)
    - 意图链 (intent_chain)

    使用内存 dict 存储（同进程生命周期内有效），
    可扩展为 Redis 存储。
    """

    def __init__(self):
        # session_id → 上下文状态
        self._states: Dict[str, Dict[str, Any]] = {}

    # ========== 状态管理 ==========

    def _get_state(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._states:
            self._states[session_id] = {
                "entities": ExtractedEntities(),
                "stage": ConversationStage.INITIAL,
                "intent_chain": [],
            }
        return self._states[session_id]

    def get_entities(self, session_id: str) -> ExtractedEntities:
        return self._get_state(session_id)["entities"]

    def get_stage(self, session_id: str) -> ConversationStage:
        return self._get_state(session_id)["stage"]

    def get_intent_chain(self, session_id: str) -> List[str]:
        return self._get_state(session_id)["intent_chain"]

    # ========== 实体提取 ==========

    def extract_entities_from_text(self, session_id: str, text: str) -> ExtractedEntities:
        """
        从文本中提取结构化实体（正则匹配）

        Args:
            session_id: 会话 ID
            text: 用户消息文本

        Returns:
            当前会话的全量实体集合
        """
        entities = self.get_entities(session_id)

        # 订单号
        for pat in ORDER_NO_PATTERNS:
            for m in pat.finditer(text):
                entities.add_order_no(m.group(1))

        # 手机号
        for m in PHONE_PATTERN.finditer(text):
            entities.add_phone(m.group(1))
        for m in PHONE_STANDALONE.finditer(text):
            entities.add_phone(m.group(1))

        # 金额
        for m in AMOUNT_PATTERN.finditer(text):
            entities.add_amount(m.group(0))

        # 商品 ID
        for m in PRODUCT_ID_PATTERN.finditer(text):
            entities.add_product_id(m.group(1))

        return entities

    def extract_entities_from_tool_result(
        self, session_id: str, tool_name: str, result: Dict[str, Any]
    ) -> ExtractedEntities:
        """
        从 Tool 调用结果中提取实体

        Args:
            session_id: 会话 ID
            tool_name: 工具名称
            result: 工具返回的 JSON 字典

        Returns:
            当前会话的全量实体集合
        """
        entities = self.get_entities(session_id)

        if not isinstance(result, dict):
            return entities

        data = result.get("data", result)

        # 从 order_query / order_manage 结果提取
        if tool_name in ("order_query", "order_manage"):
            if isinstance(data, dict):
                self._extract_order_fields(entities, data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        self._extract_order_fields(entities, item)

        # 从 product_detail / product_search 结果提取
        elif tool_name in ("product_detail", "product_search"):
            if isinstance(data, dict):
                self._extract_product_fields(entities, data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        self._extract_product_fields(entities, item)

        return entities

    @staticmethod
    def _extract_order_fields(entities: ExtractedEntities, d: dict) -> None:
        if d.get("order_no"):
            entities.add_order_no(str(d["order_no"]))
        if d.get("order_id"):
            entities.add_order_no(str(d["order_id"]))
        if d.get("phone"):
            entities.add_phone(str(d["phone"]))
        if d.get("total_amount"):
            entities.add_amount(f"{d['total_amount']}元")
        # 商品名
        items = d.get("items") or d.get("order_items") or []
        for item in items:
            if isinstance(item, dict) and item.get("product_name"):
                entities.add_product_name(item["product_name"])

    @staticmethod
    def _extract_product_fields(entities: ExtractedEntities, d: dict) -> None:
        if d.get("name"):
            entities.add_product_name(d["name"])
        if d.get("product_name"):
            entities.add_product_name(d["product_name"])
        if d.get("id"):
            entities.add_product_id(str(d["id"]))
        if d.get("price"):
            entities.add_amount(f"{d['price']}元")

    # ========== 对话阶段与意图链 ==========

    def update_stage(self, session_id: str, stage: ConversationStage) -> None:
        self._get_state(session_id)["stage"] = stage

    def append_intent(self, session_id: str, intent_value: str) -> None:
        """追加意图到意图链（去连续重复）"""
        chain = self.get_intent_chain(session_id)
        if not chain or chain[-1] != intent_value:
            chain.append(intent_value)
        # 最多保留 20 个
        if len(chain) > 20:
            self._get_state(session_id)["intent_chain"] = chain[-20:]

    def infer_stage_from_intent(self, session_id: str, intent_value: str) -> ConversationStage:
        """根据意图推断并更新对话阶段"""
        stage_map = {
            "greeting": ConversationStage.INITIAL,
            "order_query": ConversationStage.QUERYING,
            "logistics_track": ConversationStage.QUERYING,
            "product_inquiry": ConversationStage.QUERYING,
            "knowledge_faq": ConversationStage.QUERYING,
            "after_sales": ConversationStage.CONFIRMING,
            "complaint": ConversationStage.CONFIRMING,
            "general": ConversationStage.QUERYING,
        }
        stage = stage_map.get(intent_value, ConversationStage.QUERYING)
        self.update_stage(session_id, stage)
        return stage

    # ========== 指代消解 ==========

    def resolve_pronouns(self, session_id: str, message: str) -> Optional[str]:
        """
        检测消息中的指代词，生成消解提示

        Args:
            session_id: 会话 ID
            message: 用户消息

        Returns:
            指代消解提示字符串，无指代词时返回 None
        """
        if not PRONOUN_PATTERN.search(message):
            return None

        entities = self.get_entities(session_id)
        ref = entities.get_latest_entity_for_pronoun()
        if not ref:
            return None

        hint = f"（用户可能在指代「{ref}」）"
        logger.debug(f"[ConversationTracker] Pronoun resolved: {hint}")
        return hint

    # ========== 上下文摘要 ==========

    def generate_context_summary(self, session_id: str) -> str:
        """
        生成用于注入 System Prompt 的上下文摘要

        Returns:
            XML 格式的上下文摘要字符串
        """
        state = self._get_state(session_id)
        entities: ExtractedEntities = state["entities"]
        stage: ConversationStage = state["stage"]
        intent_chain: List[str] = state["intent_chain"]

        if entities.is_empty() and not intent_chain:
            return ""

        lines = [
            "<context_summary>",
            f"  <entities>{entities.to_summary_str()}</entities>",
            f"  <stage>{stage.value}</stage>",
        ]
        if intent_chain:
            lines.append(f"  <intent_chain>{' → '.join(intent_chain[-5:])}</intent_chain>")
        lines.append("</context_summary>")
        return "\n".join(lines)

    # ========== 对话历史压缩 ==========

    async def compress_history(
        self,
        chat_history: List[Dict[str, Any]],
        session_id: str,
        max_turns: int = 10,
        keep_recent: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        对话历史压缩：超过 max_turns 轮时，对早期历史做摘要

        一轮 = 一组 user + assistant。

        Args:
            chat_history: 完整的对话历史列表
            session_id: 会话 ID
            max_turns: 超过此轮数时触发压缩
            keep_recent: 保留最近的完整轮数

        Returns:
            压缩后的对话历史
        """
        if not chat_history:
            return chat_history

        # 计算轮数（以 user 消息计）
        user_count = sum(1 for m in chat_history if m.get("role") == "user")
        if user_count <= max_turns:
            return chat_history

        logger.info(
            f"[ConversationTracker] Compressing history: {user_count} turns > {max_turns}, "
            f"session={session_id}"
        )

        # 找到保留边界：保留最后 keep_recent 轮
        keep_idx = self._find_keep_boundary(chat_history, keep_recent)
        early_history = chat_history[:keep_idx]
        recent_history = chat_history[keep_idx:]

        if not early_history:
            return chat_history

        # 用小模型生成摘要
        summary = await self._summarize_history(early_history, session_id)

        # 构建压缩后的历史
        compressed: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": f"[以下是早期对话摘要]\n{summary}",
                "content_type": "text",
            }
        ]
        compressed.extend(recent_history)
        return compressed

    @staticmethod
    def _find_keep_boundary(chat_history: List[Dict[str, Any]], keep_recent: int) -> int:
        """找到应保留的最近 N 轮的起始索引"""
        user_indices = [
            i for i, m in enumerate(chat_history) if m.get("role") == "user"
        ]
        if len(user_indices) <= keep_recent:
            return 0
        # 保留最后 keep_recent 个 user 消息及其后续
        return user_indices[-keep_recent]

    async def _summarize_history(
        self, history: List[Dict[str, Any]], session_id: str
    ) -> str:
        """
        使用小模型（qwen3.6-plus）对早期历史生成摘要

        Args:
            history: 需要摘要的对话历史
            session_id: 会话 ID

        Returns:
            摘要文本
        """
        from app.config import settings

        # 构建待摘要文本
        text_parts: list[str] = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态消息只取文本部分
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
            text_parts.append(f"{role}: {content}")

        conversation_text = "\n".join(text_parts)

        # 获取当前实体信息用于辅助摘要
        entities = self.get_entities(session_id)
        entity_hint = entities.to_summary_str()

        summarize_prompt = (
            "请将以下客服对话历史压缩为一段简洁的摘要（不超过200字）。\n"
            "要求：\n"
            "1. 保留关键实体信息（订单号、商品名、金额等）\n"
            "2. 保留用户的核心诉求和已解决的问题\n"
            "3. 不要遗漏重要的操作结果\n\n"
            f"已识别的关键实体：{entity_hint}\n\n"
            f"对话历史：\n{conversation_text}"
        )

        try:
            llm = ChatOpenAI(
                model=settings.INTENT_MODEL,  # qwen3.6-plus
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=DASHSCOPE_BASE_URL,
                temperature=0.3,
                max_tokens=512,
            )
            response = await llm.ainvoke(summarize_prompt)
            summary = response.content.strip()
            logger.info(
                f"[ConversationTracker] History summarized: {len(history)} messages → "
                f"{len(summary)} chars | session={session_id}"
            )
            return summary
        except Exception as e:
            logger.error(f"[ConversationTracker] Summarization failed: {e}")
            # 降级：截取前几条消息作为简要摘要
            fallback_parts = text_parts[:6]
            return "早期对话概要：\n" + "\n".join(fallback_parts)

    # ========== 清理 ==========

    def clear_session(self, session_id: str) -> None:
        """清除指定会话的上下文状态"""
        self._states.pop(session_id, None)
