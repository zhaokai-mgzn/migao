"""
AI 智能客服系统 - C 端收货地址查询 Tool（小布专用，issue #2815 CH-025）

下单场景自动填充：老客户下单时，查询最近一笔有收货地址的订单的收货信息
（收货人/手机号/地址），供 interact form 预填，用户可修改后确认，减少输入。

数据隔离（与 customer_order_query 同构）：
- 仅 customer 角色可用（商户员工/admin 不可用）
- 复用 C 端专用端点 /api/admin/agent/orders/mine（后端强制按当前用户过滤）
- 不支持任何跨用户参数；纯只读（READONLY，无需 confirm 守卫）
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.log_sanitizer import LogSanitizer


class CustomerAddressQueryTool(BaseTool):
    """C 端收货地址查询（小布专用，强制用户级隔离，只读）"""

    name = "customer_address_query"

    description = (
        "【触发】C 端顾客下单/购买时，查询其历史收货地址用于预填：'帮我下单''我要买''地址是多少'等下单意图。"
        "【前置】无参数。查询当前登录顾客最近一笔有收货地址的订单，返回收货人/手机号/地址。"
        "【使用】命中后把收货信息作为 interact(component=form) 的预填 value 展示给顾客确认/修改；未命中则按原流程询问收货信息。"
        "【何时不用】查询订单列表/物流用 customer_order_query / customer_logistics_track；商户员工管理订单用 order_query/order_manage。"
        "【标注】READONLY — 仅查当前登录顾客自己的历史订单收货信息，结果由系统强制按用户过滤"
    )

    parameters = {
        "type": "object",
        "properties": {},
    }

    # 物理隔离：仅 C 端顾客可用；商户员工/管理员一律拒绝（用 B 端 order_query）
    allowed_roles = ["customer"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        """查询最近一笔有收货地址的订单收货信息（强制按当前用户过滤）"""
        # 权限检查（customer 角色；非 customer 直接拒绝）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="该查询仅限顾客本人使用，请联系人工客服",
                suggestion="如您是商家员工，请使用商家后台的订单管理功能",
            )

        # 用户标识硬校验：缺失即拒绝（后端同样会拒绝，这里提前拦截便于 LLM 引导）
        if not str(context.user_id).strip() or str(context.user_id).strip() in ("internal-service", "dev_user"):
            return ToolResult(
                success=False,
                error="缺少用户标识",
                message="无法查询收货地址：缺少用户身份信息",
                suggestion="请重新登录后再试",
            )

        try:
            # 调用 C 端专用端点（后端从 X-User-Id 强制按当前用户过滤，无法越权）
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/agent/orders/mine",
                params={"page": 1, "size": 10},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "查询失败")
                logger.info(
                    f"[customer-address-query] Query rejected | tenant={context.tenant_id} "
                    f"error={error_msg}"
                )
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message="收货地址查询失败，请直接告诉我您的收货信息",
                    suggestion="直接询问顾客收货人/手机号/地址后继续下单流程",
                )

            data = response.get("data", {})
            records = data.get("items", []) or []

            # 取最近一笔有收货地址的订单（已确认/进行中/已完成优先；无则任意）
            for record in records:
                address = record.get("customerAddress") or record.get("customer_address")
                name = record.get("customerName") or record.get("customer_name")
                phone = record.get("customerPhone") or record.get("customer_phone")
                if address and str(address).strip():
                    order_no = record.get("orderNo") or record.get("order_no")
                    return ToolResult(
                        success=True,
                        data={
                            "has_address": True,
                            "customer_name": name,
                            "customer_phone": phone,
                            "customer_address": str(address).strip(),
                            "order_no": order_no,
                            "source": "last_order",
                        },
                        message=f"已找到您上次的收货信息（来自订单 {order_no}），可直接确认或修改",
                        summary=f"命中上次收货信息: {LogSanitizer.mask_text(str(name) if name else '')} "
                                f"{LogSanitizer.mask_phone(str(phone) if phone else '')} "
                                f"{LogSanitizer.mask_text(str(address))}",
                    )

            # 无历史订单或无地址：返回空，LLM 走原表单询问流程
            return ToolResult(
                success=True,
                data={"has_address": False, "customer_name": None,
                      "customer_phone": None, "customer_address": None},
                message="暂未找到您之前保存的收货信息",
                summary="无历史收货地址，按原流程询问顾客收货人/手机号/地址",
            )
        except Exception as e:
            logger.error(
                f"[customer-address-query] Failed | tenant={context.tenant_id} "
                f"user={LogSanitizer.mask_phone(context.user_id)} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="收货地址查询时出错，请直接告诉我您的收货信息",
                suggestion="直接询问顾客收货人/手机号/地址后继续下单流程",
            )
