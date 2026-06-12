"""
AI 智能客服系统 - 客户管理 Tool

管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "update", "add_tag", "remove_tag", "list_tags", "create_tag", "update_tag", "delete_tag"}


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
        "客户管理工具，支持查询客户列表、客户详情、更新客户档案、管理客户标签。"
        "当需要查看客户信息、编辑客户资料、管理客户标签时使用。"
    )

    # admin、agent、tenant_admin 可使用
    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除客户/标签
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
                "description": "客户 ID（detail/update/add_tag/remove_tag 时必填）",
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
                "description": "更新数据（update 时必填），如 {\"name\": \"...\", \"phone\": \"...\"}",
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
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
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
                )

        except Exception as e:
            logger.error(f"[customer-manage] Error: action={action}, error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="客户管理操作失败，请稍后重试",
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
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        customers = []
        for record in records:
            customers.append({
                "id": record.get("id"),
                "name": record.get("name"),
                "phone": record.get("phone"),
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
            )

        data = response.get("data", {})
        logger.info(f"[customer-manage] Detail customer_id={customer_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"客户【{data.get('name', '')}】的详细信息",
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
            )

        if not data:
            return ToolResult(
                success=False,
                error="缺少更新数据",
                message="更新客户档案时必须提供更新数据（data）",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/customers/{customer_id}",
            json_data=data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"客户档案更新失败：{error_msg}",
            )

        logger.info(f"[customer-manage] Updated customer_id={customer_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"customer_id": customer_id},
            message="客户档案已更新",
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
            )
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="添加标签时必须提供标签 ID（tag_id）",
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
            )
        if not tag_id:
            return ToolResult(
                success=False,
                error="缺少标签 ID",
                message="移除标签时必须提供标签 ID（tag_id）",
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
            )

        logger.info(f"[customer-manage] Deleted tag {tag_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"tag_id": tag_id},
            message="标签已删除",
        )
