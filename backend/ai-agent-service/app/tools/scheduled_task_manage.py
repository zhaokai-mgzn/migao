"""定时任务（用户「预约」）Tool —— 让「到点提醒」这件事可被委托给米宝（issue #6486 包 2）

## 一句话

商家说「3 天后提醒我跟进张先生」⇒ 米宝建一条待办；到点由 admin-api 的扫描腿投递成**站内通知**。

## A 档可逆写（用户 2026-10-07 裁定；留痕 = `docs/wiki/agent-write-boundary.md` §五 + issue #6486）

本工具是 `product_update` / `sku_update` / `product_batch_update` 之后**第四条**进 A 档白名单的写能力，
逐条对齐 A 档口径：

| A 档要求 | 本工具 |
|---|---|
| 可逆 | ✅ `cancel` 撤销 |
| 幂等 | ✅ `dedup_key`（服务端唯一索引） |
| 非对外承诺 | ✅ 只提醒**自己**，不发给客户 |
| 不绕审核门禁 | ✅ 不涉钱、不涉状态跃迁 |
| 带 `requires_confirmation` | ✅ 见类属性 |

## 🔴 只读护栏（L1 提醒型的硬边界，别在本工具里开新写面）

到点投递**只写站内通知**；agent **不在无人监督下执行业务写**（下单 / 改价 / 发货 / 退款）。
理由是结构性的：定时执行发生在**用户不在场**时，而既有写面护栏依赖「用户点确认卡」
（卡值口径，issue #5317）—— 无人监督的定时执行**取不到**那个确认。

## 自助语义（无权限码）

三个端点（`/api/admin/agent/scheduled-tasks`）在 admin-api 里都**没有** `@RequirePermission`
（自助：收件人 = 建单者自己，取自认证上下文，body 伪造不了）⇒ 本工具**不持权限码**、回到
**角色层**（与 `notification_manage` 同款，理由见 `tests/test_tool_permission_codes.py` 的
`ROLE_GATED_B_SIDE_TOOLS`）。`allowed_roles` 必须**显式**声明（不吃 `BaseTool` 默认值）。
"""

from typing import Any, Dict, Optional

from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

#: 本工具 action 面的**唯一真值**（判据 `tests/test_scheduled_task_manage.py` 钉住）
VALID_ACTIONS = {"create", "list", "cancel"}

#: 只读 action（免确认拦截）
READ_ONLY_ACTIONS = {"list"}

# 🔴 端点路径**必须写成字面量**（不抽常量）：`tests/test_tool_payload_backend_contract.py` 的
# 静态门禁要能把每个带 payload 的调用点**归属到具体端点**；路径走常量 ⇒ 它读不出来 ⇒ 报
# 「会静默脱离本门禁射程」。端点 = admin-api 的 `AgentScheduledTaskController`
# （`/api/admin/agent/scheduled-tasks`，三个方法 POST / GET / DELETE {id}）。


class ScheduledTaskManageTool(BaseTool):
    """定时任务（用户「预约」）—— 建 / 列 / 取消「到点提醒」待办。"""

    name = "scheduled_task_manage"
    description = (
        "【触发】用户说'提醒我''到时候告诉我''过几天跟进''别忘了''帮我记着''预约个提醒'时调用。"
        "【参数】action 必填：create（建一条待办）/ list（查已有待办）/ cancel（取消待办）。"
        "create 必填 fire_at + criterion + action_label + action_url，另需 task_type。"
        "【fire_at 口径】必须是**带时区**的 ISO8601（如 2026-10-10T09:00:00+08:00）—— "
        "从当前时间（本机时区 Asia/Shanghai）推算，**不要**只给日期。"
        "【三件套不可省】criterion（为什么提醒 —— 用**商家自己的话**）/ action_label（去哪办）/ "
        "action_url（后台页地址，如 /customers?keyword=张先生）—— 服务端对三者 fail-closed，缺一即拒。"
        "【反例】'发货了通知我'这类**业务节点**提醒属系统派生（已有每日简报与主动规则），"
        "本工具只承接**用户委托**的那类；'提醒客户'不在能力内（本工具只提醒**你自己**）。"
        "【标注】WRITE|IDEMPOTENT — 写操作；用户确认后立即执行，禁止只查询/展示就停。"
        "【护栏】到点只发**站内通知**，**不会**替你下单/改价/发货 —— 到点后要动手，回会话里来办。"
    )
    # 角色层（**唯一**门禁）：三个端点都没有权限码（自助语义）⇒ 工具不持码。
    # 必须**显式**声明（不吃 BaseTool 默认值 —— 默认值含 C 端角色 customer/agent、
    # 幽灵角色 tenant_admin 与 guest，属横向越权/跨服务口径断裂，issue #5246 判据 6）。
    # 取值口径 = 与 `notification_manage` 同集（同为「自助」形态的 B 端工具）。
    allowed_roles = ["admin", "operator"]

    read_only = False
    read_only_actions = READ_ONLY_ACTIONS  # list 免确认拦截
    requires_confirmation = True           # A 档要求②：写操作要有确认门禁
    destructive = False
    idempotent = True                      # A 档要求：幂等 ⇒ 重放安全（服务端 dedup_key）

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：create（建待办）/ list（查待办）/ cancel（取消待办）",
                "enum": ["create", "list", "cancel"],
            },
            "fire_at": {
                "type": "string",
                "description": "触发时刻，**带时区**的 ISO8601（如 2026-10-10T09:00:00+08:00）。create 必填",
            },
            "task_type": {
                "type": "string",
                "description": "任务类型（可配置）：如 follow_up（跟进）/ payment（催款）/ custom（其它）",
            },
            "criterion": {
                "type": "string",
                "description": "为什么提醒 —— 用商家自己的话（如「你说过：等王总回复后再跟进张先生」）。create 必填",
            },
            "action_label": {
                "type": "string",
                "description": "到点后去哪办（按钮文案，如「去跟进张先生」）。create 必填",
            },
            "action_url": {
                "type": "string",
                "description": "处置入口地址（后台页路径，如 /customers?keyword=张先生）。create 必填",
            },
            "impact": {
                "type": "object",
                "description": "影响面（可选，如 {\"count\": 1}）",
            },
            "task_id": {
                "type": "string",
                "description": "待办 ID。cancel 必填",
            },
            "status": {
                "type": "string",
                "description": "list 时的状态筛选（缺省查全部）",
                "enum": ["pending", "fired", "cancelled", "failed", "dismissed"],
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        fire_at: Optional[str] = None,
        task_type: Optional[str] = None,
        criterion: Optional[str] = None,
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
        impact: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行定时任务操作。"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行定时任务操作",
                suggestion="请联系管理员获取执行定时任务操作权限",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请改用 create / list / cancel 之一后重试",
            )

        try:
            if action == "create":
                return await self._create(
                    context, fire_at, task_type, criterion, action_label, action_url, impact
                )
            if action == "list":
                return await self._list(context, status)
            return await self._cancel(context, task_id)
        except Exception as e:
            logger.error(
                f"ScheduledTask manage error: action={action}, error={e}", exc_info=True
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="定时任务操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    # ==================== action 实现 ====================

    async def _create(
        self,
        context: ToolContext,
        fire_at: Optional[str],
        task_type: Optional[str],
        criterion: Optional[str],
        action_label: Optional[str],
        action_url: Optional[str],
        impact: Optional[Dict[str, Any]],
    ) -> ToolResult:
        """建一条待办（三件套 fail-closed —— 本地先拦一道，服务端还有一道）。"""
        missing = [
            label
            for label, value in (
                ("fire_at（触发时刻）", fire_at),
                ("task_type（任务类型）", task_type),
                ("criterion（为什么提醒）", criterion),
                ("action_label（处置入口文案）", action_label),
                ("action_url（处置入口地址）", action_url),
            )
            if not (value or "").strip()
        ]
        if missing:
            return ToolResult(
                success=False,
                error="missing_arguments",
                message=f"缺必填参数：{'、'.join(missing)}",
                suggestion=(
                    "三件套（criterion / action_label / action_url）与 fire_at 一个都不能省 —— "
                    "没有处置入口的提醒等于制造焦虑，服务端也会拒。"
                    "请补齐后再调；fire_at 要带时区的 ISO8601。"
                ),
            )

        json_data: Dict[str, Any] = {
            "taskType": task_type,
            "fireAt": fire_at,
            "criterion": criterion,
            "actionLabel": action_label,
            "actionUrl": action_url,
        }
        if impact:
            json_data["impact"] = impact

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/agent/scheduled-tasks",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            return admin_api_failure(
                response,
                error="create_failed",
                message=response.get("message") or "创建提醒失败",
                suggestion="请核对触发时刻格式（带时区的 ISO8601）与三件套后重试",
            )

        data = response.get("data") or {}
        return ToolResult(
            success=True,
            data=data,
            message=(
                f"已记下：{fire_at} 提醒你「{action_label}」。"
                "到点会发到你的通知中心（只提醒，不会替你做任何写操作）。"
            ),
        )

    async def _list(self, context: ToolContext, status: Optional[str]) -> ToolResult:
        """列本租户待办（自助：只看得到自己的）。"""
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/agent/scheduled-tasks",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(
                response,
                error="list_failed",
                message=response.get("message") or "查询提醒失败",
                suggestion="请稍后重试",
            )
        tasks = response.get("data") or []
        if not tasks:
            return ToolResult(
                success=True,
                data={"tasks": [], "count": 0},
                message="当前没有待提醒的事项。",
            )
        return ToolResult(
            success=True,
            data={"tasks": tasks, "count": len(tasks)},
            message=f"共 {len(tasks)} 条待提醒事项。",
        )

    async def _cancel(self, context: ToolContext, task_id: Optional[str]) -> ToolResult:
        """取消一条待办（只对 pending 有效；已投递的不可撤回）。"""
        if not (task_id or "").strip():
            return ToolResult(
                success=False,
                error="missing_arguments",
                message="缺必填参数：task_id",
                suggestion="先用 action=list 查到待办 ID，再取消。",
            )
        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/agent/scheduled-tasks/{task_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(
                response,
                error="cancel_failed",
                message=response.get("message") or "取消失败",
                suggestion="请稍后重试",
            )
        cancelled = (response.get("data") or {}).get("cancelled")
        if not cancelled:
            return ToolResult(
                success=True,
                data={"task_id": task_id, "cancelled": False},
                message="这条提醒已发出或已取消，无需再处理。",
            )
        return ToolResult(
            success=True,
            data={"task_id": task_id, "cancelled": True},
            message="已取消该提醒。",
        )
