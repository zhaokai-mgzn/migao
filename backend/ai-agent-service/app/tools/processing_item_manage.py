"""
AI 智能客服系统 - 加工项管理 Tool

管理加工项写入操作：创建 / 更新（含启用停用）/ 加工分类增改。
与 processing_item_query（查询）互补，本工具负责写入操作。

⚠️ issue #8618（2026-11-04，B 端工具缺口接回）：本工具此前**不绑任何 skill**（能力物理不可达），
现绑进 B 端 `product` 域。接回形态照 `employee_manage`（#7050）：
1. 权限走既有声明（`required_permissions`，与 admin-api `ProcessingItemController` 类级注解同码），
   **不自己判角色**；
2. 确认走 `BaseTool` 的既有门禁（`read_only=False` + `requires_confirmation=True` +
   `read_only_actions` 豁免只读 action）—— 不自建第二套；
3. **删除类 action 已从本工具退场**（`delete_item` / `delete_category`）：用户裁定
   「只能改，不能删」⇒ 不可逆删除不进 B 端对话面（判据 =
   `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的不可逆动作闭词表）。
   **停用**不是删除：它是 `update_item(status=…)` 的一次**变更**（可再改回 active，幂等）。

⚠️ issue #4882：`calculate_price`（POST /api/admin/processing-items/calculate）已随
「加工项单价 + 计价方式」从 admin-api 一并退场（该端点算的就是 unitPrice × …）⇒
本工具同步删除该 action（死 action 会指向恒 404 的端点；守卫见
`tests/test_tools_processing_item_manage.py` 的 schema↔admin-api 端点一致性用例）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型（issue #8618：`delete_item` / `delete_category` / `toggle_item_status` 已退场 ——
# 删除不可逆 ⇒ 不在 B 端支持面；停用改由 `update_item(status=…)` 表达，语义 = 一次可逆的变更）
VALID_ACTIONS = {"create_processing_item", "update_item", "list_categories", "create_category", "update_category"}

#: 只读 action —— 免确认拦截（`base_skill._requires_confirmation` 直接读这个字段）。
READ_ONLY_ACTIONS = frozenset({"list_categories"})

#: 写 action（走确认门禁）。
WRITE_ACTIONS = frozenset(VALID_ACTIONS - READ_ONLY_ACTIONS)

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

    管理加工项写入操作：创建 / 更新（含启用停用）/ 加工分类增改。

    使用场景：
    - 创建新的加工项（如打孔、窗帘头加工等）
    - 更新加工项信息（名称、分类、描述、工艺声明、状态）
    - 管理加工分类（查看/创建/更新）
    """

    name = "processing_item_manage"
    description = (
        "【触发】用户说'新增加工项''修改加工''把加工项停用/启用''加工分类管理'时调用。"
        "【参数】action 必填：list_categories（查分类）只读；create_processing_item（name + category_id，"
        "craft_hint 可选）/ update_item（item_id + 至少一个要改的字段，含 status）/ "
        "create_category / update_category 为写操作，需确认。"
        "【反例】仅查看加工项目录用 processing_item_query，不要混淆；商品加工项关联 / 新建商品请引导商家到后台「商品管理」页操作（黄金策不建商品）。"
        "【标注】WRITE — list_categories 只读；增改前必须二次确认"
        "【铁律】用户说'新增加工项'就是执行指令：调 processing_item_manage(action=create_processing_item, name, category_id, craft_hint)——加工项**不再有单价与计价方式**（issue #4882 已从 admin-api 彻底删除），只需要 name + category_id（craft_hint 可选）"
        "（PP-006 实拍：agent 误宣「新增不在功能范围」，实际 create_processing_item 就是新增能力）。"
        "【铁律】用户明确要求写操作（启用/停用/创建/调整）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（PP-006/PP-007/PP-008 实拍：agent 只 list/query 不执行写工具判失败）。"
        "【口径】停用/启用加工项 = `update_item(item_id, status=inactive|active)`（同一次变更，可再改回）；"
        "**删除加工项 / 删除加工分类不在能力内**（不可逆）——如实说明并引导到后台"
        "「企业基础设置 → 加工项与加工费」页面操作。"
        "【不要用于】加工项目录查询（用 processing_item_query）；加工单状态（用 processing_order_query）"
    )
    # 权限码（admin-api 目录）：ProcessingItemController / ProcessingCategoryController 类级
    # `@RequirePermission("processing:manage")`。
    # 此前写死 ["admin","tenant_admin"] ⇒ operator / product_manager 持码却被判「权限不足」（#4106 F4）。
    required_permissions = ["processing:manage"]

    read_only = False
    read_only_actions = READ_ONLY_ACTIONS  # list_categories 免确认拦截
    requires_confirmation = True           # 写操作走既有确认门禁（#8618；不自建第二套）
    destructive = False                  # 删除类 action 已退场（只剩增改）
    idempotent = False   # 创建非幂等；update_item 是覆盖式全量 PUT

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：create_processing_item（创建加工项）/ update_item（更新加工项，含 status 启用停用）"
                    "/ list_categories（分类列表）/ create_category（创建分类）/ update_category（更新分类）"
                ),
                "enum": [
                    "create_processing_item", "update_item",
                    "list_categories", "create_category", "update_category",
                ],
            },
            "item_id": {
                "type": "string",
                "description": "加工项 ID（update_item 时必填）",
            },
            "category_id": {
                "type": "string",
                "description": (
                    "加工分类 ID（create_processing_item 时必填；update_item 时可选——不传则沿用该加工项原分类；"
                    "update_category 时必填）"
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
                "description": (
                    "目标状态（update_item 时可选）：active（启用）/ inactive（停用）。"
                    "停用/启用就是一次 status 变更，可再改回来"
                ),
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
                    context, item_id, name, category_id, craft_hint, description, status)
            elif action == "list_categories":
                return await self._list_categories(context)
            elif action == "create_category":
                return await self._create_category(context, name, description)
            elif action == "update_category":
                return await self._update_category(context, category_id, name, description)
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
            # 字面量必须**内联**在构造点：能力下线族守卫按字面量解析运行期文本，
            # 经函数参数传入的 message 它取不到 ⇒ 会把这条文本当成「静默免检」判红。
            message="加工项已更新",
        )

    async def _update_item(
        self,
        context: ToolContext,
        item_id: Optional[str],
        name: Optional[str],
        category_id: Optional[str],
        craft_hint: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> ToolResult:
        """更新加工项（含启用/停用这一种变更）

        请求体契约以 admin-api `ProcessingItemUpdateRequest` 为准（issue #3584 / #4882）：
        全量替换语义，必填只有 `name`/`categoryId`(@NotBlank)（**单价/计价方式字段已删除**）；
        未传的字段从 GET 详情继承（不传 ≠ 清空）。

        🔴 `status`（issue #8618）：启用/停用**不是**独立 action，就是这一次变更的一个字段
        —— admin-api 没有 `PUT /{id}/status` 子资源（该路径恒 404，issue #3584），
        `status` 是 `ProcessingItemUpdateRequest` 的合法可选字段 ⇒ 同样走「详情 → merge → PUT 全量」。
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
        if status:
            if status not in ("active", "inactive"):
                return ToolResult(
                    success=False,
                    error=f"无效的状态值: {status}",
                    message="请提供有效的状态值：active（启用）或 inactive（停用）",
                    suggestion="status 只支持 active（启用）/ inactive（停用），请按用户意图改传其中一个后重试",
                )
            json_data["status"] = status

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新加工项时至少提供 name、category_id、craft_hint、description 或 status 之一",
                suggestion="缺少更新内容，请让用户给出要修改的字段（名称/分类/工艺声明/描述/启用停用）后重试",
            )

        return await self._put_item_full(
            context,
            item_id,
            json_data,
            action_label="UpdateItem",
            fail_prefix="更新加工项失败",
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
