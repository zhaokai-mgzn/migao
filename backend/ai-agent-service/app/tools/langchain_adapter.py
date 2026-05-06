"""
AI 智能客服系统 - LangChain Tool 适配器

将 BaseTool 适配为 LangChain StructuredTool，实现框架解耦。
"""

import json
import time
from typing import Any, Optional
from loguru import logger
from pydantic import BaseModel, Field, create_model

from app.tools.base import BaseTool, ToolContext, ToolResult


class LangChainToolAdapter:
    """LangChain Tool 适配器
    
    将 BaseTool 转换为 LangChain StructuredTool，
    使 Tool 实现不直接依赖 LangChain 框架。
    """
    
    @staticmethod
    def build_args_schema(tool: BaseTool) -> Optional[type[BaseModel]]:
        """从 Tool 的 parameters JSON Schema 动态生成 Pydantic 模型
        
        Args:
            tool: 原始 Tool
            
        Returns:
            Optional[type[BaseModel]]: Pydantic 模型类，用作 args_schema
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
    
    @staticmethod
    def create_langchain_tool(
        tool: BaseTool,
        get_context_func,
    ) -> Any:
        """创建 LangChain Tool（实际可调用）
        
        Args:
            tool: 原始 BaseTool 实例
            get_context_func: 获取 ToolContext 的函数
            
        Returns:
            StructuredTool: LangChain Tool
        """
        from langchain_core.tools import StructuredTool
        
        async def _execute(**kwargs) -> str:
            """LangChain Tool 执行函数 - 调用真实的 BaseTool.execute()"""
            ctx = get_context_func()
            if ctx is None:
                logger.warning(f"[langchain-adapter] No tool context for: {tool.name}")
                return json.dumps({
                    "success": False,
                    "error": "No tool context available",
                    "message": "系统错误，请稍后重试",
                }, ensure_ascii=False)
            
            try:
                logger.info(f"[langchain-adapter] Executing: {tool.name} | tenant={ctx.tenant_id}")
                start = time.time()
                result = await tool.execute(ctx, **kwargs)
                duration_ms = (time.time() - start) * 1000
                logger.info(f"[langchain-adapter] Completed: {tool.name} | success={result.success} duration={duration_ms:.1f}ms | tenant={ctx.tenant_id}")
                return json.dumps({
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "message": result.message,
                }, ensure_ascii=False, default=str)
            except Exception as e:
                # 记录详细错误信息到日志（包含租户上下文便于排查）
                tenant_id = ctx.tenant_id if ctx else "unknown"
                logger.error(
                    f"[langchain-adapter] Failed: {tool.name} | tenant={tenant_id} error={type(e).__name__}: {e}",
                    exc_info=True,
                )
                # 返回泛化错误，不暴露内部细节
                return json.dumps({
                    "success": False,
                    "error": "tool_execution_failed",
                    "message": "工具执行失败，请稍后重试",
                }, ensure_ascii=False)
        
        # 构建 args_schema
        args_schema = LangChainToolAdapter.build_args_schema(tool)
        
        return StructuredTool.from_function(
            coroutine=_execute,
            name=tool.name,
            description=tool.description,
            args_schema=args_schema,
            return_direct=False,
        )
