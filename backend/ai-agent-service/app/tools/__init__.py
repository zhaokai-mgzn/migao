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
- 知识卡片检索（本店已发布知识，LLM WIKI 板块）
- 转人工

所有 Tool 通过 HTTP API 调用 admin-api，不直接操作数据库
详见文档：docs/TOOL_API_SPEC.md

知识库域：知识卡片检索（KnowledgeSearchTool）已启用——LLM WIKI 板块替代旧 RAG
（issue #3051），双端接线（米宝 #3059 / 小布 #3077）；KnowledgeManageTool（写侧）
不注册——知识管理在 admin-web 后台操作，不经 Agent（见 tools/registry.py）。
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
from app.tools.customer_logistics_track import CustomerLogisticsTrackTool
from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.order_query import OrderQueryTool
from app.tools.customer_order_query import CustomerOrderQueryTool
from app.tools.order_manage import OrderManageTool
from app.tools.product_manage import ProductManageTool
from app.tools.inventory_manage import InventoryManageTool
from app.tools.processing_item_query import ProcessingItemQueryTool
from app.tools.customer_manage import CustomerManageTool
from app.tools.employee_manage import EmployeeManageTool
from app.tools.role_manage import RoleManageTool
from app.tools.dashboard_stats import DashboardStatsTool
from app.tools.after_sales_manage import AfterSalesManageTool
from app.tools.notification_manage import NotificationManageTool
from app.tools.settings_manage import SettingsManageTool
from app.tools.session_manage import SessionManageTool
from app.tools.category_manage import CategoryManageTool
from app.tools.processing_item_manage import ProcessingItemManageTool
from app.tools.product_processing_item_manage import ProductProcessingItemManageTool
from app.tools.product_update import ProductUpdateTool
from app.tools.sku_update import SkuUpdateTool
from app.tools.interact import InteractTool

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
    "CustomerOrderQueryTool",
    "OrderManageTool",
    "ProductManageTool",
    "InventoryManageTool",
    "ProcessingItemQueryTool",
    "CustomerManageTool",
    "EmployeeManageTool",
    "RoleManageTool",
    "DashboardStatsTool",
    "AfterSalesManageTool",
    # KnowledgeManageTool 不注册：知识管理在 admin-web 后台操作，不经 Agent
    "NotificationManageTool",
    "SettingsManageTool",
    "SessionManageTool",
    "CategoryManageTool",
    "ProcessingItemManageTool",
    "InteractTool",
]
