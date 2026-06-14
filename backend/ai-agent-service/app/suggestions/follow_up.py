"""
后续问题建议生成器

在 AI 回复结束后，自动推荐 2-3 个后续问题建议，引导用户继续对话。

策略：
- 高频意图使用预设模板（<5ms）
- 涉及具体实体时使用轻量模型动态生成（~100-200ms）
- 超时或失败时返回预设模板兜底

Agent 感知：
- 米宝（mibao）：企业内部员工的 AI 助手和 AI 操作系统，B 端管理视角
- 小布（xiaobu）：C 端智能客服，消费者视角
"""

import json
import re
from typing import Optional

import httpx
from langchain_core.messages import HumanMessage
from loguru import logger

from app.config import settings
from app.llm import LLMFactory, MINIMAX_API_KEY, cost_tracker


# ========== 米宝预设建议（B 端：企业内部员工的 AI 助手和 AI 操作系统） ==========

MIBAO_PRESET_SUGGESTIONS: dict[str, list[str]] = {
    # --- 订单域 ---
    "order_query": ["查看订单详情", "筛选待发货订单", "查看物流状态"],
    "order_create": ["查看待处理订单", "查看商品列表", "查看最近订单"],
    "logistics_track": ["查看签收状态", "查看其他订单物流", "查看订单详情"],
    "after_sales": ["查看售后工单", "查看工单处理进度", "查看关联订单"],
    "after_sales_create": ["查看已有工单", "查看订单详情", "查看退款政策"],
    "complaint": ["查看投诉详情", "查看处理进度", "查看关联订单"],
    # --- 商品域 ---
    "product_inquiry": ["查看商品列表", "查看商品详情", "查看商品库存"],
    "category_manage": ["查看分类列表", "查看分类下商品", "调整分类排序"],
    "processing_manage": ["查看加工项列表", "查看加工项详情", "查看关联商品"],
    # --- 客户域 ---
    "customer_manage": ["查看客户列表", "查看客户详情", "搜索客户信息"],
    "customer_query": ["查看客户详情", "查看客户历史订单", "查看客户标签"],
    # --- 人事域 ---
    "employee_manage": ["查看员工列表", "查看员工详情", "查看角色列表"],
    "staff_manage": ["查看员工列表", "查看角色分配", "查看权限配置"],
    "role_manage": ["查看角色列表", "查看角色权限", "查看关联员工"],
    "permission_manage": ["查看权限列表", "查看角色权限", "查看菜单配置"],
    # --- 系统配置域 ---
    "system_settings": ["查看系统配置", "查看通知设置", "查看AI配置"],
    "ai_config": ["查看当前模型", "查看AI对话统计", "调整问候语"],
    "notification": ["查看未读通知", "查看通知历史", "标记全部已读"],
    "quick_reply": ["查看快捷回复", "查看回复模板", "搜索回复内容"],
    # --- 数据分析域 ---
    "dashboard": ["查看今日经营数据", "查看订单趋势", "查看客户增长"],
    "statistics": ["查看今日订单", "查看销售趋势", "查看订单状态分布"],
    "data_report": ["查看订单统计", "查看销售趋势", "查看客户分析"],
    "session_manage": ["查看在线会话", "查看会话统计", "查看活跃客户"],
    # --- 知识库域 ---
    "knowledge_faq": ["查看常见问题", "搜索知识内容", "查看最近更新"],
    "knowledge_manage": ["查看知识条目", "搜索知识内容", "查看分类统计"],
    # --- 通用 ---
    "greeting": ["查看今日订单", "查看经营数据", "查看待处理事项"],
    "capabilities": ["查看商品管理", "查看订单处理", "查看数据分析"],
    "farewell": [],
    "general": ["查看今日订单", "查看经营数据", "搜索帮助内容"],
}

# 米宝默认兜底建议（B 端管理视角）
MIBAO_DEFAULT_SUGGESTIONS: list[str] = ["查看待办事项", "查看经营数据", "查看系统通知"]


# ========== 小布预设建议（C 端：智能客服，消费者视角） ==========

XIAOBU_PRESET_SUGGESTIONS: dict[str, list[str]] = {
    "order_query": ["查看物流信息", "申请退货退款", "修改收货地址"],
    "order_create": ["查看我的订单", "浏览商品", "联系客服"],
    "logistics_track": ["确认收货", "联系快递客服", "查看其他订单物流"],
    "product_inquiry": ["查看商品详情", "了解促销活动", "咨询定制服务"],
    "after_sales": ["查看售后进度", "了解退款政策", "联系人工客服"],
    "knowledge_faq": ["查看更多常见问题", "咨询具体产品问题", "联系专业顾问"],
    "greeting": ["查看我的订单", "浏览热门商品", "咨询窗帘定制"],
    "complaint": ["查看投诉处理进度", "联系主管", "了解赔偿政策"],
    "capabilities": ["查看商品咨询", "查看订单查询", "查看知识问答"],
    "farewell": [],
    "general": ["查看我的订单", "浏览商品", "联系人工客服"],
}

# 小布默认兜底建议（C 端消费者视角）
XIAOBU_DEFAULT_SUGGESTIONS: list[str] = ["查看我的订单", "浏览商品", "联系人工客服"]


# ========== 动态生成 Prompt（Agent 感知） ==========

MIBAO_DYNAMIC_PROMPT = """你是米宝，词元通达商家管理后台的企业内部 AI 工作助手。

根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}
对话上下文：{context}

## 米宝能力范围（只能建议这些能做的事）

✅ **能做**：查订单/物流、查商品/加工项、查看经营数据/统计报表、查客户信息、查知识库/FAQ
❌ **不能做**：打电话/发短信/发邮件、导出文件到本地、修改系统配置、操作第三方平台（微信/支付宝等）、线下操作（联系快递公司等）

## 要求

1. 问题要简短自然（≤15字），像企业内部员工会说的话
2. 问题必须与当前对话主题紧密相关，且比当前问题更具体（不要建议比用户原问题更泛的问题）
3. 问题必须在上述 ✅ 能力范围内
4. 问题之间不要重复
5. 直接返回 JSON 数组格式，不要其他内容

## 禁止事项

- ❌ 不要建议 AI 已经在回复中明确回答过的问题（如回复已展示订单详情，不要再建议"查看订单详情"）
- ❌ 不要建议比用户当前问题更泛的问题（如用户问具体订单物流，不要建议"查看订单列表"）
- ❌ 不要建议"查看所有XX"这类泛泛的列表查看，建议具体的下一步操作

输出格式示例：["问题1", "问题2", "问题3"]"""

XIAOBU_DYNAMIC_PROMPT = """你是小布，面向消费者的智能客服助手。
根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}
对话上下文：{context}

要求：
1. 问题要简短自然（≤15字），像消费者会说的话
2. 问题必须与当前对话主题紧密相关（商品咨询、订单查询、售后服务等），且比当前问题更具体
3. 问题之间不要重复
4. 直接返回 JSON 数组格式，不要其他内容

## 禁止事项

- ❌ 不要建议 AI 已经在回复中明确回答过的问题
- ❌ 不要建议比用户当前问题更泛的问题（如用户问具体订单物流，不要建议"查看我的订单"）

输出格式示例：["问题1", "问题2", "问题3"]"""


# 用于检测回复中是否包含具体实体的正则
_ENTITY_PATTERNS = [
    re.compile(r"订单号[：:\s]*\w+"),
    re.compile(r"[A-Z]{2}\d{9,}[A-Z]{2}"),  # 物流单号
    re.compile(r"商品[：:\s]*[「「【]?.+?[」」】]?"),
    re.compile(r"¥\d+"),  # 价格
    re.compile(r"\d{4}-\d{2}-\d{2}"),  # 日期
]


def _has_specific_entities(answer: str) -> bool:
    """检测回复中是否包含具体实体（订单号、商品名、价格等）"""
    for pattern in _ENTITY_PATTERNS:
        if pattern.search(answer):
            return True
    return False


def _parse_suggestions_from_response(text: str) -> Optional[list[str]]:
    """从模型响应中解析建议列表"""
    text = text.strip()
    # 尝试直接解析 JSON 数组
    try:
        result = json.loads(text)
        if isinstance(result, list) and all(isinstance(s, str) for s in result):
            return result[:3]
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and all(isinstance(s, str) for s in result):
                return result[:3]
        except json.JSONDecodeError:
            pass

    return None


class FollowUpSuggestionGenerator:
    """后续问题建议生成器（Agent 感知）"""

    def __init__(self):
        self._api_key = MINIMAX_API_KEY
        self._model = settings.INTENT_MODEL  # 轻量模型，关闭思考模式
        self._llm = None  # 懒加载 LangChain LLM 实例

    async def generate(
        self,
        query: str,
        answer: str,
        intent_type: str,
        chat_history: Optional[list] = None,
        agent_type: str = "mibao",
        stage: str = "initial",
        session_id: str = "",
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> list[str]:
        """
        生成 2-3 个后续问题建议

        Args:
            query: 用户原始问题
            answer: AI 回复内容
            intent_type: 意图类型
            chat_history: 对话历史消息列表（LangChain messages）
            agent_type: Agent 类型（"mibao" 或 "xiaobu"）
            stage: 对话阶段 (initial/querying/confirming/processing/completed)
            session_id: 会话 ID（用于日志）
            tenant_id: 租户 ID（用于日志）
            user_id: 用户 ID（用于日志）

        Returns:
            2-3 个后续问题建议字符串列表
        """
        strategy = "preset"
        try:
            # 智能选择策略：有 API Key 且回复涉及具体内容时优先动态生成
            if self._should_use_dynamic(answer, intent_type):
                suggestions = await self._generate_dynamic(
                    query, answer, agent_type, chat_history=chat_history
                )
                if suggestions:
                    strategy = "dynamic"
                    result = suggestions[:3]
                    self._log_generation(
                        query, answer, intent_type, agent_type, stage,
                        session_id, tenant_id, user_id, strategy, result,
                    )
                    return result

            # 使用预设模板
            result = self._get_preset(intent_type, agent_type)
            self._log_generation(
                query, answer, intent_type, agent_type, stage,
                session_id, tenant_id, user_id, strategy, result,
            )
            return result

        except Exception as e:
            logger.warning(f"Failed to generate follow-up suggestions: {e}")
            result = self._get_preset(intent_type, agent_type)
            self._log_generation(
                query, answer, intent_type, agent_type, stage,
                session_id, tenant_id, user_id, "preset(fallback)", result,
            )
            return result

    @staticmethod
    def _log_generation(
        query: str,
        answer: str,
        intent_type: str,
        agent_type: str,
        stage: str,
        session_id: str,
        tenant_id: int,
        user_id: int,
        strategy: str,
        suggestions: list[str],
    ) -> None:
        """输出结构化日志，用于后续训练数据分析

        ⚠️ 数据安全：日志包含用户对话内容（已脱敏手机号/邮箱），
        应配置日志访问权限和保留策略，仅用于产品体验优化分析。
        """
        import json as _json
        from app.utils.log_sanitizer import LogSanitizer

        sanitized_suggestions = [LogSanitizer.mask_text(s) for s in suggestions]
        logger.info(
            "[suggestion:generated]",
            _json.dumps({
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "agent_type": agent_type,
                "intent_type": intent_type,
                "stage": stage,
                "strategy": strategy,
                "user_query": LogSanitizer.mask_text(query[:100]),
                "ai_answer": LogSanitizer.mask_text(answer[:150]),
                "suggestions": sanitized_suggestions,
            }, ensure_ascii=False),
        )

    def _should_use_dynamic(self, answer: str, intent_type: str) -> bool:
        """判断是否应该使用动态生成

        当回复内容包含具体信息（数字、状态、实体名称等）时使用动态生成，
        比纯正则检测更宽松，覆盖更多真实场景。
        """
        # 没有 API Key 时不使用动态生成
        if not self._api_key:
            return False
        # 回复太短（如问候语）不使用动态生成
        if len(answer) < 20:
            return False
        # 回复包含中文实体相关关键词时使用动态生成
        entity_keywords = [
            "订单", "商品", "客户", "物流", "退款", "发货", "收货",
            "工单", "售后", "投诉", "统计", "数据", "报表", "加工",
        ]
        if any(kw in answer for kw in entity_keywords):
            return True
        # 兜底：回复足够长时也尝试动态生成（避免漏掉）
        if len(answer) > 100:
            return True
        return _has_specific_entities(answer)

    def _get_preset(self, intent_type: str, agent_type: str = "mibao") -> list[str]:
        """获取预设建议模板（Agent 感知）"""
        if agent_type == "xiaobu":
            return XIAOBU_PRESET_SUGGESTIONS.get(intent_type, XIAOBU_DEFAULT_SUGGESTIONS)
        return MIBAO_PRESET_SUGGESTIONS.get(intent_type, MIBAO_DEFAULT_SUGGESTIONS)

    async def _generate_dynamic(
        self, query: str, answer: str, agent_type: str = "mibao",
        chat_history: Optional[list] = None,
    ) -> Optional[list[str]]:
        """使用轻量模型动态生成后续问题建议（走 LangChain 统一接口）"""
        # 根据 agent_type 选择 prompt
        if agent_type == "xiaobu":
            prompt_template = XIAOBU_DYNAMIC_PROMPT
        else:
            prompt_template = MIBAO_DYNAMIC_PROMPT

        # 构建对话上下文（最近 3 轮）
        context_text = ""
        if chat_history:
            recent = chat_history[-6:]  # 最近 3 轮（每轮 user+assistant）
            lines = []
            for msg in recent:
                role = "用户" if getattr(msg, "type", "") == "human" else "米宝"
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    lines.append(f"{role}: {content[:200]}")
            if lines:
                context_text = "\n".join(lines)

        prompt = prompt_template.format(
            query=query[:200],  # 截断避免过长
            answer=answer[:500],
            context=context_text or "（无历史对话）",
        )

        try:
            if self._llm is None:
                self._llm = LLMFactory.create_suggestion_llm()

            response = await self._llm.ainvoke([HumanMessage(content=prompt)])

            # 成本追踪（失败仅 warning）
            try:
                usage_meta = getattr(response, "usage_metadata", None) or {}
                input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
                output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
                if not (input_tokens or output_tokens):
                    resp_meta = getattr(response, "response_metadata", None) or {}
                    token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
                    input_tokens = int(
                        token_usage.get("prompt_tokens")
                        or token_usage.get("input_tokens")
                        or 0
                    )
                    output_tokens = int(
                        token_usage.get("completion_tokens")
                        or token_usage.get("output_tokens")
                        or 0
                    )
                if input_tokens or output_tokens:
                    cost_tracker.track_call(
                        model=self._model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception as track_exc:
                logger.warning(f"[follow_up] cost tracking failed: {track_exc}")

            content = response.content if isinstance(response.content, str) else ""
            return _parse_suggestions_from_response(content)

        except httpx.TimeoutException:
            logger.debug("Dynamic suggestion generation timed out, falling back to preset")
            return None
        except Exception as e:
            logger.warning(f"Dynamic suggestion generation failed: {e}")
            return None
