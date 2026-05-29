"""
AI 智能客服系统 - Tool 注册器

提供 Tool 的注册、管理和获取功能。
支持通过 contextvars 注入 ToolContext，让 LangChain Tool 能够调用实际的业务逻辑。
"""

import json
import time
import contextvars
from typing import Dict, List, Optional, Any, Type
from loguru import logger
from pydantic import BaseModel, Field, create_model

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.langchain_adapter import LangChainToolAdapter
from app.utils.http_client import AdminApiClient
from app.utils.log_sanitizer import LogSanitizer

# 全局 ToolContext，用于在 LangChain Tool 执行时传递上下文
_current_tool_context: contextvars.ContextVar[Optional[ToolContext]] = contextvars.ContextVar(
    'current_tool_context', default=None
)


def set_tool_context(context: ToolContext) -> None:
    """设置当前请求的 Tool 执行上下文"""
    _current_tool_context.set(context)


def get_tool_context() -> Optional[ToolContext]:
    """获取当前请求的 Tool 执行上下文"""
    return _current_tool_context.get()


class ToolRegistry:
    """Tool 注册器
    
    管理所有可用的 Tool，提供注册、获取和 LangChain 兼容接口。
    
    使用示例：
        registry = ToolRegistry()
        registry.register(ProductSearchTool())
        
        # 获取 Tool
        tool = registry.get_tool("product_search")
        
        # 获取所有 Tool
        tools = registry.get_all_tools()
        
        # 获取 LangChain 兼容格式
        langchain_tools = registry.get_langchain_tools()
    """
    
    def __init__(self):
        """初始化 Tool 注册器"""
        self._tools: Dict[str, BaseTool] = {}
        self._admin_api_client: Optional[AdminApiClient] = None
    
    def register(self, tool: BaseTool) -> "ToolRegistry":
        """注册 Tool
        
        Args:
            tool: Tool 实例
            
        Returns:
            ToolRegistry: 支持链式调用
            
        Raises:
            ValueError: 如果 Tool 名称已存在
        """
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")
        return self
    
    def unregister(self, name: str) -> bool:
        """注销 Tool
        
        Args:
            name: Tool 名称
            
        Returns:
            bool: 是否成功注销
        """
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Tool unregistered: {name}")
            return True
        return False
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取 Tool
        
        Args:
            name: Tool 名称
            
        Returns:
            Optional[BaseTool]: Tool 实例或 None
        """
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有已注册的 Tool
        
        Returns:
            List[BaseTool]: Tool 列表
        """
        return list(self._tools.values())
    
    def get_tool_names(self) -> List[str]:
        """获取所有 Tool 名称
        
        Returns:
            List[str]: Tool 名称列表
        """
        return list(self._tools.keys())
    
    def has_tool(self, name: str) -> bool:
        """检查 Tool 是否存在
        
        Args:
            name: Tool 名称
            
        Returns:
            bool: 是否存在
        """
        return name in self._tools
    
    def get_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Tool 的 JSON Schema
        
        Returns:
            List[Dict]: OpenAI function schema 列表
        """
        return [tool.get_schema() for tool in self._tools.values()]
    
    def get_tools_description(self) -> str:
        """获取 Tool 描述文本
        
        用于生成系统提示词中的 Tool 说明。
        
        Returns:
            str: Tool 描述文本
        """
        if not self._tools:
            return "暂无可用工具"
        
        descriptions = []
        for name, tool in self._tools.items():
            descriptions.append(f"- {name}: {tool.description}")
        
        return "\n".join(descriptions)
    
    def get_langchain_tools(self) -> List[Any]:
        """获取 LangChain 兼容的 Tool 列表
        
        每个 LangChain Tool 通过 contextvars 获取 ToolContext，
        实际调用对应 BaseTool 的 execute 方法。
        
        Returns:
            List: LangChain Tool 列表
        """
        langchain_tools = []
        for tool in self._tools.values():
            lc_tool = LangChainToolAdapter.create_langchain_tool(
                tool=tool,
                get_context_func=get_tool_context,
            )
            langchain_tools.append(lc_tool)
        
        return langchain_tools
    
    @staticmethod
    def _build_args_schema(tool: BaseTool) -> Optional[Type[BaseModel]]:
        """从 Tool 的 parameters JSON Schema 动态生成 Pydantic 模型
        
        Args:
            tool: 原始 Tool
            
        Returns:
            Optional[Type[BaseModel]]: Pydantic 模型类，用作 args_schema
        """
        props = tool.parameters.get("properties", {})
        if not props:
            return None
        
        required_fields = set(tool.parameters.get("required", []))
        
        # JSON Schema type -> Python type 映射
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        field_definitions = {}
        for field_name, field_schema in props.items():
            py_type = type_map.get(field_schema.get("type", "string"), str)
            description = field_schema.get("description", "")
            default = field_schema.get("default", ...)
            
            if field_name in required_fields:
                field_definitions[field_name] = (
                    py_type,
                    Field(description=description),
                )
            else:
                # 可选参数
                field_definitions[field_name] = (
                    Optional[py_type],
                    Field(default=default if default is not ... else None, description=description),
                )
        
        if not field_definitions:
            return None
        
        # 动态创建 Pydantic 模型
        model_name = f"{tool.name.title().replace('_', '')}Args"
        return create_model(model_name, **field_definitions)
    
    def _create_langchain_tool(self, tool: BaseTool) -> Any:
        """创建 LangChain Tool（已废弃，使用 LangChainToolAdapter）
        
        Args:
            tool: 原始 Tool
            
        Returns:
            StructuredTool: LangChain Tool
        """
        return LangChainToolAdapter.create_langchain_tool(
            tool=tool,
            get_context_func=get_tool_context,
        )
    
    async def execute_tool(
        self,
        name: str,
        context: ToolContext,
        **kwargs,
    ) -> ToolResult:
        """执行指定 Tool
        
        Args:
            name: Tool 名称
            context: Tool 执行上下文
            **kwargs: Tool 参数
            
        Returns:
            ToolResult: 执行结果
            
        Raises:
            ValueError: 如果 Tool 不存在
        """
        tool = self.get_tool(name)
        if not tool:
            logger.warning(f"[tool-registry] Tool not found: {name}")
            return ToolResult(
                success=False,
                error=f"Tool '{name}' not found",
                message=f"未知工具：{name}",
            )
        
        # 权限检查
        if not tool.check_permission(context):
            logger.info(f"[tool-registry] Permission denied: {name} | tenant={context.tenant_id} role={context.role if hasattr(context, 'role') else 'unknown'}")
            return ToolResult(
                success=False,
                error="Permission denied",
                message="您没有权限使用该功能",
            )
        
        try:
            logger.info(f"[tool-registry] Executing: {name} | tenant={context.tenant_id}")
            start = time.time()
            result = await tool.execute(context, **kwargs)
            duration_ms = (time.time() - start) * 1000
            logger.info(f"[tool-registry] Completed: {name} | success={result.success} duration={duration_ms:.1f}ms | tenant={context.tenant_id}")
            return result
        except Exception as e:
            # 记录详细错误信息到日志（包含租户上下文便于排查）
            logger.error(
                f"[tool-registry] Failed: {name} | tenant={context.tenant_id} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            # 返回泛化错误，不暴露内部细节
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="工具执行失败，请稍后重试",
            )
    
    def clear(self):
        """清空所有 Tool"""
        self._tools.clear()
        logger.info("Tool registry cleared")
    
    def __len__(self) -> int:
        """返回 Tool 数量"""
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        """检查是否包含指定 Tool"""
        return name in self._tools
    
    def __repr__(self) -> str:
        return f"ToolRegistry(tools={list(self._tools.keys())})"


# 全局注册器实例
_registry_instance: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 实例（单例模式）
    
    Returns:
        ToolRegistry: Tool 注册器实例（包含默认 Tools）
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = create_default_registry()
    return _registry_instance


def reset_tool_registry():
    """重置全局注册器实例（用于测试）"""
    global _registry_instance
    _registry_instance = None


def create_default_registry() -> ToolRegistry:
    """创建并注册所有默认 Tool
    
    注册以下 Tool：
    - product_search: 商品搜索
    - product_detail: 商品详情
    - logistics_track: 物流查询
    - knowledge_search: 知识库搜索
    - order_query: 订单查询
    - order_manage: 订单管理
    - product_manage: 商品管理
    - inventory_manage: 库存管理
    - processing_item_query: 加工项查询
    
    Returns:
        ToolRegistry: 配置好的注册器
    """
    from app.tools.product_search import ProductSearchTool
    from app.tools.product_detail import ProductDetailTool
    from app.tools.logistics_track import LogisticsTrackTool
    from app.tools.knowledge_search import KnowledgeSearchTool
    from app.tools.order_query import OrderQueryTool
    from app.tools.order_manage import OrderManageTool
    from app.tools.product_manage import ProductManageTool
    from app.tools.inventory_manage import InventoryManageTool
    from app.tools.processing_item_query import ProcessingItemQueryTool
    
    registry = ToolRegistry()
    
    # 注册所有 Tool
    registry.register(ProductSearchTool())
    registry.register(ProductDetailTool())
    registry.register(LogisticsTrackTool())
    registry.register(KnowledgeSearchTool())
    registry.register(OrderQueryTool())
    registry.register(OrderManageTool())
    registry.register(ProductManageTool())
    registry.register(InventoryManageTool())
    registry.register(ProcessingItemQueryTool())
    
    logger.info(f"Default registry created with {len(registry)} tools")
    return registry
