"""
营销海报工具（B 端黄金策，只读）

商家说「给这个商品做张海报 / 生成营销图 / 宣传图」时调用：把**商品事实**
（主图 / 名称 / 价格 / 单位 / 规格）与**操作员确认过的文案**组装成卡载荷，
由前端渲染成 750×1000 的 PNG 海报（PC 下载 / 手机长按保存到相册）。

🔴 本工具**不生成任何营销文案**（用户 2026-10-19 逐字：「有一些文案需要你引导操作员
提供给你，不要无脑的直接生成」）：
- `promo_title` / `selling_points` 是**必填**参数，缺任一 ⇒ fail-closed 返回
  `COPY_REQUIRED`，并给出「先问商家要文案」的纠偏建议；
- 服务端不读商品描述自动拼卖点、不编折扣/赠品/材质 —— 商品事实只来自 admin-api，
  文案只来自操作员。

卡片发射点：`app/api/chat.py::_detect_card_type` → `marketing_poster`；
跨端契约判据 = `tests/test_card_type_cross_end_contract.py`（B 端桌面 + B 端移动两端都要能渲染）。

权限：`GET /api/admin/products/{id}` 的读码 `product:list`（与 `product_detail` 同码）。
只读、仅 B 端（`c_end_reachable=False`）—— 海报是商家自用的营销物料，顾客端无此面。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client

#: 海报上最多展示的卖点条数（版面固定 3 行；多出的不静默吞掉 —— 由工具明确拒绝）
MAX_SELLING_POINTS = 3
#: 单条卖点上限（CJK 约 15 字/行 × 2 行）
MAX_SELLING_POINT_CHARS = 30
#: 主标题上限（740px 宽、两行 46px 字号）
MAX_TITLE_CHARS = 24


class MarketingPosterTool(BaseTool):
    """组装营销海报卡载荷（商品事实 + 操作员确认的文案）"""

    name = "marketing_poster"
    description = (
        "【触发】商家说「做张海报 / 生成营销海报 / 商品宣传图 / 发圈图」时调用。"
        "【前置·必须先问文案】本工具不会生成任何文案：调用前必须先问商家 ① 要宣传哪个商品"
        "（先用 product_search 定位 product_id）② 海报主标题（如「新品上市」「限时特惠」）"
        "③ 2~3 条卖点（商家逐字提供）。商家没给文案时不要调用本工具，先问；"
        "商家说「你帮我写」时给 2~3 个候选并让商家选定或修改，不得自行拍板。"
        "【参数】product_id（必填）/ promo_title（必填，商家确认的主标题）/ "
        "selling_points（必填，1~3 条商家确认的卖点，每条 ≤30 字）。"
        "【返回】营销海报卡（商品主图 + 名称 + 价格 + 单位 + 文案），前端可直接下载/保存到相册。"
        "【反例】不得用商品描述自动拼卖点；不得编造折扣/赠品/材质；没问过文案就调用 = 违规。"
        "【标注】READONLY"
    )

    # 与 `GET /api/admin/products/{id}` 的读码逐字同码（ProductController 的
    # `@RequirePermission("product:list")`，与 product_detail 同族）。
    required_permissions = ["product:list"]
    read_only = True
    # 仅 B 端：海报是商家营销物料，元元（顾客）没有这个面。
    c_end_reachable = False

    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品 ID（先 product_search 按商品名定位）",
            },
            "promo_title": {
                "type": "string",
                "description": "海报主标题，必须逐字来自商家（如「新品上市」「限时特惠」）",
            },
            "selling_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1~3 条卖点，必须逐字来自商家（每条 ≤30 字）",
            },
        },
        "required": ["product_id", "promo_title", "selling_points"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        promo_title: Optional[str] = None,
        selling_points: Optional[List[str]] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限生成营销海报",
                suggestion="请联系管理员开通商品查看权限（product:list）",
            )

        product_id = (product_id or "").strip()
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="请先告诉我要做哪个商品的海报",
                suggestion="缺少 product_id：先用 product_search 按商品名查到商品，再调用本工具",
                missing_params=["product_id"],
            )

        copy = _normalize_copy(promo_title, selling_points)
        if copy.get("error"):
            return ToolResult(
                success=False,
                error=copy["error"],
                message=copy["message"],
                suggestion=copy["suggestion"],
                missing_params=copy.get("missing_params"),
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                f"/api/admin/products/{product_id}",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_code = (response.get("error") or {}).get("code", "")
                error_msg = (response.get("error") or {}).get("message", "查询失败")
                # 结构化判定（只认 error.code）—— 不对中文文案做子串匹配
                # （判据 = tests/unit_ci_workflows/test_tool_input_contract_guards.py 的
                #  「中文措辞当判据」基线，只许缩短）。
                if error_code == "NOT_FOUND":
                    return admin_api_failure(
                        response,
                        error="商品不存在",
                        message="抱歉，未找到该商品，请检查商品 ID 是否正确",
                        suggestion="该商品 ID 在库中不存在，请改用 product_search 按商品名搜索，"
                                   "并把候选结果给商家确认后再做海报",
                    )
                return admin_api_failure(
                    response,
                    error=error_msg,
                    message="查询商品失败，暂时无法生成海报",
                    suggestion="请稍后重试；如持续失败请联系技术支持",
                )

            data = response.get("data") or {}
            if not data:
                return ToolResult(
                    success=False,
                    error="商品不存在",
                    message="抱歉，未找到该商品",
                    suggestion="该商品不存在或已下架，请改用 product_search 按商品名搜索并把候选给商家确认",
                )

            # 租户隔离（与 product_detail 同款）：跨租户一律按「不存在」处理
            resp_tenant_id = data.get("tenantId") or data.get("tenant_id")
            if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                logger.error(
                    f"Tenant data integrity violation in marketing_poster: "
                    f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
                )
                return ToolResult(
                    success=False,
                    error="商品不存在",
                    message="抱歉，未找到该商品",
                    suggestion="该商品不属于当前商户，请在本店范围内重新搜索",
                )

            product = _poster_product(data)
            logger.info(
                f"Marketing poster: id={product_id}, name={product.get('name')}, "
                f"tenant={context.tenant_id}"
            )

            return ToolResult(
                success=True,
                data={
                    "product": product,
                    "copy": {
                        "title": copy["title"],
                        "selling_points": copy["selling_points"],
                    },
                },
                message=f"已生成商品【{product.get('name')}】的营销海报",
                summary=(
                    f"营销海报卡：{product.get('name')}｜主标题「{copy['title']}」｜"
                    f"卖点 {len(copy['selling_points'])} 条"
                ),
            )

        except Exception as e:
            logger.error(f"Marketing poster error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="生成营销海报时出错，请稍后重试",
                suggestion="请稍后重试；如持续失败请联系技术支持",
            )


def _normalize_copy(
    promo_title: Optional[str],
    selling_points: Optional[List[str]],
) -> Dict[str, Any]:
    """校验「操作员提供的文案」；缺失/越界一律 fail-closed（不自动补文案）。"""
    title = (promo_title or "").strip() if isinstance(promo_title, str) else ""
    if not title:
        return {
            "error": "COPY_REQUIRED",
            "message": "还差海报主标题：请先问商家想在海报上写什么（例如「新品上市」「限时特惠」）",
            "suggestion": "先向商家要主标题 + 2~3 条卖点，拿到后再调用本工具；不要自行编造营销文案",
            "missing_params": ["promo_title"],
        }
    if len(title) > MAX_TITLE_CHARS:
        return {
            "error": "COPY_INVALID",
            "message": f"海报主标题太长了（最多 {MAX_TITLE_CHARS} 字），请商家精简一下",
            "suggestion": "让商家把主标题压到 24 字以内（海报版面只有两行）",
            "missing_params": [],
        }

    raw_points = selling_points if isinstance(selling_points, list) else []
    points = [p.strip() for p in raw_points if isinstance(p, str) and p.strip()]
    if not points:
        return {
            "error": "COPY_REQUIRED",
            "message": "还差卖点文案：请先问商家这个商品想突出哪 2~3 个卖点",
            "suggestion": "先向商家要 2~3 条卖点（逐字用商家给的，可参考商品规格），拿到后再调用本工具",
            "missing_params": ["selling_points"],
        }
    if len(points) > MAX_SELLING_POINTS:
        return {
            "error": "COPY_INVALID",
            "message": f"卖点最多 {MAX_SELLING_POINTS} 条（海报只放得下 3 行），请商家挑最重要的几条",
            "suggestion": f"让商家把卖点压到 {MAX_SELLING_POINTS} 条以内",
            "missing_params": ["selling_points"],
        }
    too_long = [p for p in points if len(p) > MAX_SELLING_POINT_CHARS]
    if too_long:
        return {
            "error": "COPY_INVALID",
            "message": f"有卖点太长（每条最多 {MAX_SELLING_POINT_CHARS} 字），请商家精简一下",
            "suggestion": "让商家把过长的卖点压到 30 字以内，或拆成多条（总数仍 ≤3）",
            "missing_params": ["selling_points"],
        }

    return {"title": title, "selling_points": points}


def _poster_product(data: Dict[str, Any]) -> Dict[str, Any]:
    """从 admin-api 商品详情里取**海报需要的事实**（不做任何营销加工）。"""
    images = data.get("images") if isinstance(data.get("images"), list) else []
    main_image = data.get("mainImage") or (images[0] if images else None)

    specs = data.get("specifications")
    spec_lines: List[str] = []
    if isinstance(specs, dict):
        for key, value in list(specs.items())[:3]:
            if key and value not in (None, ""):
                spec_lines.append(f"{key}：{value}")

    price = data.get("price")
    if price is None:
        price = data.get("basePrice")

    return {
        "id": data.get("id"),
        "name": data.get("name") or "未命名商品",
        "price": price,
        "unit": data.get("unit") or "件",
        "image": main_image,
        "specs": spec_lines,
    }
