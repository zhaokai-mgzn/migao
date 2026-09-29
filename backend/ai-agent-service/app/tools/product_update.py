"""商品快速更新 Tool — 改价格/名称等单个字段，轻量无负担"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.tools.confirm_value import price_preview_missing
from app.utils.http_client import get_admin_api_client


class ProductUpdateTool(BaseTool):
    """商品快速更新 — 传什么改什么，null 字段不修改"""

    name = "product_update"
    description = (
        "【触发】用户说'改价格''改名称''价格改成XX''改名''设置退货回补库存''上架/下架'时**直接调用**，无需 validate_input。"
        "【参数】product_id 必填（支持名称/序号/UUID，服务端自动解析）；只传要改的字段，其他字段保持不变。"
        "【注意】改的是商品统一定价，影响所有 SKU。单独调某个 SKU 价格请引导去商品管理页。"
        "支持设置「退货是否回补库存」（allow_return_restock：true=退货后回补库存/可再售，"
        "false=定制商品退货不回补）。"
        "【反例】单独 SKU 调价本工具不支持（用 sku_update）；加工项与商品无关，不在本工具范围。"
        "【反例】本工具不支持图片字段；设置/修改商品主图、详情图**不在 B 端能力内**（改图不代做）——如实说明并引导商家到后台「商品管理」页面(/products)操作。"
        "【必填·改价】传 price 时必须同时传 before_price（改前价，取自 product_detail 的真值）——"
        "确认卡据此呈现「改前 → 改后」；漏传一律被拒（price_preview_required，issue #5303）。"
        "**服务端会拿 before_price 与当前价按值核对，不符即拒**（issue #5317）⇒ 编一个改前价只会白烧一轮。"
        "【确认形态·改价】改价是**涉钱面**：只认**商家点确认卡**（卡值），商家打字「确认」**不算**"
        "（issue #5317）—— 被拦时**不要再调本工具**，直接发 confirm 卡等商家点。"
        "【标注】WRITE|IDEMPOTENT — 写操作；用户确认后立即执行，禁止只查询/展示就停"
        "【铁律】用户明确要求设置/修改商品（回补库存开关/价格/名称/上下架等）时：先查商品拿真实 product_id → 展示操作预览 + 确认卡 → 用户确认后立即调用本工具执行，禁止只查询/展示就停（PR-017 实拍：设置退货回补库存只 product_search 不 update 判失败）。"
    )
    # 权限码（admin-api 目录）：商品写取写码 `product:create`（ProductController 的 PUT/PATCH）。
    # 该 agent 端点自身只挂类级读码 `product:list` —— 按读码放行会让只读持有者拿到写权限。
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
            "price": {"type": "number", "description": "新价格（可选）"},
            "before_price": {
                "type": "number",
                "description": "改前价（元）。传 price 时必填：取自 product_detail 返回的**当前价**真值（不得凭记忆或推算），用于确认卡展示「改前 → 改后」",
            },
            "name": {"type": "string", "description": "新名称（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "status": {
                "type": "string",
                "enum": ["on_sale", "off_sale"],
                "description": "上下架 status=on_sale（上架）/ off_sale（下架）。null 不修改",
            },
            "allow_return_restock": {
                "type": "boolean",
                "description": "退货后是否回补库存（可选，issue #2991）：true=退货回补/可再售，false=定制商品退货不回补。null 不修改",
            },
        },
        "required": ["product_id"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        price: Optional[float] = None,
        before_price: Optional[float] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        allow_return_restock: Optional[bool] = None,
    ) -> ToolResult:
        # 权限检查：改价/改名属对商品定价的承诺修改，仅限商户角色（admin/tenant_admin）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限修改商品信息",
                suggestion="商品更新仅对商家账号开放（admin/tenant_admin），请确认当前账号角色或联系管理员",
            )

        # ── 改价必须先预览后写（issue #5303，A 档可逆写补回）──
        # 判据单一源 = `confirm_value.price_preview_missing`（确认卡的「改前价 / 改后价」
        # 字段由同一模块派生）：`price` 在场而 `before_price` 缺席 ⇒ 卡上只有"改后"，
        # "改前 → 改后"从未被展示过 ⇒ **fail-closed**（禁止无预览直接写）。
        # `before_price` 只是**预览声明**，不进请求体（`AgentProductUpdateRequest` 无此字段）。
        _preview_err = price_preview_missing({"price": price, "before_price": before_price})
        if _preview_err:
            return ToolResult(
                success=False,
                error="price_preview_required",
                message=f"改价被拒（缺改前价预览）：{_preview_err}",
                suggestion=("先用 product_detail 取该商品**当前价**（= before_price），"
                            "再发 interact(component=confirm) 把「改前价 → 改后价」展示给商家，"
                            "商家点卡后带上 before_price 重试本工具"),
            )

        # Build only the fields that were actually provided
        # ⚠️ 请求体字段名必须与 admin-api AgentProductUpdateRequest 对齐：basePrice（非 price）。
        # Jackson 忽略未知字段，传 price 会被静默丢弃 → 价格更新无效（E2E Real 暴露）。
        json_data: Dict[str, Any] = {}
        if price is not None: json_data["basePrice"] = price
        # 改前价**随请求下发**（issue #5317）：服务端据此与 DB 当前值按值核对，不符即 422 拒绝
        # （口径与批次 `oldValue` 同一实现 = `AgentWriteValues.sameValue`）。不下发 ⇒ 服务端
        # 无从回查，护栏只防「漏填」不防「填错」。字段名必须逐字等于 DTO 字段 `beforePrice`。
        if before_price is not None: json_data["beforePrice"] = before_price
        if name: json_data["name"] = name
        if description: json_data["description"] = description
        if status: json_data["status"] = status
        # allow_return_restock 透传（issue #2991）：None 不传（=不修改），true/false 显式传
        if allow_return_restock is not None:
            json_data["allowReturnRestock"] = allow_return_restock

        if not json_data:
            return ToolResult(success=False,
                error="没有要修改的字段",
                message="请提供至少一个要修改的字段",
                suggestion="没有要修改的字段，请向用户确认要改哪一项（价格/库存/规格等）后重试",
            )

        logger.info(f"[product_update] {product_id}: {list(json_data.keys())} | 改前价={before_price}")
        client = get_admin_api_client()
        response = await client.patch(
            f"/api/admin/agent/products/{product_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "更新失败") if isinstance(err, dict) else str(err)
            return admin_api_failure(response, error=msg, message=f"更新失败: {msg}",
                            suggestion="请确认商品名称或ID正确，或先调用 product_search 查询")

        return ToolResult(success=True, data=response.get("data", {}),
                         message=f"商品已更新: {', '.join(json_data.keys())}")
