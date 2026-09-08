"""
AI 智能客服系统 - 知识卡片检索 Tool（LLM WIKI 板块 P7，issue #3051）

检索本店已发布的知识卡片（knowledge_cards status=published），命中则基于卡片回答，
未命中走 LLM 通用知识兜底。检索用结构化过滤 + 关键词（无向量库），租户隔离由 admin-api 强制。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class KnowledgeSearchTool(BaseTool):
    """知识卡片检索 Tool

    检索本店已发布的知识卡片（来源：行业模板/商品派生/会话提炼/文档提炼/人工维护）。
    """

    name = "knowledge_search"
    description = (
        "【触发】顾客问本店知识类问题（面料特性/清洗保养/尺寸测量/价格政策/售后规则/加工计价等）时调用，"
        "检索本店已发布的知识卡片。【前置】query 传顾客问题的关键词。【行为】命中→基于卡片内容回答并注明"
        "「📖 来自本店知识库」；未命中→如实告知知识库暂无收录，可用通用行业知识谨慎回答（注明通用建议）。"
        "【反例】实时价格/库存/订单仍用 product_search/order_query 等工具；不得编造卡片之外的本店事实。"
        "【标注】READONLY — 放心调用，无需确认"
    )
    allowed_roles = ["customer", "admin", "agent", "tenant_admin", "operator"]

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词（顾客问题核心词），如'雪尼尔'、'多久洗一次'、'褶皱倍数'",
            },
            "category": {
                "type": "string",
                "description": "分类筛选（可选）：faq / product / measure / aftersale / config",
                "enum": ["faq", "product", "measure", "aftersale", "config"],
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        context: ToolContext,
        query: str,
        category: Optional[str] = None,
    ) -> ToolResult:
        """执行知识卡片检索

        Args:
            context: Tool 执行上下文
            query: 检索关键词
            category: 分类筛选（可选）
        """
        query = (query or "").strip()
        if not query:
            return ToolResult(
                success=False,
                error="缺少检索关键词",
                message="请提供检索关键词",
                suggestion="补充顾客问题的关键词后再检索",
            )
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限检索本店知识",
                suggestion="请联系管理员开通知识库查看权限",
            )

        try:
            params: Dict[str, Any] = {"query": query}
            if category:
                params["category"] = category

            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/knowledge/cards/search",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "检索失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message="知识检索失败，请稍后重试",
                )

            cards = response.get("data") or []
            if not cards:
                return ToolResult(
                    success=True,
                    data={"cards": [], "hit": False},
                    message="本店知识库暂无收录该内容，请用通用行业知识谨慎回答并注明通用建议，或引导转人工",
                )

            # 最多取 3 条进上下文，answer 截断防超长
            brief: List[Dict[str, Any]] = []
            for c in cards[:3]:
                answer = str(c.get("answer") or "")
                brief.append({
                    "title": c.get("title"),
                    "answer": answer[:500],
                    "category": c.get("category"),
                    "sourceType": c.get("sourceType"),
                })
            return ToolResult(
                success=True,
                data={"cards": brief, "hit": True},
                message=f"找到 {len(brief)} 条本店知识卡片，基于卡片内容回答并注明「📖 来自本店知识库」",
            )
        except Exception as e:
            logger.warning(f"[knowledge-search] 检索异常: {e}")
            return ToolResult(
                success=False,
                error="知识检索暂不可用",
                message="知识检索暂不可用，请用通用行业知识谨慎回答并注明通用建议",
            )
