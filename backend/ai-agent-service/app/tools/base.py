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


def _auto_summary(data: Any, max_items: int = 15, max_str: int = 500) -> str:
    """从 ToolResult.data 自动生成 LLM 友好的摘要，减少 LLM 解析损耗"""
    if data is None:
        return ""
    if isinstance(data, list):
        if len(data) == 0:
            return "共0条"
        total = len(data)
        if total <= 3:
            names = [str(d.get("name", d.get("id", str(d)[:30]))) for d in data if isinstance(d, dict)]
            return f"共{total}条: " + ", ".join(names)
        names = [str(d.get("name", d.get("id", str(d)[:20]))) for d in data[:max_items] if isinstance(d, dict)]
        suffix = f"等{total}条" if total > max_items else f"共{total}条"
        return f"{suffix}: " + ", ".join(names[:5]) + ("..." if len(names) > 5 else "")
    if isinstance(data, dict):
        # 处理常见嵌套: items, tree, records, orders, products
        for key in ("items", "records", "orders", "products", "tree"):
            if key in data and isinstance(data[key], list):
                inner = data[key]
                total = data.get("total", len(inner))
                if len(inner) == 0:
                    return f"共0条"
                names = []
                for d in inner[:5]:
                    if isinstance(d, dict):
                        name = d.get("name", d.get("orderNo", d.get("id", str(d)[:30])))
                        status = d.get("status", d.get("status_text", ""))
                        if status:
                            name += f"({status})"
                        names.append(str(name))
                more = f"等{total}条" if total > 5 else f"共{total}条"
                return more + ": " + ", ".join(names)
        # 统计类数据
        if any(k in data for k in ("totalCount", "pendingCount", "todayOrders", "monthRevenue")):
            parts = [f"{k}={v}" for k, v in data.items() if v is not None and not k.startswith("_")]
            return "统计: " + ", ".join(parts[:10])
        # 单对象: 取前几个关键字段
        keys = [k for k in data.keys() if not k.startswith("_")][:8]
        parts = [f"{k}={str(v)[:40]}" for k, v in [(k, data[k]) for k in keys] if v is not None]
        return "; ".join(parts[:6])
    return str(data)[:max_str]


class ToolResult(BaseModel):
    """Tool 执行结果

    统一的结果格式，包含状态、数据和错误信息。
    summary 字段自动从 data 生成 LLM 友好摘要，减少 LLM 解析损耗。
    """
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    message: Optional[str] = Field(None, description="提示消息（给用户看的）")
    summary: Optional[str] = Field(None, description="LLM友好摘要（自动生成）")

    class Config:
        extra = "allow"

    def model_post_init(self, __context):
        """自动生成 summary"""
        if self.summary is None and self.success and self.data is not None:
            self.summary = _auto_summary(self.data)


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
