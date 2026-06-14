"""
AI 智能客服系统 - LangChain Tool 适配器

将 BaseTool 适配为 LangChain StructuredTool，实现框架解耦。
"""

import json
import time
from typing import Any, Optional, Annotated
from loguru import logger
from pydantic import BaseModel, Field, create_model
from pydantic.functional_validators import BeforeValidator

from app.tools.base import BaseTool, ToolContext, ToolResult


def _json_string_parser(value: Any) -> Any:
    """BeforeValidator: LLM传了JSON字符串时自动解析为list/dict"""
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                f"[LangChainAdapter] Failed to parse JSON string arg: "
                f"value={value[:200]}"
            )
    return value


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

            # array/object 字段加 BeforeValidator，在 Pydantic 类型强制前解析 JSON 字符串
            # LLM 可能把 colors='[\"米白\"]' 传成字符串，不处理 Pydantic 会用 list(str) 逐字符拆分
            validators = []
            if py_type in (list, dict):
                validators.append(_json_string_parser)

            if field_name in required_fields:
                field_definitions[field_name] = (
                    Annotated[py_type, *validators] if validators else py_type,
                    Field(description=description),
                )
            else:
                field_definitions[field_name] = (
                    Annotated[Optional[py_type], *validators] if validators else Optional[py_type],
                    Field(default=default if default is not ... else None, description=description),
                )
        
        if not field_definitions:
            return None
        
        # 动态创建 Pydantic 模型
        model_name = f"{tool.name.title().replace('_', '')}Args"
        return create_model(model_name, **field_definitions)
    
    @staticmethod
    def _normalize_args(tool: BaseTool, kwargs: dict) -> dict:
        """根据 Tool 的 JSON Schema 规范化参数类型

        LLM 在 tool calling 时可能将 array/object 参数序列化为 JSON 字符串
        （如 options='[{"label":"A","value":"a"}]'），自动解析为正确的 Python 类型。

        这样所有 Tool 都能受益，不需要每个 Tool 单独处理此问题。
        """
        props = tool.parameters.get("properties", {})
        if not props:
            return kwargs

        normalized = dict(kwargs)
        for field_name, field_schema in props.items():
            expected_type = field_schema.get("type", "")
            if expected_type not in ("array", "object"):
                continue
            value = normalized.get(field_name)
            if value is None or not isinstance(value, str):
                continue  # 已经是正确类型或不需处理
            try:
                parsed = json.loads(value)
                if expected_type == "array" and isinstance(parsed, list):
                    logger.info(
                        f"[langchain-adapter] Normalized '{field_name}' for {tool.name}: "
                        f"JSON string → list ({len(parsed)} items)"
                    )
                    normalized[field_name] = parsed
                elif expected_type == "object" and isinstance(parsed, dict):
                    logger.info(
                        f"[langchain-adapter] Normalized '{field_name}' for {tool.name}: "
                        f"JSON string → dict"
                    )
                    normalized[field_name] = parsed
            except (json.JSONDecodeError, TypeError):
                logger.debug(
                    f"[langchain-adapter] Field '{field_name}' for {tool.name}: "
                    f"not valid JSON, keeping original value for Tool validation"
                )

        return normalized

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

            # 规范化参数：LLM 可能将 array/object 参数序列化为 JSON 字符串
            # 根据 Tool 的 JSON Schema 定义，自动解析应该为 list/dict 的字符串值
            kwargs = LangChainToolAdapter._normalize_args(tool, kwargs)

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
