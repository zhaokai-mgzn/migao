"""
AI 智能客服系统 - 订单创建 Tool

创建新订单，调用 admin-api 的 POST /api/admin/orders 接口。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class OrderCreateTool(BaseTool):
    """订单创建 Tool

    通过调用 admin-api 创建新订单。

    使用场景：
    - 客服帮客户下单
    - 客户通过聊天直接创建订单
    """

    name = "order_create"
    description = """创建新订单。收集齐后展示汇总确认,用户确认后调用。可用字段:
- customer_name(string,必填): 客户姓名
- customer_phone(string,必填): 客户电话
- customer_address(string): 收货地址
- remark(string): 备注
- items(object[]数组,必填): 商品明细,每项含 product_name(string,必填) quantity(integer,必填) unit_price(number,必填) subtotal(number,必填=数量*单价) product_id(string,可选) width(number,可选) height(number,可选)

铁律: 收集->确认->执行。确认词:"确认创建""确认下单""好的""行""可以"。"""

    # admin、agent、tenant_admin 可使用
    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = False
    idempotent = False  # 每次调用创建新订单

    # 关联校验工具
    related_tools = ["validate_input"]

    parameters = {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "description": "客户姓名（必填）",
            },
            "customer_phone": {
                "type": "string",
                "description": "客户电话（必填）",
            },
            "customer_address": {
                "type": "string",
                "description": "客户收货地址（可选）",
            },
            "remark": {
                "type": "string",
                "description": "订单备注（可选）",
            },
            "items": {
                "type": "array",
                "description": "商品明细列表（必填，至少一项）",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "商品名称（必填）",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "数量（必填）",
                        },
                        "unit_price": {
                            "type": "number",
                            "description": "单价（必填）",
                        },
                        "subtotal": {
                            "type": "number",
                            "description": "小计 = 数量 × 单价（必填）",
                        },
                        "product_id": {
                            "type": "string",
                            "description": "商品ID（可选，有则传）",
                        },
                        "width": {
                            "type": "number",
                            "description": "宽度（可选，需要尺寸时填写）",
                        },
                        "height": {
                            "type": "number",
                            "description": "高度（可选，需要尺寸时填写）",
                        },
                    },
                    "required": ["product_name", "quantity", "unit_price", "subtotal"],
                },
            },
        },
        "required": ["customer_name", "customer_phone", "items"],
    }

    async def execute(
        self,
        context: ToolContext,
        customer_name: str,
        customer_phone: str,
        items: List[Dict[str, Any]],
        customer_address: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> ToolResult:
        """执行创建订单操作

        Args:
            context: Tool 执行上下文
            customer_name: 客户姓名
            customer_phone: 客户电话
            items: 商品明细列表
            customer_address: 客户收货地址（可选）
            remark: 订单备注（可选）

        Returns:
            ToolResult: 创建结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限创建订单",
            )

        # 参数校验
        if not customer_name:
            return ToolResult(
                success=False,
                error="缺少客户姓名",
                message="创建订单时必须提供客户姓名（customer_name）",
            )

        if not customer_phone:
            return ToolResult(
                success=False,
                error="缺少客户电话",
                message="创建订单时必须提供客户电话（customer_phone）",
            )

        if not items or not isinstance(items, list):
            return ToolResult(
                success=False,
                error="缺少商品明细",
                message="创建订单时必须提供商品明细列表（items）",
            )

        # 校验每个商品项
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return ToolResult(
                    success=False,
                    error=f"商品明细第 {i + 1} 项格式错误",
                    message=f"商品明细第 {i + 1} 项必须是对象，包含 product_name、quantity、unit_price、subtotal",
                )
            required_fields = ["product_name", "quantity", "unit_price", "subtotal"]
            for field in required_fields:
                if field not in item or item[field] is None:
                    return ToolResult(
                        success=False,
                        error=f"商品明细第 {i + 1} 项缺少 {field}",
                        message=f"商品明细第 {i + 1} 项缺少必填字段：{field}",
                    )

        try:
            # 构建请求体（admin-api 使用 camelCase）
            items_payload = []
            for item in items:
                items_payload.append({
                    "productName": item["product_name"],
                    "quantity": int(item["quantity"]),
                    "unitPrice": float(item["unit_price"]),
                    "subtotal": float(item["subtotal"]),
                })

            json_data: Dict[str, Any] = {
                "customerName": customer_name,
                "customerPhone": customer_phone,
                "items": items_payload,
            }

            if customer_address:
                json_data["customerAddress"] = customer_address
            if remark:
                json_data["remark"] = remark

            logger.info(
                f"[order-create] Creating order: customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}"
            )

            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/orders",
                json_data=json_data,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "创建失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"创建订单失败：{error_msg}",
                )

            order_data = response.get("data", {})
            order_id = order_data.get("id") or order_data.get("orderNo") or ""

            logger.info(
                f"Order created: order_id={order_id}, customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}, user={context.user_id}"
            )

            return ToolResult(
                success=True,
                data=order_data,
                message=f"订单创建成功！订单号：{order_id}，客户：{customer_name}，共 {len(items)} 件商品",
                summary=f"订单创建成功: 订单号{order_id}, 客户{customer_name}, {len(items)}件商品",
            )

        except Exception as e:
            logger.error(
                f"[order-create] Failed: customer={customer_name}, "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error=str(e),
                message="创建订单失败，请稍后重试",
            )
