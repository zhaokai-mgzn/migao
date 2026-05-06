"""
AI 智能客服系统 - API Schema 定义

对话相关的 Pydantic 模型
"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field


class ChatSendRequest(BaseModel):
    """发送消息请求"""
    session_id: Optional[str] = Field(None, description="会话 ID，不传则创建新会话")
    message: str = Field(..., description="用户消息内容")
    images: Optional[List[str]] = Field(None, description="图片URL列表")


class ChatSessionCreate(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, description="会话标题，不传则自动生成")


class ChatMessageResponse(BaseModel):
    """聊天消息响应"""
    id: str = Field(..., description="消息 ID")
    session_id: str = Field(..., description="会话 ID")
    role: str = Field(..., description="消息角色: user / assistant / system")
    content: str = Field(..., description="消息内容")
    content_type: str = Field("text", description="内容类型: text / mixed")
    images: Optional[List[str]] = Field(None, description="图片URL列表")
    tool_calls: Optional[List[dict]] = Field(None, description="Tool 调用信息")
    created_at: str = Field(..., description="创建时间 ISO 格式")


class ChatSessionResponse(BaseModel):
    """会话响应"""
    id: str = Field(..., description="会话 ID")
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    title: str = Field(..., description="会话标题")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
    message_count: int = Field(0, description="消息数量")


class SSETextEvent(BaseModel):
    """SSE 文本事件数据"""
    content: str = Field(..., description="文本内容")


class SSEToolCallEvent(BaseModel):
    """SSE Tool 调用事件数据"""
    tool: str = Field(..., description="Tool 名称")
    args: dict = Field(default_factory=dict, description="Tool 参数")


class SSEToolResultEvent(BaseModel):
    """SSE Tool 结果事件数据"""
    tool: str = Field(..., description="Tool 名称")
    result: dict = Field(default_factory=dict, description="Tool 执行结果")


class SSECardEvent(BaseModel):
    """SSE 卡片事件数据"""
    type: str = Field(..., description="卡片类型: product_list / product_detail / logistics / order")
    data: Any = Field(..., description="卡片数据")


class SSEDoneEvent(BaseModel):
    """SSE 完成事件数据"""
    session_id: str = Field(..., description="会话 ID")
    message_id: str = Field(..., description="消息 ID")


class SSEErrorEvent(BaseModel):
    """SSE 错误事件数据"""
    message: str = Field(..., description="错误信息")
    code: Optional[str] = Field(None, description="错误码")
