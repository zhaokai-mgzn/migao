"""
后续问题建议生成器

在 AI 回复结束后，自动推荐 2-3 个后续问题建议，引导用户继续对话。

策略：
- 高频意图使用预设模板（<5ms）
- 涉及具体实体时使用 qwen-turbo 动态生成（100-200ms）
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
from app.llm import LLMFactory, DASHSCOPE_API_KEY, cost_tracker


# ========== 米宝预设建议（B 端：企业内部员工的 AI 助手和 AI 操作系统） ==========

MIBAO_PRESET_SUGGESTIONS: dict[str, list[str]] = {
    # --- 订单域 ---
    "order_query": ["查看订单详情", "跟踪物流状态", "处理退款申请"],
    "order_create": ["查看待处理订单", "查看订单模板", "查看最近创建"],
    "logistics_track": ["查看签收状态", "联系物流客服", "查看其他订单物流"],
    "after_sales": ["查看售后工单", "创建退款工单", "处理售后审批"],
    "after_sales_create": ["查看工单进度", "分配处理人员", "关闭已完成工单"],
    "complaint": ["查看投诉工单", "创建新投诉", "查看处理进度"],
    # --- 商品域 ---
    "product_inquiry": ["查看商品列表", "管理加工项", "调整商品价格"],
    "category_manage": ["新增商品分类", "查看分类列表", "调整分类排序"],
    "processing_manage": ["新增加工项", "调整加工项价格", "查看加工项列表"],
    # --- 客户域 ---
    "customer_manage": ["新增客户档案", "查看客户列表", "合并重复客户"],
    "customer_query": ["查看客户详情", "查看客户历史订单", "导出客户数据"],
    # --- 人事域 ---
    "employee_manage": ["创建员工账号", "查看员工列表", "分配系统角色"],
    "staff_manage": ["查看团队架构", "管理人员信息", "查看人员排班"],
    "role_manage": ["查看角色列表", "创建新角色", "分配角色权限"],
    "permission_manage": ["查看权限配置", "调整菜单权限", "查看角色权限关联"],
    # --- 系统配置域 ---
    "system_settings": ["查看系统参数", "配置业务开关", "查看操作日志"],
    "ai_config": ["调整 AI 模型", "配置提示词", "查看 AI 对话统计"],
    "notification": ["查看站内通知", "创建新公告", "标记通知已读"],
    "quick_reply": ["查看快捷回复", "新增回复模板", "编辑回复模板"],
    # --- 数据分析域 ---
    "dashboard": ["查看经营报表", "分析销售趋势", "查看实时数据"],
    "statistics": ["查看今日销售", "查看转化率", "查看客户增长"],
    "data_report": ["导出经营报表", "查看 Top 排行", "查看趋势分析"],
    "session_manage": ["查看在线会话", "转接客服", "查看会话统计"],
    # --- 知识库域 ---
    "knowledge_faq": ["查看常见问题", "新增知识条目", "编辑知识内容"],
    "knowledge_manage": ["新增知识条目", "上下架知识", "查看知识库统计"],
    # --- 通用 ---
    "greeting": ["查看今日待办", "查看经营数据", "处理待审批"],
    "capabilities": ["查看商品管理", "查看订单处理", "查看数据分析"],
    "farewell": [],
    "general": ["查看待办事项", "查看经营看板", "查看系统通知"],
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

MIBAO_DYNAMIC_PROMPT = """你是米宝，企业内部员工的 AI 工作助手和 AI 操作系统。
根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}

要求：
1. 问题要简短自然，像企业内部员工会说的话
2. 问题要与当前对话主题相关，体现 B 端管理视角（如查看数据、处理工单、管理团队等）
3. 问题之间不要重复
4. 直接返回 JSON 数组格式，不要其他内容

输出格式示例：["问题1", "问题2", "问题3"]"""

XIAOBU_DYNAMIC_PROMPT = """你是小布，面向消费者的智能客服助手。
根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}

要求：
1. 问题要简短自然，像消费者会说的话
2. 问题要与当前对话主题相关（如商品咨询、订单查询、售后服务等）
3. 问题之间不要重复
4. 直接返回 JSON 数组格式，不要其他内容

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
        self._api_key = DASHSCOPE_API_KEY
        self._model = settings.INTENT_MODEL  # qwen3.6-flash（轻量模型，关闭思考）
        self._llm = None  # 懒加载 LangChain LLM 实例

    async def generate(
        self,
        query: str,
        answer: str,
        intent_type: str,
        chat_history: Optional[list] = None,
        agent_type: str = "mibao",
    ) -> list[str]:
        """
        生成 2-3 个后续问题建议

        Args:
            query: 用户原始问题
            answer: AI 回复内容
            intent_type: 意图类型
            chat_history: 对话历史（可选）
            agent_type: Agent 类型（"mibao" 或 "xiaobu"）

        Returns:
            2-3 个后续问题建议字符串列表
        """
        try:
            # 智能选择策略
            if self._should_use_dynamic(answer, intent_type):
                suggestions = await self._generate_dynamic(query, answer, agent_type)
                if suggestions:
                    return suggestions[:3]

            # 使用预设模板
            return self._get_preset(intent_type, agent_type)

        except Exception as e:
            logger.warning(f"Failed to generate follow-up suggestions: {e}")
            return self._get_preset(intent_type, agent_type)

    def _should_use_dynamic(self, answer: str, intent_type: str) -> bool:
        """判断是否应该使用动态生成"""
        # 没有 API Key 时不使用动态生成
        if not self._api_key:
            return False
        # 回复涉及具体实体时使用动态生成
        return _has_specific_entities(answer)

    def _get_preset(self, intent_type: str, agent_type: str = "mibao") -> list[str]:
        """获取预设建议模板（Agent 感知）"""
        if agent_type == "xiaobu":
            return XIAOBU_PRESET_SUGGESTIONS.get(intent_type, XIAOBU_DEFAULT_SUGGESTIONS)
        return MIBAO_PRESET_SUGGESTIONS.get(intent_type, MIBAO_DEFAULT_SUGGESTIONS)

    async def _generate_dynamic(
        self, query: str, answer: str, agent_type: str = "mibao"
    ) -> Optional[list[str]]:
        """使用 qwen-turbo 动态生成后续问题建议（走 LangChain 统一接口）"""
        # 根据 agent_type 选择 prompt
        if agent_type == "xiaobu":
            prompt_template = XIAOBU_DYNAMIC_PROMPT
        else:
            prompt_template = MIBAO_DYNAMIC_PROMPT

        prompt = prompt_template.format(
            query=query[:200],  # 截断避免过长
            answer=answer[:500],
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
