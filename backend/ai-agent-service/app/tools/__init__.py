"""
AI 智能客服系统 - Tool 模块

提供 AI Agent 可调用的工具（Tool）：
- 订单查询
- 订单管理
- 商品搜索
- 商品详情
- 商品管理
- 库存管理
- 物流查询
- 知识库检索
- 转人工

所有 Tool 通过 HTTP API 调用 admin-api，不直接操作数据库
详见文档：docs/TOOL_API_SPEC.md
"""

# 基础设施
from app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
)

# 注册器
from app.tools.registry import (
    ToolRegistry,
    get_tool_registry,
    reset_tool_registry,
    create_default_registry,
    set_tool_context,
    get_tool_context,
)

# 具体 Tool 实现
from app.tools.product_search import ProductSearchTool
from app.tools.product_detail import ProductDetailTool
from app.tools.logistics_track import LogisticsTrackTool
from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.order_query import OrderQueryTool
from app.tools.order_manage import OrderManageTool
from app.tools.product_manage import ProductManageTool
from app.tools.inventory_manage import InventoryManageTool
from app.tools.processing_item_query import ProcessingItemQueryTool

__all__ = [
    # 基础设施
    "BaseTool",
    "ToolContext",
    "ToolResult",
    # 注册器
    "ToolRegistry",
    "get_tool_registry",
    "reset_tool_registry",
    "create_default_registry",
    "set_tool_context",
    "get_tool_context",
    # Tool 实现
    "ProductSearchTool",
    "ProductDetailTool",
    "LogisticsTrackTool",
    "KnowledgeSearchTool",
    "OrderQueryTool",
    "OrderManageTool",
    "ProductManageTool",
    "InventoryManageTool",
    "ProcessingItemQueryTool",
]
