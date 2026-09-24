"""SKU 价格更新 Tool — 按颜色/门幅精确匹配（V111：SKU 组合只有 颜色 × 门幅）"""

from typing import Optional

from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.tools.confirm_value import price_preview_missing
from app.utils.http_client import get_admin_api_client


class SkuUpdateTool(BaseTool):
    """单独更新某个 SKU 的价格"""

    name = "sku_update"
    description = (
        "【触发】用户说'白色改成XX元''散剪太贵了''XX颜色的调成XX'时直接调用。"
        "【参数】product_id + price + before_price 必填（before_price = 改前价，取自 product_detail 的 skus[].price 真值）；"
        "color/door_width 都是可选的，至少填一个来定位 SKU"
        "（SKU 组合 = 颜色 × 门幅，V111）；取值须来自 product_detail 的 skus[] 原值。"
        "【反例】改商品统一定价（影响所有 SKU）用 product_update；改图片/上下架不在 B 端能力内（不代做）；"
        "加工项不在本工具范围。"
        "【必填·改价】漏传 before_price 一律被拒（price_preview_required，issue #5303）——"
        "确认卡必须先呈现「改前 → 改后」；**服务端还会拿它与该 SKU 当前价按值核对，不符即拒**"
        "（issue #5317）⇒ 编一个改前价只会白烧一轮。"
        "【确认形态·改价】改价是**涉钱面**：只认**商家点确认卡**（卡值），商家打字「确认」**不算**"
        "（issue #5317）—— 被拦时**不要再调本工具**，直接发 confirm 卡等商家点。"
        "【标注】WRITE|IDEMPOTENT"
        "【铁律】用户明确要求写操作（禁用/创建/调整/删除/上下架/重置等）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（HR-003/PP-006/PR-005 实拍：agent 只 list/query 不执行写工具判失败）。")
    # 权限码（admin-api 目录）：SKU 改价/改库存属商品写 ⇒ 写码 `product:create`
    # （该 agent 端点只挂类级读码 `product:list`，按读码放行会让只读持有者拿到写权限）。
    # 此前写死 ["admin","tenant_admin"] ⇒ operator / product_manager 持码却被判「权限不足」（#4106 F4）。
    required_permissions = ["product:create"]
    read_only = False
    requires_confirmation = True  # 审计 07 P0-L1: 高风险非 destructive 写操作需用户确认
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品标识。支持名称/序号/UUID，服务端自动解析",
            },
            "color": {
                "type": "string",
                "description": "颜色名称，如'10# 复古墨绿'、'白色'。从 product_detail skus[].color_name 获取",
            },
            # V111：`selling_method` 参数已删除 —— 售卖方式不再是 SKU 组合维度
            # （上移为商品级基础属性 products.selling_methods），接收端
            # `AgentProductController` 的 /skus/price 也不再读该键（下发=静默丢弃，
            # 判据见 tests/test_tool_payload_backend_contract.py）。
            "door_width": {
                "type": "string",
                "description": "门幅，从 product_detail skus[].door_width 原值获取（如'2.8'）。可选（服务端兼容'2.8米'写法）",
            },
            "price": {"type": "number", "description": "新价格（元）"},
            "before_price": {
                "type": "number",
                "description": "改前价（元）必填：取自 product_detail 的 skus[].price **原值**（不得凭记忆或推算），用于确认卡展示「改前 → 改后」",
            },
        },
        "required": ["product_id", "price"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        price: float,
        before_price: Optional[float] = None,
        color: str = "",
        door_width: str = "",
    ) -> ToolResult:
        # 权限检查：SKU 调价属对商品定价的承诺修改，仅限商户角色（admin/tenant_admin）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限调整 SKU 价格",
                suggestion="SKU 调价仅对商家账号开放（admin/tenant_admin），请确认当前账号角色或联系管理员",
            )

        if not product_id or ".." in str(product_id):
            return ToolResult(success=False,
                error="Invalid product_id",
                suggestion="product_id 缺失或格式不合法，请先用 product_search 查到该商品后重试",
            )

        # ── 改价必须先预览后写（issue #5303，A 档可逆写补回）──
        # 判据单一源 = `confirm_value.price_preview_missing`（确认卡的「改前价 / 改后价」
        # 字段由同一模块派生）：没有 `before_price` ⇒ "改前 → 改后"从未被展示过
        # ⇒ **fail-closed**（禁止无预览直接写）。`before_price` 不进请求体
        # （`/skus/price` 端点只读 price/color/door_width）。
        _preview_err = price_preview_missing({"price": price, "before_price": before_price})
        if _preview_err:
            return ToolResult(
                success=False,
                error="price_preview_required",
                message=f"SKU 调价被拒（缺改前价预览）：{_preview_err}",
                suggestion=("先用 product_detail 取该 SKU 的**当前价**（= before_price），"
                            "再发 interact(component=confirm) 把「改前价 → 改后价」展示给商家，"
                            "商家点卡后带上 before_price 重试本工具"),
            )

        client = get_admin_api_client()
        body: dict = {"price": price}
        if color: body["color"] = color
        if door_width: body["door_width"] = door_width
        # 改前价**随请求下发**（issue #5317）：`/skus/price` 端点据此与匹配到的 SKU 当前价
        # 按值核对（同一实现 = `AgentWriteValues.sameValue`），不符即 422 拒绝。
        if before_price is not None: body["before_price"] = before_price

        logger.info(f"[sku_update] product={product_id} color={color} width={door_width} price={price} 改前价={before_price}")

        response = await client.patch(
            f"/api/admin/agent/products/{product_id}/skus/price",
            json_data=body,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "更新失败") if isinstance(err, dict) else str(err)
            return admin_api_failure(response, error=msg, message=f"SKU 调价失败: {msg}",
                            suggestion="请先调 product_detail 查看 SKU 列表，确认颜色/门幅正确")

        desc_parts = [p for p in [color, door_width] if p]
        desc = " ".join(desc_parts) if desc_parts else product_id

        return ToolResult(
            success=True,
            data={"color": color, "door_width": door_width, "new_price": price},
            message=f"SKU「{desc}」价格已更新为 ¥{price}",
        )
