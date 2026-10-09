"""
AI 智能客服系统 - 工艺配置读面查询 Tool（issue #4923 缺口登记：生产域 6 个零覆盖读端点）

只读六个 action（全部是 `ProductionController` 的 **GET**，路径逐条字面量写在调用点）：

| action | 端点 |
|---|---|
| `routing_gaps`      | `GET /api/admin/production/routing-gaps` |
| `route_signals`     | `GET /api/admin/production/route-signals` |
| `routing_anomalies` | `GET /api/admin/production/orders/routing-anomalies` |
| `fee_combinations`  | `GET /api/admin/production/processing-fee-combinations` |
| `fee_gaps`          | `GET /api/admin/production/processing-fee-gaps` |
| `stuck_points`      | `GET /api/admin/production/stuck-points`（可选 `processing_order_id`） |

⚠️ 本工具**不收录** `operations` / `routings` —— 那两个读面已有
`app/tools/operation_catalog_query.py`（`VALID_ACTIONS={"operations","routings"}`）；
收进来会造成**重复工具面**（同一个端点两把工具 ⇒ 模型选谁都是对、覆盖矩阵却各算一半）。

🔴 **权限码不一致（issue #4923 现场复核读数，如实登记、本包不改权限面）**：
`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java` 的六个端点在
**生效码**上分成三档（`PermissionInterceptor.resolveRequirePermission`：方法级优先、其次类级）：

- `production:view`（方法级）：`processing-fee-combinations`（该注解写在 `@GetMapping` **之前**，
  解析器按「向前回看注解区」照样认得）、`processing-fee-gaps` —— issue #5699 的 P4 收敛；
- `processing:manage`（方法级，**写码**）：`orders/routing-anomalies`；
- `order:list`（**类级**回退，本类 `@RequirePermission("order:list")`，无方法级注解）：
  `routing-gaps` / `route-signals` / `stuck-points`。

本工具声明的码 = 生产域**读**码 `production:view`（只读工具不得只持写码/订单读码 —— 那既是
`READ_WRITE_EXCEPTIONS` 要治的粒度债，也会把只持读码的岗位挡在门外）。**端点侧的三个码不是本包
的授权动作**（改授权面属产品裁定）⇒ 逐条读数与差量已写进 PR body，并由
`backend/ai-agent-service/tests/test_tools_craft_config_query.py` 的
`TestControllerPermissionParity` 把它**钉成会红的判据**（改任一码 ⇒ 该测试红）。

判据面锚（不写行号，用符号）：本文件 ⇄ `tool_http_attribution.JavaEndpointIndex`（静态归属）
⇄ `ProductionController` 的 `@GetMapping` 路径。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

VALID_ACTIONS = {
    "routing_gaps",
    "route_signals",
    "routing_anomalies",
    "fee_combinations",
    "fee_gaps",
    "stuck_points",
}


class CraftConfigQueryTool(BaseTool):
    """工艺配置读面查询 Tool（只读）"""

    name = "craft_config_query"
    description = (
        "【触发】用户问'工艺路线缺了哪些''哪些工序没进路线''信号映射''部位工艺是猜的还是填的'"
        "'路线来源异常''加工费组合有哪些''哪些组合没定价''加工费缺口''卡在哪''哪个工序卡住了'"
        "'没开工等着的有哪些'时调用。"
        "【参数】action 必填：routing_gaps（路线缺口：未进路线的活跃工序 + 没有路线的信号组合）/ "
        "route_signals（信号映射兜底表）/ routing_anomalies（路线来源=默认或部分的订单）/ "
        "fee_combinations（加工费组合定价表）/ fee_gaps（订单里出现过但没定价的组合）/ "
        "stuck_points（卡点：没开工且等待超阈值；可选 processing_order_id 只看某张加工单）。"
        "【反例】工序库目录 / 工艺路线模板用 operation_catalog_query（operations / routings）；"
        "算料参数用 craft_calc_config_query；加工项目录用 processing_item_query；"
        "某张订单做到哪道工序用 production_progress_query。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：生产域**读**码 `production:view`，与侧边栏「企业基础设置 → 工艺与路线」节点同码
    # （issue #5291 设立）。⚠️ 本工具六个端点里有三个的**端点侧**生效码不是本码（#4923 现场读数，
    # 见模块 docstring 与测试 `TestControllerPermissionParity`）⇒ 本码是**本包声明的读口径**，
    # 端点收敛属产品裁定、不在本包。
    required_permissions = ["production:view"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：routing_gaps（路线缺口）/ route_signals（信号映射）/ "
                    "routing_anomalies（路线来源异常订单）/ fee_combinations（加工费组合定价）/ "
                    "fee_gaps（加工费缺口）/ stuck_points（卡点）—— 均为只读"
                ),
                "enum": [
                    "routing_gaps",
                    "route_signals",
                    "routing_anomalies",
                    "fee_combinations",
                    "fee_gaps",
                    "stuck_points",
                ],
            },
            "processing_order_id": {
                "type": "string",
                "description": "仅 action=stuck_points 时可选：只看这一张加工单的卡点；不传 = 本租户全部活跃加工单",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        processing_order_id: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询工艺配置的缺口与卡点",
                suggestion="请联系管理员为您开通「企业基础设置 → 工艺与路线」查看权限后重试",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            client = get_admin_api_client()
            # ⚠️ 路径必须**字面量写在调用点**：`tests/test_tool_payload_backend_contract.py` 的
            # 「payload 调用点必须静态归属到端点」门禁 + 权限对账（
            # `tests/unit_ci_workflows/test_agent_permission_parity.py`）都靠静态可渲染
            # （抽成常量/字典查表会让调用点脱离射程 ⇒ 本工具变成「没有端点」⇒ 判据 1/2 红，
            #   `operation_catalog_query.py` 的注释里记着同一次实测）。
            if action == "routing_gaps":
                response = await client.get(
                    "/api/admin/production/routing-gaps",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "route_signals":
                response = await client.get(
                    "/api/admin/production/route-signals",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "routing_anomalies":
                response = await client.get(
                    "/api/admin/production/orders/routing-anomalies",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "fee_combinations":
                response = await client.get(
                    "/api/admin/production/processing-fee-combinations",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "fee_gaps":
                response = await client.get(
                    "/api/admin/production/processing-fee-gaps",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            else:
                # ⚠️ 两个分支各写一份 literal `params` 字典（不写 `params = {...} if x else None`）：
                # `params` 是 payload 载体（`tool_http_attribution.PAYLOAD_KWARGS`）⇒ 用条件表达式
                # 拼出来的键**静态不可解析**，`tests/test_tool_payload_backend_contract.py` 会判
                # 「未登记的动态构造」红（实测踩到过）。两份字面量让键恒可静态归属。
                if processing_order_id:
                    response = await client.get(
                        "/api/admin/production/stuck-points",
                        tenant_id=context.tenant_id,
                        user_id=context.user_id,
                        params={"processing_order_id": processing_order_id},
                    )
                else:
                    response = await client.get(
                        "/api/admin/production/stuck-points",
                        tenant_id=context.tenant_id,
                        user_id=context.user_id,
                    )
        except Exception as e:
            logger.error(f"Craft config query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="工艺配置查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message=f"工艺配置查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请先确认该租户是否已配置工艺路线与加工费组合",
            )

        data: Dict[str, Any] = response.get("data") or {}
        logger.info(f"[craft_config_query] action={action} done")
        # ⚠️ 成功文案必须**字面量内联在构造点**（不查模块级字典）：运行期文本若经**局部变量 /
        # 容器索引**传入，`tests/unit_ci_workflows/test_dead_capability_meta_guard.py` 的
        # `test_surfaces_are_fail_closed` 解析不到字面量 ⇒ 该文案进 `unresolved_runtime`
        # ⇒ 判据静默免检（实测踩到：`craft_config_query.message`）。该文件的出口写得很明确：
        # 「把文本**内联**到构造点，或扩展本判据的解析（**不要**登记豁免）」。
        if action == "routing_gaps":
            return ToolResult(success=True, data=data, message="工艺路线缺口如下")
        if action == "route_signals":
            return ToolResult(success=True, data=data, message="信号映射如下")
        if action == "routing_anomalies":
            return ToolResult(success=True, data=data, message="路线来源异常订单如下")
        if action == "fee_combinations":
            return ToolResult(success=True, data=data, message="加工费组合定价如下")
        if action == "fee_gaps":
            return ToolResult(success=True, data=data, message="加工费缺口如下")
        return ToolResult(success=True, data=data, message="卡点（没开工）如下")
