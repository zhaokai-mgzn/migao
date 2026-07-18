"""
AI 智能客服系统 - 订单创建 Tool

创建新订单，调用 admin-api 的 POST /api/admin/orders 接口。

安全（#518）:
- 客户创建订单前必须通过手机号 SMS 验证码验证身份
- 管理员/客服帮客户下单无需 SMS 验证
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.redis_client import RedisClient


# SMS 验证码 Redis key 前缀
_OTP_KEY_PREFIX = "sms:otp:"
_OTP_TTL_SECONDS = 300  # 5分钟有效期
_OTP_VALID_PATTERN = re.compile(r"^\d{4,6}$")  # 4-6位数字验证码
_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")  # 中国大陆手机号


class OrderCreateTool(BaseTool):
    """订单创建 Tool

    通过调用 admin-api 创建新订单。

    使用场景：
    - 客服帮客户下单
    - 客户通过聊天直接创建订单

    安全规则（#518）:
    - customer 角色：必须提供 sms_code，且通过手机号验证
    - admin/agent/tenant_admin 角色：无需 SMS 验证（帮客户下单）
    """

    name = "order_create"
    description = (
        "【触发】创建订单。用户说'创建订单''下单'时调用。"
        "【前置】必须先调 product_detail 查 SKU，多 SKU 必须让用户选规格（颜色/售卖方式/门幅）。单 SKU 直接用。"
        "必填: customer_name + customer_phone + items(product_name+quantity+unit_price+sellMethod+doorWidth+colorName)。"
        "【反例】跳过 SKU 选择直接下单。修改订单用 order_manage。WRITE"
    )
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

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
            "sms_code": {
                "type": "string",
                "description": "短信验证码，4-6位数字。customer角色必填，admin/agent不需要",
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
                            "description": "商品 32 位 UUID（可选）。当用户明确指定商品时传入。不传时服务端通过 product_name 自动匹配",
                        },
                        "width": {
                            "type": "number",
                            "description": "宽度（可选，需要尺寸时填写）",
                        },
                        "height": {
                            "type": "number",
                            "description": "高度（可选，需要尺寸时填写）",
                        },
                        "processing_info": {
                            "type": "object",
                            "description": "商品销售信息（选了颜色/门幅后必填）：colorId(颜色ID)、colorName(颜色名称)、sellingMethod(售卖方式: bulk_cut散剪/full_roll整卷)、doorWidth(门幅如2.8米)、skuCode(SKU编码)、processingItems(加工项列表)、processingFee(加工费合计)",
                            "properties": {
                                "colorId": {"type": "number", "description": "颜色ID"},
                                "colorName": {"type": "string", "description": "颜色名称"},
                                "sellingMethod": {"type": "string", "description": "售卖方式"},
                                "doorWidth": {"type": "string", "description": "门幅"},
                                "skuCode": {"type": "string", "description": "SKU编码"},
                                "processingFee": {"type": "number", "description": "加工费合计"},
                                "processingItems": {
                                    "type": "array",
                                    "description": "加工项列表",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "unitPrice": {"type": "number"},
                                            "quantity": {"type": "integer"},
                                            "unit": {"type": "string"},
                                            "pricingMethod": {"type": "string"},
                                            "subtotal": {"type": "number"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "required": ["product_name", "quantity", "unit_price", "subtotal"],
                },
            },
        },
        "required": ["customer_name", "customer_phone", "items"],
    }

    @staticmethod
    def _otp_key(phone: str, tenant_id: int) -> str:
        """构造 SMS 验证码 Redis key"""
        return f"{_OTP_KEY_PREFIX}{tenant_id}:{phone}"

    @staticmethod
    async def _verify_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """验证短信验证码

        从 Redis 读取已存储的验证码并比对。
        验证成功后删除验证码（一次性使用）。

        Args:
            phone: 客户手机号
            code: 用户输入的验证码
            tenant_id: 租户ID

        Returns:
            bool: 验证是否通过
        """
        if not _OTP_VALID_PATTERN.match(code or ""):
            return False

        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            stored_code = await redis_client.get(key)

            if stored_code and stored_code.strip() == code.strip():
                # 验证成功后删除，防止重复使用
                await redis_client.delete(key)
                logger.info(f"[sms_verify] Code verified: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
                return True

            logger.warning(f"[sms_verify] Code mismatch: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return False
        except Exception as e:
            logger.error(f"[sms_verify] Redis error: {type(e).__name__}: {e}")
            return False

    @staticmethod
    async def _store_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """存储短信验证码到 Redis

        由 SMS 发送工具调用，存储生成的验证码。

        Args:
            phone: 客户手机号
            code: 生成的验证码
            tenant_id: 租户ID

        Returns:
            bool: 存储是否成功
        """
        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            await redis_client.set(key, code, ttl=_OTP_TTL_SECONDS)
            logger.info(f"[sms_store] Code stored: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return True
        except Exception as e:
            logger.error(f"[sms_store] Redis error: {type(e).__name__}: {e}")
            return False

    def _needs_sms_verification(self, context: ToolContext) -> bool:
        """判断是否需要 SMS 验证

        只有 customer 角色需要短信验证。
        admin/agent/tenant_admin 帮客户下单时跳过。
        """
        return context.role == "customer"

    async def execute(
        self,
        context: ToolContext,
        customer_name: str,
        customer_phone: str,
        items: List[Dict[str, Any]],
        sms_code: Optional[str] = None,
        customer_address: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> ToolResult:
        """执行创建订单操作

        Args:
            context: Tool 执行上下文
            customer_name: 客户姓名
            customer_phone: 客户电话
            items: 商品明细列表
            sms_code: 短信验证码（customer角色必填）
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
                suggestion="请联系管理员获取订单创建权限",
            )

        # 参数校验
        if not customer_name:
            return ToolResult(
                success=False,
                error="缺少客户姓名",
                message="创建订单时必须提供客户姓名（customer_name）",
                suggestion="请提供客户的姓名",
            )

        if not customer_phone:
            return ToolResult(
                success=False,
                error="缺少客户电话",
                message="创建订单时必须提供客户电话（customer_phone）",
                suggestion="请提供客户的联系电话",
            )

        # 对抗编程：校验手机号格式，防止 LLM 编造号码
        if not _PHONE_PATTERN.match(customer_phone.strip()):
            return ToolResult(
                success=False,
                error="手机号格式无效",
                message=f"手机号 {customer_phone} 格式不正确，请输入 11 位中国大陆手机号",
                suggestion="请确认客户手机号是否正确",
            )

        if not items or not isinstance(items, list):
            return ToolResult(
                success=False,
                error="缺少商品明细",
                message="创建订单时必须提供商品明细列表（items）",
                suggestion="请提供至少一件商品的信息（名称、数量、单价）",
            )

        # Gap-1 安全加固: SMS 验证码校验（仅 customer 角色需要）
        if self._needs_sms_verification(context):
            if not sms_code:
                return ToolResult(
                    success=False,
                    error="缺少短信验证码",
                    message="为了您的账户安全，创建订单前需要验证手机号。请输入短信验证码",
                    suggestion="请先请求发送短信验证码到您的手机，然后提供收到的验证码",
                )
            if not _OTP_VALID_PATTERN.match(sms_code):
                return ToolResult(
                    success=False,
                    error="验证码格式无效",
                    message="短信验证码为4-6位数字，请检查后重新输入",
                    suggestion="请输入您收到的4-6位数字验证码",
                )
            verified = await self._verify_sms_code(
                phone=customer_phone,
                code=sms_code,
                tenant_id=context.tenant_id,
            )
            if not verified:
                return ToolResult(
                    success=False,
                    error="验证码错误或已过期",
                    message="短信验证码错误或已过期，请重新获取验证码",
                    suggestion="请重新请求发送短信验证码，并在5分钟内完成验证",
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
            # 对抗编程：透传 LLM 提供的所有字段，避免静默丢弃 productId/width/height/processingInfo
            items_payload = []
            for item in items:
                entry: Dict[str, Any] = {
                    "productName": item["product_name"],
                    "quantity": int(item["quantity"]),
                    "unitPrice": float(item["unit_price"]),
                    "subtotal": float(item["subtotal"]),
                }
                # 透传可选字段 — 不信任 LLM 一定传，但传了就不能丢
                for py_key, java_key in [
                    ("product_id", "productId"),
                    ("width", "width"),
                    ("height", "height"),
                    ("processing_info", "processingInfo"),
                ]:
                    if item.get(py_key) is not None:
                        entry[java_key] = item[py_key]
                items_payload.append(entry)

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
                "/api/admin/agent/orders",
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
                error="tool_execution_failed",
                message="创建订单失败，请稍后重试",
                suggestion="请检查商品信息和客户信息是否完整，确认后重试",
            )
