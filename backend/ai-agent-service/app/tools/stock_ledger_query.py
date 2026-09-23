"""
AI 智能客服系统 - 库存台账查询 Tool（issue #5247 模块覆盖：库存）

只读：按关键词分页查询库存台账。
端点 `StockLedgerController` → `GET /api/admin/stock-ledger`（方法级 `product:list`）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


def ledger_rows(data: Any) -> list:
    """容错取列表：`PageResponse`（records/items/list/rows）与裸列表两种形态都收。

    分页包装的键名不写死（同一个 `PageResponse` 在不同控制器历史上用过不同键），
    取不到就返回空列表 —— 前端/服务端的键名漂移不应让工具报「查询失败」。
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "items", "list", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


class StockLedgerQueryTool(BaseTool):
    """库存台账查询 Tool（只读）"""

    name = "stock_ledger_query"
    description = (
        "【触发】用户问'库存台账''库存明细''各颜色还剩多少''哪些货号库存告急'时调用。"
        "【参数】全部可选：sku_id（SKU id）/ product_id（商品 id）/ ref_no（业务单据号：订单号或工单号，"
        "用于回答「这一单改了哪些 SKU 的库存」）、page/size 分页。"
        "【反例】按货号/商品名/颜色模糊搜索请先用 product_search 拿到 product_id/sku_id 再查本工具"
        "（本端点**没有**关键词参数，传了会被服务端静默丢弃 = 拿全量冒充过滤结果）。\n"
        "【反例】单个商品档案里的库存字段用 product_detail；某商品实时库存数用 inventory_manage(query)；"
        "批次余量与省料度量用 batch_stock_query；到货/入库单与批次来源用 inbound_order_query。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：`StockLedgerController.GET /api/admin/stock-ledger` 方法级
    # `@RequirePermission("product:list")` —— 与侧边栏「商品列表」节点同码（页面可见性 ≡ Agent 能力）。
    required_permissions = ["product:list"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "sku_id": {"type": "string", "description": "SKU id 过滤（可选）"},
            "product_id": {"type": "string", "description": "商品 id 过滤（可选）"},
            "ref_no": {
                "type": "string",
                "description": "业务单据号过滤（订单号 / 工单号；可选）—— 一单改了哪些 SKU",
            },
            "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            "size": {"type": "integer", "description": "每页数量，默认 20", "default": 20},
        },
        "required": [],
    }

    async def execute(
        self,
        context: ToolContext,
        sku_id: Optional[str] = None,
        product_id: Optional[str] = None,
        ref_no: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询库存台账",
                suggestion="请联系管理员为您开通「商品列表」查看权限后重试",
            )

        # 参数名必须与 `StockLedgerController.getLedger` 的 `@RequestParam` **逐字一致**
        # （skuId / productId / refNo）：Spring 对未知查询参数**静默忽略** ⇒ 名字写错会
        # 「拿全量台账冒充过滤结果」（HTTP 200 假成功，本仓反复治过的形态）。
        params: Dict[str, Any] = {"page": page, "size": size}
        if sku_id:
            params["skuId"] = sku_id.strip()
        if product_id:
            params["productId"] = product_id.strip()
        if ref_no:
            params["refNo"] = ref_no.strip()

        try:
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/stock-ledger",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Stock ledger query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="库存台账查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message=f"库存台账查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，改为不带关键词查询，或请用户核对货号后重试",
            )

        rows = ledger_rows(response.get("data"))
        if not rows:
            return ToolResult(
                success=True,
                data={"list": []},
                message="库存台账暂无记录" + (f"（单据号：{ref_no}）" if ref_no else ""),
            )

        logger.info(f"[stock_ledger_query] done: count={len(rows)}")
        return ToolResult(
            success=True,
            data={"list": rows},
            message=f"共找到 {len(rows)} 条库存台账记录",
        )