"""
AI 智能客服系统 - 加工项管理 Tool

管理加工项写入操作，包括创建/更新/删除加工项、加工分类 CRUD、价格计算。
与 processing_item_query（查询）互补，本工具负责写入操作。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {
    "create_processing_item", "update_item", "delete_item", "toggle_item_status",
    "list_categories", "create_category", "update_category", "delete_category",
    "calculate_price",
}

# 计价方式 canonical 枚举（与 admin-api ProcessingItemService.validatePricingMethod
# 及 ProcessingItemCreateRequest.pricingMethod 对齐；issue #3005 回滚后无 per_piece）
VALID_PRICING_METHODS = {
    "per_meter": "按米",
    "per_set": "按套",
    "fixed": "一口价",
    "per_area": "按面积",
}

# admin-api `ProcessingItemUpdateRequest`（PUT /api/admin/processing-items/{id}）是
# **全量替换**语义：name / categoryId / pricingMethod 为 @NotBlank、unitPrice 为 @NotNull
# （另有 0.10~999.99 与最多 2 位小数约束），只发用户改动的那几个字段 → Bean Validation 失败
# → GlobalExceptionHandler 返回 **422**（issue #3584）。
# 故本工具更新加工项一律「GET 详情 → 用户显式传入字段覆盖 → PUT 全量」，
# 既保证必填齐全，也保证「只改一个字段」不会清空其它字段。
ITEM_REQUIRED_FIELDS = ("name", "categoryId", "pricingMethod", "unitPrice")
ITEM_REQUIRED_FIELD_LABELS = {
    "name": "name（加工项名称）",
    "categoryId": "categoryId（分类 ID，工具参数 category_id）",
    "pricingMethod": "pricingMethod（计价方式，工具参数 pricing_method）",
    "unitPrice": "unitPrice（单价，工具参数 price）",
}
ITEM_CARRY_OVER_FIELDS = ITEM_REQUIRED_FIELDS + (
    "unit", "minQuantity", "maxQuantity", "description", "options",
    "applicableProductCategories", "processingDays", "aiRecommended", "status",
)
UNIT_PRICE_MIN = 0.10
UNIT_PRICE_MAX = 999.99


class ProcessingItemManageTool(BaseTool):
    """加工项管理 Tool

    管理加工项写入操作：创建/更新/删除加工项、加工分类 CRUD、价格计算。

    使用场景：
    - 创建新的加工项（如打孔、窗帘头加工等）
    - 更新加工项信息（价格、名称、描述等）
    - 删除加工项
    - 管理加工分类（查看/创建/更新/删除）
    - 计算加工项价格
    """

    name = "processing_item_manage"
    description = (
        "【触发】写加工：用户说'新增加工项''修改加工''删除加工''加工分类管理''算加工价格'时调用。【前置】list_categories(查分类树,安全)。create/update/delete 需确认。【何时不用】仅查看加工项列表用 processing_item_query，不要混淆。【标注】WRITE|DESTRUCTIVE — list_categories安全,增删改需确认"
        "【铁律】用户说'新增加工项'就是执行指令：调 processing_item_manage(action=create_processing_item, name, category_id, pricing_method)——计价方式仅 per_meter(按米)/per_set(按套)/fixed(一口价)/per_area(按面积)，per_piece(按个)非法必须拒绝并说明（PP-006 实拍：agent 误宣「新增不在功能范围」，实际 create_processing_item 就是新增能力）。"
        "【铁律】用户明确要求写操作（禁用/创建/调整/删除/上下架/重置等）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（HR-003/PP-006/PR-005 实拍：agent 只 list/query 不执行写工具判失败）。"
        "【铁律】delete_item 是软删除（记录标记 deleted=1，非物理移除）：删除成功后按名称/列表复查查不到该加工项是正常结果（删除已生效），"
        "禁止误报「删除未生效」或建议用户去后台手动删除；如需恢复告知用户联系管理员（#3885）。"
    )
    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除加工项/分类
    read_only_actions = {"list_categories", "calculate_price"}  # 只读/纯计算 action 免确认拦截
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：create_processing_item（创建加工项）/ update_item（更新加工项）/ delete_item（删除加工项）"
                    "/ toggle_item_status（启用/停用加工项）"
                    "/ list_categories（分类列表）/ create_category（创建分类）/ update_category（更新分类）"
                    "/ delete_category（删除分类）/ calculate_price（计算价格）"
                ),
                "enum": [
                    "create_processing_item", "update_item", "delete_item", "toggle_item_status",
                    "list_categories", "create_category", "update_category", "delete_category",
                    "calculate_price",
                ],
            },
            "item_id": {
                "type": "string",
                "description": "加工项 ID（update_item/delete_item/toggle_item_status 时必填）",
            },
            "category_id": {
                "type": "string",
                "description": (
                    "加工分类 ID（create_processing_item 时必填；update_item 时可选——不传则沿用该加工项原分类；"
                    "update_category/delete_category 时必填）"
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "名称（create_processing_item/create_category 时必填；"
                    "update_item/update_category 时可选——不传则沿用原名称）"
                ),
            },
            "price": {
                "type": "number",
                "description": (
                    "单价（元，对应 admin-api 的 unitPrice；create_processing_item 时必填；"
                    "update_item 时可选——不传则沿用该加工项原单价）。"
                    "取值 0.10~999.99，最多 2 位小数"
                ),
            },
            "pricing_method": {
                "type": "string",
                "description": (
                    "计价方式（create_processing_item 时必填；update_item 时可选——不传则沿用原计价方式）："
                    "per_meter（按米）/ per_set（按套）"
                    "/ fixed（一口价）/ per_area（按面积）。不支持 per_piece（按个）——"
                    "行业加工费按米计价、辅料含在加工费中"
                ),
                "enum": ["per_meter", "per_set", "fixed", "per_area"],
            },
            "description": {
                "type": "string",
                "description": "描述信息（可选，update_item 传入时覆盖原描述）",
            },
            "unit": {
                "type": "string",
                "description": "计量单位（create_processing_item/update_item 时可选）",
            },
            "processing_item_id": {
                "type": "string",
                "description": "加工项 ID（calculate_price 时必填）",
            },
            "quantity": {
                "type": "number",
                "description": (
                    "数量（calculate_price 时必填；per_meter 传面料米数，per_set 传套数）。"
                    "⚠️ per_area（按面积）：quantity 是**计件数**（同一尺寸做几件，默认 1），"
                    "面积由 width×height 得出——禁止把宽×高写进 quantity（后端会再乘一次面积 → 双计）"
                ),
            },
            "width": {
                "type": "number",
                # exclusiveMinimum 0 = 与后端同口径（ProcessingItemService.calculateArea
                # 对 <=0 的尺寸抛「尺寸必须大于 0」），也是 #3622 的数值下限不变式要求。
                "exclusiveMinimum": 0,
                "description": "宽度（米，calculate_price 时按面积计价 per_area 必填；与 height 一起决定面积=宽×高，须大于 0）",
            },
            "height": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "高度（米，calculate_price 时按面积计价 per_area 必填；与 width 一起决定面积=宽×高，须大于 0）",
            },
            "status": {
                "type": "string",
                "description": "目标状态（toggle_item_status 时必填）：active（启用）/ inactive（停用）",
                "enum": ["active", "inactive"],
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        item_id: Optional[str] = None,
        category_id: Optional[str] = None,
        name: Optional[str] = None,
        price: Optional[float] = None,
        pricing_method: Optional[str] = None,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        processing_item_id: Optional[str] = None,
        quantity: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        status: Optional[str] = None,
    ) -> ToolResult:
        """执行加工项管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行加工项管理操作",
                suggestion="请联系管理员获取执行加工项管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "create_processing_item":
                return await self._create_item(
                    context, name, category_id, price, pricing_method, description, unit)
            elif action == "update_item":
                return await self._update_item(
                    context, item_id, name, category_id, price, pricing_method, description, unit)
            elif action == "delete_item":
                return await self._delete_item(context, item_id)
            elif action == "toggle_item_status":
                return await self._toggle_item_status(context, item_id, status)
            elif action == "list_categories":
                return await self._list_categories(context)
            elif action == "create_category":
                return await self._create_category(context, name, description)
            elif action == "update_category":
                return await self._update_category(context, category_id, name, description)
            elif action == "delete_category":
                return await self._delete_category(context, category_id)
            elif action == "calculate_price":
                return await self._calculate_price(
                    context, processing_item_id, quantity, width, height)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[processing-item-manage] Failed: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="加工项管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _create_item(
        self,
        context: ToolContext,
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        pricing_method: Optional[str] = None,
        description: Optional[str] = None,
        unit: Optional[str] = None,
    ) -> ToolResult:
        """创建加工项

        请求体契约以 admin-api `ProcessingItemCreateRequest` 为准（issue #3543）：
        `name` / `categoryId` / `pricingMethod`(@NotBlank) / `unitPrice`(@NotNull)，
        其中工具/LLM 侧单价参数名为 `price` → **显式映射**到 `unitPrice`。
        """
        if not name:
            return ToolResult(
                success=False,
                error="缺少加工项名称",
                message="创建加工项时必须提供 name",
            )
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="创建加工项时必须提供 category_id",
            )
        if price is None:
            return ToolResult(
                success=False,
                error="缺少价格",
                message="创建加工项时必须提供 price",
            )
        if not pricing_method:
            return ToolResult(
                success=False,
                error="缺少计价方式",
                message="创建加工项时必须提供 pricing_method（计价方式）",
                suggestion=(
                    "请向用户确认计价方式，仅支持："
                    "per_meter（按米）/ per_set（按套）/ fixed（一口价）/ per_area（按面积）"
                ),
            )
        if pricing_method not in VALID_PRICING_METHODS:
            options = " / ".join(f"{k}（{v}）" for k, v in VALID_PRICING_METHODS.items())
            return ToolResult(
                success=False,
                error=f"不支持的计价方式: {pricing_method}",
                message=(
                    f"加工项计价方式仅支持：{options}；per_piece（按个）等其它计价方式不支持，"
                    f"实际收到 {pricing_method!r}"
                ),
                suggestion=(
                    "请向用户说明加工项只支持上述 4 种计价方式（行业加工费按米计价、辅料含在加工费中），"
                    "请用户重新选择，不要自行改成其它计价方式"
                ),
            )

        json_data: Dict[str, Any] = {
            "name": name,
            "categoryId": category_id,
            # 显式映射：admin-api DTO 字段名为 pricingMethod / unitPrice（无 price）
            "pricingMethod": pricing_method,
            "unitPrice": price,
        }
        if description:
            json_data["description"] = description
        if unit:
            json_data["unit"] = unit

        logger.info(
            f"[processing-item-manage] CreateItem: name={name}, category_id={category_id}, "
            f"price={price}, pricing_method={pricing_method} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-items",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建加工项失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"加工项「{name}」创建成功",
        )

    async def _put_item_full(
        self,
        context: ToolContext,
        item_id: str,
        overrides: Dict[str, Any],
        action_label: str,
        fail_prefix: str,
        success_message: str,
    ) -> ToolResult:
        """GET 详情 → 用户显式传入字段覆盖 → PUT 全量（admin-api 是全量替换语义，issue #3584）"""
        client = get_admin_api_client()
        detail_response = await client.get(
            f"/api/admin/processing-items/{item_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not detail_response.get("success"):
            error_msg = detail_response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"{fail_prefix}：读取加工项详情失败——{error_msg}",
                suggestion="请确认 item_id 是否正确（可先用 processing_item_query 查询加工项）",
            )

        detail = detail_response.get("data") or {}
        json_data: Dict[str, Any] = {
            key: detail.get(key) for key in ITEM_CARRY_OVER_FIELDS if detail.get(key) is not None
        }
        json_data.update(overrides)

        missing = [key for key in ITEM_REQUIRED_FIELDS if json_data.get(key) in (None, "")]
        if missing:
            return ToolResult(
                success=False,
                error="加工项缺少必填字段",
                message=(
                    f"更新加工项需全量提交必填字段，但该加工项缺少："
                    f"{'、'.join(ITEM_REQUIRED_FIELD_LABELS[key] for key in missing)}，无法自动补齐"
                ),
                suggestion="请让用户补齐上述字段后重试（在本次调用中显式提供对应参数）",
            )

        logger.info(
            f"[processing-item-manage] {action_label}: item_id={item_id}, "
            f"fields={list(json_data.keys())} | tenant={context.tenant_id}"
        )

        response = await client.put(
            f"/api/admin/processing-items/{item_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"{fail_prefix}：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"item_id": item_id, **(response.get("data") or {})},
            message=success_message,
        )

    async def _update_item(
        self,
        context: ToolContext,
        item_id: Optional[str],
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        pricing_method: Optional[str] = None,
        description: Optional[str] = None,
        unit: Optional[str] = None,
    ) -> ToolResult:
        """更新加工项

        请求体契约以 admin-api `ProcessingItemUpdateRequest` 为准（issue #3584）：
        全量替换语义，`name`/`categoryId`/`pricingMethod`(@NotBlank) + `unitPrice`(@NotNull)
        缺一即 422；工具/LLM 侧单价参数名为 `price` → **显式映射**到 `unitPrice`。
        未传的字段从 GET 详情继承（不传 ≠ 清空）。
        """
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="更新加工项时必须提供 item_id",
            )

        if pricing_method is not None and pricing_method not in VALID_PRICING_METHODS:
            options = " / ".join(f"{k}（{v}）" for k, v in VALID_PRICING_METHODS.items())
            return ToolResult(
                success=False,
                error=f"不支持的计价方式: {pricing_method}",
                message=(
                    f"加工项计价方式仅支持：{options}；per_piece（按个）等其它计价方式不支持，"
                    f"实际收到 {pricing_method!r}"
                ),
                suggestion="请向用户确认计价方式后重试，不要自行改成其它计价方式",
            )

        if price is not None and not (UNIT_PRICE_MIN <= price <= UNIT_PRICE_MAX):
            return ToolResult(
                success=False,
                error="单价超出允许范围",
                message=(
                    f"加工项单价必须在 {UNIT_PRICE_MIN:.2f} ~ {UNIT_PRICE_MAX:.2f} 元之间"
                    f"（最多 2 位小数），实际收到 {price}"
                ),
                suggestion="请向用户确认单价后重试",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["unitPrice"] = price  # 显式映射：DTO 字段名为 unitPrice（无 price）
        if pricing_method:
            json_data["pricingMethod"] = pricing_method
        if description:
            json_data["description"] = description
        if unit:
            json_data["unit"] = unit

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新加工项时至少提供 name、category_id、price、pricing_method 或 description 之一",
            )

        return await self._put_item_full(
            context,
            item_id,
            json_data,
            action_label="UpdateItem",
            fail_prefix="更新加工项失败",
            success_message="加工项已更新",
        )

    async def _delete_item(self, context: ToolContext, item_id: Optional[str]) -> ToolResult:
        """删除加工项"""
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="删除加工项时必须提供 item_id",
            )

        logger.info(f"[processing-item-manage] DeleteItem: item_id={item_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/processing-items/{item_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除加工项失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"item_id": item_id},
            message=(
                f"已删除加工项（ID: {item_id}，软删除）；"
                "此后按名称/列表查询将查不到该加工项（查不到即删除已生效，属正常结果），"
                "如需恢复请联系管理员"
            ),
        )

    async def _toggle_item_status(
        self,
        context: ToolContext,
        item_id: Optional[str],
        status: Optional[str],
    ) -> ToolResult:
        """启用/停用加工项

        admin-api **没有** `PUT /api/admin/processing-items/{id}/status` 子资源
        （该路径恒 404，issue #3584）；`status` 是 `ProcessingItemUpdateRequest` 的合法
        可选字段 → 走真实存在的 `PUT /{id}`；因该端点是全量替换语义，
        同样「GET 详情 → merge → PUT 全量」，避免只发 status 触发 422 或清空其它字段。
        """
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="启用/停用加工项时必须提供 item_id",
            )
        if not status or status not in ("active", "inactive"):
            return ToolResult(
                success=False,
                error=f"无效的状态值: {status}",
                message="请提供有效的状态值：active（启用）或 inactive（停用）",
            )

        status_text = "启用" if status == "active" else "停用"
        return await self._put_item_full(
            context,
            item_id,
            {"status": status},
            action_label="ToggleItemStatus",
            fail_prefix="加工项状态更新失败",
            success_message=f"加工项已{status_text}",
        )

    async def _list_categories(self, context: ToolContext) -> ToolResult:
        """获取加工分类列表"""
        logger.info(f"[processing-item-manage] ListCategories | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/processing-categories",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取加工分类列表失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"categories": response.get("data", [])},
            message="已获取加工分类列表",
        )

    async def _create_category(
        self,
        context: ToolContext,
        name: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """创建加工分类"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="创建加工分类时必须提供 name",
            )

        json_data: Dict[str, Any] = {"name": name}
        if description:
            json_data["description"] = description

        logger.info(
            f"[processing-item-manage] CreateCategory: name={name} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-categories",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"加工分类「{name}」创建成功",
        )

    async def _update_category(
        self,
        context: ToolContext,
        category_id: Optional[str],
        name: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """更新加工分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="更新加工分类时必须提供 category_id",
            )
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="更新加工分类时必须提供 name",
            )

        json_data: Dict[str, Any] = {"name": name}
        if description:
            json_data["description"] = description

        logger.info(
            f"[processing-item-manage] UpdateCategory: category_id={category_id}, name={name} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/processing-categories/{category_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id, **json_data},
            message=f"加工分类已更新为「{name}」",
        )

    async def _delete_category(self, context: ToolContext, category_id: Optional[str]) -> ToolResult:
        """删除加工分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="删除加工分类时必须提供 category_id",
            )

        logger.info(
            f"[processing-item-manage] DeleteCategory: category_id={category_id} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/processing-categories/{category_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id},
            message="加工分类已删除",
        )

    async def _calculate_price(
        self,
        context: ToolContext,
        processing_item_id: Optional[str],
        quantity: Optional[float],
        width: Optional[float] = None,
        height: Optional[float] = None,
    ) -> ToolResult:
        """计算加工项价格

        ⚠️ 本端点（POST /api/admin/processing-items/calculate）与 `order_create` **不是同一套契约**
        （issue #3672；契约差异的归因见 `acceptance/2026-09-15/agent-gap-triage/REPORT.md` §G4）：

        - `order_create`：agent 自己把 per_area 的 `quantity` 算成「宽×高」放进
          `processing_info`，后端只做 `unitPrice × quantity`；
        - **本端点**：后端自己从请求体的 `dimensions` 算 `area = 宽×高`，再算
          `totalPrice = unitPrice × area × quantity`（`ProcessingItemService.java:248-254`；
          缺 width/height → `:310-318` 直接抛「按面积计价需要提供 width 和 height 尺寸」）。

        ⇒ per_area 必须下发 `dimensions`，且 `quantity` 是**计件数**（同一尺寸做几件，缺省 1）。
        把「宽×高」写进 quantity 会**双计**（30×8×8 = ¥1920，应为 ¥240）。
        """
        if not processing_item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="计算价格时必须提供 processing_item_id",
            )
        if (width is None) != (height is None):
            return ToolResult(
                success=False,
                error="尺寸不完整",
                message="按面积计价需要同时提供宽度和高度（width 与 height，单位：米）",
            )

        has_dimensions = width is not None and height is not None
        if quantity is None:
            if not has_dimensions:
                return ToolResult(
                    success=False,
                    error="缺少数量",
                    message="计算价格时必须提供 quantity",
                )
            # per_area：面积由 dimensions 承载，quantity 是计件数，缺省 1
            quantity = 1

        logger.info(
            f"[processing-item-manage] CalculatePrice: item_id={processing_item_id}, "
            f"quantity={quantity}, dimensions={width}x{height} | tenant={context.tenant_id}"
        )

        json_data: Dict[str, Any] = {
            "processingItemId": processing_item_id,
            "quantity": quantity,
        }
        if has_dimensions:
            json_data["dimensions"] = {"width": width, "height": height}

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-items/calculate",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "计算失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"计算加工价格失败：{error_msg}",
            )

        data = response.get("data", {})
        total_price = data.get("totalPrice") or data.get("total_price", "")

        return ToolResult(
            success=True,
            data=data,
            message=f"加工价格计算结果：{total_price}",
        )
