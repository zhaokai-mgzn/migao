"""
AI 智能客服系统 - Tool 模块

Agent 可调用的工具（Tool）门面：基础设施 + 注册器 + 全部已注册的 Tool 类。
**工具清单的单一源 = `app/tools/registry.py` 的 `create_default_registry()`** ——
本文件不再维护第二份手写清单（历史上 docstring/import/`__all__` 三份清单互相漂移）。
所有 Tool 通过 HTTP API 调用 admin-api，不直接操作数据库（见 docs/TOOL_API_SPEC.md）。

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

# 具体 Tool 实现 —— 清单与顺序必须与 `create_default_registry()` 一致（漏导出是**静默**漂移，
# `from app.tools import OrderCreateTool` 才报错；不变式 = tests/test_tools_registry.py
# ::TestToolsFacadeCompleteness）。未注册的类（KnowledgeManageTool、human_handoff）
# **不进**本清单；加工单三工具按 issue #4196 恢复注册 ⇒ 一并回到本清单。
from app.tools.product_search import ProductSearchTool
from app.tools.product_detail import ProductDetailTool
from app.tools.logistics_track import LogisticsTrackTool
from app.tools.customer_logistics_track import CustomerLogisticsTrackTool
from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.order_query import OrderQueryTool
from app.tools.customer_order_query import CustomerOrderQueryTool
from app.tools.customer_address_query import CustomerAddressQueryTool
from app.tools.order_manage import OrderManageTool
from app.tools.order_create import OrderCreateTool
from app.tools.processing_order_generate import ProcessingOrderGenerateTool
from app.tools.processing_order_query import ProcessingOrderQueryTool
from app.tools.processing_order_update import ProcessingOrderUpdateTool
from app.tools.product_manage import ProductManageTool
from app.tools.inventory_manage import InventoryManageTool
from app.tools.processing_item_query import ProcessingItemQueryTool
from app.tools.customer_manage import CustomerManageTool
from app.tools.employee_manage import EmployeeManageTool
from app.tools.role_manage import RoleManageTool
from app.tools.dashboard_stats import DashboardStatsTool
from app.tools.finance_api import FinanceApiTool
from app.tools.after_sales_manage import AfterSalesManageTool
from app.tools.aftersale_create import AftersaleCreateTool
from app.tools.aftersale_query import AftersaleQueryTool
# 转人工工具**不导出**（用户裁定 2026-09-19 退场，模型不可达；见 registry.py 注册行注释）：
# 门面清单必须与 `create_default_registry()` 一致（加工单三工具已按 #4196 恢复注册）。
# from app.tools.human_handoff import HumanHandoffTool
from app.tools.notification_manage import NotificationManageTool
from app.tools.settings_manage import SettingsManageTool
from app.tools.session_manage import SessionManageTool
from app.tools.category_manage import CategoryManageTool
from app.tools.processing_item_manage import ProcessingItemManageTool
from app.tools.product_processing_item_manage import ProductProcessingItemManageTool
from app.tools.product_update import ProductUpdateTool
from app.tools.sku_update import SkuUpdateTool
from app.tools.interact import InteractTool
from app.tools.validate_input import ValidateInputTool
from app.tools.curtain_calc import CurtainCalcTool
from app.tools.production_progress_query import ProductionProgressQueryTool
from app.tools.piecework_query import PieceworkQueryTool
from app.tools.payment_qrcode_query import PaymentQrcodeQueryTool

__all__ = [
    # 基础设施 + 注册器
    "BaseTool", "ToolContext", "ToolResult",
    "ToolRegistry", "get_tool_registry", "reset_tool_registry",
    "create_default_registry", "set_tool_context", "get_tool_context",
    # Tool 实现（= create_default_registry() 注册的全部类）
    "ProductSearchTool", "ProductDetailTool", "LogisticsTrackTool",
    "CustomerLogisticsTrackTool", "KnowledgeSearchTool", "OrderQueryTool",
    "CustomerOrderQueryTool", "CustomerAddressQueryTool", "OrderManageTool",
    "OrderCreateTool", "ProductManageTool", "InventoryManageTool",
    "ProcessingOrderGenerateTool", "ProcessingOrderQueryTool",
    "ProcessingOrderUpdateTool",
    "ProcessingItemQueryTool", "CustomerManageTool", "EmployeeManageTool",
    "RoleManageTool", "DashboardStatsTool", "FinanceApiTool",
    "AfterSalesManageTool", "AftersaleCreateTool", "AftersaleQueryTool",
    "NotificationManageTool", "SettingsManageTool",
    "SessionManageTool", "CategoryManageTool", "ProcessingItemManageTool",
    "ProductProcessingItemManageTool", "ProductUpdateTool", "SkuUpdateTool",
    "InteractTool", "ValidateInputTool", "CurtainCalcTool",
    "ProductionProgressQueryTool", "PieceworkQueryTool",
    "PaymentQrcodeQueryTool",
]
