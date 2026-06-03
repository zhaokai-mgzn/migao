"""
意图分类 - 使用 qwen3.6-plus 进行意图识别
"""

import json
from functools import lru_cache
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.llm import LLMFactory, cost_tracker
from app.router.intent_config import IntentType, IntentResult


# DashScope OpenAI 兼容接口地址
DASHSCOPE_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

# 每个意图的描述（用于动态构建分类器 Prompt）
_INTENT_DESCRIPTIONS: dict[str, str] = {
    # 公共
    "greeting": "打招呼、问候（如'你好''在吗'）",
    "farewell": "告别、结束对话（如'再见''谢谢再见''拜拜'）",
    "capabilities": "询问助手能力、功能（如'你能做什么''你有什么功能'）",
    'general': '以上都不匹配的其他问题',
    # 订单域
    'order_query': '查询订单状态、订单信息',
    'logistics_track': '查询物流、快递进度',
    'after_sales': '退货、退款、换货、售后服务（仅咨询政策）',
    'after_sales_create': '创建/受理/流转/处理/关闭售后工单等售后工单管理场景',
    'complaint': '投诉、举报、不满',
    # 商品域
    'product_inquiry': '商品咨询、价格查询、产品推荐、加工项查询',
    'category_manage': '商品分类的查询/创建/更名/启用停用/删除/排序',
    'processing_manage': '加工项的创建/更新/上下架/删除/调价等管理操作（不含单纯查询）',
    # 客户关系域
    'customer_manage': '客户档案增删改、打标签、跟进记录、合并客户等写操作',
    'customer_query': '查询客户信息、客户列表、客户详情、历史订单等读操作',
    # 人事域
    'employee_manage': '员工账号查询/创建/启用停用/删除、员工信息管理',
    'staff_manage': '人事、团队、同事、人员安排等人资总台场景（与 employee_manage 近义）',
    'role_manage': '角色查询/创建/分配、角色与员工关联',
    'permission_manage': '权限项查询/调整、权限点配置、菜单授权',
    # 系统配置域
    'system_settings': '系统级参数、租户配置、业务开关等设置项查询与修改',
    'ai_config': 'AI 助手相关配置（模型选择、温度、上下文、提示词等）',
    'notification': '站内通知/公告/消息推送的查询、创建、标读、删除等',
    'quick_reply': '客服快捷回复模板的查询、创建、编辑、删除',
    # 数据分析域
    'dashboard': '查看经营/运营看板、总览页、实时指标',
    'statistics': '查询某个具体统计指标（今日销量、转化率、在线人数等）',
    'data_report': '查看/导出经营报表、Top 排行、趋势分析',
    'session_manage': '客服会话列表/详情/关闭/转接/接接人工等会话管理操作',
    # 知识库域
    'knowledge_faq': '面料知识、保养方法、安装指南等问答',
    'knowledge_manage': '知识库条目的创建/更新/上下架/删除等管理操作',
}

# 意图判定提示（消歧规则，仅在有相关意图时展示）
_INTENT_DISAMBIGUATION: dict[str, str] = {
    "order_query": "只是问订单记录则归 order_query",
    "after_sales_create": "'退款/退换货/售后工单/受理投诉'在商家后台上下文优先 after_sales_create",
    "after_sales": "仅是咨询退换政策则仍为 after_sales",
    "processing_manage": "'加工项'需要创建/修改/上下架/删除/调价 -> processing_manage",
    "product_inquiry": "仅查询加工项价格/列表 -> product_inquiry",
    "category_manage": "'商品分类/类目'相关任何操作 -> category_manage",
    "knowledge_manage": "'知识库条目'需要增删改查（写操作为主） -> knowledge_manage",
    "knowledge_faq": "仅检索问答 -> knowledge_faq",
    "customer_query": "'客户/客户资料'查询优先 customer_query",
    "customer_manage": "客户写操作优先 customer_manage",
    "employee_manage": "'员工/同事/账号'优先 employee_manage",
    "role_manage": "'角色/职位组'优先 role_manage",
    "permission_manage": "'权限/菜单授权'优先 permission_manage",
    "system_settings": "'设置/配置/开关'优先 system_settings",
    "ai_config": "AI 相关配置优先 ai_config",
    "notification": "'通知/公告/消息'优先 notification",
    "quick_reply": "'快捷回复/模板'优先 quick_reply",
    "dashboard": "'看板/总览'优先 dashboard",
    "statistics": "具体指标优先 statistics",
    "data_report": "报表/趋势优先 data_report",
    "session_manage": "'会话/在线咨询/接入人工'优先 session_manage",
}


def _build_classifier_prompt(agent_intents: list[str] | None = None) -> str:
    '''动态构建分类器 Prompt

    Args:
        agent_intents: 该 Agent 可处理的意图列表。
                       若为 None，使用全部意图（向后兼容）。

    Returns:
        str: 完整的分类器 System Prompt
    '''
    if agent_intents is None:
        # 向后兼容：使用全部意图
        intents_to_show = list(_INTENT_DESCRIPTIONS.keys())
    else:
        # 确保 general 始终包含（兜底意图）
        intents_to_show = list(agent_intents)
        if 'general' not in intents_to_show:
            intents_to_show.append('general')

    # 构建意图列表
    intent_lines = []
    for intent in intents_to_show:
        desc = _INTENT_DESCRIPTIONS.get(intent, intent)
        intent_lines.append(f'- {intent}: {desc}')

    # 构建消歧规则（只展示与当前意图相关的规则）
    disambig_lines = []
    for intent in intents_to_show:
        rule = _INTENT_DISAMBIGUATION.get(intent)
        if rule:
            disambig_lines.append(f'- {rule}')

    intent_section = '\n'.join(intent_lines)
    disambig_section = '\n'.join(disambig_lines) if disambig_lines else '（无特殊消歧规则）'

    return f'''你是一个意图分类器。根据用户消息，从以下意图列表中选择最匹配的一个，并给出置信度。

意图列表：
{intent_section}

请严格以 JSON 格式输出，不要输出其他内容：
{{"intent": "意图名称", "confidence": 0.xx}}

判定提示：
- 优先区分'查询/读'与'管理/写'：只是问记录则归为查询类，出现创建/修改/删除/启用停用/上下架/调价等动作词则归为管理类
{disambig_section}

注意：
- confidence 取值 0.0~1.0，表示你对分类结果的确信程度
- 如果用户消息含糊不清或可能属于多个意图，降低 confidence
- 优先考虑用户的核心诉求'''


@lru_cache(maxsize=16)
def _build_classifier_prompt_cached(intent_key: tuple) -> str:
    """缓存版 Prompt 构建（tuple 参数可哈希）

    相同的 intent 组合只构建一次，避免每次请求重复计算。
    """
    agent_intents = list(intent_key) if intent_key else None
    return _build_classifier_prompt(agent_intents)


# 向后兼容：默认完整 Prompt（全部意图）
CLASSIFIER_SYSTEM_PROMPT = _build_classifier_prompt(None)


class IntentClassifier:
    """
    L2 意图分类器
    
    使用 qwen3.6-plus进行意图分类，
    相比大模型调用成本更低、速度更快。
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        """懒加载 LLM 实例（统一走 LLMFactory）"""
        if self._llm is None:
            self._llm = LLMFactory.create_intent_llm()
        return self._llm

    async def classify(
        self,
        message: str,
        chat_history: list = None,
        agent_intents: list[str] | None = None,
    ) -> IntentResult:
        """
        使用小模型对用户消息进行意图分类

        Args:
            message: 用户消息文本
            chat_history: 对话历史（可选，用于上下文理解）
            agent_intents: 该 Agent 可处理的意图列表（可选）。
                           若提供，分类器只考虑这些意图，提升准确率和降低成本。
                           若为 None，使用全部意图（向后兼容）。

        Returns:
            IntentResult: 分类结果
        """
        try:
            # 动态构建 Prompt：只列出该 Agent 相关的意图（带缓存）
            intent_key = tuple(agent_intents) if agent_intents else ()
            prompt = _build_classifier_prompt_cached(intent_key)
            messages = [SystemMessage(content=prompt)]

            # 如果有对话历史，提供最近几轮作为上下文
            if chat_history:
                recent = chat_history[-4:]  # 最近 2 轮对话
                context_text = "\n".join(
                    f"{'用户' if m.get('role') == 'user' else '客服'}: {m.get('content', '')}"
                    for m in recent
                )
                messages.append(
                    HumanMessage(content=f"对话上下文：\n{context_text}\n\n当前用户消息：{message}")
                )
            else:
                messages.append(HumanMessage(content=message))

            response = await self.llm.ainvoke(messages)
            # 成本追踪（失败仅 warning，不影响主流程）
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
                        model=settings.INTENT_MODEL,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception as track_exc:
                logger.warning(f"[intent_classifier] cost tracking failed: {track_exc}")

            result = self._parse_response(response.content)
            return result

        except Exception as e:
            logger.warning(f"Intent classifier error: {e}, falling back to general")
            return IntentResult(
                intent=IntentType.GENERAL,
                confidence=0.5,
                source="default",
                matched_keywords=[],
            )

    def _parse_response(self, content: str) -> IntentResult:
        """解析模型返回的 JSON 结果"""
        try:
            # 尝试提取 JSON（模型可能会包裹在 markdown 代码块中）
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            data = json.loads(text)
            intent_str = data.get("intent", "general")
            confidence = float(data.get("confidence", 0.5))

            # 验证 intent 是否在枚举中
            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.GENERAL
                confidence = 0.5

            return IntentResult(
                intent=intent,
                confidence=min(max(confidence, 0.0), 1.0),
                source="classifier",
                matched_keywords=[],
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse classifier response: {content}, error: {e}")
            return IntentResult(
                intent=IntentType.GENERAL,
                confidence=0.5,
                source="default",
                matched_keywords=[],
            )
