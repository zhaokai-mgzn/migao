"""
AI 智能客服系统 - 客户管理 Tool

管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。
"""

from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "list_tags"}

# 客户档案可写字段（单一事实源 = admin-api CustomerProfile 列 ∩ CustomerService.updateCustomer
# 的非空拷贝白名单）。写路径只允许下发这些 key，其余一律显式报错——禁止原样透传后由 admin-api
# 静默丢弃（Spring 默认 FAIL_ON_UNKNOWN_PROPERTIES=false → HTTP 200 但数据不落库 = 假成功，issue #3551）。
# 跨端字段契约由 tests/test_tool_field_name_contract.py 强制：既解析 CustomerProfile.java 的列，
# 也解析 CustomerService.updateCustomer 的非空拷贝白名单 —— 即上面「交集」这条口径现在是**被判据强制的**
# （issue #4115 之前只校验前者：4 个新列两边都「对得上」，却照样静默丢弃 + 谎报成功）。
WRITABLE_FIELDS = frozenset({
    "wechatNickname", "phone", "gender",
    "regionProvince", "regionCity", "regionDistrict",
    "vipLevel", "customerStatus", "agentNotes", "tags", "customFields",
    # 工艺画像与常用物流（issue #3984，V47，M2-D）
    "craftMode", "craftProfile", "defaultLogisticsType", "defaultLogisticsCompany",
    # 默认收货信息（issue #4419，V70）：收货人姓名/电话/详细地址。
    # 与 admin-api CustomerService.updateCustomer 的非空拷贝白名单**必须同集合**
    # （跨端契约由 tests/test_tool_field_name_contract.py 强制）。
    "defaultReceiverName", "defaultReceiverPhone", "defaultReceiverAddress",
})

# 姓名别名 → canonical 列名：客户实体无 name/nickname/realName 列，姓名存 wechatNickname
# （读路径 _list_customers/_detail_customer 已按同序回退，写路径必须对齐，否则静默丢弃 = 谎报成功）。
NAME_ALIAS_TO_CANONICAL = {"name": "wechatNickname", "nickname": "wechatNickname", "realName": "wechatNickname"}

# craftMode 允许值（单一事实源 = V47 迁移的列注释 / CustomerProfile#craftMode javadoc；
# admin-api CustomerService.requireValidCraftMode 是同口径的服务端兜底，非法值 400 + suggestion）。
# 本层提前拦下：省一轮注定失败的写请求，并给出比「更新失败」更可行动的提示（issue #4115）。
CRAFT_MODES = frozenset({"standard", "economy", "self_quoted"})


def normalize_update_data(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """把 update 的 data 归一化为 CustomerProfile 真实列名 payload。

    返回 (payload, rejected)；rejected 非空时调用方必须显式报错且**不得发起写请求**
    （既不静默忽略、也不部分写入——两者都会让用户看到假成功）。
    """
    payload: Dict[str, Any] = {}
    rejected: List[str] = []
    for key, value in data.items():
        canonical = NAME_ALIAS_TO_CANONICAL.get(key, key)
        if canonical not in WRITABLE_FIELDS:
            rejected.append(key)
            continue
        # 显式 wechatNickname 优先于姓名别名（两者同时出现时以 canonical 为准）
        if canonical == "wechatNickname" and key != "wechatNickname" and "wechatNickname" in payload:
            continue
        payload[canonical] = value
    return payload, sorted(rejected)


class CustomerManageTool(BaseTool):
    """客户管理 Tool

    管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。

    使用场景：
    - 查询客户列表（按关键词、来源渠道、VIP等级筛选）
    - 查看客户详细档案
    - 更新客户信息
    - 给客户打标签或移除标签
    - 管理标签库（创建、更新、删除标签）
    """

    name = "customer_manage"
    description = (
        "【触发】用户问'客户''顾客''VIP''客户档案''客户标签''给XX打标签''查XX电话'时调用。"
        "【参数】action 必填：**只有 list / detail / list_tags 三个只读 action**（B 端已只读化，issue #5247）。"
        "list 可按 keyword(名称/手机号) 搜索；detail 需 customer_id（32 位 UUID，先 list 查出真实 UUID，"
        "禁止传手机号）；list_tags 列出全店客户标签。"
        "【反例】查客户的历史订单用 order_query(keyword=XX)，不要用本工具；"
        "员工账号用 employee_manage，角色权限用 role_manage。"
        "【反例】改客户资料/打标签/删标签**不在本工具能力内**——引导用户到后台「客户列表」页面自行操作。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：issue #5246 起 `CustomerController` 的读面 `customer:view`、
    # 写面（改/删客户、标签增删）`customer:create`（此前整类挂在读码上，只读持有者能删客户）。
    required_permissions = ["customer:view"]  # B 端只读化（#5247）：写码 customer:create 已随写 action 一并移除

    read_only = True
    read_only_actions = {"list", "detail", "list_tags"}  # 只读 action 免确认拦截
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（客户列表）/ detail（客户详情）/ list_tags（标签列表）—— 均为只读",
                "enum": ["list", "detail", "list_tags"],
            },
            "customer_id": {
                "type": "string",
                "description": "客户 32 位 UUID。detail/update/add_tag/remove_tag 时必填。必须先通过 customer_manage(list) 查出真实 UUID，禁止传手机号或姓名",
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
                "description": "搜索关键词，支持客户名称、手机号（list 时可选）",
            },
            "source_channel": {
                "type": "string",
                "description": "来源渠道筛选（list 时可选）",
            },
            "vip_level": {
                "type": "string",
                "description": "VIP等级筛选（list 时可选）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        customer_id: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        keyword: Optional[str] = None,
        source_channel: Optional[str] = None,
        vip_level: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        tag_id: Optional[str] = None,
        name: Optional[str] = None,
        color: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行客户管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行客户管理操作",
                suggestion="请联系管理员获取执行客户管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_customers(context, page, size, keyword, source_channel, vip_level)
            elif action == "detail":
                return await self._detail_customer(context, customer_id)
            elif action == "list_tags":
                return await self._list_tags(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[customer-manage] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="客户管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_customers(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
        source_channel: Optional[str],
        vip_level: Optional[str],
    ) -> ToolResult:
        """查询客户列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        if source_channel:
            params["sourceChannel"] = source_channel
        if vip_level:
            params["vipLevel"] = vip_level

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/customers",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="客户列表查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        customers = []
        for record in records:
            raw_phone = record.get("phone") or ""
            # 脱敏：列表接口对手机号中间4位打码，防止批量泄露
            masked_phone = (raw_phone[:3] + "****" + raw_phone[7:]) if len(raw_phone) >= 11 else raw_phone
            customers.append({
                "id": record.get("id"),
                # 生产回归修复：admin-api 客户数据无 name 字段（存 wechatNickname/nickname），
                # 旧实现只读 name → 米宝显示"姓名字段都为空"。逐级回退。
                "name": record.get("name")
                        or record.get("wechatNickname")
                        or record.get("nickname")
                        or record.get("realName")
                        or "",
                "phone": masked_phone,
                "source_channel": record.get("sourceChannel"),
                "vip_level": record.get("vipLevel"),
                "tags": record.get("tags", []),
                "created_at": record.get("createdAt"),
            })

        logger.info(f"[customer-manage] Listed {len(customers)} customers, total={total} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={
                "customers": customers,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"找到 {total} 个客户" if total > 0 else "未找到符合条件的客户",
        )

    async def _detail_customer(
        self,
        context: ToolContext,
        customer_id: Optional[str],
    ) -> ToolResult:
        """查询客户详情"""
        if not customer_id:
            return ToolResult(
                success=False,
                error="缺少客户 ID",
                message="查询客户详情时必须提供客户 ID（customer_id）",
                suggestion="缺少 customer_id，请先用 customer_manage 的 list 操作按姓名或手机号搜到客户后重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/customers/{customer_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="客户详情查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", {})
        logger.info(f"[customer-manage] Detail customer_id={customer_id} | tenant={context.tenant_id}")

        # 姓名展示回退（生产回归：admin-api 详情同样无 name 字段）
        display_name = (data.get("name") or data.get("wechatNickname")
                        or data.get("nickname") or data.get("realName") or "")
        return ToolResult(
            success=True,
            data=data,
            message=f"客户【{display_name}】的详细信息",
        )
    async def _list_tags(self, context: ToolContext) -> ToolResult:
        """查询所有客户标签"""

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/customer-tags",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="标签列表查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", [])
        logger.info(f"[customer-manage] Listed {len(data)} tags | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"tags": data, "count": len(data)},
            message=f"共 {len(data)} 个客户标签",
        )