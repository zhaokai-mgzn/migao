"""
AI 智能客服系统 - LangChain Tool 适配器

将 BaseTool 适配为 LangChain StructuredTool，实现框架解耦。
"""

import json
import time
from typing import Any, Optional
from loguru import logger
from pydantic import BaseModel

from app.tools.base import BaseTool, ToolContext, ToolResult, build_args_schema


class LangChainToolAdapter:
    """LangChain Tool 适配器
    
    将 BaseTool 转换为 LangChain StructuredTool，
    使 Tool 实现不直接依赖 LangChain 框架。
    """
    
    @staticmethod
    def build_args_schema(tool: BaseTool) -> Optional[type[BaseModel]]:
        """从 Tool 的 parameters JSON Schema 动态生成 Pydantic 模型

        **实现单点来源**（issue #4080）：生成逻辑在 `app.tools.base.build_args_schema()`，
        本方法只做转接 —— 这里曾是三份副本之一（`BaseTool._get_args_schema()` / 本文件 /
        `ToolRegistry._build_args_schema()`），副本之间必然漂移。

        Args:
            tool: 原始 Tool

        Returns:
            Optional[type[BaseModel]]: Pydantic 模型类，用作 args_schema
        """
        return build_args_schema(tool.name, tool.parameters)

    @staticmethod
    def _unwrap_wrapped_data(tool: BaseTool, kwargs: dict) -> dict:
        """解包「把所有参数塞进 `data` 键」的调用（MiniMax 形态）；**工具自己声明了 `data` 参数时不动**。

        病灶（issue #9224 的 CU-004，评测 run 45979067843）：`customer_manage(action=update)` 的
        `data` 是**业务参数**（要改的档案字段）。旧实现在共享执行入口 `_execute_tool_safe` 里
        **无条件**解包 ⇒ `{action, customer_id, data:{phone}}` 变成 `{phone, action, customer_id}`
        ⇒ 工具收到 `data=None` ⇒ 报「缺少更新数据」，而拆出来的 `phone` 又被 `execute(**kwargs)`
        静默吞掉 ⇒ **写调用一次都没到 HTTP 层**（库里自然没有新号，评测报 `WRITE_NOT_PERSISTED`）。

        判据（会不会红）：`backend/ai-agent-service/tests/test_cu004_write_path_params_9224.py`
        的两条 —— ① 声明了 `data` 的工具必须原样收到 `data`；② **没声明** `data` 的工具仍要解包
        （MiniMax 兜底不能跟着一起被删）。
        """
        if not ("data" in kwargs and isinstance(kwargs.get("data"), dict)):
            return kwargs
        declared = (getattr(tool, "parameters", None) or {}).get("properties") or {}
        if "data" in declared:
            return kwargs
        nested = kwargs["data"]
        if not any(k not in kwargs for k in nested):
            return kwargs
        logger.info(f"[tool-exec] Flattened nested data for {tool.name}: keys={list(nested.keys())[:8]}")
        return {**nested, **{k: v for k, v in kwargs.items() if k != "data"}}

    @staticmethod
    def _normalize_args(tool: BaseTool, kwargs: dict) -> dict:
        """根据 Tool 的 JSON Schema 规范化参数类型

        LLM 在 tool calling 时可能将 array/object 参数序列化为 JSON 字符串
        （如 options='[{"label":"A","value":"a"}]'），自动解析为正确的 Python 类型。

        反向修复：LLM 也可能传 list 给 string 字段（如 name=["a","b"]），
        取第一个元素转为字符串，防止后续 .strip() 报 AttributeError。
        """
        props = tool.parameters.get("properties", {})
        if not props:
            return kwargs

        normalized = dict(kwargs)
        for field_name, field_schema in props.items():
            expected_type = field_schema.get("type", "")
            value = normalized.get(field_name)
            if value is None:
                continue

            # 反向修复：list → string（取第一个元素）
            if expected_type == "string" and isinstance(value, list):
                normalized[field_name] = str(value[0]) if value else ""
                logger.warning(
                    f"[langchain-adapter] Fixed '{field_name}' for {tool.name}: "
                    f"list → string '{normalized[field_name]}'"
                )
                continue

            if expected_type not in ("array", "object"):
                continue
            if not isinstance(value, str):
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
