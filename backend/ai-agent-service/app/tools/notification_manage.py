"""
AI 智能客服系统 - 通知管理 Tool

查询站内通知列表与未读数，并可**标记已读**（单条 / 全部）。

## 能力边界（用户 2026-10-16 裁定「能力边界 终版」，issue #5247 最新评论）

B 端黄金策的支持面 = **变更（改已存在对象/单据）+ 查询 / 分析 / 导航**；**创建**（商品 /
订单 / 其他单据类）与**删除 / 停用 / 作废**（不可逆）**不支持**。

按此口径，本工具在 issue #5247 的「整域收窄为只读」之上**接回变更 action**（issue #7040）：
- ✅ `mark_read`（标记单条已读）/ `read_all`（全部标记已读）—— **变更**。
- ❌ `delete`（删除通知）—— **删除**，不在支持面内 ⇒ 仍**不提供**（admin-api 有
  `DELETE /api/admin/notifications/{id}` 端点，按裁定 agent 侧不接线，只能引导用户去后台）。
- ❌ `create`（给**别人**发通知）—— **创建** + 对外动作 ⇒ 仍不提供（端点
  `POST /api/admin/notifications` 存在且挂 `system:manage`，按裁定不接线）。

⚠️ `VALID_ACTIONS` 是本工具 action 面的**唯一真值**（判据：
`backend/ai-agent-service/tests/test_notification_manage_change_actions.py` +
`tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 1/3/8）。

## 端点逐条核对（Java `NotificationController`；接线前已核，issue #7040）

| action | 端点 | 生效权限码 |
|---|---|---|
| `list` | `GET /api/admin/notifications` | 无（自助：收件人恒取 `SecurityContext`） |
| `unread_count` | `GET /api/admin/notifications/unread-count` | 无 |
| `mark_read` | `PUT /api/admin/notifications/{id}/read` | 无 |
| `read_all` | `PUT /api/admin/notifications/read-all` | 无 |
| ~~`delete`~~ | `DELETE /api/admin/notifications/{id}` | **有意不接线**（删除 ⊂ 严禁） |
| ~~`create`~~ | `POST /api/admin/notifications` | **有意不接线**（创建 + 对外发送） |

四个自助端点在 `NotificationController` 里**都没有** `@RequirePermission`（自助语义，
加码反而会让「通知中心」菜单点开就 403，issues #4727 / #5236）⇒ 本工具**不声明权限码**、
回到**角色层**（`allowed_roles` 必须在类体显式声明，见下）。原
`["system:manage", "employee:list"]` 是写路径的码（前者 = `POST` 建通知，后者 = create
解析收件人用的 `GET /api/admin/users`）⇒ 随 `create` 一并**不接线**。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


#: 操作类型 —— **变更 + 查询**，零创建、零删除（#7040 按 2026-10-16「能力边界 终版」接线）
VALID_ACTIONS = {"list", "unread_count", "mark_read", "read_all"}

#: 只读 action（免确认拦截）—— 其余 action 走 `BaseTool` 的写确认门禁
READ_ONLY_ACTIONS = frozenset({"list", "unread_count"})

# 通知渠道
VALID_CHANNELS = {"system", "email", "sms", "wechat"}

# 通知状态
VALID_STATUSES = {"unread", "read"}

# 渠道值映射：tool 暴露给 LLM 的语义化值 → admin-api 实际使用的值
# admin-api 数据库中站内通知 channel 字段实际值为 "internal"，而非 "system"
CHANNEL_TO_API = {
    "system": "internal",
    "internal": "internal",
    "email": "email",
    "sms": "sms",
    "wechat": "wechat",
}

# 状态值映射：tool 暴露的语义化值 → admin-api 数据库实际状态
# admin-api notifications.status 实际值为 "sent"（未读）/ "read"（已读）
STATUS_TO_API = {
    "unread": "sent",
    "read": "read",
}

# ⚠️ 端点路径**不抽成模块常量**（有意，issue #7040）：`tests/test_tool_payload_backend_contract.py`
# 的归属守卫按**静态可读的路径字面量 / f-string** 归属调用点 —— 间接成 `Name` 节点会被判
# 「无法归属到端点」（脱离跨模块契约门禁的射程）。端点与 Java `NotificationController` 的
# `@*Mapping` 逐字对应关系写在**本文件头部的端点表**里（同源单一处）。


class NotificationManageTool(BaseTool):
    """通知管理 Tool（查询 + 标记已读）

    使用场景：
    - 查询通知列表，按状态或渠道筛选
    - 获取未读通知数量
    - 标记**单条**通知已读（`mark_read`，需 `notification_id`）
    - **全部**标记已读（`read_all`）

    **不提供**：删除通知 / 发送通知 —— 引导用户到商户后台「通知中心」页处理。
    """

    name = "notification_manage"
    description = (
        "【触发】用户问'通知''消息''未读''有没有通知'，或要求'把通知标为已读''全部已读'时调用。"
        "【参数】action 必填：list（查询列表）/ unread_count（未读数）为**只读**；"
        "mark_read（标记单条已读，需 notification_id，可先从 list 取 id）/ read_all（全部标记已读）"
        "为**变更**操作。"
        "【反例】系统配置/AI 配置用 settings_manage；查会话用 session_manage。"
        "【反例】删除通知 / 发送通知**不在本工具能力内** —— "
        "如实告知用户，并引导其到商户后台「通知中心」页处理。"
        "【标注】WRITE — list / unread_count 只读免确认；"
        "mark_read / read_all 属变更，必须先确认再执行"
    )
    # 角色层（**唯一**门禁）：四个自助端点在 admin-api 里没有权限码（自助语义）⇒ 工具不持码。
    # 必须**显式**声明（不吃 `BaseTool` 默认值 —— 默认值含 C 端角色 `customer`/`agent`、
    # 幽灵角色 `tenant_admin` 与 `guest`，属横向越权/跨服务口径断裂，issue #5246 判据 6）。
    # 🔴 取值口径 = **零回归**（#5302 的最小行为变化）：改前本工具的权限码层实际只放行
    # admin（`*` 通配）+ operator（唯一持 `employee:list` 的商户岗位）⇒ 角色层按**同一集合**
    # 声明，读面既不放宽也不收窄。后台「通知中心」页面对全岗位可见，但**工具面**要不要跟着
    # 放开到其它岗位属产品裁定（会改变授权面），不在本单范围内 —— 要放开须同批改本声明
    # 与 `backend/ai-agent-service/tests/test_notification_manage_change_actions.py` 的判据。
    # 判据：`tests/test_tool_permission_codes.py` 要求「无码的 B 端工具必须被显式登记
    # （ROLE_GATED_B_SIDE_TOOLS）且保留角色白名单」。
    allowed_roles = ["admin", "operator"]

    #: 🔴 **变更能力已接回**（#7040 按 2026-10-16 裁定）：`read_only=False` 把 `mark_read` /
    #: `read_all` 交回**既有确认门禁**（`app/graph/skills/base_skill.py` 的 `_requires_confirmation`
    #: 拦未确认的非只读 action；补救路径 = 本 skill 绑定的 `interact(component=confirm)` 确认卡）。
    #: 这不是新机制：与 `product_update` / `scheduled_task_manage` 同一形态。
    read_only = False
    #: 变更类 action 的确认门禁声明（与 `scheduled_task_manage` 同口径）。
    #: 标记已读可逆、不丢数据，但能**一次改全部**且改的是用户可见状态 ⇒ 按「不绕过审核门禁」
    #: 的措辞显式声明要确认。
    requires_confirmation = True
    destructive = False  # 标记已读**不是**破坏性动作（可逆、不丢数据，故不标 destructive）
    #: 幂等（issue #7040）：标记已读是**状态置位** —— 同一通知标记两次结果一致；
    #: `read_all` 同样收敛（第二次调用时已无未读 ⇒ 无副作用）。⇒ 重放安全，允许自动重试。
    #: 判据：`backend/ai-agent-service/tests/test_tool_idempotent_retry_guard.py`。
    idempotent = True
    read_only_actions = READ_ONLY_ACTIONS  # 只读 action 免确认拦截

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：list（查询列表）/ unread_count（未读数）—— 只读；"
                    "mark_read（标记单条已读）/ read_all（全部标记已读）—— 变更，需确认"
                ),
                "enum": ["list", "unread_count", "mark_read", "read_all"],
            },
            "notification_id": {
                "type": "string",
                "description": "通知 ID（mark_read 时必填；可从 list 结果里取）",
            },
            "channel": {
                "type": "string",
                "description": "通知渠道筛选：system（站内）/ email（邮件）/ sms（短信）/ wechat（微信）",
                "enum": ["system", "email", "sms", "wechat"],
            },
            "status": {
                "type": "string",
                "description": "通知状态筛选：unread（未读）/ read（已读）",
                "enum": ["unread", "read"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        notification_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行通知操作（查询 / 变更）

        ⚠️ 形参**不叫** `read_all`：那会遮蔽同名 action 名（Python 里形参与局部名同域）。
        action 名本身保留为 `read_all`（用例 ST-005 与 admin-api 端点语义都按它对齐）。
        """
        # 权限检查（角色层：本工具没有目录权限码）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行通知管理操作",
                suggestion="请联系管理员获取执行通知管理操作权限",
            )

        # 参数校验（未接线的 action：删除 / 发送通知在这里即被拒 —— 不是"描述里没写"）
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion=(
                    "本工具提供 list / unread_count（只读）与 mark_read / read_all（变更）。"
                    "删除通知 / 发送通知不在本工具能力内 —— "
                    "请如实告知用户，并引导其到商户后台「通知中心」页处理"
                ),
            )

        try:
            if action == "list":
                return await self._list_notifications(context, page, size, status, channel)
            elif action == "unread_count":
                return await self._unread_count(context)
            elif action == "mark_read":
                return await self._mark_read(context, notification_id)
            elif action == "read_all":
                return await self._read_all(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"Notification manage error: action={action}, error={e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="通知操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    # ── 只读（两个 action 免确认拦截）─────────────────────────────────────────

    async def _list_notifications(
        self,
        context: ToolContext,
        page: int,
        size: int,
        status: Optional[str],
        channel: Optional[str],
    ) -> ToolResult:
        """查询通知列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10
        params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            if status not in VALID_STATUSES:
                return ToolResult(
                    success=False,
                    error=f"无效的通知状态: {status}",
                    message=f"不支持的状态筛选，可选：{', '.join(sorted(VALID_STATUSES))}",
                    suggestion="请改用合法状态筛选（见错误提示中的可选值）后重试，不要自行传其它状态",
                )
            # 映射为 admin-api 实际状态值（unread → sent）
            params["status"] = STATUS_TO_API.get(status, status)
        if channel:
            if channel not in VALID_CHANNELS:
                return ToolResult(
                    success=False,
                    error=f"无效的通知渠道: {channel}",
                    message=f"不支持的通知渠道，可选：{', '.join(sorted(VALID_CHANNELS))}",
                    suggestion="请改用合法通知渠道（见错误提示中的可选值）后重试，不要自行传其它渠道",
                )
            # 映射为 admin-api 实际渠道值（system → internal）
            params["channel"] = CHANNEL_TO_API.get(channel, channel)

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/notifications",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"查询通知列表失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改为不带筛选条件查询，或请用户联系管理员核对通知数据",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"Notifications list: page={page}, size={size}, total={total}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 条通知",
        )

    async def _unread_count(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """获取未读通知数量"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/notifications/unread-count",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取未读数失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改用 list 操作查询未读通知条数，或请用户稍后再看",
            )

        data = response.get("data", {})
        count = data.get("count", 0)

        logger.info(
            f"Notifications unread count: count={count}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"unread_count": count},
            message=f"您有 {count} 条未读通知",
        )

    # ── 变更（#7040 按 2026-10-16 裁定接回；两个端点均已在 admin-api 逐一核实存在）──────

    async def _mark_read(
        self,
        context: ToolContext,
        notification_id: Optional[str],
    ) -> ToolResult:
        """标记**单条**通知已读（`PUT /api/admin/notifications/{id}/read`）

        收件人由 admin-api 侧 `SecurityContext` 决定（自助语义）⇒ 只能改**自己**的通知。
        """
        if not notification_id:
            return ToolResult(
                success=False,
                error="missing_notification_id",
                message="标记已读需要提供通知 ID",
                suggestion="请先调用 action=list 取到该条通知的 id，再带 notification_id 重试",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/notifications/{notification_id}/read",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "标记失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"标记通知已读失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请在后台「通知中心」页手动标记已读",
            )

        logger.info(
            f"Notification marked read: id={notification_id}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"notification_id": notification_id, "status": "read"},
            message="已标记该条通知为已读",
        )

    async def _read_all(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """把**当前用户**全部未读通知标记已读（`PUT /api/admin/notifications/read-all`）"""
        client = get_admin_api_client()
        response = await client.put(
            "/api/admin/notifications/read-all",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "标记失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"全部标记已读失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请在后台「通知中心」页手动标记已读",
            )

        logger.info(f"Notifications marked all read: tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"status": "read", "scope": "all_unread"},
            message="已把您的未读通知全部标记为已读",
        )
