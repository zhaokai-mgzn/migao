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

    summary 字段: LLM 友好的摘要文本。若为 None，fallback 到 message。
    suggestion 字段: 失败时必须填写，告诉 LLM 如何引导用户修复问题。
    每个 tool 应自行设定 summary，确保 LLM 能快速理解结果。
    示例: ToolResult(success=True, data={...}, summary="共3个分类: 卧室系列,窗帘布艺,测试分类")
    """
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    message: Optional[str] = Field(None, description="提示消息（给用户看的）")
    summary: Optional[str] = Field(None, description="LLM友好摘要（每个tool自行填写）")
    suggestion: Optional[str] = Field(None, description="失败时的修复建议（给LLM看，帮助引导用户）")

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

    # MCP 风格 Tool Annotations — 帮助 LLM 做工具选择决策
    # read_only=True  → 纯查询，LLM 可放心调用，无需确认
    # read_only=False → 会修改数据，LLM 应先确认再调用
    # destructive=True → 可执行不可逆的删除/销毁操作，LLM 必须弹 confirm 卡片
    # idempotent=True → 相同参数多次调用结果一致，可安全重试
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True

    # 权限控制
    require_auth: bool = True
    allowed_roles: list[str] = ["customer", "admin", "agent", "tenant_admin"]
    
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

        description 中自动注入工具类型标注（read_only/destructive/idempotent），
        帮助 LLM 在 tool choice 阶段做出更好的选择决策。

        Returns:
            Dict: OpenAI function schema 格式
        """
        # 构建工具类型标注
        tags = []
        if self.read_only:
            tags.append("READONLY")
        else:
            tags.append("WRITE")
        if self.destructive:
            tags.append("DESTRUCTIVE")
        if not self.idempotent:
            tags.append("NON_IDEMPOTENT")

        tagged_desc = f"[{'|'.join(tags)}] {self.description}"

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": tagged_desc,
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
