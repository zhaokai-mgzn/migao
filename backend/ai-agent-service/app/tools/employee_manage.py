"""员工账号管理 Tool —— 查询 + **创建/变更**（issue #7050 接回写面）

## 能力边界（用户 2026-10-16「能力边界 终版」，判据见 `tests/unit_ci_workflows/test_mibao_b_end_readonly.py`）

| 面 | 本工具 |
|---|---|
| 查询（list / detail） | ✅ 只读，免确认拦截 |
| 创建员工账号 / 变更（改姓名、手机号、头像、岗位） | ✅ 写，走既有确认门禁（`requires_confirmation`） |
| 删除 / 停用（离职） | ❌ 不可逆 ⇒ 不在能力内，引导后台 |
| 重置密码 | ❌ 登录凭据面（安全边界）⇒ 本单不接线（issue #7050 逐条判） |

## 为什么接回（不是"顺手加功能"）

`#5247` 的 B 端只读化把写 action 全部删除，而用户 2026-10-16 的终版边界逐字要求
「**创建非单据对象 ✅ 必须支持**」⇒ 员工账号是其中第一个域。接回的形态**照抄**仓内既有写工具
（`order_manage` / `scheduled_task_manage` / `notification_manage`）：

1. **权限**走既有声明（`required_permissions` 粗筛 + action 级细粒度复检，码取 admin-api
   `AdminUserController` 各端点的 `@RequirePermission`），**不自己判角色**；
2. **确认**走 `BaseTool` 的既有门禁（`read_only=False` + `requires_confirmation=True` +
   `read_only_actions` 豁免只读 action）—— 由 `app/graph/skills/base_skill.py::_requires_confirmation`
   执行，工具**不自建**第二套确认；
3. **失败说人话 + 该做什么**（`migao-dev-flow` §31 P4：只陈述事实与该做什么，不责备、不催促）。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import (
    admin_api_failure,
    BaseTool,
    ToolContext,
    ToolResult,
    permission_denied,
)
from app.utils.http_client import get_admin_api_client


#: 本工具 action 面的**唯一真值**（判据 `tests/test_employee_manage_write_actions.py` 钉住）
VALID_ACTIONS = {"list", "detail", "create", "update"}

#: 只读 action —— 免确认拦截（`base_skill._requires_confirmation` 直接读这个字段）。
#: 契约：必须是 `VALID_ACTIONS` 的子集（见 `app/tools/base.py` 的同名字段注释）。
READ_ONLY_ACTIONS = frozenset({"list", "detail"})

#: 写 action（走确认门禁）。删除 / 停用 / 重置密码**有意不在此列**。
WRITE_ACTIONS = frozenset(VALID_ACTIONS - READ_ONLY_ACTIONS)


class EmployeeManageTool(BaseTool):
    """员工账号管理 Tool（查询 + 创建/变更）

    使用场景：
    - 查询员工列表（按关键词、状态、角色筛选）
    - 查看员工详细信息
    - 创建新员工账号（用户确认后执行）
    - 变更员工信息（姓名 / 手机号 / 头像 / 岗位）

    不在能力内（如实说明 + 引导后台，不承诺代办）：
    - 删除员工、停用/启用（离职）、重置密码
    """

    name = "employee_manage"
    description = (
        "【触发】用户说'有哪些员工''谁在岗''查下这个同事''开个客服账号''新来的XX加进来''"
        "把他的岗位改成仓管''改一下手机号/姓名'时调用。"
        "【参数】action 必填：list（列表，可按 keyword/status/role 过滤 + 分页）/ detail（需 user_id）"
        "为只读；create（建账号：必填 name + phone + password，另需 role 或 role_ids 指定岗位）/ "
        "update（改账号：必填 user_id，另需至少一个可改字段 name/phone/avatar/role/role_ids）为写操作。"
        "【确认】create/update 属写操作：调 interact(component=\"confirm\") 发确认卡，"
        "**卡面必须逐字带出可核对的标识**：create = 姓名 + 手机号（可打码后四位）+ 岗位；"
        "update = 谁（姓名或 user_id）+ 每个要改的字段「改前 → 改后」。用户点卡后才调用；"
        "未确认的调用会被门禁拦下。"
        "⚠️ 卡面值必须与你随后传给本工具的参数**同一份**（服务端不会重算姓名/手机号）——"
        "把没在卡上出现过的姓名/手机号/岗位传进来 = 建出一个用户没看清的账号。"
        "【反例】删除员工、停用/离职、重置密码**不在能力内**——如实说明并引导到后台"
        "「组织管理 → 员工管理」页操作。管理岗位权限用 role_manage；查客户用 customer_manage。"
        "【标注】WRITE — 创建/变更需确认；查询类 action 免确认"
        "【不要用于】岗位/角色与权限清单（用 role_manage）；计件工资（用 piecework_query）"
    )
    # 权限码（admin-api 目录）：`AdminUserController` 类级 `@RequirePermission("employee:list")`，
    # 写端点（`POST /api/admin/users` 与 `PUT /api/admin/users/{id}`）为 `employee:create`。
    # 粗筛取两码并集（任一命中即可进入工具），**action 级复检**在 execute 内按端点注解收严
    # （防止仅持读码的员工借黄金策建号/改号）。不用 allowed_roles —— 手写角色白名单
    # 会与目录漂移（#4106 F4）。
    required_permissions = ["employee:list", "employee:create"]
    read_only = False
    read_only_actions = READ_ONLY_ACTIONS  # list/detail 免确认拦截
    requires_confirmation = True           # 写操作走既有确认门禁（#7050；不自建第二套）
    destructive = False                    # 不含删除/停用（那两类不在能力内）
    idempotent = False                     # create 非幂等：重放会建出第二个账号

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：list（员工列表）/ detail（员工详情）—— 只读；"
                    "create（创建员工账号）/ update（变更员工信息）—— 写，需确认"
                ),
                "enum": ["list", "detail", "create", "update"],
            },
            "user_id": {
                "type": "string",
                "description": "员工用户 ID（detail/update 时必填；先用 list 查到真实 ID）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（list 时可选）",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10（list 时可选）",
                "default": 10,
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词，支持姓名、手机号（list 时可选）",
            },
            "status": {
                "type": "string",
                "description": "状态筛选：active/disabled（list 时可选）",
                "enum": ["active", "disabled"],
            },
            "role": {
                "type": "string",
                "description": (
                    "岗位/角色代码：list 时作筛选；create 时用于指定岗位（与 role_ids 至少给一个）；"
                    "update 时用于改岗位"
                ),
            },
            "role_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "角色 ID 列表（role_manage 的 list 里返回的角色主键 id）："
                    "create/update 时使用，与 role 至少给一个"
                ),
            },
            "name": {
                "type": "string",
                "description": "员工姓名（create 必填；update 时可改）",
            },
            "phone": {
                "type": "string",
                "description": "手机号（create 必填，同时作为登录手机号；update 时可改，需租户内未被占用）",
            },
            "password": {
                "type": "string",
                "description": (
                    "初始密码（create 必填）—— 用户未提供时可按公司规则生成并在回复中告知，但必须传值。"
                    "update 不承接改密（改密走后台）"
                ),
            },
            "avatar": {
                "type": "string",
                "description": "头像 URL（update 时可选）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        user_id: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        password: Optional[str] = None,
        name: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        avatar: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行员工管理操作"""
        # 权限检查（粗粒度：角色 + required_permissions 任一命中）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行员工管理操作",
                suggestion="请联系管理员获取执行员工管理操作权限",
            )

        # 细粒度权限（与 `AdminUserController` 的 `@RequirePermission` 逐端点对齐）：
        # 查询类 action 要 employee:list，写 action（create/update）要 employee:create。
        # 防的是「只持读码的员工」借黄金策建号/改号（#4147 G2 的同款两段式）。
        required = "employee:list" if action in self.read_only_actions else "employee:create"
        if "*" not in (context.permissions or []) and required not in (context.permissions or []):
            # 门禁**之外**的动作级拒绝 ⇒ 必须自己走共享构造点带码（issue #4147 G2；
            # 被 L0 静态锁 tests/test_tool_denial_semantics.py 覆盖）。
            return permission_denied(
                message=f"您没有权限执行该员工操作（缺少权限：{required}）",
                suggestion=(
                    "请联系管理员在「员工管理」中为您开通相应权限"
                    f"（{'查询' if required == 'employee:list' else '管理'}员工）"
                ),
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=(
                    f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}。"
                    "删除员工、停用/启用、重置密码不在本工具能力内，需到后台「组织管理 → 员工管理」操作"
                ),
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_users(context, page, size, keyword, status, role)
            elif action == "detail":
                return await self._detail_user(context, user_id)
            elif action == "create":
                return await self._create_user(context, phone, password, name, role, role_ids)
            elif action == "update":
                return await self._update_user(context, user_id, name, phone, avatar, role, role_ids)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[employee-manage] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="员工管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_users(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
        status: Optional[str],
        role: Optional[str],
    ) -> ToolResult:
        """查询员工列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        if status:
            params["status"] = status
        if role:
            params["role"] = role

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/users",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="员工列表查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        users = []
        for record in records:
            users.append({
                "id": record.get("id"),
                "name": record.get("name"),
                "phone": record.get("phone"),
                "status": record.get("status"),
                "roles": record.get("roles", []),
                "created_at": record.get("createdAt"),
            })

        logger.info(f"[employee-manage] Listed {len(users)} users, total={total} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={
                "users": users,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"找到 {total} 个员工" if total > 0 else "未找到符合条件的员工",
        )

    async def _detail_user(
        self,
        context: ToolContext,
        user_id: Optional[str],
    ) -> ToolResult:
        """查询员工详情"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="查询员工详情时必须提供员工 ID（user_id）",
                suggestion="缺少 user_id，请先用 employee_manage 的 list 操作查到该员工后再重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/users/{user_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="员工详情查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", {})
        logger.info(f"[employee-manage] Detail user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"员工【{data.get('name', '')}】的详细信息",
        )

    async def _create_user(
        self,
        context: ToolContext,
        phone: Optional[str],
        password: Optional[str],
        name: Optional[str],
        role: Optional[str],
        role_ids: Optional[List[str]],
    ) -> ToolResult:
        """创建员工账号（端点 `POST /api/admin/users`，权限码 `employee:create`）

        本地校验**逐字段具名**（§31 P4：说清缺哪个字段、该做什么），不把服务端 422 直接甩给模型
        —— 模型拿到具名错误才能追问正确的那一件事。
        """
        if not name:
            return ToolResult(
                success=False,
                error="缺少姓名",
                message="创建员工缺少姓名（name）",
                suggestion="请向用户确认员工姓名后，用 name 字段重试",
            )
        if not phone:
            return ToolResult(
                success=False,
                error="缺少手机号",
                message="创建员工缺少手机号（phone）",
                suggestion="请向用户确认员工手机号（同时是登录账号）后，用 phone 字段重试",
            )
        if not password:
            return ToolResult(
                success=False,
                error="缺少初始密码",
                message="创建员工缺少初始密码（password）",
                suggestion=(
                    "请向用户要一个初始密码（或按公司规则生成一个并在回复中告知），"
                    "用 password 字段重试"
                ),
            )
        if not role and not role_ids:
            return ToolResult(
                success=False,
                error="缺少岗位/角色",
                message="创建员工需要指定岗位（role_ids 或 role）—— 服务端不设默认岗位",
                suggestion=(
                    "先用 role_manage 的 list 查到岗位（拿到角色 id 与 code），"
                    "把 role_ids（角色 id 列表）或 role（角色代码）一起传给 create"
                ),
            )

        json_data: Dict[str, Any] = {
            "name": name,
            "phone": phone,
            "password": password,
        }
        if role_ids:
            json_data["roleIds"] = role_ids
        if role:
            json_data["role"] = role

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/users",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"创建员工失败：{error_msg}",
                suggestion=(
                    "请先用 employee_manage 的 list 确认该手机号未被其它员工占用；"
                    "若提示岗位无效，用 role_manage 的 list 核对岗位/角色代码后重试"
                ),
            )

        data = response.get("data", {})
        logger.info(f"[employee-manage] Created user: name={name} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"员工【{name}】已创建，登录手机号 {phone}",
        )

    async def _update_user(
        self,
        context: ToolContext,
        user_id: Optional[str],
        name: Optional[str],
        phone: Optional[str],
        avatar: Optional[str],
        role: Optional[str],
        role_ids: Optional[List[str]],
    ) -> ToolResult:
        """变更员工信息（端点 `PUT /api/admin/users/{id}`，权限码 `employee:create`）"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="变更员工信息缺少员工 ID（user_id）",
                suggestion="请先用 employee_manage 的 list 查到该员工的真实 ID，再用 user_id 重试",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if phone:
            json_data["phone"] = phone
        if avatar:
            json_data["avatar"] = avatar
        if role_ids:
            json_data["roleIds"] = role_ids
        elif role:
            json_data["role"] = role

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少变更内容",
                message="变更员工信息需要至少一个字段（name / phone / avatar / role / role_ids）",
                suggestion="请向用户确认要改哪一项（姓名/手机号/头像/岗位）后，带上对应字段重试",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/users/{user_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"变更员工信息失败：{error_msg}",
                suggestion=(
                    "请先用 employee_manage 的 detail 读取该员工当前信息，"
                    "核对手机号/岗位是否与他人冲突后再重试"
                ),
            )

        logger.info(f"[employee-manage] Updated user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"user_id": user_id},
            message="员工信息已变更",
        )
