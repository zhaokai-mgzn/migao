"""
AI 智能客服系统 - C 端收款二维码查询 Tool（小布专用）

触发链（issue #4085 第 1 项；用户 2026-09-18 裁定「建触发机制」，与 `production_progress`
的裁定同构：**交付物在 main ≠ 能力可达**）：

    顾客问「怎么付款 / 收款码 / 扫码支付」→ 本工具 → 返回的 `data` 即卡载荷
    → `app/api/chat.py::_detect_card_type` 映射为 `"payment"` → C 端
    `MessageBubble.renderCard` 的 `case 'payment'` → `PaymentCard`
    （扫码直接付给商家，平台不经手资金 = 二清规避）。

数据来源**复用**已有 REST，不新造数据源：
- admin-api `AgentPaymentController`：`GET /api/admin/agent/payment-qrcodes`（#3990）
- C 端同源端点 = `app/api/payments.py`：`GET /chat/payment-qrcodes`
  （只透出精简字段 image_url / payee_name）

纯只读（read_only=True）：只查当前租户的收款码配置，不改动任何数据。
无收款码是**合法答案**（不是失败）：`success=True` + 空 `payment_qrcodes`，
由卡片渲染空态「商家暂未设置收款码，请联系客服获取收款方式」。
"""

from typing import Any, Dict

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client

# 支持的收款方式（与 admin-api 表 tenant_payment_qrcodes.payment_type、C 端
# `app/api/payments.py` 的遍历口径一致：wechat 微信 / alipay 支付宝）
_PAYMENT_TYPES = ("wechat", "alipay")


class PaymentQrcodeQueryTool(BaseTool):
    """收款二维码查询 Tool（C 端只读）

    调 admin-api 冻结契约端点拿当前租户的微信/支付宝收款码，把「扫码付给谁」
    转成 LLM 与顾客都能读懂的摘要；查询失败一律给 suggestion（禁止编造收款码）。
    """

    name = "payment_qrcode_query"

    description = (
        "【触发】顾客问'怎么付款''在哪付钱''收款码/付款码''扫码支付''付给谁'时调用。"
        "【前置】无需参数（系统按当前租户自动取商家自己的收款码）。"
        "【反例】查订单金额/状态用 customer_order_query；查物流用 customer_logistics_track。"
        "【标注】READONLY — 只读查询商家收款二维码，不改动任何数据；"
        "查询结果里的收款码图片地址必须原样使用，禁止编造或改写"
    )

    # 无入参：收款码按「当前租户」取（顾客不需要、也无法指定别的商家）
    parameters = {"type": "object", "properties": {}, "required": []}

    # C 端专用：顾客可用；商户员工侧有独立的设置端（SettingsController），不共用本工具
    allowed_roles = ["customer"]
    read_only = True
    destructive = False
    idempotent = True

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        """查询当前租户的微信/支付宝收款二维码"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询收款二维码",
                suggestion="请引导顾客联系人工客服获取收款方式；禁止编造收款码或收款方名称",
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                # 冻结契约端点（#3990）；**路径用字面量**：跨模块 payload 契约门禁
                # （tests/test_tool_payload_backend_contract.py）要求 admin-api 调用点
                # 能静态归属到端点（模块常量会判「静默脱离射程」）。
                "/api/admin/agent/payment-qrcodes",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[payment-qrcode] Failed | tenant={context.tenant_id} "
                f"error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询收款二维码失败，请稍后重试",
                suggestion=(
                    "请稍后重试；仍失败时如实告知顾客暂时拿不到收款码，可转人工核实，"
                    "禁止编造收款码或收款方名称"
                ),
            )

        if not isinstance(response, dict) or not response.get("success"):
            # **必须走共享映射点**（issue #4149 G4）：扩宽后的 L0 锁在 main 上抓到本文件
            # （`Or` 形态此前不在判据射程内）—— 403/401 若就地返回，`error_code` 会丢，
            # 授权失败就被降级成「请稍后重试」并被自修复重试再买一次拒绝。
            error_info = response.get("error", {}) if isinstance(response, dict) else {}
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict) else str(error_info)
            )
            logger.info(
                f"[payment-qrcode] Rejected | tenant={context.tenant_id} error={error_msg}"
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message="查询收款二维码失败，请稍后重试",
                suggestion=(
                    "如实告知顾客暂时查不到收款码，可转人工核实；禁止编造收款码或收款方名称"
                ),
            )

        raw = response.get("data")
        qrcodes: Dict[str, Any] = {}
        for ptype in _PAYMENT_TYPES:
            q = raw.get(ptype) if isinstance(raw, dict) else None
            if not isinstance(q, dict):
                continue
            image_url = q.get("imageUrl") or q.get("image_url") or ""
            if not image_url:
                # 无图不成码：缺图片地址的配置项一律跳过（避免前端渲染空白方块）
                continue
            qrcodes[ptype] = {
                "payment_type": ptype,
                "image_url": image_url,
                "payee_name": q.get("payeeName") or q.get("payee_name") or "",
            }

        # 卡载荷 = 工具 data（`_detect_card_type` 原样下发；PaymentCard 读 payment_qrcodes）
        data = {"payment_qrcodes": qrcodes}

        logger.info(
            f"[payment-qrcode] Fetched | tenant={context.tenant_id} "
            f"types={sorted(qrcodes)}"
        )

        if not qrcodes:
            return ToolResult(
                success=True,
                data=data,
                message="商家暂未设置收款码",
                summary=(
                    "商家暂未设置收款码（微信/支付宝都没有）—— 请如实告知顾客并引导联系客服，"
                    "禁止编造收款码或收款方"
                ),
            )

        names = sorted({q["payee_name"] for q in qrcodes.values() if q["payee_name"]})
        summary = f"已获取收款二维码：{'、'.join(_label(t) for t in sorted(qrcodes))}"
        if names:
            summary += f"（收款方：{'、'.join(names)}）"
        return ToolResult(
            success=True,
            data=data,
            message="收款二维码已获取",
            summary=summary,
        )


def _label(ptype: str) -> str:
    """收款方式中文名（与 C 端 PaymentCard 的 tab 文案一致）"""
    return "微信" if ptype == "wechat" else "支付宝"