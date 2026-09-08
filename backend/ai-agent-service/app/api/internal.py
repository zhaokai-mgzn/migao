"""
内部 API 路由（Service Token 认证）

提供内部服务之间的调用接口：
- Tool 执行接口（供 admin-api 反向调用）
- 会话知识提炼（LLM WIKI 板块 P5b，issue #3051：客服会话 → 知识卡片候选）
- 健康检查
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.utils.auth import verify_service_token
from app.tools import ToolContext, get_tool_registry
from app.api.response_models import make_response
from app.knowledge.distill import distill

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    """Tool 执行请求"""
    tool_name: str = Field(..., description="Tool 名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="Tool 参数")
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")


class KnowledgeDistillRequest(BaseModel):
    """会话知识提炼请求"""
    tenant_id: int = Field(..., description="租户 ID")
    conversation_text: str = Field(..., description="待提炼文本（客服会话 或 店铺资料文档）")
    max_candidates: int = Field(5, ge=1, le=10, description="最多提炼候选数")
    mode: str = Field("conversation", description="提炼模式：conversation（客服问答对）/ document（文档→FAQ 条目）")


@router.post("/tools/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    执行 Tool（内部服务调用）
    
    由 admin-api 通过 Service Token 调用，用于反向触发 Agent Tool 执行。
    例如：admin-api 需要 AI 服务执行某个 Tool 获取结果。
    """
    registry = get_tool_registry()
    tool = registry.get_tool(request.tool_name)

    # 检查 Tool 是否存在
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "TOOL_NOT_FOUND",
                    "message": f"Tool '{request.tool_name}' not found",
                }
            }
        )

    # 安全加固：内部反向调用仅允许只读工具。写操作必须走用户侧对话流程
    # （LLM 决策 + interact confirm 卡片），防止 SERVICE_TOKEN 泄露后被用于
    # 对任意租户执行破坏性写操作。
    if not getattr(tool, "read_only", True):
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "WRITE_TOOL_FORBIDDEN",
                    "message": f"Tool '{request.tool_name}' 是写操作，禁止通过内部接口执行",
                }
            }
        )

    # 构建上下文
    context = ToolContext(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        session_id=request.session_id,
        role="admin",  # 内部调用使用 admin 角色
        permissions=["*"],  # admin 拥有全部细粒度权限（与后端 admin 角色口径一致）
    )
    
    # 执行 Tool
    try:
        result = await registry.execute_tool(
            request.tool_name,
            context,
            **request.params,
        )
        
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "message": result.message,
        }
    except Exception as e:
        logger.error(f"Internal tool execution error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Tool execution failed: {str(e)}",
                }
            }
        )


@router.get("/tools")
async def list_tools(
    authorized: bool = Depends(verify_service_token),
):
    """
    获取所有可用 Tool 列表（内部接口）
    """
    registry = get_tool_registry()
    
    tools = []
    for tool in registry.get_all_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        })
    
    return {
        "success": True,
        "data": {
            "tools": tools,
            "count": len(tools),
        }
    }


@router.post("/knowledge/distill")
async def distill_knowledge(
    request: KnowledgeDistillRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    会话知识提炼（LLM WIKI 板块 P5b，issue #3051）

    admin-api 把人工客服会话文本传来，AI 提炼为「顾客问题 → 标准回答」知识卡片候选，
    返回候选列表由 admin-api 写入待确认队列（knowledge_candidates），商家采纳后生效。
    提炼失败降级返回空候选（不阻断 admin-api 流程）。
    """
    logger.info(
        f"Knowledge distill triggered: tenant_id={request.tenant_id}, "
        f"text_len={len(request.conversation_text or '')}, max_candidates={request.max_candidates}"
    )
    candidates = await distill(request.conversation_text, max_candidates=request.max_candidates, mode=request.mode)
    return make_response(True, data={"candidates": candidates})
