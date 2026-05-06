"""
AI 智能客服系统 - Tool 基础设施

提供 Tool 基类和上下文定义，所有 Tool 必须继承 BaseTool。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from loguru import logger


class ToolContext(BaseModel):
    """Tool 执行上下文
    
    包含租户信息、用户信息、会话信息等，用于多租户隔离和权限控制。
    """
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")
    role: str = Field("customer", description="用户角色: customer/admin/agent")
    
    class Config:
        arbitrary_types_allowed = True


class ToolResult(BaseModel):
    """Tool 执行结果
    
    统一的结果格式，包含状态、数据和错误信息。
    """
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    message: Optional[str] = Field(None, description="提示消息（给用户看的）")
    
    class Config:
        extra = "allow"


class BaseTool(ABC):
    """Tool 基类
    
    所有 Tool 必须继承此类，并实现 execute 方法。
    
    示例：
        class ProductSearchTool(BaseTool):
            name = "product_search"
            description = "搜索商品列表"
            
            async def execute(self, context: ToolContext, keyword: str = "") -> ToolResult:
                # 实现搜索逻辑
                return ToolResult(success=True, data={...})
    """
    
    # Tool 元数据（子类必须定义）
    name: str = ""
    description: str = ""
    
    # 参数 JSON Schema（用于 LangChain/OpenAI function calling）
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }
    
    # 权限控制
    require_auth: bool = True
    allowed_roles: list[str] = ["customer", "admin", "agent"]
    
    def __init__(self):
        """初始化 Tool"""
        if not self.name:
            raise ValueError(f"{self.__class__.__name__} must define 'name'")
        if not self.description:
            raise ValueError(f"{self.__class__.__name__} must define 'description'")
    
    @abstractmethod
    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        """执行 Tool
        
        Args:
            context: Tool 执行上下文，包含租户、用户等信息
            **kwargs: Tool 特定参数
            
        Returns:
            ToolResult: 执行结果
        """
        pass
    
    def check_permission(self, context: ToolContext) -> bool:
        """检查权限
        
        Args:
            context: Tool 执行上下文
            
        Returns:
            bool: 是否有权限执行
        """
        if not self.require_auth:
            return True
        
        return context.role in self.allowed_roles
    
    def get_schema(self) -> Dict[str, Any]:
        """获取 LangChain/OpenAI 兼容的 function schema
        
        Returns:
            Dict: OpenAI function schema 格式
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
    
    def to_langchain_tool(self) -> Any:
        """转换为 LangChain Tool 格式
        
        Returns:
            StructuredTool: LangChain 兼容的 Tool 对象
        """
        from langchain_core.tools import StructuredTool
        
        async def _execute(**kwargs):
            # 注意：这里需要外部注入 context
            # 实际调用时会通过 agent 传递 context
            logger.debug(f"Executing {self.name} with params: {kwargs}")
            # 返回空，实际逻辑在 agent 中处理
            return {"tool": self.name, "params": kwargs}
        
        return StructuredTool.from_function(
            func=_execute,
            name=self.name,
            description=self.description,
            args_schema=self._get_args_schema(),
        )
    
    def _get_args_schema(self) -> Optional[type]:
        """获取参数 Pydantic Schema（用于 LangChain）
        
        Returns:
            Optional[type]: Pydantic BaseModel 类或 None
        """
        # 从 parameters 动态生成 Pydantic 模型
        # 简化实现：返回 None，使用默认的字典参数
        return None
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
    
    def __str__(self) -> str:
        return self.name
