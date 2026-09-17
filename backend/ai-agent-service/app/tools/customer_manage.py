"""
AI 智能客服系统 - 客户管理 Tool

管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。
"""

from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "update", "add_tag", "remove_tag", "list_tags", "create_tag", "update_tag", "delete_tag"}

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
        "【触发】用户问'客户''顾客''VIP''客户档案''客户标签''给XX打标签''查XX电话'时调用。【前置】支持 action: list/detail/update/add_tag/remove_tag/list_tags/create_tag/update_tag/delete_tag。list 可按 keyword 搜索。detail 需要 customer_id。写操作需确认。【反例】查客户的历史订单用 order_query(customer_phone=XX)，不要用本工具。【标注】WRITE(update/add_tag/remove_tag) — 删除标签/合并客户需二次确认"
    )
    allowed_roles = ["admin", "agent", "tenant_admin", "operator"]

    read_only = False
    destructive = True   # 可删除客户/标签
    read_only_actions = {"list", "detail", "list_tags"}  # 只读 action 免确认拦截
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（客户列表）/ detail（客户详情）/ update（更新档案）/ add_tag（添加标签）/ remove_tag（移除标签）/ list_tags（标签列表）/ create_tag（创建标签）/ update_tag（更新标签）/ delete_tag（删除标签）",
                "enum": ["list", "detail", "update", "add_tag", "remove_tag", "list_tags", "create_tag", "update_tag", "delete_tag"],
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
            "data": {
                "type": "object",
                "description": (
                    "更新数据（update 时必填），key 必须是客户档案真实可写字段："
                    "wechatNickname（客户姓名）/ phone / gender / regionProvince / regionCity / "
                    "regionDistrict / vipLevel / customerStatus / agentNotes（备注）/ tags / customFields。"
                    "客户实体没有 name 列，严禁下发 name/nickname/realName（工具会翻成 wechatNickname）；"
                    "其它字段一律报错不落库"
                ),
            },
            "tag_id": {
                "type": "string",
                "description": "标签 ID（add_tag/remove_tag/update_tag/delete_tag 时必填）",
            },
            "name": {
                "type": "string",
                "description": "标签名称（create_tag/update_tag 时必填）",
            },
            "color": {
                "type": "string",
                "description": "标签颜色（create_tag/update_tag 时可选）",
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
            elif action == "update":
                return await self._update_customer(context, customer_id, data)
            elif action == "add_tag":
                return await self._add_tag(context, customer_id, tag_id)
            elif action == "remove_tag":
                return await self._remove_tag(context, customer_id, tag_id)
            elif action == "list_tags":
                return await self._list_tags(context)
            elif action == "create_tag":
                return await self._create_tag(context, name, color)
            elif action == "update_tag":
                return await self._update_tag(context, tag_id, name, color)
            elif action == "delete_tag":
                return await self._delete_tag(context, tag_id)
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
            return ToolResult(
                success=False,
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
            return ToolResult(
                success=False,
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

    async def _update_customer(
        self,
        context: ToolContext,
        customer_id: Optional[str],
        data: Optional[Dict[str, Any]],
    ) -> ToolResult:
        """更新客户档案"""
        if not customer_id:
            return ToolResult(
                success=False,
                error="缺少客户 ID",
                message="更新客户档案时必须提供客户 ID（customer_id）",
                suggestion="缺少 customer_id，请先用 customer_manage 的 list 操作确认客户后再重试",
            )

        if not data:
            return ToolResult(
                success=False,
                error="缺少更新数据",
                message="更新客户档案时必须提供更新数据（data）",
                suggestion="缺少 data，请把要修改的字段（如 remark、phone）放进 data 中重试",
            )

        # 归一化为实体真实列名 + 白名单校验：不可写字段显式报错，绝不静默忽略/部分写入（#3551）
        payload, rejected = normalize_update_data(data)
        if rejected:
            return ToolResult(
                success=False,
                error=f"不支持的更新字段: {'、'.join(rejected)}",
                message=f"客户档案未做任何修改：{'、'.join(rejected)} 不是可更新字段",
                suggestion=(
                    f"客户档案可更新字段：{'、'.join(sorted(WRITABLE_FIELDS))}"
                    "（客户姓名字段名为 wechatNickname）"
                ),
            )

        # craftMode 是枚举列：非法值服务端会 400 拒绝（#4115），本层提前拦下并给出可行动提示
        # （不发起注定失败的写请求，也不让用户看到「更新失败」这种无信息量的回执）
        craft_mode = payload.get("craftMode")
        if craft_mode is not None and craft_mode not in CRAFT_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 craftMode: {craft_mode}",
                message=f"客户档案未做任何修改：craftMode={craft_mode!r} 不是合法值",
                suggestion=(
                    "craftMode 只能是 standard（跟随企业固定工艺）/ economy（主动省料）/ "
                    "self_quoted（自报用料）之一；请改用合法值重试，其余字段可同时提交"
                ),
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/customers/{customer_id}",
            json_data=payload,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"客户档案更新失败：{error_msg}",
                suggestion="请先用 customer_manage 的 detail 操作读取当前档案，核对字段后再重试；不要改成其它客户",
            )

        updated_fields = sorted(payload.keys())
        logger.info(
            f"[customer-manage] Updated customer_id={customer_id} fields={updated_fields} "
            f"| tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"customer_id": customer_id, "updated_fields": updated_fields},
            message=f"客户档案已更新：{'、'.join(updated_fields)}",
        )

    async def _add_tag(
        self,
        context: ToolContext,
        customer_id: Optional[str],
        tag_id: Optional[str],
    ) -> ToolResult:
        """给客户添加标签"""
        if not customer_id:
            return ToolResult(
                success=False,
                error="缺少客户 ID",
                message="添加标签时必须提供客户 ID（customer_id）",
                suggestion="缺少 customer_id，请先用 customer_manage 的 list 操作搜到客户后重试",
            )
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="添加标签时必须提供标签 ID（tag_id）",
                suggestion="缺少 tag_id，请先用 customer_manage 的 list_tags 操作取到标签 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/customers/{customer_id}/tags/{tag_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"添加标签失败：{error_msg}",
                suggestion="请先用 customer_manage 的 list_tags 操作确认标签仍在，再重新执行添加标签",
            )

        logger.info(f"[customer-manage] Added tag {tag_id} to customer {customer_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"customer_id": customer_id, "tag_id": tag_id},
            message="标签已添加",
        )

    async def _remove_tag(
        self,
        context: ToolContext,
        customer_id: Optional[str],
        tag_id: Optional[str],
    ) -> ToolResult:
        """移除客户标签"""
        if not customer_id:
            return ToolResult(
                success=False,
                error="缺少客户 ID",
                message="移除标签时必须提供客户 ID（customer_id）",
                suggestion="缺少 customer_id，请先用 customer_manage 的 list 操作搜到客户后重试",
            )
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="移除标签时必须提供标签 ID（tag_id）",
                suggestion="缺少 tag_id，请先用 customer_manage 的 list_tags 操作取到标签 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/customers/{customer_id}/tags/{tag_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"移除标签失败：{error_msg}",
                suggestion="请先用 customer_manage 的 detail 操作确认该客户确实带有此标签，再重新执行移除",
            )

        logger.info(f"[customer-manage] Removed tag {tag_id} from customer {customer_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"customer_id": customer_id, "tag_id": tag_id},
            message="标签已移除",
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
            return ToolResult(
                success=False,
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

    async def _create_tag(
        self,
        context: ToolContext,
        name: Optional[str],
        color: Optional[str],
    ) -> ToolResult:
        """创建客户标签"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少标签名称",
                message="创建标签时必须提供标签名称（name）",
                suggestion="缺少标签名称 name，请向用户询问要创建的标签名称后重试",
            )

        json_data: Dict[str, Any] = {"name": name}
        if color:
            json_data["color"] = color

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/customer-tags",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建标签失败：{error_msg}",
                suggestion="请先用 customer_manage 的 list_tags 操作确认是否已有同名标签，再改用 update_tag 或换一个名称",
            )

        data = response.get("data", {})
        logger.info(f"[customer-manage] Created tag: name={name} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"标签【{name}】已创建",
        )

    async def _update_tag(
        self,
        context: ToolContext,
        tag_id: Optional[str],
        name: Optional[str],
        color: Optional[str],
    ) -> ToolResult:
        """更新客户标签"""
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="更新标签时必须提供标签 ID（tag_id）",
                suggestion="缺少 tag_id，请先用 customer_manage 的 list_tags 操作取到标签 ID 后重试",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if color:
            json_data["color"] = color

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新标签时必须提供名称（name）或颜色（color）",
                suggestion="缺少更新内容，请让用户给出新的标签名称或颜色后重试",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/customer-tags/{tag_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新标签失败：{error_msg}",
                suggestion="请先用 customer_manage 的 list_tags 操作确认标签仍在，再重新执行更新",
            )

        logger.info(f"[customer-manage] Updated tag {tag_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"tag_id": tag_id},
            message="标签已更新",
        )

    async def _delete_tag(
        self,
        context: ToolContext,
        tag_id: Optional[str],
    ) -> ToolResult:
        """删除客户标签"""
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="删除标签时必须提供标签 ID（tag_id）",
                suggestion="缺少 tag_id，请先用 customer_manage 的 list_tags 操作取到标签 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/customer-tags/{tag_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除标签失败：{error_msg}",
                suggestion="请先用 customer_manage 的 list_tags 操作确认该标签未被其它客户占用，再重新执行删除",
            )

        logger.info(f"[customer-manage] Deleted tag {tag_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"tag_id": tag_id},
            message="标签已删除",
        )
