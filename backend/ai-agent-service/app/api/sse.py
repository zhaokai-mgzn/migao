"""
AI 智能客服系统 - SSE 事件助手

提供 SSE (Server-Sent Events) 事件构建工具
"""

import json
from typing import Any, Optional


class SSEEvent:
    """SSE 事件构建器"""
    
    @staticmethod
    def text(content: str) -> str:
        """
        文本事件
        
        Args:
            content: 文本内容
            
        Returns:
            SSE 格式字符串
        """
        return f"event: text\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
    
    @staticmethod
    def tool_call(tool_name: str, args: dict) -> str:
        """
        Tool 调用事件
        
        Args:
            tool_name: Tool 名称
            args: Tool 参数
            
        Returns:
            SSE 格式字符串
        """
        return f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'args': args}, ensure_ascii=False)}\n\n"
    
    @staticmethod
    def tool_result(tool_name: str, result: dict) -> str:
        """
        Tool 结果事件
        
        Args:
            tool_name: Tool 名称
            result: Tool 执行结果
            
        Returns:
            SSE 格式字符串
        """
        return f"event: tool_result\ndata: {json.dumps({'tool': tool_name, 'result': result}, ensure_ascii=False)}\n\n"
    
    @staticmethod
    def card(card_type: str, data: Any) -> str:
        """
        卡片事件
        
        Args:
            card_type: 卡片类型 (product_list / product_detail / logistics / order)
            data: 卡片数据
            
        Returns:
            SSE 格式字符串
        """
        return f"event: card\ndata: {json.dumps({'type': card_type, 'data': data}, ensure_ascii=False)}\n\n"
    
    @staticmethod
    def done(session_id: str, message_id: str) -> str:
        """
        完成事件
        
        Args:
            session_id: 会话 ID
            message_id: 消息 ID
            
        Returns:
            SSE 格式字符串
        """
        return f"event: done\ndata: {json.dumps({'session_id': session_id, 'message_id': message_id})}\n\n"
    
    @staticmethod
    def error(message: str, code: Optional[str] = None) -> str:
        """
        错误事件
        
        Args:
            message: 错误信息
            code: 错误码（可选）
            
        Returns:
            SSE 格式字符串
        """
        data = {"message": message}
        if code:
            data["code"] = code
        return f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    @staticmethod
    def heartbeat() -> str:
        """
        心跳事件
        
        Returns:
            SSE 格式字符串
        """
        return ": heartbeat\n\n"
    
    @staticmethod
    def suggestions(questions: list[str]) -> str:
        """
        后续问题建议事件
        
        Args:
            questions: 建议的后续问题列表
            
        Returns:
            SSE 格式字符串
        """
        return f"event: suggestions\ndata: {json.dumps({'questions': questions}, ensure_ascii=False)}\n\n"

    @staticmethod
    def loading(content: str = "正在处理...") -> str:
        """
        加载状态事件
        
        Args:
            content: 加载提示文本
            
        Returns:
            SSE 格式字符串
        """
        return f"event: loading\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"


class SSEStreamBuilder:
    """SSE 流构建器（用于复杂场景）"""
    
    def __init__(self):
        self.events = []
    
    def add_text(self, content: str) -> "SSEStreamBuilder":
        """添加文本事件"""
        self.events.append(SSEEvent.text(content))
        return self
    
    def add_tool_call(self, tool_name: str, args: dict) -> "SSEStreamBuilder":
        """添加 Tool 调用事件"""
        self.events.append(SSEEvent.tool_call(tool_name, args))
        return self
    
    def add_tool_result(self, tool_name: str, result: dict) -> "SSEStreamBuilder":
        """添加 Tool 结果事件"""
        self.events.append(SSEEvent.tool_result(tool_name, result))
        return self
    
    def add_card(self, card_type: str, data: Any) -> "SSEStreamBuilder":
        """添加卡片事件"""
        self.events.append(SSEEvent.card(card_type, data))
        return self
    
    def add_done(self, session_id: str, message_id: str) -> "SSEStreamBuilder":
        """添加完成事件"""
        self.events.append(SSEEvent.done(session_id, message_id))
        return self
    
    def add_error(self, message: str, code: Optional[str] = None) -> "SSEStreamBuilder":
        """添加错误事件"""
        self.events.append(SSEEvent.error(message, code))
        return self
    
    def add_loading(self, content: str = "正在处理...") -> "SSEStreamBuilder":
        """添加加载事件"""
        self.events.append(SSEEvent.loading(content))
        return self
    
    def build(self) -> str:
        """构建完整的 SSE 响应字符串"""
        return "".join(self.events)
    
    def __iter__(self):
        """支持迭代"""
        return iter(self.events)
