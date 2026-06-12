"""
AI 智能客服系统 - 快捷回复模板管理 Tool

管理快捷回复模板，包括查询列表、分类列表、创建、更新、删除模板。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "categories", "create", "update", "delete"}


class QuickReplyManageTool(BaseTool):
    """快捷回复模板管理 Tool

    管理快捷回复模板：查询列表、获取分类、创建/更新/删除模板。

    使用场景：
    - 查看快捷回复模板列表
    - 获取所有快捷回复分类
    - 创建新的快捷回复模板
    - 更新已有的快捷回复模板
    - 删除不需要的快捷回复模板
    """

    name = "quick_reply_manage"
    description = (
        "快捷回复模板管理工具，支持查询模板列表、获取分类列表、创建/更新/删除快捷回复模板。"
        "当需要管理客服快捷回复模板（如添加话术、修改模板内容、查看分类）时使用。"
    )

    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除快捷回复模板
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（模板列表）/ categories（分类列表）/ create（创建）/ update（更新）/ delete（删除）",
                "enum": ["list", "categories", "create", "update", "delete"],
            },
            "reply_id": {
                "type": "string",
                "description": "快捷回复模板 ID（update/delete 时必填）",
            },
            "title": {
                "type": "string",
                "description": "模板标题（create 时必填，update 时可选）",
            },
            "category": {
                "type": "string",
                "description": "模板分类（create 时必填，update/list 时可选）",
            },
            "content": {
                "type": "string",
                "description": "模板内容（create 时必填，update 时可选）",
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词（list 时可选）",
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
        reply_id: Optional[str] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
        content: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 10,
    ) -> ToolResult:
        """执行快捷回复模板管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行快捷回复管理操作",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "list":
                return await self._list_replies(context, page, size, category, keyword)
            elif action == "categories":
                return await self._get_categories(context)
            elif action == "create":
                return await self._create_reply(context, title, category, content)
            elif action == "update":
                return await self._update_reply(context, reply_id, title, category, content)
            elif action == "delete":
                return await self._delete_reply(context, reply_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"[quick-reply-manage] Failed: action={action}, error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="快捷回复管理操作失败，请稍后重试",
            )

    async def _list_replies(
        self,
        context: ToolContext,
        page: int,
        size: int,
        category: Optional[str],
        keyword: Optional[str],
    ) -> ToolResult:
        """查询快捷回复模板列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if category:
            params["category"] = category
        if keyword:
            params["keyword"] = keyword

        logger.info(
            f"[quick-reply-manage] List: category={category}, keyword={keyword}, "
            f"page={page}, size={size} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/quick-replies",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询快捷回复列表失败：{error_msg}",
            )

        data = response.get("data", {}) or {}
        records = data.get("items") or data.get("records") or []
        total = data.get("total", len(records))

        return ToolResult(
            success=True,
            data={
                "items": records,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"共找到 {total} 个快捷回复模板",
        )

    async def _get_categories(self, context: ToolContext) -> ToolResult:
        """获取所有快捷回复分类"""
        logger.info(f"[quick-reply-manage] Categories | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/quick-replies/categories",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取快捷回复分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"categories": response.get("data", [])},
            message="已获取快捷回复分类列表",
        )

    async def _create_reply(
        self,
        context: ToolContext,
        title: Optional[str],
        category: Optional[str],
        content: Optional[str],
    ) -> ToolResult:
        """创建快捷回复模板"""
        if not title:
            return ToolResult(
                success=False,
                error="缺少模板标题",
                message="创建快捷回复时必须提供 title",
            )
        if not category:
            return ToolResult(
                success=False,
                error="缺少模板分类",
                message="创建快捷回复时必须提供 category",
            )
        if not content:
            return ToolResult(
                success=False,
                error="缺少模板内容",
                message="创建快捷回复时必须提供 content",
            )

        logger.info(
            f"[quick-reply-manage] Create: title={title}, category={category} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/quick-replies",
            json_data={"title": title, "category": category, "content": content},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建快捷回复失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"快捷回复「{title}」创建成功",
        )

    async def _update_reply(
        self,
        context: ToolContext,
        reply_id: Optional[str],
        title: Optional[str],
        category: Optional[str],
        content: Optional[str],
    ) -> ToolResult:
        """更新快捷回复模板"""
        if not reply_id:
            return ToolResult(
                success=False,
                error="缺少模板 ID",
                message="更新快捷回复时必须提供 reply_id",
            )

        json_data: Dict[str, Any] = {}
        if title:
            json_data["title"] = title
        if category:
            json_data["category"] = category
        if content:
            json_data["content"] = content

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新快捷回复时至少提供 title、category 或 content 之一",
            )

        logger.info(
            f"[quick-reply-manage] Update: reply_id={reply_id}, fields={list(json_data.keys())} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/quick-replies/{reply_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新快捷回复失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"reply_id": reply_id, **json_data},
            message=f"快捷回复已更新",
        )

    async def _delete_reply(self, context: ToolContext, reply_id: Optional[str]) -> ToolResult:
        """删除快捷回复模板"""
        if not reply_id:
            return ToolResult(
                success=False,
                error="缺少模板 ID",
                message="删除快捷回复时必须提供 reply_id",
            )

        logger.info(f"[quick-reply-manage] Delete: reply_id={reply_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/quick-replies/{reply_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除快捷回复失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"reply_id": reply_id},
            message="快捷回复已删除",
        )
