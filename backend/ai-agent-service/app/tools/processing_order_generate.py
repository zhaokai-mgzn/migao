"""
AI 智能客服系统 - 加工单生成 Tool（issue #3340）

把已确认、且**有需要报工的作业**（含加工项 **或** 有卖布行）的订单批量生成作业单（快照固化五要素 + options，不含销售价；含加工项 / 混合单 ⇒ 加工单，全是卖布行 ⇒ 出库作业单），
并联动订单 confirmed → producing。幂等：同一订单已有加工单时拒绝重复生成。

🔴 **直派全关（issue #7507 → #7634，用户裁定「统一走智能派单」）**：本入口在服务端对**所有**订单
逐单拒绝（`DIRECT_DISPATCH_POOL_REQUIRED`）——正确去处是后台「智能派单」页（同料合并领料更省料）；
**待付款 / 加急**同样在派单页派（加急走插队区单派），不再有直派例外。⚠️ B 端 skill 自 #5247 起已只读，
本工具当前**无 skill 绑定**（模型不可达）；文案同步是为了下次恢复写能力时不再教错。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProcessingOrderGenerateTool(BaseTool):
    """生成加工单 Tool"""

    name = "processing_order_generate"
    description = (
        "【触发】用户说'生成加工单''把这几单发加工''今天确认的订单都生成加工单'时调用。"
        "【参数】需要 order_ids（订单 ID 或订单号列表）。"
        "【语义】已确认的订单可生成：含加工项（或混合）⇒ 加工单，卖布单（按米卖布、行上没有加工项）⇒ 出库作业单"
        "（卖布单同样要经裁剪 → 打包两道工序并由工人报工，同样必须先生成才能发货）；生成后订单进入生产中（producing）。"
        "🔴 统一走「智能派单」：不要在对话里直派（服务端对**所有**订单逐单拒绝并指路派单页）；"
        "待付款（pending）与加急（is_urgent=true）订单同样在派单页派 —— 不再有直派例外。"
        "【反例】查询加工单用 processing_order_query；更新加工单状态用 processing_order_update。"
        "【标注】WRITE — 批量生成前必须列出订单清单并二次确认"
    )

    # 权限码（admin-api 目录）：ProcessingOrderController 类级
    # `@RequirePermission("processing:update")`（生成/发加工/取消加工单）。
    required_permissions = ["processing:update"]
    read_only = False
    # 已恢复接入（issue #4196：反转 #3917 的下线决策）：registry 注册 + order skill 工具绑定
    # + prompts/order.md 操作指引三处齐备；概念区分口径仍在（防混淆守则）。
    # requires_confirmation=True（issue #3594 写工具确认门禁分类审计）：
    # 本工具是**真实业务写**——批量创建加工单（快照固化五要素）并把订单 confirmed
    # 推进到 producing（加工方据此排产），副作用不可忽略。此前 destructive /
    # requires_confirmation 均为 False ⇒ 完全不经 `_requires_confirmation` 代码门禁，
    # 只靠 prompt 文本铁律（间接提示注入面，审计 07 P0-L1），且与**三处已声明**的
    # 二次确认要求自相矛盾：本文件 description「批量生成前必须列出订单清单并二次确认」、
    # references/prompts/order.md「批量前先确认」、order_skill.py「写操作 confirm」。
    # 不标 destructive：加工单可由 processing_order_update(action=cancel) 取消、订单回退
    # 已确认（可逆），故按「非 destructive 但高风险写操作」口径标记。
    # 所属 skill `order` 已绑定 interact + validate_input ⇒ 确认卡路径可达，不会出现
    # 「被拦截却调不到 interact」的不可执行指令（issue #3317）。
    requires_confirmation = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "order_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "订单 ID 或订单号（ORD-xxx）列表，支持批量",
            },
        },
        "required": ["order_ids"],
    }

    async def execute(self, context: ToolContext, order_ids: List[str]) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False,
                error="权限不足",
                message="您没有权限生成加工单",
                suggestion="请改用只读查询（processing_order_query）向用户展示加工单；如需生成请先确认当前账号权限",
            )

        if not order_ids or not isinstance(order_ids, list) or len(order_ids) == 0:
            return ToolResult(
                success=False, error="缺少订单列表",
                message="请提供要生成加工单的订单 ID 或订单号",
                suggestion="请先从订单列表或查询结果中获取订单号，格式如 ORD-20260718-0001",
            )
        if len(order_ids) > 100:
            return ToolResult(
                success=False, error="批量超限",
                message="单次最多生成 100 个加工单，请分批操作",
                suggestion="单次最多 100 个订单，请按用户指定的范围分批生成（先处理前 100 个）",
            )

        try:
            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/processing-orders/generate",
                json_data={"orderIds": order_ids},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Processing order generate error: {e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="生成加工单失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "生成加工单失败") if isinstance(error_info, dict) else str(error_info)
            return admin_api_failure(response,
                error=error_msg,
                message=f"生成加工单失败：{error_msg}",
                suggestion="请确认订单已确认，且有需要报工的作业（含加工项，或有卖布行）；已有作业单的订单不可重复生成（卖布单生成的是出库作业单）",
            )

        results = response.get("data", []) or []
        ok_count = sum(1 for r in results if r.get("success"))
        fail_msgs = [r.get("message") for r in results if not r.get("success")]
        logger.info(f"[processing_order_generate] done: total={len(results)}, ok={ok_count}")

        if fail_msgs:
            return ToolResult(
                success=ok_count > 0,
                data={"results": results},
                message=f"加工单生成完成 {ok_count}/{len(results)} 个"
                        + (f"；失败原因：{'；'.join(fail_msgs[:3])}" if fail_msgs else ""),
            )
        return ToolResult(
            success=True,
            data={"results": results},
            message=f"已生成 {ok_count} 个加工单，订单已进入生产中"
                    + ("，可让加工方开始安排" if ok_count else ""),
        )
