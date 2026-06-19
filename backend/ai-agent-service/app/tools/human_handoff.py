"""
AI 智能客服系统 - 转人工客服 Tool

当智能客服无法处理用户请求时，将对话转接给人工客服。
生成唯一 handoff_id 用于追踪，记录转接原因、优先级和对话摘要。
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult

# 北京时间时区
TZ_BEIJING = timezone(timedelta(hours=8))

VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


class HumanHandoffTool(BaseTool):
    """转人工客服 Tool

    当智能客服遇到以下情况时调用：
    - 复杂投诉（涉及赔偿、质量纠纷等）
    - 退换货、退款等操作性需求
    - 用户明确要求转人工
    - 多次沟通未能解决问题
    - 超出智能客服能力范围的问题

    本 Tool 不调用外部 API，仅记录转接请求并返回结构化确认。
    实际转接由前端/会话管理层根据 handoff_id 处理。
    """

    name = "human_handoff"
    description = (
        "【触发】用户要求转人工、投诉升级、退款/退货需求、或多次沟通无法解决时调用。"
        "【前置】需要 reason（转接原因），可选 priority（优先级）和 summary（对话摘要）。"
        "【后置】返回 handoff_id 供追踪，实际转接由系统处理。"
        "【反例】普通咨询(商品/订单/物流)不要转人工，先尝试工具查询解决。"
        "【标注】WRITE — 会创建人工服务请求，需确认后执行"
    )

    read_only = False
    destructive = False
    idempotent = False

    allowed_roles = ["customer", "admin", "agent", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "转人工原因，如：退款申请、质量投诉、复杂售后、用户明确要求",
            },
            "priority": {
                "type": "string",
                "description": "优先级：low（普通咨询）/ normal（一般问题，默认）/ high（投诉升级）/ urgent（紧急）",
            },
            "summary": {
                "type": "string",
                "description": "当前对话摘要，帮助人工客服快速了解上下文",
            },
        },
        "required": ["reason"],
    }

    async def execute(
        self,
        context: ToolContext,
        reason: str,
        priority: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> ToolResult:
        """执行转人工请求

        Args:
            context: Tool 执行上下文
            reason: 转人工原因
            priority: 优先级，默认 normal
            summary: 对话摘要

        Returns:
            ToolResult: 包含 handoff_id 和状态的结构化结果
        """
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行转人工操作",
                suggestion="请联系管理员获取权限",
            )

        # 校验优先级
        effective_priority = priority or "normal"
        if effective_priority not in VALID_PRIORITIES:
            effective_priority = "normal"
            logger.warning(
                f"[human_handoff] Invalid priority '{priority}', "
                f"falling back to 'normal' | tenant={context.tenant_id}"
            )

        # 生成唯一 handoff_id
        handoff_id = f"HO-{uuid.uuid4().hex[:12].upper()}"
        created_at = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M:%S")

        # 记录审计日志
        logger.info(
            f"[AUDIT] human_handoff handoff_id={handoff_id} "
            f"tenant={context.tenant_id} user={context.user_id} "
            f"session={context.session_id} priority={effective_priority} "
            f"reason={reason[:100]}"
        )

        # 构建优先级中文标签
        priority_labels = {
            "low": "低优先级",
            "normal": "普通",
            "high": "高优先级",
            "urgent": "紧急",
        }
        priority_label = priority_labels.get(effective_priority, "普通")

        data = {
            "handoff_id": handoff_id,
            "status": "queued",
            "priority": effective_priority,
            "reason": reason,
            "summary": summary or "",
            "created_at": created_at,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "session_id": context.session_id,
        }

        # 构建用户可见消息
        if effective_priority in ("high", "urgent"):
            urgency_note = f"（{priority_label}）"
        else:
            urgency_note = ""

        message = (
            f"已为您转接人工客服{urgency_note}，请稍等~ "
            f"工单号：{handoff_id}"
        )

        summary_text = (
            f"转人工请求已提交: {handoff_id}, "
            f"优先级: {priority_label}, "
            f"原因: {reason[:50]}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=message,
            summary=summary_text,
        )
