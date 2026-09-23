"""
AI 智能客服系统 - 加工项管理 Tool

管理加工项写入操作，包括创建/更新/删除加工项、加工分类 CRUD。
与 processing_item_query（查询）互补，本工具负责写入操作。

⚠️ issue #4882：`calculate_price`（POST /api/admin/processing-items/calculate）已随
「加工项单价 + 计价方式」从 admin-api 一并退场（该端点算的就是 unitPrice × …）⇒
本工具同步删除该 action（死 action 会指向恒 404 的端点；守卫见
`tests/test_tools_processing_item_manage.py` 的 schema↔admin-api 端点一致性用例）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {
    "create_processing_item", "update_item", "delete_item", "toggle_item_status",
    "list_categories", "create_category", "update_category", "delete_category",
}

# 加工项**不再有单价与计价方式**（issue #4882）：admin-api 的
# `ProcessingItemCreateRequest` / `ProcessingItemUpdateRequest` 已把
# `pricingMethod` / `unitPrice` 两个字段**整体删除**（连带 0.10~999.99 价格区间与
# 计价方式枚举校验一起退场）⇒ 加工项只需要 `name` + `categoryId`（`craftHint` 可选）。

# admin-api `ProcessingItemUpdateRequest`（PUT /api/admin/processing-items/{id}）是
# **全量替换**语义：name / categoryId 为 @NotBlank，只发用户改动的那几个字段
# → Bean Validation 失败 → GlobalExceptionHandler 返回 **422**（issue #3584）。
# 故本工具更新加工项一律「GET 详情 → 用户显式传入字段覆盖 → PUT 全量」，
# 既保证必填齐全，也保证「只改一个字段」不会清空其它字段。
ITEM_REQUIRED_FIELDS = ("name", "categoryId")
ITEM_REQUIRED_FIELD_LABELS = {
    "name": "name（加工项名称）",
    "categoryId": "categoryId（分类 ID，工具参数 category_id）",
}
# ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：`applicableProductCategories`
# （加工项的「适用商品分类」）**已从 admin-api 的 DTO/实体/schema 整体退场**
# （V66 迁移 `DROP COLUMN`），故从本「全量 PUT 时回带字段」白名单移除。
# 留在白名单里的后果不是报错而是**静默**：Java 侧 `ProcessingItemUpdateRequest`
# 已无该字段 ⇒ Spring 静默忽略 ⇒ 每次「GET 详情 → 覆盖 → PUT 全量」都会把它丢掉，
# 而工具照样返回成功（工具审计 A4「下发 DTO 没有的键 = 无声丢数据」同型）。
# `craftHint`（V78 / issue #4452：加工项**显式声明的工艺**）必须在回带白名单里 ——
# PUT 是全量替换，GET 详情里读到的工艺声明若不回带就会**静默丢失**（工艺维一丢，
# 该加工项就取不到工序路线）。回带的是**读回来的原值**，不猜、不推导。
ITEM_CARRY_OVER_FIELDS = ITEM_REQUIRED_FIELDS + (
    "unit", "craftHint", "minQuantity", "maxQuantity", "description", "options",
    "processingDays", "aiRecommended", "status",
)


class ProcessingItemManageTool(BaseTool):
    """加工项管理 Tool

    管理加工项写入操作：创建/更新/删除加工项、加工分类 CRUD。

    使用场景：
    - 创建新的加工项（如打孔、窗帘头加工等）
    - 更新加工项信息（名称、分类、描述、工艺声明等）
    - 删除加工项
    - 管理加工分类（查看/创建/更新/删除）
    """

    name = "processing_item_manage"
    description = (
        "【触发】用户说'新增加工项''修改加工''删除加工''加工分类管理'时调用。"
        "【参数】action 必填：list_categories（查分类树）只读；create_processing_item（name + category_id，"
        "craft_hint 可选）/ update_item / delete_item / toggle_item_status / create_category / "
        "update_category / delete_category 为写操作，item_id 或 category_id 按 action 必填。"
        "【反例】仅查看加工项目录用 processing_item_query，不要混淆；商品加工项关联/建品用 product_manage。"
        "【标注】WRITE|DESTRUCTIVE — list_categories 只读；增删改前必须二次确认"
        "【铁律】用户说'新增加工项'就是执行指令：调 processing_item_manage(action=create_processing_item, name, category_id, craft_hint)——加工项**不再有单价与计价方式**（issue #4882 已从 admin-api 彻底删除），只需要 name + category_id（craft_hint 可选）"
        "（PP-006 实拍：agent 误宣「新增不在功能范围」，实际 create_processing_item 就是新增能力）。"
        "【铁律】用户明确要求写操作（禁用/创建/调整/删除/上下架/重置等）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（HR-003/PP-006/PR-005 实拍：agent 只 list/query 不执行写工具判失败）。"
        "【铁律】delete_item 是软删除（记录标记 deleted=1，非物理移除）：删除成功后按名称/列表复查查不到该加工项是正常结果（删除已生效），"
        "禁止误报「删除未生效」或建议用户去后台手动删除；如需恢复告知用户联系管理员（#3885）。"
    )
    # 权限码（admin-api 目录）：ProcessingItemController / ProcessingCategoryController 类级
    # `@RequirePermission("processing:manage")`。
    # 此前写死 ["admin","tenant_admin"] ⇒ operator / product_manager 持码却被判「权限不足」（#4106 F4）。
    required_permissions = ["processing:manage"]

    read_only = False
    destructive = True   # 可删除加工项/分类
    read_only_actions = {"list_categories"}  # 只读 action 免确认拦截
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
                    "/ delete_category（删除分类）"
                ),
                "enum": [
                    "create_processing_item", "update_item", "delete_item", "toggle_item_status",
                    "list_categories", "create_category", "update_category", "delete_category",
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
            "craft_hint": {
                "type": "string",
                "maxLength": 16,
                "description": (
                    "工艺声明（可选，≤16 字）：该加工项代表哪个工艺"
                    "（韩褶/打孔/穿杆/平幔…），是加工单工序路线的**受控来源**。"
                    "不要凭加工项**名字**猜工艺；不确定就不传（留空 = 没声明）"
                ),
            },
            "description": {
                "type": "string",
                "description": "描述信息（可选，update_item 传入时覆盖原描述）",
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
        craft_hint: Optional[str] = None,
        description: Optional[str] = None,
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
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "create_processing_item":
                return await self._create_item(
                    context, name, category_id, craft_hint, description)
            elif action == "update_item":
                return await self._update_item(
                    context, item_id, name, category_id, craft_hint, description)
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
        craft_hint: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ToolResult:
        """创建加工项

        请求体契约以 admin-api `ProcessingItemCreateRequest` 为准（issue #3543 / #4882）：
        必填只有 `name` / `categoryId`（均 @NotBlank）——**单价与计价方式已整体删除**；
        `craftHint`（工艺声明，≤16 字）可选。
        """
        if not name:
            return ToolResult(
                success=False,
                error="缺少加工项名称",
                message="创建加工项时必须提供 name",
                suggestion="缺少加工项名称 name，请向用户询问加工项名称后重试",
            )
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="创建加工项时必须提供 category_id",
                suggestion="缺少分类 category_id，请先用 processing_item_manage 的 list_categories 操作取到分类后重试",
            )
        json_data: Dict[str, Any] = {
            "name": name,
            "categoryId": category_id,
            # 单价/计价方式字段已随 #4882 从 DTO 删除；单位固定「米」——
            # 行业加工费按米计价（issue #3005），不再由调用方传（避免展示口径漂移）。
            "unit": "米",
        }
        if craft_hint:
            json_data["craftHint"] = craft_hint
        if description:
            json_data["description"] = description

        logger.info(
            f"[processing-item-manage] CreateItem: name={name}, category_id={category_id}, "
            f"craft_hint={craft_hint} | tenant={context.tenant_id}"
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"创建加工项失败：{error_msg}",
                suggestion="请先用 processing_item_manage 的 list 操作确认是否已有同名加工项，再改用更新或换一个名称",
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
            return admin_api_failure(detail_response,
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"{fail_prefix}：{error_msg}",
                suggestion="请先读取该加工项详情，核对必填字段（名称/分类）是否齐全后再重试",
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
        craft_hint: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ToolResult:
        """更新加工项

        请求体契约以 admin-api `ProcessingItemUpdateRequest` 为准（issue #3584 / #4882）：
        全量替换语义，必填只有 `name`/`categoryId`(@NotBlank)（**单价/计价方式字段已删除**）；
        未传的字段从 GET 详情继承（不传 ≠ 清空）。
        """
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="更新加工项时必须提供 item_id",
                suggestion="缺少加工项 ID item_id，请先用 processing_item_query 查到该加工项后重试",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if category_id:
            json_data["categoryId"] = category_id
        if craft_hint:
            json_data["craftHint"] = craft_hint
        if description:
            json_data["description"] = description

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新加工项时至少提供 name、category_id、craft_hint 或 description 之一",
                suggestion="缺少更新内容，请让用户给出要修改的字段（名称/分类/工艺声明/描述）后重试",
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
                suggestion="缺少加工项 ID item_id，请先用 processing_item_query 查到该加工项后重试",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"删除加工项失败：{error_msg}",
                suggestion="请先用 processing_item_query 确认该加工项存在、且未被订单或商品引用后再重新执行删除",
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
                suggestion="缺少加工项 ID item_id，请先用 processing_item_query 查到该加工项后重试",
            )
        if not status or status not in ("active", "inactive"):
            return ToolResult(
                success=False,
                error=f"无效的状态值: {status}",
                message="请提供有效的状态值：active（启用）或 inactive（停用）",
                suggestion="status 只支持 active（启用）/ inactive（停用），请按用户意图改传其中一个后重试",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取加工分类列表失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改用 processing_item_query 按分类名查询，或请用户联系管理员核对加工分类配置",
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
                suggestion="缺少分类名称 name，请向用户询问加工分类名称后重试",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"创建加工分类失败：{error_msg}",
                suggestion="请先用 processing_item_manage 的 list_categories 操作确认是否已有同名分类，再改用更新或换一个名称",
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
                suggestion="缺少分类 ID category_id，请先用 processing_item_manage 的 list_categories 操作取到分类后重试",
            )
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="更新加工分类时必须提供 name",
                suggestion="缺少分类名称 name，请向用户询问新的分类名称后重试",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"更新加工分类失败：{error_msg}",
                suggestion="请先用 processing_item_manage 的 list_categories 操作确认该分类仍在，再重新执行更新",
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
                suggestion="缺少分类 ID category_id，请先用 processing_item_manage 的 list_categories 操作取到分类后重试",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"删除加工分类失败：{error_msg}",
                suggestion="请先用 processing_item_manage 的 list 操作确认该分类下已无加工项，再重新执行删除",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id},
            message="加工分类已删除",
        )
