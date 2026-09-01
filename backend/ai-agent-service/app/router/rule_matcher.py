"""
L1 规则匹配层 - 基于关键词和正则表达式的快速意图匹配
"""

import re
from typing import Optional, Union

from app.router.intent_config import IntentType, IntentResult


def _extract_text(content: Union[str, list, None]) -> str:
    """从消息内容中提取纯文本

    支持 str 和多模态 list 格式：
    [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)
        return " ".join(parts)
    return str(content)


# 关键词 → 意图映射表
KEYWORD_MAP: dict[IntentType, list[str]] = {
    # 数据分析必须在订单前（防"订单趋势"被"订单"吞掉）
    IntentType.DASHBOARD: ["看板", "趋势", "经营", "今日数据", "本周数据", "本月数据"],
    IntentType.STATISTICS: ["统计", "数据报表"],
    IntentType.FINANCE: ["财务", "资金流水", "收支", "对账", "净收入", "净额", "登记收款", "登记退款", "记一笔", "收款", "进账", "流水", "应收账款", "没对平", "收入支出", "收了多少", "赚了多少", "收了几笔"],
    IntentType.ORDER_CREATE: ["创建订单", "新建订单", "下单", "开个单", "录单", "确认创建订单"],
    IntentType.ORDER_QUERY: ["订单", "我的订单", "订单状态", "查订单", "待发货"],
    IntentType.LOGISTICS_TRACK: ["物流", "快递", "到哪了"],
    IntentType.PRODUCT_INQUIRY: ["商品", "产品", "价格", "多少钱", "加工项", "加工项目", "加工费", "创建商品", "新建商品", "上架", "库存", "规格", "色号", "确认创建商品"],
    # 算料报价：褶皱/算料/用布量等词特异，优先于商品咨询（"多少钱"）
    IntentType.QUOTE: ["算料", "报价", "用多少布", "多少米布", "几米布", "用料", "褶皱倍数", "褶皱", "打孔帘", "韩式褶", "四爪钩"],
    # 人事域（2026-08-28 补：此前缺失导致"创建员工账号/添加员工"被商品正则劫持，HR-002 修复）
    IntentType.EMPLOYEE_MANAGE: ["员工账号", "员工管理", "员工列表", "创建员工", "新建员工", "添加员工", "开个账号", "开通账号", "员工", "人事"],
    IntentType.ROLE_MANAGE: ["角色权限", "角色", "权限"],
    # 会话管理（"看看当前有哪些会话" 此前无法触发 session_manage，SE-001 修复）
    IntentType.SESSION_MANAGE: ["客服会话", "在线会话", "排队会话", "历史会话", "会话列表", "会话"],
    IntentType.AFTER_SALES: ["退货", "退款", "换货", "售后", "维修"],
    IntentType.KNOWLEDGE_FAQ: ["怎么清洗", "怎么安装", "怎么保养", "怎么测量", "怎么选", "如何", "什么是", "为什么", "教程"],
    IntentType.FAREWELL: ["再见", "拜拜", "bye", "goodbye", "下次见", "回见"],
    IntentType.CAPABILITIES: [
        "你能做什么", "你会什么", "你有什么功能", "能帮我做什么",
        "有什么功能", "你能干什么", "你可以做什么", "你能帮我什么",
        "能做什么", "什么功能",
    ],
    IntentType.GREETING: ["你好", "在吗", "嗨", "hello", "hi"],
    IntentType.COMPLAINT: ["投诉", "举报", "不满", "差评"],
}

# 正则规则
REGEX_RULES: list[tuple[re.Pattern, IntentType]] = [
    # 订单号格式（要求 ORD 前缀，避免误匹配手机号）
    (re.compile(r"ORD[-\s]?\d{10,20}"), IntentType.ORDER_QUERY),
    # 商品创建：创建/新建/添加/上架 + 商品名（不包含"订单"/"工单"/"售后"上下文）
    (re.compile(r"(?:创建|新建|添加|上架)(?:一个|新的|个)?(?:商品|产品|窗帘|布料|色卡|抱枕|靠垫|桌布|窗纱|卷帘|百叶|罗马帘|床品|沙发垫|桌旗|遮光)"), IntentType.PRODUCT_INQUIRY),
    # 创建/新建 + 任意商品描述（排除含"订单/工单/售后/员工/账号/角色/权限/分类/通知/会话"的，
    # 防止"创建员工账号/新建分类/添加通知"等非商品意图被泛化规则劫持 —— HR-002 修复）
    (re.compile(r"(?:创建|新建|添加)(?!.*(?:订单|工单|售后|员工|账号|角色|权限|分类|通知|会话))(?:一个|新的|个)?.{0,10}(?:商品|产品|窗帘|布料|色卡|窗纱|卷帘|百叶)?"), IntentType.PRODUCT_INQUIRY),
    # 算料报价：尺寸数字（如"3米宽/3×2.7"）+ 褶皱/倍数/算料/报价 → 算料意图。
    # 例："3米窗 2倍褶皱 多少钱"、"2.7米高 打孔帘 报价"
    (re.compile(r"\d+(?:\.\d+)?\s*米?.{0,10}(?:褶皱|倍数|算料|报价|用布|打孔|韩式褶|四爪钩)"), IntentType.QUOTE),
]

# 直接回复内容已迁移到 AgentConfig.direct_replies
# 参见 agents/mibao.py 和 agents/xiaobu.py 中的配置
# GREETING_REPLIES / FAREWELL_REPLIES / CAPABILITIES_REPLIES 已删除，
# 现在由 AgentConfig.get_direct_reply(intent) 统一提供


class RuleMatcher:
    """
    L1 规则匹配器
    
    通过关键词和正则表达式进行快速意图匹配，
    命中后返回高置信度结果，无需调用小模型。
    """

    def match(self, message: Union[str, list, None]) -> Optional[IntentResult]:
        """
        对用户消息进行规则匹配

        Args:
            message: 用户消息文本（str 或多模态 list）

        Returns:
            IntentResult 或 None（未命中）
        """
        text = _extract_text(message)
        if not text or not text.strip():
            return None

        msg_lower = text.strip().lower()

        # 1. 关键词匹配
        # --- 优先匹配 capabilities（长短语，避免被其他意图抢占） ---
        cap_keywords = KEYWORD_MAP.get(IntentType.CAPABILITIES, [])
        cap_matched = [kw for kw in cap_keywords if kw.lower() in msg_lower]
        if cap_matched:
            return IntentResult(
                intent=IntentType.CAPABILITIES,
                confidence=1.0,
                source="rule",
                matched_keywords=cap_matched,
            )

        # --- 优先匹配 farewell（"谢谢，再见" 等组合也应被识别） ---
        farewell_keywords = KEYWORD_MAP.get(IntentType.FAREWELL, [])
        farewell_matched = [kw for kw in farewell_keywords if kw.lower() in msg_lower]
        if farewell_matched:
            return IntentResult(
                intent=IntentType.FAREWELL,
                confidence=1.0,
                source="rule",
                matched_keywords=farewell_matched,
            )

        # --- 优先匹配「订单统计/订单数据」→ order_query（订单域统计） ---
        # 否则会被下方 STATISTICS 的"统计"关键词抢先匹配，误路由到经营看板。
        if "订单" in msg_lower and ("统计" in msg_lower or "数据" in msg_lower):
            return IntentResult(
                intent=IntentType.ORDER_QUERY,
                confidence=0.95,
                source="rule",
                matched_keywords=["订单统计"],
            )

        # --- 优先匹配「尺寸数字 + 褶皱/算料/报价」→ quote（算料报价） ---
        # 否则"3米窗 2倍褶皱 多少钱"会被"多少钱"(3字) 压过"褶皱"(2字) 误路由到商品咨询。
        # 尺寸 + 褶皱/倍数 是算料意图的强信号，前置拦截。
        _quote_dim = re.compile(
            r"\d+(?:\.\d+)?\s*米?.{0,10}(?:褶皱|倍数|算料|报价|用布|打孔|韩式褶|四爪钩)"
        )
        if _quote_dim.search(text):
            return IntentResult(
                intent=IntentType.QUOTE,
                confidence=0.95,
                source="rule",
                matched_keywords=["尺寸+褶皱"],
            )

        # 收集所有命中的意图，而不是第一个命中即返回。
        # 跨域消息（如"给订单X创建退款工单"同时含"订单"+"退款"）存在多个候选意图时，
        # L1 不看对话历史硬猜会抢错路由（生产回归：售后工单创建被"订单/商品"抢占），
        # 此时返回 None 降级 L2 分类器（带 chat_history + agent_intents）裁决。
        matched_intents: dict[IntentType, IntentResult] = {}

        for intent, keywords in KEYWORD_MAP.items():
            # capabilities 和 farewell 已在上面处理
            if intent in (IntentType.CAPABILITIES, IntentType.FAREWELL):
                continue

            matched = [kw for kw in keywords if kw.lower() in msg_lower]
            if not matched:
                continue
            # Greeting 意图：消息非常短且完全匹配时才视为纯问候
            if intent == IntentType.GREETING and len(msg_lower) > 10:
                continue
            confidence = 1.0 if intent == IntentType.GREETING else 0.95
            matched_intents[intent] = IntentResult(
                intent=intent,
                confidence=confidence,
                source="rule",
                matched_keywords=matched,
            )

        # 2. 正则规则匹配（同样收集，不抢先返回）
        for pattern, intent in REGEX_RULES:
            if pattern.search(text):
                # 正则命中与关键词命中属于同一意图时保留关键词结果（信息更丰富）
                if intent not in matched_intents:
                    matched_intents[intent] = IntentResult(
                        intent=intent,
                        confidence=0.9,
                        source="rule",
                        matched_keywords=[f"regex:{pattern.pattern}"],
                    )

        if len(matched_intents) == 1:
            return next(iter(matched_intents.values()))

        if len(matched_intents) > 1:
            # 多意图：按关键词特异性裁决——最长命中关键词的意图胜出。
            # 例："创建订单" → ORDER_CREATE("创建订单"4字) 胜过 ORDER_QUERY("订单"2字)；
            # "给订单X创建退款工单" → 各意图最长词均为 2 字（订单/退款）→ 打平 → None（L2）。
            # 注意：regex 命中不计长度（"regex:<pattern>" 字符串远长于真实关键词，
            # 会让正则意图虚假胜出，如 "ORD123 要退款" 被 ORD 正则抢走）。
            best_len = -1
            best_intent: Optional[IntentResult] = None
            tie = False
            for intent, result in matched_intents.items():
                real_keywords = [kw for kw in result.matched_keywords if not kw.startswith("regex:")]
                max_len = max((len(kw) for kw in real_keywords), default=0)
                if max_len > best_len:
                    best_len = max_len
                    best_intent = result
                    tie = False
                elif max_len == best_len:
                    tie = True
            if best_intent is not None and not tie:
                return best_intent

        # 0 个命中 → None；多意图且特异性打平 → None（歧义交给 L2）
        return None
